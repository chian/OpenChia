"""Library calls for the Builder's existing static materialization checks.

These checks consume exact typed artifacts and inspect generated code as data.
They provide repair evidence; a passing result is not execution evidence or
permission to publish a source package. The caller binds each observation to
its candidate and records unavailable inputs as blocked requirements.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .models import FunctionImplementation, LibraryFunction
from .registry import FunctionLibrary

if TYPE_CHECKING:
    from episode_builder._contract_base import (
        BuildAttempt,
        BuildReceipt,
        EmittedEpisodeModule,
    )
    from episode_builder._contract_chain import (
        ApprovedBuildRequest,
        WorkflowMaterializationPlan,
    )
    from episode_builder.reference import EpisodeReferenceContext


def _diagnostic(code, field_path, detail, local_id=None):
    return {
        "code": code,
        "field_path": field_path,
        "detail": str(detail),
        "episode_local_id": local_id,
        "blocking": True,
    }


def _result(diagnostics=(), *, status=None):
    rows = list(diagnostics)
    return {
        "status": status or ("fail" if any(row["blocking"] for row in rows) else "pass"),
        "diagnostics": rows,
    }


def _error(exc, field_path, local_id=None):
    return _result(
        [_diagnostic("checker_error", field_path, f"{type(exc).__name__}: {exc}", local_id)],
        status="error",
    )


def plan_consistency(
    request: ApprovedBuildRequest,
    attempt: BuildAttempt,
    plan: WorkflowMaterializationPlan,
) -> dict[str, object]:
    """Check authority/topology correspondence, including a partial plan.

    The existing validator deliberately accepts consistent partial plans. This
    requirement therefore measures correspondence, not completeness or readiness.
    """
    from episode_builder._contract_chain import WorkflowMaterializationPlan

    if not isinstance(plan, WorkflowMaterializationPlan):
        return _error(TypeError("plan must be a WorkflowMaterializationPlan"), "workflow")
    try:
        plan.validate_against(request, attempt)
    except ValueError as exc:
        return _result([_diagnostic("plan_mismatch", "workflow", exc)])
    except Exception as exc:
        return _error(exc, "workflow")
    return _result()


def node_plan_consistency(
    request: ApprovedBuildRequest,
    plan: WorkflowMaterializationPlan,
    local_id: str,
    *,
    reference_context: EpisodeReferenceContext | None = None,
) -> dict[str, object]:
    """Apply the planner's actual component/binding checks to one saved node.

    Parent-owned edges reconstruct the planner's child-slot input. An absent edge
    or child plan is an unavailable prerequisite, rather than a fabricated child
    failure. Reference-backed bindings require their exact saved reference context.
    """
    from agent.episode_contracts import Sha256Digest
    from episode_builder._contract_chain import ApprovedBuildRequest, WorkflowMaterializationPlan
    from episode_builder.call_plan import validate_functions, validate_planned_calls
    from episode_builder.plan_choices import node_choices
    from episode_builder.planner import _admit_plan_payload, _architecture_numeric_bindings, _library_functions, _planning_deficits
    from episode_builder.reference import EpisodeReferenceContext

    if not isinstance(request, ApprovedBuildRequest) or not isinstance(plan, WorkflowMaterializationPlan):
        return _error(TypeError("request and plan must be typed build artifacts"), "node_plan", local_id)
    if plan.build_request_id != request.build_request_id or plan.workflow_hash != request.frozen_workflow.workflow_hash:
        return _result([_diagnostic("plan_mismatch", "workflow", "plan belongs to another approved request", local_id)])
    designs = {item.local_id: item for item in request.frozen_workflow.workflow.episodes}
    nodes = {item.local_id: item for item in plan.nodes}
    design, node = designs.get(local_id), nodes.get(local_id)
    if design is None:
        return _result([_diagnostic("unplanned_node", "node_plan", "Episode is outside the approved workflow", local_id)])
    local_diagnostics = [item.as_record() for item in plan.deficits if item.episode_local_id == local_id]
    if node is None:
        return _result(local_diagnostics + [_diagnostic("node_plan_unavailable", "node_plan", "Episode has no typed materialization plan", local_id)], status="blocked")
    children = tuple(item for item in request.frozen_workflow.workflow.episodes if item.workflow_parent_local_id == local_id)
    missing_children = sorted(item.local_id for item in children if item.local_id not in nodes)
    edges = tuple(edge for edge in plan.edges if edge.parent_local_id == local_id)
    calls = tuple(edge for edge in plan.repeatable_calls if edge.parent_local_id == local_id)
    approved_calls = tuple(
        call for call in request.frozen_workflow.workflow.repeatable_calls
        if call.caller_local_id == local_id
    )
    missing_slots = sorted(
        (set(node.child_slot_names) | {call.slot_name for call in approved_calls})
        - {edge.slot_name for edge in (*edges, *calls)}
    )
    if missing_children or missing_slots:
        return _result(local_diagnostics + [_diagnostic("child_plan_unavailable", "child_slots", f"unavailable child plans: {missing_children!r}; unavailable parent-owned slots: {missing_slots!r}", local_id)], status="blocked")
    requires_reference = any(binding["source"] == "reference" for binding in node.selected_function_bindings)
    if requires_reference and not isinstance(reference_context, EpisodeReferenceContext):
        return _result(local_diagnostics + [_diagnostic("reference_unavailable", "episode_reference", "exact reference context is required to check reference-backed bindings", local_id)], status="blocked")
    if requires_reference and (
        reference_context.design.episode_id != node.reference_episode_id
        or Sha256Digest.of_record(reference_context.as_record()) != node.reference_evidence_hash
    ):
        return _result([_diagnostic("reference_mismatch", "episode_reference", "reference context differs from the node's pinned evidence", local_id)])
    try:
        validate_planned_calls(plan.nodes, calls, approved_calls, ready=True)
        for call in approved_calls:
            validate_functions(call, _library_functions())
        numeric_bindings, numeric_failure = _architecture_numeric_bindings(design)
        if numeric_failure is not None:
            return _result(local_diagnostics + [numeric_failure.as_record()])
        # The planner checks the concrete tree before the host installs exact
        # repeatable slots. Validate those slots above, then reconstruct that
        # same input instead of mistaking a declared call for an invented child.
        payload = _admit_plan_payload(node_choices(node, edges, calls=approved_calls))
        findings = _planning_deficits(
            node=design,
            payload=payload,
            child_plans=tuple(nodes[item.local_id] for item in children),
            reference_context=reference_context,
            architecture_numeric_bindings=numeric_bindings,
        )
        diagnostics = local_diagnostics + [item.as_record() for item in findings]
    except Exception as exc:
        return _error(exc, "node_plan", local_id)
    return _result(diagnostics)


def module_admission(
    request: ApprovedBuildRequest,
    plan: WorkflowMaterializationPlan,
    module: EmittedEpisodeModule,
) -> dict[str, object]:
    """Inspect one module with the exact checks used by source admission."""
    from episode_builder._contract_base import EmittedEpisodeModule
    from episode_builder._contract_chain import ApprovedBuildRequest, WorkflowMaterializationPlan
    from episode_builder.admission import _inspect_source
    from episode_builder.declaration import build_module_declaration

    if not isinstance(request, ApprovedBuildRequest) or not isinstance(plan, WorkflowMaterializationPlan) or not isinstance(module, EmittedEpisodeModule):
        return _error(TypeError("request, plan, and module must be typed build artifacts"), "module_source")
    local_id = module.local_id
    if plan.build_request_id != request.build_request_id or plan.workflow_hash != request.frozen_workflow.workflow_hash:
        return _result([_diagnostic("plan_mismatch", "workflow", "plan belongs to another approved request", local_id)])
    design = next((item for item in request.frozen_workflow.workflow.episodes if item.local_id == local_id), None)
    node = next((item for item in plan.nodes if item.local_id == local_id), None)
    if design is None:
        return _result([_diagnostic("unplanned_module", "modules", "module is outside the approved workflow", local_id)])
    if node is None:
        return _result([_diagnostic("module_without_plan", "modules", "module has no typed node plan", local_id)], status="blocked")
    if module.module_name != node.module_name:
        return _result([_diagnostic("module_name_mismatch", "module_name", f"expected {node.module_name!r}, got {module.module_name!r}", local_id)])
    edges = tuple(edge for edge in plan.all_edges if edge.parent_local_id == local_id)
    if {edge.slot_name for edge in edges} != set(node.child_slot_names):
        return _result([_diagnostic("edge_unplanned", "child_slots", "parent-owned edges do not yet cover every planned slot", local_id)], status="blocked")
    try:
        declaration = build_module_declaration(design.contract, node, edges)
        findings = _inspect_source(
            module,
            node,
            declaration,
            frozenset(item.module_name for item in plan.nodes),
            Path(__file__).resolve().parents[1],
            design.contract,
        )
    except Exception as exc:
        return _error(exc, "module_source", local_id)
    return _result(item.as_record() for item in findings)


def source_shape(
    source: str,
    *,
    local_id: str,
    target_module_name: str,
    forbidden_module_names: tuple[str, ...],
    is_root: bool,
) -> dict[str, object]:
    """Check raw model source before the host appends its declaration.

    Use the emission call's persisted source, including rejected source. An
    EmittedEpisodeModule already has the host declaration and belongs in
    module_admission instead.
    """
    from episode_builder.emitter import EpisodeEmissionError, _validate_module_source

    try:
        _validate_module_source(
            source,
            local_id=local_id,
            target_module_name=target_module_name,
            forbidden_module_names=forbidden_module_names,
            is_root=is_root,
        )
    except EpisodeEmissionError as exc:
        return _result([_diagnostic(exc.code, exc.field_path, exc.detail, exc.episode_local_id)])
    except Exception as exc:
        return _error(exc, "module_source", local_id)
    return _result()


def receipt_materialized(receipt: BuildReceipt) -> dict[str, object]:
    """Read the exact initial-materialization outcome, not runtime success."""
    from episode_builder._contract_base import BuildReceipt

    if not isinstance(receipt, BuildReceipt):
        return _error(TypeError("receipt must be a BuildReceipt"), "build_receipt")
    return _result(
        (item.as_record() for item in receipt.deficits),
        status="pass" if receipt.materialized else "fail",
    )


materialization_check_library = FunctionLibrary()


def _register(name, description, input_type, source_path, source_symbol):
    return materialization_check_library.register(
        LibraryFunction(
            library="materialization_checks",
            function_id=name,
            interface="materialization.validation",
            description=description,
            implementation=FunctionImplementation(module=__name__, symbol=name, is_async=False),
            input_type=input_type,
            output_type="{status: pass | fail | blocked | error, diagnostics: BuildDeficit-shaped records}",
            effect="Read exact build artifacts and trusted library source; never import or execute generated candidate code, call a model, or mutate storage.",
            failure_contract="Return checker errors separately from candidate failures; missing prerequisite artifacts are blocked, not passing evidence.",
            provenance={
                "scope": "static_materialization",
                "validator": {"path": source_path, "symbol": source_symbol},
                "implementation_identity": "The handoff records the checking process's source hashes.",
            },
        )
    )


PLAN_CONSISTENCY = _register(
    "plan_consistency",
    "Check the saved plan's correspondence to approved authority and topology; a partial plan can satisfy correspondence without being complete.",
    "request: ApprovedBuildRequest, attempt: BuildAttempt, plan: WorkflowMaterializationPlan",
    "episode_builder/_contract_chain.py",
    "WorkflowMaterializationPlan.validate_against",
)
NODE_PLAN_CONSISTENCY = _register(
    "node_plan_consistency",
    "Check one saved node's selected bindings, components, payloads, and recorded unresolved choices using the existing planner validator.",
    "request: ApprovedBuildRequest, plan: WorkflowMaterializationPlan, local_id: str; optional exact reference_context: EpisodeReferenceContext",
    "episode_builder/planner.py",
    "_planning_deficits",
)
MODULE_ADMISSION = _register(
    "module_admission",
    "Apply the existing non-executing source-admission checks to one exact emitted Episode module.",
    "request: ApprovedBuildRequest, plan: WorkflowMaterializationPlan, module: EmittedEpisodeModule",
    "episode_builder/admission.py",
    "_inspect_source",
)
SOURCE_SHAPE = _register(
    "source_shape",
    "Apply existing emitter syntax and export-shape checks to raw model source, including rejected output, before host declaration attachment.",
    "source: str; keyword local_id: str, target_module_name: str, forbidden_module_names: tuple[str, ...], is_root: bool",
    "episode_builder/emitter.py",
    "_validate_module_source",
)
RECEIPT_MATERIALIZED = _register(
    "receipt_materialized",
    "Read whether the complete materialization has a statically admitted manifest; this does not establish executable behavior.",
    "receipt: BuildReceipt",
    "episode_builder/_contract_base.py",
    "BuildReceipt.materialized",
)


__all__ = [
    "PLAN_CONSISTENCY",
    "NODE_PLAN_CONSISTENCY",
    "MODULE_ADMISSION",
    "SOURCE_SHAPE",
    "RECEIPT_MATERIALIZED",
    "materialization_check_library",
    "plan_consistency",
    "node_plan_consistency",
    "module_admission",
    "source_shape",
    "receipt_materialized",
]
