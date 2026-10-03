"""Actual stock nested loops reconstructed through the common host gate.

Builder/model choices, target observations and process attestation are supplied.
The source edit, campaign admissions, worker channel, nested method loop, Run
journal and restoration gate are real. A comment edit is not a demonstrated
behavioral repair; this tests continuation, not live reasoning or confinement.
"""

import asyncio
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import sys

import pytest

from agent.episode_contracts import OpaqueId
from agent.duet_contracts import canonical_json
from agent.episode_launch import resolve_launch
from episode_runtime import protocol
from episode_runtime.broker import ScopedModelBroker
from episode_runtime.continuation import InterruptedRunRef
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunTerminalStatus
from episode_runtime.exchanges import (
    broker_experiment_request,
    broker_http_request,
    broker_learning_request,
    broker_model_request,
    broker_refinement_request,
)
from episode_runtime.executor import _HostChannel
from episode_runtime.http_broker import ScopedHttpBroker
from episode_runtime.identity import (
    inspect_runtime_source_manifest,
    runtime_identity_from_manifest,
)
from episode_runtime.learning_broker import LearningBroker
from episode_runtime.linker import prepare_source_package
from episode_runtime.records.experiments import put_data
from episode_runtime.testing.reconstruction_host import HostReconstruction
from episode_runtime.testing.reconstruction_source import admit_reconstruction_source
from episode_runtime.worker import (
    _ProtocolChannel,
    _WorkerHttpTransport,
    _WorkerModelTransport,
    runtime_collaborators,
)
from function_library.reasoning_transport import reasoning_transport_scope
from function_library.refinement_transport import refinement_transport_scope
from function_library.testing import experiment_transport_scope
from http_call_library import http_transport_scope
from iterative_episode_refiner.records import Ref
from iterative_episode_refiner.runtime import RefinementSession
from llm_call_library import ModelTransportResponse, model_transport_scope
from tests.episode_runtime.conftest import claim_store
from tests.episode_runtime.test_reasoning_workflow import _approved_request
from tests.episode_runtime.testing.launch_fixture import FixtureLaunchHost
from tests.episode_runtime.testing.refinement_fixture import prepared_refiner
from tests.episode_runtime.testing.test_measurements import ResultOnlyExecutor


class InterruptedBeforeChildReturn(BaseException):
    """Drop the physical worker after a durable final child reply."""


class ReplyPipe:
    def __init__(self, reader, binding):
        self.reader = reader
        self.decoder = protocol.FrameDecoder(
            sender=protocol.FrameSender.HOST, binding=binding
        )
        self.last = None

    def write(self, packet):
        self.last = self.decoder.decode(packet)
        self.reader.feed_data(packet)

    async def drain(self):
        return None


class SizedHostChannel(_HostChannel):
    def prepare(self, frame_type, body):
        try:
            return super().prepare(frame_type, body)
        except protocol.ProtocolError as exc:
            context = body.get("response", {}).get("context", {})
            sizes = sorted(
                ((key, len(canonical_json(value).encode("utf-8"))) for key, value in context.items()),
                key=lambda item: item[1], reverse=True,
            )
            raise AssertionError(f"{exc}; context field byte sizes: {sizes}") from exc


class LoopbackWorkerChannel(_ProtocolChannel):
    """Replace stdout only; use the worker's real request IDs and reply loop."""

    async def send(self, frame_type, body):
        async with self._send_lock:
            frame = protocol.decode_frame(
                self.encoder.encode(frame_type, body),
                sender=protocol.FrameSender.WORKER,
                binding=self.binding,
                expected_sequence=self._sent_sequence,
            )
            self._sent_sequence += 1
            await self.dispatch(frame)
            return frame


