"""Exact post-initialization seccomp boundary for the Episode worker.

The worker installs this filter only after its asyncio pipe transport, source
closure, and admitted imports are ready.  Existing descriptor I/O and the
event loop's existing socketpair remain usable; creating network endpoints,
opening paths, mutating the filesystem, spawning processes, and replacing the
process image are denied with ``EPERM``. The registered dependency variant
admits read-only open/openat; Landlock restricts those reads to the frozen roots.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
import errno
import os
import platform
from typing import Any, Mapping

from agent.duet_contracts import content_id, digest_record
from agent.episode_contracts import OpaqueId, Sha256Digest


PR_SET_NO_NEW_PRIVS = 38
PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2

_BPF_LD_W_ABS = 0x20
_BPF_JMP_JEQ_K = 0x15
_BPF_JMP_JSET_K = 0x45
_BPF_RET_K = 0x06
_SECCOMP_RET_KILL_PROCESS = 0x80000000
_SECCOMP_RET_ERRNO = 0x00050000
_SECCOMP_RET_ALLOW = 0x7FFF0000

_AUDIT_ARCH = {
    "x86_64": 0xC000003E,
    "aarch64": 0xC00000B7,
    "arm64": 0xC00000B7,
}

_DENIED_SYSCALLS = {
    "x86_64": {
        "open": 2,
        "socket": 41,
        "connect": 42,
        "accept": 43,
        "bind": 49,
        "listen": 50,
        "clone": 56,
        "fork": 57,
        "vfork": 58,
        "execve": 59,
        "truncate": 76,
        "ftruncate": 77,
        "rename": 82,
        "mkdir": 83,
        "rmdir": 84,
        "creat": 85,
        "link": 86,
        "unlink": 87,
        "symlink": 88,
        "chmod": 90,
        "fchmod": 91,
        "chown": 92,
        "fchown": 93,
        "lchown": 94,
        "ptrace": 101,
        "pivot_root": 155,
        "chroot": 161,
        "mount": 165,
        "umount2": 166,
        "openat": 257,
        "mkdirat": 258,
        "mknodat": 259,
        "fchownat": 260,
        "unlinkat": 263,
        "renameat": 264,
        "linkat": 265,
        "symlinkat": 266,
        "fchmodat": 268,
        "accept4": 288,
        "renameat2": 316,
        "execveat": 322,
        "userfaultfd": 323,
        "clone3": 435,
        "openat2": 437,
    },
    "aarch64": {
        "unlinkat": 35,
        "symlinkat": 36,
        "linkat": 37,
        "renameat": 38,
        "umount2": 39,
        "mount": 40,
        "pivot_root": 41,
        "fchmodat": 53,
        "fchownat": 54,
        "openat": 56,
        "chroot": 51,
        "ptrace": 117,
        "socket": 198,
        "bind": 200,
        "listen": 201,
        "accept": 202,
        "connect": 203,
        "clone": 220,
        "execve": 221,
        "accept4": 242,
        "execveat": 281,
        "renameat2": 276,
        "userfaultfd": 282,
        "clone3": 435,
        "openat2": 437,
    },
}
_DENIED_SYSCALLS["arm64"] = _DENIED_SYSCALLS["aarch64"]

# Linux flags are policy data, not the registering host's os.O_* constants.
# O_TMPFILE's private bit is included, not its shared O_DIRECTORY bit.
_WRITE_OPEN_FLAGS = 0x3 | 0x40 | 0x200 | 0x400 | 0x400000
_OPEN_FLAGS_ARGUMENT = {"open": 1, "openat": 2}


class SeccompError(RuntimeError):
    """The exact syscall boundary could not be installed."""


class _SockFilter(ctypes.Structure):
    _fields_ = (
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint32),
    )


class _SockFprog(ctypes.Structure):
    _fields_ = (
        ("length", ctypes.c_ushort),
        ("filter", ctypes.POINTER(_SockFilter)),
    )


_MACHINE_ALIASES = {
    # macOS and some BSDs report the Apple/ARM spelling; the kernel ABI, the
    # audit arch and the worker's uname all say ``aarch64``.
    "arm64": "aarch64",
    "amd64": "x86_64",
}


def normalize_machine(name: str) -> str:
    """Canonical kernel spelling of a machine name (``arm64`` -> ``aarch64``).

    A host that only *registers* a Run (for example macOS launching a Linux
    container) must hash the same policy the worker installs, so both sides
    name the architecture the same way.
    """
    lowered = name.lower()
    return _MACHINE_ALIASES.get(lowered, lowered)


def _machine() -> str:
    machine = normalize_machine(platform.machine())
    if machine not in _AUDIT_ARCH or machine not in _DENIED_SYSCALLS:
        raise SeccompError(f"seccomp policy is not declared for {machine!r}")
    return machine


def seccomp_policy_record(machine: str | None = None, *, dependency_reads: bool = False) -> dict[str, object]:
    if type(dependency_reads) is not bool:
        raise TypeError("dependency_reads must be a boolean")
    selected = _machine() if machine is None else normalize_machine(machine)
    if selected not in _AUDIT_ARCH or selected not in _DENIED_SYSCALLS:
        raise ValueError("seccomp machine is unsupported")
    record = {
        "machine": selected,
        "audit_arch": _AUDIT_ARCH[selected],
        "default_action": "allow",
        "denied_action": "errno_eperm",
        "denied_syscalls": {
            name: number
            for name, number in sorted(_DENIED_SYSCALLS[selected].items())
            if not dependency_reads or name not in _OPEN_FLAGS_ARGUMENT
        },
        "no_new_privs": True,
    }
    if dependency_reads:
        record.update(
            dependency_reads=True,
            read_only_open_syscalls={
                name: {"number": _DENIED_SYSCALLS[selected][name], "flags_argument": argument}
                for name, argument in _OPEN_FLAGS_ARGUMENT.items() if name in _DENIED_SYSCALLS[selected]
            },
            denied_open_flags=_WRITE_OPEN_FLAGS,
        )
    return record


def seccomp_policy_hash(machine: str | None = None, *, dependency_reads: bool = False) -> Sha256Digest:
    return digest_record(seccomp_policy_record(machine, dependency_reads=dependency_reads))


@dataclass(frozen=True)
class SeccompPolicyReceipt:
    run_id: OpaqueId
    executor_instance_id: OpaqueId
    machine: str
    policy_hash: Sha256Digest
    dependency_reads: bool = False
    receipt_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, OpaqueId):
            raise TypeError("run_id must be an OpaqueId")
        if not isinstance(self.executor_instance_id, OpaqueId):
            raise TypeError("executor_instance_id must be an OpaqueId")
        object.__setattr__(self, "machine", normalize_machine(self.machine))
        if self.machine not in _DENIED_SYSCALLS:
            raise ValueError("seccomp receipt machine is unsupported")
        if not isinstance(self.policy_hash, Sha256Digest):
            raise TypeError("policy_hash must be a Sha256Digest")
        if self.policy_hash != seccomp_policy_hash(self.machine, dependency_reads=self.dependency_reads):
            raise ValueError("seccomp receipt names another policy")
        receipt_id = content_id("seccomp_receipt", self.semantic_record())
        object.__setattr__(self, "receipt_id", receipt_id)
        object.__setattr__(
            self,
            "content_hash",
            digest_record({"receipt_id": receipt_id.value, **self.semantic_record()}),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id.value,
            "executor_instance_id": self.executor_instance_id.value,
            "policy": seccomp_policy_record(self.machine, dependency_reads=self.dependency_reads),
            "policy_hash": self.policy_hash.value,
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id.value,
            "content_hash": self.content_hash.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "SeccompPolicyReceipt":
        expected = {
            "receipt_id",
            "content_hash",
            "run_id",
            "executor_instance_id",
            "policy",
            "policy_hash",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValueError("seccomp receipt fields must be exact")
        policy = value["policy"]
        if not isinstance(policy, Mapping):
            raise ValueError("seccomp receipt policy must be an object")
        machine = policy.get("machine")
        dependency_reads = policy.get("dependency_reads", False)
        if not isinstance(machine, str) or policy != seccomp_policy_record(machine, dependency_reads=dependency_reads):
            raise ValueError("seccomp receipt policy differs from the exact policy")
        result = cls(
            run_id=OpaqueId(value["run_id"]),
            executor_instance_id=OpaqueId(value["executor_instance_id"]),
            machine=machine,
            policy_hash=Sha256Digest(value["policy_hash"]),
            dependency_reads=dependency_reads,
        )
        if (
            result.receipt_id.value != value["receipt_id"]
            or result.content_hash.value != value["content_hash"]
        ):
            raise ValueError("seccomp receipt identity is stale")
        return result


def _raise_errno(operation: str) -> None:
    number = ctypes.get_errno()
    raise SeccompError(
        f"{operation} failed: [{number}] {os.strerror(number) if number else 'unknown'}"
    )


def apply_seccomp_policy(
    *,
    run_id: OpaqueId,
    executor_instance_id: OpaqueId,
    dependency_reads: bool = False,
) -> SeccompPolicyReceipt:
    if not isinstance(run_id, OpaqueId):
        raise TypeError("run_id must be an OpaqueId")
    if not isinstance(executor_instance_id, OpaqueId):
        raise TypeError("executor_instance_id must be an OpaqueId")
    machine = _machine()
    policy = seccomp_policy_record(machine, dependency_reads=dependency_reads)
    instructions: list[_SockFilter] = [
        _SockFilter(_BPF_LD_W_ABS, 0, 0, 4),
        _SockFilter(_BPF_JMP_JEQ_K, 1, 0, _AUDIT_ARCH[machine]),
        _SockFilter(_BPF_RET_K, 0, 0, _SECCOMP_RET_KILL_PROCESS),
        _SockFilter(_BPF_LD_W_ABS, 0, 0, 0),
    ]
    denied = sorted(set(policy["denied_syscalls"].values()))
    for number in denied:
        instructions.extend(
            (
                _SockFilter(_BPF_JMP_JEQ_K, 0, 1, number),
                _SockFilter(
                    _BPF_RET_K,
                    0,
                    0,
                    _SECCOMP_RET_ERRNO | errno.EPERM,
                ),
            )
        )
    # openat2 keeps its unconditional denial: its flags live behind a pointer
    # and cannot be checked by this classic BPF filter.
    for operation in policy.get("read_only_open_syscalls", {}).values():
        instructions.extend((
            _SockFilter(_BPF_JMP_JEQ_K, 0, 4, operation["number"]),
            _SockFilter(_BPF_LD_W_ABS, 0, 0, 16 + 8 * operation["flags_argument"]),
            _SockFilter(_BPF_JMP_JSET_K, 0, 1, _WRITE_OPEN_FLAGS),
            _SockFilter(_BPF_RET_K, 0, 0, _SECCOMP_RET_ERRNO | errno.EPERM),
            _SockFilter(_BPF_RET_K, 0, 0, _SECCOMP_RET_ALLOW),
        ))
    instructions.append(_SockFilter(_BPF_RET_K, 0, 0, _SECCOMP_RET_ALLOW))
    array_type = _SockFilter * len(instructions)
    array = array_type(*instructions)
    program = _SockFprog(len(instructions), array)

    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        _raise_errno("PR_SET_NO_NEW_PRIVS")
    if libc.prctl(
        PR_SET_SECCOMP,
        SECCOMP_MODE_FILTER,
        ctypes.byref(program),
        0,
        0,
    ) != 0:
        _raise_errno("PR_SET_SECCOMP")
    return SeccompPolicyReceipt(
        run_id=run_id,
        executor_instance_id=executor_instance_id,
        machine=machine,
        policy_hash=seccomp_policy_hash(machine, dependency_reads=dependency_reads),
        dependency_reads=dependency_reads,
    )


__all__ = [
    "SeccompError",
    "SeccompPolicyReceipt",
    "apply_seccomp_policy",
    "seccomp_policy_hash",
    "seccomp_policy_record",
]
