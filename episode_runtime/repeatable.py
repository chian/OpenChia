"""Invocation checks for explicitly approved calls to existing templates."""

from __future__ import annotations

import inspect
from types import MappingProxyType

from episode_builder.call_plan import call_role
from handoff_library import ParentRequest, ParentRequestAddress, admit_parent_request
from method_loop import EpisodeRequest, EpisodeTree
from method_loop.episode import _cyclic_tree_edges
from method_loop.identities import EpisodeRef


def build_declared_tree(plan, grains):
    children = {}
    by_slot = {
        (edge.parent_local_id, edge.slot_name): edge.child_local_id
        for edge in plan.all_edges
    }
    for node in plan.nodes:
        targets = dict.fromkeys(
            by_slot[(node.local_id, slot)] for slot in node.child_slot_names
        )
        if targets:
            children[grains[node.local_id]] = tuple(
                grains[target] for target in targets
            )
    recursive = _cyclic_tree_edges(children)
    return EpisodeTree(
        root=grains[plan.root_local_id],
        children=children,
        self_nesting=tuple(
            sorted(parent for parent, child in recursive if parent == child)
        ),
        recursive_edges=tuple(sorted(recursive)),
    )


def declared_call_selections(binding, edges):
    """Actual module bindings must retain every approved policy, not just metadata."""
    components = {item.name: item for item in binding.components}
    selections = []
    for edge in edges:
        if edge.repeatable_call is None:
            continue
        slot = binding.child_slot(edge.slot_name)
        if slot.accepted_interfaces != (edge.child_interface,):
            raise ValueError(
                "repeatable slot must accept only its exact callee interface"
            )
        selections.extend(
            (call_role(slot.name, field), getattr(slot, field))
            for field in ("build_child", "prepare_request", "receive_result")
        )
        for field in (
            "request_schema",
            "authority_attenuation",
            "invocation_admission",
        ):
            role = call_role(slot.name, field)
            component = components.get(role.removeprefix("component."))
            if component is None:
                raise ValueError(f"repeatable slot omits {role}")
            selections.append((role, component))
    return tuple(selections)


def admitted_builder(
    *,
    edge,
    parent_path,
    parent_request,
    run_id,
    child_grain,
    definitions,
    current_path,
    construct,
):
    """Guard a supplied constructor; emitted code cannot select a different target.

    These functions are exact approved library implementations. A refiner policy
    must additionally cross the host boundary: a worker claim or the mere
    presence of a call binding does not create a campaign assignment.
    """
    functions = {function.definition_id: function for function in definitions}

    async def invoke(field, request, invocation):
        selection = getattr(edge.repeatable_call, field)
        function = functions.get(selection.definition_id)
        if function is None or any(
            getattr(function, name) != getattr(selection, name)
            for name in ("library", "function_id", "interface")
        ):
            raise ValueError(f"repeatable {field} has no exact executable definition")
        function.admit_arguments(selection.arguments)
        result = function.load()(
            request=request,
            parent_request=parent_request,
            invocation=invocation,
            **selection.arguments,
        )
        return await result if inspect.isawaitable(result) else result

    async def build(key, request, goal_view, collaborators):
        if tuple(current_path()) != parent_path:
            raise ValueError("repeatable builder is outside its owning invocation")
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(request, EpisodeRequest)
        ):
            raise ValueError("repeatable child requires a key and typed EpisodeRequest")
        if (
            request.goal.parent_goal_id != parent_request.goal.goal_id
            or request.goal.task_context != parent_request.goal.task_context
        ):
            raise ValueError("repeatable child changes its parent goal or task context")
        if not isinstance(request.message, ParentRequest):
            raise ValueError("repeatable child requires an admitted ParentRequest")
        path = (*parent_path, (child_grain.name, key))
        child = EpisodeRef(run_id=run_id, path=path)
        parent = EpisodeRef(run_id=run_id, path=parent_path)
        admit_parent_request(
            request.message.as_record(),
            ParentRequestAddress(
                request.message.request_id,
                parent.episode_id,
                child.episode_id,
                request.goal.goal_id,
                edge.child_interface,
            ),
            edge.request_payload_contract,
        )
        invocation = MappingProxyType({
            "run_id": run_id,
            "caller_local_id": edge.parent_local_id,
            "callee_template_local_id": edge.child_local_id,
            "slot_name": edge.slot_name,
            "parent_path": parent_path,
            "child_path": path,
            "parent_episode_id": parent.episode_id,
            "child_episode_id": child.episode_id,
        })
        if await invoke("request_schema", request, invocation) != request:
            raise ValueError(
                "repeatable request schema must admit the unchanged typed request"
            )
        if await invoke("authority_attenuation", request, invocation) is not True:
            raise ValueError(
                "repeatable child did not satisfy its authority attenuation"
            )
        if await invoke("invocation_admission", request, invocation) is not True:
            raise ValueError("repeatable invocation was not admitted")
        return construct(key, request, goal_view, collaborators)

    return build
