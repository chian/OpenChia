"""Materialization and verification of the worker's executable byte closure."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import sys
import sysconfig
import tempfile
from types import MappingProxyType
from typing import Mapping

from agent.duet_contracts import canonical_json
from agent.episode_contracts import Sha256Digest

from .interpreter import current_interpreter_executable
from .contracts import (
    InterpreterRuntimeIdentity,
    RuntimeIdentity,
    RuntimeSourceManifest,
    RUNTIME_WORKER_ENTRYPOINT,
)


WORKER_ENTRYPOINT = RUNTIME_WORKER_ENTRYPOINT
BOOTSTRAP_SOURCE_PATH = "episode_runtime/bootstrap.py"
RUNTIME_MANIFEST_FILENAME = "runtime_source_manifest.json"

ADMITTED_LOCAL_ROOTS = (
    "function_library",
    "handoff_library",
    "llm_call_library",
    "method_loop",
    "numeric_control_library",
    "question_table_goal_library",
)
SYNTHETIC_PACKAGES = (
    "agent",
    "episode_builder",
    "episode_library",
    "episode_runtime",
    "iterative_episode_refiner",
)
_SELECTED_LOCAL_SOURCES = (
    "agent/duet_contracts.py",
    "agent/episode_contract_models.py",
    "agent/episode_contracts.py",
    "iterative_episode_refiner/contracts.py",
    "episode_builder/_contract_base.py",
    "episode_builder/_contract_plan.py",
    "episode_builder/_contract_chain.py",
    "episode_builder/declaration.py",
    "episode_library/models.py",
    BOOTSTRAP_SOURCE_PATH,
    "episode_runtime/broker.py",
    "episode_runtime/contracts.py",
    "episode_runtime/identity.py",
    "episode_runtime/landlock.py",
    "episode_runtime/linker.py",
    "episode_runtime/protocol.py",
    "episode_runtime/seccomp.py",
    "episode_runtime/worker.py",
)
_IGNORED_STDLIB_DIRECTORIES = frozenset(
    {"__pycache__", "site-packages", "dist-packages"}
)
_IGNORED_STDLIB_SUFFIXES = frozenset({".pyc", ".pyo"})


class RuntimeIdentityError(RuntimeError):
    """Runtime bytes or filesystem types differ from their admitted identity."""


def _relative_path(value: object) -> str:
    if (
        not isinstance(value, str)
        or value.startswith("/")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("source paths must be normalized relative POSIX paths")
    return value


def _read_exact_file(path: Path, name: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise RuntimeIdentityError(f"cannot open exact {name}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size < 0:
            raise RuntimeIdentityError(f"{name} is not a regular file")
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise RuntimeIdentityError(f"{name} ended while being read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise RuntimeIdentityError(f"{name} grew while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _walk_regular_files(
    root: Path,
    *,
    python_only: bool,
    ignored_directories: frozenset[str] = frozenset(),
    ignored_suffixes: frozenset[str] = frozenset(),
    forbidden_directories: frozenset[str] = frozenset(),
    allow_file_symlinks: bool = False,
) -> tuple[tuple[str, Path], ...]:
    """Walk without following links and return normalized relative file paths."""

    if root.is_symlink() or not root.is_dir():
        raise RuntimeIdentityError(f"source root is not a real directory: {root}")
    result: list[tuple[str, Path]] = []
    pending = [(root, "")]
    while pending:
        directory, prefix = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise RuntimeIdentityError(
                f"cannot inspect source directory {directory}"
            ) from exc
        for entry in entries:
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise RuntimeIdentityError(
                    f"cannot inspect source entry {relative!r}"
                ) from exc
            if stat.S_ISLNK(info.st_mode):
                if not allow_file_symlinks:
                    raise RuntimeIdentityError(
                        f"source entry {relative!r} is a symlink"
                    )
                try:
                    target_info = Path(entry.path).resolve(strict=True).stat()
                except OSError as exc:
                    raise RuntimeIdentityError(
                        f"stdlib link {relative!r} has no exact target"
                    ) from exc
                if not stat.S_ISREG(target_info.st_mode):
                    raise RuntimeIdentityError(
                        f"stdlib link {relative!r} does not resolve to a regular file"
                    )
                if python_only and not relative.endswith(".py"):
                    continue
                if Path(relative).suffix not in ignored_suffixes:
                    result.append((_relative_path(relative), Path(entry.path)))
                continue
            if stat.S_ISDIR(info.st_mode):
                if entry.name in forbidden_directories:
                    raise RuntimeIdentityError(
                        f"source directory {relative!r} is forbidden"
                    )
                if entry.name not in ignored_directories:
                    pending.append((Path(entry.path), relative))
                continue
            if not stat.S_ISREG(info.st_mode):
                raise RuntimeIdentityError(
                    f"source entry {relative!r} is not regular"
                )
            if python_only and not relative.endswith(".py"):
                continue
            if Path(relative).suffix in ignored_suffixes:
                continue
            result.append((_relative_path(relative), Path(entry.path)))
    return tuple(sorted(result))


def _stdlib_entry_digest(path: Path, name: str) -> Sha256Digest:
    try:
        info = path.lstat()
    except OSError as exc:
        raise RuntimeIdentityError(f"cannot inspect exact {name}") from exc
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(path)
        resolved = path.resolve(strict=True)
        payload = _read_exact_file(resolved, f"{name} link target")
        return Sha256Digest.of_bytes(
            b"stdlib-symlink\0"
            + target.encode("utf-8", errors="strict")
            + b"\0"
            + payload
        )
    return Sha256Digest.of_bytes(_read_exact_file(path, name))


def _current_executable(path: str | Path | None = None) -> Path:
    selected = Path(
        current_interpreter_executable() if path is None else path
    ).expanduser()
    if selected.is_symlink():
        raise RuntimeIdentityError("Python executable cannot be a symlink")
    result = selected.resolve(strict=True)
    if not result.is_file():
        raise RuntimeIdentityError("Python executable is not a real regular file")
    return result


def inspect_interpreter_runtime(
    *,
    python_executable: str | Path | None = None,
) -> InterpreterRuntimeIdentity:
    """Hash the interpreter and every importable non-site stdlib file."""

    executable = _current_executable(python_executable)
    stdlib = Path(sysconfig.get_path("stdlib")).resolve(strict=True)
    stdlib_hashes = {
        relative: _stdlib_entry_digest(path, f"stdlib file {relative!r}")
        for relative, path in _walk_regular_files(
            stdlib,
            python_only=False,
            ignored_directories=_IGNORED_STDLIB_DIRECTORIES,
            ignored_suffixes=_IGNORED_STDLIB_SUFFIXES,
            allow_file_symlinks=True,
        )
    }
    shared_hashes: dict[str, Sha256Digest] = {}
    library_dir = sysconfig.get_config_var("LIBDIR")
    for variable in ("LDLIBRARY", "INSTSONAME"):
        filename = sysconfig.get_config_var(variable)
        if (
            not isinstance(library_dir, str)
            or not isinstance(filename, str)
            or not filename
        ):
            continue
        candidate = (Path(library_dir) / filename).resolve(strict=False)
        if candidate.is_file():
            key = _relative_path(f"{variable.lower()}/{candidate.name}")
            shared_hashes[key] = Sha256Digest.of_bytes(
                _read_exact_file(
                    candidate,
                    f"interpreter shared library {candidate.name!r}",
                )
            )
    return InterpreterRuntimeIdentity(
        implementation=sys.implementation.name,
        version=(
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        ),
        cache_tag=sys.implementation.cache_tag or "none",
        executable_hash=Sha256Digest.of_bytes(
            _read_exact_file(executable, "Python executable")
        ),
        stdlib_file_hashes=MappingProxyType(stdlib_hashes),
        shared_library_hashes=MappingProxyType(shared_hashes),
    )


def verify_interpreter_runtime(
    identity: InterpreterRuntimeIdentity,
    *,
    python_executable: str | Path | None = None,
) -> None:
    """Fail unless the running interpreter and complete stdlib match identity."""

    if not isinstance(identity, InterpreterRuntimeIdentity):
        raise TypeError("identity must be an InterpreterRuntimeIdentity")
    actual = inspect_interpreter_runtime(python_executable=python_executable)
    if actual.as_record() != identity.as_record():
        raise RuntimeIdentityError(
            "interpreter or standard-library bytes differ from registration"
        )


def _local_source_paths(repository_root: Path) -> tuple[tuple[str, Path], ...]:
    selected: dict[str, Path] = {}
    for relative in _SELECTED_LOCAL_SOURCES:
        normalized = _relative_path(relative)
        selected[normalized] = repository_root / normalized
    for root_name in ADMITTED_LOCAL_ROOTS:
        for relative, path in _walk_regular_files(
            repository_root / root_name,
            python_only=True,
        ):
            selected[f"{root_name}/{relative}"] = path
    return tuple(sorted(selected.items()))


def inspect_runtime_source_manifest(
    *,
    repository_root: str | Path,
    python_executable: str | Path | None = None,
) -> RuntimeSourceManifest:
    """Inspect the complete admitted local implementation closure."""

    supplied_root = Path(repository_root).expanduser()
    if supplied_root.is_symlink():
        raise ValueError("repository_root cannot be a symlink")
    root = supplied_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repository_root must be a real directory")
    hashes = {
        relative: Sha256Digest.of_bytes(
            _read_exact_file(path, f"local source {relative!r}")
        )
        for relative, path in _local_source_paths(root)
    }
    return RuntimeSourceManifest(
        worker_entrypoint=WORKER_ENTRYPOINT,
        bootstrap_path=BOOTSTRAP_SOURCE_PATH,
        local_source_hashes=MappingProxyType(hashes),
        synthetic_packages=SYNTHETIC_PACKAGES,
        admitted_local_roots=ADMITTED_LOCAL_ROOTS,
        interpreter_runtime=inspect_interpreter_runtime(
            python_executable=python_executable
        ),
    )


def runtime_identity_from_manifest(
    manifest: RuntimeSourceManifest,
) -> RuntimeIdentity:
    if not isinstance(manifest, RuntimeSourceManifest):
        raise TypeError("manifest must be a RuntimeSourceManifest")
    return RuntimeIdentity(
        worker_entrypoint=manifest.worker_entrypoint,
        runtime_source_manifest_id=manifest.manifest_id,
        runtime_source_manifest_hash=manifest.content_hash,
        interpreter_runtime_id=manifest.interpreter_runtime.interpreter_id,
        interpreter_runtime_hash=manifest.interpreter_runtime.content_hash,
    )


def _make_read_only(path: Path) -> None:
    for current_root, directories, files in os.walk(path, topdown=False):
        for filename in files:
            os.chmod(
                Path(current_root) / filename,
                0o444,
                follow_symlinks=False,
            )
        for dirname in directories:
            os.chmod(
                Path(current_root) / dirname,
                0o555,
                follow_symlinks=False,
            )
    os.chmod(path, 0o555, follow_symlinks=False)


def _discard_temporary_tree(path: Path) -> None:
    if not path.exists():
        return
    for current_root, directories, files in os.walk(path, topdown=False):
        os.chmod(current_root, 0o700, follow_symlinks=False)
        for filename in files:
            os.chmod(
                Path(current_root) / filename,
                0o600,
                follow_symlinks=False,
            )
        for dirname in directories:
            os.chmod(
                Path(current_root) / dirname,
                0o700,
                follow_symlinks=False,
            )
    shutil.rmtree(path)


def materialize_runtime_source_package(
    *,
    repository_root: str | Path,
    destination_root: str | Path,
    python_executable: str | Path | None = None,
) -> tuple[RuntimeIdentity, Path]:
    """Publish a fresh immutable package built from verified local source bytes."""

    supplied_root = Path(repository_root).expanduser()
    if supplied_root.is_symlink():
        raise ValueError("repository_root cannot be a symlink")
    root = supplied_root.resolve(strict=True)
    supplied_destination = Path(destination_root).expanduser()
    if supplied_destination.is_symlink():
        raise RuntimeIdentityError(
            "runtime source destination cannot be a symlink"
        )
    destination = supplied_destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise RuntimeIdentityError(
            "runtime source destination must be a real directory"
        )
    manifest = inspect_runtime_source_manifest(
        repository_root=root,
        python_executable=python_executable,
    )
    identity = runtime_identity_from_manifest(manifest)
    published = destination / manifest.manifest_id.value
    if published.is_symlink():
        raise RuntimeIdentityError(
            "runtime source publication path cannot be a symlink"
        )
    if published.exists():
        verify_runtime_source_package(
            identity,
            published,
            python_executable=python_executable,
        )
        return identity, published
    temporary = Path(
        tempfile.mkdtemp(prefix=".runtime-source-", dir=destination)
    )
    try:
        for relative, source in _local_source_paths(root):
            payload = _read_exact_file(source, f"local source {relative!r}")
            if (
                Sha256Digest.of_bytes(payload)
                != manifest.local_source_hashes[relative]
            ):
                raise RuntimeIdentityError(
                    f"local source {relative!r} changed during staging"
                )
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        manifest_path = temporary / RUNTIME_MANIFEST_FILENAME
        manifest_path.write_text(
            canonical_json(manifest.as_record()),
            encoding="utf-8",
        )
        with manifest_path.open("rb") as stream:
            os.fsync(stream.fileno())
        _make_read_only(temporary)
        if published.is_symlink():
            raise RuntimeIdentityError(
                "runtime source publication path became a symlink"
            )
        try:
            os.rename(temporary, published)
        except FileExistsError:
            verify_runtime_source_package(
                identity,
                published,
                python_executable=python_executable,
            )
        else:
            directory_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        _discard_temporary_tree(temporary)
    verify_runtime_source_package(
        identity,
        published,
        python_executable=python_executable,
    )
    return identity, published


def load_runtime_source_manifest(
    package_path: str | Path,
) -> RuntimeSourceManifest:
    package = Path(package_path)
    payload = _read_exact_file(
        package / RUNTIME_MANIFEST_FILENAME,
        "runtime source manifest",
    )
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeIdentityError(
            "runtime source manifest is not valid JSON"
        ) from exc
    if (
        not isinstance(value, Mapping)
        or canonical_json(value).encode("utf-8") != payload
    ):
        raise RuntimeIdentityError(
            "runtime source manifest is not canonical JSON"
        )
    try:
        return RuntimeSourceManifest.from_record(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeIdentityError(
            "runtime source manifest failed typed validation"
        ) from exc


def verify_runtime_source_package(
    identity: RuntimeIdentity,
    package_path: str | Path,
    *,
    python_executable: str | Path | None = None,
) -> RuntimeSourceManifest:
    """Verify every staged source byte and reject unmanifested package entries."""

    if not isinstance(identity, RuntimeIdentity):
        raise TypeError("identity must be a RuntimeIdentity")
    package = Path(package_path)
    if package.is_symlink() or not package.is_dir():
        raise RuntimeIdentityError(
            "runtime source package must be a real directory"
        )
    manifest = load_runtime_source_manifest(package)
    if (
        manifest.worker_entrypoint != WORKER_ENTRYPOINT
        or manifest.synthetic_packages != SYNTHETIC_PACKAGES
        or manifest.admitted_local_roots != ADMITTED_LOCAL_ROOTS
        or not set(_SELECTED_LOCAL_SOURCES).issubset(
            manifest.local_source_hashes
        )
        or any(
            relative not in _SELECTED_LOCAL_SOURCES
            and relative.split("/", 1)[0] not in ADMITTED_LOCAL_ROOTS
            for relative in manifest.local_source_hashes
        )
        or identity.worker_entrypoint != manifest.worker_entrypoint
        or identity.runtime_source_manifest_id != manifest.manifest_id
        or identity.runtime_source_manifest_hash != manifest.content_hash
        or identity.interpreter_runtime_id
        != manifest.interpreter_runtime.interpreter_id
        or identity.interpreter_runtime_hash
        != manifest.interpreter_runtime.content_hash
        or package.name != manifest.manifest_id.value
    ):
        raise RuntimeIdentityError(
            "runtime source package differs from registration"
        )
    actual_paths = {
        relative
        for relative, _ in _walk_regular_files(
            package,
            python_only=False,
            forbidden_directories=frozenset({"__pycache__"}),
        )
    }
    expected_paths = set(manifest.local_source_hashes) | {
        RUNTIME_MANIFEST_FILENAME
    }
    if actual_paths != expected_paths:
        raise RuntimeIdentityError(
            "runtime source package has missing or unmanifested entries"
        )
    for relative, expected in manifest.local_source_hashes.items():
        actual = Sha256Digest.of_bytes(
            _read_exact_file(
                package / relative,
                f"staged source {relative!r}",
            )
        )
        if actual != expected:
            raise RuntimeIdentityError(
                f"staged source {relative!r} differs from manifest"
            )
    verify_interpreter_runtime(
        manifest.interpreter_runtime,
        python_executable=python_executable,
    )
    return manifest


def load_verified_bootstrap_program(
    identity: RuntimeIdentity,
    package_path: str | Path,
    *,
    python_executable: str | Path | None = None,
) -> str:
    manifest = verify_runtime_source_package(
        identity,
        package_path,
        python_executable=python_executable,
    )
    payload = _read_exact_file(
        Path(package_path) / manifest.bootstrap_path,
        "runtime bootstrap",
    )
    if Sha256Digest.of_bytes(payload) != manifest.local_source_hashes[
        manifest.bootstrap_path
    ]:
        raise RuntimeIdentityError("runtime bootstrap differs from manifest")
    try:
        return payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RuntimeIdentityError("runtime bootstrap is not UTF-8 source") from exc


def inspect_runtime_identity(
    *,
    repository_root: str | Path,
    destination_root: str | Path,
    python_executable: str | Path | None = None,
) -> RuntimeIdentity:
    """Materialize and return the only identity admissible for launch."""

    identity, _ = materialize_runtime_source_package(
        repository_root=repository_root,
        destination_root=destination_root,
        python_executable=python_executable,
    )
    return identity


def verify_runtime_identity(
    identity: RuntimeIdentity,
    *,
    runtime_source_package: str | Path,
    python_executable: str | Path | None = None,
) -> RuntimeSourceManifest:
    return verify_runtime_source_package(
        identity,
        runtime_source_package,
        python_executable=python_executable,
    )


__all__ = [
    "ADMITTED_LOCAL_ROOTS",
    "BOOTSTRAP_SOURCE_PATH",
    "RUNTIME_MANIFEST_FILENAME",
    "SYNTHETIC_PACKAGES",
    "WORKER_ENTRYPOINT",
    "RuntimeIdentityError",
    "inspect_interpreter_runtime",
    "inspect_runtime_identity",
    "inspect_runtime_source_manifest",
    "load_runtime_source_manifest",
    "load_verified_bootstrap_program",
    "materialize_runtime_source_package",
    "runtime_identity_from_manifest",
    "verify_interpreter_runtime",
    "verify_runtime_identity",
    "verify_runtime_source_package",
]
