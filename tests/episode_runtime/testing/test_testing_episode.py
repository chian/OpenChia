"""Actual testing Episode loop with scripted model choices and supplied target output.

Exercises approval, materialization, the real linked Episode, shared experimental
measurement and host learning. It does NOT demonstrate model reasoning, target
execution, worker transport or confinement; those require the live acceptance run.
"""

from copy import deepcopy
import json
import sys

import pytest

from agent.duet_store import DuetStore
from agent.episode_contracts import EpisodeCreationSpec
from agent.episode_launch import resolve_launch
from tests.episode_runtime.testing.launch_fixture import FixtureLaunchHost
from episode_builder.service import EpisodeBuilder
from episode_library.testing import (
    DESIGN,
    testing_learning_contract as learning_contract,
)
from episode_runtime.contracts import RunEventKind, RunEventOrigin
from episode_runtime.learning_broker import LearningBroker
from episode_runtime.linker import (
    current_runtime_episode_id,
    current_runtime_episode_path,
    prepare_source_package,
)
from episode_runtime.testing.criteria import register_criterion
from episode_runtime.testing.execution import register_build
from episode_runtime.testing.inputs import workflow_template
from episode_runtime.testing.service import ExperimentService
from episode_runtime.records.experiments import put_data
from episode_runtime.testing.session import ExperimentSession
from episode_runtime.worker import runtime_collaborators
from function_library.epistemic_schemas import canonical, model_call_id
from function_library.refinement_checks import EXACT_VALUE
from function_library.reasoning_transport import reasoning_transport_scope
from function_library.testing import experiment_transport_scope
from function_library.testing_contract import TestingContract as Access
from llm_call_library.transport import ModelTransportResponse, model_transport_scope
from llm_call_library import CallOptions
from tests.episode_builder.test_repeatable_call_materialization import build, selected
from tests.episode_runtime.conftest import claim_store, numerical_control, oid
from function_library.scheduling_benchmark import optimal_schedule
from tests.episode_runtime.test_reasoning_workflow import (
    _approved_request,
    _module_response,
    _plan_response,
)
from tests.episode_runtime.testing.test_experiment_planning import experiment
from tests.episode_runtime.testing.test_measurements import ResultOnlyExecutor