def experiment_proposal(target):
    return {
        "evaluation_request_ref": target["evaluation_request_ref"],
        "experiment": {
            "schema_version": 1,
            "question": "Does the supplied observation meet this frozen fixture criterion?",
            "rationale": "Observe the target result through the common measurement service.",
            **{
                key: target[key]
                for key in (
                    "candidate_ref",
                    "build_receipt_ref",
                    "environment_ref",
                    "campaign_ref",
                    "launch_ref",
                )
            },
            "scope": {
                "kind": "workflow",
                "entry_local_id": target["root_local_id"],
                "included_local_ids": target["local_ids"],
                "component_definition_id": None,
                "unit_label": None,
                "invocation_path": [],
            },
            "boundary": {"parent_context_ref": None, "children": "execute"},
            "start": {
                "kind": "fresh",
                "artifact_ref": None,
                "input_payload": target["assigned_inputs"],
            },
            "mode": "live_fresh",
            "recording_ref": None,
            "requirements": [
                {
                    "requirement_ref": row["requirement_ref"],
                    "measure_ref": row["measure_ref"],
                    "expected": "The supplied observation is true.",
                    "falsifying": "A false or absent observation fails this fixture criterion.",
                }
                for row in target["requirements"]
            ],
            "unresolved_questions": [
                "Supplied observations do not establish correctness of the target source."
            ],
        },
    }


class SuppliedDecisions:
    def __init__(self, executor):
        self.executor = executor
        self.calls = Counter()

    async def __call__(self, request):
        prompt = json.loads(request.messages[-1]["content"])
        task, context = prompt["task"], prompt["assignment_context"]
        self.calls[task] += 1
        handlers = {
            "experiment": self.experiment,
            "choose_part": self.choose_part,
            "design": self.design,
            "change": self.change,
        }
        if task not in handlers or (task != "experiment" and self.calls[task] != 1):
            pytest.fail(
                f"Unexpected or repeated supplied-model task {task}: {context['last_feedback']}"
            )
        result = handlers[task](prompt)
        return ModelTransportResponse(
            text=json.dumps(result), route={"fixture": "supplied decisions"}
        )

    def experiment(self, prompt):
        # Explicit fixture data, not execution of the edited source.
        changed = (
            prompt["assignment_context"]["candidate"]["body"]["parent_candidate_ref"]
            is not None
        )
        self.executor.result = {"goal_observation": changed, "other_observation": True}
        return experiment_proposal(prompt["experiment_targets"][0])

    @staticmethod
    def choose_part(prompt):
        context = prompt["assignment_context"]
        assignment = context["assignment"]["body"]
        goal = next(
            row["requirement_key"]
            for row in context["requirements"]
            if row.get("field") == "goal"
        )
        return {
            "assignment": {
                "role": "designer",
                "goal": "Design the one explicit fixture source revision.",
                "contribution_requirement_keys": [goal],
                **{
                    key: assignment[key]
                    for key in (
                        "owned_slice_keys",
                        "writable_paths",
                        "local_measure_ref",
                        "acceptance_measure_ref",
                    )
                },
                "measure_request": None,
                "supersedes_assignment_refs": [],
            },
            "conflict_ref": None,
        }

    @staticmethod
    def design(prompt):
        assignment = prompt["assignment_context"]["assignment"]["body"]
        return {
            "plan": {
                "approach_key": "one-reviewed-fixture-comment",
                "requirement_mapping": {
                    key: "Record the scoped source revision, then independently observe the fixture outcome."
                    for key in assignment["contribution_requirement_keys"]
                },
                "intended_change_scope": assignment["writable_paths"],
                "assumption_refs": [],
                "proposed_component_refs": [],
                "dependency_effects": {},
                "preservation_measure_refs": [],
                "expected_observation_refs": [],
                "falsifying_observation_refs": [],
                "local_measure_ref": assignment["local_measure_ref"],
            },
            "supersedes_assignment_refs": [],
        }

    @staticmethod
    def change(prompt):
        path, source = next(iter(prompt["assignment_context"]["source_files"].items()))
        return {
            "files": [
                {
                    "logical_path": path,
                    "content": "# Scoped continuation fixture revision; no behavioral repair claimed.\n"
                    + source,
                }
            ],
            "implementation_detail_operations": [],
        }


