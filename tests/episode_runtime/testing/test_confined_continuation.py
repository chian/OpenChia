"""Native worker continuation with supplied Builder and reasoning responses.

The systemd workers, confinement attestations, journal reconstruction, launch
approval checks and host learning ledger are real. The supplied decisions test
restoration, not live-model reasoning quality. Approvals belong to a temp Duet.
"""

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess

import pytest

from agent.duet_store import DuetStore
from agent.episode_contracts import EpisodeCreationSpec
from agent.episode_launch import resolve_launch
from episode_builder.service import EpisodeBuilder
from episode_builder.store import BuildStore
from episode_library.inquiry import inquiry_contract
from episode_runtime import exchanges
from episode_runtime.broker import ScopedModelBroker
from episode_runtime.continuation import InterruptedRunRef
from episode_runtime.contracts import RunEventKind, RunTerminalStatus, RuntimePolicy
from episode_runtime.executor import (
    make_systemd_run_executor_factory,
)
from episode_runtime.executor_lifecycle import verify_stopped_executor
from episode_runtime.http_broker import ScopedHttpBroker
from episode_runtime.store import RunStore
from episode_runtime.testing.execution import RunExecution, register_build
from episode_runtime.testing.inputs import workflow_template
from episode_runtime.testing.launches import record_launch_intent
from episode_runtime.testing.reconstruction import ReconstructionCursor, ReconstructionError
from function_library.models import _thaw_json
from llm_call_library import CallOptions
from llm_call_library.transport import ModelTransportResponse, model_transport_scope
from tests.episode_runtime.conftest import numerical_control
from tests.episode_runtime.test_reasoning_workflow import (
    _approved_request,
    _module_response,
    _plan_response,
)
from tests.episode_runtime.testing.launch_fixture import FixtureLaunchHost


