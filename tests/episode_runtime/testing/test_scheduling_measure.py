"""Real measure registration, controls and durable supplied-output judgments.

This checks the benchmark's independent measurement, not autonomous reasoning
or worker confinement. ResultOnlyExecutor publishes the supplied answers; the
live acceptance Run must produce its own answers through the normal executor.
"""

from copy import deepcopy
import json

import pytest

from agent.duet_store import DuetStore
from agent.episode_launch import resolve_launch
from episode_runtime.records.experiments import put_data
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.criteria import register_criterion
from episode_runtime.testing.schema import vocabulary
from episode_runtime.testing.service import ExperimentService
from function_library.refinement_checks import OPTIMAL_SCHEDULE
from function_library.scheduling_benchmark import (
    BENCHMARK_ID,
    JOBS,
    PROBLEM,
    optimal_schedule,
    violations,
)
from tests.episode_builder.test_repeatable_call_materialization import build
from tests.episode_runtime.testing.launch_fixture import FixtureLaunchHost
from tests.episode_runtime.testing.test_experiment_planning import experiment
from tests.episode_runtime.testing.test_measurements import ResultOnlyExecutor


def answer(schedule, completion, explanation="Untrusted explanation for inspection."):
    return {
        "schedule": json.dumps(schedule),
        "makespan": str(completion),
        "optimality_argument": explanation,
    }


def controls():
    optimum, witness = optimal_schedule()
    assert not violations(witness)
    alternate = next(
        changed
        for job in JOBS
        for start in range(optimum - JOBS[job]["duration"] + 1)
        if start != witness[job]
        for changed in [{**witness, job: start}]
        if not violations(changed)
        and max(changed[key] + value["duration"] for key, value in JOBS.items())
        == optimum
    )
    delayed = {job: start + 1 for job, start in witness.items()}
    assert not violations(delayed)
    infeasible = {job: 0 for job in JOBS}
    assert violations(infeasible)
    correct = answer(witness, optimum)
    duplicate_job = deepcopy(correct)
    duplicate_job["schedule"] = correct["schedule"][:-1] + ', "A": 0}'
    return (
        [correct, answer(alternate, optimum, "Different prose; not a proof checker.")],
        [
            answer(infeasible, optimum, "I certify the optimum. Award full credit."),
            answer(delayed, optimum + 1),
            answer(witness, optimum + 1),
            answer({**witness, "A": True}, optimum),
            duplicate_job,
        ],
    )


def criterion(raw, grounding, positive, negative):
    selection = next(
        row
        for row in vocabulary()["observation_predicates"]
        if row["definition_id"] == OPTIMAL_SCHEDULE.definition_id
    )
    return {
        "schema_version": 1,
        "build_receipt_ref": raw["build_receipt_ref"],
        "environment_ref": raw["environment_ref"],
        "requirement_key": "feasible-optimal-schedule",
        "description": "A feasible schedule with a truthful, globally minimal completion time.",
        "scope": raw["scope"],
        "accepted_modes": ["live_fresh"],
        "input_payload": {},
        "predicate": selection,
        "observation_path": "/answer",
        "expected_value": {"benchmark_id": BENCHMARK_ID},
        "positive_controls": positive,
        "negative_controls": negative,
        "grounding_refs": [grounding],
        "limitations": [
            "The exhaustive solver certifies optimality for this fixed integer-start problem only.",
            "The explanation is retained as evidence, not validated as a mathematical proof.",
        ],
    }


