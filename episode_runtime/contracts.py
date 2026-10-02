"""Immutable, content-addressed contracts for an admitted Episode Run."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping, Optional

from agent.duet_contracts import content_id, digest_record
from agent.episode_contracts import (
    EpisodeDeliverableKind,
    OpaqueId,
    Sha256Digest,
)
from handoff_library import DuetLaunchRequest

from .landlock import (
    LANDLOCK_ABI_VERSION,
    LandlockPolicyReceipt,
    landlock_abi7_policy_hash,
)
from .seccomp import SeccompPolicyReceipt, seccomp_policy_hash

if TYPE_CHECKING:
    from episode_builder._contract_base import (
        BuildAttempt,
        BuildReceipt,
    )
    from episode_builder._contract_chain import ApprovedBuildRequest, BuildManifest


DEFAULT_MAX_FRAME_BYTES = 1_048_576
MAX_MAX_FRAME_BYTES = 16_777_216
RUNTIME_WORKER_ENTRYPOINT = "episode_runtime.worker.main"

_TOKEN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_DOTTED_NAME = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*$"
)
_SYSTEMD_SERVICE = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9_.:@-]{0,246}\.service$"
)
_BOOT_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_INVOCATION_ID = re.compile(r"^[0-9a-f]{32}$")


def _record(
    value: object,
    name: str,
    expected: set[str],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{name} must contain exactly {sorted(expected)!r}")
    return value


def _array(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _token(value: object, name: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a closed lowercase token")
    return value


def _absolute_runtime_path(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or value.startswith("//")
        or value == "/"
        or "\x00" in value
        or ":" in value
        or "\\" in value
        or any(character.isspace() for character in value)
        or any(part == ".." for part in value.split("/"))
        or str(PurePosixPath(value)) != value
    ):
        raise ValueError(
            f"{name} must be an unambiguous normalized absolute non-root path"
        )
    return value


def _freeze_json(value: object, name: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError(f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        keys = tuple(value)
        if any(not isinstance(key, str) or not key for key in keys):
            raise ValueError(f"{name} keys must be non-empty strings")
        return MappingProxyType(
            {
                key: _freeze_json(value[key], f"{name}.{key}")
                for key in sorted(keys)
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(
            _freeze_json(item, f"{name}[{index}]")
            for index, item in enumerate(value)
        )
    raise ValueError(f"{name} must contain only JSON-shaped values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _json_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    result = _freeze_json(value, name)
    if not isinstance(result, Mapping):
        raise AssertionError("JSON mapping freeze changed its top-level shape")
    return result


def _source_hashes(
    value: object,
    name: str,
    *,
    allow_empty: bool = False,
) -> Mapping[str, Sha256Digest]:
    if not isinstance(value, Mapping) or (not value and not allow_empty):
        qualifier = "a mapping" if allow_empty else "a non-empty mapping"
        raise ValueError(f"{name} must be {qualifier}")
    result: dict[str, Sha256Digest] = {}
    for path in sorted(value):
        if (
            not isinstance(path, str)
            or path.startswith("/")
            or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            raise ValueError(f"{name} paths must be normalized relative paths")
        raw = value[path]
        result[path] = raw if isinstance(raw, Sha256Digest) else Sha256Digest(raw)
    return MappingProxyType(result)


def _launch_request_from_record(value: object) -> DuetLaunchRequest:
    record = _record(
        value,
        "Duet launch request",
        {
            "request_id",
            "workflow_id",
            "goal_id",
            "artifact_ids_by_role",
            "measurements",
            "states",
            "flags",
        },
    )
    artifacts = record["artifact_ids_by_role"]
    if not isinstance(artifacts, Mapping):
        raise ValueError("launch artifact_ids_by_role must be an object")
    return DuetLaunchRequest(
        request_id=record["request_id"],
        workflow_id=record["workflow_id"],
        goal_id=record["goal_id"],
        artifact_ids_by_role={
            role: tuple(_array(ids, f"artifact_ids_by_role.{role}"))
            for role, ids in artifacts.items()
        },
        measurements=record["measurements"],
        states=record["states"],
        flags=record["flags"],
    )


def derive_executor_instance_id(
    *,
    systemd_unit_name: str,
    boot_id: str,
    leader_pid: int,
    leader_start_time_ticks: int,
    cgroup_path: str,
) -> OpaqueId:
    """Derive the non-reusable identity of one inspected systemd process."""

    if (
        not isinstance(systemd_unit_name, str)
        or _SYSTEMD_SERVICE.fullmatch(systemd_unit_name) is None
    ):
        raise ValueError("systemd_unit_name must be an exact transient service name")
    if not isinstance(boot_id, str) or _BOOT_ID.fullmatch(boot_id) is None:
        raise ValueError("boot_id must be a lowercase kernel boot UUID")
    _integer(leader_pid, "leader_pid", minimum=1)
    _integer(
        leader_start_time_ticks,
        "leader_start_time_ticks",
        minimum=1,
    )
    if (
        not isinstance(cgroup_path, str)
        or not cgroup_path.startswith("/")
        or cgroup_path.startswith("//")
        or "\x00" in cgroup_path
        or any(part == ".." for part in cgroup_path.split("/"))
        or str(PurePosixPath(cgroup_path)) != cgroup_path
    ):
        raise ValueError("cgroup_path must be an absolute normalized path")
    if PurePosixPath(cgroup_path).name != systemd_unit_name:
        raise ValueError("cgroup_path must end at the inspected systemd service")
    return content_id(
        "executor",
        {
            "systemd_unit_name": systemd_unit_name,
            "boot_id": boot_id,
            "leader_pid": leader_pid,
            "leader_start_time_ticks": leader_start_time_ticks,
            "cgroup_path": cgroup_path,
        },
    )


class RunEffectMode(str, Enum):
    NO_EFFECTS = "no_effects"


class RunEventOrigin(str, Enum):
    HOST = "host"
    WORKER = "worker"
    HOST_LEARNING = "host_learning"


class RunEventKind(str, Enum):
    RUNTIME_READY = "runtime_ready"
    RUN_STARTED = "run_started"
    EPISODE_STARTED = "episode_started"
    UNIT_COMPLETED = "unit_completed"
    EPISODE_COMPLETED = "episode_completed"
    MODEL_REQUESTED = "model_requested"
    MODEL_RESPONDED = "model_responded"
    LEARNING_EVIDENCE = "learning_evidence"
    LEARNING_OPENED = "learning_opened"
    LEARNING_SELECTED = "learning_selected"
    LEARNING_ATTEMPT = "learning_attempt"
    LEARNING_REPAIR_REQUESTED = "learning_repair_requested"
    LEARNING_COMMITTED = "learning_committed"
    RUN_SUCCEEDED = "run_succeeded"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"
    RUN_BLOCKED = "run_blocked"
    RUN_INTERRUPTED = "run_interrupted"
    RUN_INVALID = "run_invalid"
    RUN_RESOURCE_LIMITED = "run_resource_limited"


class RunTerminalStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"
    INTERRUPTED = "interrupted"
    INVALID = "invalid"
    RESOURCE_LIMITED = "resource_limited"


class RuntimeMountKind(str, Enum):
    RUNTIME_SOURCE_PACKAGE = "runtime_source_package"
    SOURCE_PACKAGE = "source_package"
    PYTHON_RUNTIME = "python_runtime"


@dataclass(frozen=True)
class ReadOnlyRuntimeMount:
    """One exact host input projected read-only into the executor namespace."""

    kind: RuntimeMountKind
    source_path: str
    target_path: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RuntimeMountKind):
            raise TypeError("runtime mount kind must be a RuntimeMountKind")
        source = _absolute_runtime_path(self.source_path, "mount source_path")
        target = _absolute_runtime_path(self.target_path, "mount target_path")
        if source == target:
            raise ValueError("runtime mount must project to a distinct target path")
        object.__setattr__(self, "source_path", source)
        object.__setattr__(self, "target_path", target)

    def as_record(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "source_path": self.source_path,
            "target_path": self.target_path,
        }

    @classmethod
    def from_record(cls, value: object) -> "ReadOnlyRuntimeMount":
        record = _record(
            value,
            "read-only runtime mount",
            {"kind", "source_path", "target_path"},
        )
        try:
            kind = RuntimeMountKind(record["kind"])
        except (TypeError, ValueError) as exc:
            raise ValueError("read-only runtime mount kind is invalid") from exc
        return cls(
            kind=kind,
            source_path=record["source_path"],
            target_path=record["target_path"],
        )


_TERMINAL_EVENT_BY_STATUS = {
    RunTerminalStatus.SUCCEEDED: RunEventKind.RUN_SUCCEEDED,
    RunTerminalStatus.FAILED: RunEventKind.RUN_FAILED,
    RunTerminalStatus.CANCELLED: RunEventKind.RUN_CANCELLED,
    RunTerminalStatus.BLOCKED: RunEventKind.RUN_BLOCKED,
    RunTerminalStatus.INTERRUPTED: RunEventKind.RUN_INTERRUPTED,
    RunTerminalStatus.INVALID: RunEventKind.RUN_INVALID,
    RunTerminalStatus.RESOURCE_LIMITED: RunEventKind.RUN_RESOURCE_LIMITED,
}
TERMINAL_EVENT_KINDS = frozenset(_TERMINAL_EVENT_BY_STATUS.values())


@dataclass(frozen=True)
class RuntimePolicy:
    """The fixed initial runtime admission policy.

    Frame size is a transport isolation bound.  It is not an Episode stopping
    rule, and this policy intentionally contains no elapsed-time or iteration
    decision.
    """

    deliverable_kind: EpisodeDeliverableKind = EpisodeDeliverableKind.TYPED_STATUS
    effect_mode: RunEffectMode = RunEffectMode.NO_EFFECTS
    landlock_abi: int = LANDLOCK_ABI_VERSION
    landlock_policy_hash: Sha256Digest = field(
        default_factory=landlock_abi7_policy_hash
    )
    seccomp_policy_hash: Sha256Digest = field(default_factory=seccomp_policy_hash)
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES
    policy_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        if self.deliverable_kind is not EpisodeDeliverableKind.TYPED_STATUS:
            raise ValueError("the initial runtime admits only typed_status Runs")
        if self.effect_mode is not RunEffectMode.NO_EFFECTS:
            raise ValueError("the initial runtime admits only no-effect Runs")
        if self.landlock_abi != LANDLOCK_ABI_VERSION:
            raise ValueError("runtime policy requires exact Landlock ABI 7")
        if not isinstance(self.landlock_policy_hash, Sha256Digest):
            raise TypeError("landlock_policy_hash must be a Sha256Digest")
        if self.landlock_policy_hash != landlock_abi7_policy_hash():
            raise ValueError("runtime policy names another Landlock policy")
        if not isinstance(self.seccomp_policy_hash, Sha256Digest):
            raise TypeError("seccomp_policy_hash must be a Sha256Digest")
        if self.seccomp_policy_hash != seccomp_policy_hash():
            raise ValueError("runtime policy names another seccomp policy")
        frame_limit = _integer(
            self.max_frame_bytes,
            "max_frame_bytes",
            minimum=1024,
        )
        if frame_limit > MAX_MAX_FRAME_BYTES:
            raise ValueError(
                f"max_frame_bytes must be <= {MAX_MAX_FRAME_BYTES}"
            )
        policy_id = content_id("runtime_policy", self.semantic_record())
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(
            self,
            "content_hash",
            digest_record({"policy_id": policy_id.value, **self.semantic_record()}),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "deliverable_kind": self.deliverable_kind.value,
            "effect_mode": self.effect_mode.value,
            "landlock_abi": self.landlock_abi,
            "landlock_policy_hash": self.landlock_policy_hash.value,
            "seccomp_policy_hash": self.seccomp_policy_hash.value,
            "max_frame_bytes": self.max_frame_bytes,
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id.value,
            "content_hash": self.content_hash.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "RuntimePolicy":
        record = _record(
            value,
            "runtime policy",
            {
                "policy_id",
                "content_hash",
                "deliverable_kind",
                "effect_mode",
                "landlock_abi",
                "landlock_policy_hash",
                "seccomp_policy_hash",
                "max_frame_bytes",
            },
        )
        try:
            deliverable = EpisodeDeliverableKind(record["deliverable_kind"])
            effect_mode = RunEffectMode(record["effect_mode"])
        except (TypeError, ValueError) as exc:
            raise ValueError("runtime policy contains an unknown enum value") from exc
        result = cls(
            deliverable_kind=deliverable,
            effect_mode=effect_mode,
            landlock_abi=record["landlock_abi"],
            landlock_policy_hash=Sha256Digest(record["landlock_policy_hash"]),
            seccomp_policy_hash=Sha256Digest(record["seccomp_policy_hash"]),
            max_frame_bytes=record["max_frame_bytes"],
        )
        if (
            result.policy_id.value != record["policy_id"]
            or result.content_hash.value != record["content_hash"]
        ):
            raise ValueError("runtime policy identity is stale")
        return result


@dataclass(frozen=True)
class InterpreterRuntimeIdentity:
    """Exact executable and standard-library bytes available to the worker."""

    implementation: str
    version: tuple[int, int, int]
    cache_tag: str
    executable_hash: Sha256Digest
    stdlib_file_hashes: Mapping[str, Sha256Digest]
    shared_library_hashes: Mapping[str, Sha256Digest]
    interpreter_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.implementation, str) or not self.implementation:
            raise ValueError("interpreter implementation must be non-empty")
        if (
            not isinstance(self.version, tuple)
            or len(self.version) != 3
            or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in self.version)
        ):
            raise ValueError("interpreter version must be three non-negative integers")
        if not isinstance(self.cache_tag, str) or not self.cache_tag:
            raise ValueError("interpreter cache_tag must be non-empty")
        if not isinstance(self.executable_hash, Sha256Digest):
            raise TypeError("executable_hash must be a Sha256Digest")
        object.__setattr__(
            self,
            "stdlib_file_hashes",
            _source_hashes(self.stdlib_file_hashes, "stdlib_file_hashes"),
        )
        object.__setattr__(
            self,
            "shared_library_hashes",
            _source_hashes(
                self.shared_library_hashes,
                "shared_library_hashes",
                allow_empty=True,
            ),
        )
        interpreter_id = content_id("interpreter_runtime", self.semantic_record())
        object.__setattr__(self, "interpreter_id", interpreter_id)
        object.__setattr__(
            self,
            "content_hash",
            digest_record(
                {"interpreter_id": interpreter_id.value, **self.semantic_record()}
            ),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "implementation": self.implementation,
            "version": list(self.version),
            "cache_tag": self.cache_tag,
            "executable_hash": self.executable_hash.value,
            "stdlib_file_hashes": {
                path: digest.value for path, digest in self.stdlib_file_hashes.items()
            },
            "shared_library_hashes": {
                path: digest.value for path, digest in self.shared_library_hashes.items()
            },
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "interpreter_id": self.interpreter_id.value,
            "content_hash": self.content_hash.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "InterpreterRuntimeIdentity":
        record = _record(
            value,
            "interpreter runtime identity",
            {
                "interpreter_id",
                "content_hash",
                "implementation",
                "version",
                "cache_tag",
                "executable_hash",
                "stdlib_file_hashes",
                "shared_library_hashes",
            },
        )
        result = cls(
            implementation=record["implementation"],
            version=tuple(
                _integer(item, "interpreter version")
                for item in _array(record["version"], "interpreter version")
            ),
            cache_tag=record["cache_tag"],
            executable_hash=Sha256Digest(record["executable_hash"]),
            stdlib_file_hashes=record["stdlib_file_hashes"],
            shared_library_hashes=record["shared_library_hashes"],
        )
        if (
            result.interpreter_id.value != record["interpreter_id"]
            or result.content_hash.value != record["content_hash"]
        ):
            raise ValueError("interpreter runtime identity is stale")
        return result


@dataclass(frozen=True)
class RuntimeSourceManifest:
    """Complete source-only local import closure staged for one runtime."""

    worker_entrypoint: str
    bootstrap_path: str
    local_source_hashes: Mapping[str, Sha256Digest]
    synthetic_packages: tuple[str, ...]
    admitted_local_roots: tuple[str, ...]
    interpreter_runtime: InterpreterRuntimeIdentity
    manifest_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.worker_entrypoint, str)
            or _DOTTED_NAME.fullmatch(self.worker_entrypoint) is None
        ):
            raise ValueError("worker_entrypoint must be a dotted Python name")
        if self.worker_entrypoint != RUNTIME_WORKER_ENTRYPOINT:
            raise ValueError("runtime source manifest names another worker")
        bootstrap = tuple(_source_hashes({self.bootstrap_path: Sha256Digest.of_bytes(b"")}, "bootstrap_path"))
        if len(bootstrap) != 1:
            raise AssertionError("bootstrap path validation failed")
        object.__setattr__(self, "bootstrap_path", bootstrap[0])
        object.__setattr__(
            self,
            "local_source_hashes",
            _source_hashes(self.local_source_hashes, "local_source_hashes"),
        )
        if self.bootstrap_path not in self.local_source_hashes:
            raise ValueError("runtime source manifest omits its bootstrap")
        for name in ("synthetic_packages", "admitted_local_roots"):
            values = getattr(self, name)
            if (
                not isinstance(values, tuple)
                or not values
                or len(set(values)) != len(values)
                or any(_DOTTED_NAME.fullmatch(item) is None for item in values)
                or values != tuple(sorted(values))
            ):
                raise ValueError(f"{name} must be a sorted non-empty tuple of unique module names")
        if set(self.synthetic_packages) & set(self.admitted_local_roots):
            raise ValueError("synthetic and admitted package roots must be disjoint")
        if not isinstance(self.interpreter_runtime, InterpreterRuntimeIdentity):
            raise TypeError("interpreter_runtime must be an InterpreterRuntimeIdentity")
        manifest_id = content_id("runtime_source_manifest", self.semantic_record())
        object.__setattr__(self, "manifest_id", manifest_id)
        object.__setattr__(
            self,
            "content_hash",
            digest_record({"manifest_id": manifest_id.value, **self.semantic_record()}),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "worker_entrypoint": self.worker_entrypoint,
            "bootstrap_path": self.bootstrap_path,
            "local_source_hashes": {
                path: digest.value for path, digest in self.local_source_hashes.items()
            },
            "synthetic_packages": list(self.synthetic_packages),
            "admitted_local_roots": list(self.admitted_local_roots),
            "interpreter_runtime": self.interpreter_runtime.as_record(),
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id.value,
            "content_hash": self.content_hash.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "RuntimeSourceManifest":
        record = _record(
            value,
            "runtime source manifest",
            {
                "manifest_id",
                "content_hash",
                "worker_entrypoint",
                "bootstrap_path",
                "local_source_hashes",
                "synthetic_packages",
                "admitted_local_roots",
                "interpreter_runtime",
            },
        )
        result = cls(
            worker_entrypoint=record["worker_entrypoint"],
            bootstrap_path=record["bootstrap_path"],
            local_source_hashes=record["local_source_hashes"],
            synthetic_packages=tuple(_array(record["synthetic_packages"], "synthetic_packages")),
            admitted_local_roots=tuple(_array(record["admitted_local_roots"], "admitted_local_roots")),
            interpreter_runtime=InterpreterRuntimeIdentity.from_record(record["interpreter_runtime"]),
        )
        if (
            result.manifest_id.value != record["manifest_id"]
            or result.content_hash.value != record["content_hash"]
        ):
            raise ValueError("runtime source manifest identity is stale")
        return result


@dataclass(frozen=True)
class RuntimeIdentity:
    """Identity of the staged local source and exact interpreter runtime."""

    worker_entrypoint: str
    runtime_source_manifest_id: OpaqueId
    runtime_source_manifest_hash: Sha256Digest
    interpreter_runtime_id: OpaqueId
    interpreter_runtime_hash: Sha256Digest
    runtime_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.worker_entrypoint, str)
            or _DOTTED_NAME.fullmatch(self.worker_entrypoint) is None
        ):
            raise ValueError("worker_entrypoint must be a dotted Python name")
        if self.worker_entrypoint != RUNTIME_WORKER_ENTRYPOINT:
            raise ValueError("runtime identity names another worker")
        for name in ("runtime_source_manifest_id", "interpreter_runtime_id"):
            if not isinstance(getattr(self, name), OpaqueId):
                raise TypeError(f"{name} must be an OpaqueId")
        for name in ("runtime_source_manifest_hash", "interpreter_runtime_hash"):
            if not isinstance(getattr(self, name), Sha256Digest):
                raise TypeError(f"{name} must be a Sha256Digest")
        runtime_id = content_id("runtime", self.semantic_record())
        object.__setattr__(self, "runtime_id", runtime_id)
        object.__setattr__(
            self,
            "content_hash",
            digest_record({"runtime_id": runtime_id.value, **self.semantic_record()}),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "worker_entrypoint": self.worker_entrypoint,
            "runtime_source_manifest_id": self.runtime_source_manifest_id.value,
            "runtime_source_manifest_hash": self.runtime_source_manifest_hash.value,
            "interpreter_runtime_id": self.interpreter_runtime_id.value,
            "interpreter_runtime_hash": self.interpreter_runtime_hash.value,
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "runtime_id": self.runtime_id.value,
            "content_hash": self.content_hash.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "RuntimeIdentity":
        record = _record(
            value,
            "runtime identity",
            {
                "runtime_id",
                "content_hash",
                "worker_entrypoint",
                "runtime_source_manifest_id",
                "runtime_source_manifest_hash",
                "interpreter_runtime_id",
                "interpreter_runtime_hash",
            },
        )
        result = cls(
            worker_entrypoint=record["worker_entrypoint"],
            runtime_source_manifest_id=OpaqueId(record["runtime_source_manifest_id"]),
            runtime_source_manifest_hash=Sha256Digest(record["runtime_source_manifest_hash"]),
            interpreter_runtime_id=OpaqueId(record["interpreter_runtime_id"]),
            interpreter_runtime_hash=Sha256Digest(record["interpreter_runtime_hash"]),
        )
        if (
            result.runtime_id.value != record["runtime_id"]
            or result.content_hash.value != record["content_hash"]
        ):
            raise ValueError("runtime identity is stale")
        return result


@dataclass(frozen=True)
class RunRegistration:
    """The complete immutable authority and materialization binding for one Run."""

    duet_id: OpaqueId
    admission_authority_id: OpaqueId
    admission_authority_hash: Sha256Digest
    authority_head_approval_id: OpaqueId
    authority_head_approval_hash: Sha256Digest
    workflow_approval_id: OpaqueId
    workflow_approval_hash: Sha256Digest
    workflow_id: OpaqueId
    workflow_hash: Sha256Digest
    build_request_id: OpaqueId
    build_attempt_id: OpaqueId
    build_receipt_id: OpaqueId
    manifest_id: OpaqueId
    manifest_hash: Sha256Digest
    launch_request: DuetLaunchRequest
    runtime_identity: RuntimeIdentity
    runtime_policy: RuntimePolicy
    run_id: OpaqueId = field(init=False)
    registration_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "duet_id",
            "admission_authority_id",
            "authority_head_approval_id",
            "workflow_approval_id",
            "workflow_id",
            "build_request_id",
            "build_attempt_id",
            "build_receipt_id",
            "manifest_id",
        ):
            if not isinstance(getattr(self, name), OpaqueId):
                raise TypeError(f"{name} must be an OpaqueId")
        for name in (
            "admission_authority_hash",
            "authority_head_approval_hash",
            "workflow_approval_hash",
            "workflow_hash",
            "manifest_hash",
        ):
            if not isinstance(getattr(self, name), Sha256Digest):
                raise TypeError(f"{name} must be a Sha256Digest")
        if not isinstance(self.launch_request, DuetLaunchRequest):
            raise TypeError("launch_request must be an admitted DuetLaunchRequest")
        if self.launch_request.workflow_id != self.workflow_id.value:
            raise ValueError("launch request names another frozen workflow")
        if not isinstance(self.runtime_identity, RuntimeIdentity):
            raise TypeError("runtime_identity must be a RuntimeIdentity")
        if not isinstance(self.runtime_policy, RuntimePolicy):
            raise TypeError("runtime_policy must be a RuntimePolicy")
        run_id = content_id("run", self.semantic_record())
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(
            self,
            "registration_hash",
            digest_record({"run_id": run_id.value, **self.semantic_record()}),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "duet_id": self.duet_id.value,
            "admission_authority_id": self.admission_authority_id.value,
            "admission_authority_hash": self.admission_authority_hash.value,
            "authority_head_approval_id": self.authority_head_approval_id.value,
            "authority_head_approval_hash": self.authority_head_approval_hash.value,
            "workflow_approval_id": self.workflow_approval_id.value,
            "workflow_approval_hash": self.workflow_approval_hash.value,
            "workflow_id": self.workflow_id.value,
            "workflow_hash": self.workflow_hash.value,
            "build_request_id": self.build_request_id.value,
            "build_attempt_id": self.build_attempt_id.value,
            "build_receipt_id": self.build_receipt_id.value,
            "manifest_id": self.manifest_id.value,
            "manifest_hash": self.manifest_hash.value,
            "launch_request": self.launch_request.as_record(),
            "runtime_identity": self.runtime_identity.as_record(),
            "runtime_policy": self.runtime_policy.as_record(),
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id.value,
            "registration_hash": self.registration_hash.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_admitted_build(
        cls,
        *,
        build_request: ApprovedBuildRequest,
        build_attempt: BuildAttempt,
        build_receipt: BuildReceipt,
        build_manifest: BuildManifest,
        launch_request: DuetLaunchRequest,
        runtime_identity: RuntimeIdentity,
        runtime_policy: RuntimePolicy,
    ) -> "RunRegistration":
        """Bind already-admitted Builder artifacts without copying their prose."""

        from episode_builder._contract_base import (
            BuildAttempt,
            BuildReceipt,
        )
        from episode_builder._contract_chain import ApprovedBuildRequest, BuildManifest

        if not isinstance(build_request, ApprovedBuildRequest):
            raise TypeError("build_request must be an ApprovedBuildRequest")
        if not isinstance(build_attempt, BuildAttempt):
            raise TypeError("build_attempt must be a BuildAttempt")
        if not isinstance(build_receipt, BuildReceipt):
            raise TypeError("build_receipt must be a BuildReceipt")
        if not isinstance(build_manifest, BuildManifest):
            raise TypeError("build_manifest must be a BuildManifest")
        if not isinstance(launch_request, DuetLaunchRequest):
            raise TypeError("launch_request must be an admitted DuetLaunchRequest")
        if not isinstance(runtime_identity, RuntimeIdentity):
            raise TypeError("runtime_identity must be a RuntimeIdentity")
        if not isinstance(runtime_policy, RuntimePolicy):
            raise TypeError("runtime_policy must be a RuntimePolicy")

        if build_attempt.build_request_id != build_request.build_request_id:
            raise ValueError("build attempt belongs to another approved request")
        if (
            build_receipt.build_request_id != build_request.build_request_id
            or build_receipt.build_attempt_id != build_attempt.build_attempt_id
        ):
            raise ValueError("build receipt belongs to another request or attempt")
        if not build_receipt.materialized or build_receipt.manifest_id is None:
            raise ValueError("only a materialized build receipt can be registered")
        if (
            build_manifest.manifest_id != build_receipt.manifest_id
            or build_manifest.build_request_id != build_request.build_request_id
            or build_manifest.build_attempt_id != build_attempt.build_attempt_id
        ):
            raise ValueError("build manifest belongs to another receipt")
        frozen = build_request.frozen_workflow
        if build_manifest.workflow_hash != frozen.workflow_hash:
            raise ValueError("build manifest materializes another workflow")
        if launch_request.workflow_id != frozen.artifact_id.value:
            raise ValueError("launch request names another frozen workflow")
        non_status_nodes = tuple(
            episode.local_id
            for episode in frozen.workflow.episodes
            if episode.contract.deliverable.kind
            is not EpisodeDeliverableKind.TYPED_STATUS
        )
        if non_status_nodes:
            raise ValueError(
                "the initial runtime admits only typed_status Episodes: "
                f"{non_status_nodes!r}"
            )

        authority = build_request.admission_authority
        authority_head = build_request.authority_approval
        workflow_approval = build_request.workflow_approval
        return cls(
            duet_id=frozen.duet_id,
            admission_authority_id=authority.authority_id,
            admission_authority_hash=authority.content_hash,
            authority_head_approval_id=authority_head.approval_id,
            authority_head_approval_hash=digest_record(
                authority_head.as_record()
            ),
            workflow_approval_id=workflow_approval.approval_id,
            workflow_approval_hash=digest_record(
                workflow_approval.as_record()
            ),
            workflow_id=frozen.artifact_id,
            workflow_hash=frozen.workflow_hash,
            build_request_id=build_request.build_request_id,
            build_attempt_id=build_attempt.build_attempt_id,
            build_receipt_id=build_receipt.receipt_id,
            manifest_id=build_manifest.manifest_id,
            manifest_hash=digest_record(build_manifest.as_record()),
            launch_request=launch_request,
            runtime_identity=runtime_identity,
            runtime_policy=runtime_policy,
        )

    @classmethod
    def from_record(cls, value: object) -> "RunRegistration":
        record = _record(
            value,
            "Run registration",
            {
                "run_id",
                "registration_hash",
                "duet_id",
                "admission_authority_id",
                "admission_authority_hash",
                "authority_head_approval_id",
                "authority_head_approval_hash",
                "workflow_approval_id",
                "workflow_approval_hash",
                "workflow_id",
                "workflow_hash",
                "build_request_id",
                "build_attempt_id",
                "build_receipt_id",
                "manifest_id",
                "manifest_hash",
                "launch_request",
                "runtime_identity",
                "runtime_policy",
            },
        )
        result = cls(
            duet_id=OpaqueId(record["duet_id"]),
            admission_authority_id=OpaqueId(
                record["admission_authority_id"]
            ),
            admission_authority_hash=Sha256Digest(
                record["admission_authority_hash"]
            ),
            authority_head_approval_id=OpaqueId(
                record["authority_head_approval_id"]
            ),
            authority_head_approval_hash=Sha256Digest(
                record["authority_head_approval_hash"]
            ),
            workflow_approval_id=OpaqueId(record["workflow_approval_id"]),
            workflow_approval_hash=Sha256Digest(
                record["workflow_approval_hash"]
            ),
            workflow_id=OpaqueId(record["workflow_id"]),
            workflow_hash=Sha256Digest(record["workflow_hash"]),
            build_request_id=OpaqueId(record["build_request_id"]),
            build_attempt_id=OpaqueId(record["build_attempt_id"]),
            build_receipt_id=OpaqueId(record["build_receipt_id"]),
            manifest_id=OpaqueId(record["manifest_id"]),
            manifest_hash=Sha256Digest(record["manifest_hash"]),
            launch_request=_launch_request_from_record(record["launch_request"]),
            runtime_identity=RuntimeIdentity.from_record(
                record["runtime_identity"]
            ),
            runtime_policy=RuntimePolicy.from_record(record["runtime_policy"]),
        )
        if (
            result.run_id.value != record["run_id"]
            or result.registration_hash.value != record["registration_hash"]
        ):
            raise ValueError("Run registration identity is stale")
        return result


@dataclass(frozen=True)
class InspectedExecutorAttestation:
    """Host inspection of the claimed executor and its isolation allocation.

    The cgroup values record isolation facts only.  They never participate in
    Episode continuation or stopping decisions.
    """

    run_id: OpaqueId
    registration_hash: Sha256Digest
    manifest_id: OpaqueId
    executor_instance_id: OpaqueId
    runtime_id: OpaqueId
    runtime_hash: Sha256Digest
    runtime_policy_id: OpaqueId
    runtime_policy_hash: Sha256Digest
    landlock_receipt: LandlockPolicyReceipt
    seccomp_receipt: SeccompPolicyReceipt
    systemd_unit_name: str
    systemd_invocation_id: str
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
    attestation_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "manifest_id",
            "executor_instance_id",
            "runtime_id",
            "runtime_policy_id",
        ):
            if not isinstance(getattr(self, name), OpaqueId):
                raise TypeError(f"{name} must be an OpaqueId")
        for name in (
            "registration_hash",
            "runtime_hash",
            "runtime_policy_hash",
        ):
            if not isinstance(getattr(self, name), Sha256Digest):
                raise TypeError(f"{name} must be a Sha256Digest")
        if not isinstance(self.landlock_receipt, LandlockPolicyReceipt):
            raise TypeError("landlock_receipt must be a LandlockPolicyReceipt")
        if not isinstance(self.seccomp_receipt, SeccompPolicyReceipt):
            raise TypeError("seccomp_receipt must be a SeccompPolicyReceipt")
        if (
            self.landlock_receipt.run_id != self.run_id
            or self.landlock_receipt.executor_instance_id
            != self.executor_instance_id
        ):
            raise ValueError("Landlock receipt belongs to another executor")
        if (
            self.seccomp_receipt.run_id != self.run_id
            or self.seccomp_receipt.executor_instance_id
            != self.executor_instance_id
        ):
            raise ValueError("seccomp receipt belongs to another executor")
        if self.landlock_receipt.policy_hash != landlock_abi7_policy_hash():
            raise ValueError("executor installed another Landlock policy")
        if self.seccomp_receipt.policy_hash != seccomp_policy_hash():
            raise ValueError("executor installed another seccomp policy")
        expected_executor_id = derive_executor_instance_id(
            systemd_unit_name=self.systemd_unit_name,
            boot_id=self.boot_id,
            leader_pid=self.leader_pid,
            leader_start_time_ticks=self.leader_start_time_ticks,
            cgroup_path=self.cgroup_path,
        )
        if self.executor_instance_id != expected_executor_id:
            raise ValueError(
                "executor_instance_id does not match the inspected process identity"
            )
        if (
            not isinstance(self.systemd_invocation_id, str)
            or _INVOCATION_ID.fullmatch(self.systemd_invocation_id) is None
        ):
            raise ValueError("systemd_invocation_id must be 32 lowercase hex digits")
        description_parts = (
            self.launch_description.split(":")
            if isinstance(self.launch_description, str)
            else ()
        )
        if (
            len(description_parts) != 3
            or description_parts[0] != "openchia-episode-launch"
            or description_parts[1] != self.run_id.value
            or _INVOCATION_ID.fullmatch(description_parts[2]) is None
            or self.systemd_unit_name
            != (
                "openchia-episode-"
                + self.run_id.value.rsplit("_", 1)[-1][:32]
                + "-"
                + description_parts[2]
                + ".service"
            )
        ):
            raise ValueError("launch_description is not an exact launch identity")
        if not isinstance(self.read_only_runtime_mounts, tuple):
            raise TypeError("read_only_runtime_mounts must be a tuple")
        if any(
            not isinstance(item, ReadOnlyRuntimeMount)
            for item in self.read_only_runtime_mounts
        ):
            raise TypeError(
                "read_only_runtime_mounts must contain ReadOnlyRuntimeMount values"
            )
        mount_kinds = tuple(item.kind for item in self.read_only_runtime_mounts)
        required_mounts = (
            RuntimeMountKind.RUNTIME_SOURCE_PACKAGE,
            RuntimeMountKind.SOURCE_PACKAGE,
        )
        expected_order = tuple(
            kind for kind in RuntimeMountKind if kind in set(mount_kinds)
        )
        if (
            mount_kinds != expected_order
            or not set(required_mounts).issubset(mount_kinds)
        ):
            raise ValueError(
                "executor attestation has missing, duplicate, or unordered runtime mounts"
            )
        if len({item.source_path for item in self.read_only_runtime_mounts}) != len(
            self.read_only_runtime_mounts
        ) or len({item.target_path for item in self.read_only_runtime_mounts}) != len(
            self.read_only_runtime_mounts
        ):
            raise ValueError("runtime mount sources and targets must be unique")
        for name in ("memory_max_bytes", "pids_max", "cpu_quota_micros"):
            value = getattr(self, name)
            if value is not None:
                _integer(value, name, minimum=1)
        cpu_weight = _integer(self.cpu_weight, "cpu_weight", minimum=1)
        if cpu_weight > 10_000:
            raise ValueError("cpu_weight must be <= 10000")
        _integer(self.cpu_period_micros, "cpu_period_micros", minimum=1)
        isolation = (
            self.filesystem_namespace_isolated,
            self.process_namespace_isolated,
            self.network_namespace_isolated,
            self.host_runtime_read_only,
            self.no_new_privs,
        )
        if any(not isinstance(item, bool) for item in isolation):
            raise TypeError("executor isolation facts must be boolean")
        if not all(isolation):
            raise ValueError("executor attestation must prove every isolation fact")
        attestation_id = content_id(
            "executor_attestation",
            self.semantic_record(),
        )
        object.__setattr__(self, "attestation_id", attestation_id)
        object.__setattr__(
            self,
            "content_hash",
            digest_record(
                {
                    "attestation_id": attestation_id.value,
                    **self.semantic_record(),
                }
            ),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id.value,
            "registration_hash": self.registration_hash.value,
            "manifest_id": self.manifest_id.value,
            "executor_instance_id": self.executor_instance_id.value,
            "runtime_id": self.runtime_id.value,
            "runtime_hash": self.runtime_hash.value,
            "runtime_policy_id": self.runtime_policy_id.value,
            "runtime_policy_hash": self.runtime_policy_hash.value,
            "landlock_receipt": self.landlock_receipt.as_record(),
            "seccomp_receipt": self.seccomp_receipt.as_record(),
            "systemd_unit_name": self.systemd_unit_name,
            "systemd_invocation_id": self.systemd_invocation_id,
            "launch_description": self.launch_description,
            "boot_id": self.boot_id,
            "leader_pid": self.leader_pid,
            "leader_start_time_ticks": self.leader_start_time_ticks,
            "cgroup_path": self.cgroup_path,
            "read_only_runtime_mounts": [
                item.as_record() for item in self.read_only_runtime_mounts
            ],
            "memory_max_bytes": self.memory_max_bytes,
            "pids_max": self.pids_max,
            "cpu_weight": self.cpu_weight,
            "cpu_quota_micros": self.cpu_quota_micros,
            "cpu_period_micros": self.cpu_period_micros,
            "filesystem_namespace_isolated": self.filesystem_namespace_isolated,
            "process_namespace_isolated": self.process_namespace_isolated,
            "network_namespace_isolated": self.network_namespace_isolated,
            "host_runtime_read_only": self.host_runtime_read_only,
            "no_new_privs": self.no_new_privs,
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "attestation_id": self.attestation_id.value,
            "content_hash": self.content_hash.value,
            **self.semantic_record(),
        }

    def validate_against(self, registration: RunRegistration) -> None:
        if not isinstance(registration, RunRegistration):
            raise TypeError("registration must be a RunRegistration")
        if (
            self.run_id != registration.run_id
            or self.registration_hash != registration.registration_hash
            or self.manifest_id != registration.manifest_id
            or self.runtime_id != registration.runtime_identity.runtime_id
            or self.runtime_hash != registration.runtime_identity.content_hash
            or self.runtime_policy_id != registration.runtime_policy.policy_id
            or self.runtime_policy_hash
            != registration.runtime_policy.content_hash
            or self.landlock_receipt.policy_hash
            != registration.runtime_policy.landlock_policy_hash
            or self.seccomp_receipt.policy_hash
            != registration.runtime_policy.seccomp_policy_hash
        ):
            raise ValueError("executor attestation does not match its registration")
        mounts = {item.kind: item for item in self.read_only_runtime_mounts}
        runtime_mount = mounts[RuntimeMountKind.RUNTIME_SOURCE_PACKAGE]
        source_mount = mounts[RuntimeMountKind.SOURCE_PACKAGE]
        if (
            PurePosixPath(runtime_mount.source_path).name
            != registration.runtime_identity.runtime_source_manifest_id.value
            or PurePosixPath(runtime_mount.target_path).name
            != registration.runtime_identity.runtime_source_manifest_id.value
            or PurePosixPath(source_mount.source_path).name
            != registration.manifest_id.value
            or PurePosixPath(source_mount.target_path).name
            != registration.manifest_id.value
        ):
            raise ValueError("executor mounts name another registered package")

    @classmethod
    def from_record(cls, value: object) -> "InspectedExecutorAttestation":
        record = _record(
            value,
            "executor attestation",
            {
                "attestation_id",
                "content_hash",
                "run_id",
                "registration_hash",
                "manifest_id",
                "executor_instance_id",
                "runtime_id",
                "runtime_hash",
                "runtime_policy_id",
                "runtime_policy_hash",
                "landlock_receipt",
                "seccomp_receipt",
                "systemd_unit_name",
                "systemd_invocation_id",
                "launch_description",
                "boot_id",
                "leader_pid",
                "leader_start_time_ticks",
                "cgroup_path",
                "read_only_runtime_mounts",
                "memory_max_bytes",
                "pids_max",
                "cpu_weight",
                "cpu_quota_micros",
                "cpu_period_micros",
                "filesystem_namespace_isolated",
                "process_namespace_isolated",
                "network_namespace_isolated",
                "host_runtime_read_only",
                "no_new_privs",
            },
        )
        result = cls(
            run_id=OpaqueId(record["run_id"]),
            registration_hash=Sha256Digest(record["registration_hash"]),
            manifest_id=OpaqueId(record["manifest_id"]),
            executor_instance_id=OpaqueId(record["executor_instance_id"]),
            runtime_id=OpaqueId(record["runtime_id"]),
            runtime_hash=Sha256Digest(record["runtime_hash"]),
            runtime_policy_id=OpaqueId(record["runtime_policy_id"]),
            runtime_policy_hash=Sha256Digest(record["runtime_policy_hash"]),
            landlock_receipt=LandlockPolicyReceipt.from_record(
                record["landlock_receipt"]
            ),
            seccomp_receipt=SeccompPolicyReceipt.from_record(
                record["seccomp_receipt"]
            ),
            systemd_unit_name=record["systemd_unit_name"],
            systemd_invocation_id=record["systemd_invocation_id"],
            launch_description=record["launch_description"],
            boot_id=record["boot_id"],
            leader_pid=record["leader_pid"],
            leader_start_time_ticks=record["leader_start_time_ticks"],
            cgroup_path=record["cgroup_path"],
            read_only_runtime_mounts=tuple(
                ReadOnlyRuntimeMount.from_record(item)
                for item in _array(
                    record["read_only_runtime_mounts"],
                    "read_only_runtime_mounts",
                )
            ),
            memory_max_bytes=record["memory_max_bytes"],
            pids_max=record["pids_max"],
            cpu_weight=record["cpu_weight"],
            cpu_quota_micros=record["cpu_quota_micros"],
            cpu_period_micros=record["cpu_period_micros"],
            filesystem_namespace_isolated=record[
                "filesystem_namespace_isolated"
            ],
            process_namespace_isolated=record["process_namespace_isolated"],
            network_namespace_isolated=record["network_namespace_isolated"],
            host_runtime_read_only=record["host_runtime_read_only"],
            no_new_privs=record["no_new_privs"],
        )
        if (
            result.attestation_id.value != record["attestation_id"]
            or result.content_hash.value != record["content_hash"]
        ):
            raise ValueError("executor attestation identity is stale")
        return result


@dataclass(frozen=True)
class RunEvent:
    """One host-assigned event in the immutable Run evidence chain."""

    run_id: OpaqueId
    registration_hash: Sha256Digest
    manifest_id: OpaqueId
    attestation_id: OpaqueId
    attestation_hash: Sha256Digest
    sequence: int
    origin: RunEventOrigin
    sender_sequence: int
    kind: RunEventKind
    episode_id: Optional[OpaqueId]
    payload: Mapping[str, object]
    previous_event_hash: Optional[Sha256Digest]
    event_id: OpaqueId = field(init=False)
    event_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        for name in ("run_id", "manifest_id", "attestation_id"):
            if not isinstance(getattr(self, name), OpaqueId):
                raise TypeError(f"{name} must be an OpaqueId")
        for name in ("registration_hash", "attestation_hash"):
            if not isinstance(getattr(self, name), Sha256Digest):
                raise TypeError(f"{name} must be a Sha256Digest")
        _integer(self.sequence, "sequence")
        _integer(self.sender_sequence, "sender_sequence")
        if not isinstance(self.origin, RunEventOrigin):
            raise TypeError("origin must be a RunEventOrigin")
        if not isinstance(self.kind, RunEventKind):
            raise TypeError("kind must be a RunEventKind")
        if self.episode_id is not None and not isinstance(
            self.episode_id,
            OpaqueId,
        ):
            raise TypeError("episode_id must be an OpaqueId or None")
        object.__setattr__(
            self,
            "payload",
            _json_mapping(self.payload, "Run event payload"),
        )
        if self.sequence == 0:
            if self.previous_event_hash is not None:
                raise ValueError("the first Run event cannot name a predecessor")
        elif not isinstance(self.previous_event_hash, Sha256Digest):
            raise TypeError("a non-first Run event needs a predecessor hash")
        if self.kind in TERMINAL_EVENT_KINDS:
            if set(self.payload) != {"terminal_status", "typed_status"}:
                raise ValueError("terminal event payload fields must be exact")
            try:
                status = RunTerminalStatus(self.payload["terminal_status"])
            except (TypeError, ValueError) as exc:
                raise ValueError("terminal event status is invalid") from exc
            if _TERMINAL_EVENT_BY_STATUS[status] is not self.kind:
                raise ValueError("terminal event kind and status disagree")
            if not isinstance(self.payload["typed_status"], Mapping):
                raise ValueError("terminal typed_status must be an object")
        event_id = content_id("run_event", self.semantic_record())
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(
            self,
            "event_hash",
            digest_record({"event_id": event_id.value, **self.semantic_record()}),
        )

    @property
    def terminal(self) -> bool:
        return self.kind in TERMINAL_EVENT_KINDS

    def semantic_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id.value,
            "registration_hash": self.registration_hash.value,
            "manifest_id": self.manifest_id.value,
            "attestation_id": self.attestation_id.value,
            "attestation_hash": self.attestation_hash.value,
            "sequence": self.sequence,
            "origin": self.origin.value,
            "sender_sequence": self.sender_sequence,
            "kind": self.kind.value,
            "episode_id": (
                None if self.episode_id is None else self.episode_id.value
            ),
            "payload": _thaw_json(self.payload),
            "previous_event_hash": (
                None
                if self.previous_event_hash is None
                else self.previous_event_hash.value
            ),
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id.value,
            "event_hash": self.event_hash.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "RunEvent":
        record = _record(
            value,
            "Run event",
            {
                "event_id",
                "event_hash",
                "run_id",
                "registration_hash",
                "manifest_id",
                "attestation_id",
                "attestation_hash",
                "sequence",
                "origin",
                "sender_sequence",
                "kind",
                "episode_id",
                "payload",
                "previous_event_hash",
            },
        )
        try:
            origin = RunEventOrigin(record["origin"])
            kind = RunEventKind(record["kind"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Run event contains an unknown enum value") from exc
        result = cls(
            run_id=OpaqueId(record["run_id"]),
            registration_hash=Sha256Digest(record["registration_hash"]),
            manifest_id=OpaqueId(record["manifest_id"]),
            attestation_id=OpaqueId(record["attestation_id"]),
            attestation_hash=Sha256Digest(record["attestation_hash"]),
            sequence=record["sequence"],
            origin=origin,
            sender_sequence=record["sender_sequence"],
            kind=kind,
            episode_id=(
                None
                if record["episode_id"] is None
                else OpaqueId(record["episode_id"])
            ),
            payload=record["payload"],
            previous_event_hash=(
                None
                if record["previous_event_hash"] is None
                else Sha256Digest(record["previous_event_hash"])
            ),
        )
        if (
            result.event_id.value != record["event_id"]
            or result.event_hash.value != record["event_hash"]
        ):
            raise ValueError("Run event identity is stale")
        return result


@dataclass(frozen=True)
class EffectReceipt:
    """Host-authored evidence for a future effect-capable runtime.

    The initial protocol has no worker frame for this record and the initial
    store exposes no receipt-ingress operation.  It therefore cannot be used
    to make a no-effect Run appear effectful.
    """

    run_id: OpaqueId
    registration_hash: Sha256Digest
    manifest_id: OpaqueId
    attestation_id: OpaqueId
    event_id: OpaqueId
    capability_name: str
    effect_kind: str
    request_hash: Sha256Digest
    result_hash: Sha256Digest
    receipt_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "manifest_id",
            "attestation_id",
            "event_id",
        ):
            if not isinstance(getattr(self, name), OpaqueId):
                raise TypeError(f"{name} must be an OpaqueId")
        for name in ("registration_hash", "request_hash", "result_hash"):
            if not isinstance(getattr(self, name), Sha256Digest):
                raise TypeError(f"{name} must be a Sha256Digest")
        object.__setattr__(
            self,
            "capability_name",
            _token(self.capability_name, "capability_name"),
        )
        object.__setattr__(
            self,
            "effect_kind",
            _token(self.effect_kind, "effect_kind"),
        )
        receipt_id = content_id("effect_receipt", self.semantic_record())
        object.__setattr__(self, "receipt_id", receipt_id)
        object.__setattr__(
            self,
            "content_hash",
            digest_record(
                {"receipt_id": receipt_id.value, **self.semantic_record()}
            ),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id.value,
            "registration_hash": self.registration_hash.value,
            "manifest_id": self.manifest_id.value,
            "attestation_id": self.attestation_id.value,
            "event_id": self.event_id.value,
            "capability_name": self.capability_name,
            "effect_kind": self.effect_kind,
            "request_hash": self.request_hash.value,
            "result_hash": self.result_hash.value,
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id.value,
            "content_hash": self.content_hash.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "EffectReceipt":
        record = _record(
            value,
            "effect receipt",
            {
                "receipt_id",
                "content_hash",
                "run_id",
                "registration_hash",
                "manifest_id",
                "attestation_id",
                "event_id",
                "capability_name",
                "effect_kind",
                "request_hash",
                "result_hash",
            },
        )
        result = cls(
            run_id=OpaqueId(record["run_id"]),
            registration_hash=Sha256Digest(record["registration_hash"]),
            manifest_id=OpaqueId(record["manifest_id"]),
            attestation_id=OpaqueId(record["attestation_id"]),
            event_id=OpaqueId(record["event_id"]),
            capability_name=record["capability_name"],
            effect_kind=record["effect_kind"],
            request_hash=Sha256Digest(record["request_hash"]),
            result_hash=Sha256Digest(record["result_hash"]),
        )
        if (
            result.receipt_id.value != record["receipt_id"]
            or result.content_hash.value != record["content_hash"]
        ):
            raise ValueError("effect receipt identity is stale")
        return result


__all__ = [
    "DEFAULT_MAX_FRAME_BYTES",
    "MAX_MAX_FRAME_BYTES",
    "RUNTIME_WORKER_ENTRYPOINT",
    "TERMINAL_EVENT_KINDS",
    "EffectReceipt",
    "InspectedExecutorAttestation",
    "ReadOnlyRuntimeMount",
    "RunEffectMode",
    "RunEvent",
    "RunEventKind",
    "RunEventOrigin",
    "RunRegistration",
    "RunTerminalStatus",
    "RuntimeMountKind",
    "InterpreterRuntimeIdentity",
    "RuntimeIdentity",
    "RuntimePolicy",
    "RuntimeSourceManifest",
    "derive_executor_instance_id",
]
