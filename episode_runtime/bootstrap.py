"""Minimal source-only worker bootstrap executed from host-verified argv bytes.

This module intentionally imports only the standard library.  It authenticates
the staged manifest, every staged local source, and the running interpreter
before creating synthetic package namespaces and importing the worker.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import stat
import sys
import sysconfig
from types import ModuleType


_MANIFEST_NAME = "runtime_source_manifest.json"
_IGNORED_STDLIB_DIRECTORIES = frozenset(
    {"__pycache__", "site-packages", "dist-packages"}
)
_IGNORED_STDLIB_SUFFIXES = frozenset({".pyc", ".pyo"})
_EXPECTED_WORKER_ENTRYPOINT = "episode_runtime.worker.main"
_EXPECTED_ADMITTED_LOCAL_ROOTS = [
    "function_library",
    "handoff_library",
    "llm_call_library",
    "method_loop",
    "numeric_control_library",
    "question_table_goal_library",
]
_EXPECTED_SYNTHETIC_PACKAGES = [
    "agent",
    "episode_builder",
    "episode_library",
    "episode_runtime",
    "iterative_episode_refiner",
]


class BootstrapError(RuntimeError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _content_id(kind: str, value: object) -> str:
    return f"{kind}_{hashlib.sha256(_canonical(value)).hexdigest()}"


def _record(value: object, fields: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise BootstrapError(f"{name} fields are not exact")
    return value


def _relative(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.startswith("/")
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise BootstrapError(f"{name} is not a normalized relative path")
    return value


def _read_regular(path: Path, name: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise BootstrapError(f"cannot open exact {name}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise BootstrapError(f"{name} is not a regular file")
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise BootstrapError(f"{name} ended while being read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise BootstrapError(f"{name} grew while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _walk(
    root: Path,
    *,
    ignored_directories: frozenset[str] = frozenset(),
    ignored_suffixes: frozenset[str] = frozenset(),
    forbidden_directories: frozenset[str] = frozenset(),
    allow_file_symlinks: bool = False,
) -> dict[str, Path]:
    if root.is_symlink() or not root.is_dir():
        raise BootstrapError(f"source root is not a real directory: {root}")
    result: dict[str, Path] = {}
    pending = [(root, "")]
    while pending:
        directory, prefix = pending.pop()
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                if not allow_file_symlinks:
                    raise BootstrapError(
                        f"source entry {relative!r} is a symlink"
                    )
                try:
                    target_info = Path(entry.path).resolve(strict=True).stat()
                except OSError as exc:
                    raise BootstrapError(
                        f"stdlib link {relative!r} has no exact target"
                    ) from exc
                if not stat.S_ISREG(target_info.st_mode):
                    raise BootstrapError(
                        f"stdlib link {relative!r} does not resolve to a regular file"
                    )
                if Path(relative).suffix not in ignored_suffixes:
                    result[_relative(relative, "source path")] = Path(entry.path)
                continue
            if stat.S_ISDIR(info.st_mode):
                if entry.name in forbidden_directories:
                    raise BootstrapError(
                        f"source directory {relative!r} is forbidden"
                    )
                if entry.name not in ignored_directories:
                    pending.append((Path(entry.path), relative))
                continue
            if not stat.S_ISREG(info.st_mode):
                raise BootstrapError(f"source entry {relative!r} is not regular")
            if Path(relative).suffix not in ignored_suffixes:
                result[_relative(relative, "source path")] = Path(entry.path)
    return result


def _stdlib_entry_payload_and_digest(path: Path, name: str) -> tuple[bytes, str]:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(path)
        payload = _read_regular(path.resolve(strict=True), f"{name} link target")
        return (
            payload,
            _digest(
                b"stdlib-symlink\0"
                + target.encode("utf-8", errors="strict")
                + b"\0"
                + payload
            ),
        )
    payload = _read_regular(path, name)
    return payload, _digest(payload)


def _hash_mapping(value: object, name: str, *, allow_empty: bool = False) -> dict[str, str]:
    if not isinstance(value, dict) or (not value and not allow_empty):
        raise BootstrapError(f"{name} must be a hash mapping")
    result: dict[str, str] = {}
    for raw_path, digest in value.items():
        path = _relative(raw_path, f"{name} path")
        if (
            not isinstance(digest, str)
            or len(digest) != 71
            or not digest.startswith("sha256:")
        ):
            raise BootstrapError(f"{name} contains an invalid digest")
        result[path] = digest
    return result


def _validate_interpreter_record(value: object) -> dict[str, object]:
    record = _record(
        value,
        {
            "interpreter_id",
            "content_hash",
            "implementation",
            "version",
            "cache_tag",
            "executable_hash",
            "stdlib_file_hashes",
            "shared_library_hashes",
        },
        "interpreter identity",
    )
    _hash_mapping(record["stdlib_file_hashes"], "stdlib_file_hashes")
    _hash_mapping(
        record["shared_library_hashes"],
        "shared_library_hashes",
        allow_empty=True,
    )
    semantic = {
        key: record[key]
        for key in (
            "implementation",
            "version",
            "cache_tag",
            "executable_hash",
            "stdlib_file_hashes",
            "shared_library_hashes",
        )
    }
    if (
        record["interpreter_id"] != _content_id("interpreter_runtime", semantic)
        or record["content_hash"]
        != _digest(
            _canonical(
                {"interpreter_id": record["interpreter_id"], **semantic}
            )
        )
    ):
        raise BootstrapError("interpreter identity is stale")
    return record


def _load_manifest(
    package: Path,
    expected_id: str,
    expected_hash: str,
) -> dict[str, object]:
    payload = _read_regular(package / _MANIFEST_NAME, "runtime manifest")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapError("runtime manifest is not JSON") from exc
    if _canonical(value) != payload:
        raise BootstrapError("runtime manifest is not canonical")
    record = _record(
        value,
        {
            "manifest_id",
            "content_hash",
            "worker_entrypoint",
            "bootstrap_path",
            "local_source_hashes",
            "synthetic_packages",
            "admitted_local_roots",
            "interpreter_runtime",
        },
        "runtime source manifest",
    )
    _relative(record["bootstrap_path"], "bootstrap_path")
    hashes = _hash_mapping(record["local_source_hashes"], "local_source_hashes")
    if record["bootstrap_path"] not in hashes:
        raise BootstrapError("runtime manifest omits its bootstrap")
    interpreter = _validate_interpreter_record(record["interpreter_runtime"])
    if (
        record["worker_entrypoint"] != _EXPECTED_WORKER_ENTRYPOINT
        or record["synthetic_packages"] != _EXPECTED_SYNTHETIC_PACKAGES
        or record["admitted_local_roots"] != _EXPECTED_ADMITTED_LOCAL_ROOTS
    ):
        raise BootstrapError("runtime manifest names another local source boundary")
    semantic = {
        key: record[key]
        for key in (
            "worker_entrypoint",
            "bootstrap_path",
            "local_source_hashes",
            "synthetic_packages",
            "admitted_local_roots",
            "interpreter_runtime",
        )
    }
    if (
        record["manifest_id"] != expected_id
        or record["content_hash"] != expected_hash
        or record["manifest_id"]
        != _content_id("runtime_source_manifest", semantic)
        or record["content_hash"]
        != _digest(_canonical({"manifest_id": record["manifest_id"], **semantic}))
        or package.name != expected_id
    ):
        raise BootstrapError("runtime source manifest differs from launch identity")
    record["interpreter_runtime"] = interpreter
    return record


def _verify_package(package: Path, manifest: dict[str, object]) -> None:
    actual = _walk(
        package,
        forbidden_directories=frozenset({"__pycache__"}),
    )
    expected = set(manifest["local_source_hashes"]) | {_MANIFEST_NAME}
    if set(actual) != expected:
        raise BootstrapError("runtime package has missing or unmanifested entries")
    hashes = manifest["local_source_hashes"]
    for relative, expected_hash in hashes.items():
        if _digest(_read_regular(actual[relative], f"staged source {relative!r}")) != expected_hash:
            raise BootstrapError(f"staged source {relative!r} differs from manifest")


def _current_executable() -> Path:
    """The running interpreter's real file. Mirrors ``episode_runtime.interpreter``
    (this bootstrap is source-only and must not import siblings): ``/proc/self/exe``
    on Linux, ``sys.executable`` resolved elsewhere."""
    if sys.platform.startswith("linux"):
        try:
            return Path(os.readlink("/proc/self/exe")).resolve(strict=True)
        except OSError:
            pass
    if not sys.executable:
        raise BootstrapError("sys.executable is empty; cannot identify the interpreter")
    return Path(sys.executable).expanduser().resolve(strict=True)


def _verify_interpreter(identity: dict[str, object]) -> tuple[Path, dict[Path, str]]:
    if (
        identity["implementation"] != sys.implementation.name
        or identity["version"]
        != [sys.version_info.major, sys.version_info.minor, sys.version_info.micro]
        or identity["cache_tag"] != (sys.implementation.cache_tag or "none")
    ):
        raise BootstrapError("running interpreter metadata differs from manifest")
    executable = _current_executable()
    if _digest(_read_regular(executable, "Python executable")) != identity["executable_hash"]:
        raise BootstrapError("running Python executable differs from manifest")
    stdlib = Path(sysconfig.get_path("stdlib")).resolve(strict=True)
    actual = _walk(
        stdlib,
        ignored_directories=_IGNORED_STDLIB_DIRECTORIES,
        ignored_suffixes=_IGNORED_STDLIB_SUFFIXES,
        allow_file_symlinks=True,
    )
    expected = identity["stdlib_file_hashes"]
    if set(actual) != set(expected):
        raise BootstrapError("standard-library file set differs from manifest")
    allowed: dict[Path, str] = {}
    for relative, expected_hash in expected.items():
        path = actual[relative]
        _, actual_hash = _stdlib_entry_payload_and_digest(
            path,
            f"stdlib file {relative!r}",
        )
        if actual_hash != expected_hash:
            raise BootstrapError(f"stdlib file {relative!r} differs from manifest")
        allowed[Path(os.path.abspath(path))] = expected_hash
    library_dir = sysconfig.get_config_var("LIBDIR")
    for key, expected_hash in identity["shared_library_hashes"].items():
        if not isinstance(library_dir, str):
            raise BootstrapError("interpreter shared-library directory is absent")
        path = (Path(library_dir) / Path(key).name).resolve(strict=True)
        if _digest(_read_regular(path, f"shared library {key!r}")) != expected_hash:
            raise BootstrapError(f"shared library {key!r} differs from manifest")
    return stdlib, allowed


class _SourceOnlyLoader(importlib.machinery.SourceFileLoader):
    def __init__(
        self,
        fullname: str,
        path: str,
        expected_hash: str,
        *,
        stdlib_entry: bool,
    ) -> None:
        super().__init__(fullname, path)
        self._expected_hash = expected_hash
        self._stdlib_entry = stdlib_entry

    def get_code(self, fullname: str):
        source_path = Path(self.get_filename(fullname))
        if self._stdlib_entry:
            source, actual_hash = _stdlib_entry_payload_and_digest(
                source_path,
                f"import source {fullname!r}",
            )
        else:
            source = _read_regular(source_path, f"import source {fullname!r}")
            actual_hash = _digest(source)
        if actual_hash != self._expected_hash:
            raise BootstrapError(
                f"import source {fullname!r} changed after bootstrap verification"
            )
        return compile(source, str(source_path), "exec", dont_inherit=True)

    def set_data(self, path: str, data: bytes, *_args, **_kwargs) -> None:
        raise BootstrapError("bytecode writes are forbidden")


class _ClosedImportFinder(importlib.abc.MetaPathFinder):
    def __init__(
        self,
        *,
        package: Path,
        local_hashes: dict[str, str],
        stdlib: Path,
        stdlib_files: dict[Path, str],
    ) -> None:
        self._package = package.resolve(strict=True)
        self._local_files = {
            Path(os.path.abspath(self._package / relative)): expected
            for relative, expected in local_hashes.items()
        }
        self._stdlib = stdlib.resolve(strict=True)
        self._stdlib_files = dict(stdlib_files)

    def find_spec(self, fullname: str, path=None, target=None):
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is None:
            return None
        if spec.origin in {None, "built-in", "frozen"}:
            if spec.submodule_search_locations is not None:
                for location in spec.submodule_search_locations:
                    resolved = Path(location).resolve(strict=True)
                    if not (
                        resolved == self._package
                        or self._package in resolved.parents
                        or resolved == self._stdlib
                        or self._stdlib in resolved.parents
                    ):
                        raise BootstrapError(
                            f"namespace import {fullname!r} escapes admitted roots"
                        )
            return spec
        origin = Path(os.path.abspath(spec.origin))
        local_hash = self._local_files.get(origin)
        stdlib_hash = self._stdlib_files.get(origin)
        if local_hash is None and stdlib_hash is None:
            raise BootstrapError(
                f"import {fullname!r} resolves outside staged local source and stdlib"
            )
        if origin.suffix == ".py":
            expected_hash = local_hash if local_hash is not None else stdlib_hash
            if expected_hash is None:
                raise AssertionError("admitted import lost its content hash")
            spec.loader = _SourceOnlyLoader(
                fullname,
                str(origin),
                expected_hash,
                stdlib_entry=stdlib_hash is not None,
            )
            spec.cached = None
        return spec


def _synthetic_packages(package: Path, names: object) -> None:
    if (
        not isinstance(names, list)
        or not names
        or names != sorted(set(names))
        or any(not isinstance(name, str) or "." in name for name in names)
    ):
        raise BootstrapError("synthetic package names are invalid")
    for name in names:
        location = package / name
        if not location.is_dir() or location.is_symlink():
            raise BootstrapError(f"synthetic package {name!r} is absent")
        module = ModuleType(name)
        module.__file__ = None
        module.__package__ = name
        module.__path__ = [str(location)]
        sys.modules[name] = module


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--bootstrap-package", required=True)
    parser.add_argument("--bootstrap-manifest-id", required=True)
    parser.add_argument("--bootstrap-manifest-hash", required=True)
    return parser


def main() -> None:
    arguments, worker_arguments = _parser().parse_known_args()
    package = Path(arguments.bootstrap_package)
    manifest = _load_manifest(
        package,
        arguments.bootstrap_manifest_id,
        arguments.bootstrap_manifest_hash,
    )
    _verify_package(package, manifest)
    stdlib, stdlib_files = _verify_interpreter(manifest["interpreter_runtime"])
    sys.dont_write_bytecode = True
    sys.path[:] = [str(package), str(stdlib), str(stdlib / "lib-dynload")]
    sys.meta_path[:] = [
        importlib.machinery.BuiltinImporter,
        importlib.machinery.FrozenImporter,
        _ClosedImportFinder(
            package=package,
            local_hashes=manifest["local_source_hashes"],
            stdlib=stdlib,
            stdlib_files=stdlib_files,
        ),
    ]
    _synthetic_packages(package, manifest["synthetic_packages"])
    sys.argv = ["episode-runtime-worker", *worker_arguments]
    from episode_runtime.worker import main as worker_main

    worker_main()


if __name__ == "__main__":
    main()