@pytest.mark.asyncio
async def test_testing_episode_uses_measured_failures_and_rejects_invented_or_repeat_credit(
    tmp_path,
    run_store,
):
    request, builds, target_receipt = await build(tmp_path, ())
    target_duet = request.frozen_workflow.duet_id.value
    executor = ResultOnlyExecutor(tmp_path / "execution", run_store[1].runtime_identity)
    optimum, witness = optimal_schedule()
    executor.result = {"minimum_completion": optimum + 1}
    with DuetStore(tmp_path / "duet.db") as artifacts:
        raw = experiment(artifacts, request, target_receipt)
        launch = resolve_launch({
            "project": "testing-episode-fixture",
            "project_root": str(tmp_path),
            "env_files": [],
            "routes": {
                "local": {
                    "provider": "custom",
                    "model": "unused",
                    "base_url": "http://localhost:9999/v1",
                    "api_mode": "chat_completions",
                    "auth": {"kind": "none"},
                }
            },
            "model_slots": {"selector": "local", "executor": "local"},
            "builder_slots": {"planning": "selector", "emission": "executor"},
        })
        raw["launch_ref"] = put_data(artifacts, target_duet, "launch", launch.record)
        FixtureLaunchHost(artifacts, builds, target_duet).approve_fixture(launch)
        grounding = put_data(
            artifacts,
            target_duet,
            "grounding",
            {"optimum": optimum, "witness": witness},
        )
        criterion = register_criterion(
            {
                "schema_version": 1,
                "build_receipt_ref": raw["build_receipt_ref"],
                "environment_ref": raw["environment_ref"],
                "requirement_key": "completion-time",
                "description": "Check the independently enumerated minimum.",
                "scope": raw["scope"],
                "accepted_modes": ["live_fresh"],
                "input_payload": {},
                "predicate": selected(EXACT_VALUE).as_record(),
                "observation_path": "/minimum_completion",
                "expected_value": optimum,
                "positive_controls": [optimum],
                "negative_controls": [optimum + 1],
                "grounding_refs": [grounding],
                "limitations": [
                    "Scalar check does not establish schedule feasibility."
                ],
            },
            builds=builds,
            artifacts=artifacts,
            duet_id=target_duet,
        )
        raw["requirements"] = [
            {
                "requirement_ref": criterion["requirement_ref"],
                "measure_ref": criterion["measure_ref"],
                "expected": "Returned minimum equals the independently enumerated optimum.",
                "falsifying": "A different minimum is returned.",
            }
        ]
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
    contract = EpisodeCreationSpec(
        goal="Determine what the supplied candidate establishes about the scheduling minimum.",
        progress="Distinct admitted measured findings, not pass count.",
        stopping="Registered yield continuation.",
        numeric_control=numerical_control(0.5),
        execution_capability_names=("episode_testing",),
        testing=Access({"candidate": target}, ("workflow",), ("live_fresh",)),
        epistemic=learning_contract(
            goal_class="candidate_testing",
            domain="scheduling",
            environment={"fixture": "v1"},
        ),
    )
    tester_request = _approved_request(
        tmp_path,
        spec=contract,
        reference=DESIGN,
        allowed_capabilities=("episode_testing",),
        duet_id=oid("tester"),
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
            store=builds,
            planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"selector": {}, "executor": {}},
        ).build(tester_request)
    assert receipt.materialized, [row.as_record() for row in receipt.deficits]
    inputs = builds.inspection_inputs_for_receipt(receipt.receipt_id)
    registration, package = register_build(
        executor,
        builds,
        inputs,
        workflow_template(tester_request.frozen_workflow, None),
        run_store[1].runtime_policy,
    )
    runs, registration, _ = claim_store(executor.root, registration)
    executor.run_store = runs
    broker = LearningBroker(runs, registration, package)
    prepared = prepare_source_package(registration, package)
    activated = prepared.activate()
    sequences = {RunEventOrigin.WORKER: 0, RunEventOrigin.HOST: 0}
    chosen, experiment_results = [], []

    def append(origin, kind, payload, episode=None):
        sequence = sequences[origin]
        sequences[origin] += 1
        return runs.append_event(
            run_id=registration.run_id,
            origin=origin,
            sender_sequence=sequence,
            kind=kind,
            episode_id=episode or current_runtime_episode_id(),
            payload=payload,
        )

    async def event_sink(kind, episode_id, payload):
        append(RunEventOrigin.WORKER, kind, payload, episode_id)

    async def learning(operation, payload):
        return await broker(current_runtime_episode_id().value, operation, payload)

    with DuetStore(tmp_path / "duet.db") as artifacts:
        service = ExperimentService(
            artifacts=artifacts, builds=builds, runs=runs, executor=executor
        )
        session = ExperimentSession(
            service=service, registration=registration, inputs=inputs
        )

        async def experiment_transport(operation, payload):
            path = current_runtime_episode_path()
            request_id = f"experiment-{sequences[RunEventOrigin.WORKER]}"
            append(
                RunEventOrigin.WORKER,
                RunEventKind.EXPERIMENT_REQUESTED,
                {
                    "request_id": request_id,
                    "operation": operation,
                    "payload": payload,
                },
            )
            response = await session.exchange(
                episode_id=current_runtime_episode_id(),
                episode_path=path,
                operation=operation,
                payload=payload,
            )
            append(
                RunEventOrigin.HOST,
                RunEventKind.EXPERIMENT_RESPONDED,
                {"request_id": request_id, "response": response},
            )
            if operation != "describe":
                experiment_results.append(response)
            return response

        async def scripted_tester(request):
            prompt = json.loads(request.messages[-1]["content"])
            bundle = prompt["typed_unit_input"]
            ordinal = bundle["next_ordinal"]
            if "selected_action" not in prompt:
                previous = bundle["previous_experiment"]
                if previous is None:
                    operation, payload = "run", {"spec": raw}
                elif ordinal == 2:
                    repeated = deepcopy(raw)
                    repeated["question"] = "Rephrased question about the same minimum."
                    repeated["requirements"][0]["expected"] = "The result should match."
                    operation, payload = "run", {"spec": repeated}
                else:
                    assert previous["candidate_verdict"] == "fail"
                    operation, payload = (
                        "results",
                        {"experiment_id": previous["experiment_id"]},
                    )
                chosen.append(operation)
                response = {
                    "action_class": operation,
                    "action_inputs": payload,
                    "retry_reason": "Inspect the measured failure.",
                }
            else:
                action = prompt["selected_action"]
                source = bundle["evidence"][-1]
                observation = deepcopy(source["body"]["observation"])
                assert observation["status"] == "fail"
                if ordinal == 0:
                    observation["status"] = (
                        "pass"  # Host must reject this invented finding.
                    )
                response = {
                    "action_class": action["action_class"],
                    "action_inputs": action["action_inputs"],
                    "status": "succeeded",
                    "expected_observation": "Candidate meets criterion",
                    "observed_outcome": "Criterion fails",
                    "candidate_lessons": [],
                    "revisions": [],
                    "entities": [
                        {
                            "key": f"wording-{ordinal}",
                            "fields": {"measurement": canonical(observation).decode()},
                            "evidence": [
                                {
                                    "kind": source["body"]["kind"],
                                    "ref": source["artifact_id"],
                                    "quote": source["body"]["text"],
                                }
                            ],
                            "answer_contract": {
                                "answer_forms": ["measurement"],
                                "acceptance_tests": ["matches evidence"],
                                "falsification_tests": ["differs from evidence"],
                            },
                            "uncertainties": [],
                        }
                    ],
                }
            text = json.dumps(response)
            append(
                RunEventOrigin.HOST,
                RunEventKind.MODEL_RESPONDED,
                {
                    "producer_call_id": model_call_id(text, request.task, {}),
                    "response_text": text,
                },
            )
            return ModelTransportResponse(text=text, route={})

        try:
            with (
                model_transport_scope(scripted_tester),
                reasoning_transport_scope(learning),
                experiment_transport_scope(experiment_transport),
            ):
                outcome = await activated.link(
                    event_sink=event_sink,
                    collaborators=runtime_collaborators(activated.plan),
                ).run()
        finally:
            for module in prepared.modules.values():
                sys.modules.pop(module.module_name, None)

    broker.validate_completion(outcome)
    events = runs.read_committed_prefix(registration.run_id)
    receipts = [
        event.payload["receipt"]
        for event in events
        if event.kind is RunEventKind.LEARNING_COMMITTED
    ]
    assert chosen[:2] == ["run", "results"]
    assert executor.calls == 2, chosen
    assert len(receipts) >= 3
    assert receipts[0]["measurement"]["realized_yield"] == 0
    assert (
        "differs from the host-measured"
        in receipts[0]["admission"]["rejections"][0]["reason"]
    )
    assert receipts[1]["measurement"]["realized_yield"] == 1
    assert all(
        receipt["measurement"]["realized_yield"] == 0 for receipt in receipts[2:]
    )
    assert outcome["workflow_result"]["terminal_state"] == "completed"
    assert not outcome["workflow_result"]["result"]["acceptance_granted"]
    assert all(result["candidate_verdict"] == "fail" for result in experiment_results)
    finding = outcome["workflow_result"]["result"]["established_results"][0]
    assert json.loads(finding["body"]["fields"]["measurement"])["status"] == "fail"
