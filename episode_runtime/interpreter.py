"""Locate the running interpreter's real executable on every platform.

``/proc/self/exe`` is the kernel's own answer on Linux (symlinks already
resolved); it does not exist on macOS or the BSDs, where the same contract is
met by resolving ``sys.executable``. Every identity, executor and bootstrap
path goes through here so a non-Linux host can still *design* Episodes (the
systemd/cgroup Run executor itself remains Linux-only and says so when used).
"""
from __future__ import annotations

import os
from pathlib import Path
import sys


class InterpreterPathError(RuntimeError):
    """The running interpreter's executable could not be located as a regular file."""


def current_interpreter_executable() -> Path:
    """Return the resolved path of the executable running this process."""
    if sys.platform.startswith("linux"):
        try:
            return Path(os.readlink("/proc/self/exe")).resolve(strict=True)
        except OSError:
            pass  # hardened /proc or a container without it: fall back below
    if not sys.executable:
        raise InterpreterPathError("sys.executable is empty; cannot identify the interpreter")
    try:
        resolved = Path(sys.executable).expanduser().resolve(strict=True)
    except OSError as exc:
        raise InterpreterPathError(f"cannot resolve sys.executable: {exc}") from exc
    if not resolved.is_file():
        raise InterpreterPathError("interpreter executable is not a regular file")
    return resolved


__all__ = ["InterpreterPathError", "current_interpreter_executable"]
