"""Single-unit scope through the shared CLI, planner, linker and Run store.

Generated Episodes execute, including declared children. This reuses the
in-process, scripted-model fixture; it does not establish OS confinement or
live reasoning quality.
"""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from agent.episode_contracts import OpaqueId
from agent.episode_contracts import EpisodeCreationSpec
from episode_builder.service import EpisodeBuilder
from episode_library.testing import (
    DESIGN,
    testing_learning_contract as learning_contract,
)
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunTerminalStatus
from episode_runtime.continuation import InterruptedRunRef
from episode_runtime.protocol import episode_id_for_path
from episode_runtime.records.experiments import read_record
from episode_runtime.testing_harness.contracts import ExperimentSpec
from episode_runtime.testing_harness.execution import register_build
from episode_runtime.testing_harness.inputs import workflow_template
from episode_runtime.testing_harness.planning import preview_experiment
from episode_runtime.testing_harness.recordings import read_recording, save_recording
from episode_runtime.testing_harness.session import ExperimentAccessError, ExperimentSession
from function_library.testing_contract import TestingContract as Access
from llm_call_library.transport import ModelTransportResponse, model_transport_scope
from llm_call_library import CallOptions
from openchia_cli.episode_test_command import main
from tests.episode_runtime.conftest import claim_store, numerical_control, oid
from tests.episode_runtime.test_reasoning_workflow import (
    _approved_request,
    _module_response,
    _plan_response,
)
from tests.episode_runtime.testing_harness.test_scoped_execution import nested_experiment


