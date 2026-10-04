"""Strict loading and runtime linking for one admitted source package.

Generated modules are read and compiled while the worker can still read its
immutable inputs.  They are executed only after Landlock has been installed.
The linker never imports one generated Episode from another: it owns the
concrete tree, Grain declarations, controller factories, and child closures.
"""

from __future__ import annotations

import ast
import builtins
from contextvars import ContextVar
import importlib
import inspect
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
import stat
import sys
from types import MappingProxyType, ModuleType
from typing import Any, Awaitable, Callable, Mapping, Optional

from agent.duet_contracts import canonical_json, digest_record
from agent.episode_contracts import OpaqueId, Sha256Digest
from episode_builder._contract_base import BuildAttempt
from episode_builder._contract_chain import (
    ApprovedBuildRequest,
    BuildAdmissionReport,
    BuildManifest,
    WorkflowMaterializationPlan,
)
from episode_builder.declaration import (
    DECLARATION_EXPORT,
    build_module_declaration,
)
from episode_library.models import EpisodeLibraryDesign
from episode_library.refinement import execution_bindings, resolve_reference
from function_library.reasoning import HostReceipt
from function_library.refinement import RefinementReceipt
from handoff_library import HandoffPayloadContract
from method_loop import (
    ClosedRecord,
    Context,
    Controller,
    Episode,
    EpisodeCompletion,
    EpisodeGoal,
    EpisodeRequest,
    GoalState,
    Grain,
    Path as EpisodePath,
)
from method_loop.identities import EpisodeRef, normalize_structural_path

from .contracts import RunEventKind, RunRegistration
from .components import ComponentScope, LinkedComponentRun
from .repeatable import admitted_builder, build_declared_tree, declared_call_selections


_METADATA_FILES = MappingProxyType(
    {
        "APPROVED_BUILD_REQUEST.json": ApprovedBuildRequest.from_record,
        "BUILD_ATTEMPT.json": BuildAttempt.from_record,
        "MATERIALIZATION_PLAN.json": WorkflowMaterializationPlan.from_record,
        "STATIC_ADMISSION.json": BuildAdmissionReport.from_record,
        "BUILD_MANIFEST.json": BuildManifest.from_record,
    }
)
_MODULE_EXPORTS = frozenset(
    {
        DECLARATION_EXPORT,
        "REQUEST_PAYLOAD_CONTRACT",
        "RESULT_PAYLOAD_CONTRACT",
        "PROMPTS",
        "EXECUTION_CAPABILITY_NAMES",
        "RESULT_CHANNEL_NAMES",
        "RESULT_CHANNEL_IDS",
        "BINDING",
        "DESIGN",
        "build_controller_factory",
        "build_episode",
    }
)
_BUILD_EPISODE_PARAMETERS = (
    "grain",
    "key",
    "request",
    "goal_view",
    "collaborators",
    "child_builders",
)
_BUILD_CONTROLLER_PARAMETERS = ("goal_view", "collaborators")
_ROOT_BUILDERS = {
    "build_goal_state": ("request", "collaborators"),
    "scope_goal_state": ("goal_state", "goal"),
}


class RuntimeLinkError(RuntimeError):
    """An admitted package cannot be linked to the generic Episode method."""


RunEventSink = Callable[
    [RunEventKind, OpaqueId, Mapping[str, object]],
    Awaitable[None],
]


_CURRENT_RUNTIME_EPISODE_ID: ContextVar[Optional[OpaqueId]] = ContextVar(
    "openchia_runtime_episode_id",
    default=None,
)


_CURRENT_RUNTIME_EPISODE_PATH: ContextVar[
    Optional[tuple[tuple[str, str], ...]]
] = ContextVar(
    "openchia_runtime_episode_path",
    default=None,
)


def current_runtime_episode_id() -> OpaqueId:
    """Return the Episode owning the current generated-code execution context."""

    episode_id = _CURRENT_RUNTIME_EPISODE_ID.get()
    if episode_id is None:
        raise RuntimeLinkError("model transport was called outside an Episode")
    return episode_id


def current_runtime_episode_path() -> list[dict[str, str]]:
    """Return the root-to-leaf structural path of the current Episode.

    Each element is ``{"grain": ..., "key": ...}`` exactly as the linker used
    it to build ``EpisodeRef(run_id, path)``, so the host can recompute the
    same ``episode_id`` from it.
    """

    path = _CURRENT_RUNTIME_EPISODE_PATH.get()
    if path is None:
        raise RuntimeLinkError("HTTP transport was called outside an Episode")
    return [{"grain": grain, "key": key} for grain, key in path]


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise RuntimeLinkError(f"duplicate JSON field {key!r}")
        value[key] = item
    return value


def _reject_constant(value: str) -> object:
    raise RuntimeLinkError(f"non-finite JSON number {value!r} is prohibited")


