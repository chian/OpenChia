"""Real generated nested Episodes through the shared harness, in-process.

The external model and confinement attestation are fixtures. Unlike the transport
fixture, generated sources really execute; this proves scoped execution and
recording behavior, not live reasoning or OS confinement.
"""

from copy import deepcopy
from contextlib import asynccontextmanager
import asyncio
import json
import sys

import pytest

from agent.duet_store import DuetStore
from agent.episode_contracts import (
    EpisodeCreationSpec,
    EpisodeDesignSpec,
    EpisodeWorkflowSpec,
    OpaqueId,
)
from agent.episode_launch import resolve_launch
from tests.episode_runtime.testing.launch_fixture import FixtureLaunchHost
from episode_builder.service import EpisodeBuilder
from episode_builder.store import BuildStore
from episode_library.inquiry import inquiry_contract
from episode_runtime import protocol
from episode_runtime.broker import admit_model_response, model_request_record
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunTerminalStatus
from episode_runtime.exchanges import (
    broker_model_request,
    broker_experiment_request,
    broker_refinement_request,
    broker_learning_request,
)
from episode_runtime.learning_broker import LearningBroker
from episode_runtime.linker import (
    prepare_source_package,
    current_runtime_episode_id,
    current_runtime_episode_path,
)
from episode_runtime.scoped import validate_execution_path
from episode_runtime.testing.boundaries import capture_boundary
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.planning import preview_experiment
from episode_runtime.testing.playback import ReplayDivergence
from episode_runtime.testing.recordings import read_recording
from episode_runtime.testing.service import ExperimentService
from episode_runtime.records.experiments import put_data
from episode_runtime.worker import runtime_collaborators
from function_library.episode_calls import BUILD_REPEATABLE_CHILD
from function_library.reasoning_transport import reasoning_transport_scope
from function_library.refinement_transport import refinement_transport_scope
from function_library.testing import experiment_transport_scope
from handoff_library import ADMIT_CHILD_RESULT, ADMIT_PARENT_REQUEST
from llm_call_library.transport import ModelTransportResponse, model_transport_scope
from llm_call_library import CallOptions
from openchia_cli.episode_test_command import main
from tests.episode_runtime.conftest import claim_store, numerical_control
from tests.episode_runtime.test_reasoning_workflow import (
    _approved_request,
    _plan_response,
    _module_response,
    _binding,
)
from tests.episode_runtime.testing.test_experiment_planning import experiment
from tests.episode_runtime.testing.test_measurements import ResultOnlyExecutor
from tests.episode_runtime.testing.test_recorded_execution import _Channel


CHILDREN = """
from method_loop import EpisodeGoal, EpisodeRequest, ChildEpisodeUnit
from method_loop.identities import EpisodeRef
from handoff_library import ParentRequest
from function_library.epistemic_schemas import identity
from function_library.reasoning import HostReceiptController

class Children(ReasoningSource):
    def __init__(self, request, goal_view, collaborators, builders):
        super().__init__(goal_view["goal"], **dict(BINDING.open_source.arguments))
        self.request, self.collaborators, self.builders = request, collaborators, builders
        self.child_run = False
    async def next(self, view):
        if self.child_run:
            return await super().next(view)
        self.child_run = True
        slot = BINDING.child_slots[0]
        goal = EpisodeGoal.child(self.request.goal, objective="Inspect the scoped inquiry", result_contract=RESULT_PAYLOAD_CONTRACT.as_record())
        path = (*view.path, (slot.name, "selected"))
        child_id = EpisodeRef(view.episode_ref.run_id, path).episode_id
        request = EpisodeRequest(goal, ParentRequest(
            request_id=identity("request", {"child": child_id}),
            parent_episode_id=view.episode_ref.episode_id, child_episode_id=child_id,
            goal_id=goal.goal_id, child_interface=slot.accepted_interfaces[0],
        ))
        child = self.builders[slot.name]("selected", request, MappingProxyType({"goal": goal.objective}), self.collaborators)
        # Child completion does not award parent progress or finish the parent.
        # The parent subsequently executes its own host-governed reasoning loop.
        return ChildEpisodeUnit(child, lambda result, completion, request: HostReceiptController().state())
"""