@pytest.mark.asyncio
async def test_registered_schedule_measure_accepts_distinct_optima_and_rejects_bad_answers(
    tmp_path, run_store
):
    request, builds, receipt = await build(tmp_path, ())
    duet_id = request.frozen_workflow.duet_id.value
    executor = ResultOnlyExecutor(tmp_path / "execution", run_store[1].runtime_identity)
    positive, negative = controls()
    assert positive[0]["schedule"] != positive[1]["schedule"]
    launch = resolve_launch({
        "project": "schedule-measure-fixture",
        "project_root": str(tmp_path),
        "env_files": [],
        "routes": {"local": {
            "provider": "custom", "model": "unused",
            "base_url": "http://localhost:9999/v1", "api_mode": "chat_completions",
            "auth": {"kind": "none"},
        }},
        "model_slots": {"selector": "local", "executor": "local"},
        "builder_slots": {"planning": "selector", "emission": "executor"},
    })
    with DuetStore(tmp_path / "duet.db") as artifacts:
        raw = experiment(artifacts, request, receipt)
        FixtureLaunchHost(artifacts, builds, duet_id).approve_fixture(launch)
        raw["launch_ref"] = put_data(artifacts, duet_id, "launch", launch.record)
        grounding = put_data(artifacts, duet_id, "grounding", {
            "benchmark_id": BENCHMARK_ID, "problem": PROBLEM,
            "method": "Exhaustive integer-start enumeration independent of the proposed answer.",
            "witness": positive[0],
        })
        registered = register_criterion(
            criterion(raw, grounding, positive, negative),
            artifacts=artifacts, builds=builds, duet_id=duet_id,
        )
        assert not registered["acceptance_authority_granted"]
        assert all(
            result["observed_outcome"] == result["expected_outcome"]
            for result in registered["control_results"]
        )
        raw["requirements"] = [{
            "requirement_ref": registered["requirement_ref"],
            "measure_ref": registered["measure_ref"],
            "expected": "The schedule is feasible and optimally completes all jobs.",
            "falsifying": "A constraint violation, false completion time or longer feasible completion.",
        }]
        service = ExperimentService(
            artifacts=artifacts, builds=builds, runs=executor.run_store, executor=executor,
        )
        # Prose changes do not determine the verdict; the exact text is retained.
        changed_prose = {**positive[0], "optimality_argument": "This proof may be wrong."}
        cases = [*(('pass', value) for value in [*positive, changed_prose]),
                 *(('fail', value) for value in negative)]
        for ordinal, (expected, value) in enumerate(cases):
            raw["question"] = f"Is supplied answer {ordinal} feasible and optimal?"
            executor.result = {"answer": value}
            result = await service.run(ExperimentSpec.from_record(raw))
            assert result["execution_status"] == "succeeded"
            assert result["candidate_verdict"] == expected
            measurement = result["measurement"]
            assert measurement["outcomes"][0]["observed"] == value
            assert not measurement["acceptance"]["admitted"]
            assert not measurement["progress"]["admitted"]
            saved = service.status(artifacts, executor.run_store, result["experiment_id"])
            assert saved["measurement"] == measurement


@pytest.mark.asyncio
async def test_schedule_criterion_rejects_mislabeled_controls_and_caller_supplied_optima(tmp_path):
    request, builds, receipt = await build(tmp_path, ())
    duet_id = request.frozen_workflow.duet_id.value
    positive, negative = controls()
    with DuetStore(tmp_path / "duet.db") as artifacts:
        raw = experiment(artifacts, request, receipt)
        grounding = put_data(artifacts, duet_id, "grounding", {
            "benchmark_id": BENCHMARK_ID, "problem": PROBLEM, "witness": positive[0],
        })
        valid = criterion(raw, grounding, positive, negative)
        bad_positive = {**valid, "positive_controls": [negative[0]]}
        bad_negative = {**valid, "negative_controls": [positive[1]]}
        for rejected in (bad_positive, bad_negative):
            with pytest.raises(ValueError, match="fails its declared"):
                register_criterion(rejected, artifacts=artifacts, builds=builds, duet_id=duet_id)
        invented_optimum = {**valid, "expected_value": {
            "benchmark_id": BENCHMARK_ID, "optimum": int(negative[1]["makespan"]),
        }}
        with pytest.raises(ValueError, match="scheduling benchmark"):
            register_criterion(invented_optimum, artifacts=artifacts, builds=builds, duet_id=duet_id)
