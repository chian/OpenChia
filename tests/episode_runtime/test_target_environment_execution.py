"""Target dependencies stay out of host imports and use the actual backend."""

import ast
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agent.duet_contracts import canonical_json
from agent.episode_contracts import Sha256Digest
from episode_runtime.bootstrap import BootstrapError, _ClosedImportFinder
from episode_runtime.environment_runtime import verify_target_environment
from episode_runtime.contracts import RuntimePolicy
from episode_runtime.executor import make_systemd_run_executor_factory
from episode_runtime.identity import RuntimeIdentityError
from episode_runtime.linker import _preload_declared_imports
from episode_runtime.landlock import landlock_abi7_policy_hash
from episode_runtime.seccomp import seccomp_policy_hash
from episode_runtime.target_environment import PreparedTargetEnvironment


def test_dependency_read_policy_switches_as_one_registered_contract():
    default = RuntimePolicy()
    with pytest.raises(ValueError, match="another Landlock policy"):
        replace(default, dependency_reads=True)
    dependency = replace(
        default, dependency_reads=True,
        landlock_policy_hash=landlock_abi7_policy_hash(dependency_reads=True),
        seccomp_policy_hash=seccomp_policy_hash(dependency_reads=True),
    )
    assert RuntimePolicy.from_record(dependency.as_record()) == dependency
    with pytest.raises(ValueError, match="another Landlock policy"):
        replace(dependency, dependency_reads=False)
    restored = replace(
        dependency, dependency_reads=False,
        landlock_policy_hash=landlock_abi7_policy_hash(), seccomp_policy_hash=seccomp_policy_hash(),
    )
    assert restored == default
    assert dependency.content_hash != default.content_hash


def test_dependency_imports_are_deferred_verified_and_include_namespace_children(tmp_path, monkeypatch):
    sources = {"target_namespace/child.py": b"answer = 42\n"}
    digest = Sha256Digest.of_bytes(b"frozen recipe/runtime/lock")
    prepared = PreparedTargetEnvironment(
        recipe_hash=digest, runtime_hash=digest, lock_hash=digest,
        import_roots=("target_namespace",), distributions=(),
        file_hashes={name: Sha256Digest.of_bytes(body) for name, body in sources.items()},
    )
    package = tmp_path / prepared.environment_id.value
    site = package / "site-packages"
    for name, body in sources.items():
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    (package / "TARGET_ENVIRONMENT.json").write_text(canonical_json(prepared.as_record()), encoding="utf-8")
    assert verify_target_environment(package, prepared) == site
    monkeypatch.syspath_prepend(str(site))
    namespace = "target_namespace"
    assert namespace not in sys.modules
    deferred = _preload_declared_imports(
        ast.parse("from target_namespace import child"), excluded_roots=frozenset({namespace}),
    )
    assert deferred == ((namespace, ("child",)),)
    assert namespace not in sys.modules
    finder = _ClosedImportFinder(package=tmp_path, local_hashes={}, stdlib=tmp_path, stdlib_files={})
    finder.admit_dependencies(site, {name: value.value for name, value in prepared.file_hashes.items()})
    with pytest.raises(BootstrapError, match="before worker confinement"):
        finder.find_spec(namespace)
    finder.enable_dependencies()
    parent = finder.find_spec(namespace)
    child = finder.find_spec(f"{namespace}.child", parent.submodule_search_locations)
    loaded = {}
    exec(child.loader.get_code(f"{namespace}.child"), loaded)
    assert loaded["answer"] == 42
    (site / "target_namespace/child.py").write_text("answer = 99\n", encoding="utf-8")
    with pytest.raises(BootstrapError, match="changed after bootstrap verification"):
        child.loader.get_code(f"{namespace}.child")
    with pytest.raises(RuntimeIdentityError, match="differs from prepared environment"):
        verify_target_environment(package, prepared)


@pytest.mark.platforms("linux")
@pytest.mark.asyncio
async def test_preparation_uses_native_backend_with_only_explicit_environment(tmp_path, monkeypatch, run_store):
    runtime_dir = Path("/run/user") / str(os.getuid())
    if (runtime_dir / "bus").exists():
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir / 'bus'}")
    status = subprocess.run(["systemctl", "--user", "is-system-running"], capture_output=True, timeout=5)
    if status.returncode != 0:
        pytest.skip("native preparation requires a running user systemd manager")
    store, _, _ = run_store
    executor = make_systemd_run_executor_factory(repository_root=Path(__file__).resolve().parents[2])(store)
    output = tmp_path / "preparation"
    output.mkdir()
    outside = tmp_path / "not-writable"
    outside.write_text("preserved", encoding="utf-8")
    monkeypatch.setenv("OPENCHIA_PREPARATION_PRIVATE_SENTINEL", "must not propagate")
    script = """
import json, os, pathlib, sys
assert os.environ == {'EXPECTED_SETTING': 'explicit', 'LANG': 'C.UTF-8'}
pathlib.Path('prepared.txt').write_text('prepared', encoding='utf-8')
try:
    pathlib.Path(sys.argv[1]).write_text('unauthorized', encoding='utf-8')
except OSError:
    pass
else:
    raise AssertionError('preparation escaped its writable directory')
print(json.dumps({'environment': dict(os.environ), 'cwd': os.getcwd()}), flush=True)
print('complete diagnostic stderr', file=sys.stderr, flush=True)
raise SystemExit(7)
"""
    result = await asyncio.wait_for(executor.prepare_environment(
        (str(executor.python_executable), "-I", "-S", "-c", script, str(outside)),
        read_only_paths=((str(outside), str(outside)),), writable_directory=output,
        environment={"EXPECTED_SETTING": "explicit", "LANG": "C.UTF-8"}, network_access=False,
    ), 30)
    assert result["returncode"] == 7, result
    assert result["backend"] == "systemd"
    facts = json.loads(result["stdout"])
    assert facts == {"environment": {"EXPECTED_SETTING": "explicit", "LANG": "C.UTF-8"}, "cwd": str(output)}
    assert "complete diagnostic stderr" in result["stderr"]
    assert (output / "prepared.txt").read_text(encoding="utf-8") == "prepared"
    assert outside.read_text(encoding="utf-8") == "preserved"