async def run_linked(
    session, package, decisions, *, gate=None, authorize=None, interrupt=False
):
    """A test I/O adapter around the ordinary linked worker, not a new loop."""
    runs, registration = session.store.evidence.runs, session.registration
    claim_store(runs.root, registration, store=runs)
    prepared = prepare_source_package(registration, package)
    binding = protocol.ProtocolBinding.from_registration(registration)
    reader = asyncio.StreamReader()
    writer = ReplyPipe(reader, binding)
    host = SizedHostChannel(binding=binding, reader=asyncio.StreamReader(), writer=writer)
    worker = LoopbackWorkerChannel(binding=binding, reader=reader)
    models = ScopedModelBroker.from_plan(decisions, prepared.plan)
    learning = LearningBroker(runs, registration, package)

    async def forbidden_http(*args, **kwargs):
        pytest.fail("The stock refiner has no approved HTTP operation in this fixture.")

    http = ScopedHttpBroker(
        policy={},
        credentials={},
        transport=forbidden_http,
        max_frame_bytes=binding.max_frame_bytes,
    )
    request_handlers = {
        "learning_request": (broker_learning_request, {"session": learning}),
        "refinement_request": (broker_refinement_request, {"session": session}),
        "experiment_request": (broker_experiment_request, {"session": None}),
        "model_request": (broker_model_request, {"model_broker": models}),
        "http_request": (broker_http_request, {"http_broker": http}),
    }

    async def dispatch(frame):
        if gate is not None and await gate.consume(frame, host, authorize=authorize):
            return
        arguments = dict(
            run_store=runs, registration=registration, channel=host, frame=frame
        )
        if frame.frame_type == "run_event":
            body = frame.body
            runs.append_event(
                run_id=registration.run_id,
                origin=RunEventOrigin.WORKER,
                sender_sequence=frame.sender_sequence,
                kind=RunEventKind(body["event_kind"]),
                episode_id=OpaqueId(body["episode_id"]),
                payload=body["payload"],
            )
        else:
            broker, owner = request_handlers[frame.frame_type]
            await broker(**arguments, **owner)
            if (
                interrupt
                and frame.frame_type == "refinement_request"
                and frame.body["operation"] == "close_unit"
            ):
                call = session.calls[frame.body["episode_id"]]
                reply = writer.last.body["response"]
                if call.assignment.body["role"] == "implementer" and reply["stop"]:
                    assert reply["disposition"] == "attained"
                    assert call.unit_id is None
                    # The worker decodes the committed reply but send() has not
                    # returned to the unit, so its final receipt cannot escape.
                    await worker._pending_refinement[frame.body["request_id"]]
                    raise InterruptedBeforeChildReturn

    worker.dispatch = dispatch
    receiver = asyncio.create_task(worker.receive_loop())
    try:
        activated = prepared.activate()
        with (
            model_transport_scope(_WorkerModelTransport(worker)),
            http_transport_scope(_WorkerHttpTransport(worker)),
            reasoning_transport_scope(worker.request_learning),
            refinement_transport_scope(worker.request_refinement),
            experiment_transport_scope(worker.request_experiment),
        ):
            result = await activated.link(
                event_sink=worker.event,
                collaborators=runtime_collaborators(prepared.plan),
            ).run()
        status = RunTerminalStatus(result["outcome"])
        session.validate_return(status.value, result)
    except InterruptedBeforeChildReturn:
        status = RunTerminalStatus.INTERRUPTED
        result = {
            "outcome": "interrupted",
            "reason": "completed Implementer has not returned to Designer",
        }
    finally:
        receiver.cancel()
        try:
            await receiver
        except asyncio.CancelledError:
            pass
        for module in prepared.modules.values():
            sys.modules.pop(module.module_name, None)
    return runs.finalize_run(
        run_id=registration.run_id,
        origin=RunEventOrigin.HOST,
        sender_sequence=host.next_sender_sequence,
        terminal_status=status,
        typed_status=result,
    )


def campaign_effects(session):
    with session.view() as view:
        actions = Counter(
            row[0]
            for row in view.connection.execute(
                "SELECT action FROM refinement_operations WHERE campaign_id = ? AND commit_id IS NOT NULL",
                (session.campaign_id.value,),
            )
        )
        units = tuple(row.record.ref.as_record() for row in view.entries("unit"))
        return {
            "head": dict(view.head),
            "actions": actions,
            "units": units,
            "ordinal": session._operation_ordinal,
        }