def _read_regular_file(path: Path, name: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError as exc:
        raise RuntimeLinkError(f"{name} is absent") from exc
    except OSError as exc:
        raise RuntimeLinkError(
            f"{name} cannot be opened without following links"
        ) from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeLinkError(f"{name} must be a regular non-symlink file")
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                raise RuntimeLinkError(f"{name} ended while it was read")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise RuntimeLinkError(f"{name} grew while it was read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_record(path: Path, name: str) -> Mapping[str, object]:
    payload = _read_regular_file(path, name)
    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeLinkError(f"{name} is not strict UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise RuntimeLinkError(f"{name} must contain one JSON object")
    if canonical_json(value).encode("utf-8") != payload:
        raise RuntimeLinkError(f"{name} is not canonically encoded")
    return value


def _module_relative_path(module_name: str) -> str:
    parts = module_name.split(".")
    if any(not part.isidentifier() for part in parts):
        raise RuntimeLinkError("manifest module name is not a dotted identifier")
    return "/".join(parts) + ".py"


def _package_files(root: Path) -> Mapping[str, Path]:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeLinkError("source package must be a real directory")
    files: dict[str, Path] = {}
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root).as_posix()
        if item.is_symlink():
            raise RuntimeLinkError(
                f"source package entry {relative!r} cannot be a symlink"
            )
        if item.is_dir():
            continue
        if not item.is_file():
            raise RuntimeLinkError(
                f"source package entry {relative!r} is not a regular file"
            )
        files[relative] = item
    return MappingProxyType(files)


def _import_names(tree: ast.Module) -> tuple[str, ...]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise RuntimeLinkError("generated modules cannot use relative imports")
            if node.module is None:
                raise RuntimeLinkError("generated import has no absolute module")
            names.add(node.module)
    return tuple(sorted(names))


def _preload_declared_imports(tree: ast.Module) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                importlib.import_module(alias.name)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level or node.module is None:
            raise RuntimeLinkError("generated imports must be absolute")
        fromlist = tuple(alias.name for alias in node.names)
        builtins.__import__(node.module, fromlist=fromlist, level=0)


def _library_implementation_modules(import_names, selected_bindings) -> tuple[str, ...]:
    """Resolve selected definitions exported by already verified library imports.

    LibraryFunction objects carry lazy implementation references. Importing their
    registry does not load those implementations; after Landlock it is too late.
    Inspect trusted exports only, never execute a generated module to discover them.
    """
    from function_library import FunctionLibrary, LibraryFunction

    selected = {item["definition_id"] for item in selected_bindings}
    modules = set()
    for name in import_names:
        for value in tuple(vars(sys.modules[name]).values()):
            if isinstance(value, LibraryFunction):
                definitions = (value,)
            elif isinstance(value, FunctionLibrary):
                definitions = value.functions()
            elif isinstance(value, EpisodeLibraryDesign):
                definitions = value.function_definitions
            else:
                continue
            for definition in definitions:
                if definition.definition_id not in selected:
                    continue
                if definition.implementation is not None:
                    modules.add(definition.implementation.module)
                if definition.evaluation is not None:
                    modules.add(definition.evaluation.implementation.module)
    return tuple(sorted(modules))


def _implementation_modules(tree: ast.Module) -> tuple[str, ...]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        terminal = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else ""
        )
        if terminal != "FunctionImplementation":
            continue
        keywords = {item.arg: item.value for item in node.keywords}
        module = keywords.get("module")
        if not (
            isinstance(module, ast.Constant)
            and isinstance(module.value, str)
            and module.value
        ):
            raise RuntimeLinkError(
                "FunctionImplementation.module must be a literal module name"
            )
        modules.add(module.value)
    return tuple(sorted(modules))


def _memory_only_builtins(import_names: tuple[str, ...]) -> dict[str, object]:
    admitted = frozenset(import_names)

    def memory_import(
        name: str,
        globals: object = None,
        locals: object = None,
        fromlist: object = (),
        level: int = 0,
    ) -> ModuleType:
        del globals, locals
        if level != 0 or name not in admitted:
            raise ImportError(f"generated import {name!r} was not preloaded")
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            raise ImportError(f"preloaded module {name!r} is no longer resident")
        if fromlist:
            if not isinstance(fromlist, (tuple, list)) or any(
                not isinstance(item, str) for item in fromlist
            ):
                raise ImportError("generated import fromlist is malformed")
            return module
        root_name = name.split(".", 1)[0]
        root = sys.modules.get(root_name)
        if not isinstance(root, ModuleType):
            raise ImportError(f"preloaded import root {root_name!r} is absent")
        return root

    namespace = dict(vars(builtins))
    namespace["__import__"] = memory_import
    return namespace


def _signature(function: object, name: str) -> tuple[str, ...]:
    if not callable(function) or inspect.iscoroutinefunction(function):
        raise RuntimeLinkError(f"{name} must be a synchronous callable")
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError) as exc:
        raise RuntimeLinkError(f"{name} has no inspectable signature") from exc
    parameters = tuple(signature.parameters.values())
    if any(
        parameter.kind is not inspect.Parameter.POSITIONAL_OR_KEYWORD
        or parameter.default is not inspect.Parameter.empty
        for parameter in parameters
    ):
        raise RuntimeLinkError(f"{name} must use required positional parameters")
    return tuple(parameter.name for parameter in parameters)


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise RuntimeLinkError("runtime evidence contains a non-finite number")
        return value
    if hasattr(value, "as_record"):
        return _json_value(value.as_record())
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return {
        "unprojected_type": (
            f"{type(value).__module__}.{type(value).__qualname__}"
        )
    }


