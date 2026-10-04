"""Real refiner/checker loops and shared dispatch, with supplied target outputs.

This exercises approved builds, authentic broker events and campaign admission.
The in-process refiner and supplied target return do not prove live reasoning
or native confinement; the independent optimum tests the judgment connection.
"""

import asyncio
import json
from copy import deepcopy

import pytest

from agent.episode_launch import resolve_launch
from episode_runtime.broker import ScopedModelBroker
from episode_runtime.contracts import RunTerminalStatus
from episode_runtime.records.experiments import put_data, read_record
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.service import ExperimentService
from iterative_episode_refiner.execution import execute_refinement
from llm_call_library.transport import ModelTransportResponse
from function_library.scheduling_benchmark import optimal_schedule, violations
from tests.episode_runtime.conftest import oid
from tests.episode_runtime.testing.launch_fixture import FixtureLaunchHost
from tests.episode_runtime.testing.refinement_fixture import prepared_refiner
from tests.episode_runtime.testing.test_measurements import ResultOnlyExecutor
from tests.episode_runtime.testing.test_scoped_execution import LinkedExecutor


class SuppliedTargetExecutor(LinkedExecutor):
    async def execute(self, **kwargs):
        if kwargs.get("refinement_session") is not None or kwargs[
            "registration"
        ].duet_id == oid("checker_duet"):
            return await super().execute(**kwargs)
        return await ResultOnlyExecutor.execute(self, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("independent_checker", [False, True])
async def test_refiner_designs_shared_experiment_and_parent_receives_measured_failure(
    tmp_path, run_store, independent_checker, monkeypatch
):
    optimum, witness = optimal_schedule()
    assert not violations(witness)
    async with prepared_refiner(
        tmp_path,
        run_store[1].runtime_identity,
        runtime_check={
            "purpose": "composition",
            "expected": True if independent_checker else optimum,
            "observation_path": "/payload/typed_status/workflow_result/flags/checker_pass"
            if independent_checker
            else "/payload/typed_status/minimum_completion",
            "grounding": {"optimum": optimum, "witness": witness},
        },
        executor_type=SuppliedTargetExecutor,
        independent_checker=independent_checker,
    ) as session:
        evaluations = session.evaluations
        artifacts, builds, runs = (
            session.store.evidence.duets,
            evaluations.builder.store,
            session.store.evidence.runs,
        )
        launch = resolve_launch({
            "project": "supplied-target-fixture",
            "project_root": str(tmp_path),
            "env_files": [],
            "routes": {
                "target": {
                    "provider": "custom",
                    "model": "unused-target-model",
                    "base_url": "http://localhost:9999/v1",
                    "api_mode": "chat_completions",
                    "auth": {"kind": "none"},
                }
            },
            "model_slots": {"planner": "target", "writer": "target", "selector": "target", "executor": "target"},
            "builder_slots": {"planning": "planner", "emission": "writer"},
        })
        evaluations.target_launch_ref = put_data(
            artifacts, session.duet_id, "launch", launch.record
        )
        FixtureLaunchHost(artifacts, builds, session.duet_id).approve_fixture(launch)
        # A candidate claiming its own pass cannot substitute for the checker.
        evaluations.executor.result = {
            "minimum_completion": optimum + 1,
            "checker_pass": True,
            "workflow_result": {"flags": {"checker_pass": True}},
        }
        expected_observed = False if independent_checker else optimum + 1
        inputs = builds.inspection_inputs_for_receipt(
            session.registration.build_receipt_id
        )
        proposals, parent_prompts = [], []
        evaluate = evaluations.evaluate
        repeated = []

        async def resend_request(session, call, payload):
            first = await evaluate(session, call, payload)
            if "experiment_proposal_ref" not in payload:
                return first
            with session.view() as view:
                head = dict(view.head)
            calls = evaluations.executor.calls
            second = await evaluate(session, call, payload)
            assert second == first
            assert evaluations.executor.calls == calls
            with session.view() as view:
                assert dict(view.head) == head
            feedback = second["context"]["last_feedback"]
            assert (
                feedback["measurement"]["outcomes"][0]["observed"] == expected_observed
            )
            repeated.append(second["experiment_result"]["experiment_id"])
            return second

        evaluations.evaluate = resend_request

        async def refiner_model(request):
            prompt = json.loads(request.messages[-1]["content"])
            if prompt["task"] != "experiment":
                parent_prompts.append(prompt)
                raise asyncio.CancelledError
            target = prompt["experiment_targets"][0]
            spec = {
                "schema_version": 1,
                "question": "Does this candidate return the independently established minimum?",
                "rationale": "Run the complete candidate because the parent's criterion is about its final answer.",
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
                        "expected": "The candidate should return the independently enumerated minimum.",
                        "falsifying": "Any other value fails the parent's exact criterion.",
                    }
                    for row in target["requirements"]
                ],
                "unresolved_questions": [
                    "A scalar match alone does not prove the schedule witness."
                ],
            }
            proposals.append(spec)
            return ModelTransportResponse(
                text=json.dumps({
                    "evaluation_request_ref": target["evaluation_request_ref"],
                    "experiment": spec,
                }),
                route={},
            )

        result = await execute_refinement(
            store=session.store,
            campaign_id=session.campaign_id,
            registration=session.registration,
            source_package_path=builds.verify_source_package(inputs.manifest),
            executor=evaluations.executor,
            model_broker=ScopedModelBroker.from_plan(refiner_model, inputs.plan),
            http_broker=None,
            evaluations=evaluations,
        )
        assert result.run_evidence.terminal_status is RunTerminalStatus.CANCELLED
        assert len(proposals) == 1, [row.as_record() for row in result.decision_records]
        spec = ExperimentSpec.from_record(proposals[0])
        assert repeated == [spec.experiment_id]
        status = ExperimentService.status(artifacts, runs, spec.experiment_id)
        assert status["candidate_verdict"] == "fail"
        outcome = status["measurement"]["outcomes"][0]
        assert outcome["observed"] == expected_observed
        assert outcome["criterion_expected"] == (
            True if independent_checker else optimum
        )
        assert not status["measurement"]["acceptance"]["admitted"]
        assert not status["measurement"]["progress"]["admitted"]
        dispatch = read_record(artifacts, "dispatch", experiment_id=spec.experiment_id)
        assert dispatch["record"]["spec"] == proposals[0]
        assert dispatch["record"]["spec"]["launch_ref"] == evaluations.target_launch_ref
        execution = read_record(artifacts, "execution", run_id=status["run_id"])
        assert execution["record"]["launch_approval_ref"]["configuration_hash"] == launch.configuration_hash
        assert execution["record"]["launch_approval_ref"]["duet_id"] == session.duet_id
        assert parent_prompts
        history = parent_prompts[0]["assignment_context"]["test_history"]["items"]
        failures = [
            row for row in history if row["test_result"]["outcome"]["status"] == "fail"
        ]
        assert failures
        assert all(
            row["test_result"]["outcome"]["observed"] == expected_observed
            for row in failures
        )
        assert all(
            row["test_result"]["outcome"]["predicted"]
            == proposals[0]["requirements"][0]["expected"]
            and row["test_result"]["outcome"]["falsifying"]
            == proposals[0]["requirements"][0]["falsifying"]
            for row in failures
        )
        assert result.verified_build is None
        if independent_checker:
            checker_scope = dispatch["record"]["plan"]["measurements"][0]["instrument"]["scope"]
            assert checker_scope["entry_local_id"] == "check"
            assert checker_scope["included_local_ids"] == ["check"]
            assert checker_scope["origin"] == "fresh_typed_entry"
            assert checker_scope["limitations"]
            assert "goals" not in checker_scope
            checker_run = status["instrument_runs"][0]
            checker_execution = read_record(artifacts, "execution", run_id=checker_run["run_id"])
            assert checker_execution["record"]["launch_approval_ref"] == execution["record"]["launch_approval_ref"]
            assert outcome["evidence_ref"] == checker_run["evidence_ref"]
            assert outcome["evidence_ref"] != status["evidence_ref"]
            assert checker_run["run_id"] != status["run_id"]
            assert all(
                row["test_result"]["execution_ref"] == checker_run["evidence_ref"]
                for row in failures
            )
            from episode_runtime.records.catalog import execution_overview

            checker_record = execution_overview(
                artifacts,
                runs,
                read_record(artifacts, "execution", run_id=checker_run["run_id"]),
            )
            assert checker_record["intent"]["relationship"] == "experiment_instrument"
            assert (
                checker_record["intent"]["parent_experiment_id"] == spec.experiment_id
            )
            assert (
                checker_record["intent"]["target_execution_ref"]
                == status["evidence_ref"]
            )
            assert checker_record["candidate_verdict"] == "unmeasured"
            assert checker_record["measurement_ref"] is None
            assert checker_record["scope"]["boundary_origin"] == "fresh_typed_entry"
            assert checker_record["scope"]["boundary_ref"]
            assert checker_record["scope"]["limitations"]
            assert "input_payload" not in checker_record["scope"]

            service = ExperimentService(
                artifacts=artifacts,
                builds=builds,
                runs=runs,
                executor=evaluations.executor,
            )
            corrected = deepcopy(proposals[0])
            corrected["question"] = (
                "Does the independent checker accept the correct known answer?"
            )
            evaluations.executor.result = {
                "minimum_completion": optimum,
                "checker_pass": False,
                "workflow_result": {"flags": {"checker_pass": False}},
            }
            good = await service.run(ExperimentSpec.from_record(corrected))
            assert good["candidate_verdict"] == "pass"
            assert good["measurement"]["outcomes"][0]["observed"] is True

            # A checker can be interrupted independently of its successful
            # target. Continuing it must select a new measurement while retaining
            # the old report and target evidence. The first checker return here
            # is supplied interruption data, not a worker restoration test.
            interrupted_spec = ExperimentSpec.from_record({
                **corrected, "question": "Does this successful target pass after its checker resumes?",
            })
            executor = evaluations.executor
            execute = executor.execute

            async def interrupt_checker(**kwargs):
                if kwargs["registration"].duet_id != oid("checker_duet"):
                    return await execute(**kwargs)
                executor.terminal = RunTerminalStatus.INTERRUPTED
                try:
                    return await ResultOnlyExecutor.execute(executor, **kwargs)
                finally:
                    executor.terminal = RunTerminalStatus.SUCCEEDED

            with monkeypatch.context() as patch:
                patch.setattr(executor, "execute", interrupt_checker)
                interrupted = await service.run(interrupted_spec)
            assert interrupted["execution_status"] == "succeeded"
            assert interrupted["candidate_verdict"] == "unmeasured"
            old_checker = interrupted["instrument_runs"][0]
            assert old_checker["execution_status"] == "interrupted"
            old_measurement = read_record(artifacts, "measurement", experiment_id=interrupted_spec.experiment_id)
            old_instrument_result = read_record(
                artifacts, "instrument_result", experiment_id=interrupted_spec.experiment_id,
                instrument_id=old_checker["instrument_id"],
            )

            async def continue_checker(**kwargs):
                await kwargs.pop("continuation_admission")()
                return await execute(**kwargs)

            calls = executor.calls
            with monkeypatch.context() as patch:
                patch.setattr(executor, "execute", continue_checker)
                continued = await service.continue_run(
                    experiment_id=interrupted_spec.experiment_id,
                    resume_from=old_checker["resume_from"],
                )
            assert executor.calls == calls + 1
            assert continued["run_id"] == interrupted["run_id"]
            assert continued["evidence_ref"] == interrupted["evidence_ref"]
            assert continued["candidate_verdict"] == "pass"
            new_checker = continued["instrument_runs"][0]
            assert new_checker["run_id"] != old_checker["run_id"]
            assert continued["measurement"]["outcomes"][0]["evidence_ref"] == new_checker["evidence_ref"]
            assert continued["measurement"]["measurement_ref"] != interrupted["measurement"]["measurement_ref"]
            assert read_record(artifacts, "measurement", experiment_id=interrupted_spec.experiment_id) == old_measurement
            assert read_record(
                artifacts, "instrument_result", experiment_id=interrupted_spec.experiment_id,
                instrument_id=old_checker["instrument_id"],
            ) == old_instrument_result
            assert read_record(
                artifacts, "instrument_result_attempt", experiment_id=interrupted_spec.experiment_id,
                instrument_id=old_checker["instrument_id"], run_id=new_checker["run_id"],
            )["record"]["evidence_ref"] == new_checker["evidence_ref"]

            missing = deepcopy(corrected)
            missing["question"] = (
                "Can missing target inputs establish a checker verdict?"
            )
            evaluations.executor.result = {"checker_pass": True}
            missing_spec = ExperimentSpec.from_record(missing)
            calls = evaluations.executor.calls
            unavailable = await service.run(missing_spec)
            assert evaluations.executor.calls == calls + 1
            assert unavailable["candidate_verdict"] == "unmeasured"
            assert unavailable["measurement"]["outcomes"][0]["status"] == "unavailable"
            assert (
                unavailable["instrument_runs"][0]["checking_gap"]["kind"]
                == "checker_input_invalid"
            )
            assert unavailable["instrument_runs"][0]["recording_ref"] is None
            assert await service.run(missing_spec) == unavailable
            assert evaluations.executor.calls == calls + 1