def controller_history(session):
    """Compare numeric decisions, retaining all statistics but not fixture IDs."""
    result = []
    with session.view() as view:
        for entry in view.entries("unit"):
            receipt = entry.record.as_record()["body"]
            assignment = view.read(
                Ref.from_record(receipt["assignment_ref"]), "assignment"
            )
            decision = view.read(
                Ref.from_record(receipt["continuation_ref"]), "continuation"
            ).as_record()["body"]
            step = deepcopy(decision["numeric_step"])
            admission = step["admission"]
            admission["new_identity_count"] = len(admission.pop("new_identity_ids"))
            for key in ("before", "after"):
                snapshot = admission[key]
                snapshot["accepted_counts"] = list(
                    map(len, snapshot.pop("accepted_by_position"))
                )
                snapshot["incidence_frequencies"] = [
                    sorted(frequency for _, frequency in row)
                    for row in snapshot.pop("incidence_by_position")
                ]
            result.append({
                "role": assignment.body["role"],
                **{
                    key: receipt[key]
                    for key in (
                        "ordinal",
                        "credit_before",
                        "credit_after",
                        "realized_yield",
                        "disposition",
                    )
                },
                **{
                    key: decision[key]
                    for key in (
                        "remaining_opportunities",
                        "prior_remaining_opportunities",
                        "attained",
                        "usable_observation",
                        "stop",
                    )
                },
                "numeric_step": step,
            })
    return result


