"""Prepare a Target Workflow's dependency environment inside a managed backend.

The host supplies paths and runtime identity. Recipe text declares requirements;
it never becomes a command or setup script. PM owns tool admission and execution.
"""
from __future__ import annotations

import argparse
from importlib import machinery, metadata
import json
import os
from pathlib import Path
import sys
import tomllib
from urllib.parse import urlsplit

from agent.episode_contracts import Sha256Digest
from episode_runtime.target_environment import TargetEnvironmentLock, TargetEnvironmentRecipe
from pm.build_operations import verified_tools
from pm.environment import PythonEnvironment, prune_site_pth
from pm.environments import site_packages


_REQUEST_FIELDS = {
    "schema_version", "recipe", "resolved_lock", "runtime_hash", "work_dir",
    "tool_store", "tool_target", "python_executable",
}
_PROJECT_NAME = "openchia-target-workflow"


def _absolute_path(value, name):
    if not isinstance(value, str) or not value or "\x00" in value or not Path(value).is_absolute():
        raise ValueError(f"{name} must be an absolute host-supplied path")
    return Path(value)


def _requirements(recipe):
    """uv is the final PEP 508 parser even on a stdlib-only preparation runtime."""
    try:
        from packaging.requirements import Requirement
    except ModuleNotFoundError:
        Requirement = None
    for text in recipe.dependencies:
        if "===" in text.partition(";")[0]:
            raise ValueError(f"dependency requires a standard bounded version: {text}")
        if Requirement is not None:
            requirement = Requirement(text)
            bounded = not requirement.url and any(
                spec.operator in {"<", "<=", "~=", "=="}
                for spec in requirement.specifier
            )
        else:
            # A marker's comparisons cannot supply the dependency's version bound.
            specifier = text.partition(";")[0]
            bounded = any(operator in specifier for operator in ("<", "~=", "=="))
        if not bounded:
            raise ValueError(f"dependency must have a bounded registry version: {text}")


def _project_text(recipe):
    return (
        "[project]\n"
        f"name = {json.dumps(_PROJECT_NAME)}\n"
        'version = "0.0.0"\n'
        f"requires-python = {json.dumps('==' + recipe.python + '.*')}\n"
        f"dependencies = {json.dumps(list(recipe.dependencies))}\n"
        "[tool.uv]\npackage = false\n"
    )


def _registry_lock(lockfile):
    """Frozen locks cannot redirect public-registry preparation to another source."""
    parsed = tomllib.loads(lockfile)
    packages = parsed.get("package")
    if not isinstance(packages, list) or not packages:
        raise ValueError("resolved lock must contain packages")
    for package in packages:
        source = package.get("source")
        if package.get("name") == _PROJECT_NAME and source == {"virtual": "."}:
            continue
        if source != {"registry": "https://pypi.org/simple"}:
            raise ValueError(f"resolved package {package.get('name')!r} is not from public PyPI")
        for artifact in [package.get("sdist"), *package.get("wheels", [])]:
            if artifact is None:
                continue
            url = urlsplit(artifact.get("url", ""))
            if (url.scheme != "https" or url.hostname != "files.pythonhosted.org"
                    or url.username or url.password or url.port not in (None, 443)):
                raise ValueError("resolved artifact must use public PyPI HTTPS storage")
            digest = artifact.get("hash", "")
            if not digest.startswith("sha256:"):
                raise ValueError("resolved artifact requires a SHA-256 hash")
            Sha256Digest(digest)


def _environment(work_dir):
    home, temporary = work_dir / "home", work_dir / "tmp"
    home.mkdir(exist_ok=True)
    temporary.mkdir(exist_ok=True)
    environment = {
        "HOME": str(home), "USERPROFILE": str(home), "PATH": os.defpath,
        "TMPDIR": str(temporary), "TMP": str(temporary), "TEMP": str(temporary),
        "XDG_DATA_HOME": str(home / "data"), "XDG_CACHE_HOME": str(home / "cache"),
        "HERMES_VERBOSE": "1", "LANG": "C.UTF-8", "TZ": "UTC",
    }
    if os.name == "nt" and "SystemRoot" in os.environ:
        environment["SystemRoot"] = os.environ["SystemRoot"]
    return environment


