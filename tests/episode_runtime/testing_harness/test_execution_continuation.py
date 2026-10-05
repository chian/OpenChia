"""Shared continuation admission and immutable attempt links through real stores.

Uses the existing supplied-result executor fixture, not resumed worker code.
The callback verifies current authority; these checks do not establish process
confinement, reconstruction or live model reasoning.
"""

from dataclasses import replace

import pytest

from agent.duet_store import DuetStore
from agent.episode_contracts import Sha256Digest
from agent.episode_launch import LaunchConfigurationError, resolve_launch
from episode_runtime.continuation import InterruptedRunRef
from episode_runtime.contracts import RunTerminalStatus
from episode_runtime.records.experiments import execution_attempts, read_record
from episode_runtime.testing_harness.execution import RunExecution, register_build
from episode_runtime.testing_harness.inputs import workflow_template
from episode_runtime.testing_harness.launches import record_launch_intent
from tests.episode_builder.test_repeatable_call_materialization import build
from tests.episode_runtime.testing_harness.launch_fixture import FixtureLaunchHost
from tests.episode_runtime.testing_harness.test_measurements import ResultOnlyExecutor


@pytest.mark.asyncio
@pytest.mark.parametrize("withdraw_launch", [False, True])
async def test_shared_continuation_links_exact_attempts_and_rechecks_current_authority(
    tmp_path, run_store, monkeypatch, withdraw_launch,
):
    request, builds, receipt = await build(tmp_path, ())
    inputs = builds.inspection_inputs_for_receipt(receipt.receipt_id)
    executor = ResultOnlyExecutor(tmp_path / "execution", run_store[1].runtime_identity)
    executor.terminal = RunTerminalStatus.INTERRUPTED
    runs = executor.run_store
    original, package = register_build(
        executor, builds, inputs, workflow_template(request.frozen_workflow),
        run_store[1].runtime_policy,
    )
    launch = resolve_launch({
        "project": "continuation-admission-fixture", "project_root": str(tmp_path),
        "env_files": [],
        "routes": {"local": {
            "provider": "custom", "model": "unused", "base_url": "http://localhost:9999/v1",
            "api_mode": "chat_completions", "auth": {"kind": "none"},
        }},
        "model_slots": {"selector": "local", "executor": "local"},
        "builder_slots": {"planning": "selector", "emission": "executor"},
    })
    with DuetStore(tmp_path / "duet.db") as artifacts:
        owner = original.duet_id.value
        host = FixtureLaunchHost(artifacts, builds, owner)
        host.approve_fixture(launch)
        launch_id, _ = host._prepare_model_launch(
            "run", original.run_id.value, model_types=("selector", "executor"),
        )
        intent = record_launch_intent(artifacts, original, launch_id, launch.configuration_hash)
        execution = RunExecution(artifacts=artifacts, builds=builds, runs=runs, executor=executor)
        arguments = dict(source_package_path=package, intent_ref=intent, model_broker=None, http_broker=None)
        old_evidence = await execution.execute(registration=original, **arguments)
        old_audit = runs.read_audit_log(original.run_id)
        old_dispatch = read_record(artifacts, "execution", run_id=original.run_id.value)
        resumed = replace(original, resume_from=InterruptedRunRef.from_run(runs, original.run_id))
        execute_fixture = executor.execute
        authorities = []

        async def check_activation(**kwargs):
            callback = kwargs.pop("continuation_admission")
            before = artifacts.events(owner)
            authority = await callback()
            authorities.append(authority)
            assert artifacts.events(owner) == before  # Revalidation cannot redispatch.
            if withdraw_launch:
                host._launch_event("launch_configuration_selected", {
                    "mode": "reuse", "selection_id": "new-unapproved-selection",
                    "spec": launch.record["requested_spec"],
                }, human=True)
            assert await callback() == authority
            return await execute_fixture(**kwargs)

        monkeypatch.setattr(executor, "execute", check_activation)
        executor.terminal = RunTerminalStatus.SUCCEEDED
        if withdraw_launch:
            with pytest.raises(LaunchConfigurationError, match="Human launch approval required"):
                await execution.execute(registration=resumed, **arguments)
            assert executor.calls == 1
        else:
            continued = await execution.execute(registration=resumed, **arguments)
            assert continued.terminal_status is RunTerminalStatus.SUCCEEDED
            assert await execution.execute(registration=resumed, **arguments) == continued
            assert executor.calls == 2 and len(authorities) == 1
            forged = replace(resumed, manifest_hash=Sha256Digest.of_bytes(b"different candidate"))
            with pytest.raises(ValueError, match="continuation cannot change"):
                await execution.execute(registration=forged, **arguments)
            assert read_record(artifacts, "execution", run_id=forged.run_id.value) is None

        assert authorities[0]["logical_registration_hash"] == original.registration_hash.value
        assert authorities[0]["launch_approval_ref"] is not None
        chain = execution_attempts(artifacts, runs, original.run_id)
        assert execution_attempts(artifacts, None, resumed.run_id) == chain
        assert [row["record"]["registration"]["run_id"] for row in chain] == [original.run_id.value, resumed.run_id.value]
        assert all(row["record"]["intent_ref"] == intent for row in chain)
        link = read_record(artifacts, "continuation", predecessor_run_id=original.run_id.value)
        assert link["record"]["resume_from"] == resumed.resume_from.as_record()
        assert link["record"]["execution_ref"] == {key: chain[-1][key] for key in ("artifact_id", "content_hash")}
        assert read_record(artifacts, "execution", run_id=original.run_id.value) == old_dispatch
        assert runs.read_audit_log(original.run_id) == old_audit
        assert runs.read_evidence(original.run_id) == old_evidence
        status = execution.status(artifacts, runs, original.run_id.value)
        assert status["run_id"] == resumed.run_id.value
        assert status["logical_run_id"] == original.run_id.value
        assert status["attempts"][0]["execution_status"] == "interrupted"
        assert status["execution_status"] == (
            "terminal_evidence_unavailable" if withdraw_launch else "succeeded"
        )
        assert not status["progress"]["admitted"]