async def nested_build(tmp_path):
    parent = EpisodeCreationSpec(
        goal="Inspect the scoped inquiry",
        progress="Child's admitted finding",
        stopping="Child's host numerical decision",
        numeric_control=numerical_control(0.9),
        epistemic=inquiry_contract(
            goal_class="inquiry",
            domain="scope_fixture",
            environment={"dataset": "empty"},
        ),
    )
    leaf = EpisodeCreationSpec(
        goal="Inspect the scoped inquiry",
        progress="Admitted evidence",
        stopping="Host numerical decision",
        numeric_control=numerical_control(0.9),
        epistemic=inquiry_contract(
            goal_class="inquiry",
            domain="scope_fixture",
            environment={"dataset": "empty"},
        ),
    )
    workflow = EpisodeWorkflowSpec((
        EpisodeDesignSpec("root", None, parent),
        EpisodeDesignSpec("group", "root", parent),
        EpisodeDesignSpec("leaf", "group", leaf),
    ))
    request = _approved_request(tmp_path, workflow=workflow)
    builds = BuildStore(tmp_path)

    async def builder_model(request):
        prompt = json.loads(request.messages[-1]["content"])
        if "node" in prompt:
            response = _plan_response(prompt)
            response["interface"] = "test." + prompt["node"]["local_id"]
            response["selected_function_bindings"][0].update(
                prompt["structural_binding_contract"][
                    "required_request_admission_pointer"
                ]
            )
            for child in prompt["direct_children"]:
                slot = child["local_id"]
                roles = {
                    "build_child": BUILD_REPEATABLE_CHILD,
                    "prepare_request": ADMIT_PARENT_REQUEST,
                    "receive_result": ADMIT_CHILD_RESULT,
                }
                response["selected_function_bindings"].extend(
                    _binding(
                        f"edge.{slot}.{role}",
                        function,
                        {"payload_contract": child["result_payload_contract"]}
                        if role == "receive_result"
                        else {},
                    )
                    for role, function in roles.items()
                )
                response["child_slots"].append({
                    "slot_name": slot,
                    "child_local_id": slot,
                    "child_interface": child["interface"],
                    "request_payload_contract": child["request_payload_contract"],
                    "result_payload_contract": child["result_payload_contract"],
                    "build_child": "invoke declared child",
                    "prepare_request": "preserve parent goal",
                    "receive_result": "forward typed host receipt",
                    "basis": "scope fixture",
                })
        else:
            children = bool(prompt.get("direct_edges"))
            response = _module_response(
                prompt,
                source_expression="Children(request, goal_view, collaborators, child_builders)"
                if children
                else None,
                extra_source=CHILDREN if children else "",
            )
        return ModelTransportResponse(text=json.dumps(response), route={})

    with model_transport_scope(builder_model):
        receipt = await EpisodeBuilder(
            store=builds,
            planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"selector": {}, "executor": {}},
        ).build(request)
    assert receipt.materialized, [row.as_record() for row in receipt.deficits]
    return request, builds, receipt