async def case(tmp_path, runtime_manifest, checks, *, interrupted):
    async with prepared_refiner(
        tmp_path,
        runtime_identity_from_manifest(runtime_manifest),
        runtime_checks=checks,
        allow_source_edits=True,
        executor_type=ResultOnlyExecutor,
    ) as session:
        evaluations = session.evaluations
        artifacts, builds, runs = (
            session.store.evidence.duets,
            evaluations.builder.store,
            session.store.evidence.runs,
        )
        launch = resolve_launch({
            "project": "nested-continuation-fixture",
            "project_root": str(tmp_path),
            "env_files": [],
            "routes": {
                "target": {
                    "provider": "custom",
                    "model": "unused-supplied-target",
                    "base_url": "http://localhost:9999/v1",
                    "api_mode": "chat_completions",
                    "auth": {"kind": "none"},
                }
            },
            "model_slots": {
                "selector": "target",
                "executor": "target",
                "planner": "target",
                "writer": "target",
            },
            "builder_slots": {"planning": "planner", "emission": "writer"},
        })
        evaluations.target_launch_ref = put_data(
            artifacts, session.duet_id, "launch", launch.record
        )
        FixtureLaunchHost(artifacts, builds, session.duet_id).approve_fixture(launch)
        inputs = builds.inspection_inputs_for_receipt(
            session.registration.build_receipt_id
        )
        package = builds.verify_source_package(inputs.manifest)
        decisions = SuppliedDecisions(evaluations.executor)
        evidence = await run_linked(session, package, decisions, interrupt=interrupted)
        if interrupted:
            assert evidence.terminal_status is RunTerminalStatus.INTERRUPTED
            original = session.registration
            original_audit = runs.read_audit_log(original.run_id)
            saved = session.continuation_state()
            assert not saved["pending_children"]
            active = {
                session.calls[row["episode_id"]].assignment.body["role"]: row
                for row in saved["calls"]
            }
            assert {role: row["status"] for role, row in active.items()} == {
                "parts": "waiting",
                "designer": "waiting",
                "implementer": "attained",
            }
            assert (
                active["parts"]["unit_id"] is not None
                and active["designer"]["unit_id"] is not None
            )
            child_id = active["implementer"]["episode_id"]
            assert active["implementer"]["unit_id"] is None
            assert not any(
                event.kind is RunEventKind.EPISODE_COMPLETED
                and event.episode_id.value == child_id
                for event in original_audit
            )
            effects, call_counts, target_calls = (
                campaign_effects(session),
                dict(decisions.calls),
                evaluations.executor.calls,
            )
            resumed = replace(
                original, resume_from=InterruptedRunRef.from_run(runs, original.run_id)
            )
            session = RefinementSession(
                store=session.store,
                campaign_id=session.campaign_id,
                registration=resumed,
                source_package_path=package,
                evaluations=evaluations,
            )
            assert (
                resumed.logical_run_id == original.run_id
                and resumed.run_id != original.run_id
            )
            source_receipt = admit_reconstruction_source(
                prepare_source_package(resumed, package),
                source_package_path=package,
                runtime_manifest=runtime_manifest,
            )
            gate = HostReconstruction(
                runs, resumed, source_receipt, refinement_session=session
            )
            activations = []

            async def authorize():
                assert gate.cursor.prefix_verified
                assert campaign_effects(session) == effects
                assert dict(decisions.calls) == call_counts
                assert evaluations.executor.calls == target_calls
                assert runs.read_audit_log(original.run_id) == original_audit
                assert runs.read_committed_prefix(resumed.run_id) == ()
                activations.append(gate.cursor.report())
                return {
                    "kind": "supplied_test_authority",
                    "native_activation_verified": False,
                }

            evidence = await run_linked(
                session, package, decisions, gate=gate, authorize=authorize
            )
            assert len(activations) == 1 and gate.activated
            assert runs.read_audit_log(original.run_id) == original_audit
            suffix = runs.read_audit_log(resumed.run_id)
            assert suffix[0].kind is RunEventKind.RUN_RECONSTRUCTED
            assert (
                sum(
                    event.kind is RunEventKind.EPISODE_COMPLETED
                    and event.episode_id.value == child_id
                    for event in suffix
                )
                == 1
            )
            assert sum(
                event.kind is RunEventKind.MODEL_RESPONDED for event in suffix
            ) == sum(decisions.calls.values()) - sum(call_counts.values())
        assert evidence.terminal_status is RunTerminalStatus.SUCCEEDED, (
            evidence.typed_status
        )
        root = session.calls[session.root_id]
        report = session.store.project(session.campaign_id, root.invocation_id)
        assert report.body["termination"] == "attained"
        assert evidence.typed_status["workflow_result"] == {
            "report_id": report.artifact_id.value,
            "disposition": report.body["termination"],
        }
        assert not report.body["unresolved_requirement_keys"]
        effects = campaign_effects(session)
        assert (
            effects["actions"]["apply_change"] == effects["actions"]["admit_plan"] == 1
        )
        assert (
            decisions.calls["change"]
            == decisions.calls["design"]
            == decisions.calls["choose_part"]
            == 1
        )
        history = controller_history(session)
        assert any(row["realized_yield"] > 0 for row in history)
        prefix = runs.read_execution_prefix(session.registration.run_id)
        units = [
            json.dumps(protocol._thaw_json(event.payload["unit_ref"]), sort_keys=True)
            for event in prefix
            if event.kind is RunEventKind.UNIT_COMPLETED
        ]
        assert len(units) == len(set(units))
        return {
            "completion": protocol._thaw_json(evidence.typed_status["completion"]),
            "disposition": evidence.typed_status["workflow_result"]["disposition"],
            "history": history,
            "actions": effects["actions"],
            "model_calls": dict(decisions.calls),
            "target_runs": evaluations.executor.calls,
            "worker_units": len(units),
        }


@pytest.mark.asyncio
async def test_completed_implementer_returns_once_after_exact_nested_reconstruction(
    tmp_path,
):
    runtime_manifest = inspect_runtime_source_manifest(
        repository_root=Path(__file__).resolve().parents[2]
    )
    schema = (
        _approved_request(tmp_path / "coverage")
        .frozen_workflow.workflow.episodes[0]
        .contract.as_record()
    )
    checks = [
        {
            "requirement_field": field,
            "purpose": purpose,
            "expected": True,
            "observation_path": "/payload/typed_status/"
            + ("goal_observation" if field == "goal" else "other_observation"),
            "grounding": {
                "fixture": "supplied Boolean observations for restoration only",
                "field": field,
            },
        }
        for field in (*schema, "workflow_parent_local_id")
        for purpose in ("local", "acceptance", "composition")
    ]
    uninterrupted = await case(
        tmp_path / "uninterrupted", runtime_manifest, checks, interrupted=False
    )
    resumed = await case(
        tmp_path / "resumed", runtime_manifest, checks, interrupted=True
    )
    assert resumed == uninterrupted
