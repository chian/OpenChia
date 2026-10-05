"""Verify exact source for confined whole-Run reconstruction.

Whole Runs regenerate inside the ordinary confined worker and must match every
recorded boundary before new effects are admitted. Later-unit experiments need
the stricter stock-wrapper source language below because they omit the prefix.
Neither check activates generated code or invokes generated functions on host.
"""

import ast
from pathlib import Path

from agent.duet_contracts import canonical_json, digest_record
from agent.episode_contracts import Sha256Digest
from episode_builder.declaration import DECLARATION_EXPORT, build_module_declaration
from function_library import reasoning, refinement, testing

from ..contracts import RuntimeSourceManifest
from ..identity import runtime_identity_from_manifest
from ..linker import (
    PreparedSourcePackage,
    _module_relative_path,
    _package_files,
    _read_regular_file,
)


_IMPORTS = {
    "types": {"MappingProxyType"},
    "episode_library.models": {"EpisodeLibraryDesign"},
    "method_loop": {
        "Episode",
        "EpisodeBindingDeclaration",
        "EpisodeChildSlot",
        "EpisodeControllerBinding",
        "EpisodeFunctionBinding",
        "EpisodeTopologyRole",
    },
    "handoff_library": {
        "HandoffPayloadContract",
        "ADMIT_DUET_LAUNCH_REQUEST",
        "ADMIT_PARENT_REQUEST",
        "ADMIT_CHILD_RESULT",
    },
    "function_library": {"refinement", "reasoning"},
    "function_library.episode_calls": {"BUILD_REPEATABLE_CHILD"},
    "function_library.reasoning": {
        "OPEN_SOURCE",
        "BUILD_RESULT",
        "CONTROLLER",
        "SCHEMA",
        "ReasoningSource",
        "ReasoningGoalState",
        "build_reasoning_result",
        "build_controller_factory",
        "build_goal_state",
        "scope_goal_state",
        "reasoning_function_library",
    },
    "function_library.refinement": {
        "OPEN_SOURCE",
        "BUILD_EPISODE",
        "BUILD_RESULT",
        "CONTROLLER",
        "SCHEMA",
        "PREPARE_CHILD",
        "RECEIVE_CHILD",
        "REQUEST_SCHEMA",
        "ATTENUATE",
        "ADMIT_CALL",
        "build_refinement_episode",
        "build_controller_factory",
        "build_goal_state",
        "scope_goal_state",
        "refinement_function_library",
    },
    "function_library.epistemic": {"epistemic_function_library"},
    "function_library.testing": {"testing_function_library"},
    "function_library.testing_source": {"TestingSource"},
    "numeric_control_library": {
        "COMPOSE_INCIDENCE_CONTROLLER",
        "MARGINAL_DOMINATED_HYPERVOLUME",
        "PAIRED_INCIDENCE",
        "PREDICTED_CREDIT_UPPER_BOUND",
    },
}
_METADATA = {
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
_FUNCTIONS = {
    "build_episode": (
        "grain",
        "key",
        "request",
        "goal_view",
        "collaborators",
        "child_builders",
    ),
    "build_controller_factory": ("goal_view", "collaborators"),
    "build_goal_state": ("request", "collaborators"),
    "scope_goal_state": ("goal_state", "goal"),
}
_REGISTRIES = {
    "function_library.reasoning.reasoning_function_library",
    "function_library.refinement.refinement_function_library",
    "function_library.epistemic.epistemic_function_library",
    "function_library.testing.testing_function_library",
}
_RESERVED = (
    _METADATA
    | set(_FUNCTIONS)
    | {
        "dict",
        "tuple",
        "function",
        "selection",
        *sum(_FUNCTIONS.values(), ()),
    }
)


def _qualified(value, imports):
    if isinstance(value, ast.Name):
        return imports.get(value.id, value.id)
    if isinstance(value, ast.Attribute):
        return _qualified(value.value, imports) + "." + value.attr
    raise ValueError("reconstruction wrapper contains an indirect reference")


class _Normalize(ast.NodeTransformer):
    def __init__(self, imports):
        self.imports = imports

    def visit_Attribute(self, node):
        try:
            name = _qualified(node, self.imports)
        except ValueError:
            return self.generic_visit(node)
        return ast.Name(id=name, ctx=ast.Load())

    def visit_Name(self, node):
        return ast.Name(id=self.imports.get(node.id, node.id), ctx=node.ctx)

    def visit_Call(self, node):
        node = self.generic_visit(node)
        node.keywords.sort(key=lambda item: item.arg or "")
        return node


def _shape(value, imports=None):
    return ast.dump(_Normalize(imports or {}).visit(value), include_attributes=False)


def _matches(value, *templates):
    actual = _shape(value)
    return any(
        actual == _shape(ast.parse(template, mode="eval").body)
        for template in templates
    )


def _literal(value):
    try:
        return ast.literal_eval(value)
    except (ValueError, TypeError, SyntaxError) as exc:
        raise ValueError("reconstruction metadata must be literal data") from exc


def _keywords(value, expected, imports):
    if (
        not isinstance(value, ast.Call)
        or _qualified(value.func, imports) != expected
        or value.args
    ):
        raise ValueError(f"reconstruction metadata requires {expected}")
    result = {}
    for keyword in value.keywords:
        if keyword.arg is None:
            entries = _literal(keyword.value)
            if not isinstance(entries, dict):
                raise ValueError("metadata expansion must be a literal mapping")
            entries = {
                key: ast.parse(repr(item), mode="eval").body
                for key, item in entries.items()
            }
        else:
            entries = {keyword.arg: keyword.value}
        if result.keys() & entries.keys():
            raise ValueError("reconstruction metadata repeats a keyword")
        result.update(entries)
    return result


def _selection(value, planned, imports):
    fields = _keywords(value, "method_loop.EpisodeFunctionBinding", imports)
    if set(fields) != {
        "name",
        "library",
        "function_id",
        "interface",
        "definition_id",
        "arguments",
    }:
        raise ValueError("reconstruction function selection has unsupported fields")
    result = {key: _literal(item) for key, item in fields.items()}
    if not isinstance(result["name"], str) or not result["name"]:
        raise ValueError("reconstruction selection requires a literal name")
    if canonical_json({
        key: result[key] for key in result if key != "name"
    }) != canonical_json({key: planned[key] for key in result if key != "name"}):
        raise ValueError("reconstruction wrapper changes a frozen function selection")
    return result["name"]


def _binding(value, node, contract, edges, imports):
    fields = _keywords(value, "method_loop.EpisodeBindingDeclaration", imports)
    literals = {
        key: getattr(contract, key)
        for key in ("goal", "unit", "result", "progress", "stopping")
    }
    literals.update(grain_name=node.grain_name, interface=node.interface)
    if set(fields) != set(literals) | {
        "topology_role",
        "admit_request",
        "open_source",
        "build_result",
        "controller",
        "components",
        "child_slots",
    }:
        raise ValueError("unsupported reconstruction binding fields")
    for key, expected in literals.items():
        if _literal(fields[key]) != expected:
            raise ValueError("reconstruction binding changes the frozen contract")
    if (
        _qualified(fields["topology_role"], imports)
        != "method_loop.EpisodeTopologyRole." + node.topology_role.upper()
    ):
        raise ValueError("reconstruction binding changes topology")
    planned = {item["role"]: item for item in node.selected_function_bindings}
    for key in ("admit_request", "open_source", "build_result"):
        _selection(fields[key], planned[key], imports)
    controller = _keywords(
        fields["controller"], "method_loop.EpisodeControllerBinding", imports
    )
    if set(controller) != {
        "schema",
        "composer",
        "credit",
        "rarefaction",
        "continuation",
    }:
        raise ValueError("unsupported reconstruction controller fields")
    for key, selection in controller.items():
        _selection(selection, planned["controller." + key], imports)
    components = fields["components"]
    if not isinstance(components, ast.Tuple):
        raise ValueError("reconstruction components must be an explicit tuple")
    component_roles = [key for key in planned if key.startswith("component.")]
    if len(components.elts) != len(component_roles):
        raise ValueError("reconstruction components differ from the frozen plan")
    for selection, role in zip(components.elts, component_roles):
        if _selection(selection, planned[role], imports) != role.removeprefix(
            "component."
        ):
            raise ValueError("reconstruction component changed its dispatch name")
    slots = fields["child_slots"]
    if not isinstance(slots, ast.Tuple) or len(slots.elts) != len(edges):
        raise ValueError("reconstruction child slots differ from the frozen plan")
    seen = set()
    by_slot = {edge.slot_name: edge for edge in edges}
    for raw in slots.elts:
        slot = _keywords(raw, "method_loop.EpisodeChildSlot", imports)
        if set(slot) != {
            "name",
            "accepted_interfaces",
            "build_child",
            "prepare_request",
            "receive_result",
        }:
            raise ValueError("unsupported reconstruction child slot")
        name = _literal(slot["name"])
        if (
            name in seen
            or name not in by_slot
            or tuple(_literal(slot["accepted_interfaces"]))
            != (by_slot[name].child_interface,)
        ):
            raise ValueError(
                "reconstruction child interface differs from the frozen plan"
            )
        seen.add(name)
        for key in ("build_child", "prepare_request", "receive_result"):
            _selection(slot[key], planned[f"edge.{name}.{key}"], imports)
    return planned


def _design(value, node, imports):
    fields = _keywords(value, "episode_library.models.EpisodeLibraryDesign", imports)
    if (
        set(fields)
        != {
            "qualified_name",
            "title",
            "binding",
            "function_definitions",
            "source_symbols",
        }
        or _literal(fields["qualified_name"]) != node.interface
        or not isinstance(_literal(fields["title"]), str)
        or _literal(fields["source_symbols"]) != ()
        or not _matches(fields["binding"], "BINDING")
    ):
        raise ValueError("unsupported reconstruction DESIGN metadata")
    expression = fields["function_definitions"]
    # Only this metadata-only registry projection is allowed at import time.
    if (
        not isinstance(expression, ast.Call)
        or not isinstance(expression.func, ast.Name)
        or expression.func.id != "tuple"
        or expression.keywords
        or len(expression.args) != 1
    ):
        raise ValueError("DESIGN must use the stock registered-definition projection")
    generator = expression.args[0]
    if not isinstance(generator, ast.GeneratorExp) or len(generator.generators) != 1:
        raise ValueError("DESIGN must use the stock registered-definition projection")
    iteration = generator.generators[0]
    if not isinstance(iteration.iter, ast.Tuple):
        raise ValueError("DESIGN registry inputs must be an explicit tuple")
    inputs = iteration.iter.elts
    iteration.iter = ast.Tuple(elts=[], ctx=ast.Load())
    if not _matches(
        expression,
        "tuple(function for function in () if function.definition_id in {selection.definition_id for selection in BINDING.function_bindings()})",
    ):
        raise ValueError("DESIGN changes the stock registered-definition projection")
    for item in inputs:
        if isinstance(item, ast.Starred):
            call = item.value
            if (
                not isinstance(call, ast.Call)
                or call.args
                or call.keywords
                or _qualified(call.func, imports).removesuffix(".functions")
                not in _REGISTRIES
                or not _qualified(call.func, imports).endswith(".functions")
            ):
                raise ValueError("DESIGN expands an unsupported registry")
        else:
            qualified = _qualified(item, imports)
            module, _, name = qualified.rpartition(".")
            if name not in _IMPORTS.get(module, set()) or not name.isupper():
                raise ValueError("DESIGN references a non-stock function definition")


def _wrapper(value, name, family, imports):
    args = value.args
    if (
        value.decorator_list
        or value.returns is not None
        or getattr(value, "type_params", ())
        or args.posonlyargs
        or args.kwonlyargs
        or args.vararg
        or args.kwarg
        or args.defaults
        or args.kw_defaults
        or tuple(item.arg for item in args.args) != _FUNCTIONS[name]
        or any(item.annotation is not None for item in args.args)
        or len(value.body) != 1
        or not isinstance(value.body[0], ast.Return)
    ):
        raise ValueError(f"{name} must be a stock required-argument forwarding wrapper")
    expression = _Normalize(imports).visit(value.body[0].value)
    module = (
        "function_library.refinement"
        if family == "refinement"
        else "function_library.reasoning"
    )
    templates = {
        "build_controller_factory": (
            f"{module}.build_controller_factory(goal_view, collaborators)",
        ),
        "build_goal_state": (
            "function_library.reasoning.ReasoningGoalState()",
            f"{module}.build_goal_state(request, collaborators)",
        ),
        "scope_goal_state": (
            "types.MappingProxyType({'goal': goal.objective})",
            f"{module}.scope_goal_state(goal_state, goal)",
        ),
    }
    if family == "refinement":
        templates["build_episode"] = tuple(
            f"function_library.refinement.build_refinement_episode(grain, key, request, goal_view, collaborators, child_builders, **{arguments}, declared_channel_ids=RESULT_CHANNEL_IDS)"
            for arguments in (
                "BINDING.open_source.arguments",
                "dict(BINDING.open_source.arguments)",
            )
        )
    else:
        source = (
            "function_library.testing_source.TestingSource"
            if family == "testing"
            else "function_library.reasoning.ReasoningSource"
        )
        templates["build_episode"] = tuple(
            f"method_loop.Episode(grain=grain, key=key, request=request, source={source}(goal_view['goal'], **{arguments}), build_result=function_library.reasoning.build_reasoning_result)"
            for arguments in (
                "BINDING.open_source.arguments",
                "dict(BINDING.open_source.arguments)",
            )
        )
    if not _matches(expression, *templates[name]):
        raise ValueError(f"{name} changes the stock {family} reconstruction behavior")


def _admit_module(source, *, node, contract, edges):
    tree = ast.parse(source)
    imports, assigned, functions = {}, {}, {}
    for statement in tree.body:
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        if isinstance(statement, ast.ImportFrom) and not statement.level:
            for alias in statement.names:
                local = alias.asname or alias.name
                # An ABI wrapper may deliberately shadow an imported builder only
                # when the imported builder has a distinct local alias.
                if (
                    alias.name not in _IMPORTS.get(statement.module, set())
                    or local in imports
                    or local in _RESERVED
                ):
                    raise ValueError("unsupported or shadowing reconstruction import")
                imports[local] = statement.module + "." + alias.name
        elif (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
        ):
            name = statement.targets[0].id
            if name not in _METADATA or name in assigned or name in imports:
                raise ValueError(
                    "reconstruction wrappers cannot rebind names or mutate modules"
                )
            assigned[name] = statement.value
        elif (
            isinstance(statement, ast.FunctionDef)
            and statement.name in _FUNCTIONS
            and statement.name not in functions
            and statement.name not in imports
        ):
            functions[statement.name] = statement
        else:
            raise ValueError(
                "reconstruction requires stock wrappers without generated helpers, subclasses or top-level effects"
            )
    expected_functions = (
        set(_FUNCTIONS)
        if node.parent_local_id is None
        else {"build_episode", "build_controller_factory"}
    )
    if set(assigned) != _METADATA or set(functions) != expected_functions:
        raise ValueError("reconstruction wrapper exports differ from the stock ABI")
    expected = {
        DECLARATION_EXPORT: build_module_declaration(contract, node, edges),
        "PROMPTS": node.prompt_specs,
        "EXECUTION_CAPABILITY_NAMES": node.capability_names,
        "RESULT_CHANNEL_NAMES": node.result_channel_names,
        "RESULT_CHANNEL_IDS": node.result_channel_ids,
    }
    for name, expected_value in expected.items():
        if canonical_json(_literal(assigned[name])) != canonical_json(expected_value):
            raise ValueError(f"{name} differs from the admitted reconstruction plan")
    for name, expected_value in (
        ("REQUEST_PAYLOAD_CONTRACT", node.request_payload_contract),
        ("RESULT_PAYLOAD_CONTRACT", node.result_payload_contract),
    ):
        call = assigned[name]
        if (
            not isinstance(call, ast.Call)
            or _qualified(call.func, imports)
            != "handoff_library.HandoffPayloadContract.from_record"
            or len(call.args) != 1
            or call.keywords
            or canonical_json(_literal(call.args[0])) != canonical_json(expected_value)
        ):
            raise ValueError("reconstruction payload metadata differs from the plan")
    planned = _binding(assigned["BINDING"], node, contract, edges, imports)
    families = {
        refinement.OPEN_SOURCE.definition_id: "refinement",
        reasoning.OPEN_SOURCE.definition_id: "reasoning",
        testing.OPEN_SOURCE.definition_id: "testing",
    }
    family = families.get(planned["open_source"]["definition_id"])
    if family is None:
        raise ValueError("reconstruction has no supported stock source family")
    reference = refinement if family == "refinement" else reasoning
    if any(
        planned[role]["definition_id"] != definition.definition_id
        for role, definition in (
            ("controller.composer", reference.CONTROLLER),
            ("controller.schema", reference.SCHEMA),
            ("build_result", reference.BUILD_RESULT),
        )
    ):
        raise ValueError(
            "reconstruction requires the stock controller, schema and result adapter"
        )
    _design(assigned["DESIGN"], node, imports)
    for name, function in functions.items():
        _wrapper(function, name, family, imports)
    return family


def admit_reconstruction_source(prepared, *, source_package_path, runtime_manifest):
    """Verify exact admitted bytes; the confined worker reconstructs their trace.

    The executor verifies every staged worker byte and its interpreter against
    the frozen registration. The host checkout need not be identical: the worker
    still runs that original closure, and every saved protocol frame must match
    before the host admits new work. This does not substitute current worker code.
    """
    if not isinstance(prepared, PreparedSourcePackage) or not isinstance(
        runtime_manifest, RuntimeSourceManifest
    ):
        raise TypeError(
            "reconstruction admission requires a prepared package and verified runtime manifest"
        )
    if prepared.registration.runtime_identity != runtime_identity_from_manifest(
        runtime_manifest
    ):
        raise ValueError("reconstruction runtime differs from the frozen registration")
    root = Path(source_package_path)
    if root.is_symlink() or root.name != prepared.manifest.manifest_id.value:
        raise ValueError(
            "reconstruction source package differs from its admitted manifest"
        )
    contracts = {
        item.local_id: item.contract
        for item in prepared.build_request.frozen_workflow.workflow.episodes
    }
    modules = []
    for node in prepared.plan.nodes:
        module = prepared.modules[node.local_id]
        source = _read_regular_file(root / module.relative_path, module.module_name)
        if Sha256Digest.of_bytes(source) != module.source_hash:
            raise ValueError("reconstruction wrapper changed after package preparation")
        contract = contracts[node.local_id]
        selected = {item["role"]: item for item in node.selected_function_bindings}
        # Host sessions are required by frozen declarations, not inferred from
        # executable source text. The ordinary linker/admission already checked
        # this package; no generated Python is evaluated by this verifier.
        family = (
            "refinement" if selected["open_source"]["definition_id"] == refinement.OPEN_SOURCE.definition_id
            else "testing" if contract.testing is not None else "target"
        )
        modules.append({
            "local_id": node.local_id,
            "family": family,
            "source_hash": module.source_hash.value,
        })
    return {
        "schema_version": 1,
        "kind": "confined_run_reconstruction",
        "runtime_identity": prepared.registration.runtime_identity.as_record(),
        "manifest_id": prepared.manifest.manifest_id.value,
        "modules": modules,
        "limitations": [
            "Exact admitted code regenerates from the original entry in the confined worker; every saved protocol frame must match before live work is authorized.",
            "Unrecorded nondeterminism is not restored. Observable divergence fails closed; an unanswered external HTTP effect requires reconciliation.",
            "Source admission neither proves the saved prefix nor authorizes continuation; shared reconstruction and host-state admission remain required.",
        ],
    }


def admit_reasoning_unit_source(inputs, *, source_package_path, entry_local_id):
    """Admit source shape for a new experiment at a saved reasoning-unit boundary.

    ``inputs`` comes from BuildStore inspection or package preparation. Recheck the bytes
    without activating generated code: package activation loads even modules
    outside the selected scope, so every wrapper must exclude mutation effects.
    Runtime identity, original history, ledger baseline and authority are separate
    execution checks; this receipt does not establish them or restore any state.
    """
    from episode_builder.inspection import MaterializationInspectionInput, _expected_package_files

    if isinstance(inputs, PreparedSourcePackage):
        emitted = inputs.modules
        expected_files = _expected_package_files(
            inputs.build_request, inputs.build_attempt, inputs.plan,
            inputs.admission_report, inputs.manifest, emitted,
        )
    elif isinstance(inputs, MaterializationInspectionInput):
        emitted = {module.local_id: module for module in inputs.emitted_modules}
        expected_files = inputs.source_package_files
    else:
        raise TypeError("reasoning unit admission requires typed build inspection or a prepared source package")
    if (
        inputs.manifest is None
        or inputs.admission_report is None
        or not inputs.admission_report.admitted
        or expected_files is None
    ):
        raise ValueError("reasoning unit admission requires a verified admitted source package")
    nodes = {node.local_id: node for node in inputs.plan.nodes}
    if not isinstance(entry_local_id, str) or entry_local_id not in nodes:
        raise ValueError("reasoning unit entry must name a node in this exact build")
    if any(edge.parent_local_id == entry_local_id for edge in inputs.plan.all_edges):
        raise ValueError("reasoning unit entry must have no declared children or repeatable calls")

    root = Path(source_package_path).expanduser()
    if root.is_symlink() or root.name != inputs.manifest.manifest_id.value:
        raise ValueError("reasoning unit source package differs from its admitted manifest")
    files = _package_files(root)
    if files.keys() != expected_files.keys():
        raise ValueError("reasoning unit package files changed after build inspection")
    source_bytes = {}
    for relative, path in files.items():
        payload = _read_regular_file(path, relative)
        if Sha256Digest.of_bytes(payload) != expected_files[relative]:
            raise ValueError("reasoning unit source package changed after build inspection")
        if relative.endswith(".py"):
            source_bytes[relative] = payload

    if emitted.keys() != nodes.keys():
        raise ValueError("reasoning unit admission requires every generated module")
    contracts = {
        item.local_id: item.contract
        for item in inputs.build_request.frozen_workflow.workflow.episodes
    }
    modules = []
    for node in inputs.plan.nodes:
        module = emitted[node.local_id]
        source = source_bytes[_module_relative_path(module.module_name)]
        if (
            Sha256Digest.of_bytes(source) != module.source_hash
            or module.source_hash != inputs.manifest.module_hashes_by_local_id[node.local_id]
        ):
            raise ValueError("reasoning unit wrapper differs from its frozen module hash")
        family = _admit_module(
            source.decode("utf-8", errors="strict"),
            node=node,
            contract=contracts[node.local_id],
            edges=tuple(
                edge for edge in inputs.plan.all_edges
                if edge.parent_local_id == node.local_id
            ),
        )
        if family != "reasoning":
            raise ValueError("later-unit source admission supports only stock reasoning wrappers, not testing or refinement")
        modules.append({
            "local_id": node.local_id,
            "family": family,
            "source_hash": module.source_hash.value,
        })
    return {
        "schema_version": 1,
        "kind": "stock_reasoning_unit_source",
        "entry_local_id": entry_local_id,
        "root_local_id": inputs.plan.root_local_id,
        "manifest_ref": {
            "artifact_id": inputs.manifest.manifest_id.value,
            "content_hash": digest_record(inputs.manifest.as_record()).value,
        },
        "modules": modules,
        "source": "function_library.reasoning.ReasoningSource",
        "controller": "function_library.reasoning.HostReceiptController",
        "goal_state": "function_library.reasoning.ReasoningGoalState",
        "goal_scoper": "function_library.reasoning.scope_goal_state",
        "restoration_verified": False,
        "limitations": [
            "Every generated module must be an exact stock reasoning wrapper; testing, refinement, custom sources and generated mutation effects are unsupported.",
            "The selected entry is a leaf with no declared child or repeatable calls; the root uses the immutable stock reasoning goal state and scoper.",
            "Source shape does not validate a saved prefix, restore a ledger or controller, authorize execution, or verify the frozen runtime implementation.",
        ],
    }
