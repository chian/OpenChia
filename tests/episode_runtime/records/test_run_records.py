"""Maintained record behavior on the real RunStore, without a model or executor."""

import pytest

from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunTerminalStatus
from episode_runtime.protocol import episode_id_for_path
from episode_runtime.records.index import RunRecordIndex
from episode_runtime.records.runs import RunRecord
from episode_runtime.store import RunStore


def started(runs, registration, sequence=0):
    path = [{"grain": "inquiry", "key": registration.run_id.value}]
    return runs.append_event(
        run_id=registration.run_id,
        origin=RunEventOrigin.WORKER,
        sender_sequence=sequence,
        kind=RunEventKind.EPISODE_STARTED,
        episode_id=episode_id_for_path(registration.run_id, path),
        payload={"episode_path": path},
    )


def test_record_survives_reopen_and_inspection_never_reconstructs_audit(run_store, monkeypatch):
    runs, registration, _ = run_store
    before = runs.read_run_record(registration.run_id)
    assert before["index_status"] == "current"
    assert before["record"]["activity"]["events"] == 0
    event = started(runs, registration)
    evidence = runs.finalize_run(
        run_id=registration.run_id, origin=RunEventOrigin.HOST, sender_sequence=0,
        terminal_status=RunTerminalStatus.INTERRUPTED,
        typed_status={"reason": "External interruption is not completion", "private_detail": "not in overview"},
    )
    reopened = RunStore(runs.root)

    def no_audit(*args, **kwargs):
        raise AssertionError("routine record inspection must not reconstruct audit history")

    monkeypatch.setattr(reopened, "_load_event_chain_locked", no_audit)
    monkeypatch.setattr(reopened, "read_evidence", no_audit)
    view = reopened.read_run_record(registration.run_id)
    record = RunRecord.from_record(view["record"])
    assert view["index_status"] == "current"
    assert record.run_id == event.run_id.value
    assert record.registration_hash == registration.registration_hash.value
    assert record.activity.events == evidence.event_count
    assert record.activity.invocations_started == 1
    assert record.terminal_status == "interrupted"
    assert record.evidence_ref.artifact_id == evidence.evidence_id.value
    assert record.through_event.content_hash == evidence.head_event_hash.value
    assert "private_detail" not in view["record"]
    assert "typed_status" not in view["record"]


def test_interrupted_projection_is_visible_and_refresh_does_not_execute(run_store, monkeypatch):
    runs, registration, _ = run_store

    def interrupted(*args, **kwargs):
        raise OSError("injected interruption after source commit")

    from episode_runtime.store import RunStoreNotFound

    startup = RunStore(runs.root.parent / "unstarted")
    with monkeypatch.context() as patch:
        patch.setattr(RunRecordIndex, "_replace", interrupted)
        with pytest.raises(OSError):
            startup.publish_registration(registration)
    with pytest.raises(RunStoreNotFound):
        startup.read_registration(registration.run_id)
    startup.publish_registration(registration)
    assert startup.read_run_record(registration.run_id)["index_status"] == "current"

    with monkeypatch.context() as patch:
        patch.setattr(RunRecordIndex, "_replace", interrupted)
        with pytest.raises(OSError, match="after source commit"):
            started(runs, registration)
    before = runs.read_committed_prefix(registration.run_id)
    view = runs.read_run_record(registration.run_id)
    assert view["index_status"] == "behind"
    assert view["required_action"] == "refresh_record"
    assert view["record"]["activity"]["events"] == 0
    inventory = runs.read_inventory(registration.run_id, {})
    assert inventory["index_status"] == "behind"
    assert not inventory["items"]  # Inserted fact rolled back with failed summary publication.
    repaired = runs.refresh_run_record(registration.run_id)
    assert repaired["index_status"] == "current"
    assert repaired["record"]["activity"]["events"] == len(before)
    assert len(runs.read_inventory(registration.run_id, {})["items"]) == len(before)
    assert runs.read_committed_prefix(registration.run_id) == before
    assert runs.refresh_run_record(registration.run_id) == repaired

    with monkeypatch.context() as patch:
        patch.setattr(runs, "_publish_terminal_artifacts_locked", interrupted)
        with pytest.raises(OSError, match="after source commit"):
            runs.finalize_run(
                run_id=registration.run_id, origin=RunEventOrigin.HOST, sender_sequence=0,
                terminal_status=RunTerminalStatus.INTERRUPTED,
                typed_status={"reason": "test interruption"},
            )
    pending = runs.read_run_record(registration.run_id)
    assert pending["index_status"] == "publication_pending"
    assert pending["record"]["terminal_status"] == "interrupted"
    assert pending["record"]["evidence_ref"] is None
    evidence = runs.complete_terminal_publication(registration.run_id)
    complete = runs.read_run_record(registration.run_id)
    assert complete["index_status"] == "current"
    assert complete["record"]["evidence_ref"]["artifact_id"] == evidence.evidence_id.value
    assert complete["record"]["terminal_status"] == "interrupted"


