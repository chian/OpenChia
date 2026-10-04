"""Campaign admission and common measurement, not live reasoning acceptance.

The target/refiner builds and campaign checks are actually admitted. Runtime
outputs are supplied by the existing result-only executor to isolate judgment
and scope binding; neither reasoning nor confinement is claimed here.
"""

from copy import deepcopy
from dataclasses import replace

import pytest

from agent.episode_launch import resolve_launch
from tests.episode_runtime.testing.launch_fixture import FixtureLaunchHost
from episode_runtime.records.experiments import put_data
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.planning import preview_experiment
from episode_runtime.testing.service import ExperimentService
from iterative_episode_refiner.records import Ref
from function_library.scheduling_benchmark import optimal_schedule, violations
from tests.episode_runtime.testing.refinement_fixture import prepared_refiner
from tests.episode_runtime.testing.test_experiment_planning import experiment
from tests.episode_runtime.testing.test_measurements import ResultOnlyExecutor


@pytest.mark.asyncio
async def test_shared_measurement_uses_admitted_campaign_check_without_awarding_credit(
    tmp_path, run_store
):
    optimum, witness = optimal_schedule()
    assert not violations(witness)
    async with prepared_refiner(
        tmp_path,
        run_store[1].runtime_identity,
        runtime_check={
            "expected": optimum,
            "observation_path": "/payload/typed_status/minimum_completion",
            "grounding": {"optimum": optimum, "witness": witness},
        },
    ) as session:
        artifacts, builds = session.store.evidence.duets, session.store.evidence.builds
        with session.view() as view:
            check = next(
                row.record
                for row in view.entries("check")
                if row.record.body["evidence_kind"] == "execution"
            )
            candidate = view.candidate
            head = dict(view.head)
            receipt = view.data(
                Ref.from_record(session.contract.body["initial_build_receipt_ref"])
            )
        inputs = builds.inspection_inputs_for_receipt(receipt["receipt_id"])
        executor = ResultOnlyExecutor(
            tmp_path / "measurement_runs", run_store[1].runtime_identity
        )
        service = ExperimentService(
            artifacts=artifacts,
            builds=builds,
            runs=executor.run_store,
            executor=executor,
        )
        spec = experiment(artifacts, inputs.build_request, inputs.receipt)
        spec.update(
            question="Does the reported minimum match independent enumeration?",
            rationale="Apply the parent's admitted check without changing its expected value.",
            candidate_ref=candidate.ref.as_record(),
            campaign_ref=session.contract.ref.as_record(),
            environment_ref=dict(session.contract.body["environment_ref"]),
            requirements=[
                {
                    "requirement_ref": check.ref.as_record(),
                    "measure_ref": dict(check.body["measure_ref"]),
                    "expected": "The returned minimum equals the independently enumerated optimum.",
                    "falsifying": "A different number or a string in place of the number fails the frozen check.",
                }
            ],
        )
        launch = resolve_launch({
            "project": "campaign-measurement-fixture",
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
        spec["launch_ref"] = put_data(
            artifacts, session.duet_id, "launch", launch.record
        )
        FixtureLaunchHost(artifacts, builds, session.duet_id).approve_fixture(launch)
        plan = preview_experiment(
            ExperimentSpec.from_record(spec),
            artifacts=artifacts,
            builds=builds,
            runs=executor.run_store,
        )
        assert plan["resolved"], plan["gaps"]
        assert plan["measurements"][0]["eligible"]
        assert (
            plan["measurements"][0]["criterion"]["expected_value"]
            == check.body["expected"]
        )
        assert plan["measurement_implementation_hash"]

        for value, expected_status in ((optimum, "pass"), (str(optimum), "fail")):
            requested = deepcopy(spec)
            requested["question"] += f" Case: {expected_status}."
            # Predictions remain worker data; saying "pass" cannot change an oracle.
            requested["requirements"][0]["expected"] = "I predict a pass."
            executor.result = {"minimum_completion": value}
            result = await service.run(ExperimentSpec.from_record(requested))
            assert result["candidate_verdict"] == expected_status
            outcome = result["measurement"]["outcomes"][0]
            assert outcome["requirement_key"] == check.body["requirement_key"]
            assert outcome["criterion_expected"] == optimum
            assert outcome["observed"] == value
            assert not result["measurement"]["acceptance"]["admitted"]
            assert not result["measurement"]["progress"]["admitted"]
            assert await service.run(ExperimentSpec.from_record(requested)) == result
        assert executor.calls == 2
        with session.view() as view:
            assert dict(view.head) == head
            assert not view.entries("observation")

        # A stored proposal is not an installed criterion, even with valid hashes.
        unadmitted = replace(check, body={**check.body, "expected": optimum + 1})
        with artifacts.transaction() as connection:
            session.store._put(connection, session.duet_id, unadmitted)
        changed = deepcopy(spec)
        changed["requirements"][0]["requirement_ref"] = unadmitted.ref.as_record()
        rejected = preview_experiment(
            ExperimentSpec.from_record(changed),
            artifacts=artifacts,
            builds=builds,
            runs=executor.run_store,
        )
        assert not rejected["resolved"]
        assert rejected["gaps"][-1]["kind"] == "measurement_context_invalid"
