"""Opt-in real-model reasoning acceptance, distinct from scripted wiring tests.

The Builder model is a deterministic materialization fixture; every reasoning
selection and attempt is an actual configured provider call. RunStore and the
Episode loop are real. This test does NOT claim process-confinement coverage.
"""

import asyncio
import json
from pathlib import Path
import sys

import pytest

from agent.episode_contracts import EpisodeCreationSpec
from episode_builder.service import EpisodeBuilder
from episode_builder.store import BuildStore
from episode_library.reasoning import DESIGN
from episode_runtime.broker import model_request_record, admit_model_response
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunRegistration
from episode_runtime.learning_broker import LearningBroker
from episode_runtime.linker import current_runtime_episode_id, prepare_source_package
from function_library.epistemic import default_components
from function_library.epistemic_contract import EpistemicContract
from function_library.epistemic_schemas import model_call_id
from function_library.models import _thaw_json
from function_library.reasoning_transport import reasoning_transport_scope
from handoff_library import DuetLaunchRequest
from llm_call_library.transport import ModelTransportResponse, model_transport_scope

from conftest import claim_store, numerical_control, oid
from scheduling_benchmark import JOBS, PROBLEM, optimal_schedule, violations
from test_reasoning_workflow import _approved_request, _module_response, _plan_response


def test_independent_schedule_oracle():
    horizon, schedule = optimal_schedule()
    assert not violations(schedule)
    assert horizon == max(schedule[j] + job["duration"] for j, job in JOBS.items())
    invalid = {j: 0 for j in JOBS}
    assert violations(invalid)


@pytest.mark.platforms("linux")
@pytest.mark.asyncio
async def test_live_episode_solves_and_justifies_resource_schedule(
    tmp_path, run_store, request
):
    socket = request.config.getoption("--live-reasoning-socket")
    if not socket:
        pytest.skip(
            "requires explicit --live-reasoning-socket; no model answers are mocked"
        )
    report_path = request.config.getoption("--live-reasoning-report")
    report = {
        "problem": PROBLEM,
        "model_calls": [],
        "passed": False,
        "coverage": "Live reasoning through materialized Episode and host ledger; deterministic Builder fixture; no process confinement",
    }
    spec = EpisodeCreationSpec(
        goal=PROBLEM,
        progress="Evidence-grounded reasoning state",
        stopping="Registered numerical rarefaction",
        numeric_control=numerical_control(0.9),
        epistemic=EpistemicContract(
            goal_class="optimal_resource_schedule",
            domain="operations_research",
            allowed_actions=("solve", "verify", "revise"),
            environment={"benchmark": "seven_jobs_two_workers_one_laser_v1"},
            assumptions=(),
            required_fields=("schedule", "makespan", "optimality_argument"),
            required_evidence=("problem_specification",),
            components=default_components(),
            evidence=(
                {"kind": "problem_specification", "text": PROBLEM, "observation": {}},
            ),
        ),
    )
    approved = _approved_request(tmp_path, spec=spec, reference=DESIGN)
    build_store = BuildStore(tmp_path)

    async def materialization_fixture(call):
        prompt = json.loads(call.messages[-1]["content"])
        value = _plan_response(prompt) if "node" in prompt else _module_response(prompt)
        return ModelTransportResponse(json.dumps(value), {})

    with model_transport_scope(materialization_fixture):
        built = await EpisodeBuilder(store=build_store).build(approved)
    assert built.status == "materialized", [d.as_record() for d in built.deficits]
    manifest = build_store.read_manifest(built.manifest_id)
    registration = RunRegistration.from_admitted_build(
        build_request=approved,
        build_attempt=build_store.read_build_attempt(built.build_attempt_id),
        build_receipt=built,
        build_manifest=manifest,
        launch_request=DuetLaunchRequest(
            oid("launch").value,
            approved.frozen_workflow.artifact_id.value,
            oid("goal").value,
            {},
        ),
        runtime_identity=run_store[1].runtime_identity,
        runtime_policy=run_store[1].runtime_policy,
    )
    store, registration, _ = claim_store(tmp_path / "live", registration)
    package = build_store.source_package_path(manifest.manifest_id)
    broker = LearningBroker(store, registration, package)
    prepared = prepare_source_package(registration, package)
    activated = prepared.activate()
    worker_sequence = 0

    async def event_sink(kind, episode_id, payload):
        nonlocal worker_sequence
        store.append_event(
            run_id=registration.run_id,
            origin=RunEventOrigin.WORKER,
            sender_sequence=worker_sequence,
            kind=kind,
            episode_id=episode_id,
            payload=payload,
        )
        worker_sequence += 1

    async def learning(operation, payload):
        return await broker(current_runtime_episode_id().value, operation, payload)

    async def live_model(call):
        reader, writer = await asyncio.open_unix_connection(
            socket, limit=4 * 1024 * 1024
        )
        writer.write(json.dumps(model_request_record(call)).encode() + b"\n")
        await writer.drain()
        response_record = json.loads(await reader.readline())
        writer.close()
        await writer.wait_closed()
        assert "response" in response_record, response_record
        response = admit_model_response(response_record["response"])
        report["model_calls"].append({
            "request": model_request_record(call),
            "response": response.text,
            "route": dict(response.route),
        })
        store.append_event(
            run_id=registration.run_id,
            origin=RunEventOrigin.HOST,
            sender_sequence=len(report["model_calls"]),
            kind=RunEventKind.MODEL_RESPONDED,
            episode_id=current_runtime_episode_id(),
            payload={
                "producer_call_id": model_call_id(
                    response.text, call.task, response.route
                ),
                "response_text": response.text,
            },
        )
        return response

    try:
        with model_transport_scope(live_model), reasoning_transport_scope(learning):
            # Operational harness fail-safe, never an Episode completion condition.
            outcome = await asyncio.wait_for(
                activated.link(event_sink=event_sink).run(), 600
            )
        report["outcome"] = _thaw_json(outcome)
        broker.validate_completion(outcome)
        frontier = outcome["workflow_result"]["result"]["admitted_problem_frontier"]
        assert frontier, "No actual schedule survived the reasoning Episode"
        optimum, oracle_schedule = optimal_schedule()
        report["independent_oracle"] = {
            "minimum_makespan": optimum,
            "schedule": oracle_schedule,
        }
        for entity in frontier:
            fields = entity["body"]["fields"]
            schedule = json.loads(fields["schedule"])
            errors = violations(schedule)
            report["answer"] = {
                "schedule": schedule,
                "claimed_makespan": fields["makespan"],
                "optimality_argument": fields["optimality_argument"],
                "constraint_violations": errors,
            }
            assert not errors, errors
            actual = max(schedule[j] + job["duration"] for j, job in JOBS.items())
            assert int(fields["makespan"]) == actual == optimum
        report["passed"] = True
    finally:
        # Keep the causal receipts after the runner removes its temporary home.
        report["learning_events"] = [
            {
                "event_id": e.event_id.value,
                "kind": e.kind.value,
                "payload": _thaw_json(e.payload),
            }
            for e in broker._events()
            if e.origin is RunEventOrigin.HOST_LEARNING
        ]
        report["run_store"] = str(store.root)
        if report_path:
            Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    k: v
                    for k, v in report.items()
                    if k not in {"model_calls", "outcome", "learning_events"}
                },
                indent=2,
            )
        )
        for module in prepared.modules.values():
            sys.modules.pop(module.module_name, None)
