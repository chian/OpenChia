"""Container Run executor: argument mapping, inspection facts, and the executor seam.

These tests never touch a real container runtime: the CLI is a stub and the
``docker inspect`` / in-container probe outputs are canned.  The integration
test at the end runs only when a Linux container daemon is reachable.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from agent.episode_contracts import OpaqueId, Sha256Digest
from episode_runtime import ExecutorKind, RunExecutor, SystemdRunExecutor
from episode_runtime import container_executor as ce
from episode_runtime.contracts import (
    InterpreterRuntimeIdentity,
    ReadOnlyRuntimeMount,
    RuntimeMountKind,
    derive_executor_instance_id,
    expected_executor_unit_name,
)
from episode_runtime.executor import ExecutorResources, RunExecutionError, _LaunchIdentity

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- resources


def test_only_the_kernel_default_cpu_weight_is_admitted():
    base = dict(memory_max_bytes=None, pids_max=None, cpu_quota_per_sec_micros=None, cpu_period_micros=100_000)
    assert "--cpu-shares" not in ce.container_resource_arguments(ExecutorResources(cpu_weight=100, **base))
    with pytest.raises(ValueError):
        ce.container_resource_arguments(ExecutorResources(cpu_weight=99, **base))


def test_resource_arguments_map_every_bound():
    resources = ExecutorResources(
        memory_max_bytes=4 * 1024 * 1024 * 1024,
        pids_max=4096,
        cpu_weight=100,
        cpu_quota_per_sec_micros=4_000_000,
        cpu_period_micros=100_000,
    )
    args = ce.container_resource_arguments(resources)
    assert args == (
        "--cpu-period", "100000", "--cpu-quota", "400000",
        "--memory", str(4 * 1024 * 1024 * 1024), "--pids-limit", "4096",
    )


def test_unbounded_resources_omit_their_flags():
    resources = ExecutorResources(
        memory_max_bytes=None, pids_max=None, cpu_weight=100,
        cpu_quota_per_sec_micros=None, cpu_period_micros=100_000,
    )
    args = ce.container_resource_arguments(resources)
    assert "--memory" not in args and "--pids-limit" not in args and "--cpu-quota" not in args


def test_cpu_max_parsing_matches_systemd_per_second_semantics():
    assert ce._cpu_max("400000 100000") == (4_000_000, 100_000)
    assert ce._cpu_max("max 100000") == (None, 100_000)
    with pytest.raises(RunExecutionError):
        ce._cpu_max("1 3")  # not a whole microsecond rate


# ------------------------------------------------------------- contracts


def test_container_unit_name_and_executor_id_follow_the_kind():
    run_id = OpaqueId("run_" + "a" * 64)
    nonce = "b" * 32
    container = expected_executor_unit_name(ExecutorKind.CONTAINER, run_id, nonce)
    systemd = expected_executor_unit_name(ExecutorKind.SYSTEMD, run_id, nonce)
    assert systemd == container + ".service"
    boot = "0f3b7b2e-5c1d-4a0e-9d7a-6f2c3b1a9e88"
    executor_id = derive_executor_instance_id(
        executor_kind=ExecutorKind.CONTAINER, unit_name=container, invocation_id="c" * 64,
        boot_id=boot, leader_pid=4242, leader_start_time_ticks=99, cgroup_path="/",
    )
    assert executor_id.value.startswith("executor_")
    with pytest.raises(ValueError):
        derive_executor_instance_id(
            executor_kind=ExecutorKind.CONTAINER, unit_name=container, invocation_id="not-hex",
            boot_id=boot, leader_pid=4242, leader_start_time_ticks=99, cgroup_path="/",
        )
    with pytest.raises(ValueError):  # a systemd unit still needs the cgroup to end at the service
        derive_executor_instance_id(
            executor_kind=ExecutorKind.SYSTEMD, unit_name=systemd, invocation_id="",
            boot_id=boot, leader_pid=1, leader_start_time_ticks=1, cgroup_path="/user.slice/other.service",
        )


# ------------------------------------------------------- executor construction


def _fake_interpreter() -> InterpreterRuntimeIdentity:
    return InterpreterRuntimeIdentity(
        implementation="cpython", version=(3, 14, 7), cache_tag="cpython-314",
        executable_hash=Sha256Digest.of_bytes(b"python"),
        stdlib_file_hashes={"os.py": Sha256Digest.of_bytes(b"os")},
        shared_library_hashes={},
    )


def _runtime(tmp_path: Path) -> ce.ContainerRuntime:
    cli = tmp_path / "docker"
    cli.write_text("#!/bin/sh\nexit 0\n"); cli.chmod(0o755)
    return ce.ContainerRuntime(
        cli=cli, image_reference="python:3.14-slim", image_id="sha256:" + "d" * 64,
        python_executable=PurePosixPath("/usr/local/bin/python3.14"),
        interpreter_runtime=_fake_interpreter(), daemon_cpus=4, daemon_memory_bytes=8 * 1024**3 + 12345,
    )


def test_default_resources_mirror_the_daemon_and_round_memory_to_mib(tmp_path):
    resources = _runtime(tmp_path).default_resources()
    assert resources.memory_max_bytes == 8 * 1024**3  # 12345 trailing bytes dropped
    assert resources.cpu_quota_per_sec_micros == 4_000_000
    assert resources.cpu_period_micros == 100_000 and resources.cpu_weight == 100


def test_container_executor_satisfies_the_host_protocol(tmp_path):
    from episode_runtime.store import RunStore

    executor = ce.ContainerRunExecutor(
        run_store=RunStore(tmp_path / "runs"), repository_root=REPO,
        resources=_runtime(tmp_path).default_resources(), runtime=_runtime(tmp_path),
    )
    assert isinstance(executor, RunExecutor)
    assert executor.python_executable == PurePosixPath("/usr/local/bin/python3.14")
    assert executor._identity_arguments() == {"interpreter_runtime": _fake_interpreter()}


def test_launch_arguments_are_hardened_and_carry_the_same_worker_argv(tmp_path, run_store):
    runtime = _runtime(tmp_path)
    executor = ce.ContainerRunExecutor.__new__(ce.ContainerRunExecutor)
    executor.runtime = runtime
    executor.resources = runtime.default_resources()
    executor.python_executable = runtime.python_executable
    registration = run_store[1]
    run_id = registration.run_id
    mounts = executor._runtime_mounts(
        registration,
        Path("/srv/runtime_pkg") / registration.runtime_identity.runtime_source_manifest_id.value,
        Path("/srv/src") / registration.manifest_id.value,
    )
    identity = _LaunchIdentity(unit_name=expected_executor_unit_name(ExecutorKind.CONTAINER, run_id, "1" * 32),
                               description=f"openchia-episode-launch:{run_id.value}:{'1' * 32}")
    args = executor._launch_arguments(registration, identity, mounts, "print('bootstrap')")
    text = " ".join(args)
    assert args[:3] == (str(runtime.cli), "run", "--rm")
    for required in ("--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
                     f"--user {ce.CONTAINER_USER}", "--pids-limit 4096", "--cpu-period 100000", "--cpu-quota 400000"):
        assert required in text, required
    for mount in mounts:
        assert f"--volume {mount.source_path}:{mount.target_path}:ro" in text
    image_index = args.index(runtime.image_id)
    worker = args[image_index + 1:]
    assert worker[:6] == ("/usr/local/bin/python3.14", "-I", "-S", "-B", "-X", "pycache_prefix=/tmp/openchia-disabled-pycache")
    assert worker[6:8] == ("-c", "print('bootstrap')")
    for flag, value in (
        ("--run-id", registration.run_id.value),
        ("--registration-hash", registration.registration_hash.value),
        ("--logical-run-id", registration.logical_run_id.value),
        ("--logical-registration-hash", registration.logical_registration_hash.value),
        ("--manifest-id", registration.manifest_id.value),
        ("--max-frame-bytes", str(registration.runtime_policy.max_frame_bytes)),
    ):
        assert flag in worker and worker[worker.index(flag) + 1] == value


# ----------------------------------------------------------- inspection


def _canned_inspect(name, description, image_id, *, mounts, network="none", readonly=True, nnp=True):
    return {
        "Id": "c" * 64, "Name": "/" + name, "Image": image_id,
        "State": {"Running": True, "Status": "running", "Pid": 4242},
        "Config": {"Labels": {"openchia.launch": description}},
        "HostConfig": {
            "NetworkMode": network, "ReadonlyRootfs": readonly, "PidMode": "",
            "SecurityOpt": ["no-new-privileges"] if nnp else [], "CapDrop": ["ALL"],
        },
        "Mounts": [{"Type": "bind", "Source": m.source_path, "Destination": m.target_path, "RW": False} for m in mounts],
    }


def _canned_probe(mounts, *, ro=True, nnp="1"):
    table = {"/": [{"options": ["ro" if ro else "rw"], "fstype": "overlay"}], "/tmp": [{"options": ["rw", "nosuid"], "fstype": "tmpfs"}]}
    for m in mounts:
        table[m.target_path] = [{"options": ["ro" if ro else "rw", "relatime"], "fstype": "fakeowner"}]
    return {
        "boot_id": "fd573bc2-ae45-473b-81a1-20b71face43e", "leader_start_time_ticks": 1234, "cgroup_path": "/",
        "no_new_privs": nnp, "cpu_max": "400000 100000", "cpu_weight": "100",
        "memory_max": str(8 * 1024**3), "pids_max": "4096", "mounts": table, "uid": 65534,
    }


def _inspect_with(monkeypatch, tmp_path, inspect_record, probe_record):
    runtime = _runtime(tmp_path)
    executor = ce.ContainerRunExecutor.__new__(ce.ContainerRunExecutor)
    executor.runtime = runtime
    executor.resources = runtime.default_resources()
    executor.python_executable = runtime.python_executable

    async def fake_inspect(self, name):
        return inspect_record

    async def fake_probe(self, name):
        return probe_record

    monkeypatch.setattr(ce.ContainerRunExecutor, "_inspect_container", fake_inspect)
    monkeypatch.setattr(ce.ContainerRunExecutor, "_probe", fake_probe)
    launcher = SimpleNamespace(returncode=None)
    run_id = OpaqueId("run_" + "e" * 64)
    nonce = "2" * 32
    identity = _LaunchIdentity(unit_name=expected_executor_unit_name(ExecutorKind.CONTAINER, run_id, nonce),
                               description=f"openchia-episode-launch:{run_id.value}:{nonce}")
    mounts = (
        ReadOnlyRuntimeMount(kind=RuntimeMountKind.RUNTIME_SOURCE_PACKAGE, source_path="/srv/rt/pkg_a", target_path="/tmp/inputs/pkg_a"),
        ReadOnlyRuntimeMount(kind=RuntimeMountKind.SOURCE_PACKAGE, source_path="/srv/src/pkg_b", target_path="/tmp/inputs/pkg_b"),
    )
    return executor, identity, mounts, launcher


def test_inspection_builds_facts_that_prove_every_isolation_fact(monkeypatch, tmp_path):
    runtime = _runtime(tmp_path)
    executor, identity, mounts, launcher = _inspect_with(monkeypatch, tmp_path, None, None)
    monkeypatch.setattr(ce.ContainerRunExecutor, "_inspect_container",
                        lambda self, name: _async(_canned_inspect(identity.unit_name, identity.description, runtime.image_id, mounts=mounts)))
    monkeypatch.setattr(ce.ContainerRunExecutor, "_probe", lambda self, name: _async(_canned_probe(mounts)))
    facts = asyncio.run(executor._inspect(identity, launcher, mounts))
    assert facts.executor_kind is ExecutorKind.CONTAINER
    assert facts.invocation_id == "c" * 64 and facts.leader_pid == 4242
    assert facts.read_only_runtime_mounts == mounts
    assert (facts.filesystem_namespace_isolated, facts.process_namespace_isolated, facts.network_namespace_isolated,
            facts.host_runtime_read_only, facts.no_new_privs) == (True, True, True, True, True)
    assert (facts.memory_max_bytes, facts.pids_max, facts.cpu_weight, facts.cpu_quota_micros, facts.cpu_period_micros) == (
        8 * 1024**3, 4096, 100, 4_000_000, 100_000)
    assert facts.executor_instance_id.value.startswith("executor_")


def _async(value):
    async def coroutine():
        return value
    return coroutine()


@pytest.mark.parametrize("breakage", ["rw-mount", "network", "no-nnp", "wrong-label", "wrong-quota"])
def test_inspection_rejects_a_container_that_breaks_the_policy(monkeypatch, tmp_path, breakage):
    runtime = _runtime(tmp_path)
    executor, identity, mounts, launcher = _inspect_with(monkeypatch, tmp_path, None, None)
    inspect_record = _canned_inspect(identity.unit_name, identity.description, runtime.image_id, mounts=mounts)
    probe_record = _canned_probe(mounts)
    if breakage == "rw-mount":
        probe_record = _canned_probe(mounts, ro=False)
    elif breakage == "network":
        inspect_record["HostConfig"]["NetworkMode"] = "bridge"
    elif breakage == "no-nnp":
        probe_record["no_new_privs"] = "0"
    elif breakage == "wrong-label":
        inspect_record["Config"]["Labels"]["openchia.launch"] = "openchia-episode-launch:run_x:" + "9" * 32
    elif breakage == "wrong-quota":
        probe_record["cpu_max"] = "200000 100000"
    monkeypatch.setattr(ce.ContainerRunExecutor, "_inspect_container", lambda self, name: _async(inspect_record))
    monkeypatch.setattr(ce.ContainerRunExecutor, "_probe", lambda self, name: _async(probe_record))
    if breakage in ("network", "no-nnp"):
        # these produce facts whose isolation booleans are False; the attestation contract rejects them
        facts = asyncio.run(executor._inspect(identity, launcher, mounts))
        assert not (facts.network_namespace_isolated and facts.no_new_privs)
    else:
        with pytest.raises(RunExecutionError):
            asyncio.run(executor._inspect(identity, launcher, mounts))


# ------------------------------------------------------------ selection


def test_backend_selection(monkeypatch):
    from episode_runtime import executor_selection as sel

    monkeypatch.delenv(sel.EXECUTOR_BACKEND_ENV, raising=False)
    # ADR 0005: the container is the default everywhere; host systemd never selects.
    assert sel.resolve_executor_backend() == "container"
    assert sel.resolve_executor_backend("auto") == "container"
    assert sel.resolve_executor_backend("systemd") == "systemd"
    monkeypatch.setenv(sel.EXECUTOR_BACKEND_ENV, "systemd")
    assert sel.resolve_executor_backend() == "systemd"
    assert sel.resolve_executor_backend("container") == "container"
    monkeypatch.setenv(sel.EXECUTOR_BACKEND_ENV, "bogus")
    with pytest.raises(ValueError):
        sel.resolve_executor_backend()


def test_systemd_executor_still_satisfies_the_protocol():
    assert issubclass(SystemdRunExecutor, ce._RunExecutorBase)
    for name in ("inspect_runtime_identity", "execute", "_launch", "_inspect", "_stop_exact", "_identity_arguments"):
        assert callable(getattr(SystemdRunExecutor, name))


# ------------------------------------------------------- live daemon (optional)


def _daemon_available() -> bool:
    try:
        cli = ce.find_container_cli()
    except ce.ContainerRuntimeError:
        return False
    try:
        completed = subprocess.run([str(cli), "info", "--format", "{{.OSType}}"], capture_output=True, timeout=20)
    except Exception:
        return False
    return completed.returncode == 0 and completed.stdout.strip() == b"linux"


@pytest.mark.skipif(not _daemon_available(), reason="no Linux container daemon reachable")
def test_live_image_interpreter_identity_is_stable_and_pinned():
    runtime = ce.inspect_container_runtime(repository_root=REPO, pull=False)
    assert runtime.image_id.startswith("sha256:")
    assert runtime.interpreter_runtime.version[:2] == (3, 14)
    again = ce.inspect_container_runtime(repository_root=REPO, pull=False)
    assert again.interpreter_runtime.as_record() == runtime.interpreter_runtime.as_record()
    assert runtime.python_executable.is_absolute()
