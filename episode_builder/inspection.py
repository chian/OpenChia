"""Typed, non-executing inspection of one exact EpisodeBuilder attempt.

The projector is the only UI-facing interpretation boundary for build
artifacts.  It correlates typed records, parses generated source as Python AST
without importing it, and emits one content-addressed Materialized
Specification with stable refinement targets.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional

from agent.duet_contracts import canonical_json, content_id
from agent.episode_contracts import OpaqueId, Sha256Digest

from ._contract_base import (
    BuildAttempt,
    BuildDeficit,
    BuildReceipt,
    EmittedEpisodeModule,
)
from ._contract_chain import (
    ApprovedBuildRequest,
    BuildAdmissionReport,
    BuildManifest,
    WorkflowMaterializationPlan,
)


_BUILD_EPISODE_PARAMETERS = (
    "grain",
    "key",
    "request",
    "goal_view",
    "collaborators",
    "child_builders",
)
_BUILD_CONTROLLER_FACTORY_PARAMETERS = ("goal_view", "collaborators")
_ROOT_BUILDERS = {
    "build_goal_state": ("request", "collaborators"),
    "scope_goal_state": ("goal_state", "goal"),
}


def _freeze(value: object, name: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ValueError(f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) or not key for key in value):
            raise ValueError(f"{name} keys must be non-empty strings")
        return MappingProxyType(
            {
                key: _freeze(value[key], f"{name}.{key}")
                for key in sorted(value)
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item, f"{name}[]") for item in value)
    raise ValueError(f"{name} must contain JSON-shaped values")


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _mapping(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} must contain exactly {sorted(fields)!r}")
    return value


def _text(value: object, name: str, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{name} must be non-empty text without NUL bytes")
    if len(value) > maximum:
        raise ValueError(f"{name} is too long")
    return value


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _package_module_path(module_name: str) -> str:
    parts = module_name.split(".")
    if any(not part.isidentifier() for part in parts):
        raise ValueError("module name cannot be projected to a Python path")
    return Path(*parts).with_suffix(".py").as_posix()


@dataclass(frozen=True)
class SpecificationPart:
    """One stable, independently targetable part of the projection."""

    stable_target: str
    name: str
    value: object
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        target = _text(self.stable_target, "stable_target", 2048)
        if not target.startswith("/"):
            raise ValueError("stable_target must be a JSON pointer")
        object.__setattr__(self, "stable_target", target)
        object.__setattr__(self, "name", _text(self.name, "part name", 256))
        frozen = _freeze(self.value, "part value")
        object.__setattr__(self, "value", frozen)
        object.__setattr__(
            self,
            "content_hash",
            Sha256Digest.of_record(
                {
                    "stable_target": target,
                    "name": self.name,
                    "value": _thaw(frozen),
                }
            ),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "stable_target": self.stable_target,
            "name": self.name,
            "value": _thaw(self.value),
            "content_hash": self.content_hash.value,
        }

    @classmethod
    def from_record(cls, value: object) -> "SpecificationPart":
        record = _mapping(
            value,
            {"stable_target", "name", "value", "content_hash"},
            "specification part",
        )
        result = cls(
            stable_target=record["stable_target"],
            name=record["name"],
            value=record["value"],
        )
        if result.content_hash.value != record["content_hash"]:
            raise ValueError("specification part hash is stale")
        return result


@dataclass(frozen=True)
class SourceSymbolIndexEntry:
    """Exact AST location of one generated source symbol."""

    episode_local_id: str
    module_name: str
    symbol_path: str
    kind: str
    lineno: int
    col_offset: int
    end_lineno: int
    end_col_offset: int
    source_hash: Sha256Digest
    stable_target: str

    def __post_init__(self) -> None:
        for name in (
            "episode_local_id",
            "module_name",
            "symbol_path",
            "kind",
            "stable_target",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name, 2048))
        if not self.stable_target.startswith("/"):
            raise ValueError("source symbol stable target must be a JSON pointer")
        for name in ("lineno", "end_lineno"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive line number")
        for name in ("col_offset", "end_col_offset"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 0:
                raise ValueError(f"{name} must be a non-negative column")
        if (self.end_lineno, self.end_col_offset) < (
            self.lineno,
            self.col_offset,
        ):
            raise ValueError("source symbol span is reversed")
        if not isinstance(self.source_hash, Sha256Digest):
            object.__setattr__(self, "source_hash", Sha256Digest(self.source_hash))

    def as_record(self) -> dict[str, Any]:
        return {
            "episode_local_id": self.episode_local_id,
            "module_name": self.module_name,
            "symbol_path": self.symbol_path,
            "kind": self.kind,
            "lineno": self.lineno,
            "col_offset": self.col_offset,
            "end_lineno": self.end_lineno,
            "end_col_offset": self.end_col_offset,
            "source_hash": self.source_hash.value,
            "stable_target": self.stable_target,
        }

    @classmethod
    def from_record(cls, value: object) -> "SourceSymbolIndexEntry":
        record = _mapping(
            value,
            {
                "episode_local_id",
                "module_name",
                "symbol_path",
                "kind",
                "lineno",
                "col_offset",
                "end_lineno",
                "end_col_offset",
                "source_hash",
                "stable_target",
            },
            "source symbol",
        )
        return cls(
            **{
                **record,
                "source_hash": Sha256Digest(record["source_hash"]),
            }
        )


@dataclass(frozen=True)
class ProjectedDeficit:
    origin: str
    deficit: BuildDeficit

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin", _text(self.origin, "deficit origin", 64))
        if not isinstance(self.deficit, BuildDeficit):
            raise TypeError("projected deficit must contain a BuildDeficit")

    def as_record(self) -> dict[str, Any]:
        return {"origin": self.origin, "deficit": self.deficit.as_record()}

    @classmethod
    def from_record(cls, value: object) -> "ProjectedDeficit":
        record = _mapping(value, {"origin", "deficit"}, "projected deficit")
        return cls(
            origin=record["origin"],
            deficit=BuildDeficit.from_record(record["deficit"]),
        )


@dataclass(frozen=True)
class EpisodeSpecification:
    """All projected parts for one frozen Episode local identity."""

    local_id: str
    stable_target: str
    episode_id: Optional[str]
    parts: tuple[SpecificationPart, ...]
    source_symbols: tuple[SourceSymbolIndexEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "local_id", _text(self.local_id, "local_id", 256))
        target = _text(self.stable_target, "stable_target", 2048)
        if not target.startswith("/"):
            raise ValueError("Episode stable target must be a JSON pointer")
        object.__setattr__(self, "stable_target", target)
        if self.episode_id is not None:
            object.__setattr__(
                self,
                "episode_id",
                _text(self.episode_id, "episode_id", 128),
            )
        if not isinstance(self.parts, tuple) or any(
            not isinstance(item, SpecificationPart) for item in self.parts
        ):
            raise TypeError("parts must contain SpecificationPart values")
        if not isinstance(self.source_symbols, tuple) or any(
            not isinstance(item, SourceSymbolIndexEntry)
            for item in self.source_symbols
        ):
            raise TypeError("source_symbols must contain AST index entries")
        parts = tuple(sorted(self.parts, key=lambda item: item.stable_target))
        symbols = tuple(
            sorted(
                self.source_symbols,
                key=lambda item: (
                    item.symbol_path,
                    item.lineno,
                    item.col_offset,
                ),
            )
        )
        targets = [item.stable_target for item in (*parts, *symbols)]
        if len(set(targets)) != len(targets):
            raise ValueError("Episode projection stable targets must be unique")
        object.__setattr__(self, "parts", parts)
        object.__setattr__(self, "source_symbols", symbols)

    def as_record(self) -> dict[str, Any]:
        return {
            "local_id": self.local_id,
            "stable_target": self.stable_target,
            "episode_id": self.episode_id,
            "parts": [item.as_record() for item in self.parts],
            "source_symbols": [item.as_record() for item in self.source_symbols],
        }

    @classmethod
    def from_record(cls, value: object) -> "EpisodeSpecification":
        record = _mapping(
            value,
            {"local_id", "stable_target", "episode_id", "parts", "source_symbols"},
            "Episode specification",
        )
        if not isinstance(record["parts"], list) or not isinstance(
            record["source_symbols"], list
        ):
            raise ValueError("Episode specification collections must be arrays")
        return cls(
            local_id=record["local_id"],
            stable_target=record["stable_target"],
            episode_id=record["episode_id"],
            parts=tuple(SpecificationPart.from_record(item) for item in record["parts"]),
            source_symbols=tuple(
                SourceSymbolIndexEntry.from_record(item)
                for item in record["source_symbols"]
            ),
        )


@dataclass(frozen=True)
class MaterializedSpecification:
    """Strict UI projection of one exact, possibly blocked build attempt."""

    build_request_id: OpaqueId
    build_attempt_id: OpaqueId
    plan_id: OpaqueId
    workflow_hash: Sha256Digest
    status: str
    receipt_id: Optional[OpaqueId]
    admission_report_id: Optional[OpaqueId]
    manifest_id: Optional[OpaqueId]
    workflow_global: tuple[SpecificationPart, ...]
    episodes: tuple[EpisodeSpecification, ...]
    deficits: tuple[ProjectedDeficit, ...]
    local_id_to_episode_id: Mapping[str, Optional[str]]
    expected_source_package_files: Mapping[str, Sha256Digest]
    specification_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        for name in ("build_request_id", "build_attempt_id", "plan_id"):
            if not isinstance(getattr(self, name), OpaqueId):
                raise TypeError(f"{name} must be an OpaqueId")
        if not isinstance(self.workflow_hash, Sha256Digest):
            object.__setattr__(self, "workflow_hash", Sha256Digest(self.workflow_hash))
        if self.status not in {"partial", "blocked", "failed", "materialized"}:
            raise ValueError("Materialized Specification status is invalid")
        for name in ("receipt_id", "admission_report_id", "manifest_id"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, OpaqueId):
                raise TypeError(f"{name} must be an OpaqueId or None")
        globals_ = tuple(sorted(self.workflow_global, key=lambda item: item.stable_target))
        episodes = tuple(sorted(self.episodes, key=lambda item: item.local_id))
        if any(not isinstance(item, SpecificationPart) for item in globals_):
            raise TypeError("workflow_global must contain SpecificationPart values")
        if any(not isinstance(item, EpisodeSpecification) for item in episodes):
            raise TypeError("episodes must contain EpisodeSpecification values")
        if len({item.local_id for item in episodes}) != len(episodes):
            raise ValueError("Episode specifications must have unique local IDs")
        deficits = tuple(self.deficits)
        if any(not isinstance(item, ProjectedDeficit) for item in deficits):
            raise TypeError("deficits must contain ProjectedDeficit values")
        crosswalk: dict[str, Optional[str]] = {}
        if not isinstance(self.local_id_to_episode_id, Mapping):
            raise TypeError("local_id_to_episode_id must be a mapping")
        for local_id in sorted(self.local_id_to_episode_id):
            episode_id = self.local_id_to_episode_id[local_id]
            crosswalk[_text(local_id, "crosswalk local_id", 256)] = (
                None
                if episode_id is None
                else _text(episode_id, "crosswalk episode_id", 128)
            )
        if set(crosswalk) != {item.local_id for item in episodes}:
            raise ValueError("crosswalk must cover every projected Episode")
        package: dict[str, Sha256Digest] = {}
        if not isinstance(self.expected_source_package_files, Mapping):
            raise TypeError("expected_source_package_files must be a mapping")
        for path in sorted(self.expected_source_package_files):
            if (
                not isinstance(path, str)
                or path.startswith("/")
                or any(part in {"", ".", ".."} for part in path.split("/"))
            ):
                raise ValueError("source package paths must be normalized relative paths")
            digest = self.expected_source_package_files[path]
            package[path] = digest if isinstance(digest, Sha256Digest) else Sha256Digest(digest)
        targets = ["/workflow_global"]
        targets.extend(item.stable_target for item in globals_)
        for episode in episodes:
            targets.append(episode.stable_target)
            targets.extend(item.stable_target for item in episode.parts)
            targets.extend(item.stable_target for item in episode.source_symbols)
        if len(set(targets)) != len(targets):
            raise ValueError("Materialized Specification targets must be globally unique")
        object.__setattr__(self, "workflow_global", globals_)
        object.__setattr__(self, "episodes", episodes)
        object.__setattr__(self, "deficits", deficits)
        object.__setattr__(self, "local_id_to_episode_id", MappingProxyType(crosswalk))
        object.__setattr__(self, "expected_source_package_files", MappingProxyType(package))
        semantic = self.semantic_record()
        object.__setattr__(
            self,
            "specification_id",
            content_id("materialized_specification", semantic),
        )
        object.__setattr__(self, "content_hash", Sha256Digest.of_record(semantic))

    @property
    def stable_targets(self) -> tuple[str, ...]:
        targets = ["/workflow_global"]
        targets.extend(item.stable_target for item in self.workflow_global)
        for episode in self.episodes:
            targets.append(episode.stable_target)
            targets.extend(item.stable_target for item in episode.parts)
            targets.extend(item.stable_target for item in episode.source_symbols)
        return tuple(targets)

    def semantic_record(self) -> dict[str, Any]:
        return {
            "build_request_id": self.build_request_id.value,
            "build_attempt_id": self.build_attempt_id.value,
            "plan_id": self.plan_id.value,
            "workflow_hash": self.workflow_hash.value,
            "status": self.status,
            "receipt_id": None if self.receipt_id is None else self.receipt_id.value,
            "admission_report_id": (
                None
                if self.admission_report_id is None
                else self.admission_report_id.value
            ),
            "manifest_id": None if self.manifest_id is None else self.manifest_id.value,
            "workflow_global": [item.as_record() for item in self.workflow_global],
            "episodes": [item.as_record() for item in self.episodes],
            "deficits": [item.as_record() for item in self.deficits],
            "local_id_to_episode_id": dict(self.local_id_to_episode_id),
            "expected_source_package_files": {
                path: digest.value
                for path, digest in self.expected_source_package_files.items()
            },
            "stable_targets": list(self.stable_targets),
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "specification_id": self.specification_id.value,
            "content_hash": self.content_hash.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "MaterializedSpecification":
        fields = {
            "specification_id",
            "content_hash",
            "build_request_id",
            "build_attempt_id",
            "plan_id",
            "workflow_hash",
            "status",
            "receipt_id",
            "admission_report_id",
            "manifest_id",
            "workflow_global",
            "episodes",
            "deficits",
            "local_id_to_episode_id",
            "expected_source_package_files",
            "stable_targets",
        }
        record = _mapping(value, fields, "Materialized Specification")
        for name in ("workflow_global", "episodes", "deficits", "stable_targets"):
            if not isinstance(record[name], list):
                raise ValueError(f"{name} must be an array")
        result = cls(
            build_request_id=OpaqueId(record["build_request_id"]),
            build_attempt_id=OpaqueId(record["build_attempt_id"]),
            plan_id=OpaqueId(record["plan_id"]),
            workflow_hash=Sha256Digest(record["workflow_hash"]),
            status=record["status"],
            receipt_id=(
                None if record["receipt_id"] is None else OpaqueId(record["receipt_id"])
            ),
            admission_report_id=(
                None
                if record["admission_report_id"] is None
                else OpaqueId(record["admission_report_id"])
            ),
            manifest_id=(
                None if record["manifest_id"] is None else OpaqueId(record["manifest_id"])
            ),
            workflow_global=tuple(
                SpecificationPart.from_record(item)
                for item in record["workflow_global"]
            ),
            episodes=tuple(
                EpisodeSpecification.from_record(item) for item in record["episodes"]
            ),
            deficits=tuple(
                ProjectedDeficit.from_record(item) for item in record["deficits"]
            ),
            local_id_to_episode_id=record["local_id_to_episode_id"],
            expected_source_package_files=record["expected_source_package_files"],
        )
        if tuple(record["stable_targets"]) != result.stable_targets:
            raise ValueError("Materialized Specification stable-target index is stale")
        if (
            result.specification_id.value != record["specification_id"]
            or result.content_hash.value != record["content_hash"]
        ):
            raise ValueError("Materialized Specification identity is stale")
        return result


@dataclass(frozen=True)
class MaterializationInspectionInput:
    """Exact typed correlation inputs for the pure projector."""

    build_request: ApprovedBuildRequest
    build_attempt: BuildAttempt
    plan: WorkflowMaterializationPlan
    emitted_modules: tuple[EmittedEpisodeModule, ...]
    admission_report: Optional[BuildAdmissionReport] = None
    manifest: Optional[BuildManifest] = None
    receipt: Optional[BuildReceipt] = None
    source_package_files: Optional[Mapping[str, Sha256Digest]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.build_request, ApprovedBuildRequest):
            raise TypeError("build_request must be an ApprovedBuildRequest")
        if not isinstance(self.build_attempt, BuildAttempt):
            raise TypeError("build_attempt must be a BuildAttempt")
        if not isinstance(self.plan, WorkflowMaterializationPlan):
            raise TypeError("plan must be a WorkflowMaterializationPlan")
        self.plan.validate_against(self.build_request, self.build_attempt)
        if not isinstance(self.emitted_modules, tuple) or any(
            not isinstance(item, EmittedEpisodeModule)
            for item in self.emitted_modules
        ):
            raise TypeError("emitted_modules must contain emitted module records")
        emitted = {item.local_id: item for item in self.emitted_modules}
        if len(emitted) != len(self.emitted_modules):
            raise ValueError("inspection input contains duplicate emitted modules")
        planned = {item.local_id: item for item in self.plan.nodes}
        if not set(emitted).issubset(planned):
            raise ValueError("inspection input contains an unplanned module")
        for local_id, module in emitted.items():
            if module.module_name != planned[local_id].module_name:
                raise ValueError("emitted module name differs from its plan")
        if self.admission_report is not None:
            if not isinstance(self.admission_report, BuildAdmissionReport):
                raise TypeError("admission_report must be a BuildAdmissionReport")
            self.admission_report.validate_against(self.plan)
            hashes = {key: item.source_hash for key, item in emitted.items()}
            if self.admission_report.module_source_hashes != hashes:
                raise ValueError("admission report differs from emitted module records")
        if self.manifest is not None:
            if self.admission_report is None:
                raise ValueError("manifest inspection requires its admission report")
            if not isinstance(self.manifest, BuildManifest):
                raise TypeError("manifest must be a BuildManifest")
            self.manifest.validate_against(self.plan, self.admission_report)
        if self.receipt is not None:
            if not isinstance(self.receipt, BuildReceipt):
                raise TypeError("receipt must be a BuildReceipt")
            if (
                self.receipt.build_request_id != self.build_request.build_request_id
                or self.receipt.build_attempt_id != self.build_attempt.build_attempt_id
                or self.receipt.plan_id != self.plan.plan_id
            ):
                raise ValueError("receipt belongs to another build chain")
            emitted_ids = {
                key: item.emitted_module_id for key, item in emitted.items()
            }
            if self.receipt.emitted_module_ids_by_local_id != emitted_ids:
                raise ValueError("receipt emitted-module index is stale")
            expected_report_id = (
                None
                if self.admission_report is None
                else self.admission_report.report_id
            )
            expected_manifest_id = (
                None if self.manifest is None else self.manifest.manifest_id
            )
            if (
                self.receipt.admission_report_id != expected_report_id
                or self.receipt.manifest_id != expected_manifest_id
            ):
                raise ValueError("receipt optional artifacts are not correlated")
        if self.source_package_files is not None:
            if self.manifest is None:
                raise ValueError("source package evidence requires a manifest")
            actual = {
                path: (
                    digest
                    if isinstance(digest, Sha256Digest)
                    else Sha256Digest(digest)
                )
                for path, digest in self.source_package_files.items()
            }
            expected = _expected_package_files(
                self.build_request,
                self.build_attempt,
                self.plan,
                self.admission_report,
                self.manifest,
                emitted,
            )
            if actual != expected:
                raise ValueError("source package files differ from the typed build chain")
            object.__setattr__(self, "source_package_files", MappingProxyType(actual))


def _expected_package_files(
    build_request: ApprovedBuildRequest,
    build_attempt: BuildAttempt,
    plan: WorkflowMaterializationPlan,
    report: Optional[BuildAdmissionReport],
    manifest: Optional[BuildManifest],
    emitted: Mapping[str, EmittedEpisodeModule],
) -> dict[str, Sha256Digest]:
    if report is None or manifest is None:
        return {}
    records = {
        "APPROVED_BUILD_REQUEST.json": build_request.as_record(),
        "BUILD_ATTEMPT.json": build_attempt.as_record(),
        "MATERIALIZATION_PLAN.json": plan.as_record(),
        "STATIC_ADMISSION.json": report.as_record(),
        "BUILD_MANIFEST.json": manifest.as_record(),
    }
    if manifest.environment_recipe is not None:
        from episode_runtime.target_environment import ENVIRONMENT_RECIPE_PATH

        records[ENVIRONMENT_RECIPE_PATH] = manifest.as_record()["environment_recipe"]
    if manifest.environment_lock is not None:
        records["TARGET_ENVIRONMENT_LOCK.json"] = manifest.as_record()["environment_lock"]
    expected = {
        path: Sha256Digest.of_bytes(canonical_json(record).encode("utf-8"))
        for path, record in records.items()
    }
    for local_id, module in emitted.items():
        expected[_package_module_path(module.module_name)] = module.source_hash
    return dict(sorted(expected.items()))


def _source_symbols(module: EmittedEpisodeModule) -> tuple[SourceSymbolIndexEntry, ...]:
    tree = ast.parse(module.module_source, filename=f"<{module.module_name}>", mode="exec")
    entries: list[SourceSymbolIndexEntry] = []
    counts: dict[str, int] = {}

    def add(node: ast.AST, symbol_path: str, kind: str) -> None:
        count = counts.get(symbol_path, 0)
        counts[symbol_path] = count + 1
        token = symbol_path if count == 0 else f"{symbol_path}#{count + 1}"
        base = f"/episodes/{_pointer_token(module.local_id)}/source_symbols"
        entries.append(
            SourceSymbolIndexEntry(
                episode_local_id=module.local_id,
                module_name=module.module_name,
                symbol_path=token,
                kind=kind,
                lineno=int(getattr(node, "lineno")),
                col_offset=int(getattr(node, "col_offset")),
                end_lineno=int(getattr(node, "end_lineno", getattr(node, "lineno"))),
                end_col_offset=int(
                    getattr(node, "end_col_offset", getattr(node, "col_offset"))
                ),
                source_hash=module.source_hash,
                stable_target=f"{base}/{_pointer_token(token)}",
            )
        )

    def visit(body: list[ast.stmt]) -> None:
        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                add(statement, statement.name, type(statement).__name__)
            elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else (statement.target,)
                )
                for target in targets:
                    if isinstance(target, ast.Name):
                        add(statement, target.id, type(statement).__name__)

    visit(tree.body)
    return tuple(
        sorted(entries, key=lambda item: (item.symbol_path, item.lineno, item.col_offset))
    )


def _function_parameters(function: ast.FunctionDef) -> tuple[str, ...] | None:
    arguments = function.args
    if (
        arguments.posonlyargs
        or arguments.vararg is not None
        or arguments.kwonlyargs
        or arguments.kwarg is not None
        or arguments.defaults
        or arguments.kw_defaults
    ):
        return None
    return tuple(argument.arg for argument in arguments.args)


def _runtime_abi(
    module: EmittedEpisodeModule,
    *,
    is_root: bool,
) -> tuple[dict[str, object], tuple[BuildDeficit, ...]]:
    tree = ast.parse(module.module_source, filename=f"<{module.module_name}>", mode="exec")
    functions = {
        statement.name: statement
        for statement in tree.body
        if isinstance(statement, ast.FunctionDef)
    }
    expected = {
        "build_controller_factory": _BUILD_CONTROLLER_FACTORY_PARAMETERS,
        "build_episode": _BUILD_EPISODE_PARAMETERS,
        **(_ROOT_BUILDERS if is_root else {}),
    }
    observed: dict[str, object] = {}
    deficits: list[BuildDeficit] = []
    for name, parameters in expected.items():
        function = functions.get(name)
        actual = None if function is None else _function_parameters(function)
        observed[name] = None if actual is None else list(actual)
        if actual != parameters:
            deficits.append(
                BuildDeficit(
                    code=(
                        "module_exports_incomplete"
                        if function is None
                        else "builder_signature_invalid"
                    ),
                    field_path=f"module_source.{name}",
                    detail=(
                        f"{name} parameters must be exactly {parameters!r}; "
                        f"received {actual!r}"
                    ),
                    episode_local_id=module.local_id,
                )
            )
    unexpected_root = (
        []
        if is_root
        else sorted(set(_ROOT_BUILDERS).intersection(functions))
    )
    if unexpected_root:
        deficits.append(
            BuildDeficit(
                code="root_builder_on_child",
                field_path="module_source",
                detail=f"child module exports root-only builders {unexpected_root!r}",
                episode_local_id=module.local_id,
            )
        )
    return (
        {
            "expected": {
                name: list(parameters) for name, parameters in expected.items()
            },
            "observed": observed,
            "unexpected_root_exports": unexpected_root,
            "conforms": not deficits,
        },
        tuple(deficits),
    )


def _part(base: str, name: str, value: object) -> SpecificationPart:
    return SpecificationPart(
        stable_target=f"{base}/parts/{_pointer_token(name)}",
        name=name,
        value=value,
    )


def project_materialized_specification(
    inputs: MaterializationInspectionInput,
) -> MaterializedSpecification:
    """Verify and project build evidence without executing generated source."""

    if not isinstance(inputs, MaterializationInspectionInput):
        raise TypeError("inputs must be MaterializationInspectionInput")
    request = inputs.build_request
    attempt = inputs.build_attempt
    plan = inputs.plan
    report = inputs.admission_report
    manifest = inputs.manifest
    receipt = inputs.receipt
    emitted = {item.local_id: item for item in inputs.emitted_modules}
    nodes = {item.local_id: item for item in plan.nodes}
    designs = {
        item.local_id: item
        for item in request.frozen_workflow.workflow.episodes
    }
    edges_by_parent: dict[str, list[object]] = {}
    for edge in plan.all_edges:
        edges_by_parent.setdefault(edge.parent_local_id, []).append(edge.as_record())
    global_base = "/workflow_global"
    workflow_global = (
        _part(global_base, "authority", {
            "authority_approval": request.authority_approval.as_record(),
            "workflow_approval": request.workflow_approval.as_record(),
            "admission_authority": request.admission_authority.as_record(),
        }),
        _part(global_base, "frozen_workflow", request.frozen_workflow.as_record()),
        _part(global_base, "build_request", request.as_record()),
        _part(global_base, "build_attempt", attempt.as_record()),
        _part(global_base, "materialization_plan", plan.as_record()),
        _part(global_base, "outcome", {
            "status": "partial" if receipt is None else receipt.status,
            "receipt_id": None if receipt is None else receipt.receipt_id.value,
            "admission_report_id": None if report is None else report.report_id.value,
            "manifest_id": None if manifest is None else manifest.manifest_id.value,
        }),
    )
    episode_specs: list[EpisodeSpecification] = []
    crosswalk: dict[str, Optional[str]] = {}
    inspection_deficits: list[BuildDeficit] = []
    for local_id in sorted(designs):
        base = f"/episodes/{_pointer_token(local_id)}"
        node = nodes.get(local_id)
        module = emitted.get(local_id)
        episode_id = (
            None
            if manifest is None
            else manifest.episode_ids_by_local_id.get(local_id)
        )
        crosswalk[local_id] = episode_id
        runtime_abi: object = None
        if module is not None:
            runtime_abi, abi_deficits = _runtime_abi(
                module,
                is_root=node is not None and node.parent_local_id is None,
            )
            inspection_deficits.extend(abi_deficits)
        parts = [
            _part(base, "frozen_contract", designs[local_id].as_record()),
            _part(
                base,
                "node_plan",
                None if node is None else node.as_record(),
            ),
            _part(base, "parent_owned_edges", edges_by_parent.get(local_id, [])),
            _part(
                base,
                "materialization_disposition",
                plan.node_dispositions.get(local_id),
            ),
            _part(
                base,
                "emitted_module",
                None if module is None else module.as_record(),
            ),
            _part(base, "runtime_abi", runtime_abi),
            _part(
                base,
                "admission",
                {
                    "source_hash": (
                        None
                        if report is None
                        or local_id not in report.module_source_hashes
                        else report.module_source_hashes[local_id].value
                    ),
                    "episode_id": episode_id,
                },
            ),
        ]
        episode_specs.append(
            EpisodeSpecification(
                local_id=local_id,
                stable_target=base,
                episode_id=episode_id,
                parts=tuple(parts),
                source_symbols=() if module is None else _source_symbols(module),
            )
        )
    deficits: list[ProjectedDeficit] = [
        ProjectedDeficit("plan", item) for item in plan.deficits
    ]
    deficits.extend(
        ProjectedDeficit("inspection", item) for item in inspection_deficits
    )
    if report is not None:
        deficits.extend(ProjectedDeficit("admission", item) for item in report.deficits)
    if receipt is not None:
        deficits.extend(ProjectedDeficit("receipt", item) for item in receipt.deficits)
    expected_package = _expected_package_files(
        request,
        attempt,
        plan,
        report,
        manifest,
        emitted,
    )
    return MaterializedSpecification(
        build_request_id=request.build_request_id,
        build_attempt_id=attempt.build_attempt_id,
        plan_id=plan.plan_id,
        workflow_hash=plan.workflow_hash,
        status="partial" if receipt is None else receipt.status,
        receipt_id=None if receipt is None else receipt.receipt_id,
        admission_report_id=None if report is None else report.report_id,
        manifest_id=None if manifest is None else manifest.manifest_id,
        workflow_global=workflow_global,
        episodes=tuple(episode_specs),
        deficits=tuple(deficits),
        local_id_to_episode_id=crosswalk,
        expected_source_package_files=expected_package,
    )


__all__ = [
    "EpisodeSpecification",
    "MaterializationInspectionInput",
    "MaterializedSpecification",
    "ProjectedDeficit",
    "SourceSymbolIndexEntry",
    "SpecificationPart",
    "project_materialized_specification",
]