async def boundary_through_session(service, raw, whole, tmp_path, unit):
    """Real approved host session; the caller-start event is a fixture."""
    target = {
        key: raw[key]
        for key in (
            "candidate_ref",
            "build_receipt_ref",
            "environment_ref",
            "launch_ref",
            "campaign_ref",
        )
    }
    target.update(
        requirements=[
            {key: row[key] for key in ("requirement_ref", "measure_ref")}
            for row in raw["requirements"]
        ],
        recording_refs=[],
        parent_context_refs=[],
    )
    request = _approved_request(
        tmp_path,
        duet_id=oid("unit_tester"),
        reference=DESIGN,
        allowed_capabilities=("episode_testing",),
        spec=EpisodeCreationSpec(
            goal="Inspect one declared unit",
            progress="Admitted experimental evidence",
            stopping="Host numerical decision",
            numeric_control=numerical_control(0.9),
            execution_capability_names=("episode_testing",),
            testing=Access(
                {"candidate": target},
                ("workflow", "unit"),
                ("live_fresh", "live_saved"),
            ),
            epistemic=learning_contract(
                goal_class="testing",
                domain="unit",
                environment={"fixture": "unit_scope"},
            ),
        ),
    )

    async def builder_model(request):
        prompt = json.loads(request.messages[-1]["content"])
        response = (
            _plan_response(prompt, testing=True)
            if "node" in prompt
            else _module_response(prompt)
        )
        return ModelTransportResponse(text=json.dumps(response), route={})

    with model_transport_scope(builder_model):
        receipt = await EpisodeBuilder(
            store=service.builds,
            planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"selector": {}, "executor": {}},
        ).build(request)
    assert receipt.materialized, [row.as_record() for row in receipt.deficits]
    inputs = service.builds.inspection_inputs_for_receipt(receipt.receipt_id)
    source = service.runs.read_registration(OpaqueId(whole["run_id"]))
    registration, _ = register_build(
        service.executor,
        service.builds,
        inputs,
        workflow_template(request.frozen_workflow, None),
        source.runtime_policy,
    )
    claim_store(service.executor.root, registration, store=service.runs)
    path = [
        {"grain": inputs.plan.nodes[0].grain_name, "key": registration.run_id.value}
    ]
    caller = episode_id_for_path(registration.run_id, path)
    service.runs.append_event(
        run_id=registration.run_id,
        origin=RunEventOrigin.WORKER,
        sender_sequence=0,
        kind=RunEventKind.EPISODE_STARTED,
        episode_id=caller,
        payload={"episode_path": path},
    )
    session = ExperimentSession(
        service=service, registration=registration, inputs=inputs
    )

    async def exchange(operation, payload):
        return await session.exchange(
            episode_id=caller, episode_path=path, operation=operation, payload=payload
        )

    owned = await exchange("run", {"spec": raw})
    assert owned["run_id"] == whole["run_id"]
    result = await exchange(
        "boundary",
        {
            "experiment_id": whole["experiment_id"],
            "unit_id": unit["unit_ref"]["unit_id"],
        },
    )
    assert session._recording_allowed(caller.value, target, result["recording_ref"])
    complete = save_recording(service.artifacts, service.runs, whole["run_id"])
    assert not session._recording_allowed(caller.value, target, complete)
    assert session._boundary_allowed(caller.value, result["parent_context_ref"])
    malformed = await exchange(
        "boundary",
        {
            "experiment_id": whole["experiment_id"],
            "unit_id": unit["unit_ref"]["unit_id"],
            "episode_id": unit["unit_ref"]["episode_id"],
        },
    )
    assert malformed["operation_status"] == "rejected"
    history = await exchange("history", {"query": {}})
    access = read_record(
        service.artifacts, "access", run_id=registration.run_id.value,
        episode_id=caller.value, key=whole["experiment_id"],
    )
    service.runs.finalize_run(
        run_id=registration.run_id,
        origin=RunEventOrigin.HOST,
        sender_sequence=0,
        terminal_status=RunTerminalStatus.INTERRUPTED,
        typed_status={"reason": "host access fixture; no testing Episode executed"},
    )
    original_audit = service.runs.read_audit_log(registration.run_id)
    resumed = replace(
        registration,
        resume_from=InterruptedRunRef.from_run(service.runs, registration.run_id),
    )
    claim_store(service.executor.root, resumed, store=service.runs)
    session = ExperimentSession(service=service, registration=resumed, inputs=inputs)
    assert await exchange("results", {"experiment_id": whole["experiment_id"]}) == owned
    assert await exchange("history", {"query": {}}) == history
    assert session._recording_allowed(caller.value, target, result["recording_ref"])
    assert session._boundary_allowed(caller.value, result["parent_context_ref"])
    assert await exchange("run", {"spec": raw}) == owned
    assert read_record(
        service.artifacts, "access", run_id=registration.run_id.value,
        episode_id=caller.value, key=whole["experiment_id"],
    ) == access
    assert read_record(
        service.artifacts, "access", run_id=resumed.run_id.value,
        episode_id=caller.value, key=whole["experiment_id"],
    ) is None
    recording = await exchange("recording", {"experiment_id": whole["experiment_id"]})
    assert recording["recording_ref"] == complete
    assert read_record(
        service.artifacts, "recording_access", run_id=registration.run_id.value,
        episode_id=caller.value, key=complete,
    ) is not None
    assert read_record(
        service.artifacts, "recording_access", run_id=resumed.run_id.value,
        episode_id=caller.value, key=complete,
    ) is None
    assert service.runs.read_audit_log(registration.run_id) == original_audit
    assert service.runs.read_committed_prefix(resumed.run_id) == ()

    # Identical code in a separate execution is not the same logical caller.
    unrelated = replace(
        registration,
        launch_request=replace(registration.launch_request, request_id=oid("unrelated_tester").value),
    )
    claim_store(service.executor.root, unrelated, store=service.runs)
    unrelated_path = [{"grain": path[0]["grain"], "key": unrelated.run_id.value}]
    unrelated_caller = episode_id_for_path(unrelated.run_id, unrelated_path)
    service.runs.append_event(
        run_id=unrelated.run_id, origin=RunEventOrigin.WORKER, sender_sequence=0,
        kind=RunEventKind.EPISODE_STARTED, episode_id=unrelated_caller,
        payload={"episode_path": unrelated_path},
    )
    with pytest.raises(ExperimentAccessError, match="not assigned"):
        await ExperimentSession(service=service, registration=unrelated, inputs=inputs).exchange(
            episode_id=unrelated_caller, episode_path=unrelated_path,
            operation="results", payload={"experiment_id": whole["experiment_id"]},
        )
    service.runs.append_event(
        run_id=resumed.run_id, origin=RunEventOrigin.WORKER, sender_sequence=0,
        kind=RunEventKind.EPISODE_COMPLETED, episode_id=caller,
        payload={"episode_path": path},
    )
    with pytest.raises(ExperimentAccessError, match="no active recorded invocation"):
        await exchange("results", {"experiment_id": whole["experiment_id"]})
    return result


