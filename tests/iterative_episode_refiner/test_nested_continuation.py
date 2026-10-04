"""Actual stock nested loops continued through the shared experiment service.

The refiner runs in real confined systemd workers. Builder/model choices and
Target Workflow observations are supplied; only target executions are replaced
by the existing result fixture. Source edits, campaign admissions, nested loops,
Run journal and continuation are real. A comment edit is not a behavioral repair;
this tests native nested recovery, not live-model reasoning or target correctness.
"""

import asyncio
from collections import Counter
from copy import deepcopy
from pathlib import Path
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from agent.episode_contracts import OpaqueId
from agent.duet_contracts import DuetIdentity
from agent.duet_episode_transport import DuetEpisodeBinding, required_slots
from agent.episode_launch import resolve_launch
from episode_runtime import exchanges, protocol
from episode_runtime.continuation import InterruptedRunRef
from episode_runtime.contracts import RunEventKind, RunTerminalStatus
from episode_runtime.executor import make_systemd_run_executor_factory
from episode_runtime.executor_lifecycle import verify_stopped_executor
from episode_runtime.identity import (
    inspect_runtime_source_manifest,
    runtime_identity_from_manifest,
)
from episode_runtime.records.experiments import put_data
from episode_runtime.store import RunStoreNotFound
from episode_runtime.testing_harness.service import ExperimentService
from iterative_episode_refiner.records import Ref
from llm_call_library import ModelTransportResponse
from tests.episode_runtime.test_reasoning_workflow import _approved_request
from tests.episode_runtime.testing_harness.launch_fixture import FixtureLaunchHost
from tests.episode_runtime.testing_harness.refinement_fixture import prepared_refiner
from tests.episode_runtime.testing_harness.test_measurements import ResultOnlyExecutor
from tests.episode_runtime.testing_harness.test_refinement_job_experiments import job_spec


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


