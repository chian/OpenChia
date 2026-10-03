"""Ordinary human launch reaches the real testing Episode and shared service.

Approval, materialization, generated Episodes, host brokers, measurement and
stores are real. Model responses and executor attestation are fixtures; this is
not live reasoning, operating-system confinement or a scheduling acceptance run.
"""

import asyncio
import json
from pathlib import Path
import sys

import pytest

from agent.duet_contracts import DuetProtocolError
from agent.episode_blueprints import workflow_blueprint_from_spec
from agent.episode_contracts import (
    EpisodeCreationSpec,
    EpisodeDesignSpec,
    EpisodeWorkflowSpec,
    OpaqueId,
)
from agent.openchia_host import OpenChiaHost
from episode_library.inquiry import DESIGN as INQUIRY, inquiry_contract
from episode_library.models import EpisodeReference
from episode_library.testing import (
    DESIGN as TESTING,
    testing_learning_contract as learning_contract,
)
from episode_runtime.contracts import RunEventKind
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.criteria import register_criterion
from episode_runtime.testing.execution import RunExecution
from episode_runtime.testing.launches import validate_launch_intent
from episode_runtime.records.experiments import record_id
from episode_runtime.records.experiments import put_data
from function_library.refinement_checks import EXACT_VALUE
from function_library.testing_contract import TestingContract as Access
from tests.episode_runtime.conftest import claim_store, numerical_control
from tests.episode_runtime.test_reasoning_workflow import (
    _module_response,
    _plan_response,
)
from tests.episode_runtime.testing.test_experiment_planning import experiment
from tests.episode_runtime.testing.test_scoped_execution import LinkedExecutor


class HostExecutor(LinkedExecutor):
    def __init__(self, runs, identity):
        super().__init__(runs.root.parent, identity)
        self.run_store = runs
        self.repository_root = Path(__file__).resolve().parents[2]
        self.python_executable = Path(sys.executable)


def _build(host, contract, reference):
    workflow = EpisodeWorkflowSpec((
        EpisodeDesignSpec(
            "inquiry",
            None,
            contract,
            EpisodeReference(reference.episode_id),
        ),
    ))
    draft = host.submit_episode_architecture(
        candidate_workflow_architecture=workflow_blueprint_from_spec(workflow),
        expected_artifact_id=None,
        expected_content_hash=None,
        expected_revision=None,
        human_note_ids=(),
    )
    assert draft["ready"], draft
    with pytest.raises(DuetProtocolError, match="sealed workflow authority"):
        host.start_run()
    host.approve_current()
    host.start_build()
    thread = host._build_thread
    if thread is not None:
        thread.join(timeout=60)
        assert not thread.is_alive(), host.build_status()
    assert host.build_status()["state"] == "materialized", host.build_status()
    baseline = host.workspace.current_baseline()
    return host.build_store.inspection_inputs_for_receipt(baseline.build_receipt_id)