@pytest.mark.asyncio
async def test_unit_selection_observes_only_one_unit_without_claiming_episode_completion(
    tmp_path, run_store, monkeypatch, capsys
):
    async with nested_experiment(tmp_path, run_store, monkeypatch) as (
        service,
        raw,
        whole,
        calls,
    ):
        source = read_recording(service.runs, whole["run_id"])

        def capture(unit):
            assert (
                main([
                    "boundary",
                    "--run-store",
                    str(service.runs.root),
                    "--run-id",
                    whole["run_id"],
                    "--duet-store",
                    str(tmp_path / "duet.db"),
                    "--unit-id",
                    unit["unit_ref"]["unit_id"],
                ])
                == 0
            )
            return json.loads(capsys.readouterr().out)

        def experiment_for(boundary, entry, members):
            value = deepcopy(raw)
            value.update(mode="live_saved", recording_ref=None)
            value["scope"].update(
                kind="unit",
                entry_local_id=entry,
                included_local_ids=members,
                unit_label=boundary["unit_label"],
                invocation_path=boundary["invocation_path"],
            )
            value["boundary"]["parent_context_ref"] = boundary["parent_context_ref"]
            value["start"] = {
                "kind": "saved_inputs",
                "artifact_ref": boundary["recording_ref"],
                "input_payload": {},
            }
            return value

        for entry, members in (("root", ["root", "group", "leaf"]), ("leaf", ["leaf"])):
            invocation = next(
                row for row in source["invocations"] if row["grain"] == entry
            )
            units = [
                row
                for row in source["units"]
                if row["unit_ref"]["episode_id"] == invocation["episode_id"]
            ]
            first = next(row for row in units if row["unit_ref"]["unit_index"] == 0)
            boundary = capture(first)
            assert boundary["unit_ref"] == first["unit_ref"]
            assert boundary["initial_state_reproducible"]
            indexed = service.runs.read_inventory(OpaqueId(whole["run_id"]), {
                "kind": "units", "episode_id": invocation["episode_id"],
            })["items"]
            assert boundary["reconstruction_prefix"] == indexed[0]["reconstruction_prefix"]
            assert boundary["reconstruction_prefix"]["through_event_ref"] == invocation["event_ref"]
            if entry == "root":
                assert (
                    await boundary_through_session(service, raw, whole, tmp_path, first)
                    == boundary
                )
            selected = experiment_for(boundary, entry, members)
            plan = preview_experiment(
                ExperimentSpec.from_record(selected),
                builds=service.builds,
                artifacts=service.artifacts,
                runs=service.runs,
            )
            assert plan["resolved"], plan["gaps"]
            call_count = len(calls)
            result = await service.run(ExperimentSpec.from_record(selected))
            assert result["execution_status"] == "succeeded", result
            assert len(calls) > call_count
            assert "completion" not in result["typed_status"]
            assert "workflow_result" not in result["typed_status"]
            registration = service.runs.read_registration(OpaqueId(result["run_id"]))
            target = registration.execution_scope.target_ref(result["run_id"])
            events = service.runs.read_audit_log(registration.run_id)
            owned = [
                event
                for event in events
                if event.episode_id == OpaqueId(target.episode_id)
            ]
            observed = [
                event for event in owned if event.kind is RunEventKind.UNIT_COMPLETED
            ]
            assert len(observed) == 1
            assert observed[0].payload["unit_ref"] == target.as_record()
            assert not any(
                event.kind is RunEventKind.EPISODE_COMPLETED for event in owned
            )
            # The parent unit runs its declared children, then returns while its
            # own numerical controller still says to continue.
            if entry == "root":
                assert not result["typed_status"]["unit_result"]["controller_step"][
                    "stop"
                ]
                completed = [
                    event
                    for event in events
                    if event.kind is RunEventKind.EPISODE_COMPLETED
                ]
                assert len(completed) == 2
                later = next(row for row in units if row["unit_ref"]["unit_index"] == 1)
                later_boundary = capture(later)
                assert not later_boundary["initial_state_reproducible"]
                assert later_boundary["reconstruction_prefix"] == indexed[1]["reconstruction_prefix"]
                assert later_boundary["reconstruction_prefix"]["through_event_ref"] == first["event_ref"]
                assert not later_boundary["reconstruction_prefix"]["restoration_verified"]
                later_spec = experiment_for(later_boundary, entry, members)
                calls_before = service.executor.calls
                unavailable = await service.run(ExperimentSpec.from_record(later_spec))
                assert unavailable["execution_status"] == "unavailable"
                assert any(
                    "restoration" in gap["detail"]
                    for gap in unavailable["plan"]["gaps"]
                )
                assert service.executor.calls == calls_before

            calls_before = service.executor.calls
            again = await service.run(ExperimentSpec.from_record(selected))
            assert again == result
            assert service.executor.calls == calls_before
            assert len(calls) > call_count
            changed = deepcopy(selected)
            changed["scope"]["unit_label"] = "a different unit"
            refused = await service.run(ExperimentSpec.from_record(changed))
            assert refused["execution_status"] == "unavailable"
            assert service.executor.calls == calls_before
            if entry == "leaf":
                playback = deepcopy(selected)
                playback.update(
                    mode="recorded",
                    recording_ref=boundary["recording_ref"],
                    launch_ref=None,
                )
                live_calls = len(calls)
                replayed = await service.run(ExperimentSpec.from_record(playback))
                # This reasoning prompt includes a Run-local learning identity.
                # A new Run must expose that mismatch, not rewrite the prompt.
                assert replayed["execution_status"] == "invalid"
                assert (
                    replayed["recorded_execution"]["divergence"]["kind"]
                    == "unmatched_external_request"
                )
                assert not replayed["recorded_execution"]["reused_responses"]
                assert len(calls) == live_calls
