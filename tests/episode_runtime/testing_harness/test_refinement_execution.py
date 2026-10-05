"""Refinement integration uses actual approved builds, not a seeded campaign index."""

import asyncio
import json
from dataclasses import replace

import pytest

from tests.episode_runtime.testing_harness.refinement_fixture import prepared_refiner
from iterative_episode_refiner.execution import execute_refinement
from episode_runtime.broker import ScopedModelBroker
from episode_runtime.contracts import RunEventKind, RunTerminalStatus
from episode_runtime.records.experiments import read_run_intent
from episode_runtime.testing_harness.service import ExperimentService
from agent.episode_contracts import Sha256Digest
from llm_call_library.transport import ModelTransportResponse


@pytest.mark.asyncio
async def test_refiner_baseline_keeps_static_passes_separate_from_acceptance(
    tmp_path, run_store
):
    async with prepared_refiner(tmp_path, run_store[1].runtime_identity) as session:
        root = session.calls[session.root_id]
        context = session.snapshot(root)["context"]
        assert context["test_history"]["items"] == []
        evaluations = session.evaluations
        inputs = evaluations.builder.store.inspection_inputs_for_receipt(
            session.registration.build_receipt_id
        )
        artifacts = session.store.evidence.duets
        # The campaign explicitly binds this separately approved refiner. That
        # link cannot be used to read another target artifact or changed build.
        assert session.duet_id != session.registration.duet_id.value
        assert (
            read_run_intent(
                artifacts, session.contract.ref.as_record(), session.registration
            )["duet_id"]
            == session.duet_id
        )
        with pytest.raises(ValueError, match="exact approved Run"):
            read_run_intent(
                artifacts,
                session.contract.ref.as_record(),
                replace(
                    session.registration,
                    manifest_hash=Sha256Digest.of_bytes(b"different build"),
                ),
            )
        with pytest.raises(ValueError, match="authorized Duet"):
            read_run_intent(
                artifacts,
                session.contract.body["environment_ref"],
                session.registration,
            )
        prompts = []

        async def model(request):
            prompt = json.loads(request.messages[-1]["content"])
            prompts.append(prompt)
            if len(prompts) > 1:
                # Caller cancellation after inspecting one rejected choice, not
                # a turn budget or a claim that the refiner has finished.
                raise asyncio.CancelledError
            return ModelTransportResponse(text='{"invalid_assignment": true}', route={})

        result = await execute_refinement(
            store=session.store,
            campaign_id=session.campaign_id,
            registration=session.registration,
            source_package_path=evaluations.builder.store.verify_source_package(
                inputs.manifest
            ),
            executor=evaluations.executor,
            model_broker=ScopedModelBroker.from_plan(model, inputs.plan),
            http_broker=None,
            evaluations=evaluations,
        )
        assert result.build_status == "unresolved"
        assert result.verified_build is None
        assert result.decision_records
        assert result.run_evidence.terminal_status is RunTerminalStatus.CANCELLED
        assert result.disposition == "cancelled"
        assert not result.has_terminal_report
        events = session.store.evidence.runs.read_audit_log(session.registration.run_id)
        requests = {
            event.payload["request_id"]: event
            for event in events
            if event.kind is RunEventKind.REFINEMENT_REQUESTED
        }
        replies = [
            event for event in events
            if event.kind is RunEventKind.REFINEMENT_RESPONDED
        ]
        assert replies
        opened, closed = [], []
        for reply in replies:
            request = requests[reply.payload["request_id"]]
            state = reply.payload["session_state"]
            assert state["registration_ref"]["run_id"] == session.registration.run_id.value
            assert state["campaign_ref"] == session.contract.ref.as_record()
            assert "session_state" not in reply.payload["response"]
            assert all(call["status"] not in {"returned", "superseded"} for call in state["calls"])
            caller = next(call for call in state["calls"] if call["episode_id"] == request.episode_id.value)
            if request.payload["operation"] == "begin_unit":
                assert caller["unit_id"] == reply.payload["response"]["unit_id"]
                assert caller["candidate_before_ref"] is not None
                opened.append(caller["unit_id"])
            elif request.payload["operation"] == "close_unit":
                assert caller["unit_id"] is None
                closed.append(request.payload["payload"]["unit_id"])
        assert opened and closed and set(closed) <= set(opened)
        assert len(prompts) == 2
        assert prompts[1]["assignment_context"]["last_feedback"]["reason"]
        assert (
            prompts[1]["assignment_context"]["recent_units"][-1]["body"][
                "realized_yield"
            ]
            == 0
        )
        observations = prompts[0]["assignment_context"]["test_history"]["items"]
        assert observations
        assert {row["test_result"]["outcome"]["status"] for row in observations} == {
            "pass"
        }
        assert all(
            row["test_result"]["candidate_ref"] == result.candidate.ref.as_record()
            for row in observations
        )
        assert result.source_admission_refs
        assert result.root_report.body["unresolved_requirement_keys"]
        assert any(
            row.kind == "evaluation"
            and any(
                gap["kind"] == "coverage_missing"
                for gap in row.body["availability"]["gaps"]
            )
            for row in result.decision_records
        )
        history = ExperimentService.history(
            artifacts,
            evaluations.executor.run_store,
            duet_id=session.registration.duet_id.value,
            query={"kind": "executions"},
        )
        execution = next(
            row
            for row in history["items"]
            if row["run_id"] == session.registration.run_id.value
        )
        assert execution["intent"]["campaign_id"] == session.campaign_id.value
        assert execution["execution_status"] == "cancelled"
        assert execution["candidate_verdict"] == "unmeasured"