def test_ordinary_run_preserves_approval_and_launches_nested_experiments(
    tmp_path, monkeypatch
):
    identity = claim_store(tmp_path / "attestation")[1].runtime_identity
    executors = []

    def executor_factory(runs):
        executor = HostExecutor(runs, identity)
        executors.append(executor)
        return executor

    launch_spec = {
        "project": "host-testing-integration",
        "project_root": str(tmp_path),
        "env_files": [],
        "routes": {
            "fixture": {
                "provider": "custom",
                "model": "scripted",
                "base_url": "https://example.org/v1",
                "api_mode": "chat_completions",
                "auth": {"kind": "none"},
            }
        },
        "model_slots": {
            "planner": "fixture", "writer": "fixture",
            "selector": "fixture", "executor": "fixture",
        },
        "builder_slots": {"planning": "planner", "emission": "writer"},
    }
    launch_path = tmp_path / "launch.json"
    launch_path.write_text(json.dumps(launch_spec), encoding="utf-8")
    raw, selections = {}, []

    def respond(route, key, request, cancel, progress):
        prompt = json.loads(request.messages[-1]["content"])
        if "node" in prompt:
            value = _plan_response(
                prompt, testing=prompt["node"]["contract"].get("testing") is not None
            )
        elif "admitted_node_plan" in prompt:
            value = _module_response(prompt)
        else:
            bundle = prompt["typed_unit_input"]
            if "selected_action" not in prompt:
                operation, inputs = "discover", {}
                if "testing_service" in bundle:
                    prior = bundle["previous_experiment"]
                    operation = "run" if prior is None else "results"
                    inputs = (
                        {"spec": raw}
                        if prior is None
                        else {"experiment_id": prior["experiment_id"]}
                    )
                    selections.append((
                        operation,
                        None if prior is None else prior["candidate_verdict"],
                    ))
                value = {
                    "action_class": operation,
                    "action_inputs": inputs,
                    "retry_reason": "Inspect the measured result",
                }
            else:
                selection = prompt["selected_action"]
                value = {
                    "action_class": selection["action_class"],
                    "action_inputs": selection["action_inputs"],
                    "status": "inconclusive",
                    "expected_observation": "A typed result",
                    "observed_outcome": "Result recorded",
                    "candidate_lessons": [],
                    "entities": [],
                    "revisions": [],
                }
                sources = [
                    row
                    for row in bundle["evidence"]
                    if row["schema_id"] == "openchia.experiment-measurement"
                ]
                if sources:
                    source = sources[-1]
                    value["entities"] = [
                        {
                            "key": "measured-result",
                            "fields": {
                                "measurement": json.dumps(source["body"]["observation"])
                            },
                            "evidence": [
                                {
                                    "kind": "experiment_measurement",
                                    "ref": source["artifact_id"],
                                    "quote": source["body"]["text"],
                                }
                            ],
                            "answer_contract": {
                                "answer_forms": ["Host-measured outcome"],
                                "acceptance_tests": [
                                    "Equals the committed measurement"
                                ],
                                "falsification_tests": [
                                    "Differs from the committed measurement"
                                ],
                            },
                            "uncertainties": [],
                        }
                    ]
        return json.dumps(value), route["model"]

    monkeypatch.setattr("agent.episode_launch_transport._invoke", respond)
    hosts = [
        OpenChiaHost(
            home=tmp_path,
            session_id=session,
            available_tool_names=(),
            agent_kwargs_factory=lambda *args: {},
            run_executor_factory=executor_factory,
        )
        for session in ("target", "tester")
    ]
    target, tester = hosts
    try:
        for host in hosts:
            host.configure_launch(str(launch_path))
            host.approve_launch(host.preview_launch()["configuration_hash"])
        target_inputs = _build(
            target,
            EpisodeCreationSpec(
                goal="Inspect the supplied evidence",
                progress="Admitted knowledge",
                stopping="Host numerical decision",
                numeric_control=numerical_control(0.9),
                epistemic=inquiry_contract(
                    goal_class="inquiry",
                    domain="launch-fixture",
                    environment={"dataset": "empty"},
                ),
            ),
            INQUIRY,
        )
        raw.update(
            experiment(target.store, target_inputs.build_request, target_inputs.receipt)
        )
        owner = target.identity.duet_id.value
        raw["launch_ref"] = put_data(
            target.store, owner, "launch", target.preview_launch()["configuration"]
        )
        ground = put_data(
            target.store,
            owner,
            "grounding",
            {"claim": "Only a committed host continuation decision reports completed."},
        )
        predicate = EXACT_VALUE.bind("measurement").as_record()
        predicate.pop("name")
        criteria = register_criterion(
            {
                "schema_version": 1,
                "build_receipt_ref": raw["build_receipt_ref"],
                "environment_ref": raw["environment_ref"],
                "requirement_key": "yield-return",
                "description": "The target returns a committed host completion.",
                "scope": raw["scope"],
                "accepted_modes": ["live_fresh"],
                "input_payload": {},
                "predicate": predicate,
                "observation_path": "/workflow_result/terminal_state",
                "expected_value": "completed",
                "positive_controls": ["completed"],
                "negative_controls": ["continuing", "blocked"],
                "grounding_refs": [ground],
                "limitations": [
                    "Completion is not correctness of the target's substantive reasoning."
                ],
            },
            builds=target.build_store,
            artifacts=target.store,
            duet_id=owner,
        )
        raw["requirements"] = [
            {
                "requirement_ref": criteria["requirement_ref"],
                "measure_ref": criteria["measure_ref"],
                "expected": "The target reaches its host-governed return.",
                "falsifying": "It returns another terminal state.",
            }
        ]
        delegated = {
            key: raw[key]
            for key in (
                "candidate_ref",
                "build_receipt_ref",
                "environment_ref",
                "launch_ref",
                "campaign_ref",
            )
        }
        delegated.update(
            requirements=[
                {key: row[key] for key in ("requirement_ref", "measure_ref")}
                for row in raw["requirements"]
            ],
            recording_refs=[],
            parent_context_refs=[],
        )
        testing_contract = EpisodeCreationSpec(
            goal="Measure the approved candidate and inspect its result",
            progress="Distinct measured findings",
            stopping="Host numerical decision",
            numeric_control=numerical_control(0.9),
            execution_capability_names=("episode_testing",),
            testing=Access({"target": delegated}, ("workflow",), ("live_fresh",)),
            epistemic=learning_contract(
                goal_class="candidate_testing",
                domain="launch-fixture",
                environment={"dataset": "empty"},
            ),
        )
        _build(tester, testing_contract, TESTING)
        tester.start_run()
        thread = tester._run_thread
        if thread is not None:
            thread.join(timeout=180)
            assert not thread.is_alive(), tester.run_status()
        status = tester.run_status()
        assert status["state"] == "succeeded", status["error"]
        assert selections[0] == ("run", None)
        assert ("results", "pass") in selections
        assert sum(executor.calls for executor in executors) == 2
        run_id = status["run_id"]
        execution = RunExecution.status(tester.store, tester.run_store, run_id)
        assert execution["execution_status"] == "succeeded"
        assert execution["candidate_verdict"] == "unmeasured"
        intent = tester.store.get_artifact(execution["intent_ref"]["artifact_id"])
        assert intent["kind"] == "experiment.launch_intent.v1"
        registration = tester.run_store.read_registration(OpaqueId(run_id))
        validate_launch_intent(tester.store, registration, intent["record"])
        invalid_intent = put_data(
            tester.store,
            tester.identity.duet_id.value,
            "launch_intent",
            {**intent["record"], "configuration_hash": "sha256:" + "0" * 64},
        )
        executor = executors[-1]
        with pytest.raises(ValueError, match="exact resolved model configuration"):
            asyncio.run(
                RunExecution(
                    artifacts=tester.store,
                    builds=tester.build_store,
                    runs=tester.run_store,
                    executor=executor,
                ).execute(
                    registration=registration,
                    source_package_path=tester.build_store.source_package_path(
                        registration.manifest_id
                    ),
                    intent_ref=invalid_intent,
                    model_broker=None,
                    http_broker=None,
                )
            )
        assert sum(item.calls for item in executors) == 2
        recorded = tester.store.get_artifact(record_id("execution", run_id=run_id))["record"]
        assert recorded["registration"] == registration.as_record()
        audit = tester.run_store.read_audit_log(OpaqueId(run_id))
        assert any(event.kind is RunEventKind.EXPERIMENT_RESPONDED for event in audit)
        measurement = tester.store.get_artifact(
            record_id("measurement", experiment_id=ExperimentSpec.from_record(raw).experiment_id)
        )
        assert measurement["record"]["candidate_verdict"] == "pass"
        assert not measurement["record"]["acceptance"]["admitted"]
    finally:
        for host in reversed(hosts):
            host.close()
