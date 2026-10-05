"""Import the actual worker using only its verified staged closure and stdlib.

The help path stops before starting an execution or installing confinement. It
tests package completeness without reading implementation text or permitting
imports from the checkout to hide missing staged dependencies.
"""

from pathlib import Path
import subprocess
import sys

from episode_runtime.identity import materialize_runtime_source_package


def test_worker_imports_from_its_verified_staged_closure(tmp_path):
    identity, package = materialize_runtime_source_package(
        repository_root=Path(__file__).resolve().parents[2],
        destination_root=tmp_path / "runtime_sources",
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(package / "episode_runtime/bootstrap.py"),
            "--bootstrap-package",
            str(package),
            "--bootstrap-manifest-id",
            identity.runtime_source_manifest_id.value,
            "--bootstrap-manifest-hash",
            identity.runtime_source_manifest_hash.value,
            "--help",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--source-package" in completed.stdout
