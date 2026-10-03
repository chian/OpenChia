"""The Builder's deterministic conversion between choices and typed plans.

Initial planning and scoped candidate repair share this conversion. Neither
caller gets to supply contract, module, channel, or reference identities.
"""

from agent.duet_contracts import canonical_json
from agent.episode_contracts import Sha256Digest

from ._contract_plan import EdgeMaterializationPlan, NodeMaterializationPlan


CHOICE_FIELDS = (
    "interface",
    "result_channel_names",
    "request_payload_contract",
    "result_payload_contract",
    "selected_function_bindings",
    "generated_component_specs",
    "prompt_specs",
    "goal_state_spec",
    "derivation_basis",
)


def node_choices(node, edges, *, unresolved=(), calls=()):
    """Recover planner input, excluding host-installed repeatable bindings."""
    from .call_plan import call_bindings

    record = node.as_record()
    call_roles = {binding["role"] for call in calls for binding in call_bindings(call)}
    result = {key: record[key] for key in CHOICE_FIELDS}
    result["selected_function_bindings"] = [
        binding
        for binding in result["selected_function_bindings"]
        if binding["role"] not in call_roles
    ]
    result["child_slots"] = [
        {
            **{
                key: edge.as_record()[key]
                for key in (
                    "child_local_id",
                    "slot_name",
                    "child_interface",
                    "request_payload_contract",
                    "result_payload_contract",
                    "prepare_request",
                    "receive_result",
                    "build_child",
                )
            },
            "basis": edge.derivation_basis.get(
                "basis", canonical_json(edge.derivation_basis)
            ),
        }
        for edge in edges
    ]
    result["unresolved"] = [dict(item) for item in unresolved]
    return result


def materialize_node_choices(design, payload, reference_context, *, has_children):
    """Convert admitted planner choices; structural identities are host-owned."""
    from .planner import _module_name, _result_channel_ids

    selected = tuple(payload["selected_function_bindings"])
    channel_names = tuple(payload["result_channel_names"])
    return NodeMaterializationPlan(
        local_id=design.local_id,
        parent_local_id=design.workflow_parent_local_id,
        contract_hash=design.contract.spec_hash,
        reference_episode_id=(
            None
            if design.episode_reference is None
            else design.episode_reference.episode_id
        ),
        reference_evidence_hash=(
            None
            if reference_context is None
            else Sha256Digest.of_record(reference_context.as_record())
        ),
        module_name=_module_name(design.local_id, design.contract.spec_hash.value),
        interface=str(payload["interface"]),
        grain_name=design.local_id,
        topology_role="branch" if has_children else "leaf",
        capability_names=design.contract.execution_capability_names,
        result_channel_names=channel_names,
        result_channel_ids=_result_channel_ids(design, channel_names),
        request_payload_contract=payload["request_payload_contract"],
        result_payload_contract=payload["result_payload_contract"],
        selected_function_bindings=selected,
        generated_component_specs=tuple(payload["generated_component_specs"]),
        prompt_specs=tuple(payload["prompt_specs"]),
        goal_state_spec=payload["goal_state_spec"],
        child_slot_names=tuple(
            str(item["slot_name"]) for item in payload["child_slots"]
        ),
        derivation_basis=payload["derivation_basis"],
        function_definition_ids=tuple(
            sorted({
                str(item["definition_id"])
                for item in selected
                if str(item.get("source")) == "library"
            })
        ),
    )


def materialize_edge_choices(parent_local_id, child, raw):
    """Construct an edge after the caller has checked the child's exact facts."""
    return EdgeMaterializationPlan(
        parent_local_id=parent_local_id,
        child_local_id=child.local_id,
        slot_name=str(raw["slot_name"]),
        child_interface=child.interface,
        prepare_request=str(raw["prepare_request"]),
        receive_result=str(raw["receive_result"]),
        build_child=str(raw["build_child"]),
        request_payload_contract=child.request_payload_contract,
        result_payload_contract=child.result_payload_contract,
        derivation_basis={
            "prepare_request": raw["prepare_request"],
            "receive_result": raw["receive_result"],
            "build_child": raw["build_child"],
            "basis": raw["basis"],
        },
    )
