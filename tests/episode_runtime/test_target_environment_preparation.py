"""Native PM preparation and cache repair, without model output or a substitute runner."""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agent.duet_contracts import content_id
from agent.duet_store import DuetStore
from episode_builder.store import BuildStore
from episode_runtime.executor import make_systemd_run_executor_factory
from episode_runtime.store import RunStore
from episode_runtime.target_environment import TargetEnvironmentRecipe
from episode_runtime.target_environment_preparation import EnvironmentPreparationService
from tests.pm._fixtures import admitted_pm_tools as admitted_pm_tools


@pytest.mark.platforms("linux")
@pytest.mark.asyncio
async def test_native_recipe_preparation_fresh_rebuild_and_mutated_diagnostic_cache(
    tmp_path, monkeypatch, admitted_pm_tools,
):
    if os.environ.get("HERMES_RUN_E2E") != "1":
        pytest.skip("set HERMES_RUN_E2E=1 for public-PyPI preparation through native systemd")
    runtime_dir = Path("/run/user") / str(os.getuid())
    if (runtime_dir / "bus").exists():
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir / 'bus'}")
    status = subprocess.run(["systemctl", "--user", "is-system-running"], capture_output=True, timeout=5)
    if status.returncode != 0:
        pytest.skip("native preparation requires the running user systemd manager")
    tools, _, _ = admitted_pm_tools
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(tools))
    runs, builds = RunStore(tmp_path / "runs"), BuildStore(tmp_path / "builds")
    artifacts = DuetStore(tmp_path / "authority.sqlite3")
    duet_id = content_id("duet", {"test": "native-dependency-preparation"}).value
    artifacts.create_duet(duet_id=duet_id, identity={}, policy={}, state="design")
    executor = make_systemd_run_executor_factory(repository_root=Path(__file__).resolve().parents[2])(runs)
    service = EnvironmentPreparationService(artifacts=artifacts, builds=builds, runs=runs, executor=executor)
    recipe = TargetEnvironmentRecipe(
        python=f"{sys.version_info.major}.{sys.version_info.minor}",
        dependencies=("humanize==4.13.0",), import_roots=("humanize",),
    )
    probe = subprocess.run(
        [str(executor.python_executable), "-I", "-S", "-c",
         "import importlib.util; assert importlib.util.find_spec('humanize') is None"],
        capture_output=True, timeout=5,
    )
    assert probe.returncode == 0, probe.stderr
    try:
        initial = await asyncio.wait_for(service.prepare(recipe, duet_id=duet_id), 120)
        assert initial["status"] == "prepared", initial
        assert service.describe()["coding_diagnostics"]["direct_interpreter_available"]
        assert initial["diagnostic_execution"]["mode"] == "direct_interpreter"
        assert {"name": "humanize", "version": "4.13.0"} in initial["prepared"]["distributions"]
        assert "humanize" not in sys.modules
        cached = await service.prepare(recipe, duet_id=duet_id)
        assert cached["cache_reused"] and cached["python_executable"] == initial["python_executable"]
        fresh = await asyncio.wait_for(service.prepare(recipe, duet_id=duet_id, fresh=True), 120)
        assert fresh["status"] == "prepared", fresh
        assert not fresh["cache_reused"] and fresh["python_executable"] != initial["python_executable"]
        assert fresh["resolved_lock"] == initial["resolved_lock"]
        assert fresh["prepared"] == initial["prepared"]
        # A coding session can mutate its own venv; it must not become cached Run evidence.
        for result in (initial, fresh):
            site = Path(result["diagnostic_environment"]["site_packages"])
            (site / "humanize/__init__.py").write_text("raise RuntimeError('changed coding environment')\n", encoding="utf-8")
        repaired = await asyncio.wait_for(service.prepare(recipe, duet_id=duet_id), 120)
        assert repaired["status"] == "prepared" and not repaired["cache_reused"], repaired
        assert repaired["prepared"] == initial["prepared"]
        reused = await service.prepare(recipe, duet_id=duet_id)
        assert reused["cache_reused"] and reused["python_executable"] == repaired["python_executable"]
        output = tmp_path / "probe"
        output.mkdir()
        package = Path(repaired["site_packages"])
        actual = await executor.prepare_environment(
            (str(executor.python_executable), "-I", "-S", "-c",
             "import sys;sys.path.insert(0,sys.argv[1]);import humanize;print(humanize.intcomma(1234567))",
             str(package)),
            read_only_paths=((str(package), str(package)),), writable_directory=output,
            environment={"LANG": "C.UTF-8"}, network_access=False,
        )
        assert actual["returncode"] == 0 and actual["stdout"].strip() == "1,234,567", actual
        rows = artifacts.artifacts_by_kind(duet_id=duet_id, kind="experiment.environment_preparation.v1")
        assert all(row["record"]["log_refs"] for row in rows)
        assert json.loads((package.parent / "TARGET_ENVIRONMENT.json").read_text(encoding="utf-8")) == repaired["prepared"]
    finally:
        artifacts.close()
