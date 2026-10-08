"""Preparation failure propagation through real admission and ownership stores.

Faults are injected at the preparation boundary; supplied-result execution is
only a storage fixture. These tests do not claim package or live-model success.
"""

import pytest

from agent.duet_store import DuetStore
from agent.episode_contracts import OpaqueId
from agent.episode_launch import resolve_launch
from episode_runtime.contracts import RunRegistration, RunTerminalStatus
from episode_runtime.records.experiments import execution_attempts, put_data, read_record
from episode_runtime.store import RunStoreNotFound
from episode_runtime.target_environment_preparation import EnvironmentPreparationFailure
from episode_runtime.testing_harness.contracts import ExperimentSpec
from episode_runtime.testing_harness.recovery import (
    claim_execution_owner, execution_owner_status, release_execution_owner,
)
from episode_runtime.testing_harness.service import ExperimentService
from function_library.scheduling_benchmark import optimal_schedule
from iterative_episode_refiner.records import Ref
from tests.episode_builder.test_repeatable_call_materialization import build
from tests.episode_runtime.conftest import oid
from tests.episode_runtime.testing_harness.launch_fixture import FixtureLaunchHost
from tests.episode_runtime.testing_harness.refinement_fixture import prepared_refiner
from tests.episode_runtime.testing_harness.test_experiment_planning import experiment
from tests.episode_runtime.testing_harness.test_measurements import ResultOnlyExecutor
from tests.episode_runtime.testing_harness.test_refinement_experiments import SuppliedTargetExecutor


def _launch(tmp_path, artifacts, builds, duet_id):
    launch = resolve_launch({
        "project": "environment-failure-fixture", "project_root": str(tmp_path),
        "env_files": [],
        "routes": {"local": {
            "provider": "custom", "model": "unused", "base_url": "http://localhost:9999/v1",
            "api_mode": "chat_completions", "auth": {"kind": "none"},
        }},
        "model_slots": {"selector": "local", "executor": "local"},
        "builder_slots": {"planning": "selector", "emission": "executor"},
    })
    FixtureLaunchHost(artifacts, builds, duet_id).approve_fixture(launch)
    return put_data(artifacts, duet_id, "launch", launch.record)


