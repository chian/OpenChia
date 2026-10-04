"""Shared history over actual stores and typed intents, not live task acceptance.

Dispatch/intent records here are fixtures. No candidate, model or confinement
is exercised; these assertions cover indexed discovery and ownership only.
"""

import json

import pytest

from agent.duet_contracts import content_id, digest_record
from agent.duet_store import DuetStore
from episode_runtime.contracts import RunEventOrigin, RunTerminalStatus
from episode_runtime.records.experiments import put_data, put_record
from episode_runtime.testing.service import ExperimentService
from iterative_episode_refiner.records import Ref, RefinementRecord


@pytest.mark.parametrize(
    "intent_kind", ["ordinary", "evaluation_run", "measure_control_run"]
)
def test_shared_execution_history_keeps_intent_and_limits(
    run_store, tmp_path, monkeypatch, capsys, intent_kind
):
    from openchia_cli.episode_test_command import main

    runs, registration, _ = run_store
    duet_id = registration.duet_id.value
    artifacts_path = tmp_path / "history.db"
    with DuetStore(artifacts_path) as artifacts:
        artifacts.create_duet(
            duet_id=duet_id, identity={}, policy={}, state="specifying"
        )
        reference = put_data(
            artifacts, duet_id, "history_fixture", {"private": "not public context"}
        )
        if intent_kind == "ordinary":
            intent = put_data(
                artifacts,
                duet_id,
                "launch_intent",
                {
                    "registration_hash": registration.registration_hash.value,
                    "model_launch_id": "launch_fixture",
                    "configuration_hash": reference["content_hash"],
                },
            )
        else:
            campaign_id = content_id("campaign", {"fixture": intent_kind})

            def typed(kind, body):
                record = RefinementRecord(
                    kind, campaign_id, body, Ref.from_record(reference)
                )
                artifacts.put_artifact(
                    **record.ref.as_record(),
                    duet_id=duet_id,
                    kind=f"refinement.{kind}.v1",
                    revision=1,
                    record=record.as_record(),
                )
                return record.ref.as_record()

            if intent_kind == "evaluation_run":
                request = typed(
                    "evaluation",
                    {
                        "candidate_ref": reference,
                        "measure_ref": reference,
                        "check_keys": ["check_schedule"],
                        "input_refs": [reference],
                        "environment_ref": reference,
                        "harness_ref": reference,
                        "purpose": "acceptance",
                        "parent_operation_id": "validation_fixture",
                        "capability_ref": reference,
                    },
                )
                intent = typed(
                    intent_kind,
                    {
                        "request_ref": request,
                        "candidate_ref": reference,
                        "registration": registration.as_record(),
                        "build_receipt_ref": reference,
                    },
                )
            else:
                intent = typed(
                    intent_kind,
                    {
                        "proposal_ref": reference,
                        "grounding_ref": reference,
                        "control_ref": reference,
                        "registration": registration.as_record(),
                        "gap": None,
                    },
                )
        put_record(
            artifacts,
            "execution",
            run_id=registration.run_id.value,
            duet_id=duet_id,
            record={
                "schema_version": 1,
                "registration": registration.as_record(),
                "intent_ref": intent,
                "mode": "live_fresh",
                "context": None,
                "recording_ref": None,
                "scope": {
                    "kind": "workflow",
                    "entry_local_id": "root",
                    "included_local_ids": ["root"],
                    "children": "execute",
                },
            },
        )
        terminal = runs.finalize_run(
            run_id=registration.run_id,
            origin=RunEventOrigin.HOST,
            sender_sequence=0,
            terminal_status=RunTerminalStatus.INTERRUPTED,
            typed_status={"reason": "fixture interruption is not completion"},
        )

        def no_audit(*args, **kwargs):
            raise AssertionError(
                "shared history must not reconstruct audit or scan a campaign"
            )

        monkeypatch.setattr(type(runs), "read_evidence", no_audit)
        monkeypatch.setattr(type(runs), "_load_event_chain_locked", no_audit)
        monkeypatch.setattr(artifacts, "events", no_audit)
        query = {"kind": "executions", "limit": 1}
        page = ExperimentService.history(artifacts, runs, duet_id=duet_id, query=query)
        assert len(page["items"]) == 1 and page["next_query"] is None
        row = page["items"][0]
        assert row["run_id"] == registration.run_id.value
        assert row["execution_status"] == "interrupted"
        assert (
            row["candidate_verdict"] == "unmeasured" and row["measurement_ref"] is None
        )
        assert (
            row["run_record"]["record"]["evidence_ref"]["artifact_id"]
            == terminal.evidence_id.value
        )
        assert row["intent_ref"] == intent
        if intent_kind == "ordinary":
            assert row["intent"]["relationship"] == "ordinary_run"
            assert row["intent"]["model_launch_id"] == "launch_fixture"
        else:
            assert row["intent"]["relationship"] == "refinement"
            assert row["intent"]["campaign_id"] == campaign_id.value
            if intent_kind == "evaluation_run":
                assert row["intent"]["purpose"] == "acceptance"
                assert row["intent"]["check_keys"] == ["check_schedule"]
        assert "not public context" not in json.dumps(page)
        assert row["reuse"]["recorded_responses"] == "missing_execution_context"
        recordings_query = row["recordings"]["query"]
        assert recordings_query["run_id"] == registration.run_id.value
        assert (
            ExperimentService.history(
                artifacts, runs, duet_id=duet_id, query=recordings_query
            )["items"]
            == []
        )
        assert (
            ExperimentService.history(
                artifacts, runs, duet_id="unrelated", query=query
            )["items"]
            == []
        )
        with pytest.raises(ValueError, match="not available to this history owner"):
            ExperimentService.history(
                artifacts, runs, duet_id="unrelated", query=recordings_query
            )
        with pytest.raises(ValueError, match="owned experiments"):
            ExperimentService.history(
                artifacts,
                runs,
                duet_id=duet_id,
                query=query,
                invocation={
                    "run_id": registration.run_id.value,
                    "episode_id": "child",
                    "registration_hash": registration.registration_hash.value,
                },
            )
        assert (
            main([
                "history",
                "--duet-store",
                str(artifacts_path),
                "--run-store",
                str(runs.root),
                "--duet-id",
                duet_id,
                "--kind",
                "executions",
                "--limit",
                "1",
            ])
            == 0
        )
        assert json.loads(capsys.readouterr().out) == page

        # A rehashed record cannot use another Run's stable execution identity.
        # The public writer refuses overwriting it; a read of a substituted row
        # must also reject the mismatched key before it can become a history view.
        from episode_runtime.records.catalog import execution_overview
        from episode_runtime.records.experiments import read_record

        stored = read_record(artifacts, "execution", run_id=registration.run_id.value)
        replaced = {**stored, "artifact_id": "other_execution"}
        assert digest_record(replaced["record"]).value == replaced["content_hash"]
        with pytest.raises(ValueError, match="different owner"):
            execution_overview(artifacts, runs, replaced)


