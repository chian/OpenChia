"""Registered, task-independent generic Creator template semantics."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Mapping

from agent.generic_creator_models import GenericCreatorInstanceSpec, GenericCreatorType


@dataclass(frozen=True)
class CreatorTemplateDefinition:
    creator_type: GenericCreatorType
    required_inputs: frozenset[str]
    optional_inputs: frozenset[str] = frozenset()

    @property
    def allowed_inputs(self) -> frozenset[str]:
        return self.required_inputs | self.optional_inputs

    def validate(self, value: Mapping[str, Any]) -> None:
        actual = set(value)
        missing = sorted(self.required_inputs - actual)
        unknown = sorted(actual - self.allowed_inputs)
        if missing or unknown:
            raise ValueError(
                f"malformed {self.creator_type.value} work_definition: "
                f"missing={missing!r}, unknown={unknown!r}"
            )


TEMPLATE_REGISTRY: dict[GenericCreatorType, CreatorTemplateDefinition] = {
    GenericCreatorType.PLAN_CONTEXT_CREATOR: CreatorTemplateDefinition(
        GenericCreatorType.PLAN_CONTEXT_CREATOR,
        frozenset(
            {
                "stable_task_goal",
                "desired_result_schema",
                "constraints_and_safety_bounds",
                "available_capabilities",
                "supplied_references",
                "existing_artifacts_and_evidence",
                "unresolved_questions",
            }
        ),
        frozenset({"suggested_decomposition"}),
    ),
    GenericCreatorType.WORKLIST_FACTORY_CREATOR: CreatorTemplateDefinition(
        GenericCreatorType.WORKLIST_FACTORY_CREATOR,
        frozenset(
            {
                "items",
                "artifact_schema",
                "builder_episode_template",
                "test_episode_template",
                "shared_constraints",
                "per_item_acceptance_gates",
                "retry_and_stagnation_policy",
            }
        ),
        frozenset({"execution_mode", "parallelism"}),
    ),
    GenericCreatorType.AGENT_LOOP_DESIGNER_CREATOR: CreatorTemplateDefinition(
        GenericCreatorType.AGENT_LOOP_DESIGNER_CREATOR,
        frozenset(
            {
                "task_state_schema",
                "allowed_actions_or_tools",
                "observation_schema",
                "transition_rules",
                "result_schema",
                "progress_measurement",
                "stopping_rule",
                "safety_bounds",
                "representative_test_scenarios",
            }
        ),
    ),
    GenericCreatorType.INTEGRATION_HANDOFF_CREATOR: CreatorTemplateDefinition(
        GenericCreatorType.INTEGRATION_HANDOFF_CREATOR,
        frozenset(
            {
                "component_artifacts",
                "interface_contracts",
                "dependency_edges",
                "integration_scenarios",
                "expected_handoff_behavior",
                "gate_ownership",
            }
        ),
        frozenset({"required_regressions"}),
    ),
    GenericCreatorType.RAREFACTION_PORTFOLIO_CREATOR: CreatorTemplateDefinition(
        GenericCreatorType.RAREFACTION_PORTFOLIO_CREATOR,
        frozenset(
            {
                "candidates",
                "dependency_status",
                "estimated_cost",
                "prior_accepted_yield",
                "uncertainty",
                "integration_unblock_value",
                "remaining_budgets",
                "rarefaction_rules",
            }
        ),
    ),
    GenericCreatorType.QUALIFICATION_RELEASE_CREATOR: CreatorTemplateDefinition(
        GenericCreatorType.QUALIFICATION_RELEASE_CREATOR,
        frozenset(
            {
                "integrated_artifact_graph",
                "required_gates",
                "evidence_ledger",
                "safety_constraints",
                "deliverable_schema",
            }
        ),
    ),
    GenericCreatorType.GENERIC_ORCHESTRATOR_CREATOR: CreatorTemplateDefinition(
        GenericCreatorType.GENERIC_ORCHESTRATOR_CREATOR,
        frozenset(
            {
                "task_specification",
                "template_instance_ids",
                "budget_allocation",
                "rarefaction_instance_id",
                "integration_instance_id",
                "qualification_instance_id",
            }
        ),
    ),
}


def validate_template_spec(spec: GenericCreatorInstanceSpec) -> CreatorTemplateDefinition:
    if not isinstance(spec, GenericCreatorInstanceSpec):
        raise TypeError("template validation requires GenericCreatorInstanceSpec")
    definition = TEMPLATE_REGISTRY[spec.creator_type]
    definition.validate(spec.work_definition)
    _VALIDATORS[spec.creator_type](spec.work_definition)
    if spec.creator_type is GenericCreatorType.WORKLIST_FACTORY_CREATOR:
        required_children = len(spec.work_definition["items"]) * 2
        if spec.maximum_child_episodes < required_children:
            raise ValueError(
                "worklist factory child budget must cover one builder and one tester per item"
            )
        if spec.work_definition.get("parallelism", 1) > spec.maximum_child_episodes:
            raise ValueError("worklist parallelism exceeds the child Episode budget")
    return definition


_RESULT_FIELDS: dict[GenericCreatorType, frozenset[str]] = {
    GenericCreatorType.PLAN_CONTEXT_CREATOR: frozenset(
        {
            "work_graph", "work_packages", "worklists", "cross_cutting_contracts",
            "dependency_and_integration_edges", "interface_contracts", "assumptions",
            "unresolved_questions", "evidence_gates", "template_assignments",
            "immutable_success_criteria_refs",
        }
    ),
    GenericCreatorType.WORKLIST_FACTORY_CREATOR: frozenset(
        {"item_records", "accepted_artifact_ids", "accepted_evidence_ids", "terminal_counts"}
    ),
    GenericCreatorType.AGENT_LOOP_DESIGNER_CREATOR: frozenset(
        {"episode_contract", "conformance_tests", "failure_recovery_behavior", "terminal_results"}
    ),
    GenericCreatorType.INTEGRATION_HANDOFF_CREATOR: frozenset(
        {"edge_records", "fault_ids", "repair_request_ids", "regression_results"}
    ),
    GenericCreatorType.RAREFACTION_PORTFOLIO_CREATOR: frozenset(
        {"decision", "candidate_id", "marginal_accepted_yield", "budget_reallocation", "stop_reason"}
    ),
    GenericCreatorType.QUALIFICATION_RELEASE_CREATOR: frozenset(
        {"qualified", "package_artifact_id", "verified_gate_ids", "verified_edge_ids", "fault_ids"}
    ),
    GenericCreatorType.GENERIC_ORCHESTRATOR_CREATOR: frozenset(
        {"artifact_evidence_graph", "instance_statuses", "root_episode_progress", "qualification_artifact_id"}
    ),
}


def validate_template_result(
    spec: GenericCreatorInstanceSpec, result: Mapping[str, Any]
) -> None:
    """Validate the narrow, typed result envelope for one registered role."""

    if not isinstance(result, Mapping):
        raise ValueError("generic Creator result must be an object")
    expected = _RESULT_FIELDS[spec.creator_type]
    actual = set(result)
    if actual != expected:
        raise ValueError(
            f"malformed {spec.creator_type.value} result: "
            f"missing={sorted(expected - actual)!r}, unknown={sorted(actual - expected)!r}"
        )
    if spec.creator_type is GenericCreatorType.PLAN_CONTEXT_CREATOR:
        if tuple(result["immutable_success_criteria_refs"]) != spec.immutable_parent_success_criteria_refs:
            raise ValueError("planning result cannot alter immutable parent success criteria")
    if spec.creator_type is GenericCreatorType.QUALIFICATION_RELEASE_CREATOR:
        if not isinstance(result["qualified"], bool):
            raise ValueError("qualified must be boolean")
        if result["qualified"] and result["fault_ids"]:
            raise ValueError("a qualified release cannot also report faults")
    if spec.creator_type is GenericCreatorType.GENERIC_ORCHESTRATOR_CREATOR:
        progress = result["root_episode_progress"]
        if isinstance(progress, bool) or not isinstance(progress, (int, float)) or not 0 <= progress <= 1:
            raise ValueError("root_episode_progress must be normalized to [0, 1]")


def _array(value: object, name: str, *, non_empty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (non_empty and not value):
        suffix = " and non-empty" if non_empty else ""
        raise ValueError(f"{name} must be an array{suffix}")
    return value


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _validate_plan(value: Mapping[str, Any]) -> None:
    _object(value["desired_result_schema"], "desired_result_schema")
    _object(value["constraints_and_safety_bounds"], "constraints_and_safety_bounds")
    _array(value["available_capabilities"], "available_capabilities")
    _array(value["supplied_references"], "supplied_references")
    _array(value["existing_artifacts_and_evidence"], "existing_artifacts_and_evidence")
    _array(value["unresolved_questions"], "unresolved_questions")


def _validate_worklist(value: Mapping[str, Any]) -> None:
    items = _array(value["items"], "items", non_empty=True)
    item_ids = [
        item if isinstance(item, str) else item.get("item_id") if isinstance(item, Mapping) else None
        for item in items
    ]
    if any(not isinstance(item, str) or not item.strip() for item in item_ids):
        raise ValueError("each worklist item must be text or contain a non-empty item_id")
    if len(set(item_ids)) != len(item_ids):
        raise ValueError("worklist item IDs must be unique")
    _object(value["artifact_schema"], "artifact_schema")
    _object(value["builder_episode_template"], "builder_episode_template")
    _object(value["test_episode_template"], "test_episode_template")
    _object(value["shared_constraints"], "shared_constraints")
    gates = _array(value["per_item_acceptance_gates"], "per_item_acceptance_gates", non_empty=True)
    gate_ids = [
        item if isinstance(item, str) else item.get("gate_id") if isinstance(item, Mapping) else None
        for item in gates
    ]
    if any(not isinstance(item, str) or not item.strip() for item in gate_ids):
        raise ValueError("per-item acceptance gates need non-empty gate_id values")
    _object(value["retry_and_stagnation_policy"], "retry_and_stagnation_policy")
    mode = value.get("execution_mode", "serial")
    if mode not in {"serial", "bounded_parallel"}:
        raise ValueError("execution_mode must be serial or bounded_parallel")
    parallelism = value.get("parallelism", 1)
    if isinstance(parallelism, bool) or not isinstance(parallelism, int) or parallelism < 1:
        raise ValueError("parallelism must be a positive integer")
    if mode == "serial" and parallelism != 1:
        raise ValueError("serial worklists must use parallelism 1")


def _validate_loop(value: Mapping[str, Any]) -> None:
    for name in (
        "task_state_schema",
        "observation_schema",
        "transition_rules",
        "result_schema",
        "progress_measurement",
        "stopping_rule",
        "safety_bounds",
    ):
        _object(value[name], name)
    _array(value["allowed_actions_or_tools"], "allowed_actions_or_tools", non_empty=True)
    _array(value["representative_test_scenarios"], "representative_test_scenarios", non_empty=True)


def _validate_integration(value: Mapping[str, Any]) -> None:
    _array(value["component_artifacts"], "component_artifacts", non_empty=True)
    _array(value["interface_contracts"], "interface_contracts", non_empty=True)
    edges = _array(value["dependency_edges"], "dependency_edges", non_empty=True)
    edge_ids = [item.get("edge_id") if isinstance(item, Mapping) else None for item in edges]
    if any(not isinstance(item, str) or not item.strip() for item in edge_ids):
        raise ValueError("integration dependency edges need non-empty edge_id values")
    if len(set(edge_ids)) != len(edge_ids):
        raise ValueError("integration edge IDs must be unique")
    _array(value["integration_scenarios"], "integration_scenarios", non_empty=True)
    _object(value["expected_handoff_behavior"], "expected_handoff_behavior")
    _object(value["gate_ownership"], "gate_ownership")


def _validate_rarefaction(value: Mapping[str, Any]) -> None:
    candidates = _array(value["candidates"], "candidates", non_empty=True)
    if any(not isinstance(item, str) or not item.strip() for item in candidates):
        raise ValueError("rarefaction candidates must be non-empty identifiers")
    for name in (
        "dependency_status",
        "estimated_cost",
        "prior_accepted_yield",
        "uncertainty",
        "integration_unblock_value",
        "remaining_budgets",
        "rarefaction_rules",
    ):
        _object(value[name], name)
    if len(set(candidates)) != len(candidates):
        raise ValueError("rarefaction candidates must be unique")
    for name in (
        "estimated_cost", "prior_accepted_yield", "uncertainty",
        "integration_unblock_value",
    ):
        values = value[name]
        for candidate in candidates:
            number = values.get(candidate, 0)
            if (
                isinstance(number, bool)
                or not isinstance(number, (int, float))
                or not math.isfinite(float(number))
                or number < 0
            ):
                raise ValueError(f"{name}[{candidate!r}] must be finite and non-negative")
    remaining_cost = value["remaining_budgets"].get("cost", 0)
    minimum_yield = value["rarefaction_rules"].get("minimum_marginal_yield", 0)
    for number, name in (
        (remaining_cost, "remaining_budgets.cost"),
        (minimum_yield, "rarefaction_rules.minimum_marginal_yield"),
    ):
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(float(number))
            or number < 0
        ):
            raise ValueError(f"{name} must be finite and non-negative")


def _validate_qualification(value: Mapping[str, Any]) -> None:
    _object(value["integrated_artifact_graph"], "integrated_artifact_graph")
    _array(value["required_gates"], "required_gates", non_empty=True)
    _object(value["evidence_ledger"], "evidence_ledger")
    _object(value["safety_constraints"], "safety_constraints")
    _object(value["deliverable_schema"], "deliverable_schema")


def _validate_orchestrator(value: Mapping[str, Any]) -> None:
    _object(value["task_specification"], "task_specification")
    instance_ids = _array(value["template_instance_ids"], "template_instance_ids", non_empty=True)
    if any(not isinstance(item, str) or not item.strip() for item in instance_ids):
        raise ValueError("template_instance_ids must contain non-empty text")
    if len(set(instance_ids)) != len(instance_ids):
        raise ValueError("template_instance_ids must be unique")
    _object(value["budget_allocation"], "budget_allocation")
    for name in ("rarefaction_instance_id", "integration_instance_id", "qualification_instance_id"):
        if not isinstance(value[name], str) or not value[name]:
            raise ValueError(f"{name} must be non-empty text")
        if value[name] not in instance_ids:
            raise ValueError(f"{name} must identify a declared template instance")


_VALIDATORS: dict[GenericCreatorType, Callable[[Mapping[str, Any]], None]] = {
    GenericCreatorType.PLAN_CONTEXT_CREATOR: _validate_plan,
    GenericCreatorType.WORKLIST_FACTORY_CREATOR: _validate_worklist,
    GenericCreatorType.AGENT_LOOP_DESIGNER_CREATOR: _validate_loop,
    GenericCreatorType.INTEGRATION_HANDOFF_CREATOR: _validate_integration,
    GenericCreatorType.RAREFACTION_PORTFOLIO_CREATOR: _validate_rarefaction,
    GenericCreatorType.QUALIFICATION_RELEASE_CREATOR: _validate_qualification,
    GenericCreatorType.GENERIC_ORCHESTRATOR_CREATOR: _validate_orchestrator,
}


def select_rarefaction_candidate(work_definition: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic next-work decision from declared portfolio facts."""

    TEMPLATE_REGISTRY[GenericCreatorType.RAREFACTION_PORTFOLIO_CREATOR].validate(work_definition)
    _validate_rarefaction(work_definition)
    candidates = [str(item) for item in work_definition["candidates"]]
    dependencies = work_definition["dependency_status"]
    cost = work_definition["estimated_cost"]
    prior_yield = work_definition["prior_accepted_yield"]
    uncertainty = work_definition["uncertainty"]
    unblock = work_definition["integration_unblock_value"]
    budget = work_definition["remaining_budgets"]
    rules = work_definition["rarefaction_rules"]
    maximum_cost = float(budget.get("cost", 0))
    minimum_marginal_yield = float(rules.get("minimum_marginal_yield", 0))

    ranked: list[tuple[float, str]] = []
    for candidate in candidates:
        if dependencies.get(candidate) not in {"ready", "satisfied", True}:
            continue
        candidate_cost = float(cost.get(candidate, 0))
        if candidate_cost <= 0 or candidate_cost > maximum_cost:
            continue
        expected_unique_yield = max(0.0, float(prior_yield.get(candidate, 0)))
        exploration = max(0.0, float(uncertainty.get(candidate, 0)))
        integration_value = max(0.0, float(unblock.get(candidate, 0)))
        marginal = (expected_unique_yield + exploration + integration_value) / candidate_cost
        if marginal >= minimum_marginal_yield:
            ranked.append((marginal, candidate))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if not ranked:
        return {"decision": "stop", "candidate_id": None, "marginal_accepted_yield": 0.0}
    score, candidate = ranked[0]
    return {"decision": "select", "candidate_id": candidate, "marginal_accepted_yield": score}


__all__ = [
    "CreatorTemplateDefinition",
    "TEMPLATE_REGISTRY",
    "select_rarefaction_candidate",
    "validate_template_result",
    "validate_template_spec",
]