@dataclass(frozen=True)
class PreparedModule:
    local_id: str
    module_name: str
    relative_path: str
    source_hash: Sha256Digest
    import_names: tuple[str, ...]
    implementation_modules: tuple[str, ...]
    code: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class PreparedSourcePackage:
    """Verified and compiled package whose generated code has not executed."""

    registration: RunRegistration
    build_request: ApprovedBuildRequest
    build_attempt: BuildAttempt
    plan: WorkflowMaterializationPlan
    admission_report: BuildAdmissionReport
    manifest: BuildManifest
    modules: Mapping[str, PreparedModule]

    def __post_init__(self) -> None:
        object.__setattr__(self, "modules", MappingProxyType(dict(self.modules)))

    def activate(self) -> "ActivatedSourcePackage":
        """Execute admitted code after the caller has installed confinement."""

        activated: dict[str, ActivatedModule] = {}
        inserted: list[str] = []
        try:
            for node in self.plan.nodes:
                prepared = self.modules[node.local_id]
                required_resident = set(prepared.import_names) | (
                    set(prepared.implementation_modules)
                    - {prepared.module_name}
                )
                missing_resident = sorted(
                    name
                    for name in required_resident
                    if not isinstance(sys.modules.get(name), ModuleType)
                )
                if missing_resident:
                    raise RuntimeLinkError(
                        "pre-Landlock module residency changed: "
                        f"{missing_resident!r}"
                    )
                if prepared.module_name in sys.modules:
                    raise RuntimeLinkError(
                        f"generated module name {prepared.module_name!r} is occupied"
                    )
                module = ModuleType(prepared.module_name)
                module.__file__ = f"<admitted:{prepared.relative_path}>"
                module.__package__ = prepared.module_name.rpartition(".")[0]
                module.__dict__["__builtins__"] = _memory_only_builtins(
                    prepared.import_names
                )
                sys.modules[prepared.module_name] = module
                inserted.append(prepared.module_name)
                exec(prepared.code, module.__dict__, module.__dict__)
                activated[node.local_id] = _validate_activated_module(
                    module=module,
                    node=node,
                    plan=self.plan,
                    build_request=self.build_request,
                )
        except BaseException:
            for module_name in reversed(inserted):
                sys.modules.pop(module_name, None)
            raise
        return ActivatedSourcePackage(
            registration=self.registration,
            build_request=self.build_request,
            plan=self.plan,
            manifest=self.manifest,
            modules=activated,
        )


@dataclass(frozen=True)
class ActivatedModule:
    local_id: str
    module: ModuleType = field(repr=False, compare=False)
    binding: object
    design: EpisodeLibraryDesign


