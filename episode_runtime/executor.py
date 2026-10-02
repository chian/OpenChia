"""Host executor for one strictly admitted, isolated Episode Run."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import sys
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Protocol, runtime_checkable
from urllib.parse import urlsplit

from agent.episode_contracts import OpaqueId

from .broker import (
    ScopedModelBroker,
    admit_model_request,
    model_request_hash,
    model_response_hash,
    model_response_record,
)
from .audit_contracts import RunEvidence
from .http_broker import ScopedHttpBroker, http_response_bytes
from .http_contracts import http_request_hash, http_response_hash
from .contracts import (
    ExecutorKind,
    RuntimeIdentity,
    expected_executor_unit_name,
    InspectedExecutorAttestation,
    ReadOnlyRuntimeMount,
    RunEventKind,
    RunEventOrigin,
    RunRegistration,
    RunTerminalStatus,
    RuntimeMountKind,
    derive_executor_instance_id,
)
from .protocol import (
    CancelKind,
    FrameDecoder,
    FrameEncoder,
    FrameSender,
    HostFrameType,
    ProtocolBinding,
    ProtocolError,
    ProtocolFrame,
    WorkerFrameType,
    _thaw_json,
    decode_frame,
)
from .store import RunStore, RunStoreConflict
from .identity import load_verified_bootstrap_program, verify_runtime_identity
from .interpreter import current_interpreter_executable


class RunExecutionError(RuntimeError):
    """The exact transient executor or protocol failed."""


@dataclass(frozen=True)
class ExecutorResources:
    """Cgroup allocation facts; none is an Episode stopping rule."""

    memory_max_bytes: Optional[int]
    pids_max: Optional[int]
    cpu_weight: int
    cpu_quota_per_sec_micros: Optional[int]
    cpu_period_micros: int

    def __post_init__(self) -> None:
        for name in ("memory_max_bytes", "pids_max", "cpu_quota_per_sec_micros"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"{name} must be a positive integer or None")
        for name in ("cpu_weight", "cpu_period_micros"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.cpu_weight > 10_000:
            raise ValueError("cpu_weight must be <= 10000")
        if not 1_000 <= self.cpu_period_micros <= 1_000_000:
            raise ValueError("cpu_period_micros must be between 1ms and 1s")

    @classmethod
    def from_host_effective_allocation(
        cls,
        *,
        cgroup_root: str | Path = "/sys/fs/cgroup",
        process_cgroup_path: str | Path = "/proc/self/cgroup",
    ) -> "ExecutorResources":
        """Mirror the host process's effective cgroup-v2 allocation.

        ``None`` is the explicit unbounded value for memory, tasks, or CPU
        quota.  The scan takes the tightest finite ancestor allocation; it
        never invents a task-specific ceiling.
        """

        hierarchy = _host_cgroup_hierarchy(
            cgroup_root=Path(cgroup_root),
            process_cgroup_path=Path(process_cgroup_path),
        )
        quota, period = _effective_cpu_allocation(hierarchy)
        return cls(
            memory_max_bytes=_effective_scalar_limit(hierarchy, "memory.max"),
            pids_max=_effective_scalar_limit(hierarchy, "pids.max"),
            cpu_weight=_read_positive_control(
                hierarchy[0] / "cpu.weight",
                "host cpu.weight",
            ),
            cpu_quota_per_sec_micros=quota,
            cpu_period_micros=period,
        )


@dataclass(frozen=True)
class _ExecutorFacts:
    executor_kind: ExecutorKind
    unit_name: str
    invocation_id: str
    launch_description: str
    boot_id: str
    leader_pid: int
    leader_start_time_ticks: int
    cgroup_path: str
    read_only_runtime_mounts: tuple[ReadOnlyRuntimeMount, ...]
    memory_max_bytes: Optional[int]
    pids_max: Optional[int]
    cpu_weight: int
    cpu_quota_micros: Optional[int]
    cpu_period_micros: int
    filesystem_namespace_isolated: bool
    process_namespace_isolated: bool
    network_namespace_isolated: bool
    host_runtime_read_only: bool
    no_new_privs: bool

    @property
    def executor_instance_id(self) -> OpaqueId:
        return derive_executor_instance_id(
            executor_kind=self.executor_kind,
            unit_name=self.unit_name,
            invocation_id=self.invocation_id,
            boot_id=self.boot_id,
            leader_pid=self.leader_pid,
            leader_start_time_ticks=self.leader_start_time_ticks,
            cgroup_path=self.cgroup_path,
        )


@dataclass(frozen=True)
class _LaunchIdentity:
    unit_name: str
    description: str


WORKER_STDERR_TAIL_BYTES = 4096


async def _drain_stderr(stream: asyncio.StreamReader) -> bytes:
    """Consume the worker's stderr so it can never block, keeping only a tail."""
    tail = b""
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return tail
        tail = (tail + chunk)[-WORKER_STDERR_TAIL_BYTES:]


async def _attach_worker_stderr(
    exc: Optional[BaseException], stderr_tail: Optional["asyncio.Task[bytes]"]
) -> None:
    """Note the worker's last stderr bytes on the host-side failure.

    The note is host diagnostics only: it reaches the operator through the
    raised exception, never the evidence chain, and a worker that wrote nothing
    leaves the exception untouched.
    """
    if stderr_tail is None:
        return
    try:
        tail = await asyncio.wait_for(stderr_tail, 5.0)
    except BaseException:
        stderr_tail.cancel()
        return
    text = " ".join(tail.decode("utf-8", errors="replace").replace("\x00", " ").split())
    if exc is not None and text:
        exc.add_note(f"worker stderr: {text}")


