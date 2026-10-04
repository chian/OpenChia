"""Restore host bindings from real broker receipts without repeating admissions.

Worker boundaries and child choices are supplied; campaign admission, host calls,
and the shared Run journal are real. This is not resumed worker execution.
"""

import asyncio
from dataclasses import replace

import pytest

from agent.duet_contracts import DuetIdentity, content_id
from agent.duet_service import DuetService
from agent.duet_store import DuetConflictError
from agent.episode_blueprints import workflow_blueprint_from_spec
from agent.episode_contracts import OpaqueId
from episode_runtime import protocol
from episode_runtime.broker import ScopedModelBroker
from episode_runtime.continuation import InterruptedRunRef
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunTerminalStatus
from episode_runtime.exchanges import broker_model_request, broker_refinement_request
from episode_runtime.executor import _HostChannel
from handoff_library import ParentRequest
from iterative_episode_refiner.runtime import RefinementSession
from iterative_episode_refiner.contracts import RefinementTarget, RefinementTargetLayer
from iterative_episode_refiner.records import Ref
from iterative_episode_refiner.runtime_proposals import _inherited_draft, assign_child
from method_loop import EpisodeRequest
from llm_call_library import ModelTransportResponse
from tests.episode_runtime.conftest import claim_store
from tests.episode_runtime.testing.refinement_fixture import prepared_refiner
from tests.episode_runtime.testing.test_host_exchange_recordings import PacketWriter
from tests.episode_runtime.test_model_request_thaw import REQUEST