class LinkedExecutor(ResultOnlyExecutor):
    async def execute(
        self, *, registration, source_package_path, model_broker, **kwargs
    ):
        self.calls += 1
        claim_store(self.root, registration, store=self.run_store)
        prepared = prepare_source_package(registration, source_package_path)
        broker = LearningBroker(self.run_store, registration, source_package_path)
        binding = protocol.ProtocolBinding.from_registration(registration)
        channel = _Channel(binding)
        worker = protocol.FrameEncoder(
            sender=protocol.FrameSender.WORKER, binding=binding
        )
        sequence = 0
        responses = []
        host_error = None
        publish = channel.publish

        async def capture(prepared):
            responses.append(protocol._thaw_json(prepared[0].body))
            return await publish(prepared)

        channel.publish = capture

        def frame(kind, body):
            nonlocal sequence
            value = protocol.decode_frame(
                worker.encode(kind, body),
                sender=protocol.FrameSender.WORKER,
                binding=binding,
                expected_sequence=sequence,
            )
            sequence += 1
            return value

        async def event_sink(kind, episode_id, payload):
            event = frame(
                "run_event",
                {
                    "event_kind": kind.value,
                    "episode_id": episode_id.value,
                    "payload": payload,
                },
            )
            if kind is RunEventKind.EPISODE_STARTED:
                validate_execution_path(registration, payload["episode_path"])
            self.run_store.append_event(
                run_id=registration.run_id,
                origin=RunEventOrigin.WORKER,
                sender_sequence=event.sender_sequence,
                kind=kind,
                episode_id=episode_id,
                payload=payload,
            )

        async def learning(operation, payload):
            value = frame(
                "learning_request",
                {
                    "episode_id": current_runtime_episode_id().value,
                    "episode_path": current_runtime_episode_path(),
                    "request_id": OpaqueId.mint(
                        "learning_request", f"call-{sequence}"
                    ).value,
                    "operation": operation,
                    "payload": payload,
                },
            )
            await broker_learning_request(
                run_store=self.run_store,
                registration=registration,
                channel=channel,
                frame=value,
                session=broker,
            )
            return responses[-1]["response"]

        async def experiment(operation, payload):
            value = frame(
                "experiment_request",
                {
                    "episode_id": current_runtime_episode_id().value,
                    "episode_path": current_runtime_episode_path(),
                    "request_id": OpaqueId.mint(
                        "experiment_request", f"call-{sequence}"
                    ).value,
                    "operation": operation,
                    "payload": payload,
                },
            )
            await broker_experiment_request(
                run_store=self.run_store,
                registration=registration,
                channel=channel,
                frame=value,
                session=kwargs.get("experiment_session"),
            )
            return responses[-1]["response"]

        async def refinement(operation, payload):
            value = frame(
                "refinement_request",
                {
                    "episode_id": current_runtime_episode_id().value,
                    "episode_path": current_runtime_episode_path(),
                    "request_id": OpaqueId.mint(
                        "refinement_request", f"call-{sequence}"
                    ).value,
                    "operation": operation,
                    "payload": payload,
                },
            )
            await broker_refinement_request(
                run_store=self.run_store,
                registration=registration,
                channel=channel,
                frame=value,
                session=kwargs.get("refinement_session"),
            )
            return responses[-1]["response"]

        async def model(request):
            nonlocal host_error
            path = current_runtime_episode_path()
            validate_execution_path(registration, path)
            value = frame(
                "model_request",
                {
                    "episode_id": current_runtime_episode_id().value,
                    "episode_path": path,
                    "model_request_id": OpaqueId.mint(
                        "model_request", f"scope-{sequence}"
                    ).value,
                    "request": model_request_record(request),
                },
            )
            try:
                await broker_model_request(
                    run_store=self.run_store,
                    registration=registration,
                    channel=channel,
                    frame=value,
                    model_broker=model_broker,
                )
            except ReplayDivergence as exc:
                host_error = exc
                raise
            return admit_model_response(responses[-1]["response"])

        try:
            activated = prepared.activate()
            with (
                model_transport_scope(model),
                reasoning_transport_scope(learning),
                experiment_transport_scope(experiment),
                refinement_transport_scope(refinement),
            ):
                result = await activated.link(
                    event_sink=event_sink,
                    collaborators=runtime_collaborators(prepared.plan),
                ).run()
            terminal_status = RunTerminalStatus(result["outcome"])
            if terminal_status is RunTerminalStatus.SUCCEEDED:
                broker.validate_completion(result)
            if kwargs.get("refinement_session") is not None:
                kwargs["refinement_session"].validate_return(terminal_status.value, result)
            return self.run_store.finalize_run(
                run_id=registration.run_id,
                origin=RunEventOrigin.HOST,
                sender_sequence=channel.sequence,
                terminal_status=terminal_status,
                typed_status=result,
            )
        except asyncio.CancelledError:
            return self.run_store.finalize_run(
                run_id=registration.run_id,
                origin=RunEventOrigin.HOST,
                sender_sequence=channel.sequence,
                terminal_status=RunTerminalStatus.CANCELLED,
                typed_status={"outcome": "cancelled", "reason": "test caller cancelled"},
            )
        except Exception as exc:
            # In this in-process fixture the worker's call adapter can wrap
            # transport errors. The real host retains its own broker error;
            # preserve that separation before publishing terminal evidence.
            if host_error is None:
                raise
            self.run_store.finalize_run(
                run_id=registration.run_id,
                origin=RunEventOrigin.HOST,
                sender_sequence=channel.sequence,
                terminal_status=RunTerminalStatus.INVALID,
                typed_status={
                    "outcome": "invalid",
                    "reason": "recorded_response_divergence",
                },
            )
            raise host_error from exc
        finally:
            for module in prepared.modules.values():
                sys.modules.pop(module.module_name, None)