def test_recording_choices_show_scoped_context_and_executable_inventory_requests(
    run_store,
    tmp_path,
    monkeypatch,
):
    from episode_runtime.contracts import RunEventKind
    from episode_runtime.protocol import episode_id_for_path
    from episode_runtime.records.catalog import recording_choice
    from episode_runtime.records.experiments import read_reference
    from episode_runtime.testing.recordings import save_recording

    runs, registration, _ = run_store
    owner = registration.duet_id.value
    with DuetStore(tmp_path / "recording_choices.db") as artifacts:
        artifacts.create_duet(duet_id=owner, identity={}, policy={}, state="specifying")
        paths = [
            [
                {"grain": "root", "key": registration.run_id.value},
                {"grain": "child", "key": str(index)},
            ]
            for index in range(5)
        ]
        episodes = [episode_id_for_path(registration.run_id, path) for path in paths]
        for sequence, (path, episode) in enumerate(zip(paths, episodes, strict=True)):
            runs.append_event(
                run_id=registration.run_id,
                origin=RunEventOrigin.WORKER,
                sender_sequence=sequence,
                kind=RunEventKind.EPISODE_STARTED,
                episode_id=episode,
                payload={
                    "episode_path": path,
                    "request": {"private": "raw input"},
                    "goal_view": {},
                    "goal_state_id": "initial",
                    "initial_goal_state_id": "initial",
                },
            )
        reference = save_recording(
            artifacts,
            runs,
            registration.run_id.value,
            episode_ids=[episode.value for episode in episodes[:4]],
        )
        runs.append_event(
            run_id=registration.run_id,
            origin=RunEventOrigin.WORKER,
            sender_sequence=len(episodes),
            kind=RunEventKind.EPISODE_COMPLETED,
            episode_id=episodes[0],
            payload={"ended_by": "yield_stop", "end_reason": "", "units_consumed": 0},
        )

        def no_audit(*args, **kwargs):
            raise AssertionError(
                "recording discovery must use maintained facts, not the source journal"
            )

        monkeypatch.setattr(type(runs), "read_evidence", no_audit)
        monkeypatch.setattr(type(runs), "_load_event_chain_locked", no_audit)
        choice = recording_choice(
            read_reference(artifacts, reference, owner), artifacts=artifacts, runs=runs
        )
        first = choice["invocations"]
        assert first == ExperimentService.inventory(
            artifacts, runs, duet_id=owner, **choice["inventory_request"]
        )
        second = ExperimentService.inventory(
            artifacts, runs, duet_id=owner, **choice["next_inventory_request"]
        )
        assert (
            first["through_event_ref"]
            == second["through_event_ref"]
            == choice["through_event_ref"]
        )
        selected = first["items"] + second["items"]
        assert {row["episode_id"] for row in selected} == {
            episode.value for episode in episodes[:4]
        }
        assert all(row["completion"] is None for row in selected)
        assert all(
            row["state_restoration"] == "not_needed_for_initial_entry"
            for row in selected
        )
        assert choice["reuse"]["recorded_responses"] == "missing_execution_context"
        assert (
            choice["reuse"]["continue_interrupted"]
            == "not_a_continuation_boundary"
        )
        assert "raw input" not in json.dumps(choice)
        assert episodes[4].value not in json.dumps(choice)
        from episode_runtime.store import RunStore

        unavailable = recording_choice(
            read_reference(artifacts, reference, owner),
            artifacts=artifacts,
            runs=RunStore(tmp_path / "missing_runs"),
        )
        assert unavailable["recording_ref"] == choice["recording_ref"]
        assert unavailable["through_event_ref"] == choice["through_event_ref"]
        assert unavailable["invocations"]["required_action"] == "restore_source_run"
        assert unavailable["invocations"]["items"] == []