@pytest.mark.platforms("linux")
@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt_reply", [False, True], ids=["matching", "divergent"])
async def test_confined_continuation_preserves_credit_and_rejects_divergent_worker_requests(
    tmp_path, monkeypatch, corrupt_reply
):
    runtime_dir = Path("/run/user") / str(os.getuid())
    if (runtime_dir / "bus").exists():
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv(
            "DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir / 'bus'}"
        )
    status = subprocess.run(
        ["systemctl", "--user", "is-system-running"],
        capture_output=True,
        timeout=5,
    )
    if status.returncode != 0:
        pytest.skip("native continuation requires a running user systemd manager")
    spec = EpisodeCreationSpec(
        goal="Determine which search routes remain useful for this corpus.",
        progress="Admitted durable knowledge transitions",
        stopping="Registered projected-yield continuation",
        # Explicit fixture contract, not the shipped library's default threshold.
        numeric_control=numerical_control(0.9),
        epistemic=inquiry_contract(
            goal_class="open_problem",
            domain="test",
            environment={"dataset": "v1"},
            evidence=({
                "kind": "support",
                "text": "Search X yielded no records under dataset v1.",
                "observation": {
                    "action_class": "discover", "action_inputs": {},
                    "goal_class": "open_problem", "environment": {"dataset": "v1"},
                    "assumptions": [], "expected_observation": "relevant records",
                    "observed_outcome": "no records", "status": "failed",
                },
            },),
        ),
    )
    request = _approved_request(tmp_path, spec=spec)
    builds = BuildStore(tmp_path)

    async def builder_model(request):
        prompt = json.loads(request.messages[-1]["content"])
        response = _plan_response(prompt) if "node" in prompt else _module_response(prompt)
        return ModelTransportResponse(text=json.dumps(response), route={})

    with model_transport_scope(builder_model):
        receipt = await EpisodeBuilder(
            store=builds,
            planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"selector": {}, "executor": {}},
        ).build(request)
    assert receipt.status == "materialized", [d.as_record() for d in receipt.deficits]
    inputs = builds.inspection_inputs_for_receipt(receipt.receipt_id)
    runs = RunStore(tmp_path / "execution" / "runs")
    executor = make_systemd_run_executor_factory(
        repository_root=Path(__file__).resolve().parents[3]
    )(runs)
    registration, package = register_build(
        executor, builds, inputs, workflow_template(request.frozen_workflow), RuntimePolicy()
    )
    calls = []

    async def inquiry_model(request):
        prompt = json.loads(request.messages[-1]["content"])
        bundle = prompt["typed_unit_input"]
        ordinal = bundle["next_ordinal"]
        phase = "execution" if "selected_action" in prompt else "selection"
        assert (ordinal, phase) not in calls, "continuation repeated an old model call"
        calls.append((ordinal, phase))
        action = "discover" if ordinal == 0 else "clarify"
        if phase == "selection":
            response = {"action_class": action, "action_inputs": {}, "retry_reason": ""}
        else:
            response = {
                "action_class": action, "action_inputs": {}, "status": "failed",
                "expected_observation": "relevant records", "observed_outcome": "no records",
                "candidate_lessons": [], "entities": [], "revisions": [],
            }
            if ordinal == 0:
                response["candidate_lessons"] = [{
                    "claim": "This route yielded no records", "action_class": action,
                    "scope_tier": "episode", "reopening_conditions": ["dataset changes"],
                    "evidence_refs": [bundle["evidence"][0]["artifact_id"]],
                }]
        return ModelTransportResponse(text=json.dumps(response), route={})

    async def no_http(*args, **kwargs):
        raise AssertionError("This fixture has no HTTP capability")

    real_learning = exchanges.broker_learning_request
    cut = []

    async def interrupt_after_committed_reply(**arguments):
        await real_learning(**arguments)
        if (
            arguments["registration"].run_id == registration.run_id
            and arguments["frame"].body["operation"] == "submit"
        ):
            event = runs.read_committed_prefix(registration.run_id)[-1]
            assert event.kind is RunEventKind.LEARNING_RESPONDED
            assert event.payload["response"]["measurement"]["realized_yield"] > 0
            assert not event.payload["response"]["stop"]
            cut.append(event.event_id)
            raise asyncio.CancelledError

    monkeypatch.setattr(exchanges, "broker_learning_request", interrupt_after_committed_reply)
    launch = resolve_launch({
        "project": "confined-continuation-fixture", "project_root": str(tmp_path),
        "env_files": [],
        "routes": {"supplied": {
            "provider": "custom", "model": "supplied-no-network",
            "base_url": "http://localhost:9999/v1", "api_mode": "chat_completions",
            "auth": {"kind": "none"},
        }},
        "model_slots": {"selector": "supplied", "executor": "supplied"},
        "builder_slots": {"planning": "selector", "emission": "executor"},
    })
    with DuetStore(tmp_path / "duet.db") as artifacts:
        host = FixtureLaunchHost(artifacts, builds, registration.duet_id.value)
        host.approve_fixture(launch)
        launch_id, _ = host._prepare_model_launch(
            "run", registration.run_id.value, model_types=("selector", "executor")
        )
        intent = record_launch_intent(artifacts, registration, launch_id, launch.configuration_hash)
        execution = RunExecution(artifacts=artifacts, builds=builds, runs=runs, executor=executor)
        arguments = dict(
            source_package_path=package, intent_ref=intent,
            model_broker=ScopedModelBroker.from_plan(inquiry_model, inputs.plan),
            http_broker=ScopedHttpBroker(
                policy=registration.egress_policy, credentials={}, transport=no_http,
                max_frame_bytes=registration.runtime_policy.max_frame_bytes,
            ),
        )
        # These are operational test watchdogs, never Episode stopping criteria.
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(execution.execute(registration=registration, **arguments), 240)
        assert len(cut) == 1
        old_evidence = runs.read_evidence(registration.run_id)
        old_audit = runs.read_audit_log(registration.run_id)
        old_claim = runs.read_claim(registration.run_id)
        assert old_evidence.terminal_status is RunTerminalStatus.CANCELLED
        assert calls == [(0, "selection"), (0, "execution")]
        assert (await verify_stopped_executor(executor, old_claim))["stopped"]

        resumed = replace(registration, resume_from=InterruptedRunRef.from_run(runs, registration.run_id))
        if corrupt_reply:
            accept = ReconstructionCursor.accept
            injected = []

            def altered_historical_reply(cursor, frame):
                reply = accept(cursor, frame)
                if frame.frame_type == "learning_request" and frame.body["operation"] == "retrieve" and not injected:
                    # Fault-inject the host's replay reply, not the immutable
                    # audit or worker source. The actual confined worker must
                    # then generate a different next model request.
                    changed = _thaw_json(reply.body)
                    changed["response"]["next_ordinal"] += 1
                    injected.append(frame.body["request_id"])
                    return replace(reply, body=changed)
                return reply

            monkeypatch.setattr(ReconstructionCursor, "accept", altered_historical_reply)
            with pytest.raises(ReconstructionError, match="reconstruction_diverged"):
                await asyncio.wait_for(execution.execute(registration=resumed, **arguments), 240)
            assert len(injected) == 1
            rejected = runs.read_evidence(resumed.run_id)
            suffix = runs.read_audit_log(resumed.run_id)
            assert rejected.terminal_status is RunTerminalStatus.INVALID
            assert not any(event.kind in {
                RunEventKind.RUN_RECONSTRUCTED, RunEventKind.MODEL_REQUESTED,
                RunEventKind.LEARNING_COMMITTED, RunEventKind.HTTP_REQUESTED,
            } for event in suffix)
            assert calls == [(0, "selection"), (0, "execution")]
            assert runs.read_audit_log(registration.run_id) == old_audit
            assert runs.read_evidence(registration.run_id) == old_evidence
            assert (await verify_stopped_executor(executor, runs.read_claim(resumed.run_id)))["stopped"]
            return
        final = await asyncio.wait_for(execution.execute(registration=resumed, **arguments), 240)
        assert final.terminal_status is RunTerminalStatus.SUCCEEDED, final.typed_status
        result = final.typed_status["workflow_result"]
        assert result["terminal_state"] == "completed"
        assert result["result"]["durable_lessons"]
        assert runs.read_audit_log(registration.run_id) == old_audit
        assert runs.read_evidence(registration.run_id) == old_evidence
        assert resumed.run_id != registration.run_id
        assert resumed.logical_run_id == registration.run_id
        assert runs.read_claim(resumed.run_id).executor_instance_id != old_claim.executor_instance_id

        suffix = runs.read_audit_log(resumed.run_id)
        gates = [event.payload for event in suffix if event.kind is RunEventKind.RUN_RECONSTRUCTED]
        assert len(gates) == 1
        assert gates[0]["resume_from"] == resumed.resume_from.as_record()
        source_admission = gates[0]["source_admission"]
        assert source_admission["kind"] == "confined_run_reconstruction"
        assert source_admission["manifest_id"] == registration.manifest_id.value
        assert source_admission["runtime_identity"] == registration.runtime_identity.as_record()
        # A reasoning Episode is ordinary admitted Target Workflow code, not
        # a privileged source family with its own continuation engine.
        assert {row["family"] for row in source_admission["modules"]} == {"target"}
        assert {row["local_id"] for row in source_admission["modules"]} == {
            node.local_id for node in inputs.plan.nodes
        }
        assert gates[0]["activation_admission"]["previous_executor"]["stopped"]
        assert gates[0]["activation_admission"]["current_authority"]["launch_approval_ref"]
        assert not any(event.kind is RunEventKind.EPISODE_STARTED for event in suffix)
        units = [
            event.payload["receipt"] for event in runs.read_execution_prefix(resumed.run_id)
            if event.kind is RunEventKind.LEARNING_COMMITTED
        ]
        assert [unit["ordinal"] for unit in units] == list(range(len(units)))
        assert units[0]["measurement"]["realized_yield"] > 0
        assert all(unit["measurement"]["realized_yield"] == 0 for unit in units[1:])
        assert units[-1]["measurement"]["credit_after"] == units[0]["measurement"]["credit_after"]
        assert len(calls) == 2 * len(units) == len(set(calls))