class _HostChannel:
    def __init__(
        self,
        *,
        binding: ProtocolBinding,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.binding = binding
        self.reader = reader
        self.writer = writer
        self.decoder = FrameDecoder(sender=FrameSender.WORKER, binding=binding)
        self.encoder = FrameEncoder(sender=FrameSender.HOST, binding=binding)
        self._sent_sequence = 0

    @property
    def next_sender_sequence(self) -> int:
        return self._sent_sequence

    async def send(
        self,
        frame_type: str,
        body: Mapping[str, object],
    ) -> ProtocolFrame:
        expected = self._sent_sequence
        packet = self.encoder.encode(frame_type, body)
        frame = decode_frame(
            packet,
            sender=FrameSender.HOST,
            binding=self.binding,
            expected_sequence=expected,
        )
        self._sent_sequence += 1
        self.writer.write(packet)
        await self.writer.drain()
        return frame

    async def receive(self) -> ProtocolFrame:
        try:
            prefix = await self.reader.readexactly(4)
            length = int.from_bytes(prefix, "big")
            if length < 1 or length > self.binding.max_frame_bytes:
                raise ProtocolError("frame length is outside its admitted bound")
            payload = await self.reader.readexactly(length)
        except asyncio.IncompleteReadError as exc:
            raise ProtocolError("worker protocol stream ended inside a frame") from exc
        return self.decoder.decode(prefix + payload)


def _read_small_control(path: Path, name: str) -> str:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise RunExecutionError(f"cannot read {name}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise RunExecutionError(f"{name} is not a regular control file")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, 4096)
            if not chunk:
                break
            size += len(chunk)
            if size > 16_384:
                raise RunExecutionError(f"{name} exceeds its control-file bound")
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    try:
        value = b"".join(chunks).decode("ascii", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise RunExecutionError(f"{name} is not ASCII") from exc
    if not value or "\x00" in value:
        raise RunExecutionError(f"{name} is empty or malformed")
    return value


def _host_cgroup_hierarchy(
    *,
    cgroup_root: Path,
    process_cgroup_path: Path,
) -> tuple[Path, ...]:
    root = cgroup_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise RunExecutionError("cgroup_root must be a directory")
    record = _read_small_control(process_cgroup_path, "host process cgroup")
    unified = tuple(
        line[3:]
        for line in record.splitlines()
        if line.startswith("0::/")
    )
    if len(unified) != 1:
        raise RunExecutionError("host process does not have one cgroup-v2 path")
    relative = PurePosixPath(unified[0]).relative_to("/")
    leaf = root.joinpath(*relative.parts).resolve(strict=True)
    if leaf != root and root not in leaf.parents:
        raise RunExecutionError("host cgroup escapes the supplied cgroup root")
    hierarchy: list[Path] = []
    current = leaf
    while True:
        hierarchy.append(current)
        if current == root:
            break
        current = current.parent
    return tuple(hierarchy)


def _parse_positive_control(value: str, name: str) -> int:
    try:
        result = int(value, 10)
    except ValueError as exc:
        raise RunExecutionError(f"{name} is not an integer") from exc
    if result < 1:
        raise RunExecutionError(f"{name} must be positive")
    return result


def _read_positive_control(path: Path, name: str) -> int:
    return _parse_positive_control(_read_small_control(path, name), name)


def _effective_scalar_limit(
    hierarchy: tuple[Path, ...],
    filename: str,
) -> Optional[int]:
    limits: list[int] = []
    for directory in hierarchy:
        value = _read_small_control(directory / filename, f"host {filename}")
        if value != "max":
            limits.append(_parse_positive_control(value, f"host {filename}"))
    return min(limits) if limits else None


def _effective_cpu_allocation(
    hierarchy: tuple[Path, ...],
) -> tuple[Optional[int], int]:
    finite: list[tuple[Fraction, int]] = []
    leaf_period: Optional[int] = None
    for index, directory in enumerate(hierarchy):
        fields = _read_small_control(
            directory / "cpu.max",
            "host cpu.max",
        ).split()
        if len(fields) != 2:
            raise RunExecutionError("host cpu.max must contain quota and period")
        period = _parse_positive_control(fields[1], "host cpu.max period")
        if not 1_000 <= period <= 1_000_000:
            raise RunExecutionError("host cpu.max period is outside kernel bounds")
        if index == 0:
            leaf_period = period
        if fields[0] != "max":
            quota = _parse_positive_control(fields[0], "host cpu.max quota")
            finite.append((Fraction(quota, period), period))
    if leaf_period is None:
        raise AssertionError("cgroup hierarchy cannot be empty")
    if not finite:
        return None, leaf_period
    ratio, period = min(finite, key=lambda item: item[0])
    per_second = ratio * 1_000_000
    if per_second.denominator != 1:
        raise RunExecutionError(
            "effective host CPU quota is not exactly expressible in microseconds per second"
        )
    return int(per_second), period


def _launch_identity(
    run_id: OpaqueId,
    executor_kind: ExecutorKind = ExecutorKind.SYSTEMD,
) -> _LaunchIdentity:
    nonce = secrets.token_hex(16)
    return _LaunchIdentity(
        unit_name=expected_executor_unit_name(executor_kind, run_id, nonce),
        description=f"openchia-episode-launch:{run_id.value}:{nonce}",
    )


def _cpu_quota_percent(resources: ExecutorResources) -> str:
    if resources.cpu_quota_per_sec_micros is None:
        return "infinity"
    percent = Decimal(resources.cpu_quota_per_sec_micros) / Decimal(10_000)
    return f"{format(percent.normalize(), 'f')}%"


def _systemd_limit(value: Optional[int]) -> str:
    return "infinity" if value is None else str(value)


def _hidden_by_protect_home(path: Path) -> bool:
    protected = (Path("/home"), Path("/root"), Path("/run/user"))
    return any(path == root or root in path.parents for root in protected)


def _systemd_properties(
    resources: ExecutorResources,
    mounts: tuple[ReadOnlyRuntimeMount, ...],
) -> tuple[str, ...]:
    bind_specification = " ".join(
        f"{mount.source_path}:{mount.target_path}" for mount in mounts
    )
    return (
        "Type=exec",
        "Restart=no",
        f"MemoryMax={_systemd_limit(resources.memory_max_bytes)}",
        f"TasksMax={_systemd_limit(resources.pids_max)}",
        f"CPUWeight={resources.cpu_weight}",
        f"CPUQuota={_cpu_quota_percent(resources)}",
        f"CPUQuotaPeriodSec={resources.cpu_period_micros}us",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "PrivateTmp=yes",
        f"BindReadOnlyPaths={bind_specification}",
        "PrivateDevices=yes",
        "PrivateNetwork=yes",
        "PrivatePIDs=yes",
        "ProtectProc=invisible",
        "ProcSubset=pid",
        "NoNewPrivileges=yes",
        "RestrictSUIDSGID=yes",
        "LockPersonality=yes",
        "ProtectClock=yes",
        "ProtectKernelTunables=yes",
        "ProtectKernelModules=yes",
        "ProtectKernelLogs=yes",
        "ProtectControlGroups=yes",
        "RestrictAddressFamilies=AF_UNIX",
    )


async def _command_output(*arguments: str) -> str:
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        raise RunExecutionError(f"command {arguments[0]!r} failed")
    try:
        return stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RunExecutionError("systemd inspection returned non-UTF-8 data") from exc


_SHOW_PROPERTIES = (
    "ActiveState",
    "SubState",
    "MainPID",
    "ControlGroup",
    "MemoryMax",
    "TasksMax",
    "CPUWeight",
    "CPUQuotaPerSecUSec",
    "CPUQuotaPeriodUSec",
    "ProtectSystem",
    "ProtectHome",
    "PrivateTmp",
    "PrivateNetwork",
    "PrivatePIDs",
    "ProtectProc",
    "ProcSubset",
    "NoNewPrivileges",
    "Description",
    "InvocationID",
)


async def _show_unit(systemctl: Path, unit_name: str) -> Mapping[str, str]:
    output = await _command_output(
        str(systemctl),
        "--user",
        "show",
        "--no-pager",
        "--property=" + ",".join(_SHOW_PROPERTIES),
        unit_name,
    )
    values: dict[str, str] = {}
    for line in output.splitlines():
        name, separator, value = line.partition("=")
        if not separator or name not in _SHOW_PROPERTIES or name in values:
            raise RunExecutionError("systemd inspection fields are malformed")
        values[name] = value
    if set(values) != set(_SHOW_PROPERTIES):
        raise RunExecutionError("systemd inspection omitted required properties")
    return MappingProxyType(values)


def _positive_integer(value: str, name: str) -> int:
    try:
        result = int(value, 10)
    except ValueError as exc:
        raise RunExecutionError(f"systemd {name} is not numeric") from exc
    if result < 1:
        raise RunExecutionError(f"systemd {name} must be positive")
    return result


def _optional_positive_integer(value: str, name: str) -> Optional[int]:
    if value == "infinity":
        return None
    return _positive_integer(value, name)


def _positive_microseconds(value: str, name: str) -> int:
    try:
        return _positive_integer(value, name)
    except RunExecutionError:
        pass
    units = {
        "us": Decimal(1),
        "ms": Decimal(1_000),
        "s": Decimal(1_000_000),
        "min": Decimal(60_000_000),
    }
    for suffix, multiplier in units.items():
        if not value.endswith(suffix):
            continue
        number = value[: -len(suffix)].strip()
        try:
            micros = Decimal(number) * multiplier
        except Exception as exc:
            raise RunExecutionError(f"systemd {name} is not a time span") from exc
        if micros != micros.to_integral_value() or micros < 1:
            raise RunExecutionError(f"systemd {name} is not whole microseconds")
        return int(micros)
    raise RunExecutionError(f"systemd {name} is not a supported time span")


def _decode_mountinfo_path(value: str) -> str:
    replacements = {
        "\\040": " ",
        "\\011": "\t",
        "\\012": "\n",
        "\\134": "\\",
    }
    decoded = value
    for escaped, character in replacements.items():
        decoded = decoded.replace(escaped, character)
    if "\\" in decoded:
        raise RunExecutionError("mountinfo contains an unsupported path escape")
    return decoded


def _read_mountinfo(pid: int) -> tuple[tuple[str, frozenset[str]], ...]:
    try:
        lines = Path(f"/proc/{pid}/mountinfo").read_text(
            encoding="utf-8",
            errors="strict",
        ).splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise RunExecutionError("cannot inspect executor mount namespace") from exc
    mounts: list[tuple[str, frozenset[str]]] = []
    for line in lines:
        fields = line.split()
        if len(fields) < 10 or "-" not in fields[6:]:
            raise RunExecutionError("executor mountinfo record is malformed")
        mount_path = _decode_mountinfo_path(fields[4])
        if not mount_path.startswith("/") or str(PurePosixPath(mount_path)) != mount_path:
            raise RunExecutionError("executor mountinfo path is not normalized")
        mounts.append((mount_path, frozenset(fields[5].split(","))))
    return tuple(mounts)


def _same_mounted_object(pid: int, mount: ReadOnlyRuntimeMount) -> bool:
    projected = Path(f"/proc/{pid}/root").joinpath(
        *PurePosixPath(mount.target_path).relative_to("/").parts
    )
    try:
        source = os.stat(mount.source_path, follow_symlinks=False)
        target = os.stat(projected, follow_symlinks=False)
    except OSError as exc:
        raise RunExecutionError("cannot compare a projected runtime input") from exc
    return (
        source.st_dev == target.st_dev
        and source.st_ino == target.st_ino
        and stat.S_IFMT(source.st_mode) == stat.S_IFMT(target.st_mode)
    )


def _verify_read_only_runtime_mounts(
    pid: int,
    expected: tuple[ReadOnlyRuntimeMount, ...],
) -> tuple[ReadOnlyRuntimeMount, ...]:
    mountinfo = _read_mountinfo(pid)
    for mount in expected:
        exact = tuple(
            options for path, options in mountinfo if path == mount.target_path
        )
        if len(exact) != 1 or "ro" not in exact[0]:
            raise RunExecutionError(
                f"runtime input {mount.kind.value!r} is not one exact read-only mount"
            )
        prefix = mount.target_path + "/"
        if any(
            "ro" not in options
            for path, options in mountinfo
            if path.startswith(prefix)
        ):
            raise RunExecutionError(
                f"runtime input {mount.kind.value!r} contains a writable submount"
            )
        if not _same_mounted_object(pid, mount):
            raise RunExecutionError(
                f"runtime input {mount.kind.value!r} projects another host object"
            )
    return expected


def _proc_start_time(pid: int) -> int:
    try:
        line = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RunExecutionError("cannot inspect executor process start time") from exc
    close = line.rfind(")")
    if close < 1:
        raise RunExecutionError("executor /proc stat record is malformed")
    fields = line[close + 2 :].split()
    if len(fields) <= 19:
        raise RunExecutionError("executor /proc stat record is incomplete")
    return _positive_integer(fields[19], "process start time")


def _proc_cgroup(pid: int) -> str:
    try:
        lines = Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise RunExecutionError("cannot inspect executor cgroup") from exc
    unified = tuple(line[3:] for line in lines if line.startswith("0::/"))
    if len(unified) != 1:
        raise RunExecutionError("executor does not have one unified cgroup")
    value = unified[0]
    if str(PurePosixPath(value)) != value:
        raise RunExecutionError("executor cgroup path is not normalized")
    return value


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="ascii"
        ).strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise RunExecutionError("cannot inspect kernel boot identity") from exc


async def _inspect_executor(
    *,
    systemctl: Path,
    launch_identity: _LaunchIdentity,
    launcher: asyncio.subprocess.Process,
    resources: ExecutorResources,
    read_only_runtime_mounts: tuple[ReadOnlyRuntimeMount, ...],
) -> _ExecutorFacts:
    while True:
        if launcher.returncode is not None:
            raise RunExecutionError("transient service exited before inspection")
        try:
            values = await _show_unit(systemctl, launch_identity.unit_name)
        except RunExecutionError:
            await asyncio.sleep(0.05)
            continue
        if values["ActiveState"] == "active" and values["SubState"] == "running":
            break
        if values["ActiveState"] in {"failed", "inactive", "deactivating"}:
            raise RunExecutionError("transient service did not reach running state")
        await asyncio.sleep(0.05)

    pid = _positive_integer(values["MainPID"], "MainPID")
    cgroup = values["ControlGroup"]
    if (
        not cgroup.startswith("/")
        or PurePosixPath(cgroup).name != launch_identity.unit_name
        or _proc_cgroup(pid) != cgroup
        or values["Description"] != launch_identity.description
        or len(values["InvocationID"]) != 32
        or any(character not in "0123456789abcdef" for character in values["InvocationID"])
    ):
        raise RunExecutionError("systemd and /proc cgroup identities disagree")
    inspected_mounts = _verify_read_only_runtime_mounts(
        pid,
        read_only_runtime_mounts,
    )
    facts = _ExecutorFacts(
        executor_kind=ExecutorKind.SYSTEMD,
        unit_name=launch_identity.unit_name,
        invocation_id=values["InvocationID"],
        launch_description=launch_identity.description,
        boot_id=_boot_id(),
        leader_pid=pid,
        leader_start_time_ticks=_proc_start_time(pid),
        cgroup_path=cgroup,
        read_only_runtime_mounts=inspected_mounts,
        memory_max_bytes=_optional_positive_integer(
            values["MemoryMax"],
            "MemoryMax",
        ),
        pids_max=_optional_positive_integer(values["TasksMax"], "TasksMax"),
        cpu_weight=_positive_integer(values["CPUWeight"], "CPUWeight"),
        cpu_quota_micros=(
            None
            if values["CPUQuotaPerSecUSec"] == "infinity"
            else _positive_microseconds(
                values["CPUQuotaPerSecUSec"],
                "CPUQuotaPerSecUSec",
            )
        ),
        cpu_period_micros=_positive_microseconds(
            values["CPUQuotaPeriodUSec"],
            "CPUQuotaPeriodUSec",
        ),
        filesystem_namespace_isolated=(
            values["ProtectSystem"] == "strict"
            and values["ProtectHome"] == "yes"
            and values["PrivateTmp"] == "yes"
            and inspected_mounts == read_only_runtime_mounts
        ),
        process_namespace_isolated=(
            values["PrivatePIDs"] == "yes"
            and values["ProtectProc"] == "invisible"
            and values["ProcSubset"] == "pid"
        ),
        network_namespace_isolated=values["PrivateNetwork"] == "yes",
        host_runtime_read_only=(
            values["ProtectSystem"] == "strict"
            and inspected_mounts == read_only_runtime_mounts
        ),
        no_new_privs=values["NoNewPrivileges"] == "yes",
    )
    if (
        facts.memory_max_bytes != resources.memory_max_bytes
        or facts.pids_max != resources.pids_max
        or facts.cpu_weight != resources.cpu_weight
        or facts.cpu_quota_micros != resources.cpu_quota_per_sec_micros
        or facts.cpu_period_micros != resources.cpu_period_micros
    ):
        raise RunExecutionError("live cgroup allocation differs from launch policy")
    return facts


@runtime_checkable
class RunExecutor(Protocol):
    """What the OpenChia host needs from any Run executor."""

    run_store: RunStore
    repository_root: Path
    python_executable: Path | PurePosixPath

    def inspect_runtime_identity(
        self,
        *,
        destination_root: str | Path,
    ) -> RuntimeIdentity: ...

    async def execute(
        self,
        *,
        registration: RunRegistration,
        source_package_path: str | Path,
        model_broker: ScopedModelBroker,
        http_broker: ScopedHttpBroker,
    ) -> RunEvidence: ...


class _RunExecutorBase:
    """The Run protocol, independent of how the leader process is launched.

    Subclasses provide the launch mechanism and its inspection: a transient
    systemd service on a Linux host, or an OCI container.  Everything from the
    identity checks through the event chain, cancellation and finalization is
    shared, so the two executors cannot drift apart in what they persist.
    """

    run_store: RunStore
    repository_root: Path

    def _identity_arguments(self) -> dict[str, Any]:
        """Keyword arguments naming the worker interpreter for identity checks."""
        raise NotImplementedError

    def _launch_identity(self, run_id: OpaqueId) -> _LaunchIdentity:
        raise NotImplementedError

    def _runtime_mounts(
        self,
        registration: RunRegistration,
        runtime_source_package: Path,
        source_package: Path,
    ) -> tuple[ReadOnlyRuntimeMount, ...]:
        raise NotImplementedError

    async def _launch(
        self,
        registration: RunRegistration,
        launch_identity: _LaunchIdentity,
        mounts: tuple[ReadOnlyRuntimeMount, ...],
        bootstrap_program: str,
    ) -> asyncio.subprocess.Process:
        """Start the leader with its stdin/stdout as the protocol pipes."""
        raise NotImplementedError

    async def _inspect(
        self,
        launch_identity: _LaunchIdentity,
        launcher: asyncio.subprocess.Process,
        mounts: tuple[ReadOnlyRuntimeMount, ...],
    ) -> _ExecutorFacts:
        raise NotImplementedError

    async def _stop_exact(
        self,
        launch_identity: _LaunchIdentity,
        launcher: asyncio.subprocess.Process,
        facts: Optional[_ExecutorFacts],
    ) -> None:
        raise NotImplementedError

    async def _broker_http_request(
        self,
        *,
        registration: RunRegistration,
        channel: _HostChannel,
        frame: ProtocolFrame,
        http_broker: ScopedHttpBroker,
    ) -> None:
        """Broker one admitted HTTP request and record both evidence events.

        The decoder already admitted the request and verified that
        ``episode_path`` hashes to ``episode_id``; the path's leaf grain names
        the node whose approved rules apply.  Policy outcomes come back as
        response records; only a malformed request raises.
        """

        body = frame.body
        local_id = body["episode_path"][-1]["grain"]
        request = body["request"]
        request_hash = http_request_hash(request)
        episode_id = OpaqueId(body["episode_id"])
        matched = http_broker.match_rule(local_id, request)
        rule_name = None if matched is None else matched.name
        url = urlsplit(str(request["url"]))
        self.run_store.append_event(
            run_id=registration.run_id,
            origin=RunEventOrigin.WORKER,
            sender_sequence=frame.sender_sequence,
            kind=RunEventKind.HTTP_REQUESTED,
            episode_id=episode_id,
            payload={
                "http_request_id": body["http_request_id"],
                "request_hash": request_hash.value,
                "rule": rule_name,
                "method": request["method"],
                "host": url.hostname,
                "path": url.path,
            },
        )
        response = await http_broker(local_id=local_id, request=request)
        response_frame = await channel.send(
            HostFrameType.HTTP_RESPONSE.value,
            {
                "http_request_id": body["http_request_id"],
                "response": response,
            },
        )
        self.run_store.append_event(
            run_id=registration.run_id,
            origin=RunEventOrigin.HOST,
            sender_sequence=response_frame.sender_sequence,
            kind=RunEventKind.HTTP_RESPONDED,
            episode_id=episode_id,
            payload={
                "http_request_id": body["http_request_id"],
                "request_hash": request_hash.value,
                "response_hash": http_response_hash(response).value,
                "outcome": response["outcome"],
                "status": response["status"],
                "response_bytes": http_response_bytes(response),
                "rule": response["rule"],
            },
        )

    async def execute(
        self,
        *,
        registration: RunRegistration,
        source_package_path: str | Path,
        model_broker: ScopedModelBroker,
        http_broker: ScopedHttpBroker,
    ) -> RunEvidence:
        """Execute one fresh registration; cancellation persists cancellation."""

        if not isinstance(registration, RunRegistration):
            raise TypeError("registration must be a RunRegistration")
        if not isinstance(model_broker, ScopedModelBroker):
            raise TypeError("model_broker must be a ScopedModelBroker")
        if not isinstance(http_broker, ScopedHttpBroker):
            raise TypeError("http_broker must be a ScopedHttpBroker")
        runtime_source_package = (
            self.run_store.runtime_sources_root
            / registration.runtime_identity.runtime_source_manifest_id.value
        )
        verify_runtime_identity(
            registration.runtime_identity,
            runtime_source_package=runtime_source_package,
            **self._identity_arguments(),
        )
        bootstrap_program = load_verified_bootstrap_program(
            registration.runtime_identity,
            runtime_source_package,
            **self._identity_arguments(),
        )
        supplied_source_package = Path(source_package_path).expanduser()
        if supplied_source_package.is_symlink():
            raise ValueError("source_package_path cannot be a symlink")
        source_package = supplied_source_package.resolve(strict=True)
        if (
            source_package.is_symlink()
            or not source_package.is_dir()
            or source_package.name != registration.manifest_id.value
        ):
            raise ValueError("source_package_path must name the exact manifest package")
        from .learning_broker import LearningBroker
        # Package rejection must precede publication: an unclaimed registration
        # has no event channel through which it could be finalized.
        learning_broker = await asyncio.to_thread(
            LearningBroker, self.run_store, registration, source_package
        )
        self.run_store.publish_registration(registration)

        launch_identity = self._launch_identity(registration.run_id)
        mounts = self._runtime_mounts(
            registration,
            runtime_source_package,
            source_package,
        )
        launcher: Optional[asyncio.subprocess.Process] = None
        stderr_tail: Optional[asyncio.Task[bytes]] = None
        channel: Optional[_HostChannel] = None
        facts: Optional[_ExecutorFacts] = None
        claimed = False
        evidence: Optional[RunEvidence] = None
        try:
            launcher = await self._launch(
                registration,
                launch_identity,
                mounts,
                bootstrap_program,
            )
            if launcher.stdin is None or launcher.stdout is None:
                raise RunExecutionError(
                    "the Run launcher did not provide protocol pipes"
                )
            if launcher.stderr is not None:
                stderr_tail = asyncio.create_task(_drain_stderr(launcher.stderr))
            channel = _HostChannel(
                binding=ProtocolBinding.from_registration(registration),
                reader=launcher.stdout,
                writer=launcher.stdin,
            )
            facts = await self._inspect(launch_identity, launcher, mounts)
            await channel.send(
                HostFrameType.INITIALIZE.value,
                {
                    "registration": registration.as_record(),
                    "executor_instance_id": facts.executor_instance_id.value,
                },
            )
            ready = await channel.receive()
            if ready.frame_type != WorkerFrameType.READY.value:
                raise ProtocolError("initialize must be followed by ready")
            if (
                ready.body["runtime_id"]
                != registration.runtime_identity.runtime_id.value
                or ready.body["runtime_hash"]
                != registration.runtime_identity.content_hash.value
            ):
                raise ProtocolError("worker ready frame names another runtime")
            from .landlock import LandlockPolicyReceipt
            from .seccomp import SeccompPolicyReceipt

            receipt = LandlockPolicyReceipt.from_record(
                ready.body["landlock_receipt"]
            )
            seccomp_receipt = SeccompPolicyReceipt.from_record(
                ready.body["seccomp_receipt"]
            )
            if (
                receipt.executor_instance_id != facts.executor_instance_id
                or seccomp_receipt.executor_instance_id
                != facts.executor_instance_id
            ):
                raise ProtocolError("isolation receipt names another executor")
            attestation = InspectedExecutorAttestation(
                run_id=registration.run_id,
                registration_hash=registration.registration_hash,
                manifest_id=registration.manifest_id,
                executor_instance_id=facts.executor_instance_id,
                runtime_id=registration.runtime_identity.runtime_id,
                runtime_hash=registration.runtime_identity.content_hash,
                runtime_policy_id=registration.runtime_policy.policy_id,
                runtime_policy_hash=registration.runtime_policy.content_hash,
                landlock_receipt=receipt,
                seccomp_receipt=seccomp_receipt,
                executor_kind=facts.executor_kind,
                executor_unit_name=facts.unit_name,
                executor_invocation_id=facts.invocation_id,
                launch_description=facts.launch_description,
                boot_id=facts.boot_id,
                leader_pid=facts.leader_pid,
                leader_start_time_ticks=facts.leader_start_time_ticks,
                cgroup_path=facts.cgroup_path,
                read_only_runtime_mounts=facts.read_only_runtime_mounts,
                memory_max_bytes=facts.memory_max_bytes,
                pids_max=facts.pids_max,
                cpu_weight=facts.cpu_weight,
                cpu_quota_micros=facts.cpu_quota_micros,
                cpu_period_micros=facts.cpu_period_micros,
                filesystem_namespace_isolated=facts.filesystem_namespace_isolated,
                process_namespace_isolated=facts.process_namespace_isolated,
                network_namespace_isolated=facts.network_namespace_isolated,
                host_runtime_read_only=facts.host_runtime_read_only,
                no_new_privs=facts.no_new_privs,
            )
            attestation.validate_against(registration)
            self.run_store.claim_run(attestation)
            claimed = True
            self.run_store.append_event(
                run_id=registration.run_id,
                origin=RunEventOrigin.WORKER,
                sender_sequence=ready.sender_sequence,
                kind=RunEventKind.RUNTIME_READY,
                episode_id=None,
                payload={
                    "runtime_id": registration.runtime_identity.runtime_id.value,
                    "runtime_hash": registration.runtime_identity.content_hash.value,
                    "landlock_receipt_id": receipt.receipt_id.value,
                    "landlock_receipt_hash": receipt.content_hash.value,
                    "seccomp_receipt_id": seccomp_receipt.receipt_id.value,
                    "seccomp_receipt_hash": seccomp_receipt.content_hash.value,
                },
            )
            start = await channel.send(
                HostFrameType.START.value,
                {"executor_attestation": attestation.as_record()},
            )
            self.run_store.append_event(
                run_id=registration.run_id,
                origin=RunEventOrigin.HOST,
                sender_sequence=start.sender_sequence,
                kind=RunEventKind.RUN_STARTED,
                episode_id=None,
                payload={"attestation_id": attestation.attestation_id.value},
            )

            worker_event_kinds = {
                RunEventKind.EPISODE_STARTED,
                RunEventKind.UNIT_COMPLETED,
                RunEventKind.EPISODE_COMPLETED,
            }
            while True:
                frame = await channel.receive()
                if frame.frame_type == WorkerFrameType.LEARNING_REQUEST.value:
                    response = await learning_broker(frame.body["episode_id"], frame.body["operation"], frame.body["payload"])
                    await channel.send(HostFrameType.LEARNING_RESPONSE.value,
                                       {"request_id": frame.body["request_id"], "response": response})
                    continue
                if frame.frame_type == WorkerFrameType.MODEL_REQUEST.value:
                    # Frame bodies are frozen (lists become tuples) for hashing;
                    # the broker contract is plain JSON, so thaw the record once
                    # here, exactly as INITIALIZE and START thaw theirs.
                    request_record = _thaw_json(frame.body["request"])
                    request = admit_model_request(request_record)
                    request_hash = model_request_hash(request)
                    episode_id = OpaqueId(frame.body["episode_id"])
                    self.run_store.append_event(
                        run_id=registration.run_id,
                        origin=RunEventOrigin.WORKER,
                        sender_sequence=frame.sender_sequence,
                        kind=RunEventKind.MODEL_REQUESTED,
                        episode_id=episode_id,
                        payload={
                            "model_request_id": frame.body["model_request_id"],
                            "request_hash": request_hash.value,
                            "task": request.task,
                        },
                    )
                    response = await model_broker(request_record)
                    from function_library.epistemic_schemas import model_call_id
                    response_frame = await channel.send(
                        HostFrameType.MODEL_RESPONSE.value,
                        {
                            "model_request_id": frame.body["model_request_id"],
                            "response": model_response_record(response),
                        },
                    )
                    self.run_store.append_event(
                        run_id=registration.run_id,
                        origin=RunEventOrigin.HOST,
                        sender_sequence=response_frame.sender_sequence,
                        kind=RunEventKind.MODEL_RESPONDED,
                        episode_id=episode_id,
                        payload={
                            "model_request_id": frame.body["model_request_id"],
                            "request_hash": request_hash.value,
                            "response_hash": model_response_hash(response).value,
                            "producer_call_id": model_call_id(response.text, request.task, response.route),
                            "response_text": response.text,
                            "route": dict(response.route),
                        },
                    )
                    continue
                if frame.frame_type == WorkerFrameType.HTTP_REQUEST.value:
                    await self._broker_http_request(
                        registration=registration,
                        channel=channel,
                        frame=frame,
                        http_broker=http_broker,
                    )
                    continue
                if frame.frame_type == WorkerFrameType.RUN_EVENT.value:
                    kind = RunEventKind(frame.body["event_kind"])
                    if kind not in worker_event_kinds:
                        raise ProtocolError("worker emitted a host-owned event kind")
                    self.run_store.append_event(
                        run_id=registration.run_id,
                        origin=RunEventOrigin.WORKER,
                        sender_sequence=frame.sender_sequence,
                        kind=kind,
                        episode_id=(
                            None
                            if frame.body["episode_id"] is None
                            else OpaqueId(frame.body["episode_id"])
                        ),
                        payload=frame.body["payload"],
                    )
                    continue
                if frame.frame_type != WorkerFrameType.TERMINAL.value:
                    raise ProtocolError("worker sent an invalid post-start frame")
                if frame.body["terminal_status"] == RunTerminalStatus.SUCCEEDED.value:
                    await asyncio.to_thread(
                        learning_broker.validate_completion, frame.body["typed_status"]
                    )
                terminal_status = RunTerminalStatus(frame.body["terminal_status"])
                evidence = self.run_store.finalize_run(
                    run_id=registration.run_id,
                    origin=RunEventOrigin.WORKER,
                    sender_sequence=frame.sender_sequence,
                    terminal_status=terminal_status,
                    typed_status=frame.body["typed_status"],
                )
                await channel.send(
                    HostFrameType.TERMINAL_ACK.value,
                    {
                        "evidence_id": evidence.evidence_id.value,
                        "evidence_hash": evidence.content_hash.value,
                    },
                )
                channel.writer.close()
                await channel.writer.wait_closed()
                await launcher.wait()
                return evidence
        except asyncio.CancelledError:
            if claimed and evidence is None:
                try:
                    cancel = await channel.send(
                        HostFrameType.CANCEL.value,
                        {"cancel_kind": CancelKind.HUMAN_CANCELLED.value},
                    )
                    sender_sequence = cancel.sender_sequence
                except BaseException:
                    sender_sequence = channel.next_sender_sequence
                try:
                    evidence = self.run_store.finalize_run(
                        run_id=registration.run_id,
                        origin=RunEventOrigin.HOST,
                        sender_sequence=sender_sequence,
                        terminal_status=RunTerminalStatus.CANCELLED,
                        typed_status={
                            "outcome": "cancelled",
                            "cancel_kind": CancelKind.HUMAN_CANCELLED.value,
                        },
                    )
                except RunStoreConflict:
                    pass
            raise
        except BaseException as exc:
            if claimed and evidence is None:
                try:
                    cancel = await channel.send(
                        HostFrameType.CANCEL.value,
                        {"cancel_kind": CancelKind.PROTOCOL_VIOLATION.value},
                    )
                    sender_sequence = cancel.sender_sequence
                except BaseException:
                    sender_sequence = channel.next_sender_sequence
                failure = " ".join(str(exc).replace("\x00", " ").split())[:2048]
                status = RunTerminalStatus.FAILED
                if isinstance(exc.__cause__, asyncio.IncompleteReadError):
                    status = RunTerminalStatus.INTERRUPTED
                elif isinstance(exc, (ProtocolError, ValueError)):
                    status = RunTerminalStatus.INVALID
                elif isinstance(exc, MemoryError):
                    status = RunTerminalStatus.RESOURCE_LIMITED
                try:
                    evidence = self.run_store.finalize_run(
                        run_id=registration.run_id,
                        origin=RunEventOrigin.HOST,
                        sender_sequence=sender_sequence,
                        terminal_status=status,
                        typed_status={
                            "outcome": status.value,
                            "failure_type": type(exc).__name__,
                            "failure": failure or "host executor failure",
                        },
                    )
                except RunStoreConflict:
                    pass
            raise
        finally:
            if launcher is not None and launcher.returncode is None:
                await self._stop_exact(launch_identity, launcher, facts)
            await _attach_worker_stderr(sys.exception(), stderr_tail)



@dataclass
class SystemdRunExecutor(_RunExecutorBase):
    """Launch, attest, broker, persist, and tear down one Run exactly once."""

    run_store: RunStore
    repository_root: Path
    resources: ExecutorResources
    python_executable: Path = field(default_factory=current_interpreter_executable)
    python_runtime_root: Optional[Path] = None
    systemd_run: Path = Path("/usr/bin/systemd-run")
    systemctl: Path = Path("/usr/bin/systemctl")
    env_executable: Path = Path("/usr/bin/env")
    _python_executable_relative: Optional[Path] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.run_store, RunStore):
            raise TypeError("run_store must be a RunStore")
        if not isinstance(self.resources, ExecutorResources):
            raise TypeError("resources must be ExecutorResources")
        original_paths = {
            name: Path(getattr(self, name)).expanduser()
            for name in (
                "repository_root",
                "python_executable",
                "systemd_run",
                "systemctl",
                "env_executable",
            )
        }
        original_python_runtime_root = (
            None
            if self.python_runtime_root is None
            else Path(self.python_runtime_root).expanduser()
        )
        if any(
            original_paths[name].is_symlink()
            for name in ("repository_root",)
        ):
            raise ValueError(
                "repository_root cannot be a symlink"
            )
        for name in (
            "repository_root",
            "python_executable",
            "systemd_run",
            "systemctl",
            "env_executable",
        ):
            path = original_paths[name].resolve(strict=True)
            object.__setattr__(self, name, path)
        if original_python_runtime_root is not None:
            if original_python_runtime_root.is_symlink():
                raise ValueError("python_runtime_root cannot be a symlink")
            python_runtime_root = original_python_runtime_root.resolve(strict=True)
            if not python_runtime_root.is_dir():
                raise ValueError("python_runtime_root must be a directory")
            object.__setattr__(self, "python_runtime_root", python_runtime_root)
        if not self.repository_root.is_dir():
            raise ValueError("repository_root must be a directory")
        if _hidden_by_protect_home(self.env_executable):
            raise ValueError("env_executable must remain readable with ProtectHome=yes")
        if _hidden_by_protect_home(self.python_executable):
            if self.python_runtime_root is None:
                raise ValueError(
                    "a protected-home Python requires python_runtime_root"
                )
            try:
                python_relative = self.python_executable.relative_to(
                    self.python_runtime_root
                )
            except ValueError as exc:
                raise ValueError(
                    "python_executable must be inside python_runtime_root"
                ) from exc
            object.__setattr__(self, "_python_executable_relative", python_relative)
        else:
            if self.python_runtime_root is not None:
                raise ValueError(
                    "python_runtime_root is only admitted for a protected-home Python"
                )
            object.__setattr__(self, "_python_executable_relative", None)

    def _runtime_mounts(
        self,
        registration: RunRegistration,
        runtime_source_package: Path,
        source_package: Path,
    ) -> tuple[ReadOnlyRuntimeMount, ...]:
        suffix = registration.run_id.value.rsplit("_", 1)[-1][:40]
        base = PurePosixPath(f"/tmp/openchia-episode-inputs-{suffix}")
        mounts = [
            ReadOnlyRuntimeMount(
                kind=RuntimeMountKind.RUNTIME_SOURCE_PACKAGE,
                source_path=str(runtime_source_package),
                target_path=str(
                    base
                    / registration.runtime_identity.runtime_source_manifest_id.value
                ),
            ),
            ReadOnlyRuntimeMount(
                kind=RuntimeMountKind.SOURCE_PACKAGE,
                source_path=str(source_package),
                target_path=str(base / registration.manifest_id.value),
            ),
        ]
        if self.python_runtime_root is not None:
            mounts.append(
                ReadOnlyRuntimeMount(
                    kind=RuntimeMountKind.PYTHON_RUNTIME,
                    source_path=str(self.python_runtime_root),
                    target_path=str(base / "python-runtime"),
                )
            )
        return tuple(mounts)

    def _launch_arguments(
        self,
        registration: RunRegistration,
        launch_identity: _LaunchIdentity,
        mounts: tuple[ReadOnlyRuntimeMount, ...],
        bootstrap_program: str,
    ) -> tuple[str, ...]:
        mount_by_kind = {mount.kind: mount for mount in mounts}
        runtime_source = Path(
            mount_by_kind[
                RuntimeMountKind.RUNTIME_SOURCE_PACKAGE
            ].target_path
        )
        source = Path(
            mount_by_kind[RuntimeMountKind.SOURCE_PACKAGE].target_path
        )
        python_executable = self.python_executable
        python_mount = mount_by_kind.get(RuntimeMountKind.PYTHON_RUNTIME)
        if python_mount is not None:
            if self._python_executable_relative is None:
                raise AssertionError("Python runtime mount has no executable path")
            python_executable = (
                Path(python_mount.target_path) / self._python_executable_relative
            )
        arguments = [
            str(self.systemd_run),
            "--user",
            "--quiet",
            "--collect",
            "--wait",
            "--pipe",
            "--service-type=exec",
            f"--unit={launch_identity.unit_name}",
            f"--description={launch_identity.description}",
        ]
        arguments.extend(
            f"--property={property_value}"
            for property_value in _systemd_properties(self.resources, mounts)
        )
        arguments.extend(
            (
                str(self.env_executable),
                "-i",
                str(python_executable),
                "-I",
                "-S",
                "-B",
                "-X",
                "pycache_prefix=/tmp/openchia-disabled-pycache",
                "-c",
                bootstrap_program,
                "--bootstrap-package",
                str(runtime_source),
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
                str(source),
                "--runtime-source-package",
                str(runtime_source),
            )
        )
        return tuple(arguments)

    async def _stop_exact(
        self,
        launch_identity: _LaunchIdentity,
        launcher: asyncio.subprocess.Process,
        facts: Optional[_ExecutorFacts],
    ) -> None:
        if launcher.returncode is not None:
            return
        try:
            values = await _show_unit(
                self.systemctl,
                launch_identity.unit_name,
            )
        except RunExecutionError:
            try:
                await _command_output(
                    str(self.systemctl),
                    "--user",
                    "stop",
                    launch_identity.unit_name,
                )
            finally:
                if launcher.returncode is None:
                    launcher.terminate()
                    await launcher.wait()
            return
        if values["Description"] != launch_identity.description:
            launcher.terminate()
            await launcher.wait()
            raise RunExecutionError(
                "refusing to stop a transient unit with another launch identity"
            )
        if facts is not None:
            live_pid = _positive_integer(values["MainPID"], "MainPID")
            if (
                values["InvocationID"] != facts.invocation_id
                or live_pid != facts.leader_pid
                or values["ControlGroup"] != facts.cgroup_path
                or _proc_start_time(live_pid) != facts.leader_start_time_ticks
                or _proc_cgroup(live_pid) != facts.cgroup_path
                or _boot_id() != facts.boot_id
            ):
                launcher.terminate()
                await launcher.wait()
                raise RunExecutionError(
                    "refusing to stop a transient unit whose process identity changed"
                )
        await _command_output(
            str(self.systemctl),
            "--user",
            "stop",
            launch_identity.unit_name,
        )
        await launcher.wait()


    def _identity_arguments(self) -> dict[str, Any]:
        return {"python_executable": self.python_executable}

    def _launch_identity(self, run_id: OpaqueId) -> _LaunchIdentity:
        return _launch_identity(run_id, ExecutorKind.SYSTEMD)

    def inspect_runtime_identity(
        self,
        *,
        destination_root: str | Path,
    ) -> RuntimeIdentity:
        from .identity import inspect_runtime_identity

        return inspect_runtime_identity(
            repository_root=self.repository_root,
            destination_root=destination_root,
            python_executable=self.python_executable,
        )

    async def _launch(
        self,
        registration: RunRegistration,
        launch_identity: _LaunchIdentity,
        mounts: tuple[ReadOnlyRuntimeMount, ...],
        bootstrap_program: str,
    ) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            *self._launch_arguments(
                registration,
                launch_identity,
                mounts,
                bootstrap_program,
            ),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _inspect(
        self,
        launch_identity: _LaunchIdentity,
        launcher: asyncio.subprocess.Process,
        mounts: tuple[ReadOnlyRuntimeMount, ...],
    ) -> _ExecutorFacts:
        return await _inspect_executor(
            systemctl=self.systemctl,
            launch_identity=launch_identity,
            launcher=launcher,
            resources=self.resources,
            read_only_runtime_mounts=mounts,
        )


RunExecutorFactory = Callable[[RunStore], RunExecutor]


def make_systemd_run_executor_factory(
    *,
    repository_root: str | Path,
) -> RunExecutorFactory:
    """Build the strict host dependency for fresh per-Run executors.

    The current interpreter identity is captured once.  Effective cgroup-v2
    allocation is inspected afresh for every explicit Run action, so a
    long-lived host neither invents nor retains stale task ceilings.
    """

    root = Path(repository_root).expanduser()
    if root.is_symlink():
        raise ValueError("runtime repository cannot be a symlink")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("runtime repository must exist")
    interpreter = current_interpreter_executable()
    base_prefix = Path(sys.base_prefix).expanduser().resolve(strict=True)
    python_runtime_root = (
        base_prefix if _hidden_by_protect_home(interpreter) else None
    )
    if python_runtime_root is not None:
        try:
            interpreter.relative_to(python_runtime_root)
        except ValueError as exc:
            raise ValueError(
                "current protected-home interpreter is outside sys.base_prefix"
            ) from exc

    def factory(run_store: RunStore) -> SystemdRunExecutor:
        if not isinstance(run_store, RunStore):
            raise TypeError("run_store must be a RunStore")
        return SystemdRunExecutor(
            run_store=run_store,
            repository_root=root,
            resources=ExecutorResources.from_host_effective_allocation(),
            python_executable=interpreter,
            python_runtime_root=python_runtime_root,
        )

    return factory


__all__ = [
    "ExecutorResources",
    "RunExecutor",
    "RunExecutorFactory",
    "RunExecutionError",
    "SystemdRunExecutor",
    "make_systemd_run_executor_factory",
]
