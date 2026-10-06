"""Preparation uses the admitted PM tool closure, not ambient package settings."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agent.episode_contracts import Sha256Digest
from episode_runtime.target_environment import TargetEnvironmentLock, TargetEnvironmentRecipe
from pm.environment import PythonEnvironment, prune_site_pth
from pm.environments import site_packages
from pm.package import InstallError
from pm.prepared_project import _installed, _registry_lock, _requirements
from tests.pm._fixtures import _wheel, admitted_pm_tools as admitted_pm_tools


def test_preparation_builds_and_reuses_exact_lock_without_ambient_state(tmp_path, admitted_pm_tools):
    store, target, _ = admitted_pm_tools
    recipe = TargetEnvironmentRecipe(python=f"{sys.version_info.major}.{sys.version_info.minor}")
    runtime = Sha256Digest.of_bytes(b"the selected backend runtime")
    original_env = dict(os.environ)
    original_facts = (store / "facts.json").read_bytes()
    results = []
    for name in ("initial", "independent"):
        work = tmp_path / name
        work.mkdir()
        (work / "tmp").mkdir()
        request = {
            "schema_version": 1, "recipe": recipe.as_record(), "runtime_hash": runtime.value,
            "resolved_lock": results[0]["resolved_lock"] if results else None,
            "work_dir": str(work), "tool_store": str(store), "tool_target": target,
            "python_executable": sys.executable,
        }
        request_path = work / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        env = {**os.environ, "HERMES_VERBOSE": "1", "TMPDIR": str(work / "tmp"),
               "UV_INDEX_URL": "https://wrong.invalid/simple", "UV_PROJECT_ENVIRONMENT": str(tmp_path / "wrong"),
               "UV_PYTHON": "/wrong/python", "NETRC": str(tmp_path / "private.netrc")}
        completed = subprocess.run(
            [sys.executable, "-m", "pm.prepared_project", "--request", str(request_path)],
            cwd=Path(__file__).resolve().parents[2], env=env, text=True, capture_output=True, timeout=60,
        )
        assert completed.returncode == 0, completed.stderr
        result = json.loads((work / "result.json").read_text(encoding="utf-8"))
        assert result["status"] == "prepared"
        assert Path(result["python_executable"]).is_file()
        assert Path(result["site_packages"]).is_relative_to(work / "venv")
        assert result["distributions"] == result["import_roots"] == []
        resolved = TargetEnvironmentLock.from_record(result["resolved_lock"])
        assert resolved.recipe_hash == recipe.recipe_hash and resolved.runtime_hash == runtime
        assert (work / "source/uv.lock").read_text(encoding="utf-8") == resolved.lockfile
        results.append(result)
    assert results[0]["resolved_lock"] == results[1]["resolved_lock"]
    assert results[0]["site_packages"] != results[1]["site_packages"]
    assert not (tmp_path / "wrong").exists()
    assert (store / "facts.json").read_bytes() == original_facts
    assert dict(os.environ) == original_env

    # The same entrypoint retains a concrete failure instead of silently revising a lock.
    request["runtime_hash"] = Sha256Digest.of_bytes(b"different runtime").value
    request_path.write_text(json.dumps(request), encoding="utf-8")
    failed = subprocess.run(
        [sys.executable, "-m", "pm.prepared_project", "--request", str(request_path)],
        cwd=Path(__file__).resolve().parents[2], env=env, text=True, capture_output=True, timeout=60,
    )
    receipt = json.loads((work / "result.json").read_text(encoding="utf-8"))
    assert failed.returncode != 0 and receipt["status"] == "failed"
    assert receipt["stage"] == "requirements" and "another recipe or runtime" in receipt["message"]


def test_wheel_only_preparation_rejects_builds_and_import_hooks(tmp_path, admitted_pm_tools):
    _, _, uv = admitted_pm_tools
    project = tmp_path / "local-source"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname="source-probe"\nversion="1"\n'
        '[build-system]\nrequires=[]\nbuild-backend="probe"\nbackend-path=["."]\n', encoding="utf-8",
    )
    marker = project / "executed"
    (project / "probe.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_name('executed').write_text('build backend executed')\n"
        "raise RuntimeError('local build backend reached')\n", encoding="utf-8",
    )
    engine = PythonEnvironment(
        uv=uv, python=Path(sys.executable), destination=tmp_path / "venv", cache=tmp_path / "cache",
        env={"PATH": os.defpath}, no_config=True, no_build=True, offline=True,
    )
    engine.create()
    with pytest.raises(InstallError):
        engine.install_requirements([str(project)])
    assert not marker.exists(), "wheel-only policy executed a build backend"
    with pytest.raises(InstallError):
        replace(engine, no_build=False).install_requirements([str(project)])
    assert marker.exists(), "the control path did not reach the actual local build backend"

    wheels = tmp_path / "wheels"
    wheels.mkdir()
    _wheel(wheels, "measurement_dep")
    engine.install_requirements(["measurement-dep==1.0"], wheelhouse=wheels)
    prune_site_pth(engine.destination)
    site = site_packages(engine.destination)
    distributions, roots = _installed(site, ("measurement_dep",))
    assert distributions == [{"name": "measurement_dep", "version": "1.0"}]
    assert roots == ["measurement_dep"] and "measurement_dep" not in sys.modules
    (site / "unsafe.pth").write_text("import arbitrary_startup_code\n", encoding="utf-8")
    with pytest.raises(ValueError, match="startup hook"):
        _installed(site, ())
    (site / "unsafe.pth").unlink()
    with pytest.raises(ValueError, match="not installed"):
        _installed(site, ("missing_dependency",))
    with pytest.raises(ValueError, match="bounded"):
        _requirements(TargetEnvironmentRecipe(python="3.14", dependencies=("example>=1",)))
    with pytest.raises(ValueError, match="public PyPI"):
        _registry_lock('[[package]]\nname="example"\nsource={registry="https://other.invalid/simple"}\n')