def test_inventory_pins_prefix_and_selector_without_reading_audit(run_store, monkeypatch, capsys):
    import json
    from method_loop.identities import UnitRef
    from openchia_cli.episode_test_command import main

    runs, registration, _ = run_store
    root = [{"grain": "root", "key": registration.run_id.value}]
    paths = [root, [*root, {"grain": "child", "key": "a"}], [*root, {"grain": "child", "key": "b"}]]
    episodes = [episode_id_for_path(registration.run_id, path) for path in paths]
    sequence = 0

    def emit(kind, episode, payload):
        nonlocal sequence
        event = runs.append_event(
            run_id=registration.run_id, origin=RunEventOrigin.WORKER,
            sender_sequence=sequence, kind=kind, episode_id=episode, payload=payload,
        )
        sequence += 1
        return event

    starts = []
    for episode, path in zip(episodes, paths):
        starts.append(emit(RunEventKind.EPISODE_STARTED, episode, {
            "episode_path": path, "request": {"private_input": "not returned in inventory"},
            "goal_view": {}, "goal_state_id": "initial", "initial_goal_state_id": "initial",
        }))
    first_page = runs.read_inventory(registration.run_id, {"limit": 1})
    assert first_page["next_query"] is not None
    first_unit = UnitRef(episodes[1].value, 0)
    observed = emit(RunEventKind.UNIT_COMPLETED, episodes[1], {
        "unit_ref": first_unit.as_record(), "unit_label": "check solution",
        "controller_input": {"private_output": "not returned"}, "controller_step": {},
    })
    first_unit_ref = {"run_id": registration.run_id.value, "event_id": observed.event_id.value, "content_hash": observed.event_hash.value}
    emit(RunEventKind.UNIT_COMPLETED, episodes[1], {
        "unit_ref": UnitRef(episodes[1].value, 1).as_record(), "unit_label": "later check",
    })
    emit(RunEventKind.EPISODE_COMPLETED, episodes[1], {"ended_by": "yield_stop", "end_reason": "", "units_consumed": 2})
    emit(RunEventKind.UNIT_COMPLETED, episodes[2], {
        "unit_ref": UnitRef(episodes[2].value, 2).as_record(), "unit_label": "missing predecessors",
    })
    runs.finalize_run(
        run_id=registration.run_id, origin=RunEventOrigin.HOST, sender_sequence=0,
        terminal_status=RunTerminalStatus.INTERRUPTED, typed_status={"reason": "root unfinished"},
    )
    reopened = RunStore(runs.root)

    def no_audit(*args, **kwargs):
        raise AssertionError("inventory cannot reconstruct audit history")

    monkeypatch.setattr(RunStore, "_load_event_chain_locked", no_audit)
    monkeypatch.setattr(RunStore, "read_evidence", no_audit)
    rows = list(first_page["items"])
    query = first_page["next_query"]
    while query is not None:
        page = reopened.read_inventory(registration.run_id, query)
        rows.extend(page["items"])
        assert page["through_event_ref"] == first_page["through_event_ref"]
        query = page["next_query"]
    assert [row["episode_id"] for row in rows] == [episode.value for episode in episodes]
    assert all(row["counts"]["units"] == 0 and row["completion"] is None for row in rows)
    current = reopened.read_inventory(registration.run_id, {})
    assert current["items"][1]["counts"]["units"] == 2
    assert current["items"][1]["completion"]["completion"]["ended_by"] == "yield_stop"
    assert current["items"][0]["completion"] is None  # Run interruption cannot invent completion.
    selected = dict(selected_episode_ids=[episodes[1].value], through_event_ref=first_unit_ref)
    units = reopened.read_inventory(registration.run_id, {"kind": "units"}, **selected)
    assert [row["unit_ref"] for row in units["items"]] == [first_unit.as_record()]
    assert units["items"][0]["event_ref"] == first_unit_ref
    assert units["items"][0]["has_controller_step"]
    from episode_runtime.testing_harness.recordings import event_reference

    first_prefix = units["items"][0]["reconstruction_prefix"]
    assert first_prefix["status"] == "located"
    assert first_prefix["through_event_ref"] == event_reference(starts[1])
    assert first_prefix["completed_units"] == 0
    later_units = reopened.read_inventory(registration.run_id, {
        "kind": "units", "episode_id": episodes[1].value,
    })["items"]
    later_prefix = later_units[1]["reconstruction_prefix"]
    assert later_prefix["through_event_ref"] == first_unit_ref
    assert later_prefix["completed_units"] == first_unit.unit_index + 1
    assert later_prefix["through_event_ref"] != later_units[1]["event_ref"]
    assert not later_prefix["restoration_verified"]
    missing = reopened.read_inventory(registration.run_id, {
        "kind": "units", "episode_id": episodes[2].value,
    })["items"][0]["reconstruction_prefix"]
    assert missing["status"] == "unavailable" and missing["through_event_ref"] is None
    assert missing["gap"] == "preceding_units_missing_or_inconsistent"
    with pytest.raises(ValueError, match="outside its recording selector"):
        reopened.read_inventory(registration.run_id, {"episode_id": episodes[2].value}, **selected)
    with pytest.raises(ValueError, match="exceeds its selected recording prefix"):
        reopened.read_inventory(registration.run_id, {"through_event_ref": current["through_event_ref"]}, **selected)
    with pytest.raises(ValueError, match="hash differs"):
        reopened.read_inventory(registration.run_id, {"through_event_ref": {**first_unit_ref, "content_hash": "sha256:" + "0" * 64}})
    assert main([
        "inventory", "--run-store", str(runs.root), "--run-id", registration.run_id.value,
        "--kind", "units", "--episode-id", episodes[1].value,
        "--through-event-ref", json.dumps(first_unit_ref),
    ]) == 0
    visible = json.loads(capsys.readouterr().out)
    assert visible["items"] == units["items"]
    assert "private_output" not in json.dumps(visible)
    assert "private_input" not in json.dumps(current)
