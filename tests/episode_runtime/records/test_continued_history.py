"""Indexed discovery over real physical Run records with fixture dispatches.

This tests record ownership and provenance, not worker reconstruction, launch
approval, measurement validity or live reasoning.
"""

from dataclasses import replace

import pytest

from agent.duet_contracts import digest_record
from agent.duet_store import DuetStore
from episode_runtime.continuation import InterruptedRunRef
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunTerminalStatus
from episode_runtime.protocol import episode_id_for_path
from episode_runtime.records.catalog import execution_overview, history, inventory
from episode_runtime.records.experiments import put_record, read_record
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.recordings import save_recording
from method_loop.identities import UnitRef
from tests.episode_builder.test_repeatable_call_materialization import build
from tests.episode_runtime.conftest import claim_store
from tests.episode_runtime.testing.test_experiment_planning import experiment


@pytest.mark.asyncio
async def test_continued_history_retains_reports_and_pins_owned_recording_queries(
    tmp_path, run_store, monkeypatch,
):
    request, _, receipt = await build(tmp_path, ())
    original = replace(run_store[1], duet_id=request.frozen_workflow.duet_id)
    runs, _, _ = claim_store(tmp_path / "history", original)
    owner = original.duet_id.value
    with DuetStore(tmp_path / "history.db") as artifacts:
        artifacts.create_duet(duet_id=owner, identity={}, policy={}, state="specifying")
        spec = ExperimentSpec.from_record(experiment(artifacts, request, receipt))
        put_record(
            artifacts, "dispatch", experiment_id=spec.experiment_id, duet_id=owner,
            record={"spec": spec.as_record(), "registration": original.as_record(), "plan": {"measurements": []}},
        )
        dispatch = read_record(artifacts, "dispatch", experiment_id=spec.experiment_id)

        def reference(row):
            return {key: row[key] for key in ("artifact_id", "content_hash")}

        def publish(registration):
            put_record(
                artifacts, "execution", run_id=registration.run_id.value, duet_id=owner,
                record={
                    "registration": registration.as_record(), "intent_ref": reference(dispatch),
                    "mode": "live_fresh", "context": None, "recording_ref": None,
                    "scope": {"kind": "workflow", "entry_local_id": "inquiry", "included_local_ids": ["inquiry"]},
                },
            )
            return read_record(artifacts, "execution", run_id=registration.run_id.value)

        original_execution = publish(original)
        path = [{"grain": "root", "key": original.run_id.value}]
        episode = episode_id_for_path(original.run_id, path)
        runs.append_event(
            run_id=original.run_id, origin=RunEventOrigin.WORKER, sender_sequence=0,
            kind=RunEventKind.EPISODE_STARTED, episode_id=episode,
            payload={
                "episode_path": path, "request": {}, "goal_view": {},
                "goal_state_id": "initial", "initial_goal_state_id": "initial",
            },
        )
        interrupted = runs.finalize_run(
            run_id=original.run_id, origin=RunEventOrigin.HOST, sender_sequence=0,
            terminal_status=RunTerminalStatus.INTERRUPTED, typed_status={},
        )
        resume_from = InterruptedRunRef.from_run(runs, original.run_id)
        original_recording = save_recording(artifacts, runs, original.run_id.value)
        interrupted_ref = {"artifact_id": interrupted.evidence_id.value, "content_hash": interrupted.content_hash.value}
        report = {
            "experiment_id": spec.experiment_id, "candidate_verdict": "unmeasured",
            "execution_ref": interrupted_ref, "outcomes": [],
            "limitations": ["Fixture interruption; no measured result."], "unresolved_questions": [],
        }
        put_record(artifacts, "measurement", experiment_id=spec.experiment_id, duet_id=owner, record=report)
        original_report = read_record(artifacts, "measurement", experiment_id=spec.experiment_id)
        invocation = {"run_id": "testing-owner", "episode_id": "testing-child", "registration_hash": original.registration_hash.value}
        put_record(
            artifacts, "access", run_id=invocation["run_id"], episode_id=invocation["episode_id"], key=spec.experiment_id,
            duet_id=owner, record={**invocation, "spec": spec.as_record()},
        )
        before = history(artifacts, runs, duet_id=owner, query={}, invocation=invocation)["items"][0]
        assert before["execution"]["continuation"]["availability"] == "requires_validation"
        assert before["execution"]["continuation"]["resume_from"] == resume_from.as_record()
        pinned_query = before["execution"]["recordings"]["query"]

        resumed = replace(original, resume_from=resume_from)
        claim_store(tmp_path / "history", resumed, store=runs)
        current_execution = publish(resumed)
        put_record(
            artifacts, "continuation", predecessor_run_id=original.run_id.value, duet_id=owner,
            record={"resume_from": resume_from.as_record(), "execution_ref": reference(current_execution)},
        )
        unit = UnitRef(episode.value, 0)
        runs.append_event(
            run_id=resumed.run_id, origin=RunEventOrigin.WORKER, sender_sequence=0,
            kind=RunEventKind.UNIT_COMPLETED, episode_id=episode,
            payload={"unit_ref": unit.as_record(), "unit_label": "continued work"},
        )
        completed = runs.finalize_run(
            run_id=resumed.run_id, origin=RunEventOrigin.HOST, sender_sequence=0,
            terminal_status=RunTerminalStatus.SUCCEEDED, typed_status={},
        )
        current_recording = save_recording(artifacts, runs, resumed.run_id.value)
        completed_ref = {"artifact_id": completed.evidence_id.value, "content_hash": completed.content_hash.value}
        put_record(
            artifacts, "measurement_attempt", experiment_id=spec.experiment_id,
            execution_set_hash=digest_record({"target_run_id": resumed.run_id.value, "instrument_run_ids": {}}).value,
            duet_id=owner, record={**report, "execution_ref": completed_ref},
        )

        def no_audit(*args, **kwargs):
            raise AssertionError("history must use maintained records, not reconstruct audit")

        monkeypatch.setattr(type(runs), "read_evidence", no_audit)
        monkeypatch.setattr(type(runs), "_load_event_chain_locked", no_audit)
        monkeypatch.setattr(artifacts, "events", no_audit)
        current = history(artifacts, runs, duet_id=owner, query={}, invocation=invocation)["items"][0]
        execution = current["execution"]
        assert execution["run_id"] == resumed.run_id.value
        assert execution["logical_run_id"] == original.run_id.value
        assert execution["continuation"]["availability"] == "not_interrupted"
        assert [row["execution_status"] for row in execution["attempts"]] == ["interrupted", "succeeded"]
        assert current["measurement"]["execution_ref"] == completed_ref
        retained = execution_overview(artifacts, runs, original_execution, experiment_id=spec.experiment_id)
        assert retained["continuation"]["availability"] == "already_continued"
        assert retained["measurement_ref"] is None
        assert retained["current_execution_ref"] == reference(current_execution)
        for query, expected in ((pinned_query, original_recording), (execution["recordings"]["query"], current_recording)):
            page = history(artifacts, runs, duet_id=owner, query=query, invocation=invocation)
            assert [row["recording_ref"] for row in page["items"]] == [expected]
        with pytest.raises(ValueError, match="outside the owned experiment lineage"):
            history(artifacts, runs, duet_id=owner, query={**pinned_query, "attempt_run_id": "another-run"}, invocation=invocation)
        query = {**current["reports_query"], "limit": 1}
        first = history(artifacts, runs, duet_id=owner, query=query, invocation=invocation)
        second = history(artifacts, runs, duet_id=owner, query=first["next_query"], invocation=invocation)
        reports = first["items"] + second["items"]
        assert second["next_query"] is None and len(reports) == 2
        assert [row["measurement_ref"] for row in reports if row["is_current"]] == [current["measurement"]["measurement_ref"]]
        assert {row["execution_ref"]["artifact_id"] for row in reports} == {interrupted_ref["artifact_id"], completed_ref["artifact_id"]}
        assert read_record(artifacts, "measurement", experiment_id=spec.experiment_id) == original_report
        with pytest.raises(ValueError, match="not available to this history owner"):
            history(artifacts, runs, duet_id=owner, query=query, invocation={**invocation, "episode_id": "sibling"})

        source = {"kind": "experiment", "experiment_id": spec.experiment_id}
        available = inventory(artifacts, runs, duet_id=owner, source=source, query={})
        assert available["selection_status"] == "required"
        assert available["required_action"] == "select_attempt_prefix"
        assert available["items"] == [] and available["run_id"] is None
        earlier, later = available["attempts"]
        start = inventory(artifacts, runs, duet_id=owner, **earlier["inventory_requests"]["invocations"])
        inherited = inventory(artifacts, runs, duet_id=owner, **later["inventory_requests"]["invocations"])
        fresh = inventory(artifacts, runs, duet_id=owner, **later["inventory_requests"]["units"])
        assert start["coverage"] == inherited["coverage"] == fresh["coverage"] == "physical_attempt_only"
        assert start["items"][0]["episode_id"] == episode.value
        assert start["items"][0]["completion"] is None
        assert inherited["items"] == []  # No fabricated start in the continued attempt.
        assert fresh["items"][0]["unit_ref"] == unit.as_record()
        assert fresh["items"][0]["event_ref"]["run_id"] == resumed.run_id.value
        with pytest.raises(ValueError, match="outside the owned experiment lineage"):
            inventory(artifacts, runs, duet_id=owner, source=source, query={
                "through_event_ref": {**later["through_event_ref"], "run_id": "unrelated-run"},
            })
        with pytest.raises(ValueError, match="another Run"):
            inventory(artifacts, runs, duet_id=owner,
                source={"kind": "recording", "recording_ref": original_recording},
                query={"through_event_ref": later["through_event_ref"]},
            )
