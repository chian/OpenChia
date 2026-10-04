"""A new scoped experiment inherits learning without repeating earlier work.

The real Builder, linked Episode loop, service, ledger and stores execute here.
Materializer/model replies are supplied and the executor's attestation is inert;
this is in-process restoration evidence, not live reasoning or confinement proof.
"""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from agent.duet_store import DuetStore
from agent.episode_contracts import EpisodeCreationSpec, OpaqueId
from agent.episode_launch import resolve_launch
from episode_builder.service import EpisodeBuilder
from episode_builder.store import BuildStore
from episode_runtime.contracts import RunEventKind
from episode_runtime.linker import RuntimeLinkError, prepare_source_package
from episode_runtime.records.experiments import put_data
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.recordings import read_recording, save_recording
from episode_runtime.testing.service import ExperimentService
from episode_runtime.testing.units import capture_unit_boundary
from function_library.epistemic_schemas import identity
from function_library.models import _thaw_json
from llm_call_library import CallOptions
from llm_call_library.transport import ModelTransportResponse, model_transport_scope
from tests.episode_runtime.conftest import numerical_control
from tests.episode_runtime.test_epistemic_learning import attempt, contract
from tests.episode_runtime.test_reasoning_workflow import (
    _approved_request,
    _module_response,
    _plan_response,
)
from tests.episode_runtime.testing.launch_fixture import FixtureLaunchHost
from tests.episode_runtime.testing.test_experiment_planning import experiment
from tests.episode_runtime.testing.test_scoped_execution import LinkedExecutor


