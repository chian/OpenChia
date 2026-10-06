"""Prepare saved Target Workflow dependencies through the selected Run backend.

The package manager runs in that backend, not in the OpenChia host. The existing
BuildStore retains complete logs and the Duet artifact store retains resolution
and preparation records. A prepared environment is evidence, never a verdict.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import errno
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile

from agent.duet_contracts import canonical_json
from agent.episode_contracts import Sha256Digest
from .records.experiments import put_data, put_record, read_record, read_reference
from .target_environment import (
    PreparedTargetEnvironment, TargetEnvironmentLock, TargetEnvironmentRecipe,
)


@dataclass(frozen=True)
class EnvironmentPreparationFailure(RuntimeError):
    result: dict

    def __str__(self):
        return "; ".join(item["message"] for item in self.result["diagnostics"])


def _dependency_files(root):
    """Read package bytes without importing them or following package links."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("prepared dependencies must be a real directory")
    files = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs:
            if (Path(directory) / name).is_symlink():
                raise ValueError("prepared dependency directories must not be symlinks")
        dirs[:] = [name for name in dirs if name != "__pycache__"]
        for name in names:
            path = Path(directory) / name
            if path.suffix in {".pyc", ".pyo"}:
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("prepared dependency entries must be regular files")
            files[path.relative_to(root).as_posix()] = path
    return dict(sorted(files.items()))


