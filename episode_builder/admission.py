"""Non-executing admission for materialized Episode module source.

Build admission compiles and inspects syntax trees only. Generated Python is
an inert, content-addressed artifact at this boundary: importing it, resolving
its callables, constructing a Grain, and constructing an Episode all belong to
a later isolated runtime worker.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

from agent.episode_contracts import OpaqueId, Sha256Digest

from ._contract_base import (
    BuildAttempt,
    BuildDeficit,
    EmittedEpisodeModule,
)
from ._contract_chain import (
    ApprovedBuildRequest,
    BuildAdmissionReport,
    WorkflowMaterializationPlan,
)
from ._contract_plan import (
    EdgeMaterializationPlan,
    NodeMaterializationPlan,
)
from .declaration import DECLARATION_EXPORT, build_module_declaration


_EPISODE_ID = re.compile(r"^episode_[0-9a-f]{64}$")
_FUNCTION_DEFINITION_ID = re.compile(r"^function_[0-9a-f]{64}$")
_REQUIRED_VALUES = frozenset(
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
_BUILD_CONTROLLER_FACTORY_PARAMETERS = ("goal_view", "collaborators")
_ROOT_BUILDERS = {
    "build_goal_state": ("request", "collaborators"),
    "scope_goal_state": ("goal_state", "goal"),
}
ADMITTED_IMPORT_ROOTS = frozenset(
    {
        "__future__",
        "collections",
        "copy",
        "dataclasses",
        "decimal",
        "enum",
        "episode_library",
        "fractions",
        "function_library",
        "functools",
        "handoff_library",
        "hashlib",
        "http_call_library",
        "itertools",
        "json",
        "llm_call_library",
        "math",
        "method_loop",
        "numeric_control_library",
        "operator",
        "question_table_goal_library",
        "re",
        "statistics",
        "typing",
        "types",
    }
)
INTERNAL_IMPLEMENTATION_ROOTS = frozenset(
    {
        "function_library",
        "handoff_library",
        "http_call_library",
        "llm_call_library",
        "method_loop",
        "numeric_control_library",
        "question_table_goal_library",
    }
)
# Private aliases retained for existing call sites; the public names above are
# the single source of truth that the emitter shows the authoring model.
_ALLOWED_IMPORT_ROOTS = ADMITTED_IMPORT_ROOTS
_INTERNAL_IMPLEMENTATION_ROOTS = INTERNAL_IMPLEMENTATION_ROOTS
_FORBIDDEN_CALL_NAMES = frozenset(
    {
        "__import__",
        "breakpoint",
        "compile",
        "eval",
        "exec",
        "globals",
        "input",
        "locals",
        "open",
        "vars",
    }
)
_FORBIDDEN_CALL_ATTRIBUTES = frozenset(
    {
        "exec",
        "fork",
        "import_module",
        "load",
        "popen",
        "rmdir",
        "rmtree",
        "spawn",
        "system",
        "unlink",
        "urlopen",
        "write_bytes",
        "write_text",
    }
)
_FORBIDDEN_ATTRIBUTES = frozenset(
    {
        "__builtins__",
        "__class__",
        "__code__",
        "__dict__",
        "__globals__",
        "__loader__",
        "__spec__",
        "__subclasses__",
    }
)


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _canonical(value: object) -> str:
    return json.dumps(
        _plain(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _detail(value: object) -> str:
    return " ".join(str(value).replace("\x00", " ").split())[:2000] or (
        "unspecified admission failure"
    )


def _deficit(
    code: str,
    field_path: str,
    detail: object,
    *,
    local_id: str | None = None,
) -> BuildDeficit:
    return BuildDeficit(
        code=code,
        field_path=field_path,
        detail=_detail(detail),
        episode_local_id=local_id,
    )


def _assigned_values(tree: ast.Module) -> dict[str, list[ast.expr]]:
    result: dict[str, list[ast.expr]] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name):
                    result.setdefault(target.id, []).append(statement.value)
        elif isinstance(statement, ast.AnnAssign) and isinstance(
            statement.target,
            ast.Name,
        ):
            if statement.value is not None:
                result.setdefault(statement.target.id, []).append(statement.value)
    return result


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


def _mapping_proxy_call(value: ast.AST | None) -> bool:
    return bool(
        isinstance(value, ast.Call)
        and (
            (isinstance(value.func, ast.Name) and value.func.id == "MappingProxyType")
            or (
                isinstance(value.func, ast.Attribute)
                and value.func.attr == "MappingProxyType"
            )
        )
    )


def _scope_goal_state_error(function: ast.FunctionDef) -> str | None:
    proxy_names = {
        target.id
        for statement in ast.walk(function)
        if isinstance(statement, ast.Assign)
        and _mapping_proxy_call(statement.value)
        for target in statement.targets
        if isinstance(target, ast.Name)
    }
    returns = [item for item in ast.walk(function) if isinstance(item, ast.Return)]
    if not returns or any(
        not (
            _mapping_proxy_call(item.value)
            or (
                isinstance(item.value, ast.Name)
                and item.value.id in proxy_names
            )
        )
        for item in returns
    ):
        return "every explicit return must be a freshly constructed MappingProxyType"
    if not any(
        isinstance(item, ast.Name)
        and item.id == "goal"
        and isinstance(item.ctx, ast.Load)
        for item in ast.walk(function)
    ):
        return "scope_goal_state must use the supplied goal when scoping the view"
    mutators = {
        "append",
        "clear",
        "extend",
        "insert",
        "pop",
        "remove",
        "setdefault",
        "sort",
        "update",
    }
    for item in ast.walk(function):
        if (
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and isinstance(item.func.value, ast.Name)
            and item.func.value.id == "goal_state"
            and item.func.attr in mutators
        ):
            return "scope_goal_state cannot mutate goal_state"
        if isinstance(item, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
            targets = (
                item.targets
                if isinstance(item, ast.Assign)
                else (
                    tuple(item.targets)
                    if isinstance(item, ast.Delete)
                    else (item.target,)
                )
            )
            for target in targets:
                root = target
                while isinstance(root, (ast.Attribute, ast.Subscript)):
                    root = root.value
                if isinstance(root, ast.Name) and root.id == "goal_state":
                    return "scope_goal_state cannot mutate goal_state"
    return None


def _imported_modules(tree: ast.Module) -> tuple[str, ...]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                modules.append("." * node.level + (node.module or ""))
            elif node.module is not None:
                modules.append(node.module)
    return tuple(modules)


def _call_terminal_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return ""


def _literal_assignment(
    assigned: Mapping[str, list[ast.expr]],
    name: str,
) -> object:
    values = assigned.get(name, ())
    if len(values) != 1:
        raise ValueError(f"{name} must be assigned exactly once")
    try:
        return ast.literal_eval(values[0])
    except (TypeError, ValueError, SyntaxError) as exc:
        raise ValueError(f"{name} must be a literal value") from exc


def _top_level_effects(tree: ast.Module) -> tuple[str, ...]:
    effects: list[str] = []
    for statement in tree.body:
        if isinstance(
            statement,
            (
                ast.Import,
                ast.ImportFrom,
                ast.Assign,
                ast.AnnAssign,
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
            ),
        ):
            continue
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        effects.append(type(statement).__name__)
    return tuple(effects)


def _inspect_source(
    module: EmittedEpisodeModule,
    node: NodeMaterializationPlan,
    expected_declaration: Mapping[str, object],
    generated_module_names: frozenset[str],
) -> tuple[BuildDeficit, ...]:
    local_id = node.local_id
    deficits: list[BuildDeficit] = []

    def add(code: str, field_path: str, detail: object) -> None:
        deficits.append(_deficit(code, field_path, detail, local_id=local_id))

    try:
        compile(
            module.module_source,
            f"<episode-builder:{module.module_name}>",
            "exec",
            dont_inherit=True,
        )
        tree = ast.parse(
            module.module_source,
            filename=f"<episode-builder:{module.module_name}>",
            mode="exec",
        )
    except SyntaxError as exc:
        add(
            "module_syntax_error",
            "module_source",
            f"line {exc.lineno}, column {exc.offset}: {exc.msg}",
        )
        return tuple(deficits)

    effects = _top_level_effects(tree)
    if effects:
        add(
            "module_top_level_effect",
            "module_source",
            f"top-level executable statements are not admitted: {effects!r}",
        )

    assigned = _assigned_values(tree)
    missing = sorted(_REQUIRED_VALUES - set(assigned))
    if missing:
        add(
            "module_exports_incomplete",
            "module_source",
            f"module omits required value exports {missing!r}",
        )
    duplicated = sorted(
        name for name in _REQUIRED_VALUES if len(assigned.get(name, ())) > 1
    )
    if duplicated:
        add(
            "module_exports_reassigned",
            "module_source",
            f"required exports are assigned more than once: {duplicated!r}",
        )

    functions = {
        statement.name: statement
        for statement in tree.body
        if isinstance(statement, ast.FunctionDef)
    }
    module_values = set(assigned)
    required_builders = {
        "build_controller_factory": _BUILD_CONTROLLER_FACTORY_PARAMETERS,
        "build_episode": _BUILD_EPISODE_PARAMETERS,
        **(_ROOT_BUILDERS if node.parent_local_id is None else {}),
    }
    for name, parameters in required_builders.items():
        function = functions.get(name)
        if function is None:
            add(
                "module_exports_incomplete",
                f"module_source.{name}",
                f"module omits synchronous {name}()",
            )
        elif _function_parameters(function) != parameters:
            add(
                "builder_signature_invalid",
                f"module_source.{name}",
                f"{name} parameters must be exactly {parameters!r}",
            )
    if node.parent_local_id is not None:
        unexpected = sorted(set(_ROOT_BUILDERS) & set(functions))
        if unexpected:
            add(
                "root_builder_on_child",
                "module_source",
                f"child module exports root-only builders {unexpected!r}",
            )
    for item in ast.walk(tree):
        if isinstance(item, (ast.Global, ast.Nonlocal)):
            add(
                "module_state_mutation_forbidden",
                "module_source",
                "generated builders cannot capture or mutate module state",
            )
    mutators = {
        "add",
        "append",
        "clear",
        "discard",
        "extend",
        "insert",
        "pop",
        "remove",
        "setdefault",
        "sort",
        "update",
    }
    for function in functions.values():
        for item in ast.walk(function):
            if (
                isinstance(item, ast.Call)
                and isinstance(item.func, ast.Attribute)
                and isinstance(item.func.value, ast.Name)
                and item.func.value.id in module_values
                and item.func.attr in mutators
            ):
                add(
                    "module_state_mutation_forbidden",
                    f"module_source.{function.name}",
                    f"{function.name} mutates module value {item.func.value.id!r}",
                )
            if isinstance(item, (ast.Attribute, ast.Subscript)) and isinstance(
                item.ctx,
                (ast.Store, ast.Del),
            ):
                root: ast.AST = item
                while isinstance(root, (ast.Attribute, ast.Subscript)):
                    root = root.value
                if isinstance(root, ast.Name) and root.id in module_values:
                    add(
                        "module_state_mutation_forbidden",
                        f"module_source.{function.name}",
                        f"{function.name} mutates module value {root.id!r}",
                    )
    if node.parent_local_id is None and "scope_goal_state" in functions:
        scope_error = _scope_goal_state_error(functions["scope_goal_state"])
        if scope_error is not None:
            add(
                "goal_view_mutable",
                "module_source.scope_goal_state",
                scope_error,
            )

    for binding in node.selected_function_bindings:
        if binding["source"] != "generated":
            continue
        function_name = str(binding["function_id"])
        if not function_name.isidentifier() or function_name not in functions:
            add(
                "generated_function_missing",
                "selected_function_bindings",
                f"generated binding {binding['role']!r} needs top-level "
                f"function {function_name!r}",
            )

    for binding in node.selected_function_bindings:
        role = str(binding["role"])
        if not role.startswith("edge.") or not role.endswith(".receive_result"):
            continue
        function_name = str(binding["function_id"])
        function = functions.get(function_name)
        if function is None or not any(
            isinstance(item, ast.Call)
            and _call_terminal_name(item) == "admit_child_result"
            for item in ast.walk(function)
        ):
            add(
                "child_result_correlation_missing",
                "selected_function_bindings",
                f"{role!r} must call handoff_library.admit_child_result before "
                "parent-local projection",
            )

    try:
        declaration = _literal_assignment(assigned, DECLARATION_EXPORT)
    except ValueError as exc:
        add("host_declaration_invalid", "module_source", exc)
    else:
        if _canonical(declaration) != _canonical(expected_declaration):
            add(
                "host_declaration_mismatch",
                "module_source",
                "embedded host declaration differs from the frozen contract and plan",
            )

    literal_expectations = {
        "PROMPTS": node.prompt_specs,
        "EXECUTION_CAPABILITY_NAMES": node.capability_names,
        "RESULT_CHANNEL_NAMES": node.result_channel_names,
        "RESULT_CHANNEL_IDS": node.result_channel_ids,
    }
    for name, expected in literal_expectations.items():
        try:
            actual = _literal_assignment(assigned, name)
        except ValueError as exc:
            add("module_literal_invalid", f"module_source.{name.lower()}", exc)
            continue
        if _canonical(actual) != _canonical(expected):
            add(
                "module_literal_mismatch",
                f"module_source.{name.lower()}",
                f"{name} differs from the admitted materialization plan",
            )

    for imported in _imported_modules(tree):
        if imported.startswith("."):
            add(
                "relative_import_forbidden",
                "module_source",
                f"relative import {imported!r} is not admitted",
            )
            continue
        root = imported.split(".", 1)[0]
        if root not in _ALLOWED_IMPORT_ROOTS:
            add(
                "module_import_forbidden",
                "module_source",
                f"import {imported!r} is outside the Episode module surface",
            )
        if root == "episode_library" and imported != "episode_library.models":
            add(
                "reference_episode_imported",
                "module_source",
                f"reference Episode import {imported!r} must be ported into the "
                "task-specific module instead of reused concretely",
            )
        if imported in generated_module_names or root.startswith("built_episode_"):
            add(
                "concrete_episode_imported",
                "module_source",
                f"generated Episode import {imported!r} bypasses runtime tree linking",
            )

    for item in ast.walk(tree):
        if isinstance(item, ast.Attribute) and item.attr in _FORBIDDEN_ATTRIBUTES:
            add(
                "python_introspection_forbidden",
                "module_source",
                f"attribute {item.attr!r} is outside the Episode module surface",
            )
        if not isinstance(item, ast.Call):
            continue
        terminal = _call_terminal_name(item)
        if terminal in _FORBIDDEN_CALL_NAMES or terminal in _FORBIDDEN_CALL_ATTRIBUTES:
            add(
                "direct_effect_forbidden",
                "module_source",
                f"call {terminal!r} bypasses declared collaborators",
            )
        if terminal != "FunctionImplementation":
            continue
        keywords = {keyword.arg: keyword.value for keyword in item.keywords}
        module_value = keywords.get("module")
        if not (
            isinstance(module_value, ast.Constant)
            and isinstance(module_value.value, str)
        ):
            add(
                "implementation_module_dynamic",
                "module_source",
                "FunctionImplementation.module must be a literal module name",
            )
            continue
        implementation_module = module_value.value
        root = implementation_module.split(".", 1)[0]
        if implementation_module != module.module_name and root not in (
            _INTERNAL_IMPLEMENTATION_ROOTS
        ):
            add(
                "implementation_module_forbidden",
                "module_source",
                f"FunctionImplementation module {implementation_module!r} is not "
                "the materialized module or an admitted internal library",
            )
    return tuple(deficits)


@dataclass(frozen=True)
class AdmissionOutcome:
    """Static source-admission result and manifest-ready content identities."""

    report: BuildAdmissionReport
    episode_ids_by_local_id: Mapping[str, str]
    function_definition_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.report, BuildAdmissionReport):
            raise TypeError("report must be a BuildAdmissionReport")
        episode_ids = dict(self.episode_ids_by_local_id)
        if any(
            not isinstance(local_id, str)
            or not isinstance(episode_id, str)
            or _EPISODE_ID.fullmatch(episode_id) is None
            for local_id, episode_id in episode_ids.items()
        ):
            raise ValueError("admission outcome contains an invalid Episode identity")
        if self.report.admitted and set(episode_ids) != set(
            self.report.module_source_hashes
        ):
            raise ValueError(
                "an admitted outcome needs one source-bound Episode ID per module"
            )
        definition_ids = tuple(sorted(set(self.function_definition_ids)))
        if any(
            _FUNCTION_DEFINITION_ID.fullmatch(value) is None
            for value in definition_ids
        ):
            raise ValueError("function_definition_ids contain an invalid identity")
        object.__setattr__(
            self,
            "episode_ids_by_local_id",
            MappingProxyType(dict(sorted(episode_ids.items()))),
        )
        object.__setattr__(self, "function_definition_ids", definition_ids)


class EpisodeBuildAdmission:
    """Inspect exact source without importing it or constructing runtime state."""

    def __init__(self, *, repository_root: str | Path | None = None) -> None:
        root = (
            Path(__file__).resolve().parents[1]
            if repository_root is None
            else Path(repository_root).expanduser().resolve()
        )
        if not root.is_dir():
            raise ValueError(f"repository root does not exist: {root}")
        self.repository_root = root

    def admit(
        self,
        build_request: ApprovedBuildRequest,
        build_attempt: BuildAttempt,
        plan: WorkflowMaterializationPlan,
        emitted_modules: tuple[EmittedEpisodeModule, ...],
    ) -> BuildAdmissionReport:
        return self.admit_outcome(
            build_request,
            build_attempt,
            plan,
            emitted_modules,
        ).report

    def admit_outcome(
        self,
        build_request: ApprovedBuildRequest,
        build_attempt: BuildAttempt,
        plan: WorkflowMaterializationPlan,
        emitted_modules: tuple[EmittedEpisodeModule, ...],
    ) -> AdmissionOutcome:
        if not isinstance(build_request, ApprovedBuildRequest):
            raise TypeError("admission requires ApprovedBuildRequest")
        if not isinstance(build_attempt, BuildAttempt):
            raise TypeError("admission requires BuildAttempt")
        if not isinstance(plan, WorkflowMaterializationPlan):
            raise TypeError("admission requires WorkflowMaterializationPlan")
        if not isinstance(emitted_modules, tuple) or any(
            not isinstance(module, EmittedEpisodeModule)
            for module in emitted_modules
        ):
            raise TypeError(
                "emitted_modules must contain EmittedEpisodeModule values"
            )

        deficits: list[BuildDeficit] = list(plan.deficits)
        try:
            plan.validate_against(build_request, build_attempt)
        except (TypeError, ValueError) as exc:
            deficits.append(_deficit("plan_mismatch", "workflow", exc))

        frozen_by_id = {
            episode.local_id: episode
            for episode in build_request.frozen_workflow.workflow.episodes
        }
        plan_by_id = {node.local_id: node for node in plan.nodes}
        counts = Counter(module.local_id for module in emitted_modules)
        emitted_by_id = {
            module.local_id: module
            for module in emitted_modules
            if counts[module.local_id] == 1
        }
        for local_id, count in sorted(counts.items()):
            if count > 1:
                deficits.append(
                    _deficit(
                        "duplicate_module",
                        "modules",
                        f"received {count} modules for one Episode",
                        local_id=local_id,
                    )
                )
            if local_id not in frozen_by_id:
                deficits.append(
                    _deficit(
                        "unplanned_module",
                        "modules",
                        "module does not belong to the frozen workflow",
                        local_id=local_id,
                    )
                )
        for local_id in sorted(set(frozen_by_id) - set(counts)):
            deficits.append(
                _deficit(
                    "missing_module",
                    "modules",
                    "no emitted module covers this frozen Episode",
                    local_id=local_id,
                )
            )

        edges_by_parent: dict[str, list[EdgeMaterializationPlan]] = {}
        for edge in plan.edges:
            edges_by_parent.setdefault(edge.parent_local_id, []).append(edge)
        generated_module_names = frozenset(
            node.module_name for node in plan.nodes
        )
        source_hashes = {
            local_id: module.source_hash
            for local_id, module in emitted_by_id.items()
            if local_id in plan_by_id
        }
        episode_ids: dict[str, str] = {}
        library_definition_ids: set[str] = set()

        for local_id in sorted(set(frozen_by_id) & set(emitted_by_id)):
            node = plan_by_id.get(local_id)
            module = emitted_by_id[local_id]
            if node is None:
                deficits.append(
                    _deficit(
                        "module_without_plan",
                        "modules",
                        "frozen Episode has no materialization node",
                        local_id=local_id,
                    )
                )
                continue
            if module.module_name != node.module_name:
                deficits.append(
                    _deficit(
                        "module_name_mismatch",
                        "module_name",
                        f"expected {node.module_name!r}, got {module.module_name!r}",
                        local_id=local_id,
                    )
                )
                continue
            declaration = build_module_declaration(
                frozen_by_id[local_id].contract,
                node,
                tuple(edges_by_parent.get(local_id, ())),
            )
            node_deficits = _inspect_source(
                module,
                node,
                declaration,
                generated_module_names,
            )
            deficits.extend(node_deficits)
            if not node_deficits:
                if plan.node_dispositions[local_id] == "unchanged":
                    predecessor = build_request.predecessor_manifest
                    if predecessor is None or (
                        predecessor.module_hashes_by_local_id.get(local_id)
                        != module.source_hash
                    ):
                        deficits.append(
                            _deficit(
                                "unchanged_module_diverged",
                                "module_source",
                                "unchanged module differs from predecessor manifest",
                                local_id=local_id,
                            )
                        )
                        continue
                    episode_ids[local_id] = (
                        predecessor.episode_ids_by_local_id[local_id]
                    )
                else:
                    episode_ids[local_id] = OpaqueId.mint(
                        "episode",
                        _canonical(
                            {
                                "workflow_hash": plan.workflow_hash.value,
                                "episode_local_id": local_id,
                                "node_plan_hash": Sha256Digest.of_record(
                                    node.as_record()
                                ).value,
                                "module_name": module.module_name,
                                "source_hash": module.source_hash.value,
                            }
                        ),
                    ).value
                library_definition_ids.update(
                    str(binding["definition_id"])
                    for binding in node.selected_function_bindings
                    if binding["source"] == "library"
                )

        report = BuildAdmissionReport(
            build_request_id=build_request.build_request_id,
            build_attempt_id=build_attempt.build_attempt_id,
            plan_id=plan.plan_id,
            workflow_hash=plan.workflow_hash,
            module_source_hashes=source_hashes,
            deficits=tuple(deficits),
        )
        report.validate_against(plan)
        return AdmissionOutcome(
            report=report,
            episode_ids_by_local_id=episode_ids,
            function_definition_ids=tuple(library_definition_ids),
        )


def admit_workflow_modules(
    build_request: ApprovedBuildRequest,
    build_attempt: BuildAttempt,
    plan: WorkflowMaterializationPlan,
    emitted_modules: tuple[EmittedEpisodeModule, ...],
) -> BuildAdmissionReport:
    return EpisodeBuildAdmission().admit(
        build_request,
        build_attempt,
        plan,
        emitted_modules,
    )


def admit_workflow_outcome(
    build_request: ApprovedBuildRequest,
    build_attempt: BuildAttempt,
    plan: WorkflowMaterializationPlan,
    emitted_modules: tuple[EmittedEpisodeModule, ...],
) -> AdmissionOutcome:
    return EpisodeBuildAdmission().admit_outcome(
        build_request,
        build_attempt,
        plan,
        emitted_modules,
    )


__all__ = [
    "AdmissionOutcome",
    "EpisodeBuildAdmission",
    "admit_workflow_modules",
    "admit_workflow_outcome",
]