def _failure(artifacts, builds, duet_id):
    output = b"Injected restoration failure before any worker was claimed."
    value = {
        "status": "failed", "prepared": None, "resolved_lock": None,
        "diagnostics": [{
            "stage": "preparation", "error_type": "PreparationProcessFailed",
            "message": "The saved dependency environment could not be restored.",
        }],
        "log_refs": [{
            "stream": "stderr", "content_hash": builds.put_blob(output).value,
            "bytes": len(output),
        }],
    }
    return EnvironmentPreparationFailure({
        **value, "preparation_ref": put_data(artifacts, duet_id, "environment_preparation", value),
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("continued", [False, True])
async def test_unclaimed_preparation_failure_preserves_feedback_and_exact_retry(
    tmp_path, run_store, monkeypatch, continued,
):
    request, builds, receipt = await build(tmp_path, ())
    owner = request.frozen_workflow.duet_id.value
    executor = ResultOnlyExecutor(tmp_path / "execution", run_store[1].runtime_identity)
    runs = executor.run_store
    with DuetStore(tmp_path / "duet.db") as artifacts:
        raw = experiment(artifacts, request, receipt)
        raw["launch_ref"] = _launch(tmp_path, artifacts, builds, owner)
        spec = ExperimentSpec.from_record(raw)
        service = ExperimentService(artifacts=artifacts, builds=builds, runs=runs, executor=executor)
        original = None
        if continued:
            executor.terminal = RunTerminalStatus.INTERRUPTED
            original = await service.run(spec)
        executor.terminal = RunTerminalStatus.SUCCEEDED
        failure = _failure(artifacts, builds, owner)

        async def fail_preparation(**kwargs):
            raise failure

        calls = executor.calls
        with monkeypatch.context() as patch:
            patch.setattr(service.execution, "_execute_owned", fail_preparation)
            result = await service.run(spec) if original is None else await service.continue_run(
                experiment_id=spec.experiment_id, resume_from=original["resume_from"],
            )
            assert result["execution_status"] == "unavailable"
            assert result["candidate_verdict"] == "unmeasured"
            assert result["environment_preparation"] == failure.result
            assert result["environment_subject"] == "target_workflow"
            assert not result["progress"]["admitted"]
            assert "measurement" not in result and "evidence_ref" not in result
            run_id = OpaqueId(result["run_id"])
            row = read_record(artifacts, "execution", run_id=run_id.value)
            registration = RunRegistration.from_record(row["record"]["registration"])
            assert execution_owner_status(artifacts, registration)["state"] == "released"
            with pytest.raises(RunStoreNotFound):
                runs.read_claim(run_id)
            again = await service.continue_interrupted(experiment_id=spec.experiment_id)
            assert again == result
            assert executor.calls == calls
            assert execution_owner_status(artifacts, registration)["state"] == "released"

        recovered = await service.continue_interrupted(experiment_id=spec.experiment_id)
        assert recovered["run_id"] == result["run_id"]
        assert recovered["execution_status"] == "succeeded"
        assert executor.calls == calls + 1
        assert runs.read_evidence(run_id).terminal_status is RunTerminalStatus.SUCCEEDED
        assert len(execution_attempts(artifacts, runs, run_id)) == (2 if continued else 1)
        assert read_record(artifacts, "execution", run_id=run_id.value) == row


@pytest.mark.asyncio
async def test_checker_preparation_failure_is_unmeasured_and_does_not_poison_retry(
    tmp_path, run_store, monkeypatch,
):
    optimum, witness = optimal_schedule()
    async with prepared_refiner(
        tmp_path, run_store[1].runtime_identity,
        runtime_check={
            "expected": True,
            "observation_path": "/payload/typed_status/workflow_result/flags/checker_pass",
            "grounding": {"optimum": optimum, "witness": witness},
        },
        independent_checker=True, executor_type=SuppliedTargetExecutor,
    ) as session:
        artifacts, builds, runs = session.store.evidence.duets, session.store.evidence.builds, session.store.evidence.runs
        with session.view() as view:
            check = next(row.record for row in view.entries("check") if row.record.body["evidence_kind"] == "execution")
            candidate = view.candidate
            receipt = view.data(Ref.from_record(session.contract.body["initial_build_inputs_ref"]))
        inputs = builds.inspection_inputs_for_receipt(receipt["receipt_id"])
        raw = experiment(artifacts, inputs.build_request, inputs.receipt)
        raw.update(
            candidate_ref=candidate.ref.as_record(), campaign_ref=session.contract.ref.as_record(),
            environment_ref=dict(session.contract.body["environment_ref"]),
            launch_ref=_launch(tmp_path, artifacts, builds, session.duet_id),
            requirements=[{
                "requirement_ref": check.ref.as_record(), "measure_ref": dict(check.body["measure_ref"]),
                "expected": "The independent checker accepts the enumerated optimum.",
                "falsifying": "The independent checker rejects the returned value.",
            }],
        )
        spec = ExperimentSpec.from_record(raw)
        executor = session.evaluations.executor
        executor.result = {"minimum_completion": optimum}
        service = ExperimentService(artifacts=artifacts, builds=builds, runs=runs, executor=executor)
        failure = _failure(artifacts, builds, session.duet_id)
        execute = service.execution._execute_owned

        async def fail_checker_preparation(**kwargs):
            if kwargs["registration"].duet_id == oid("checker_duet"):
                raise failure
            return await execute(**kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(service.execution, "_execute_owned", fail_checker_preparation)
            unavailable = await service.run(spec)
        assert unavailable["execution_status"] == "succeeded"  # The target did run.
        assert unavailable["candidate_verdict"] == "unmeasured"
        assert "measurement" not in unavailable
        checker, = unavailable["instrument_runs"]
        assert checker["execution_status"] == "unavailable"
        assert checker["environment_preparation"] == failure.result
        assert checker["environment_subject"] == "measurement"
        assert "evidence_ref" not in checker
        assert read_record(artifacts, "measurement", experiment_id=spec.experiment_id) is None
        assert read_record(
            artifacts, "instrument_result", experiment_id=spec.experiment_id,
            instrument_id=checker["instrument_id"],
        ) is None
        row = read_record(artifacts, "execution", run_id=checker["run_id"])
        registration = RunRegistration.from_record(row["record"]["registration"])
        assert execution_owner_status(artifacts, registration)["state"] == "released"
        with pytest.raises(RunStoreNotFound):
            runs.read_claim(registration.run_id)
        calls = executor.calls
        lease = claim_execution_owner(artifacts, registration)
        try:
            pending = await service.run(spec)
            assert pending["instrument_runs"][0]["execution_status"] == "terminal_evidence_unavailable"
            assert executor.calls == calls  # A live owner is never replaced.
        finally:
            release_execution_owner(artifacts, registration, lease)
        recovered = await service.run(spec)
        assert recovered["candidate_verdict"] == "pass"
        assert recovered["run_id"] == unavailable["run_id"]
        assert recovered["instrument_runs"][0]["run_id"] == checker["run_id"]
        assert executor.calls == calls + 1
        assert await service.run(spec) == recovered  # Claimed terminal Runs stay cached.
        assert executor.calls == calls + 1

        continued_spec = ExperimentSpec.from_record({
            **raw, "question": "Does a continued checker retain its preparation failure attribution?",
        })
        execute_fixture = executor.execute

        async def interrupt_checker(**kwargs):
            if kwargs["registration"].duet_id != oid("checker_duet"):
                return await execute_fixture(**kwargs)
            executor.terminal = RunTerminalStatus.INTERRUPTED
            try:
                return await ResultOnlyExecutor.execute(executor, **kwargs)
            finally:
                executor.terminal = RunTerminalStatus.SUCCEEDED

        with monkeypatch.context() as patch:
            patch.setattr(executor, "execute", interrupt_checker)
            interrupted = await service.run(continued_spec)
        stopped_checker, = interrupted["instrument_runs"]
        with monkeypatch.context() as patch:
            patch.setattr(service.execution, "_execute_owned", fail_checker_preparation)
            continued_failure = await service.continue_run(
                experiment_id=continued_spec.experiment_id,
                resume_from=stopped_checker["resume_from"],
            )
        assert continued_failure["execution_status"] == "unavailable"
        assert continued_failure["environment_subject"] == "measurement"
        assert continued_failure["environment_preparation"] == failure.result
        assert "measurement" not in continued_failure and "evidence_ref" not in continued_failure
        assert continued_failure["run_id"] != interrupted["run_id"]
        assert continued_failure["run_id"] != stopped_checker["run_id"]