def _validate_activated_module(
    *,
    module: ModuleType,
    node: object,
    plan: WorkflowMaterializationPlan,
    build_request: ApprovedBuildRequest,
) -> ActivatedModule:
    missing = sorted(name for name in _MODULE_EXPORTS if not hasattr(module, name))
    root_only = node.parent_local_id is None
    required_builders = {
        "build_controller_factory": _BUILD_CONTROLLER_PARAMETERS,
        "build_episode": _BUILD_EPISODE_PARAMETERS,
        **(_ROOT_BUILDERS if root_only else {}),
    }
    missing.extend(name for name in required_builders if not hasattr(module, name))
    if missing:
        raise RuntimeLinkError(
            f"generated module {module.__name__!r} omits exports {sorted(set(missing))!r}"
        )
    if not root_only and any(hasattr(module, name) for name in _ROOT_BUILDERS):
        raise RuntimeLinkError("a child module exposes root-only goal builders")
    for name, parameters in required_builders.items():
        if _signature(getattr(module, name), name) != parameters:
            raise RuntimeLinkError(
                f"{module.__name__}.{name} has another runtime ABI"
            )

    from method_loop import EpisodeBindingDeclaration

    binding = module.BINDING
    design = module.DESIGN
    if not isinstance(binding, EpisodeBindingDeclaration):
        raise RuntimeLinkError("BINDING is not an EpisodeBindingDeclaration")
    if not isinstance(design, EpisodeLibraryDesign) or design.binding != binding:
        raise RuntimeLinkError("DESIGN does not exactly contain BINDING")
    if any(not definition.executable for definition in design.function_definitions):
        raise RuntimeLinkError("runtime DESIGN contains a non-executable function")
    for definition in design.function_definitions:
        implementation = definition.implementation
        if implementation is None or implementation.module not in sys.modules:
            raise RuntimeLinkError(
                "runtime function implementation was not preloaded before Landlock"
            )
        evaluation = definition.evaluation
        if (
            evaluation is not None
            and evaluation.implementation.module not in sys.modules
        ):
            raise RuntimeLinkError(
                "runtime function evaluator was not preloaded before Landlock"
            )
        definition.load()

    frozen = next(
        item
        for item in build_request.frozen_workflow.workflow.episodes
        if item.local_id == node.local_id
    )
    if (
        binding.grain_name != node.grain_name
        or binding.interface != node.interface
        or binding.topology_role.value != node.topology_role
        or binding.goal != frozen.contract.goal
        or binding.unit != frozen.contract.unit
        or binding.result != frozen.contract.result
        or binding.progress != frozen.contract.progress
        or binding.stopping != frozen.contract.stopping
    ):
        raise RuntimeLinkError("BINDING changes the frozen node contract")

    planned_bindings = {
        str(item["role"]): item
        for item in node.selected_function_bindings
    }
    numeric_bindings = (
        ("controller.rarefaction", binding.controller.rarefaction),
        ("controller.continuation", binding.controller.continuation),
    )
    if resolve_reference(frozen.episode_reference) is not None:
        try:
            numeric_bindings += execution_bindings(binding)
        except KeyError as exc:
            raise RuntimeLinkError("BINDING omits a fixed refinement adapter") from exc
    if frozen.contract.epistemic is not None:
        components = {item.name: item for item in binding.components}
        for role in frozen.contract.epistemic.components:
            name = f"epistemic_{role}"
            if name not in components:
                raise RuntimeLinkError(f"BINDING omits frozen epistemic component {role}")
            numeric_bindings += ((f"component.{name}", components[name]),)
    try:
        numeric_bindings += declared_call_selections(
            binding, tuple(edge for edge in plan.repeatable_calls if edge.parent_local_id == node.local_id),
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeLinkError("BINDING changes an approved repeatable call") from exc
    semantic_fields = (
        "library",
        "function_id",
        "interface",
        "definition_id",
        "arguments",
    )
    for role, selection in numeric_bindings:
        planned = planned_bindings.get(role)
        if planned is None:
            raise RuntimeLinkError(
                f"materialization plan omits Architecture-owned {role}"
            )
        actual = selection.as_record()
        expected_semantics = {
            field: _json_value(planned[field])
            for field in semantic_fields
        }
        actual_semantics = {
            field: _json_value(actual[field])
            for field in semantic_fields
        }
        if canonical_json(expected_semantics) != canonical_json(actual_semantics):
            raise RuntimeLinkError(
                f"BINDING changes Architecture-owned {role} function or arguments"
            )

    exact_literals = {
        "PROMPTS": node.prompt_specs,
        "EXECUTION_CAPABILITY_NAMES": node.capability_names,
        "RESULT_CHANNEL_NAMES": node.result_channel_names,
        "RESULT_CHANNEL_IDS": node.result_channel_ids,
    }
    for name, expected in exact_literals.items():
        if canonical_json({"value": _json_value(getattr(module, name))}) != canonical_json(
            {"value": _json_value(expected)}
        ):
            raise RuntimeLinkError(f"{name} differs from the materialization plan")
    if not isinstance(module.REQUEST_PAYLOAD_CONTRACT, HandoffPayloadContract):
        raise RuntimeLinkError("REQUEST_PAYLOAD_CONTRACT has another type")
    if not isinstance(module.RESULT_PAYLOAD_CONTRACT, HandoffPayloadContract):
        raise RuntimeLinkError("RESULT_PAYLOAD_CONTRACT has another type")
    if (
        module.REQUEST_PAYLOAD_CONTRACT.as_record()
        != _json_value(node.request_payload_contract)
        or module.RESULT_PAYLOAD_CONTRACT.as_record()
        != _json_value(node.result_payload_contract)
    ):
        raise RuntimeLinkError("payload contracts differ from the admitted plan")
    edges = tuple(edge for edge in plan.all_edges if edge.parent_local_id == node.local_id)
    expected_declaration = build_module_declaration(frozen.contract, node, edges)
    if getattr(module, DECLARATION_EXPORT) != expected_declaration:
        raise RuntimeLinkError("host declaration differs from the admitted plan")
    return ActivatedModule(
        local_id=node.local_id,
        module=module,
        binding=binding,
        design=design,
    )


def prepare_source_package(
    registration: RunRegistration,
    source_package_path: str | Path,
) -> PreparedSourcePackage:
    """Verify, compile, and preload one exact Builder source package."""

    if not isinstance(registration, RunRegistration):
        raise TypeError("registration must be a RunRegistration")
    supplied_root = Path(source_package_path).expanduser()
    if supplied_root.is_symlink():
        raise RuntimeLinkError("source package path cannot be a symlink")
    root = supplied_root.resolve(strict=True)
    if root.name != registration.manifest_id.value:
        raise RuntimeLinkError("source package directory does not name the manifest")
    package_files = _package_files(root)
    records: dict[str, object] = {}
    for filename, loader in _METADATA_FILES.items():
        if filename not in package_files:
            raise RuntimeLinkError(f"source package omits {filename}")
        try:
            records[filename] = loader(
                _read_record(package_files[filename], filename)
            )
        except (TypeError, ValueError) as exc:
            raise RuntimeLinkError(f"{filename} failed typed validation") from exc

    build_request = records["APPROVED_BUILD_REQUEST.json"]
    build_attempt = records["BUILD_ATTEMPT.json"]
    plan = records["MATERIALIZATION_PLAN.json"]
    report = records["STATIC_ADMISSION.json"]
    manifest = records["BUILD_MANIFEST.json"]
    assert isinstance(build_request, ApprovedBuildRequest)
    assert isinstance(build_attempt, BuildAttempt)
    assert isinstance(plan, WorkflowMaterializationPlan)
    assert isinstance(report, BuildAdmissionReport)
    assert isinstance(manifest, BuildManifest)
    try:
        plan.validate_against(build_request, build_attempt)
        report.validate_against(plan)
        manifest.validate_against(plan, report)
    except (TypeError, ValueError) as exc:
        raise RuntimeLinkError("source package build chain is invalid") from exc
    if not report.admitted:
        raise RuntimeLinkError("source package was not statically admitted")
    if registration.execution_scope is not None:
        scope = registration.execution_scope
        scope.validate_plan(plan)
        workflow_hash = scope.workflow_hash
        if workflow_hash != registration.workflow_hash.value:
            raise RuntimeLinkError("selected boundary belongs to a different approved workflow")

    frozen = build_request.frozen_workflow
    authority = build_request.admission_authority
    authority_head = build_request.authority_approval
    workflow_approval = build_request.workflow_approval
    if (
        build_request.build_request_id != registration.build_request_id
        or build_attempt.build_attempt_id != registration.build_attempt_id
        or manifest.manifest_id != registration.manifest_id
        or digest_record(manifest.as_record()) != registration.manifest_hash
        or frozen.duet_id != registration.duet_id
        or frozen.artifact_id != registration.workflow_id
        or frozen.workflow_hash != registration.workflow_hash
        or authority.authority_id != registration.admission_authority_id
        or authority.content_hash != registration.admission_authority_hash
        or authority_head.approval_id != registration.authority_head_approval_id
        or digest_record(authority_head.as_record())
        != registration.authority_head_approval_hash
        or workflow_approval.approval_id != registration.workflow_approval_id
        or digest_record(workflow_approval.as_record())
        != registration.workflow_approval_hash
    ):
        raise RuntimeLinkError("source package differs from the Run registration")

    expected_paths = set(_METADATA_FILES)
    prepared: dict[str, PreparedModule] = {}
    generated_names = {node.module_name for node in plan.nodes}
    for node in plan.nodes:
        relative = _module_relative_path(node.module_name)
        expected_paths.add(relative)
        path = package_files.get(relative)
        if path is None:
            raise RuntimeLinkError(f"source package omits module {node.module_name!r}")
        source = _read_regular_file(path, f"module {node.module_name}")
        digest = Sha256Digest.of_bytes(source)
        if (
            digest != manifest.module_hashes_by_local_id[node.local_id]
            or digest != report.module_source_hashes[node.local_id]
        ):
            raise RuntimeLinkError(
                f"module {node.module_name!r} differs from its manifest"
            )
        try:
            text = source.decode("utf-8", errors="strict")
            tree = ast.parse(text, filename=f"<admitted:{relative}>", mode="exec")
            code = compile(
                tree,
                filename=f"<admitted:{relative}>",
                mode="exec",
                dont_inherit=True,
            )
        except (UnicodeDecodeError, SyntaxError) as exc:
            raise RuntimeLinkError(
                f"admitted module {node.module_name!r} cannot be compiled"
            ) from exc
        imports = _import_names(tree)
        if set(imports) & generated_names:
            raise RuntimeLinkError("generated modules cannot import each other")
        _preload_declared_imports(tree)
        implementation_modules = tuple(sorted(
            set(_implementation_modules(tree))
            | set(_library_implementation_modules(imports, node.selected_function_bindings))
        ))
        for imported in implementation_modules:
            if imported == node.module_name:
                continue
            importlib.import_module(imported)
        prepared[node.local_id] = PreparedModule(
            local_id=node.local_id,
            module_name=node.module_name,
            relative_path=relative,
            source_hash=digest,
            import_names=imports,
            implementation_modules=implementation_modules,
            code=code,
        )
    if set(package_files) != expected_paths:
        unknown = sorted(set(package_files) - expected_paths)
        missing = sorted(expected_paths - set(package_files))
        raise RuntimeLinkError(
            f"source package file set differs: missing={missing!r}, unknown={unknown!r}"
        )
    package = PreparedSourcePackage(
        registration=registration,
        build_request=build_request,
        build_attempt=build_attempt,
        plan=plan,
        admission_report=report,
        manifest=manifest,
        modules=prepared,
    )
    baseline = getattr(registration.execution_scope, "learning_baseline", None)
    if baseline is not None:
        from .testing.reconstruction_source import admit_reasoning_unit_source

        try:
            admission = admit_reasoning_unit_source(
                package, source_package_path=root,
                entry_local_id=registration.execution_scope.entry_local_id,
            )
        except ValueError as exc:
            raise RuntimeLinkError(f"later-unit source restoration unavailable: {exc}") from exc
        if canonical_json(admission) != canonical_json(baseline["source_admission"]):
            raise RuntimeLinkError("saved learning source admission differs from the prepared package")
    return package


class _GoalViewRegistry:
    def __init__(self) -> None:
        self._by_path: dict[EpisodePath, Mapping[str, object]] = {}

    def register(self, path: EpisodePath, view: object) -> None:
        if type(view) is not MappingProxyType:
            raise RuntimeLinkError(
                "scope_goal_state must return an exact MappingProxyType view"
            )
        known = self._by_path.get(path)
        if known is not None and known != view:
            raise RuntimeLinkError("one Episode path received two goal views")
        self._by_path[path] = view

    def require(self, path: EpisodePath) -> Mapping[str, object]:
        try:
            return self._by_path[path]
        except KeyError as exc:
            raise RuntimeLinkError(
                "controller opened before its exact goal view was registered"
            ) from exc


@dataclass(frozen=True)
class _InstrumentedEpisode(Episode):
    runtime_episode_id: OpaqueId = field(default=None)  # type: ignore[assignment]
    runtime_event_sink: RunEventSink = field(default=None, repr=False)  # type: ignore[assignment]
    runtime_episode_path: tuple[tuple[str, str], ...] = field(default=None)  # type: ignore[assignment]
    runtime_boundary: Callable[[], Mapping[str, object]] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.runtime_episode_id, OpaqueId):
            raise TypeError("runtime_episode_id must be an OpaqueId")
        object.__setattr__(
            self,
            "runtime_episode_path",
            normalize_structural_path(self.runtime_episode_path),
        )
        if not callable(self.runtime_event_sink):
            raise TypeError("runtime_event_sink must be callable")
        if not callable(self.runtime_boundary):
            raise TypeError("runtime_boundary must be callable")

    def run(self, ctx: Context):  # type: ignore[override]
        del ctx
        raise RuntimeLinkError("isolated runtime Episodes must run asynchronously")

    async def run_async(self, ctx: Context):  # type: ignore[override]
        return await self._run_runtime(ctx)

    async def run_unit_async(self, ctx: Context, *, expected_label: str, starting_unit_index: int = 0):
        return await self._run_runtime(ctx, unit_label=expected_label, starting_unit_index=starting_unit_index)

    async def _run_runtime(self, ctx, *, unit_label=None, starting_unit_index=0):
        token = _CURRENT_RUNTIME_EPISODE_ID.set(self.runtime_episode_id)
        path_token = _CURRENT_RUNTIME_EPISODE_PATH.set(self.runtime_episode_path)
        try:
            await self.runtime_event_sink(
                RunEventKind.EPISODE_STARTED,
                self.runtime_episode_id,
                {
                    "grain": self.grain.name,
                    "key": self.key,
                    "episode_path": [{"grain": grain, "key": key} for grain, key in self.runtime_episode_path],
                    "request": self.request.as_record(),
                    **self.runtime_boundary(),
                },
            )
            if unit_label is not None:
                return await super().run_unit_async(ctx, expected_label=unit_label, starting_unit_index=starting_unit_index)
            record = await super().run_async(ctx)
            await self.runtime_event_sink(
                RunEventKind.EPISODE_COMPLETED,
                self.runtime_episode_id,
                {
                    "ended_by": record.ended_by,
                    "end_reason": record.end_reason,
                    "units_consumed": record.units_consumed,
                    "controller_state": _json_value(record.controller_state),
                },
            )
            return record
        finally:
            _CURRENT_RUNTIME_EPISODE_PATH.reset(path_token)
            _CURRENT_RUNTIME_EPISODE_ID.reset(token)


