"""systemd 255 service lifecycle and backend-specific attestation contracts.

The native check runs an actual service with descendants. The existing reasoning
and continuation tests exercise the full admitted Episode worker separately.
"""

import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess

import pytest

from episode_runtime.contracts import (
    ExecutorKind,
    InspectedExecutorAttestation,
    derive_executor_instance_id,
    expected_executor_unit_name,
)
from episode_runtime.executor import (
    ExecutorResources,
    _launch_identity,
    make_systemd_run_executor_factory,
)


@pytest.mark.platforms("linux")
@pytest.mark.asyncio
@pytest.mark.parametrize("resources", [None, ExecutorResources(
    memory_max_bytes=512 * 1024**2, pids_max=32, cpu_weight=73,
    cpu_quota_per_sec_micros=750_000, cpu_period_micros=100_000,
)])
async def test_native_service_inspection_and_host_stop_include_descendants(
    tmp_path, monkeypatch, run_store, resources,
):
    runtime_dir = Path("/run/user") / str(os.getuid())
    if (runtime_dir / "bus").exists():
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir / 'bus'}")
    status = subprocess.run(
        ["systemctl", "--user", "is-system-running"], capture_output=True, timeout=5,
    )
    if status.returncode != 0:
        pytest.skip("native service check requires a running user systemd manager")
    store, registration, _ = run_store
    executor = make_systemd_run_executor_factory(
        repository_root=Path(__file__).resolve().parents[2], resources=resources,
    )(store)
    source, runtime = tmp_path / "source", tmp_path / "runtime"
    source.mkdir()
    runtime.mkdir()
    mounts = executor._runtime_mounts(registration, runtime, source)
    identity = _launch_identity(registration.run_id)
    # This deliberately runs before the worker's no-spawn syscall policy, to
    # establish that service-level cancellation reaches descendants too.
    program = """
import json, os, signal, subprocess, sys
child = subprocess.Popen([sys.executable, '-I', '-S', '-c', 'import signal; signal.pause()'])
print(json.dumps({'parent': os.getpid(), 'child': child.pid}), flush=True)
signal.pause()
"""
    launcher = await executor._launch(registration, identity, mounts, program)
    facts = None
    try:
        facts = await asyncio.wait_for(executor._inspect(identity, launcher, mounts), 15)
        output = await asyncio.wait_for(launcher.stdout.readline(), 15)
        assert output, (await launcher.stderr.read()).decode()
        pids = json.loads(output)
        assert facts.leader_pid == pids["parent"]
        assert facts.process_namespace_isolated is False
        assert facts.filesystem_namespace_isolated and facts.network_namespace_isolated
        assert facts.host_runtime_read_only and facts.no_new_privs
        assert (facts.memory_max_bytes, facts.pids_max, facts.cpu_weight,
                facts.cpu_quota_micros, facts.cpu_period_micros) == (
            executor.resources.memory_max_bytes, executor.resources.pids_max,
            executor.resources.cpu_weight, executor.resources.cpu_quota_per_sec_micros,
            executor.resources.cpu_period_micros,
        )
        await asyncio.wait_for(executor._stop_exact(identity, launcher, facts), 15)
        for pid in pids.values():
            # A terminated child may briefly be a zombie pending init's reap.
            path = Path(f"/proc/{pid}/stat")
            if path.exists():
                assert path.read_text(encoding="ascii").rsplit(")", 1)[1].split()[0] == "Z"
    finally:
        if launcher.returncode is None:
            await executor._stop_exact(identity, launcher, facts)


def test_only_systemd_accepts_no_private_pid_namespace(run_store):
    _, registration, original = run_store
    native = replace(original, process_namespace_isolated=False)
    native.validate_against(registration)
    assert InspectedExecutorAttestation.from_record(native.as_record()) == native
    assert native.content_hash != original.content_hash
    for field in ("filesystem_namespace_isolated", "network_namespace_isolated",
                  "host_runtime_read_only", "no_new_privs"):
        with pytest.raises(ValueError, match="required isolation"):
            replace(native, **{field: False})

    name = expected_executor_unit_name(ExecutorKind.CONTAINER, registration.run_id, "a" * 32)
    instance = derive_executor_instance_id(
        executor_kind=ExecutorKind.CONTAINER, unit_name=name, invocation_id="b" * 64,
        boot_id=original.boot_id, leader_pid=original.leader_pid,
        leader_start_time_ticks=original.leader_start_time_ticks, cgroup_path="/",
    )
    container = replace(
        original, executor_kind=ExecutorKind.CONTAINER, executor_unit_name=name,
        executor_instance_id=instance, executor_invocation_id="b" * 64, cgroup_path="/",
        landlock_receipt=replace(original.landlock_receipt, executor_instance_id=instance),
        seccomp_receipt=replace(original.seccomp_receipt, executor_instance_id=instance),
    )
    with pytest.raises(ValueError, match="container executor must prove"):
        replace(container, process_namespace_isolated=False)
