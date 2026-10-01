"""Exact Landlock ABI 7 confinement for an Episode worker process.

The runtime applies this policy inside the worker.  This module does not open
or admit filesystem or network rules: every handled right is denied by the
empty ruleset.  Applying the policy is intentionally an explicit function so
importing the runtime never changes the importing process.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import errno
import os
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
_LANDLOCK_RESTRICT_SELF = 446
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


def landlock_abi7_policy_record() -> dict[str, int | bool]:
    """Return the immutable, allow-rule-free policy applied by this module."""

    return {
        "abi_version": LANDLOCK_ABI_VERSION,
        "handled_access_fs": LANDLOCK_HANDLED_ACCESS_FS,
        "handled_access_net": LANDLOCK_HANDLED_ACCESS_NET,
        "scoped": LANDLOCK_SCOPED_RIGHTS,
        "allow_rule_count": 0,
        "no_new_privs": True,
        "ruleset_restricted": True,
    }


def landlock_abi7_policy_hash() -> Sha256Digest:
    return digest_record(landlock_abi7_policy_record())


@dataclass(frozen=True)
class LandlockPolicyReceipt:
    """Content-bound evidence that one worker installed the exact ABI 7 policy."""

    run_id: OpaqueId
    executor_instance_id: OpaqueId
    policy_hash: Sha256Digest = field(
        default_factory=landlock_abi7_policy_hash
    )
    receipt_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, OpaqueId):
            raise TypeError("run_id must be an OpaqueId")
        if not isinstance(self.executor_instance_id, OpaqueId):
            raise TypeError("executor_instance_id must be an OpaqueId")
        if not isinstance(self.policy_hash, Sha256Digest):
            raise TypeError("policy_hash must be a Sha256Digest")
        if self.policy_hash != landlock_abi7_policy_hash():
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
            "policy": landlock_abi7_policy_record(),
            "policy_hash": self.policy_hash.value,
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
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValueError("Landlock policy receipt fields must be exact")
        if value["policy"] != landlock_abi7_policy_record():
            raise ValueError("Landlock policy receipt contains another policy")
        result = cls(
            run_id=OpaqueId(value["run_id"]),
            executor_instance_id=OpaqueId(value["executor_instance_id"]),
            policy_hash=Sha256Digest(value["policy_hash"]),
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
) -> LandlockPolicyReceipt:
    """Install the exact deny-by-default ABI 7 policy in the current process.

    No allow rule is added.  The ruleset descriptor is closed whether policy
    installation succeeds or fails.  Callers must invoke this after process
    setup and before admitting worker-controlled data.
    """

    if not isinstance(run_id, OpaqueId):
        raise TypeError("run_id must be an OpaqueId")
    if not isinstance(executor_instance_id, OpaqueId):
        raise TypeError("executor_instance_id must be an OpaqueId")

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