def approve_successor(session):
    """A legitimate successor approval in this test's isolated Duet store."""
    artifacts = session.store.duet_store
    authority = DuetService(artifacts, allowed_episode_capabilities=())
    identity = DuetIdentity.from_record(artifacts.get_duet(session.duet_id)["identity"])
    refiner = authority.refiner
    baseline = refiner.load_baseline(OpaqueId(artifacts.latest_artifact(duet_id=session.duet_id, kind="refinement_baseline")["artifact_id"]))
    target = RefinementTarget(RefinementTargetLayer.MATERIALIZATION_IMPLEMENTATION, baseline.materialized_specification_id, baseline.materialized_specification_hash, "/workflow_global")
    note, = refiner.record_workspace_notes(
        identity, baseline_id=baseline.baseline_id,
        body="Clarify implementation diagnostics without changing architecture.",
        targets=(target,), idempotency_keys=("restore-authority-successor",),
    )
    frozen = authority.verify_workflow_approval(baseline.workflow_approval_id)[1]
    result = refiner.request(
        identity, baseline_id=baseline.baseline_id.value,
        candidate_workflow_architecture=workflow_blueprint_from_spec(frozen.workflow),
        human_note_ids=(note.note_id.value,),
        implementation_directives=({"human_note_id": note.note_id.value, "target_id": target.target_id.value, "instruction": note.body},),
    )
    return authority.approve_current_implementation_refinement(identity, decision_id=OpaqueId(result["decision_id"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ("prepared_child", "open_child_unit", "closed_child_unit"))
async def test_host_restoration_preserves_waiting_calls_without_repeating_credit(tmp_path, boundary):
    runtime_identity = claim_store(tmp_path / "identity")[1].runtime_identity
    async with prepared_refiner(tmp_path, runtime_identity) as session:
        registration, runs = session.registration, session.store.evidence.runs
        claim_store(runs.root, registration, store=runs)
        binding = protocol.ProtocolBinding.from_registration(registration)
        worker = protocol.FrameEncoder(sender=protocol.FrameSender.WORKER, binding=binding)
        channel = _HostChannel(binding=binding, reader=asyncio.StreamReader(), writer=PacketWriter())
        ordinal = 0

        def frame(kind, body):
            nonlocal ordinal
            result = protocol.decode_frame(worker.encode(kind, body), sender=protocol.FrameSender.WORKER, binding=binding, expected_sequence=ordinal)
            ordinal += 1
            return result

        def started(episode_id, call):
            body = {
                "episode_id": episode_id, "event_kind": "episode_started",
                "payload": {
                    "episode_path": [{"grain": grain, "key": key} for grain, key in call.path],
                    "request": EpisodeRequest(call.goal, call.request or registration.launch_request).as_record(),
                    "goal_view": {"goal": call.goal.as_record()["objective"]},
                    "goal_state_id": "supplied-boundary", "initial_goal_state_id": "supplied-boundary",
                },
            }
            emitted = frame("run_event", body)
            runs.append_event(run_id=registration.run_id, origin=RunEventOrigin.WORKER, sender_sequence=emitted.sender_sequence, kind=RunEventKind.EPISODE_STARTED, episode_id=OpaqueId(episode_id), payload=body["payload"])

        async def exchange(episode_id, call, operation, payload):
            emitted = frame("refinement_request", {
                "episode_id": episode_id,
                "episode_path": [{"grain": grain, "key": key} for grain, key in call.path],
                "request_id": content_id("refinement_request", {"ordinal": ordinal}).value,
                "operation": operation, "payload": payload,
            })
            await broker_refinement_request(run_store=runs, registration=registration, channel=channel, frame=emitted, session=session)

        root = session.calls[session.root_id]
        started(session.root_id, root)
        await exchange(session.root_id, root, "begin_unit", {"role": "parts"})
        selection = assign_child(
            session, root,
            _inherited_draft(root, "designer", goal="Inspect the assigned refinement requirements."),
            session.contract.producer_ref,
        )
        await exchange(session.root_id, root, "prepare_child", {"unit_id": root.unit_id.value, "selection": selection})
        child_id, child = next(iter(session.pending.items()))
        if boundary != "prepared_child":
            request = ParentRequest(
                request_id=content_id("request", {"child": child_id}).value,
                parent_episode_id=session.root_id, child_episode_id=child_id,
                goal_id=child.goal.goal_id, child_interface="refinement.designer",
                artifact_ids_by_role={
                    "campaign": (session.campaign_id.value,),
                    "assignment": (child.assignment.artifact_id.value,),
                    "invocation": (child.invocation_id.value,),
                },
            )
            await exchange(session.root_id, root, "enter_child", {
                "request": request.as_record(), "goal": child.goal.as_record(),
                "invocation": {"child_episode_id": child_id},
            })
            started(child_id, child)
            await exchange(child_id, child, "begin_unit", {"role": "designer"})
            if boundary == "closed_child_unit":
                await exchange(child_id, child, "close_unit", {"unit_id": child.unit_id.value})
            assert root.unit_id is not None
        if boundary == "open_child_unit":
            # Model reply is durable, but propose has not happened at interruption.
            async def model(request):
                return ModelTransportResponse(text="not json", route={"fixture": "prior reply"})

            emitted = frame("model_request", {
                "episode_id": child_id,
                "episode_path": [{"grain": grain, "key": key} for grain, key in child.path],
                "model_request_id": content_id("model_request", "saved proposal").value,
                "request": REQUEST,
            })
            models = ScopedModelBroker(model, {tuple(grain for grain, _ in child.path): "designer"})
            await broker_model_request(run_store=runs, registration=registration, channel=channel, frame=emitted, model_broker=models)
        runs.finalize_run(
            run_id=registration.run_id, origin=RunEventOrigin.HOST,
            sender_sequence=channel.next_sender_sequence,
            terminal_status=RunTerminalStatus.INTERRUPTED,
            typed_status={"outcome": "interrupted", "reason": "host-state fixture boundary"},
        )
        old_audit = runs.read_audit_log(registration.run_id)
        saved = session.continuation_state()
        resumed = replace(registration, resume_from=InterruptedRunRef.from_run(runs, registration.run_id))
        builds = session.store.evidence.builds
        inputs = builds.inspection_inputs_for_receipt(registration.build_receipt_id)
        arguments = dict(store=session.store, campaign_id=session.campaign_id,
                         source_package_path=builds.verify_source_package(inputs.manifest), evaluations=session.evaluations)
        restored = RefinementSession(registration=resumed, **arguments)
        expected = {**saved, "registration_ref": {"run_id": resumed.run_id.value, "content_hash": resumed.registration_hash.value}}
        assert restored.continuation_state() == expected
        assert runs.read_audit_log(registration.run_id) == old_audit
        assert restored._operation_ordinal == session._operation_ordinal
        if boundary == "prepared_child":
            assert restored.pending[child_id].request is None
        else:
            assert restored.calls[child_id].request == child.request
            assert restored.calls[session.root_id].unit_id == root.unit_id
            # Restoration does not weaken the separate fresh-launch gate.
            with pytest.raises(ValueError, match="active root assignment"):
                RefinementSession(registration=registration, **arguments)
        if boundary == "closed_child_unit":
            assert restored.calls[child_id].unit_id is None
            assert restored.calls[child_id].candidate_before == child.candidate_before
        if boundary == "open_child_unit":
            claim_store(runs.root, resumed, store=runs)
            producer = next(event for event in old_audit if event.kind is RunEventKind.MODEL_RESPONDED)
            reply = await restored.exchange(
                episode_id=OpaqueId(child_id),
                episode_path=[{"grain": grain, "key": key} for grain, key in child.path],
                operation="propose", payload={
                    "unit_id": child.unit_id.value, "task": "design",
                    "raw_response": producer.payload["response_text"],
                    "producer_call_id": producer.payload["producer_call_id"],
                },
            )
            assert not reply["proceed"]  # Invalid JSON, not a lost producer.
            feedback = restored.store.evidence.reference(restored.calls[child_id].feedback_ref, restored.duet_id)
            proposal = restored.store.evidence.reference(Ref.from_record(feedback["proposal_ref"]), restored.duet_id)
            assert proposal["run_id"] == registration.run_id.value
            assert proposal["event"] == producer.as_record()
            assert runs.read_committed_prefix(resumed.run_id) == ()
            assert runs.read_execution_prefix(resumed.run_id) == old_audit
            with session.view() as view:
                head = dict(view.head)
            successor = approve_successor(session)
            assert successor.approval_id.value != head["authority_head_id"]
            assert session.store.duet_store.get_approval(head["authority_head_id"])["revoked"] is False
            with session.view() as view:
                assert dict(view.head) == head
            with pytest.raises(DuetConflictError, match="authority is no longer current"):
                RefinementSession(registration=resumed, **arguments)
            assert runs.read_audit_log(registration.run_id) == old_audit
            return

        # A later legitimate campaign change cannot be substituted for the exact
        # committed state, even though the original evidence remains available.
        active_id = session.root_id if boundary == "prepared_child" else child_id
        active = restored.calls[active_id]
        path = [{"grain": grain, "key": key} for grain, key in active.path]
        if active.unit_id is None:
            await restored.exchange(episode_id=OpaqueId(active_id), episode_path=path, operation="begin_unit", payload={"role": active.assignment.body["role"]})
        await restored.exchange(episode_id=OpaqueId(active_id), episode_path=path, operation="close_unit", payload={"unit_id": active.unit_id.value})
        with pytest.raises(ValueError, match="campaign changed"):
            RefinementSession(registration=resumed, **arguments)
        assert runs.read_audit_log(registration.run_id) == old_audit
