"""Host-owned declaration embedded in every materialized Episode module."""

from __future__ import annotations

from agent.episode_contracts import EpisodeCreationSpec

from ._contract_plan import EdgeMaterializationPlan, NodeMaterializationPlan


DECLARATION_EXPORT = "OPENCHIA_BUILD_DECLARATION"


def build_module_declaration(
    contract: EpisodeCreationSpec,
    plan: NodeMaterializationPlan,
    direct_edges: tuple[EdgeMaterializationPlan, ...],
) -> dict[str, object]:
    """Bind inert source to the exact frozen contract, node plan, and edges."""

    if not isinstance(contract, EpisodeCreationSpec):
        raise TypeError("contract must be an EpisodeCreationSpec")
    if not isinstance(plan, NodeMaterializationPlan):
        raise TypeError("plan must be a NodeMaterializationPlan")
    if contract.spec_hash != plan.contract_hash:
        raise ValueError("node plan does not belong to the frozen contract")
    if not isinstance(direct_edges, tuple) or any(
        not isinstance(edge, EdgeMaterializationPlan) for edge in direct_edges
    ):
        raise TypeError("direct_edges must contain EdgeMaterializationPlan values")
    if any(edge.parent_local_id != plan.local_id for edge in direct_edges):
        raise ValueError("direct edge belongs to another parent Episode")
    if {edge.slot_name for edge in direct_edges} != set(plan.child_slot_names):
        raise ValueError("direct edges do not exactly cover the node child slots")
    return {
        "episode_local_id": plan.local_id,
        "frozen_contract": contract.as_record(),
        "node_plan": plan.as_record(),
        "direct_edges": [
            edge.as_record()
            for edge in sorted(
                direct_edges,
                key=lambda item: (item.slot_name, item.child_local_id),
            )
        ],
    }


__all__ = ["DECLARATION_EXPORT", "build_module_declaration"]
