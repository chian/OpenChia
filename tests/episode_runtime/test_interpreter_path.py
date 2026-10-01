"""The runtime must locate its own interpreter on every platform, not just Linux.

Observed on macOS: the first human turn in OpenChia failed with
``Human instruction was not persisted for the Duet: [Errno 2] No such file or
directory: '/proc/self/exe'`` because building the OpenChia host eagerly
constructs the systemd Run executor factory, which read ``/proc/self/exe``.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from episode_runtime import current_interpreter_executable, make_systemd_run_executor_factory
from episode_runtime.identity import _current_executable, inspect_interpreter_runtime


def test_current_interpreter_executable_is_this_process():
    found = current_interpreter_executable()
    assert found.is_file()
    assert not found.is_symlink()
    expected = Path(sys.executable).resolve(strict=True)
    if sys.platform.startswith("linux") and os.path.exists("/proc/self/exe"):
        expected = Path(os.readlink("/proc/self/exe")).resolve(strict=True)
    assert found == expected


def test_identity_default_executable_resolves_without_proc(monkeypatch):
    """identity._current_executable() with no explicit path must not touch /proc."""
    real_readlink = os.readlink

    def no_proc(path, *args, **kwargs):
        if str(path).startswith("/proc/"):
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return real_readlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "readlink", no_proc)
    assert _current_executable() == Path(sys.executable).resolve(strict=True)


def test_executor_factory_builds_on_this_platform(tmp_path):
    """The factory is constructed when the OpenChia host is created, before any Run;
    it must build wherever the Duet can design, even where systemd never runs."""
    repo = Path(__file__).resolve().parents[2]
    factory = make_systemd_run_executor_factory(repository_root=repo)
    assert callable(factory)


def test_interpreter_runtime_identity_inspects_without_proc():
    identity = inspect_interpreter_runtime()
    assert identity is not None