@asynccontextmanager
async def nested_experiment(tmp_path, run_store, monkeypatch):
    request, builds, receipt = await nested_build(tmp_path)
    executor = LinkedExecutor(tmp_path / "execution", run_store[1].runtime_identity)
    calls = []

    def model(route, key, request, cancel, progress):
        prompt = json.loads(request.messages[-1]["content"])
        calls.append(prompt)
        result = {
            "action_class": "discover",
            "action_inputs": {},
            "retry_reason": "Inspect remaining uncertainty",
        }
        if "selected_action" in prompt:
            result = {
                "action_class": "discover",
                "action_inputs": {},
                "status": "inconclusive",
                "expected_observation": "new evidence",
                "observed_outcome": "no additional evidence",
                "candidate_lessons": [],
                "entities": [],
                "revisions": [],
            }
        return json.dumps(result), route["model"]

    monkeypatch.setattr("agent.episode_launch_transport._invoke", model)
    launch = resolve_launch({
        "project": "scope-fixture",
        "project_root": str(tmp_path),
        "env_files": [],
        "routes": {
            "local": {
                "provider": "custom",
                "model": "fixture",
                "base_url": "https://example.org/v1",
                "api_mode": "chat_completions",
                "auth": {"kind": "none"},
            }
        },
        "model_slots": {"selector": "local", "executor": "local"},
        "builder_slots": {"planning": "selector", "emission": "executor"},
    })
    with DuetStore(tmp_path / "duet.db") as artifacts:
        raw = experiment(artifacts, request, receipt)
        FixtureLaunchHost(artifacts, builds, request.frozen_workflow.duet_id.value).approve_fixture(launch)
        raw["scope"].update(
            entry_local_id="root", included_local_ids=["root", "group", "leaf"]
        )
        raw["launch_ref"] = put_data(
            artifacts, request.frozen_workflow.duet_id.value, "launch", launch.record
        )
        service = ExperimentService(
            artifacts=artifacts,
            builds=builds,
            runs=executor.run_store,
            executor=executor,
        )
        whole = await service.run(ExperimentSpec.from_record(raw))
        assert whole["execution_status"] == "succeeded", whole
        yield service, raw, whole, calls