@dataclass
class LinkedEpisodeRun:
    registration: RunRegistration
    root_episode: Episode
    context: Context

    async def run(self) -> Mapping[str, object]:
        scope = self.registration.execution_scope
        if scope is not None and scope.kind == "unit":
            from .units import unit_projection

            record = await self.root_episode.run_unit_async(
                self.context, expected_label=scope.unit_label,
                starting_unit_index=scope.unit_ref["unit_index"],
            )
            return {
                "outcome": "succeeded",
                "execution_scope": scope.as_record(),
                "unit_result": unit_projection(record),
                "limitations": [
                    "One selected unit was observed; the containing Episode was not completed or accepted.",
                    "Its controller decision is reported unchanged; experiment scope is not an Episode stopping rule.",
                ],
            }
        record = await self.root_episode.run_async(self.context)
        result = self.root_episode.build_result(record)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, ClosedRecord):
            raise RuntimeLinkError("root build_result must return a ClosedRecord")
        completion = EpisodeCompletion.from_record(record)
        outcome = "succeeded"
        if isinstance(record.controller_state, HostReceipt):
            outcome = record.controller_state.record["terminal_state"]
            outcome = "succeeded" if outcome == "completed" else "blocked"
        if isinstance(record.controller_state, RefinementReceipt):
            # Yield exhaustion is a valid return, not proof that the build works.
            outcome = "succeeded" if record.controller_state.record["disposition"] == "attained" else "blocked"
        return MappingProxyType(
            {
                "outcome": outcome,
                "root_episode_id": record.episode_id,
                "completion": completion.as_record(),
                "workflow_result": _json_value(result),
                **({"execution_scope": self.registration.execution_scope.as_record()} if self.registration.execution_scope is not None else {}),
            }
        )