class EnvironmentPreparationService:
    def __init__(self, *, artifacts, builds, runs, executor, network_access=True):
        if executor.run_store is not runs:
            raise ValueError("environment preparation must use the selected RunStore")
        if type(network_access) is not bool:
            raise TypeError("installation network access is a host boolean")
        self.artifacts, self.builds, self.runs, self.executor = artifacts, builds, runs, executor
        self.network_access = network_access
        self._identity = None

    @property
    def runtime_identity(self):
        if self._identity is None:
            self._identity = self.executor.inspect_runtime_identity(destination_root=self.runs.runtime_sources_root)
        return self._identity

    def describe(self):
        identity = self.runtime_identity
        manifest = json.loads((
            self.runs.runtime_sources_root / identity.runtime_source_manifest_id.value
            / "runtime_source_manifest.json"
        ).read_text(encoding="utf-8"))
        interpreter = manifest["interpreter_runtime"]
        return {
            "runtime": {
                "identity": identity.as_record(),
                "python": ".".join(map(str, interpreter["version"][:2])),
                "implementation": interpreter["implementation"],
                "version": interpreter["version"],
                "executable": str(self.executor.python_executable),
                "executable_scope": "selected_run_backend",
            },
            "libraries": {
                "base": ["Python standard library", *manifest["admitted_local_roots"]],
                "third_party": "Only the recipe's host-resolved, hash-bound dependency closure is available.",
            },
            "package_management": {
                "mechanism": "OpenChia PM, using its pinned uv in the selected execution backend",
                "declarations": ".openchia-environment.json",
                "resolution": "Host saves uv.lock with the admitted build; Runs do not resolve again.",
                "setup_instructions": "Explanatory text, not arbitrary host shell commands.",
            },
            "workspace": {"managed_root": str(self.runs.root / "target_environments")},
            "coding_diagnostics": self._diagnostic_access(),
            "installation_access": {
                "network": self.network_access,
                "registry": "https://pypi.org/simple",
                "writable": "Only the preparation's managed output and cache",
                "source_builds": False,
                "system_packages": False,
            },
            "runtime_access": {
                "dependencies": "Read-only admitted files",
                "network": "Unchanged Run egress contract; installation access grants no runtime access",
            },
            "credential_references": [],
            "credentials": "Anonymous public registry only; no ambient credentials or personal package configuration are read.",
        }

    def _diagnostic_access(self):
        from .executor import SystemdRunExecutor

        direct = isinstance(self.executor, SystemdRunExecutor)
        return {
            "mode": "direct_interpreter" if direct else "selected_backend_required",
            "direct_interpreter_available": direct,
            "guidance": (
                "The prepared interpreter may run coding diagnostics in the coding workspace. "
                "These observations are not independent validation or credit."
                if direct else
                "The prepared environment belongs to the selected Run backend, not the coding shell. "
                "Do not execute its interpreter or add its packages to the host Python. "
                "Submit candidate edits for independent validation through OpenChia's existing Run backend."
            ),
        }

    def _resolution(self, duet_id, recipe):
        return read_record(
            self.artifacts, "environment_resolution", owner_duet_id=duet_id,
            recipe_hash=recipe.recipe_hash.value, runtime_hash=self.runtime_identity.content_hash.value,
        )

    def _logs(self, outcome):
        refs = []
        for stream in ("stdout", "stderr"):
            payload = str(outcome.get(stream, "")).encode("utf-8")
            refs.append({"stream": stream, "content_hash": self.builds.put_blob(payload).value, "bytes": len(payload)})
        return refs

    def _record(self, result, *, duet_id, candidate_ref, recipe):
        access = self._diagnostic_access()
        if result["status"] != "prepared":
            access = {
                "mode": "unavailable", "direct_interpreter_available": False,
                "guidance": "No prepared diagnostic interpreter is available. Repair the saved recipe using the preparation diagnostics.",
            }
        result = {**result, "diagnostic_execution": access}
        reference = put_data(self.artifacts, duet_id, "environment_preparation", {
            "candidate_ref": candidate_ref,
            "recipe": recipe.as_record() if isinstance(recipe, TargetEnvironmentRecipe) else recipe,
            "runtime": self.runtime_identity.as_record(),
            "installation_access": self.describe()["installation_access"],
            **result,
        })
        return {**result, "preparation_ref": reference}

    @staticmethod
    def _failure(stage, exc, *, logs=(), resolved_lock=None):
        return {
            "status": "failed", "prepared": None, "resolved_lock": resolved_lock,
            "diagnostics": [{"stage": stage, "error_type": type(exc).__name__, "message": str(exc)}],
            "log_refs": list(logs), "python_executable": None, "site_packages": None,
        }

    def _cached(self, resolution, lock):
        prepared = PreparedTargetEnvironment.from_record(resolution["prepared"])
        if (prepared.lock_hash != lock.content_hash or prepared.recipe_hash != lock.recipe_hash
                or prepared.runtime_hash != lock.runtime_hash):
            raise ValueError("cached dependency closure belongs to another saved lock")
        root = self.runs.root / "target_environments" / prepared.environment_id.value
        record = root / "TARGET_ENVIRONMENT.json"
        if not record.is_file() or record.is_symlink():
            return None
        if json.loads(record.read_text(encoding="utf-8")) != prepared.as_record():
            raise ValueError("cached environment record differs from its identity")
        actual = _dependency_files(root / "site-packages")
        if set(actual) != set(prepared.file_hashes) or any(
            Sha256Digest.of_bytes(path.read_bytes()) != prepared.file_hashes[name]
            for name, path in actual.items()
        ):
            raise ValueError("cached environment files differ from the saved recipe/runtime resolution")
        diagnostic = resolution.get("diagnostic_environment")
        if diagnostic is None:
            return None
        try:
            current = self._diagnostic_environment(
                Path(diagnostic["root"]).parent, diagnostic["python_executable"], diagnostic["site_packages"],
            )
        except (OSError, ValueError):
            return None
        if current != diagnostic:
            return None
        return {
            "status": "prepared", "prepared": prepared.as_record(), "resolved_lock": lock.as_record(),
            "diagnostics": [], "log_refs": resolution["log_refs"],
            "python_executable": diagnostic["python_executable"]
            if self._diagnostic_access()["direct_interpreter_available"] else None,
            "site_packages": str(root / "site-packages"),
            "diagnostic_environment": diagnostic,
            "cache_reused": True,
        }

    def _cached_preparation(self, duet_id, lock):
        """The immutable lock survives disposable coding environments and fresh Runs."""
        cursor = None
        while True:
            page = self.artifacts.artifact_page(
                duet_id=duet_id, kinds=("experiment.environment_preparation.v1",), after=cursor,
            )
            for row in page["items"]:
                value = row["record"]
                if value.get("status") != "prepared" or value["resolved_lock"]["content_hash"] != lock.content_hash.value:
                    continue
                read_reference(self.artifacts, {
                    "artifact_id": row["artifact_id"], "content_hash": row["content_hash"],
                }, duet_id)
                cached = self._cached(value, lock)
                if cached is not None:
                    return cached
            cursor = page["next_cursor"]
            if cursor is None:
                return None

    def _diagnostic_environment(self, work, executable, site):
        """Authenticate the writable coding venv separately from published Run bytes."""
        base = (self.runs.root / "target_environments").resolve()
        if work.is_symlink() or work.parent.resolve() != base or not work.name.startswith("preparation-"):
            raise ValueError("diagnostic environment is outside a managed preparation")
        root = work / "venv"
        executable, site = Path(executable), Path(site)
        if (root.is_symlink() or not root.is_dir() or not executable.is_absolute()
                or not executable.is_relative_to(root) or not site.is_absolute()
                or not site.resolve().is_relative_to(root.resolve())):
            raise ValueError("package manager interpreter or packages escape the prepared venv")
        if not (root / "pyvenv.cfg").is_file() or not executable.parent.resolve().is_relative_to(root.resolve()):
            raise ValueError("prepared interpreter has no managed venv configuration")
        files, links = {}, {}
        approved_python = self.executor.python_executable
        for directory, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if name != "__pycache__"]
            for name in [*dirs, *names]:
                path = Path(directory) / name
                relative = path.relative_to(root).as_posix()
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode):
                    target = os.readlink(path)
                    destination = Path(os.path.abspath(path.parent / target))
                    if destination != approved_python and not destination.is_relative_to(root):
                        raise ValueError("diagnostic venv link escapes to an unapproved runtime")
                    links[relative] = target
                elif stat.S_ISREG(info.st_mode):
                    if path.suffix not in {".pyc", ".pyo"}:
                        files[relative] = Sha256Digest.of_bytes(path.read_bytes()).value
                elif not stat.S_ISDIR(info.st_mode):
                    raise ValueError("diagnostic venv contains a non-file entry")
        if executable.relative_to(root).as_posix() not in files | links:
            raise ValueError("package manager returned a missing interpreter")
        return {
            "root": str(root), "python_executable": str(executable), "site_packages": str(site),
            "file_hashes": files, "symlinks": links,
        }

    def _request(self, recipe, lock):
        from pm.build_operations import verified_tools
        from pm.environments import store_root
        from pm.store import current_target

        base = self.runs.root / "target_environments"
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        work = Path(tempfile.mkdtemp(prefix="preparation-", dir=base))
        (work / "tmp").mkdir(mode=0o700)
        (work / "home").mkdir(mode=0o700)
        repo = self.executor.repository_root.resolve()
        tools = store_root(repo)
        target = current_target()
        # The existing PM lookup verifies an installed tool, never bootstraps
        # packages or changes OpenChia's own environment on this path.
        verified_tools(["uv"], source_store=tools, target=target)
        if hasattr(self.executor, "runtime") and not target.startswith("linux-"):
            raise ValueError("the container backend needs a Linux-compatible PM tool bundle; host tools are not a fallback")
        request = {
            "schema_version": 1, "recipe": recipe.as_record(),
            "resolved_lock": None if lock is None else lock.as_record(),
            "runtime_hash": self.runtime_identity.content_hash.value,
            "work_dir": str(work), "tool_store": str(tools), "tool_target": target,
            "python_executable": str(self.executor.python_executable),
        }
        request_path = work / "request.json"
        request_path.write_text(canonical_json(request), encoding="utf-8")
        # Explicit repository source is the trusted PM implementation, not
        # site-packages inherited from the host or the coding agent.
        program = (
            "import runpy,sys;sys.path.insert(0,sys.argv.pop(1));"
            "runpy.run_module('pm.prepared_project',run_name='__main__')"
        )
        command = (str(self.executor.python_executable), "-I", "-S", "-B", "-c", program,
                   str(repo), "--request", str(request_path))
        environment = {
            "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "HERMES_VERBOSE": "1", "HERMES_HOME": str(work / "home"),
            "TMPDIR": str(work / "tmp"), "TMP": str(work / "tmp"), "TEMP": str(work / "tmp"),
            "UV_NO_BUILD": "1", "UV_LINK_MODE": "copy", "UV_DEFAULT_INDEX": "https://pypi.org/simple",
        }
        return work, command, ((str(repo), str(repo)), (str(tools), str(tools))), environment

    def _publish(self, recipe, result, work, logs):
        lock = TargetEnvironmentLock.from_record(result["resolved_lock"])
        if lock.recipe_hash != recipe.recipe_hash or lock.runtime_hash != self.runtime_identity.content_hash:
            raise ValueError("package manager returned another recipe/runtime resolution")
        site = Path(result["site_packages"])
        if not site.resolve().is_relative_to(work.resolve()):
            raise ValueError("package manager output escapes the managed preparation")
        diagnostic = self._diagnostic_environment(work, result["python_executable"], site)
        files = _dependency_files(site)
        prepared = PreparedTargetEnvironment(
            recipe_hash=recipe.recipe_hash, runtime_hash=lock.runtime_hash, lock_hash=lock.content_hash,
            import_roots=result["import_roots"], distributions=result["distributions"],
            file_hashes={name: Sha256Digest.of_bytes(path.read_bytes()) for name, path in files.items()},
        )
        root = self.runs.root / "target_environments" / prepared.environment_id.value
        stage = Path(tempfile.mkdtemp(prefix="publication-", dir=root.parent))
        for name, source in files.items():
            path = stage / "site-packages" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, path)
        (stage / "site-packages").mkdir(exist_ok=True)
        (stage / "TARGET_ENVIRONMENT.json").write_text(canonical_json(prepared.as_record()), encoding="utf-8")
        try:
            stage.rename(root)
        except OSError as exc:
            if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                raise
            # Publication races preserve the existing immutable tree and then
            # independently verify it below; never overwrite a cached package.
            shutil.rmtree(stage)
        value = {
            "status": "prepared", "prepared": prepared.as_record(), "resolved_lock": lock.as_record(),
            "diagnostics": [], "log_refs": logs,
            "python_executable": result["python_executable"]
            if self._diagnostic_access()["direct_interpreter_available"] else None,
            "site_packages": str(root / "site-packages"), "cache_reused": False,
            "diagnostic_environment": diagnostic,
        }
        if self._cached(value, lock) is None:
            raise ValueError("prepared coding environment changed during publication")
        return value

    async def prepare_manifest(self, manifest, *, duet_id, fresh=False):
        if manifest.environment_recipe is None:
            return None
        if manifest.environment_lock is None:
            raise EnvironmentPreparationFailure(self._failure(
                "resolution", ValueError("an admitted build requires a saved dependency lock before a Run"),
            ))
        result = await self.prepare(
            manifest.environment_recipe, duet_id=duet_id,
            resolved_lock=manifest.environment_lock, fresh=fresh,
        )
        if result["status"] != "prepared":
            raise EnvironmentPreparationFailure(result)
        return PreparedTargetEnvironment.from_record(result["prepared"])

    async def prepare(self, recipe, *, duet_id, candidate_ref=None, resolved_lock=None, fresh=False):
        await asyncio.to_thread(lambda: self.runtime_identity)
        stage, logs, lock = "recipe", [], None
        try:
            recipe = recipe if isinstance(recipe, TargetEnvironmentRecipe) else TargetEnvironmentRecipe.from_record(recipe)
            lock = resolved_lock if isinstance(resolved_lock, TargetEnvironmentLock) else (
                TargetEnvironmentLock.from_record(resolved_lock) if resolved_lock is not None else None
            )
            previous = await asyncio.to_thread(self._resolution, duet_id, recipe)
            if previous is not None:
                saved = TargetEnvironmentLock.from_record(previous["record"]["resolved_lock"])
                if lock is not None and lock.content_hash != saved.content_hash:
                    raise ValueError("provided dependency lock differs from the saved recipe/runtime resolution")
                lock = saved
            if lock is not None and (
                lock.recipe_hash != recipe.recipe_hash or lock.runtime_hash != self.runtime_identity.content_hash
            ):
                raise ValueError("saved environment resolution does not match the recipe and selected runtime")
            if lock is not None and not fresh:
                cached = await asyncio.to_thread(self._cached_preparation, duet_id, lock)
                if cached is not None:
                    return await asyncio.to_thread(self._record, cached, duet_id=duet_id, candidate_ref=candidate_ref, recipe=recipe)
            stage = "preparation"
            work, command, mounts, environment = await asyncio.to_thread(self._request, recipe, lock)
            outcome = await self.executor.prepare_environment(
                command, read_only_paths=mounts, writable_directory=work,
                environment=environment, network_access=self.network_access,
            )
            logs = await asyncio.to_thread(self._logs, outcome)
            path = work / "result.json"
            result = json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8")) if path.is_file() else None
            if outcome["returncode"] != 0 or result is None or result.get("status") != "prepared":
                detail = result if isinstance(result, dict) else {
                    "stage": stage, "error_type": "PreparationProcessFailed",
                    "message": f"Backend preparation exited {outcome['returncode']}: {str(outcome.get('stderr', ''))[-4000:]}",
                }
                value = self._failure(detail.get("stage", stage), RuntimeError(detail["message"]), logs=logs)
                value["diagnostics"][0]["error_type"] = detail.get("error_type", "PreparationProcessFailed")
            else:
                stage = "publication"
                value = await asyncio.to_thread(self._publish, recipe, result, work, logs)
                if previous is None:
                    await asyncio.to_thread(
                        put_record, self.artifacts, "environment_resolution", duet_id=duet_id,
                        owner_duet_id=duet_id, recipe_hash=recipe.recipe_hash.value,
                        runtime_hash=self.runtime_identity.content_hash.value,
                        record={"resolved_lock": value["resolved_lock"]},
                    )
        except (ValueError, OSError, RuntimeError, TypeError, KeyError) as exc:
            value = self._failure(stage, exc, logs=logs, resolved_lock=None if lock is None else lock.as_record())
        return await asyncio.to_thread(self._record, value, duet_id=duet_id, candidate_ref=candidate_ref, recipe=recipe)
