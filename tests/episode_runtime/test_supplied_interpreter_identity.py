"""Runtime identity with a supplied (non-host) interpreter, and the bootstrap inspector.

The container executor's worker runs the image's Python, not the host's.  The
identity recorded in the runtime manifest must then be the image interpreter's,
and the host must verify the staged package against *that* identity instead
of re-inspecting itself.  The bootstrap's ``--inspect-interpreter`` mode is the
inspector; it must agree byte-for-byte with ``inspect_interpreter_runtime``.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent.episode_contracts import Sha256Digest
from episode_runtime.contracts import InterpreterRuntimeIdentity
from episode_runtime.identity import (
    RuntimeIdentityError,
    inspect_interpreter_runtime,
    interpreter_runtime_from_inspection,
    materialize_runtime_source_package,
    verify_runtime_source_package,
)

REPO = Path(__file__).resolve().parents[2]


def test_bootstrap_inspector_agrees_with_the_host_inspection():
    bootstrap = (REPO / "episode_runtime" / "bootstrap.py").read_text(encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", bootstrap, "--inspect-interpreter"],
        capture_output=True, timeout=600, check=True,
    )
    record = json.loads(completed.stdout)
    from_bootstrap = interpreter_runtime_from_inspection(record)
    from_host = inspect_interpreter_runtime()
    assert from_bootstrap.as_record() == from_host.as_record()
    assert Path(record["executable_path"]).is_file()


def _other_interpreter() -> InterpreterRuntimeIdentity:
    return InterpreterRuntimeIdentity(
        implementation="cpython", version=(3, 14, 7), cache_tag="cpython-314",
        executable_hash=Sha256Digest.of_bytes(b"linux python"),
        stdlib_file_hashes={"os.py": Sha256Digest.of_bytes(b"os")},
        shared_library_hashes={"ldlibrary/libpython3.14.so": Sha256Digest.of_bytes(b"so")},
    )


def test_supplied_interpreter_is_recorded_and_verified_without_touching_the_host(tmp_path):
    other = _other_interpreter()
    identity, package = materialize_runtime_source_package(
        repository_root=REPO, destination_root=tmp_path / "runtime_sources", interpreter_runtime=other,
    )
    assert identity.interpreter_runtime_id == other.interpreter_id
    manifest = verify_runtime_source_package(identity, package, interpreter_runtime=other)
    assert manifest.interpreter_runtime.as_record() == other.as_record()
    # Verifying against the host's own interpreter must fail: the package names another one.
    with pytest.raises(RuntimeIdentityError):
        verify_runtime_source_package(identity, package)
    # And a different supplied identity is rejected too.
    different = InterpreterRuntimeIdentity(
        implementation="cpython", version=(3, 14, 7), cache_tag="cpython-314",
        executable_hash=Sha256Digest.of_bytes(b"other bytes"),
        stdlib_file_hashes={"os.py": Sha256Digest.of_bytes(b"os")}, shared_library_hashes={},
    )
    with pytest.raises(RuntimeIdentityError):
        verify_runtime_source_package(identity, package, interpreter_runtime=different)


def test_inspection_record_shape_is_exact():
    with pytest.raises(RuntimeIdentityError):
        interpreter_runtime_from_inspection({"implementation": "cpython"})
