"""Dependency-leaf immutable values shared by EpisodeBuilder contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Any, Mapping, Optional

from agent.duet_contracts import content_id
from agent.episode_contracts import OpaqueId, Sha256Digest


_LOCAL_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_TOKEN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_FIELD_PATH = re.compile(r"^[a-z][a-z0-9_.\[\]-]{0,511}$")
_DOTTED_NAME = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*$")
_DEFINITION_ID = re.compile(r"^function_[0-9a-f]{64}$")
_EPISODE_ID = re.compile(r"^episode_[0-9a-f]{64}$")
_ATTEMPT_NONCE = re.compile(r"^[0-9a-f]{64}$")
_BUILD_STATUSES = frozenset({"materialized", "blocked", "failed"})


def _record(value: object, name: str, expected: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{name} must contain exactly {sorted(expected)!r}")
    return value


def _array(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    return value


def _text(value: object, name: str, *, maximum: int = 8192) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be non-empty text without NUL bytes")
    if len(value) > maximum:
        raise ValueError(f"{name} must be at most {maximum} characters")
    return value


def _local_id(value: object, name: str) -> str:
    result = _text(value, name, maximum=64)
    if _LOCAL_ID.fullmatch(result) is None:
        raise ValueError(f"{name} must be a lowercase Episode-local identifier")
    return result


def _token(value: object, name: str) -> str:
    result = _text(value, name, maximum=128)
    if _TOKEN.fullmatch(result) is None:
        raise ValueError(f"{name} must be a lowercase token")
    return result


def _tuple_of_strings(
    value: object,
    name: str,
    *,
    pattern: re.Pattern[str] | None = None,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be a tuple")
    result = tuple(_text(item, name, maximum=512) for item in value)
    if pattern is not None and any(pattern.fullmatch(item) is None for item in result):
        raise ValueError(f"{name} contains an invalid value")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must contain unique values")
    return result


def _freeze_json(value: object, name: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError(f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        keys = tuple(value)
        if any(not isinstance(key, str) or not key for key in keys):
            raise ValueError(f"{name} keys must be non-empty strings")
        return MappingProxyType(
            {
                key: _freeze_json(value[key], f"{name}.{key}")
                for key in sorted(keys)
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(
            _freeze_json(item, f"{name}[{index}]")
            for index, item in enumerate(value)
        )
    raise ValueError(f"{name} must contain only JSON-shaped values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _json_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    frozen = _freeze_json(value, name)
    if not isinstance(frozen, Mapping):
        raise AssertionError("mapping freeze changed the top-level shape")
    return frozen


def _derivation_basis(
    value: object,
    name: str,
) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{name} must identify at least one derivation")
    result: dict[str, str] = {}
    for key in sorted(value):
        if not isinstance(key, str) or not key:
            raise ValueError(f"{name} fields must be non-empty strings")
        result[key] = _text(value[key], f"{name}.{key}", maximum=1024)
    return MappingProxyType(result)


@dataclass(frozen=True)
class MaterializerIdentity:
    """Content identity of the exact Builder implementation and model route."""

    builder_source_hashes: Mapping[str, Sha256Digest]
    function_catalog: tuple[Mapping[str, object], ...]
    planner_model_config: Mapping[str, object]
    materializer_id: OpaqueId = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.builder_source_hashes, Mapping) or not self.builder_source_hashes:
            raise ValueError("builder_source_hashes must be a non-empty mapping")
        sources: dict[str, Sha256Digest] = {}
        for path in sorted(self.builder_source_hashes):
            if (
                not isinstance(path, str)
                or not path.endswith(".py")
                or path.startswith("/")
                or any(part in {"", ".", ".."} for part in path.split("/"))
            ):
                raise ValueError("builder source paths must be normalized Python paths")
            digest = self.builder_source_hashes[path]
            sources[path] = digest if isinstance(digest, Sha256Digest) else Sha256Digest(digest)
        if not isinstance(self.function_catalog, tuple) or not self.function_catalog:
            raise ValueError("function_catalog must be a non-empty tuple")
        catalog = tuple(
            _json_mapping(item, f"function_catalog[{index}]")
            for index, item in enumerate(self.function_catalog)
        )
        definition_ids = [item.get("definition_id") for item in catalog]
        if any(
            not isinstance(item, str) or _DEFINITION_ID.fullmatch(item) is None
            for item in definition_ids
        ) or len(set(definition_ids)) != len(definition_ids):
            raise ValueError("function_catalog must contain unique definition IDs")
        model_config = _json_mapping(self.planner_model_config, "planner_model_config")
        forbidden = {
            "api_key",
            "access_key",
            "auth_token",
            "access_token",
            "refresh_token",
            "secret",
            "password",
            "credential",
            "private_key",
            "cookie",
        }
        pending: list[object] = [model_config]
        while pending:
            current = pending.pop()
            if isinstance(current, Mapping):
                for key, item in current.items():
                    lowered = key.lower()
                    normalized = lowered.replace("-", "_")
                    if any(marker in normalized for marker in forbidden):
                        raise ValueError(
                            "planner_model_config cannot contain secrets"
                        )
                    pending.append(item)
            elif isinstance(current, tuple):
                pending.extend(current)
        object.__setattr__(self, "builder_source_hashes", MappingProxyType(sources))
        object.__setattr__(self, "function_catalog", catalog)
        object.__setattr__(self, "planner_model_config", model_config)
        object.__setattr__(
            self,
            "materializer_id",
            content_id("materializer", self.semantic_record()),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "builder_source_hashes": {
                path: digest.value
                for path, digest in self.builder_source_hashes.items()
            },
            "function_catalog": _thaw_json(self.function_catalog),
            "planner_model_config": _thaw_json(self.planner_model_config),
        }

    def as_record(self) -> dict[str, Any]:
        return {"materializer_id": self.materializer_id.value, **self.semantic_record()}

    @classmethod
    def from_record(cls, value: object) -> "MaterializerIdentity":
        record = _record(
            value,
            "materializer identity",
            {
                "materializer_id",
                "builder_source_hashes",
                "function_catalog",
                "planner_model_config",
            },
        )
        catalog = _array(record["function_catalog"], "function_catalog")
        result = cls(
            builder_source_hashes=record["builder_source_hashes"],
            function_catalog=tuple(catalog),
            planner_model_config=record["planner_model_config"],
        )
        if result.materializer_id.value != record["materializer_id"]:
            raise ValueError("materializer identity is stale")
        return result


@dataclass(frozen=True)
class BuildAttempt:
    """One fresh invocation of one materializer for one approved request."""

    build_request_id: OpaqueId
    materializer: MaterializerIdentity
    nonce: str
    build_attempt_id: OpaqueId = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.build_request_id, OpaqueId):
            raise TypeError("build_request_id must be an OpaqueId")
        if not isinstance(self.materializer, MaterializerIdentity):
            raise TypeError("materializer must be a MaterializerIdentity")
        if not isinstance(self.nonce, str) or _ATTEMPT_NONCE.fullmatch(self.nonce) is None:
            raise ValueError("build attempt nonce must be 64 lowercase hexadecimal digits")
        object.__setattr__(
            self,
            "build_attempt_id",
            content_id("build_attempt", self.semantic_record()),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "build_request_id": self.build_request_id.value,
            "materializer": self.materializer.as_record(),
            "nonce": self.nonce,
        }

    def as_record(self) -> dict[str, Any]:
        return {"build_attempt_id": self.build_attempt_id.value, **self.semantic_record()}

    @classmethod
    def from_record(cls, value: object) -> "BuildAttempt":
        record = _record(
            value,
            "build attempt",
            {"build_attempt_id", "build_request_id", "materializer", "nonce"},
        )
        result = cls(
            build_request_id=OpaqueId(record["build_request_id"]),
            materializer=MaterializerIdentity.from_record(record["materializer"]),
            nonce=record["nonce"],
        )
        if result.build_attempt_id.value != record["build_attempt_id"]:
            raise ValueError("build attempt identity is stale")
        return result


@dataclass(frozen=True)
class BuildDeficit:
    """One Builder-owned unresolved choice anchored to the Duet design."""

    code: str
    field_path: str
    detail: str
    episode_local_id: Optional[str] = None
    blocking: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _token(self.code, "deficit code"))
        path = _text(self.field_path, "deficit field_path", maximum=512)
        if _FIELD_PATH.fullmatch(path) is None:
            raise ValueError("deficit field_path has an invalid shape")
        object.__setattr__(self, "field_path", path)
        object.__setattr__(
            self,
            "detail",
            _text(self.detail, "deficit detail", maximum=2048),
        )
        if self.episode_local_id is not None:
            object.__setattr__(
                self,
                "episode_local_id",
                _local_id(self.episode_local_id, "deficit episode_local_id"),
            )
        if not isinstance(self.blocking, bool):
            raise ValueError("deficit blocking must be boolean")

    def as_record(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field_path": self.field_path,
            "detail": self.detail,
            "episode_local_id": self.episode_local_id,
            "blocking": self.blocking,
        }

    @classmethod
    def from_record(cls, value: object) -> "BuildDeficit":
        record = _record(
            value,
            "build deficit",
            {"code", "field_path", "detail", "episode_local_id", "blocking"},
        )
        return cls(**record)


@dataclass(frozen=True)
class EmittedEpisodeModule:
    """One generated Episode module with source and derivation kept together."""

    local_id: str
    module_name: str
    module_source: str
    derivation_notes: Mapping[str, str]
    source_hash: Sha256Digest = field(init=False)
    emitted_module_id: OpaqueId = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "local_id", _local_id(self.local_id, "local_id"))
        module_name = _text(self.module_name, "module_name", maximum=512)
        if _DOTTED_NAME.fullmatch(module_name) is None:
            raise ValueError("module_name must be a dotted Python module name")
        object.__setattr__(self, "module_name", module_name)
        if (
            not isinstance(self.module_source, str)
            or not self.module_source.strip()
            or "\x00" in self.module_source
        ):
            raise ValueError("module_source must be non-empty text without NUL bytes")
        object.__setattr__(
            self,
            "derivation_notes",
            _derivation_basis(self.derivation_notes, "derivation_notes"),
        )
        object.__setattr__(
            self,
            "source_hash",
            Sha256Digest.of_bytes(self.module_source.encode("utf-8")),
        )
        object.__setattr__(
            self,
            "emitted_module_id",
            content_id("emitted_module", self.semantic_record()),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "local_id": self.local_id,
            "module_name": self.module_name,
            "module_source": self.module_source,
            "derivation_notes": dict(self.derivation_notes),
            "source_hash": self.source_hash.value,
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "emitted_module_id": self.emitted_module_id.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "EmittedEpisodeModule":
        record = _record(
            value,
            "emitted Episode module",
            {
                "emitted_module_id",
                "local_id",
                "module_name",
                "module_source",
                "derivation_notes",
                "source_hash",
            },
        )
        result = cls(
            local_id=record["local_id"],
            module_name=record["module_name"],
            module_source=record["module_source"],
            derivation_notes=record["derivation_notes"],
        )
        if result.source_hash.value != record["source_hash"]:
            raise ValueError("emitted Episode module source hash is stale")
        if result.emitted_module_id.value != record["emitted_module_id"]:
            raise ValueError("emitted Episode module identity is stale")
        return result


def _opaque_id_map(
    value: object,
    name: str,
    *,
    allow_empty: bool = False,
) -> Mapping[str, OpaqueId]:
    if not isinstance(value, Mapping) or (not value and not allow_empty):
        qualifier = "a mapping" if allow_empty else "a non-empty mapping"
        raise ValueError(f"{name} must be {qualifier}")
    result: dict[str, OpaqueId] = {}
    for local_id in sorted(value):
        key = _local_id(local_id, f"{name} key")
        raw = value[local_id]
        result[key] = raw if isinstance(raw, OpaqueId) else OpaqueId(raw)
    return MappingProxyType(result)


@dataclass(frozen=True)
class BuildReceipt:
    """The immutable outcome for one source-materialization attempt."""

    build_request_id: OpaqueId
    build_attempt_id: OpaqueId
    plan_id: OpaqueId
    status: str
    manifest_id: Optional[OpaqueId]
    admission_report_id: Optional[OpaqueId]
    emitted_module_ids_by_local_id: Mapping[str, OpaqueId]
    deficits: tuple[BuildDeficit, ...]
    receipt_id: OpaqueId = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.build_request_id, OpaqueId):
            raise TypeError("build_request_id must be an OpaqueId")
        if not isinstance(self.build_attempt_id, OpaqueId):
            raise TypeError("build_attempt_id must be an OpaqueId")
        if not isinstance(self.plan_id, OpaqueId):
            raise TypeError("plan_id must be an OpaqueId")
        if self.status not in _BUILD_STATUSES:
            raise ValueError(f"status must be one of {sorted(_BUILD_STATUSES)!r}")
        if self.manifest_id is not None and not isinstance(self.manifest_id, OpaqueId):
            raise TypeError("manifest_id must be an OpaqueId or None")
        if self.admission_report_id is not None and not isinstance(
            self.admission_report_id,
            OpaqueId,
        ):
            raise TypeError("admission_report_id must be an OpaqueId or None")
        object.__setattr__(
            self,
            "emitted_module_ids_by_local_id",
            _opaque_id_map(
                self.emitted_module_ids_by_local_id,
                "emitted_module_ids_by_local_id",
                allow_empty=True,
            ),
        )
        if not isinstance(self.deficits, tuple) or any(
            not isinstance(deficit, BuildDeficit) for deficit in self.deficits
        ):
            raise TypeError("deficits must contain BuildDeficit values")
        blocking = any(deficit.blocking for deficit in self.deficits)
        if self.status == "materialized":
            if (
                self.manifest_id is None
                or self.admission_report_id is None
                or blocking
            ):
                raise ValueError(
                    "a materialized build requires an admission report, a manifest, "
                    "and no blocking deficit"
                )
        else:
            if self.manifest_id is not None or not blocking:
                raise ValueError(
                    "a blocked or failed build requires a blocking deficit and no manifest"
                )
        object.__setattr__(
            self,
            "deficits",
            tuple(
                sorted(
                    self.deficits,
                    key=lambda item: (
                        item.episode_local_id or "",
                        item.field_path,
                        item.code,
                        item.detail,
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "receipt_id",
            content_id("build_receipt", self.semantic_record()),
        )

    @property
    def materialized(self) -> bool:
        return self.status == "materialized"

    @property
    def content_hash(self) -> Sha256Digest:
        return Sha256Digest.of_record(self.semantic_record())

    def semantic_record(self) -> dict[str, Any]:
        return {
            "build_request_id": self.build_request_id.value,
            "build_attempt_id": self.build_attempt_id.value,
            "plan_id": self.plan_id.value,
            "status": self.status,
            "manifest_id": (
                None if self.manifest_id is None else self.manifest_id.value
            ),
            "admission_report_id": (
                None
                if self.admission_report_id is None
                else self.admission_report_id.value
            ),
            "emitted_module_ids_by_local_id": {
                local_id: identifier.value
                for local_id, identifier in self.emitted_module_ids_by_local_id.items()
            },
            "deficits": [deficit.as_record() for deficit in self.deficits],
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id.value,
            "content_hash": self.content_hash.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "BuildReceipt":
        record = _record(
            value,
            "build receipt",
            {
                "receipt_id",
                "content_hash",
                "build_request_id",
                "build_attempt_id",
                "plan_id",
                "status",
                "manifest_id",
                "admission_report_id",
                "emitted_module_ids_by_local_id",
                "deficits",
            },
        )
        if not isinstance(record["deficits"], list):
            raise ValueError("build receipt deficits must be an array")
        result = cls(
            build_request_id=OpaqueId(record["build_request_id"]),
            build_attempt_id=OpaqueId(record["build_attempt_id"]),
            plan_id=OpaqueId(record["plan_id"]),
            status=record["status"],
            manifest_id=(
                None
                if record["manifest_id"] is None
                else OpaqueId(record["manifest_id"])
            ),
            admission_report_id=(
                None
                if record["admission_report_id"] is None
                else OpaqueId(record["admission_report_id"])
            ),
            emitted_module_ids_by_local_id=record[
                "emitted_module_ids_by_local_id"
            ],
            deficits=tuple(
                BuildDeficit.from_record(item) for item in record["deficits"]
            ),
        )
        if result.receipt_id.value != record["receipt_id"]:
            raise ValueError("build receipt identity is stale")
        if result.content_hash.value != record["content_hash"]:
            raise ValueError("build receipt content hash is stale")
        return result