def _installed(site, requested_roots):
    from episode_runtime.identity import ADMITTED_LOCAL_ROOTS, SYNTHETIC_PACKAGES

    reserved = set(sys.stdlib_module_names) | set(ADMITTED_LOCAL_ROOTS) | set(SYNTHETIC_PACKAGES)
    reserved.update({"sitecustomize", "usercustomize"})
    checkout = Path(__file__).resolve().parent.parent
    reserved.update(path.stem for path in checkout.glob("*.py"))
    reserved.update(path.name for path in checkout.iterdir() if (path / "__init__.py").is_file())
    for hook in site.glob("*.pth"):
        if any(line.strip() and not line.lstrip().startswith("#")
               for line in hook.read_text(encoding="utf-8").splitlines()):
            raise ValueError(f"dependency requires an unsupported startup hook: {hook.name}")
    if any(site.glob("*.egg-link")):
        raise ValueError("editable dependency links are not supported")
    distributions, roots = [], set()
    suffixes = tuple(machinery.all_suffixes())
    for distribution in metadata.distributions(path=[str(site)]):
        name, version = distribution.metadata.get("Name"), distribution.version
        if not name or not version:
            raise ValueError("installed distribution is missing its name or exact version")
        distributions.append({"name": name, "version": version})
        if distribution.files is None:
            raise ValueError(f"installed distribution has no file inventory: {name}")
        for relative in distribution.files:
            path = Path(relative)
            if (not path.parts or path.parts[0] in {"..", "."}
                    or not path.name.endswith(suffixes) or not (site / path).is_file()):
                continue
            root = path.parts[0] if len(path.parts) > 1 else path.name.split(".")[0]
            if root.isidentifier() and root != "__pycache__":
                roots.add(root)
    if overlap := sorted(roots & reserved):
        raise ValueError(f"dependency import roots collide with runtime modules: {overlap}")
    if missing := sorted(set(requested_roots) - roots):
        raise ValueError(f"requested import roots are not installed: {missing}")
    names = [row["name"].lower().replace("_", "-").replace(".", "-") for row in distributions]
    if len(set(names)) != len(names):
        raise ValueError("installed distribution names are not unique")
    return sorted(distributions, key=lambda row: row["name"]), sorted(roots)


def prepare(request):
    """Return a receipt and exit status; retain the stage of an actionable failure."""
    stage = "request"
    try:
        if not isinstance(request, dict) or set(request) != _REQUEST_FIELDS:
            raise ValueError(f"preparation request must contain exactly {sorted(_REQUEST_FIELDS)}")
        if type(request["schema_version"]) is not int or request["schema_version"] != 1:
            raise ValueError("unsupported preparation request version")
        work_dir = _absolute_path(request["work_dir"], "work_dir")
        tool_store = _absolute_path(request["tool_store"], "tool_store")
        python = _absolute_path(request["python_executable"], "python_executable")
        recipe = TargetEnvironmentRecipe.from_record(request["recipe"])
        runtime_hash = Sha256Digest(request["runtime_hash"])
        stage = "requirements"
        _requirements(recipe)
        if not python.samefile(sys.executable):
            raise ValueError("preparation must run on the selected backend Python executable")
        if recipe.python != f"{sys.version_info.major}.{sys.version_info.minor}":
            raise ValueError(f"recipe Python {recipe.python} differs from selected backend Python "
                             f"{sys.version_info.major}.{sys.version_info.minor}")
        lock = (None if request["resolved_lock"] is None
                else TargetEnvironmentLock.from_record(request["resolved_lock"]))
        if lock is not None and (lock.recipe_hash != recipe.recipe_hash or lock.runtime_hash != runtime_hash):
            raise ValueError("resolved lock belongs to another recipe or runtime")
        stage = "tools"
        selection = verified_tools(["uv"], source_store=tool_store, target=request["tool_target"])
        environment = PythonEnvironment(
            uv=selection.entries["uv"].binary, python=python,
            destination=work_dir / "venv", cache=work_dir / "cache",
            env=_environment(work_dir), no_config=True, no_build=True, output=sys.stderr,
        )
        stage = "lock"
        source = work_dir / "source"
        source.mkdir()
        (source / "pyproject.toml").write_text(_project_text(recipe), encoding="utf-8")
        lock_path = source / "uv.lock"
        if lock is None:
            environment.lock(source)
            lock = TargetEnvironmentLock(recipe.recipe_hash, runtime_hash, lock_path.read_text(encoding="utf-8"))
        else:
            _registry_lock(lock.lockfile)
            lock_path.write_text(lock.lockfile, encoding="utf-8")
            environment.check_lock(source)
        _registry_lock(lock.lockfile)
        stage = "create"
        environment.destination.mkdir()
        environment.create()
        # uv's own venv marker is not a package requirement; the worker does not run it.
        prune_site_pth(environment.destination)
        stage = "sync"
        environment.sync(source, locked=True, no_install_project=True, no_default_groups=True,
                         compile_bytecode=False)
        if lock_path.read_text(encoding="utf-8") != lock.lockfile:
            raise ValueError("locked installation changed the frozen resolution")
        stage = "inspect"
        site = site_packages(environment.destination)
        distributions, roots = _installed(site, recipe.import_roots)
        stage = "check"
        environment.check()
        return {
            "schema_version": 1, "status": "prepared", "resolved_lock": lock.as_record(),
            "site_packages": str(site), "distributions": distributions,
            "import_roots": roots, "python_executable": str(environment.executable),
        }, 0
    except Exception as exc:
        print(f"Target Workflow preparation failed at {stage}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return {"schema_version": 1, "status": "failed", "stage": stage,
                "error_type": type(exc).__name__, "message": str(exc)}, 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    work_dir = args.request.resolve().parent
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise ValueError("preparation request must be a JSON object")
        work_dir = _absolute_path(request.get("work_dir"), "work_dir")
    except (OSError, ValueError) as exc:
        result, code = {"schema_version": 1, "status": "failed", "stage": "request",
                        "error_type": type(exc).__name__, "message": str(exc)}, 1
        print(f"Target Workflow preparation request failed: {exc}", file=sys.stderr)
    else:
        result, code = prepare(request)
    (work_dir / "result.json").write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