@pytest.mark.asyncio
async def test_saved_invocation_runs_only_selected_code_and_preserves_nesting(
    tmp_path, run_store, monkeypatch, capsys
):
    async with nested_experiment(tmp_path, run_store, monkeypatch) as (
        service, raw, whole, calls
    ):
        artifacts, builds, executor = service.artifacts, service.builds, service.executor
        recorded = read_recording(executor.run_store, whole["run_id"])
        assert {row["grain"] for row in recorded["invocations"]} == {
            "root",
            "group",
            "leaf",
        }
        owner = executor.run_store.read_registration(OpaqueId(whole["run_id"])).duet_id.value
        indexed = service.inventory(
            artifacts, executor.run_store, duet_id=owner,
            source={"kind": "experiment", "experiment_id": whole["experiment_id"]}, query={},
        )
        assert [row["episode_path"] for row in indexed["items"]] == [row["episode_path"] for row in recorded["invocations"]]
        assert all(row["entry_context"] == "requires_boundary_validation" for row in indexed["items"])
        units, query = [], {"kind": "units"}
        while query is not None:
            indexed_units = service.inventory(
                artifacts, executor.run_store, duet_id=owner,
                source={"kind": "experiment", "experiment_id": whole["experiment_id"]}, query=query,
            )
            units.extend(indexed_units["items"])
            query = indexed_units["next_query"]
        assert [row["unit_ref"] for row in units] == [row["unit_ref"] for row in recorded["units"]]
        source_calls = len(calls)
        for kind, entry, included in (
            ("episode", "leaf", ["leaf"]),
            ("nested", "group", ["group", "leaf"]),
        ):
            invocation = next(
                row for row in recorded["invocations"] if row["grain"] == entry
            )
            from episode_runtime.testing.recordings import save_recording

            exact_ref = save_recording(artifacts, executor.run_store, whole["run_id"], episode_ids=[invocation["episode_id"]])
            narrow_inventory = service.inventory(
                artifacts, executor.run_store, duet_id=owner,
                source={"kind": "recording", "recording_ref": exact_ref}, query={},
            )
            assert [row["episode_id"] for row in narrow_inventory["items"]] == [invocation["episode_id"]]
            with pytest.raises(ValueError, match="outside its recording selector"):
                service.inventory(
                    artifacts, executor.run_store, duet_id=owner,
                    source={"kind": "recording", "recording_ref": exact_ref},
                    query={"episode_id": recorded["invocations"][0]["episode_id"]},
                )
            assert (
                main([
                    "boundary",
                    "--run-store",
                    str(executor.run_store.root),
                    "--run-id",
                    whole["run_id"],
                    "--duet-store",
                    str(tmp_path / "duet.db"),
                    "--episode-id",
                    invocation["episode_id"],
                ])
                == 0
            )
            boundary = json.loads(capsys.readouterr().out)
            assert boundary["initial_state_reproducible"]
            selected = deepcopy(raw)
            selected.update(mode="live_saved", recording_ref=None)
            selected["scope"].update(
                kind=kind,
                entry_local_id=entry,
                included_local_ids=included,
                invocation_path=boundary["invocation_path"],
            )
            selected["boundary"]["parent_context_ref"] = boundary["parent_context_ref"]
            selected["start"] = {
                "kind": "saved_inputs",
                "artifact_ref": boundary["recording_ref"],
                "input_payload": {},
            }
            preview = preview_experiment(
                ExperimentSpec.from_record(selected),
                artifacts=artifacts,
                builds=builds,
                runs=executor.run_store,
            )
            assert preview["resolved"], preview["gaps"]
            if kind == "nested":
                omitted_child = deepcopy(selected)
                omitted_child["scope"]["included_local_ids"] = [entry]
                rejected = preview_experiment(
                    ExperimentSpec.from_record(omitted_child),
                    artifacts=artifacts,
                    builds=builds,
                    runs=executor.run_store,
                )
                assert not rejected["resolved"]
                assert any(
                    gap["kind"] == "child_outside_scope" for gap in rejected["gaps"]
                )
            forged = deepcopy(selected)
            changed = deepcopy(preview["execution_scope"]["boundary"])
            changed["goal_view"] = {"goal": "A different question"}
            forged["boundary"]["parent_context_ref"] = put_data(
                artifacts, owner, "boundary", changed
            )
            rejected = preview_experiment(
                ExperimentSpec.from_record(forged),
                artifacts=artifacts,
                builds=builds,
                runs=executor.run_store,
            )
            assert not rejected["resolved"]
            assert any(
                gap["kind"] == "invocation_boundary_unavailable"
                for gap in rejected["gaps"]
            )
            result = await service.run(ExperimentSpec.from_record(selected))
            assert result["execution_status"] == "succeeded", result
            executed = read_recording(executor.run_store, result["run_id"])
            assert {row["grain"] for row in executed["invocations"]} == set(included)
            assert len(calls) > source_calls
            source_calls = len(calls)
            assert result["typed_status"]["execution_scope"]["kind"] == kind
            registration = executor.run_store.read_registration(
                OpaqueId(result["run_id"])
            )
            with pytest.raises(ValueError, match="outside the exact"):
                validate_execution_path(
                    registration, [{"grain": "root", "key": result["run_id"]}]
                )
            assert whole["run_id"] != result["run_id"]
            # Reusing a narrowed result cannot turn its evidence into a root claim.
            narrowed = capture_boundary(
                artifacts,
                executor.run_store,
                result["run_id"],
                executed["invocations"][0]["episode_id"],
            )
            assert (
                narrowed["invocation_path"]
                == executed["invocations"][0]["episode_path"]
            )
            broadened = deepcopy(raw)
            broadened.update(
                mode="recorded",
                recording_ref=narrowed["recording_ref"],
                launch_ref=None,
            )
            broadened["start"] = {
                "kind": "saved_inputs",
                "artifact_ref": narrowed["recording_ref"],
                "input_payload": {},
            }
            calls_before = executor.calls
            with pytest.raises(ValueError, match="complete recorded invocation set"):
                await service.run(ExperimentSpec.from_record(broadened))
            assert executor.calls == calls_before

            if kind == "episode":
                playback = deepcopy(selected)
                playback.update(
                    mode="recorded",
                    recording_ref=boundary["recording_ref"],
                    launch_ref=None,
                )
                repeated = await service.run(ExperimentSpec.from_record(playback))
                assert repeated["execution_status"] == "invalid"
                assert (
                    repeated["recorded_execution"]["divergence"]["kind"]
                    == "unmatched_external_request"
                )
                assert not repeated["recorded_execution"]["reused_responses"]
                assert len(calls) == source_calls
                # Reasoning prompts carry invocation-local learning identities.
                # They differ in a new Run, so exact playback must not rewrite
                # the prompt, use an old response, or call a live model instead.
