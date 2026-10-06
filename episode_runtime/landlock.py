"""Exact Landlock ABI 7 confinement for an Episode worker process.

The default policy denies every handled right. A registered dependency policy
adds read-only directory rules whose exact paths are retained in the receipt;
the host must compare those paths with the frozen environment before starting
the Run. Importing this module never changes the importing process.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import errno
import os
from pathlib import PurePosixPath
import sys
from typing import Any, Mapping

from agent.duet_contracts import content_id, digest_record
from agent.episode_contracts import OpaqueId, Sha256Digest


LANDLOCK_ABI_VERSION = 7
LANDLOCK_CREATE_RULESET_VERSION = 1

# ABI 7 defines filesystem access rights in bits 0 through 15.
LANDLOCK_HANDLED_ACCESS_FS = (1 << 16) - 1
# TCP bind and connect are network access rights 0 and 1.
LANDLOCK_HANDLED_ACCESS_NET = (1 << 2) - 1
# Abstract Unix sockets and signal delivery are scoped rights 0 and 1.
LANDLOCK_SCOPED_RIGHTS = (1 << 2) - 1

PR_SET_NO_NEW_PRIVS = 38

_LANDLOCK_CREATE_RULESET = 444
_LANDLOCK_ADD_RULE = 445
_LANDLOCK_RESTRICT_SELF = 446
_LANDLOCK_RULE_PATH_BENEATH = 1
_LANDLOCK_ACCESS_READ_ONLY = (1 << 2) | (1 << 3)
_SUPPORTED_MACHINES = frozenset(
    {
        "aarch64",
        "arm64",
        "i386",
        "i486",
        "i586",
        "i686",
        "riscv64",
        "x86_64",
    }
)


class LandlockError(RuntimeError):
    """The exact runtime isolation policy could not be installed."""


class _LandlockRulesetAttr(ctypes.Structure):
    _fields_ = (
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
        ("scoped", ctypes.c_uint64),
    )


class _LandlockPathBeneathAttr(ctypes.Structure):
    # The Linux UAPI packs this u64/i32 pair into 12 bytes; ctypes requires an
    # explicit packing layout on Python 3.14+ even on a Linux host.
    _layout_ = "ms"
    _pack_ = 1
    _fields_ = (
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    )


def landlock_abi7_policy_record(*, dependency_reads: bool = False) -> dict[str, object]:
    """Hash the policy independently of Run-specific mount paths."""

    if type(dependency_reads) is not bool:
        raise TypeError("dependency_reads must be a boolean")
    record = {
        "abi_version": LANDLOCK_ABI_VERSION,
        "handled_access_fs": LANDLOCK_HANDLED_ACCESS_FS,
        "handled_access_net": LANDLOCK_HANDLED_ACCESS_NET,
        "scoped": LANDLOCK_SCOPED_RIGHTS,
        "allow_rule_count": 0,
        "no_new_privs": True,
        "ruleset_restricted": True,
    }
    if dependency_reads:
        del record["allow_rule_count"]
        record.update(
            dependency_reads=True,
            allowed_access_fs=_LANDLOCK_ACCESS_READ_ONLY,
            rule_source="registered_environment_read_only_paths",
        )
    return record


def landlock_abi7_policy_hash(*, dependency_reads: bool = False) -> Sha256Digest:
    return digest_record(landlock_abi7_policy_record(dependency_reads=dependency_reads))


def _canonical_read_only_paths(paths) -> tuple[str, ...]:
    if not isinstance(paths, (tuple, list)):
        raise TypeError("read_only_paths must be a sequence of absolute directory paths")
    for path in paths:
        if (
            not isinstance(path, str) or "\x00" in path
            or not PurePosixPath(path).is_absolute() or path == "/" or path.startswith("//")
            or ".." in PurePosixPath(path).parts or PurePosixPath(path).as_posix() != path
        ):
            raise ValueError("read-only policy paths must be normalized absolute non-root directories")
    if len(paths) != len(set(paths)):
        raise ValueError("read-only policy paths must be unique")
    return tuple(sorted(paths))


@dataclass(frozen=True)
class LandlockPolicyReceipt:
    """Content-bound evidence that one worker installed the exact ABI 7 policy."""

    run_id: OpaqueId
    executor_instance_id: OpaqueId
    policy_hash: Sha256Digest = field(
        default_factory=landlock_abi7_policy_hash
    )
    dependency_reads: bool = False
    read_only_paths: tuple[str, ...] = ()
    receipt_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, OpaqueId):
            raise TypeError("run_id must be an OpaqueId")
        if not isinstance(self.executor_instance_id, OpaqueId):
            raise TypeError("executor_instance_id must be an OpaqueId")
        if not isinstance(self.policy_hash, Sha256Digest):
            raise TypeError("policy_hash must be a Sha256Digest")
        paths = _canonical_read_only_paths(self.read_only_paths)
        object.__setattr__(self, "read_only_paths", paths)
        if type(self.dependency_reads) is not bool or self.dependency_reads != bool(paths):
            raise ValueError("dependency-read policy must bind its nonempty read-only paths")
        if self.policy_hash != landlock_abi7_policy_hash(dependency_reads=self.dependency_reads):
            raise ValueError("Landlock receipt does not bind the exact ABI 7 policy")
        receipt_id = content_id("landlock_receipt", self.semantic_record())
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
            "executor_instance_id": self.executor_instance_id.value,
            "policy": landlock_abi7_policy_record(dependency_reads=self.dependency_reads),
            "policy_hash": self.policy_hash.value,
            **({"read_only_paths": list(self.read_only_paths)} if self.dependency_reads else {}),
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id.value,
            "content_hash": self.content_hash.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "LandlockPolicyReceipt":
        expected = {
            "receipt_id",
            "content_hash",
            "run_id",
            "executor_instance_id",
            "policy",
            "policy_hash",
        }
        if not isinstance(value, Mapping) or not isinstance(value.get("policy"), Mapping):
            raise ValueError("Landlock policy receipt fields must be exact")
        dependency_reads = value["policy"].get("dependency_reads", False)
        if dependency_reads:
            expected.add("read_only_paths")
        if set(value) != expected:
            raise ValueError("Landlock policy receipt fields must be exact")
        if value["policy"] != landlock_abi7_policy_record(dependency_reads=dependency_reads):
            raise ValueError("Landlock policy receipt contains another policy")
        result = cls(
            run_id=OpaqueId(value["run_id"]),
            executor_instance_id=OpaqueId(value["executor_instance_id"]),
            policy_hash=Sha256Digest(value["policy_hash"]),
            dependency_reads=dependency_reads,
            read_only_paths=value.get("read_only_paths", ()),
        )
        if (
            result.receipt_id.value != value["receipt_id"]
            or result.content_hash.value != value["content_hash"]
        ):
            raise ValueError("Landlock policy receipt identity is stale")
        return result


def _syscall_number(name: str) -> int:
    if not sys.platform.startswith("linux"):
        raise LandlockError("Landlock ABI 7 is available only on Linux")
    machine = os.uname().machine.lower()
    if machine not in _SUPPORTED_MACHINES:
        raise LandlockError(
            f"Landlock syscall numbers are not declared for {machine!r}"
        )
    if name == "create_ruleset":
        return _LANDLOCK_CREATE_RULESET
    if name == "restrict_self":
        return _LANDLOCK_RESTRICT_SELF
    if name == "add_rule":
        return _LANDLOCK_ADD_RULE
    raise AssertionError(f"unknown Landlock syscall {name!r}")


def _raise_errno(operation: str) -> None:
    error_number = ctypes.get_errno()
    detail = os.strerror(error_number) if error_number else "unknown error"
    raise LandlockError(f"{operation} failed: [{error_number}] {detail}")


def _query_abi(libc: ctypes.CDLL) -> int:
    result = libc.syscall(
        _syscall_number("create_ruleset"),
        ctypes.c_void_p(),
        ctypes.c_size_t(0),
        ctypes.c_uint32(LANDLOCK_CREATE_RULESET_VERSION),
    )
    if result == -1:
        _raise_errno("Landlock ABI query")
    return int(result)


def apply_landlock_abi7(
    *,
    run_id: OpaqueId,
    executor_instance_id: OpaqueId,
    read_only_paths: tuple[str, ...] = (),
) -> LandlockPolicyReceipt:
    """Install the exact deny-by-default ABI 7 policy in the current process.

    Only the registered dependency variant adds read-only rules. Callers must
    derive the paths from the verified registration, not candidate code, and
    invoke this before importing any dependency or activating generated code.
    """

    if not isinstance(run_id, OpaqueId):
        raise TypeError("run_id must be an OpaqueId")
    if not isinstance(executor_instance_id, OpaqueId):
        raise TypeError("executor_instance_id must be an OpaqueId")
    paths = _canonical_read_only_paths(read_only_paths)

    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    libc.prctl.argtypes = (
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    )
    libc.prctl.restype = ctypes.c_int

    actual_abi = _query_abi(libc)
    if actual_abi != LANDLOCK_ABI_VERSION:
        raise LandlockError(
            f"executor requires Landlock ABI {LANDLOCK_ABI_VERSION}, "
            f"kernel reported {actual_abi}"
        )

    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        _raise_errno("PR_SET_NO_NEW_PRIVS")

    attributes = _LandlockRulesetAttr(
        handled_access_fs=LANDLOCK_HANDLED_ACCESS_FS,
        handled_access_net=LANDLOCK_HANDLED_ACCESS_NET,
        scoped=LANDLOCK_SCOPED_RIGHTS,
    )
    ruleset_fd = libc.syscall(
        _syscall_number("create_ruleset"),
        ctypes.byref(attributes),
        ctypes.sizeof(attributes),
        ctypes.c_uint32(0),
    )
    if ruleset_fd == -1:
        _raise_errno("Landlock ruleset creation")

    try:
        for path in paths:
            descriptor = os.open(path, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
            try:
                rule = _LandlockPathBeneathAttr(
                    allowed_access=_LANDLOCK_ACCESS_READ_ONLY, parent_fd=descriptor,
                )
                result = libc.syscall(
                    _syscall_number("add_rule"), ctypes.c_int(ruleset_fd),
                    ctypes.c_int(_LANDLOCK_RULE_PATH_BENEATH), ctypes.byref(rule), ctypes.c_uint32(0),
                )
                if result == -1:
                    _raise_errno("Landlock read-only rule admission")
            finally:
                os.close(descriptor)
        result = libc.syscall(
            _syscall_number("restrict_self"),
            ctypes.c_int(ruleset_fd),
            ctypes.c_uint32(0),
        )
        if result == -1:
            _raise_errno("Landlock restriction")
    finally:
        try:
            os.close(int(ruleset_fd))
        except OSError as exc:
            if exc.errno != errno.EBADF:
                raise

    return LandlockPolicyReceipt(
        run_id=run_id,
        executor_instance_id=executor_instance_id,
        policy_hash=landlock_abi7_policy_hash(dependency_reads=bool(paths)),
        dependency_reads=bool(paths), read_only_paths=paths,
    )


__all__ = [
    "LANDLOCK_ABI_VERSION",
    "LANDLOCK_HANDLED_ACCESS_FS",
    "LANDLOCK_HANDLED_ACCESS_NET",
    "LANDLOCK_SCOPED_RIGHTS",
    "LandlockError",
    "LandlockPolicyReceipt",
    "apply_landlock_abi7",
    "landlock_abi7_policy_hash",
    "landlock_abi7_policy_record",
]