@pytest.mark.asyncio
async def test_later_unit_reuses_verified_learning_without_reexecution_or_new_credit(
    tmp_path, run_store, monkeypatch
):
    request = _approved_request(
        tmp_path,
        spec=EpisodeCreationSpec(
            goal="Determine whether this recorded search route yields relevant records.",
            progress="Admitted scoped knowledge from the recorded search evidence.",
            stopping="Registered projected-yield continuation.",
            numeric_control=numerical_control(0.9),
            epistemic=contract(),
        ),
    )
    builds = BuildStore(tmp_path)

    async def materializer(call):
        prompt = json.loads(call.messages[-1]["content"])
        response = _plan_response(prompt) if "node" in prompt else _module_response(prompt)
        return ModelTransportResponse(text=json.dumps(response), route={})

    with model_transport_scope(materializer):
        receipt = await EpisodeBuilder(
            store=builds,
            planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"selector": {}, "executor": {}},
        ).build(request)
    assert receipt.materialized, [item.as_record() for item in receipt.deficits]
    executor = LinkedExecutor(tmp_path / "execution", run_store[1].runtime_identity)
    calls = []

    def model(route, key, call, cancel, progress):
        prompt = json.loads(call.messages[-1]["content"])
        calls.append(prompt)
        if "selected_action" not in prompt:
            response = {
                "action_class": "discover",
                "action_inputs": {},
                "retry_reason": "Explicit duplicate-admission test of this same recorded route.",
            }
        else:
            response = attempt(prompt["typed_unit_input"]["evidence"][0]["artifact_id"])
        return json.dumps(response), route["model"]

    monkeypatch.setattr("agent.episode_launch_transport._invoke", model)
    launch = resolve_launch({
        "project": "later-unit-fixture",
        "project_root": str(tmp_path),
        "env_files": [],
        "routes": {"local": {
            "provider": "custom", "model": "supplied-fixture",
            "base_url": "https://example.org/v1", "api_mode": "chat_completions",
            "auth": {"kind": "none"},
        }},
        "model_slots": {"selector": "local", "executor": "local"},
        "builder_slots": {"planning": "selector", "emission": "executor"},
    })
    with DuetStore(tmp_path / "duet.db") as artifacts:
        owner = request.frozen_workflow.duet_id.value
        FixtureLaunchHost(artifacts, builds, owner).approve_fixture(launch)
        raw = experiment(artifacts, request, receipt)
        raw["launch_ref"] = put_data(artifacts, owner, "launch", launch.record)
        service = ExperimentService(
            artifacts=artifacts, builds=builds,
            runs=executor.run_store, executor=executor,
        )
        original = await service.run(ExperimentSpec.from_record(raw))
        assert original["execution_status"] == "succeeded", original
        source_id = OpaqueId(original["run_id"])
        original_audit = tuple(event.as_record() for event in service.runs.read_audit_log(source_id))
        source_commits = [
            event for event in service.runs.read_audit_log(source_id)
            if event.kind is RunEventKind.LEARNING_COMMITTED
        ]
        assert len(source_commits) >= 2
        first = source_commits[0].payload
        prior_credit = first["receipt"]["measurement"]["credit_after"]
        assert prior_credit > 0 and not first["receipt"]["stop"]
        assert source_commits[-1].payload["receipt"]["stop"]
        assert all(
            event.payload["receipt"]["measurement"]["realized_yield"] == 0
            for event in source_commits[1:]
        )
        original_lesson, = first["state"]["records"]
        recording = read_recording(service.runs, source_id.value)
        selected = next(row for row in recording["units"] if row["unit_ref"]["unit_index"] == 1)
        boundary = capture_unit_boundary(
            artifacts, service.runs, source_id.value, selected["unit_ref"]["unit_id"]
        )
        assert boundary["reconstruction_prefix"]["completed_units"] == 1
        assert not boundary["initial_state_reproducible"]

        scoped = deepcopy(raw)
        scoped.update(mode="live_saved", recording_ref=None)
        scoped["scope"].update(
            kind="unit", unit_label=boundary["unit_label"],
            invocation_path=boundary["invocation_path"],
        )
        scoped["boundary"]["parent_context_ref"] = boundary["parent_context_ref"]
        scoped["start"] = {
            "kind": "saved_inputs", "artifact_ref": boundary["recording_ref"],
            "input_payload": {},
        }
        spec = ExperimentSpec.from_record(scoped)
        preview = service.preview(spec)
        assert preview["resolved"], preview["gaps"]

        # Probe the actual store validator immediately before the valid scoped
        # commit. Neither forged payload reaches publication; a correctly
        # rehashed receipt cannot reset inherited credit or erase its state.
        original_new_event = service.runs._new_event
        refused = []

        def probe_publication(**kwargs):
            if (
                kwargs["kind"] is RunEventKind.LEARNING_COMMITTED
                and getattr(kwargs["registration"].execution_scope, "learning_baseline", None) is not None
            ):
                for attack, expected_error in (
                    ("credit_reset", "credit update does not match durable history"),
                    ("state_discard", "checkpoint contains unadmitted changes"),
                ):
                    forged = _thaw_json(kwargs["payload"])
                    if attack == "credit_reset":
                        forged["receipt"]["measurement"].update(
                            inherited_credit=0, credit_before=0, credit_after=0,
                        )
                    else:
                        forged["state"]["records"] = []
                    forged["receipt"]["receipt_id"] = identity("receipt", {
                        key: value for key, value in forged["receipt"].items()
                        if key != "receipt_id"
                    })
                    with pytest.raises(ValueError, match=expected_error):
                        original_new_event(**{**kwargs, "payload": forged})
                    refused.append(attack)
            return original_new_event(**kwargs)

        monkeypatch.setattr(service.runs, "_new_event", probe_publication)
        before_calls, before_runs = len(calls), executor.calls
        result = await service.run(spec)
        assert result["execution_status"] == "succeeded", result
        assert result["run_id"] != source_id.value
        assert executor.calls == before_runs + 1
        assert len(calls) == before_calls + 2
        assert refused == ["credit_reset", "state_discard"]
        assert "selected_action" not in calls[before_calls]
        assert "selected_action" in calls[before_calls + 1]
        registration = service.runs.read_registration(OpaqueId(result["run_id"]))
        target = registration.execution_scope.target_ref(registration.logical_run_id.value)
        assert target.unit_index == 1
        assert target.episode_id != selected["unit_ref"]["episode_id"]
        # The generic executor's preparation boundary must independently verify
        # this too; using the shared service is not a substitute for admission.
        inputs = builds.inspection_inputs_for_receipt(receipt.receipt_id)
        forged_baseline = _thaw_json(registration.execution_scope.learning_baseline)
        forged_baseline["source_admission"]["goal_scoper"] = "custom.unverified_scoper"
        forged_registration = replace(registration, execution_scope=replace(
            registration.execution_scope, learning_baseline=forged_baseline,
        ))
        with pytest.raises(RuntimeLinkError, match="source admission differs"):
            prepare_source_package(
                forged_registration, builds.verify_source_package(inputs.manifest),
            )
        for prompt in calls[before_calls:]:
            bundle = prompt["typed_unit_input"]
            assert bundle["next_ordinal"] == 1
            assert bundle["reused_learning"]["inherited_credit"] == prior_credit
            assert bundle["reused_learning"]["new_yield_from_import"] == 0
            lesson, = bundle["applicable_lessons"]
            assert lesson["record_id"] == original_lesson["record_id"]
            assert lesson["evidence_refs"] == list(original_lesson["evidence_refs"])
            assert lesson["scope"]["key"] == target.episode_id
            assert lesson["equivalence_key"] != original_lesson["equivalence_key"]

        events = service.runs.read_audit_log(registration.run_id)
        unit, = [event for event in events if event.kind is RunEventKind.UNIT_COMPLETED]
        committed, = [event for event in events if event.kind is RunEventKind.LEARNING_COMMITTED]
        assert unit.payload["unit_ref"] == target.as_record()
        assert not any(event.kind is RunEventKind.EPISODE_COMPLETED for event in events)
        assert "completion" not in result["typed_status"]
        assert "workflow_result" not in result["typed_status"]
        measurement = committed.payload["receipt"]["measurement"]
        assert measurement["realized_yield"] == 0
        assert measurement["inherited_credit"] == prior_credit
        assert measurement["credit_before"] == measurement["credit_after"] == prior_credit
        assert not committed.payload["receipt"]["admission"]["transitions"]
        assert len(committed.payload["state"]["records"]) == 1
        assert tuple(event.as_record() for event in service.runs.read_audit_log(source_id)) == original_audit
        scoped_audit = tuple(event.as_record() for event in events)
        assert await service.run(spec) == result
        assert len(calls) == before_calls + 2
        assert executor.calls == before_runs + 1
        assert tuple(event.as_record() for event in service.runs.read_audit_log(registration.run_id)) == scoped_audit
        assert tuple(event.as_record() for event in service.runs.read_audit_log(source_id)) == original_audit

        # Numerical evaluation of the scoped Run must also seed its inherited
        # observations. Replaying only its new duplicate would change the
        # controller's estimate; neither kind of reused evidence earns credit.
        saved = save_recording(artifacts, service.runs, result["run_id"])
        observed = read_recording(service.runs, result["run_id"])
        numerical = deepcopy(raw)
        numerical.update(
            mode="numerical", recording_ref=saved, launch_ref=None,
            start={"kind": "saved_inputs", "artifact_ref": saved, "input_payload": {}},
            boundary={"children": "reuse", "parent_context_ref": saved},
        )
        numerical["scope"].update(
            kind="episode", invocation_path=observed["invocations"][0]["episode_path"],
        )
        numerical_spec = ExperimentSpec.from_record(numerical)
        numerical_preview = service.preview(numerical_spec)
        assert numerical_preview["resolved"], numerical_preview["gaps"]
        inherited_preview, = numerical_preview["numerical_inputs"]["invocations"]
        assert inherited_preview["reused_unit_count"] == 1
        replay = await service.run(numerical_spec)
        assert replay["execution_status"] == "evaluated", replay
        assert replay["controller_comparison"] == "reproduced"
        assert replay["source_run_id"] == result["run_id"]
        assert "run_id" not in replay
        assert not replay["progress"]["admitted"]
        invocation, = replay["invocations"]
        assert invocation["reused_unit_count"] == 1
        assert invocation["inherited_history_ref"] == {
            key: _thaw_json(registration.execution_scope.learning_baseline[key])
            for key in ("source_registration_ref", "through_event_ref")
        }
        assert inherited_preview["inherited_history_ref"] == invocation["inherited_history_ref"]
        assert all(item["matches"] for item in invocation["units"])
        assert invocation["units"][-1]["recorded"] == _thaw_json(committed.payload["receipt"]["numeric_step"])
        assert await service.run(numerical_spec) == replay
        assert len(calls) == before_calls + 2
        assert executor.calls == before_runs + 1
        assert tuple(event.as_record() for event in service.runs.read_audit_log(registration.run_id)) == scoped_audit
        assert tuple(event.as_record() for event in service.runs.read_audit_log(source_id)) == original_audit