async def case(tmp_path, runtime_manifest, checks, patch, *, interrupted):
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
        target_executor = evaluations.executor
        decisions = SuppliedDecisions(target_executor)
        executor = make_systemd_run_executor_factory(
            repository_root=Path(__file__).resolve().parents[2]
        )(runs)
        assert executor.inspect_runtime_identity(
            destination_root=runs.runtime_sources_root
        ) == session.registration.runtime_identity
        evaluations.executor = executor
        identity = DuetIdentity.from_record(artifacts.get_duet(session.duet_id)["identity"])
        agent = SimpleNamespace(
            _duet_identity=identity,
            _current_main_runtime=lambda: {
                "provider": "custom", "model": "supplied-refiner-decisions",
                "base_url": "http://localhost:9999/v1", "api_mode": "chat_completions",
                "session_id": "native-continuation-fixture", "auth_mode": "none",
            },
            reasoning_config=None,
        )
        binding = DuetEpisodeBinding.from_bound_agent(
            artifacts=artifacts, owner_duet_id=session.duet_id,
            agent=agent, model_types=required_slots(inputs),
        )
        patch.setattr(DuetEpisodeBinding, "transport", lambda self, **kwargs: decisions)
        service = ExperimentService(
            artifacts=artifacts, builds=builds, runs=runs, executor=executor,
            duet_binding=binding, refinement_evaluations=evaluations,
        )
        spec = job_spec(session, binding, completed=True)
        preview = service.preview(spec)
        assert preview["resolved"], preview["gaps"]
        sessions, cuts, activations = {}, [], []
        startup_events = {RunEventKind.RUNTIME_READY, RunEventKind.RUN_STARTED}
        native_execute = executor.execute

        async def execute_with_supplied_target(**arguments):
            current = arguments.get("refinement_session")
            if current is None:
                # Only Target Workflow observations are supplied. The refiner's
                # process, pipes, isolation and reconstruction are never replaced.
                assert arguments["registration"].duet_id.value == session.duet_id
                return await target_executor.execute(**arguments)
            registration = arguments["registration"]
            sessions[registration.run_id.value] = current
            if registration.resume_from is not None:
                admit = arguments["continuation_admission"]

                async def inspect_activation():
                    authority = await admit()
                    assert any(call.assignment.body["role"] == "implementer"
                               for call in current.calls.values())
                    assert campaign_effects(current) == effects
                    assert dict(decisions.calls) == call_counts
                    assert target_executor.calls == target_calls
                    assert runs.read_audit_log(original.run_id) == original_audit
                    try:
                        published = runs.read_registration(registration.run_id)
                    except RunStoreNotFound:
                        stage = "before_launch"
                    else:
                        stage = "after_reconstruction"
                        assert published == registration
                        assert runs.read_claim(registration.run_id).executor_instance_id != original_claim.executor_instance_id
                        before_activation = runs.read_committed_prefix(registration.run_id)
                        assert before_activation
                        assert all(event.kind in startup_events for event in before_activation)
                    activations.append((stage, authority))
                    return authority

                arguments["continuation_admission"] = inspect_activation
            return await native_execute(**arguments)

        patch.setattr(executor, "execute", execute_with_supplied_target)
        exchange = exchanges.broker_refinement_request

        async def interrupt_closed_implementer(**arguments):
            await exchange(**arguments)
            frame = arguments["frame"]
            if interrupted and not cuts and frame.body["operation"] == "close_unit":
                current = arguments["session"]
                call = current.calls[frame.body["episode_id"]]
                event = runs.read_committed_prefix(arguments["registration"].run_id)[-1]
                assert event.kind is RunEventKind.REFINEMENT_RESPONDED
                reply = event.payload["response"]
                if call.assignment.body["role"] == "implementer" and reply["stop"]:
                    assert reply["disposition"] == "attained" and call.unit_id is None
                    cuts.append(event.event_id)
                    # The final reply is durable, but the host has not accepted
                    # any child-return event. Stop the real physical worker.
                    raise asyncio.CancelledError

        patch.setattr(exchanges, "broker_refinement_request", interrupt_closed_implementer)
        if interrupted:
            with pytest.raises(asyncio.CancelledError):
                await service.run(spec)
            assert len(cuts) == 1 and len(sessions) == 1
            session = next(iter(sessions.values()))
            original = session.registration
            evidence = runs.read_evidence(original.run_id)
            assert evidence.terminal_status is RunTerminalStatus.CANCELLED
            original_audit = runs.read_audit_log(original.run_id)
            original_claim = runs.read_claim(original.run_id)
            assert (await verify_stopped_executor(executor, original_claim))["stopped"]
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
                campaign_effects(session), dict(decisions.calls), target_executor.calls,
            )
            continuation = {
                "experiment_id": spec.experiment_id,
                "resume_from": InterruptedRunRef.from_run(runs, original.run_id).as_record(),
            }
            result = await service.continue_run(**continuation)
            session = sessions[result["run_id"]]
            resumed = session.registration
            evidence = runs.read_evidence(resumed.run_id)
            assert resumed.logical_run_id == original.run_id and resumed.run_id != original.run_id
            assert runs.read_claim(resumed.run_id).executor_instance_id != original_claim.executor_instance_id
            assert {stage for stage, _ in activations} == {"before_launch", "after_reconstruction"}
            assert activations[0][0] == "before_launch"
            assert activations[-1][0] == "after_reconstruction"
            assert all(authority["duet_model_binding_ref"] == binding.reference
                       for _, authority in activations)
            assert runs.read_audit_log(original.run_id) == original_audit
            suffix = runs.read_audit_log(resumed.run_id)
            gates = [(index, event) for index, event in enumerate(suffix)
                     if event.kind is RunEventKind.RUN_RECONSTRUCTED]
            assert len(gates) == 1
            gate_index, gate = gates[0]
            assert all(event.kind in startup_events for event in suffix[:gate_index])
            admission = gate.payload["activation_admission"]
            assert admission["previous_executor"]["stopped"]
            assert admission["current_authority"]["duet_model_binding_ref"] == binding.reference
            assert sum(event.kind is RunEventKind.EPISODE_COMPLETED
                       and event.episode_id.value == child_id for event in suffix) == 1
            assert sum(event.kind is RunEventKind.MODEL_RESPONDED for event in suffix) == (
                sum(decisions.calls.values()) - sum(call_counts.values())
            )
            effects_after, calls_after, targets_after = (
                campaign_effects(session), dict(decisions.calls), target_executor.calls,
            )
            assert (await service.continue_run(**continuation))["run_id"] == resumed.run_id.value
            assert campaign_effects(session) == effects_after
            assert dict(decisions.calls) == calls_after and target_executor.calls == targets_after
        else:
            result = await service.run(spec)
            session = sessions[result["run_id"]]
            evidence = runs.read_evidence(session.registration.run_id)
        assert result["candidate_verdict"] == "pass", result
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
            "target_runs": target_executor.calls,
            "worker_units": len(units),
        }


@pytest.mark.platforms("linux")
@pytest.mark.asyncio
async def test_completed_implementer_returns_once_after_exact_nested_reconstruction(
    tmp_path, monkeypatch,
):
    runtime_dir = Path("/run/user") / str(os.getuid())
    if (runtime_dir / "bus").exists():
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir / 'bus'}")
    status = subprocess.run(
        ["systemctl", "--user", "is-system-running"], capture_output=True, timeout=5,
    )
    if status.returncode != 0:
        pytest.skip("native nested continuation requires a running user systemd manager")
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
    with monkeypatch.context() as patch:
        resumed = await case(
            tmp_path / "resumed", runtime_manifest, checks, patch, interrupted=True
        )
    with monkeypatch.context() as patch:
        uninterrupted = await case(
            tmp_path / "uninterrupted", runtime_manifest, checks, patch, interrupted=False
        )
    assert resumed == uninterrupted
