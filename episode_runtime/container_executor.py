"""Container-backed Run executor: the systemd Run protocol inside an OCI container.

The leader is launched with a Docker-compatible CLI (Docker, Rancher Desktop,
Podman) instead of ``systemd-run``.  Everything the worker sees is the same —
the read-only runtime and source packages at the same paths, the same
interpreter flags and bootstrap argv, stdin/stdout as the protocol pipes, no
network — so the worker, the bootstrap and the evidence chain are untouched.

What differs is how the host inspects the leader.  ``systemctl show`` and the
host's ``/proc`` are replaced by ``docker inspect`` (container id, leader pid,
runtime policy as applied) plus one probe executed *inside* the container that
reads its own ``/proc/1`` and cgroup files: kernel boot id, leader start time,
cgroup path, ``NoNewPrivs``, the live cpu/memory/pids ceilings, and the mount
table proving every runtime input is mounted read-only.  Mount *content*
integrity is proven by the worker, which hashes every staged file against the
registered manifest before it reports ready.

The worker interpreter is the image's, not the host's.  Its identity is
captured by running the bootstrap's ``--inspect-interpreter`` mode in the exact
image (by digest) once per host process; the same bootstrap code verifies it at
every launch.  This is what lets a macOS host — whose own Python can never be
the worker's — register and execute Linux Runs.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional

from agent.episode_contracts import OpaqueId

from .contracts import (
    ExecutorKind,
    InterpreterRuntimeIdentity,
    ReadOnlyRuntimeMount,
    RunRegistration,
    RuntimeIdentity,
    RuntimeMountKind,
)
from .executor import (
    ExecutorResources,
    RunExecutionError,
    _ExecutorFacts,
    _LaunchIdentity,
    _RunExecutorBase,
    _launch_identity,
)
from .identity import (
    BOOTSTRAP_SOURCE_PATH,
    inspect_runtime_identity,
    interpreter_runtime_from_inspection,
)
from .store import RunStore


DEFAULT_CONTAINER_IMAGE = "python:3.14-slim"
#: An unprivileged, nameless uid/gid (``nobody``) for the leader and every probe.
CONTAINER_USER = "65534:65534"
#: Writable scratch for the interpreter inside an otherwise read-only root.
_TMPFS_SPEC = "/tmp:rw,nosuid,nodev,size=256m"
_DEFAULT_PIDS_MAX = 4096
_CPU_PERIOD_MICROS = 100_000
_MIB = 1 << 20

#: Desktop container runtimes keep their CLI outside PATH until their shell
#: integration is installed; the platform resolver probes these after PATH.
_CONTAINER_DESKTOP_DIRS = (
    "/Applications/Docker.app/Contents/Resources/bin",
    "/Applications/Rancher Desktop.app/Contents/Resources/resources/darwin/bin",
)
#: How long a launched container may take to reach the running state before the
#: Run is failed instead of waiting on a wedged or unauthorized daemon forever.
CONTAINER_START_TIMEOUT_SECONDS = 120.0

# Executed with ``docker exec`` inside the running container (stdlib only, the
# worker's own interpreter, same uid as the leader).  It reports the facts the
# host cannot see across the VM boundary.  Its output is data the host then
# checks against the launch policy; it carries no authority on its own.
_PROBE_SOURCE = r'''
import json, os
def read(path):
    with open(path, "r", encoding="utf-8") as stream:
        return stream.read()
after_comm = read("/proc/1/stat").rsplit(")", 1)[1].split()
status = {}
for line in read("/proc/1/status").splitlines():
    key, sep, value = line.partition(":")
    if sep:
        status[key] = value.strip()
cgroup = ""
for line in read("/proc/1/cgroup").splitlines():
    if line.startswith("0::"):
        cgroup = line[3:]
def control(name):
    try:
        return read("/sys/fs/cgroup/" + name).strip()
    except OSError:
        return None
mounts = {}
for line in read("/proc/1/mountinfo").splitlines():
    parts = line.split(" ")
    separator = parts.index("-")
    mountpoint = parts[4].replace("\\040", " ")
    mounts.setdefault(mountpoint, []).append({
        "options": parts[5].split(","),
        "fstype": parts[separator + 1],
    })
print(json.dumps({
    "boot_id": read("/proc/sys/kernel/random/boot_id").strip(),
    "leader_start_time_ticks": int(after_comm[19]),
    "cgroup_path": cgroup,
    "no_new_privs": status.get("NoNewPrivs"),
    "cpu_max": control("cpu.max"),
    "cpu_weight": control("cpu.weight"),
    "memory_max": control("memory.max"),
    "pids_max": control("pids.max"),
    "mounts": mounts,
    "uid": os.getuid(),
}, sort_keys=True))
'''


class ContainerRuntimeError(RuntimeError):
    """The container runtime, image, or its interpreter could not be established."""


def find_container_cli(explicit: str | Path | None = None) -> Path:
    """Locate a Docker-compatible CLI: explicit path, ``OPENCHIA_CONTAINER_CLI``,
    then ``docker``/``podman`` on PATH and in the desktop runtimes' install dirs,
    all through the platform resolver."""
    from hermes_platform.resolver.core import locate_command
    from hermes_platform.resolver.known_dirs import homebrew_dirs, user_local_bin

    names: list[str] = []
    if explicit is not None:
        names.append(str(explicit))
    env = os.environ.get("OPENCHIA_CONTAINER_CLI")
    if env:
        names.append(env)
    names.extend(("docker", "podman"))
    known_dirs = (*homebrew_dirs(), *user_local_bin(), *_CONTAINER_DESKTOP_DIRS)
    for name in names:
        command = locate_command(name, known_dirs=known_dirs).command
        if command:
            return Path(command[0]).resolve(strict=True)
    raise ContainerRuntimeError(
        "no Docker-compatible CLI found (install Docker Desktop, Rancher Desktop or Podman, "
        "or set OPENCHIA_CONTAINER_CLI)"
    )


#: The only CPU weight the container executor admits: the kernel default, which
#: every container runtime leaves untouched when ``--cpu-shares`` is not passed.
#: runc's shares-to-weight mapping has changed between releases (linear, then
#: quadratic), so a weight that must be *computed* from shares cannot be
#: verified portably; the default needs no mapping at all.
CONTAINER_CPU_WEIGHT = 100


def container_resource_arguments(resources: ExecutorResources) -> tuple[str, ...]:
    """``docker run`` flags that make the container's cgroup equal *resources*.

    ``cpu_weight`` must be :data:`CONTAINER_CPU_WEIGHT`; the probe reads the
    live ``cpu.weight`` back and the attestation requires equality.
    """
    if not isinstance(resources, ExecutorResources):
        raise TypeError("resources must be ExecutorResources")
    if resources.cpu_weight != CONTAINER_CPU_WEIGHT:
        raise ValueError(
            f"the container executor admits only cpu_weight={CONTAINER_CPU_WEIGHT}; "
            "runtimes map --cpu-shares to cgroup weights inconsistently"
        )
    arguments: list[str] = ["--cpu-period", str(resources.cpu_period_micros)]
    if resources.cpu_quota_per_sec_micros is not None:
        quota = resources.cpu_quota_per_sec_micros * resources.cpu_period_micros
        if quota % 1_000_000:
            raise ValueError("cpu quota must be a whole number of microseconds per period")
        arguments.extend(("--cpu-quota", str(quota // 1_000_000)))
    if resources.memory_max_bytes is not None:
        arguments.extend(("--memory", str(resources.memory_max_bytes)))
    if resources.pids_max is not None:
        arguments.extend(("--pids-limit", str(resources.pids_max)))
    return tuple(arguments)


def container_isolation_arguments() -> tuple[str, ...]:
    return (
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", CONTAINER_USER,
        "--tmpfs", _TMPFS_SPEC,
        "--workdir", "/",
    )


@dataclass(frozen=True)
class ContainerRuntime:
    """One container runtime and the exact image whose interpreter the worker runs."""

    cli: Path
    image_reference: str
    image_id: str
    python_executable: PurePosixPath
    interpreter_runtime: InterpreterRuntimeIdentity
    daemon_cpus: int
    daemon_memory_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.cli, Path):
            raise TypeError("cli must be a Path")
        if not isinstance(self.image_id, str) or not self.image_id.startswith("sha256:"):
            raise ValueError("image_id must be an image digest")
        if not isinstance(self.python_executable, PurePosixPath) or not self.python_executable.is_absolute():
            raise ValueError("python_executable must be an absolute container path")
        if not isinstance(self.interpreter_runtime, InterpreterRuntimeIdentity):
            raise TypeError("interpreter_runtime must be an InterpreterRuntimeIdentity")
        for name in ("daemon_cpus", "daemon_memory_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")

    def default_resources(self) -> ExecutorResources:
        """The container VM's whole allocation: the only host ceiling that exists.

        Memory is rounded down to a MiB so the cgroup stores it unchanged on
        any page size; the probe must read back exactly these values.
        """
        return ExecutorResources(
            memory_max_bytes=(self.daemon_memory_bytes // _MIB) * _MIB,
            pids_max=_DEFAULT_PIDS_MAX,
            cpu_weight=CONTAINER_CPU_WEIGHT,
            cpu_quota_per_sec_micros=self.daemon_cpus * 1_000_000,
            cpu_period_micros=_CPU_PERIOD_MICROS,
        )


def _run_cli(cli: Path, *arguments: str, stdin: bytes | None = None, timeout: float = 300.0) -> str:
    try:
        completed = subprocess.run(
            [str(cli), *arguments],
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ContainerRuntimeError(f"{cli.name} {arguments[0]} failed: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()[:500]
        raise ContainerRuntimeError(f"{cli.name} {' '.join(arguments[:2])} failed: {detail}")
    return completed.stdout.decode("utf-8", errors="strict")


def inspect_container_runtime(
    *,
    repository_root: str | Path,
    image: str = DEFAULT_CONTAINER_IMAGE,
    cli: str | Path | None = None,
    pull: bool = True,
) -> ContainerRuntime:
    """Resolve the CLI, pin the image by digest, and capture its interpreter identity.

    The identity is produced by the repository's own bootstrap running inside
    the image, so it is byte-for-byte what the worker's bootstrap will verify.
    """
    cli_path = find_container_cli(cli)
    root = Path(repository_root).expanduser().resolve(strict=True)
    try:
        info = json.loads(_run_cli(cli_path, "info", "--format", "{{json .}}", timeout=60))
    except json.JSONDecodeError as exc:
        raise ContainerRuntimeError("container daemon info is not JSON") from exc
    if info.get("OSType") != "linux":
        raise ContainerRuntimeError("the container daemon must run Linux containers")
    cpus = info.get("NCPU")
    memory = info.get("MemTotal")
    if not isinstance(cpus, int) or cpus < 1 or not isinstance(memory, int) or memory < _MIB:
        raise ContainerRuntimeError("container daemon did not report its CPU and memory allocation")
    try:
        image_id = _run_cli(cli_path, "image", "inspect", "--format", "{{.Id}}", image, timeout=60).strip()
    except ContainerRuntimeError:
        if not pull:
            raise
        _run_cli(cli_path, "pull", "--quiet", image, timeout=900)
        image_id = _run_cli(cli_path, "image", "inspect", "--format", "{{.Id}}", image, timeout=60).strip()
    bootstrap = (root / BOOTSTRAP_SOURCE_PATH).read_text(encoding="utf-8")
    output = _run_cli(
        cli_path,
        "run", "--rm", "-i",
        *container_isolation_arguments(),
        image_id,
        "python", "-I", "-S", "-B", "-c", bootstrap, "--inspect-interpreter",
        timeout=600,
    )
    try:
        record = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ContainerRuntimeError("image interpreter inspection is not JSON") from exc
    if not isinstance(record, dict) or not isinstance(record.get("executable_path"), str):
        raise ContainerRuntimeError("image interpreter inspection omitted the executable path")
    return ContainerRuntime(
        cli=cli_path,
        image_reference=image,
        image_id=image_id,
        python_executable=PurePosixPath(record["executable_path"]),
        interpreter_runtime=interpreter_runtime_from_inspection(record),
        daemon_cpus=cpus,
        daemon_memory_bytes=memory,
    )


async def _cli_output(cli: Path, *arguments: str) -> str:
    process = await asyncio.create_subprocess_exec(
        str(cli),
        *arguments,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        raise RunExecutionError(f"{cli.name} {arguments[0]} failed")
    try:
        return stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RunExecutionError("container inspection returned non-UTF-8 data") from exc


def _optional_limit(value: object, name: str) -> Optional[int]:
    if value in (None, "max"):
        return None
    try:
        parsed = int(str(value))
    except ValueError as exc:
        raise RunExecutionError(f"container {name} is malformed") from exc
    if parsed < 1:
        raise RunExecutionError(f"container {name} is not positive")
    return parsed


def _cpu_max(value: object) -> tuple[Optional[int], int]:
    """``cpu.max`` -> (quota in microseconds per second or None, period in microseconds)."""
    if not isinstance(value, str):
        raise RunExecutionError("container cpu.max is absent")
    parts = value.split()
    if len(parts) != 2:
        raise RunExecutionError("container cpu.max is malformed")
    period = _optional_limit(parts[1], "cpu.max period")
    if period is None:
        raise RunExecutionError("container cpu.max period is malformed")
    if parts[0] == "max":
        return None, period
    quota = _optional_limit(parts[0], "cpu.max quota")
    if quota is None:
        raise RunExecutionError("container cpu.max quota is malformed")
    per_second = quota * 1_000_000
    if per_second % period:
        raise RunExecutionError("container cpu quota is not a whole microsecond rate")
    return per_second // period, period


def _mount_is_read_only(mounts: Mapping[str, Any], target: str) -> bool:
    entries = mounts.get(target)
    if not isinstance(entries, list) or not entries:
        return False
    for mountpoint, stacked in mounts.items():
        if mountpoint == target or mountpoint.startswith(target + "/"):
            if not all(
                isinstance(entry, dict) and "ro" in entry.get("options", [])
                for entry in stacked
            ):
                return False
    return True


@dataclass
class ContainerRunExecutor(_RunExecutorBase):
    """Launch, attest, broker, persist, and tear down one Run in one container."""

    run_store: RunStore
    repository_root: Path
    resources: ExecutorResources
    runtime: ContainerRuntime
    python_executable: PurePosixPath = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.run_store, RunStore):
            raise TypeError("run_store must be a RunStore")
        if not isinstance(self.resources, ExecutorResources):
            raise TypeError("resources must be ExecutorResources")
        if not isinstance(self.runtime, ContainerRuntime):
            raise TypeError("runtime must be a ContainerRuntime")
        root = Path(self.repository_root).expanduser()
        if root.is_symlink():
            raise ValueError("repository_root cannot be a symlink")
        self.repository_root = root.resolve(strict=True)
        if not self.repository_root.is_dir():
            raise ValueError("repository_root must be a directory")
        self.python_executable = self.runtime.python_executable

    # --- identity -----------------------------------------------------------

    def _identity_arguments(self) -> dict[str, Any]:
        return {"interpreter_runtime": self.runtime.interpreter_runtime}

    def inspect_runtime_identity(
        self,
        *,
        destination_root: str | Path,
    ) -> RuntimeIdentity:
        return inspect_runtime_identity(
            repository_root=self.repository_root,
            destination_root=destination_root,
            interpreter_runtime=self.runtime.interpreter_runtime,
        )

    def _launch_identity(self, run_id: OpaqueId) -> _LaunchIdentity:
        return _launch_identity(run_id, ExecutorKind.CONTAINER)

    # --- launch -------------------------------------------------------------

    def _runtime_mounts(
        self,
        registration: RunRegistration,
        runtime_source_package: Path,
        source_package: Path,
    ) -> tuple[ReadOnlyRuntimeMount, ...]:
        suffix = registration.run_id.value.rsplit("_", 1)[-1][:40]
        base = PurePosixPath(f"/tmp/openchia-episode-inputs-{suffix}")
        return (
            ReadOnlyRuntimeMount(
                kind=RuntimeMountKind.RUNTIME_SOURCE_PACKAGE,
                source_path=str(runtime_source_package),
                target_path=str(
                    base / registration.runtime_identity.runtime_source_manifest_id.value
                ),
            ),
            ReadOnlyRuntimeMount(
                kind=RuntimeMountKind.SOURCE_PACKAGE,
                source_path=str(source_package),
                target_path=str(base / registration.manifest_id.value),
            ),
        )

    def _worker_arguments(
        self,
        registration: RunRegistration,
        mounts: tuple[ReadOnlyRuntimeMount, ...],
        bootstrap_program: str,
    ) -> tuple[str, ...]:
        by_kind = {mount.kind: mount for mount in mounts}
        runtime_source = by_kind[RuntimeMountKind.RUNTIME_SOURCE_PACKAGE].target_path
        source = by_kind[RuntimeMountKind.SOURCE_PACKAGE].target_path
        return (
            str(self.python_executable),
            "-I",
            "-S",
            "-B",
            "-X",
            "pycache_prefix=/tmp/openchia-disabled-pycache",
            "-c",
            bootstrap_program,
            "--bootstrap-package",
            runtime_source,
            "--bootstrap-manifest-id",
            registration.runtime_identity.runtime_source_manifest_id.value,
            "--bootstrap-manifest-hash",
            registration.runtime_identity.runtime_source_manifest_hash.value,
            "--run-id",
            registration.run_id.value,
            "--registration-hash",
            registration.registration_hash.value,
            "--manifest-id",
            registration.manifest_id.value,
            "--max-frame-bytes",
            str(registration.runtime_policy.max_frame_bytes),
            "--source-package",
            source,
            "--runtime-source-package",
            runtime_source,
        )

    def _launch_arguments(
        self,
        registration: RunRegistration,
        launch_identity: _LaunchIdentity,
        mounts: tuple[ReadOnlyRuntimeMount, ...],
        bootstrap_program: str,
    ) -> tuple[str, ...]:
        arguments: list[str] = [
            str(self.runtime.cli),
            "run",
            "--rm",
            "-i",
            "--name",
            launch_identity.unit_name,
            "--label",
            f"openchia.launch={launch_identity.description}",
            *container_isolation_arguments(),
            *container_resource_arguments(self.resources),
        ]
        for mount in mounts:
            arguments.extend(("--volume", f"{mount.source_path}:{mount.target_path}:ro"))
        arguments.append(self.runtime.image_id)
        arguments.extend(self._worker_arguments(registration, mounts, bootstrap_program))
        return tuple(arguments)

    async def _launch(
        self,
        registration: RunRegistration,
        launch_identity: _LaunchIdentity,
        mounts: tuple[ReadOnlyRuntimeMount, ...],
        bootstrap_program: str,
    ) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            *self._launch_arguments(registration, launch_identity, mounts, bootstrap_program),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

    # --- inspection ---------------------------------------------------------

    async def _inspect_container(self, name: str) -> Mapping[str, Any]:
        output = await _cli_output(
            self.runtime.cli, "inspect", "--type", "container", "--format", "{{json .}}", name
        )
        try:
            record = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RunExecutionError("container inspection is not JSON") from exc
        if not isinstance(record, dict):
            raise RunExecutionError("container inspection is malformed")
        return record

    async def _probe(self, name: str) -> Mapping[str, Any]:
        output = await _cli_output(
            self.runtime.cli,
            "exec",
            "--user",
            CONTAINER_USER,
            name,
            str(self.python_executable),
            "-I",
            "-S",
            "-B",
            "-c",
            _PROBE_SOURCE,
        )
        try:
            record = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RunExecutionError("container probe output is not JSON") from exc
        if not isinstance(record, dict):
            raise RunExecutionError("container probe output is malformed")
        return record

    async def _inspect(
        self,
        launch_identity: _LaunchIdentity,
        launcher: asyncio.subprocess.Process,
        mounts: tuple[ReadOnlyRuntimeMount, ...],
    ) -> _ExecutorFacts:
        name = launch_identity.unit_name
        deadline = asyncio.get_running_loop().time() + CONTAINER_START_TIMEOUT_SECONDS
        last_error: Optional[BaseException] = None
        while True:
            if launcher.returncode is not None:
                raise RunExecutionError("container exited before inspection")
            if asyncio.get_running_loop().time() > deadline:
                raise RunExecutionError(
                    "container did not become inspectable within "
                    f"{CONTAINER_START_TIMEOUT_SECONDS:.0f}s"
                    + (f" (last inspection error: {last_error})" if last_error else "")
                ) from last_error
            try:
                info = await self._inspect_container(name)
            except RunExecutionError as exc:
                last_error = exc
                await asyncio.sleep(0.05)
                continue
            state = info.get("State") or {}
            if state.get("Running") is True:
                break
            if state.get("Status") in {"exited", "dead", "removing"}:
                raise RunExecutionError("container did not reach the running state")
            if asyncio.get_running_loop().time() > deadline:
                raise RunExecutionError(
                    "container did not reach the running state within "
                    f"{CONTAINER_START_TIMEOUT_SECONDS:.0f}s"
                )
            await asyncio.sleep(0.05)

        container_id = info.get("Id")
        host_config = info.get("Config") or {}
        run_config = info.get("HostConfig") or {}
        labels = host_config.get("Labels") or {}
        if (
            not isinstance(container_id, str)
            or labels.get("openchia.launch") != launch_identity.description
            or info.get("Name", "").lstrip("/") != name
            or info.get("Image") != self.runtime.image_id
        ):
            raise RunExecutionError("container identity disagrees with the launch")
        pid = state.get("Pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
            raise RunExecutionError("container leader pid is unknown")

        probe = await self._probe(name)
        if probe.get("uid") != int(CONTAINER_USER.split(":")[0]):
            raise RunExecutionError("container leader is not the unprivileged runtime user")
        mounts_table = probe.get("mounts")
        if not isinstance(mounts_table, dict):
            raise RunExecutionError("container probe omitted the mount table")
        mounts_read_only = all(
            _mount_is_read_only(mounts_table, mount.target_path) for mount in mounts
        )
        inspected_mounts = {
            (entry.get("Destination"), entry.get("Source"), entry.get("RW"))
            for entry in info.get("Mounts") or []
            if isinstance(entry, dict)
        }
        mounts_declared_read_only = all(
            (mount.target_path, mount.source_path, False) in inspected_mounts
            for mount in mounts
        )
        tmp_is_private = any(
            entry.get("fstype") == "tmpfs" for entry in mounts_table.get("/tmp", [])
        )
        security_options = run_config.get("SecurityOpt") or []
        no_new_privs = (
            any(str(option).startswith("no-new-privileges") for option in security_options)
            and probe.get("no_new_privs") == "1"
        )
        cap_drop = run_config.get("CapDrop") or []
        if "ALL" not in cap_drop:
            raise RunExecutionError("container retains capabilities")
        cpu_quota, cpu_period = _cpu_max(probe.get("cpu_max"))
        cpu_weight = _optional_limit(probe.get("cpu_weight"), "cpu.weight")
        if cpu_weight is None:
            raise RunExecutionError("container cpu.weight is absent")
        facts = _ExecutorFacts(
            executor_kind=ExecutorKind.CONTAINER,
            unit_name=name,
            invocation_id=container_id,
            launch_description=launch_identity.description,
            boot_id=str(probe.get("boot_id", "")),
            leader_pid=pid,
            leader_start_time_ticks=int(probe.get("leader_start_time_ticks", 0)),
            cgroup_path=str(probe.get("cgroup_path", "")),
            read_only_runtime_mounts=mounts if (mounts_read_only and mounts_declared_read_only) else (),
            memory_max_bytes=_optional_limit(probe.get("memory_max"), "memory.max"),
            pids_max=_optional_limit(probe.get("pids_max"), "pids.max"),
            cpu_weight=cpu_weight,
            cpu_quota_micros=cpu_quota,
            cpu_period_micros=cpu_period,
            filesystem_namespace_isolated=(
                run_config.get("ReadonlyRootfs") is True
                and tmp_is_private
                and mounts_read_only
                and mounts_declared_read_only
            ),
            process_namespace_isolated=run_config.get("PidMode", "") in ("", "private"),
            network_namespace_isolated=run_config.get("NetworkMode") == "none",
            host_runtime_read_only=(
                run_config.get("ReadonlyRootfs") is True
                and mounts_read_only
                and mounts_declared_read_only
            ),
            no_new_privs=no_new_privs,
        )
        if facts.read_only_runtime_mounts != mounts:
            raise RunExecutionError("container runtime inputs are not all mounted read-only")
        live = (
            facts.memory_max_bytes, facts.pids_max, facts.cpu_weight,
            facts.cpu_quota_micros, facts.cpu_period_micros,
        )
        policy = (
            self.resources.memory_max_bytes, self.resources.pids_max, self.resources.cpu_weight,
            self.resources.cpu_quota_per_sec_micros, self.resources.cpu_period_micros,
        )
        if live != policy:
            raise RunExecutionError(
                "live cgroup allocation differs from launch policy: "
                f"live (memory, pids, weight, quota/s, period)={live} policy={policy}"
            )
        return facts

    # --- teardown -----------------------------------------------------------

    async def _stop_exact(
        self,
        launch_identity: _LaunchIdentity,
        launcher: asyncio.subprocess.Process,
        facts: Optional[_ExecutorFacts],
    ) -> None:
        if launcher.returncode is not None:
            return
        name = launch_identity.unit_name
        try:
            info = await self._inspect_container(name)
        except RunExecutionError:
            if launcher.returncode is None:
                launcher.terminate()
                await launcher.wait()
            return
        labels = (info.get("Config") or {}).get("Labels") or {}
        if labels.get("openchia.launch") != launch_identity.description:
            launcher.terminate()
            await launcher.wait()
            raise RunExecutionError(
                "refusing to stop a container with another launch identity"
            )
        if facts is not None and info.get("Id") != facts.invocation_id:
            launcher.terminate()
            await launcher.wait()
            raise RunExecutionError(
                "refusing to stop a container whose identity changed"
            )
        try:
            await _cli_output(self.runtime.cli, "stop", "--time", "2", name)
        finally:
            if launcher.returncode is None:
                try:
                    await asyncio.wait_for(launcher.wait(), timeout=10)
                except asyncio.TimeoutError:
                    launcher.terminate()
                    await launcher.wait()


_RUNTIME_CACHE: dict[tuple[str, str], ContainerRuntime] = {}


def make_container_run_executor_factory(
    *,
    repository_root: str | Path,
    image: str = DEFAULT_CONTAINER_IMAGE,
    cli: str | Path | None = None,
):
    """Build the container host dependency for fresh per-Run executors.

    Nothing touches the container daemon here: the host constructs this
    factory when a Duet session starts, and a design-only session must work
    without Docker running.  The CLI is located, the image pinned by digest and
    its interpreter identity captured on the first explicit Run, then cached
    for the host process; the VM allocation is re-read for every Run so the
    ceilings mirror the runtime as it is, not as it was.
    """
    root = Path(repository_root).expanduser()
    if root.is_symlink():
        raise ValueError("runtime repository cannot be a symlink")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("runtime repository must exist")

    def factory(run_store: RunStore) -> ContainerRunExecutor:
        if not isinstance(run_store, RunStore):
            raise TypeError("run_store must be a RunStore")
        cli_path = find_container_cli(cli)
        key = (str(cli_path), image)
        runtime = _RUNTIME_CACHE.get(key)
        if runtime is None:
            runtime = inspect_container_runtime(repository_root=root, image=image, cli=cli_path)
            _RUNTIME_CACHE[key] = runtime
        return ContainerRunExecutor(
            run_store=run_store,
            repository_root=root,
            resources=runtime.default_resources(),
            runtime=runtime,
        )

    return factory


__all__ = [
    "CONTAINER_START_TIMEOUT_SECONDS",
    "CONTAINER_USER",
    "ContainerRunExecutor",
    "ContainerRuntime",
    "ContainerRuntimeError",
    "DEFAULT_CONTAINER_IMAGE",
    "container_isolation_arguments",
    "CONTAINER_CPU_WEIGHT",
    "container_resource_arguments",
    "find_container_cli",
    "inspect_container_runtime",
    "make_container_run_executor_factory",
]
