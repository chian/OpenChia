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
from handoff_library import ADMIT_CHILD_RESULT
from function_library.refinement import RECEIVE_CHILD as RECEIVE_REFINEMENT_CHILD

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


def _top_level_functions(
    tree: ast.Module,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Index every top-level def, synchronous or async.

    Generated components that call the brokered libraries (``http_json``,
    ``http_request``, the model calls) are necessarily ``async def``; only the
    four builders the runtime calls directly must stay synchronous, and the
    caller checks that separately.
    """
    return {
        statement.name: statement
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _function_parameters(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, ...] | None:
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


def constructor_signatures() -> dict[str, dict[str, list[str]]]:
    """Constructor fields of every library class a generated module builds.

    Read from the dataclasses themselves so the emitter's contract and the
    admission check below can never disagree with the runtime.
    """
    import dataclasses

    import episode_library.models
    import function_library.models
    import handoff_library
    import method_loop
    import numeric_control_library

    classes = {
        "episode_library.models.EpisodeLibraryDesign": episode_library.models.EpisodeLibraryDesign,
        "method_loop.EpisodeBindingDeclaration": method_loop.EpisodeBindingDeclaration,
        "method_loop.EpisodeControllerBinding": method_loop.EpisodeControllerBinding,
        "method_loop.EpisodeFunctionBinding": method_loop.EpisodeFunctionBinding,
        "method_loop.EpisodeChildSlot": method_loop.EpisodeChildSlot,
        "method_loop.EpisodeRequest": method_loop.EpisodeRequest,
        "method_loop.ChildEpisodeUnit": method_loop.ChildEpisodeUnit,
        "method_loop.ReportContract": method_loop.ReportContract,
        "function_library.models.LibraryFunction": function_library.models.LibraryFunction,
        "function_library.models.FunctionImplementation": function_library.models.FunctionImplementation,
        "handoff_library.HandoffPayloadContract": handoff_library.HandoffPayloadContract,
        "numeric_control_library.ResultColumnSchema": numeric_control_library.ResultColumnSchema,
    }
    signatures: dict[str, dict[str, list[str]]] = {}
    for qualified, cls in classes.items():
        init_fields = [field for field in dataclasses.fields(cls) if field.init]
        required = [
            field.name
            for field in init_fields
            if field.default is dataclasses.MISSING
            and field.default_factory is dataclasses.MISSING
        ]
        signatures[qualified] = {
            "required": required,
            "optional": [field.name for field in init_fields if field.name not in required],
            "derived": [field.name for field in dataclasses.fields(cls) if not field.init],
        }
    signatures["method_loop.EpisodeTopologyRole"] = {
        "required": [],
        "optional": [],
        "derived": [],
        "members": [member.name for member in method_loop.EpisodeTopologyRole],
    }
    return signatures


def _constructor_argument_deficits(tree: ast.Module) -> tuple[str, ...]:
    """Check keyword/positional arguments of library class constructions statically.

    A call that unpacks ``*args``/``**kwargs`` cannot be checked and is skipped;
    everything else must name only real fields and supply every required one.
    """
    signatures = {
        qualified: spec
        for qualified, spec in constructor_signatures().items()
        if "members" not in spec
    }
    by_module: dict[str, dict[str, str]] = {}
    for qualified in signatures:
        module_name, _, class_name = qualified.rpartition(".")
        by_module.setdefault(module_name, {})[class_name] = qualified
    local_names: dict[str, str] = {}
    module_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in by_module and not node.level:
            for alias in node.names:
                qualified = by_module[node.module].get(alias.name)
                if qualified is not None:
                    local_names[alias.asname or alias.name] = qualified
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in by_module:
                    module_aliases[alias.asname or alias.name] = alias.name
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        qualified = None
        if isinstance(node.func, ast.Name):
            qualified = local_names.get(node.func.id)
        elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            module_name = module_aliases.get(node.func.value.id)
            if module_name is not None:
                qualified = by_module[module_name].get(node.func.attr)
        if qualified is None:
            continue
        if any(isinstance(item, ast.Starred) for item in node.args) or any(
            keyword.arg is None for keyword in node.keywords
        ):
            continue
        spec = signatures[qualified]
        fields = spec["required"] + spec["optional"]
        supplied = set(fields[: len(node.args)])
        unknown = sorted(
            keyword.arg for keyword in node.keywords if keyword.arg not in fields
        )
        supplied.update(keyword.arg for keyword in node.keywords if keyword.arg in fields)
        missing = [name for name in spec["required"] if name not in supplied]
        if len(node.args) > len(fields):
            found.append(
                f"{qualified} at line {node.lineno} takes at most {len(fields)} "
                f"positional arguments; received {len(node.args)}"
            )
        if unknown or missing:
            parts = []
            if unknown:
                parts.append(f"unknown keyword(s) {unknown!r}")
            if missing:
                parts.append(f"missing required field(s) {missing!r}")
            found.append(
                f"{qualified} at line {node.lineno}: {'; '.join(parts)}; its fields are "
                f"{fields!r}"
            )
    return tuple(found)


_FROZEN_BINDING_FIELDS = ("goal", "unit", "result", "progress", "stopping")


def _binding_contract_deficits(
    tree: ast.Module, expected: Mapping[str, object]
) -> tuple[str, ...]:
    """Compare the module's BINDING literals with the frozen node, statically.

    The runtime linker rejects a BINDING whose grain_name, interface,
    topology_role, goal, unit, result, progress or stopping differ from the
    frozen node by a single character; this makes the same comparison at
    admission, where the operator sees it as a deficit with the first
    differing character instead of a failed Run.
    """
    constants: dict[str, object] = {}
    binding: ast.AST | None = None
    for statement in tree.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1:
            continue
        target = statement.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id == "BINDING":
            binding = statement.value
            continue
        try:
            constants[target.id] = ast.literal_eval(statement.value)
        except (ValueError, TypeError, SyntaxError):
            pass
    if not isinstance(binding, ast.Call):
        return ("BINDING must be assigned one EpisodeBindingDeclaration(...) call at module level",)
    keywords = {keyword.arg: keyword.value for keyword in binding.keywords if keyword.arg}
    found: list[str] = []
    for field, want in expected.items():
        value = keywords.get(field)
        if value is None:
            found.append(f"BINDING omits {field}")
            continue
        got: object
        if field == "topology_role" and isinstance(value, ast.Attribute):
            got = value.attr.lower()
        elif isinstance(value, ast.Constant):
            got = value.value
        elif isinstance(value, ast.Name) and value.id in constants:
            got = constants[value.id]
        else:
            found.append(
                f"BINDING.{field} must be a string literal or a module-level "
                "constant so admission can compare it with the frozen contract"
            )
            continue
        if got == want:
            continue
        if field in _FROZEN_BINDING_FIELDS and isinstance(got, str) and isinstance(want, str):
            index = next(
                (i for i in range(min(len(got), len(want))) if got[i] != want[i]),
                min(len(got), len(want)),
            )
            found.append(
                f"BINDING.{field} differs from the frozen contract at character "
                f"{index}: frozen ...{want[max(0, index - 30):index + 40]!r}, module "
                f"...{got[max(0, index - 30):index + 40]!r}; copy the frozen text "
                "byte for byte"
            )
        else:
            found.append(f"BINDING.{field} is {got!r}; the frozen node requires {want!r}")
    return tuple(found)


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


_LOCAL_LIBRARY_ROOTS = frozenset(_INTERNAL_IMPLEMENTATION_ROOTS | {"episode_library"})


def _module_file(repository_root: Path, module_name: str) -> Path | None:
    base = repository_root.joinpath(*module_name.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(item) for item in target.elts))
    return set()


def _exported_names(module_file: Path) -> frozenset[str] | None:
    """Names ``from <module> import <name>`` can bind, read without importing.

    Returns ``None`` when the module star-imports, since its surface cannot be
    known statically; the caller then skips name resolution for that module.
    """
    tree = ast.parse(module_file.read_text("utf-8"), filename=str(module_file))
    names: set[str] = set()

    def collect(statements: list[ast.stmt]) -> bool:
        for statement in statements:
            if isinstance(
                statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                names.add(statement.name)
            elif isinstance(statement, ast.Assign):
                for target in statement.targets:
                    names.update(_target_names(target))
            elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
                names.update(_target_names(statement.target))
            elif isinstance(statement, ast.Import):
                names.update(
                    alias.asname or alias.name.split(".", 1)[0]
                    for alias in statement.names
                )
            elif isinstance(statement, ast.ImportFrom):
                if any(alias.name == "*" for alias in statement.names):
                    return False
                names.update(alias.asname or alias.name for alias in statement.names)
            elif isinstance(statement, (ast.If, ast.Try)):
                bodies = [statement.body, statement.orelse]
                if isinstance(statement, ast.Try):
                    bodies.append(statement.finalbody)
                    bodies.extend(handler.body for handler in statement.handlers)
                if not all(collect(body) for body in bodies):
                    return False
        return True

    return frozenset(names) if collect(tree.body) else None


def _imported_name_deficits(
    tree: ast.Module, repository_root: Path
) -> tuple[tuple[str, str], ...]:
    """Resolve library imports against the real module files, non-executing.

    Admission already restricts import *roots*; this restricts the imported
    *names* too, so a module that names a real class under the wrong library
    (``from episode_library.models import EpisodeControllerBinding``) is
    blocked here instead of failing inside the isolated Run with an
    ImportError the host cannot see.
    """
    found: list[tuple[str, str]] = []
    for item in ast.walk(tree):
        if isinstance(item, ast.ImportFrom):
            if item.level or item.module is None:
                continue
            if item.module.split(".", 1)[0] not in _LOCAL_LIBRARY_ROOTS:
                continue
            module_file = _module_file(repository_root, item.module)
            if module_file is None:
                found.append(
                    (
                        "imported_module_missing",
                        f"import {item.module!r} names no module in the admitted libraries",
                    )
                )
                continue
            exported = _exported_names(module_file)
            if exported is None:
                continue
            for alias in item.names:
                if alias.name == "*" or alias.name in exported:
                    continue
                if _module_file(repository_root, f"{item.module}.{alias.name}"):
                    continue
                found.append(
                    (
                        "imported_name_missing",
                        f"import {alias.name!r} from {item.module!r} names nothing that "
                        "module defines or re-exports; import it from the library "
                        "whose __all__ lists it",
                    )
                )
        elif isinstance(item, ast.Import):
            for alias in item.names:
                if alias.name.split(".", 1)[0] not in _LOCAL_LIBRARY_ROOTS:
                    continue
                if _module_file(repository_root, alias.name) is None:
                    found.append(
                        (
                            "imported_module_missing",
                            f"import {alias.name!r} names no module in the admitted libraries",
                        )
                    )
    return tuple(found)


def _inspect_source(
    module: EmittedEpisodeModule,
    node: NodeMaterializationPlan,
    expected_declaration: Mapping[str, object],
    generated_module_names: frozenset[str],
    repository_root: Path | None = None,
    frozen_contract: object | None = None,
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

    functions = _top_level_functions(tree)
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
        elif isinstance(function, ast.AsyncFunctionDef):
            add(
                "builder_async_forbidden",
                f"module_source.{name}",
                f"{name} must be a synchronous def; the runtime calls it directly",
            )
        elif _function_parameters(function) is None:
            add(
                "builder_signature_invalid",
                f"module_source.{name}",
                f"{name} parameters must be exactly {parameters!r} as plain "
                "positional parameters; the def uses default values, "
                "*args/**kwargs, keyword-only or positional-only parameters",
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
        if binding["source"] == "library" and any(
            all(binding[name] == getattr(receiver, name)
                for name in ("library", "function_id", "interface", "definition_id"))
            for receiver in (ADMIT_CHILD_RESULT, RECEIVE_REFINEMENT_CHILD)
        ):
            # Selecting the admission function itself is already correlation;
            # requiring an emitted wrapper would reject the exact library route.
            # The registered refiner receiver also calls that same admission
            # function; this is an exact definition match, not a prose exemption.
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

    if repository_root is not None:
        for code, detail in _imported_name_deficits(tree, repository_root):
            add(code, "module_source", detail)

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

    for detail in _constructor_argument_deficits(tree):
        add("constructor_arguments_invalid", "module_source", detail)

    if frozen_contract is not None:
        expected: dict[str, object] = {
            "grain_name": node.grain_name,
            "interface": node.interface,
            "topology_role": node.topology_role,
            **{field: getattr(frozen_contract, field) for field in _FROZEN_BINDING_FIELDS},
        }
        for detail in _binding_contract_deficits(tree, expected):
            add("binding_contract_mismatch", "module_source.binding", detail)

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
        for edge in plan.all_edges:
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
                self.repository_root,
                frozen_by_id[local_id].contract,
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
