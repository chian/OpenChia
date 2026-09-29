from __future__ import annotations

from typing import Any, Optional

from agent.episode_contracts import EVIDENCE_GATE_SCORE_PROGRESS_ADAPTER, Sha256Digest
from agent.generic_creator_models import (
    CancellationBehavior,
    GenericCreatorInstanceSpec,
    GenericCreatorType,
    GenericEvidenceRequirement,
    GenericProgressMeasurement,
    GenericRetryPolicy,
)


def work_definition(creator_type: GenericCreatorType) -> dict[str, Any]:
    definitions: dict[GenericCreatorType, dict[str, Any]] = {
        GenericCreatorType.PLAN_CONTEXT_CREATOR: {
            "stable_task_goal": "Produce a typed result",
            "desired_result_schema": {"type": "object"},
            "constraints_and_safety_bounds": {"network": "read_only"},
            "available_capabilities": ["read_file"],
            "supplied_references": [],
            "existing_artifacts_and_evidence": [],
            "unresolved_questions": [],
        },
        GenericCreatorType.WORKLIST_FACTORY_CREATOR: {
            "items": [{"item_id": "item_a"}, {"item_id": "item_b"}],
            "artifact_schema": {"type": "object"},
            "builder_episode_template": {"template": "build"},
            "test_episode_template": {"template": "test"},
            "shared_constraints": {"bounded": True},
            "per_item_acceptance_gates": [{"gate_id": "check_a"}],
            "retry_and_stagnation_policy": {"maximum_attempts": 2},
            "execution_mode": "serial",
            "parallelism": 1,
        },
        GenericCreatorType.AGENT_LOOP_DESIGNER_CREATOR: {
            "task_state_schema": {"type": "object"},
            "allowed_actions_or_tools": ["observe"],
            "observation_schema": {"type": "object"},
            "transition_rules": {"kind": "table"},
            "result_schema": {"type": "object"},
            "progress_measurement": {"kind": "host"},
            "stopping_rule": {"kind": "bounded"},
            "safety_bounds": {"iterations": 3},
            "representative_test_scenarios": [{"scenario_id": "normal"}],
        },
        GenericCreatorType.INTEGRATION_HANDOFF_CREATOR: {
            "component_artifacts": [{"artifact_id": "component_a"}],
            "interface_contracts": [{"interface_id": "interface_a"}],
            "dependency_edges": [{"edge_id": "edge_a", "artifact_ids": []}],
            "integration_scenarios": [{"scenario_id": "handoff_a"}],
            "expected_handoff_behavior": {"result": "accepted"},
            "gate_ownership": {"edge_a": "child"},
        },
        GenericCreatorType.RAREFACTION_PORTFOLIO_CREATOR: {
            "candidates": ["candidate_a", "candidate_b"],
            "dependency_status": {"candidate_a": "ready", "candidate_b": "ready"},
            "estimated_cost": {"candidate_a": 2, "candidate_b": 1},
            "prior_accepted_yield": {"candidate_a": 1, "candidate_b": 0.25},
            "uncertainty": {"candidate_a": 0, "candidate_b": 0.25},
            "integration_unblock_value": {"candidate_a": 0, "candidate_b": 1},
            "remaining_budgets": {"cost": 2},
            "rarefaction_rules": {"minimum_marginal_yield": 0.1},
        },
        GenericCreatorType.QUALIFICATION_RELEASE_CREATOR: {
            "integrated_artifact_graph": {"artifacts": []},
            "required_gates": ["build", "integration"],
            "evidence_ledger": {"manifest_id": "manifest"},
            "safety_constraints": {"required": True},
            "deliverable_schema": {"type": "object"},
        },
        GenericCreatorType.GENERIC_ORCHESTRATOR_CREATOR: {
            "task_specification": {"schema_version": 1},
            "template_instance_ids": ["planner", "portfolio", "integration", "qualification"],
            "budget_allocation": {"iterations": 20},
            "rarefaction_instance_id": "portfolio",
            "integration_instance_id": "integration",
            "qualification_instance_id": "qualification",
        },
    }
    return definitions[creator_type]


def creator_spec(
    instance_id: str = "root",
    *,
    creator_type: GenericCreatorType = GenericCreatorType.PLAN_CONTEXT_CREATOR,
    parent_instance_id: Optional[str] = None,
    namespace: Optional[str] = None,
    capabilities: tuple[str, ...] = ("read_file",),
    maximum_iterations: int = 20,
    maximum_child_episodes: int = 5,
    maximum_depth: int = 3,
    maximum_elapsed_time: float = 100.0,
    may_create_child_creators: bool = True,
    definition: Optional[dict[str, Any]] = None,
) -> GenericCreatorInstanceSpec:
    return GenericCreatorInstanceSpec(
        instance_id=instance_id,
        creator_type=creator_type,
        parent_instance_id=parent_instance_id,
        local_goal="Exercise a generic Creator safely",
        immutable_parent_success_criteria_refs=("criteria_a",),
        input_artifacts=(),
        work_definition=definition or work_definition(creator_type),
        result_schema={"type": "object"},
        dependency_ids=(),
        interface_contracts=(),
        progress_measurement=GenericProgressMeasurement(
            adapter_id=EVIDENCE_GATE_SCORE_PROGRESS_ADAPTER,
            gate_manifest_id=f"manifest_{instance_id}",
            description="Accepted required evidence gates",
        ),
        target=1.0,
        minimum_delta=0.1,
        stagnation_window=3,
        evidence_requirements=(
            GenericEvidenceRequirement("evidence_a", "test_result", "host_test", 1),
        ),
        assignable_capabilities=capabilities,
        shared_state_namespace=namespace or instance_id,
        maximum_iterations=maximum_iterations,
        maximum_child_episodes=maximum_child_episodes,
        maximum_depth=maximum_depth,
        maximum_elapsed_time=maximum_elapsed_time,
        fault_ownership={},
        parent_gates_may_satisfy=("gate_a",),
        cancellation_behavior=CancellationBehavior.CASCADE_IMMEDIATELY,
        retry_behavior=GenericRetryPolicy(2, True, True),
        may_create_child_creators=may_create_child_creators,
    )


RUNTIME_IDENTITY = Sha256Digest.of_bytes(b"frozen-test-runtime")
