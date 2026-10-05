"""Native refiner continuation keeps old replies and uses the new Duet model.

Real worker confinement, SDK HTTP, journals and reconstruction. The endpoint
supplies one invalid answer then API errors; this is not reasoning acceptance.
"""

import asyncio
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from agent.duet_contracts import DuetIdentity
from agent.episode_contracts import OpaqueId
from agent.duet_episode_transport import DuetEpisodeBinding, required_slots
from agent.openchia_build_continue import restore_binding
from episode_runtime.contracts import RunEventKind, RunTerminalStatus
from episode_runtime.executor import make_systemd_run_executor_factory
from episode_runtime.executor_lifecycle import verify_stopped_executor
from episode_runtime.records.experiments import execution_attempts, read_record
from episode_runtime.store import RunStore
from episode_runtime.testing_harness.service import ExperimentService
from llm_call_library.transport import ModelCallFailed
from tests.agent.test_episode_model_failure_reporting import error_server
from tests.episode_runtime.testing_harness.refinement_fixture import prepared_refiner
from tests.episode_runtime.testing_harness.test_refinement_job_experiments import job_spec


@pytest.mark.platforms("linux")
@pytest.mark.asyncio
async def test_api_stop_then_explicit_resume_changes_future_model_only(tmp_path, run_store, monkeypatch):
    runtime_dir = Path("/run/user") / str(os.getuid())
    if (runtime_dir / "bus").exists():
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir / 'bus'}")
    status = subprocess.run(["systemctl", "--user", "is-system-running"], capture_output=True, timeout=5)
    if status.stdout.strip() not in {b"running", b"degraded"}:
        pytest.skip("requires a running native user systemd manager")

    def executor(root, _identity):
        return make_systemd_run_executor_factory(
            repository_root=Path(__file__).resolve().parents[3],
        )(RunStore(root / "runs"))

    async with prepared_refiner(tmp_path, run_store[1].runtime_identity, executor_type=executor) as session:
        artifacts, builds, runs = session.store.evidence.duets, session.store.evidence.builds, session.store.evidence.runs
        identity = DuetIdentity.from_record(artifacts.get_duet(session.duet_id)["identity"])
        inputs = builds.inspection_inputs_for_receipt(session.registration.build_receipt_id)
        with error_server("chat_completions", "Server overloaded", respond=lambda body, n: '{"invalid_assignment":true}' if n == 1 else None) as (endpoint, calls):
            runtime = {"model": "original-model", "provider": "custom", "base_url": endpoint, "api_mode": "chat_completions", "session_id": "continuation", "api_key": None}
            agent = SimpleNamespace(_duet_identity=identity, _current_main_runtime=lambda: dict(runtime), reasoning_config={"enabled": True, "effort": "medium"})
            binding = DuetEpisodeBinding.from_bound_agent(
                artifacts=artifacts, owner_duet_id=session.duet_id, agent=agent, model_types=required_slots(inputs),
            )
            spec = job_spec(session, binding)

            def service(selected):
                return ExperimentService(
                    artifacts=artifacts, builds=builds, runs=runs, executor=session.evaluations.executor,
                    duet_binding=selected, refinement_evaluations=session.evaluations,
                )

            first = service(binding)
            host = SimpleNamespace(identity=identity, store=artifacts, _duet_agent=agent)
            runtime["model"] = "not-selected-for-fresh-run"
            unselected = restore_binding(host, binding.reference)
            assert not service(unselected).preview(spec)["resolved"]
            runtime["model"] = "original-model"
            with pytest.raises(ModelCallFailed):
                await asyncio.wait_for(first.run(spec), 240)
            assert len(calls) == 2  # Rejected answer continued; API error stopped.
            stopped = first.status(artifacts, runs, spec.experiment_id)
            old_id = OpaqueId(stopped["run_id"])
            old_audit, old_evidence = runs.read_audit_log(old_id), runs.read_evidence(old_id)
            old_execution = read_record(artifacts, "execution", run_id=old_id.value)
            assert old_evidence.terminal_status is RunTerminalStatus.INTERRUPTED
            assert old_evidence.typed_status["stop_reason"] == "model_api_error"
            assert (await verify_stopped_executor(session.evaluations.executor, runs.read_claim(old_id)))["stopped"]
            with pytest.raises(ModelCallFailed):
                await first.run(spec)
            assert len(calls) == 2  # Re-reading a stopped experiment cannot retry it.

            runtime["model"] = "new-model"
            agent.reasoning_config = {"enabled": True, "effort": "high"}
            current = restore_binding(host, binding.reference)
            assert current.reference != binding.reference
            second = service(current)
            with pytest.raises(ModelCallFailed):
                await asyncio.wait_for(second.continue_interrupted(experiment_id=spec.experiment_id), 240)
            assert len(calls) == 3  # Only the unanswered request was retried.
            assert [call["model"] for call in calls] == ["original-model", "original-model", "new-model"]
            assert calls[-1]["reasoning_effort"] == "high"
            assert calls[-1]["messages"] == calls[-2]["messages"]
            chain = execution_attempts(artifacts, runs, old_id)
            assert len(chain) == 2
            new_id = OpaqueId(chain[-1]["record"]["registration"]["run_id"])
            assert chain[-1]["record"]["duet_model_binding_ref"] == current.reference
            assert old_execution["record"]["duet_model_binding_ref"] == binding.reference
            assert runs.read_audit_log(old_id) == old_audit
            assert runs.read_evidence(old_id) == old_evidence
            assert read_record(artifacts, "execution", run_id=old_id.value) == old_execution
            assert runs.read_evidence(new_id).terminal_status is RunTerminalStatus.INTERRUPTED
            assert (await verify_stopped_executor(session.evaluations.executor, runs.read_claim(new_id)))["stopped"]
            assert any(event.kind is RunEventKind.RUN_RECONSTRUCTED for event in runs.read_audit_log(new_id))