@pytest.mark.asyncio
async def test_experiment_history_returns_owner_preserving_next_query(
    tmp_path, run_store, monkeypatch
):
    from tests.episode_builder.test_repeatable_call_materialization import build
    from tests.episode_runtime.testing.test_experiment_planning import experiment
    from episode_runtime.testing.contracts import ExperimentSpec

    request, _builds, receipt = await build(tmp_path, ())
    runs, registration, _ = run_store
    duet_id = request.frozen_workflow.duet_id.value
    invocation = {
        "run_id": registration.run_id.value,
        "episode_id": "testing-invocation",
        "registration_hash": registration.registration_hash.value,
    }
    with DuetStore(tmp_path / "duet.db") as artifacts:
        raw = experiment(artifacts, request, receipt)
        ids = set()
        for question in ("Inspect the answer.", "Inspect the counterexample."):
            spec = ExperimentSpec.from_record({**raw, "question": question})
            ids.add(spec.experiment_id)
            put_record(
                artifacts,
                "access",
                **{key: invocation[key] for key in ("run_id", "episode_id")},
                key=spec.experiment_id,
                duet_id=duet_id,
                record={
                    "registration_hash": invocation["registration_hash"],
                    "episode_id": invocation["episode_id"],
                    "spec": spec.as_record(),
                },
            )

        def no_audit(*args, **kwargs):
            raise AssertionError("history must page owner indexes")

        monkeypatch.setattr(artifacts, "events", no_audit)
        monkeypatch.setattr(type(runs), "_load_event_chain_locked", no_audit)
        first = ExperimentService.history(
            artifacts, runs, duet_id=duet_id, query={"limit": 1}, invocation=invocation
        )
        second = ExperimentService.history(
            artifacts,
            runs,
            duet_id=duet_id,
            query=first["next_query"],
            invocation=invocation,
        )
        assert {page["items"][0]["experiment_id"] for page in (first, second)} == ids
        assert second["next_query"] is None
        assert second["query"]["after"] == first["next_cursor"]
        other = ExperimentService.history(
            artifacts,
            runs,
            duet_id=duet_id,
            query={},
            invocation={**invocation, "episode_id": "other-invocation"},
        )
        assert other["items"] == []
