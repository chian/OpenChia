"""Candidate environment declarations and the exact dependency closure of a Run.

These records are data. Importing them never resolves packages, executes setup
instructions, loads dependency modules or changes the current interpreter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from agent.duet_contracts import content_id, digest_record
from agent.episode_contracts import OpaqueId, Sha256Digest


ENVIRONMENT_RECIPE_PATH = ".openchia-environment.json"


def _exact(value, fields, name):
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} must contain exactly {sorted(fields)}")
    return value


def _strings(value, name):
    if not isinstance(value, (tuple, list)) or any(
        not isinstance(item, str) or not item or "\x00" in item for item in value
    ):
        raise ValueError(f"{name} must be an array of nonempty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(value)


def _roots(value):
    roots = _strings(value, "import_roots")
    if any(not root.isascii() or not root.isidentifier() for root in roots):
        raise ValueError("import_roots must contain top-level Python module names")
    return tuple(sorted(roots))


@dataclass(frozen=True)
class TargetEnvironmentRecipe:
    """Editable requirements, not permission to install into the host.

    PM validates requirement syntax and produces the separately saved resolution.
    Free-form setup instructions are explanatory data, never host shell commands.
    """

    python: str
    dependencies: tuple[str, ...] = ()
    import_roots: tuple[str, ...] = ()
    setup_instructions: str = ""
    schema_version: int = 1
    recipe_hash: Sha256Digest = field(init=False)

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported Target Workflow environment recipe version")
        version = self.python.split(".") if isinstance(self.python, str) else ()
        if len(version) != 2 or any(not part.isascii() or not part.isdigit() for part in version):
            raise ValueError("environment python must identify the available major.minor runtime")
        requirements = _strings(self.dependencies, "dependencies")
        for requirement in requirements:
            if (
                requirement != requirement.strip()
                or not requirement[0].isalnum()
                or any(character in requirement for character in ("\n", "\r", "@", "/", "\\"))
                or ":" in requirement
            ):
                raise ValueError("dependencies must be registry requirements, not URLs, paths or installer options")
        if not isinstance(self.setup_instructions, str) or "\x00" in self.setup_instructions:
            raise ValueError("setup_instructions must be text without NUL bytes")
        object.__setattr__(self, "dependencies", tuple(sorted(requirements)))
        object.__setattr__(self, "import_roots", _roots(self.import_roots))
        object.__setattr__(self, "recipe_hash", digest_record(self.as_record()))

    def as_record(self):
        return {
            "schema_version": self.schema_version,
            "python": self.python,
            "dependencies": list(self.dependencies),
            "import_roots": list(self.import_roots),
            "setup_instructions": self.setup_instructions,
        }

    @classmethod
    def from_record(cls, value):
        record = _exact(value, {
            "schema_version", "python", "dependencies", "import_roots", "setup_instructions",
        }, "Target Workflow environment recipe")
        return cls(**record)


@dataclass(frozen=True)
class TargetEnvironmentLock:
    """Host-resolved package graph retained with an admitted build."""

    recipe_hash: Sha256Digest
    runtime_hash: Sha256Digest
    lockfile: str
    schema_version: int = 1
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported Target Workflow environment lock version")
        if not isinstance(self.recipe_hash, Sha256Digest) or not isinstance(self.runtime_hash, Sha256Digest):
            raise TypeError("environment lock must bind exact recipe and runtime hashes")
        if not isinstance(self.lockfile, str) or not self.lockfile.strip() or "\x00" in self.lockfile:
            raise ValueError("environment lock must contain the resolved uv.lock text")
        object.__setattr__(self, "content_hash", digest_record(self.semantic_record()))

    def semantic_record(self):
        return {
            "schema_version": self.schema_version,
            "recipe_hash": self.recipe_hash.value,
            "runtime_hash": self.runtime_hash.value,
            "lockfile": self.lockfile,
        }

    def as_record(self):
        return {"content_hash": self.content_hash.value, **self.semantic_record()}

    @classmethod
    def from_record(cls, value):
        record = _exact(value, {
            "schema_version", "recipe_hash", "runtime_hash", "lockfile", "content_hash",
        }, "Target Workflow environment lock")
        result = cls(
            recipe_hash=Sha256Digest(record["recipe_hash"]),
            runtime_hash=Sha256Digest(record["runtime_hash"]),
            lockfile=record["lockfile"], schema_version=record["schema_version"],
        )
        if result.content_hash.value != record["content_hash"]:
            raise ValueError("Target Workflow environment lock identity is stale")
        return result


@dataclass(frozen=True)
class PreparedTargetEnvironment:
    """Hash-bound installed files, independent of a coding-session directory."""

    recipe_hash: Sha256Digest
    runtime_hash: Sha256Digest
    lock_hash: Sha256Digest
    import_roots: tuple[str, ...]
    distributions: tuple[Mapping[str, str], ...]
    file_hashes: Mapping[str, Sha256Digest]
    schema_version: int = 1
    environment_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("unsupported prepared Target Workflow environment version")
        for name in ("recipe_hash", "runtime_hash", "lock_hash"):
            if not isinstance(getattr(self, name), Sha256Digest):
                raise TypeError(f"{name} must be a Sha256Digest")
        object.__setattr__(self, "import_roots", _roots(self.import_roots))
        distributions = []
        for raw in self.distributions:
            row = _exact(raw, {"name", "version"}, "resolved distribution")
            if any(not isinstance(row[key], str) or not row[key] or "\x00" in row[key] for key in row):
                raise ValueError("resolved distribution must name its exact version")
            distributions.append(MappingProxyType(dict(row)))
        names = [row["name"] for row in distributions]
        if len(set(names)) != len(names):
            raise ValueError("resolved distribution names must be unique")
        object.__setattr__(self, "distributions", tuple(sorted(distributions, key=lambda row: row["name"])))
        if not isinstance(self.file_hashes, Mapping):
            raise ValueError("dependency file_hashes must be a mapping")
        hashes = {}
        for path, digest in sorted(self.file_hashes.items()):
            if (
                not isinstance(path, str) or not path or path.startswith("/")
                or "\\" in path or "\x00" in path
                or any(part in {"", ".", ".."} for part in path.split("/"))
            ):
                raise ValueError("dependency paths must be normalized relative paths")
            if not isinstance(digest, Sha256Digest):
                raise TypeError("dependency file hashes must be Sha256Digest values")
            hashes[path] = digest
        object.__setattr__(self, "file_hashes", MappingProxyType(hashes))
        identity = content_id("target_environment", self.semantic_record())
        object.__setattr__(self, "environment_id", identity)
        object.__setattr__(self, "content_hash", digest_record({
            "environment_id": identity.value, **self.semantic_record(),
        }))

    def semantic_record(self):
        return {
            "schema_version": self.schema_version,
            "recipe_hash": self.recipe_hash.value,
            "runtime_hash": self.runtime_hash.value,
            "lock_hash": self.lock_hash.value,
            "import_roots": list(self.import_roots),
            "distributions": [dict(row) for row in self.distributions],
            "file_hashes": {path: digest.value for path, digest in self.file_hashes.items()},
        }

    def as_record(self):
        return {
            "environment_id": self.environment_id.value,
            "content_hash": self.content_hash.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_record(cls, value):
        record = _exact(value, {
            "schema_version", "recipe_hash", "runtime_hash", "lock_hash", "import_roots",
            "distributions", "file_hashes", "environment_id", "content_hash",
        }, "prepared Target Workflow environment")
        if not isinstance(record["file_hashes"], Mapping):
            raise ValueError("dependency file_hashes must be a mapping")
        result = cls(
            schema_version=record["schema_version"],
            recipe_hash=Sha256Digest(record["recipe_hash"]),
            runtime_hash=Sha256Digest(record["runtime_hash"]),
            lock_hash=Sha256Digest(record["lock_hash"]),
            import_roots=record["import_roots"],
            distributions=record["distributions"],
            file_hashes={path: Sha256Digest(digest) for path, digest in record["file_hashes"].items()},
        )
        if result.environment_id.value != record["environment_id"] or result.content_hash.value != record["content_hash"]:
            raise ValueError("prepared Target Workflow environment identity is stale")
        return result