@dataclass(frozen=True)
class ActivatedSourcePackage:
    registration: RunRegistration
    build_request: ApprovedBuildRequest
    plan: WorkflowMaterializationPlan
    manifest: BuildManifest
    modules: Mapping[str, ActivatedModule]

    def __post_init__(self) -> None:
        object.__setattr__(self, "modules", MappingProxyType(dict(self.modules)))

    def link(
        self,
        *,
        event_sink: RunEventSink,
        collaborators: Mapping[str, object] = MappingProxyType({}),
    ) -> LinkedEpisodeRun | LinkedComponentRun:
        if not callable(event_sink):
            raise TypeError("event_sink must be callable")
        if not isinstance(collaborators, Mapping):
            raise TypeError("collaborators must be a mapping")
        collaborators = MappingProxyType(dict(collaborators))
        expected_capabilities = {
            name for node in self.plan.nodes for name in node.capability_names
        }
        if set(collaborators) != expected_capabilities:
            raise RuntimeLinkError(
                "runtime collaborators must exactly cover admitted capabilities"
            )

        scope = self.registration.execution_scope
        if isinstance(scope, ComponentScope):
            scope.validate_plan(self.plan)
            definitions = self.modules[scope.entry_local_id].design.function_definitions
            definition = next((item for item in definitions if item.definition_id == scope.binding["definition_id"]), None)
            if definition is None:
                raise RuntimeLinkError("component is absent from the admitted module design")
            return LinkedComponentRun(self.registration, definition, event_sink)

        registry = _GoalViewRegistry()
        node_by_id = {node.local_id: node for node in self.plan.nodes}
        root_node = node_by_id[self.plan.root_local_id]
        root_module = self.modules[root_node.local_id].module
        context_holder: dict[str, Context] = {}

        grains: dict[str, Grain] = {}
        for node in self.plan.nodes:
            activated = self.modules[node.local_id]

            def controller_factory(
                path: EpisodePath,
                *,
                activated: ActivatedModule = activated,
            ) -> Controller:
                goal_view = registry.require(path)
                factory = activated.module.build_controller_factory(
                    goal_view,
                    collaborators,
                )
                if not callable(factory):
                    raise RuntimeLinkError(
                        "build_controller_factory must return ControllerFactory"
                    )
                controller = factory(path)
                if not isinstance(controller, Controller):
                    raise RuntimeLinkError(
                        "ControllerFactory returned another runtime type"
                    )
                if getattr(scope, "learning_baseline", None) is not None:
                    from function_library.reasoning import HostReceiptController

                    if type(controller) is not HostReceiptController:
                        raise RuntimeLinkError("saved learning requires the stock receipt controller")
                    controller.observe(
                        "inherited-state", HostReceipt(scope.learning_baseline["controller_state"]),
                        is_root=len(path) == 1,
                    )
                return controller

            grains[node.local_id] = Grain(
                name=activated.binding.grain_name,
                unit=activated.binding.unit,
                result=activated.binding.result,
                controller=controller_factory,
            )

        edges_by_parent: dict[str, dict[str, str]] = {}
        edge_by_slot = {}
        for edge in self.plan.all_edges:
            edges_by_parent.setdefault(edge.parent_local_id, {})[
                edge.slot_name
            ] = edge.child_local_id
            edge_by_slot[(edge.parent_local_id, edge.slot_name)] = edge
        tree = build_declared_tree(self.plan, grains)

        from .scoped import initial_launch, restore_entry
        goal_state = root_module.build_goal_state(
            initial_launch(self.registration),
            collaborators,
        )
        if not isinstance(goal_state, GoalState):
            raise RuntimeLinkError("build_goal_state must return GoalState")
        initial_goal_state_id = goal_state.state_id
        entry_id, root_request, root_path, root_view = restore_entry(
            self.registration, self.plan, root_module, goal_state,
        )
        root_key = root_path[-1][1]
        registry.register(root_path, root_view)

        context = Context(
            tree=tree,
            run_id=self.registration.logical_run_id.value,
            goal_state=goal_state,
            boundary_path=root_path[:-1],
        )
        context_holder["context"] = context

        def build_node(
            local_id: str,
            key: str,
            request: EpisodeRequest,
            goal_view: object,
            supplied_collaborators: Mapping[str, object],
        ) -> Episode:
            if not isinstance(key, str) or not key:
                raise RuntimeLinkError("Episode key must be non-empty text")
            if not isinstance(request, EpisodeRequest):
                raise RuntimeLinkError("child builder requires EpisodeRequest")
            if (
                not isinstance(supplied_collaborators, Mapping)
                or dict(supplied_collaborators) != dict(collaborators)
            ):
                raise RuntimeLinkError("child builder collaborators changed")
            node = node_by_id[local_id]
            if self.registration.execution_scope is not None and local_id not in self.registration.execution_scope.included_local_ids:
                raise RuntimeLinkError("child construction exceeds the selected execution scope")
            activated = self.modules[local_id]
            current_path = tuple(context_holder["context"].path)
            path = current_path + ((grains[local_id].name, key),) if current_path else root_path
            child_builders: dict[str, Callable[..., Episode]] = {}
            for slot_name, child_id in edges_by_parent.get(local_id, {}).items():

                def child_builder(
                    child_key: str,
                    child_request: EpisodeRequest,
                    supplied_view: object,
                    child_collaborators: Mapping[str, object],
                    *,
                    child_id: str = child_id,
                ) -> Episode:
                    current = context_holder["context"].path
                    if tuple(current) != path:
                        raise RuntimeLinkError(
                            "child builder was called outside its owning parent Context"
                        )
                    child_node = node_by_id[child_id]
                    recomputed = root_module.scope_goal_state(
                        goal_state,
                        child_request.goal,
                    )
                    if type(supplied_view) is not MappingProxyType or supplied_view != recomputed:
                        raise RuntimeLinkError(
                            "supplied child goal view differs from root scoping"
                        )
                    child_path = tuple(current) + (
                        (grains[child_id].name, str(child_key)),
                    )
                    registry.register(child_path, recomputed)
                    return build_node(
                        child_node.local_id,
                        child_key,
                        child_request,
                        recomputed,
                        child_collaborators,
                    )

                edge = edge_by_slot[(local_id, slot_name)]
                child_builders[slot_name] = (
                    child_builder if edge.repeatable_call is None else admitted_builder(
                        edge=edge, parent_path=path, parent_request=request,
                        run_id=self.registration.logical_run_id.value, child_grain=grains[child_id],
                        definitions=activated.design.function_definitions,
                        current_path=lambda: context_holder["context"].path,
                        construct=child_builder,
                    )
                )

            episode = activated.module.build_episode(
                grains[local_id],
                key,
                request,
                goal_view,
                collaborators,
                MappingProxyType(child_builders),
            )
            if not isinstance(episode, Episode):
                raise RuntimeLinkError("build_episode must return Episode")
            if (
                episode.grain != grains[local_id]
                or episode.key != key
                or episode.request != request
            ):
                raise RuntimeLinkError(
                    "build_episode changed its supplied Grain, key, or request"
                )
            expected_slots = set(node.child_slot_names)
            if set(child_builders) != expected_slots:
                raise RuntimeLinkError("runtime child builders differ from the plan")
            runtime_ref = EpisodeRef(
                run_id=self.registration.logical_run_id.value,
                path=path,
            )
            runtime_episode_id = OpaqueId(runtime_ref.episode_id)
            runtime_path = runtime_ref.path

            prior_on_unit = episode.on_unit
            prior_build_result = episode.build_result
            if getattr(scope, "learning_baseline", None) is not None:
                from function_library.reasoning import ReasoningGoalState, ReasoningSource

                if (
                    type(episode.source) is not ReasoningSource
                    or type(goal_state) is not ReasoningGoalState
                    or episode.resume_units
                    or prior_on_unit is not None
                    or episode.on_close is not None
                ):
                    raise RuntimeLinkError("saved learning requires stock reasoning state without custom hooks")

            async def on_unit(item: object, contribution: object, view: object) -> None:
                from .units import unit_projection
                if prior_on_unit is not None:
                    prior = prior_on_unit(item, contribution, view)
                    if inspect.isawaitable(prior):
                        await prior
                await event_sink(
                    RunEventKind.UNIT_COMPLETED,
                    runtime_episode_id,
                    unit_projection(view),
                )

            async def build_result(record: object) -> ClosedRecord:
                token = _CURRENT_RUNTIME_EPISODE_ID.set(runtime_episode_id)
                path_token = _CURRENT_RUNTIME_EPISODE_PATH.set(runtime_path)
                try:
                    result = prior_build_result(record)
                    if inspect.isawaitable(result):
                        result = await result
                    if not isinstance(result, ClosedRecord):
                        raise RuntimeLinkError(
                            "build_result must return an admitted ClosedRecord"
                        )
                    return result
                finally:
                    _CURRENT_RUNTIME_EPISODE_PATH.reset(path_token)
                    _CURRENT_RUNTIME_EPISODE_ID.reset(token)

            return _InstrumentedEpisode(
                grain=episode.grain,
                key=episode.key,
                source=episode.source,
                request=episode.request,
                build_result=build_result,
                on_unit=on_unit,
                on_close=episode.on_close,
                resume_units=episode.resume_units,
                runtime_episode_id=runtime_episode_id,
                runtime_event_sink=event_sink,
                runtime_episode_path=runtime_path,
                runtime_boundary=lambda: {
                    "goal_state_id": goal_state.state_id,
                    "initial_goal_state_id": initial_goal_state_id,
                    "goal_view": _json_value(registry.require(path)),
                },
            )

        root_episode = build_node(
            entry_id,
            root_key,
            root_request,
            root_view,
            collaborators,
        )
        return LinkedEpisodeRun(
            registration=self.registration,
            root_episode=root_episode,
            context=context,
        )


__all__ = [
    "ActivatedSourcePackage",
    "LinkedEpisodeRun",
    "PreparedSourcePackage",
    "RunEventSink",
    "RuntimeLinkError",
    "current_runtime_episode_id",
    "current_runtime_episode_path",
    "prepare_source_package",
]
