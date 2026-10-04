"""Host materialization of exact call bindings after concrete tree planning.

Call targets may be ancestors, so their interfaces are resolved only after every
concrete node exists. The planner cannot invent or silently omit a call slot.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from agent.episode_call_contracts import CALL_FUNCTION_FIELDS
from function_library.episode_calls import BUILD_REPEATABLE_CHILD

from ._contract_base import _record
from ._contract_plan import EdgeMaterializationPlan


def call_role(slot, field):
    if field in {"prepare_request", "receive_result", "build_child"}:
        return f"edge.{slot}.{field}"
    return f"component.repeatable_{slot}_{field}"


def call_bindings(call):
    bindings = []
    for name in (*CALL_FUNCTION_FIELDS, "build_child"):
        selection = (
            {
                **{
                    key: getattr(BUILD_REPEATABLE_CHILD, key)
                    for key in ("library", "function_id", "interface", "definition_id")
                },
                "arguments": {},
            }
            if name == "build_child"
            else getattr(call, name).as_record()
        )
        bindings.append({
            "role": call_role(call.slot_name, name),
            "source": "library",
            **selection,
            "basis": f"frozen repeatable_calls.{call.caller_local_id}.{call.slot_name}.{name}",
        })
    return tuple(bindings)


def validate_functions(call, functions):
    catalog = {function.definition_id: function for function in functions}
    for binding in call_bindings(call):
        function = catalog.get(binding["definition_id"])
        if function is None or any(
            binding[key] != getattr(function, key)
            for key in ("library", "function_id", "interface")
        ):
            raise ValueError(
                f"{binding['role']} does not resolve to an exact registered function"
            )
        function.admit_arguments(binding["arguments"])


def materialize_call(call, nodes, functions):
    """Return a replaced caller and its call edge; leave input plans untouched."""
    validate_functions(call, functions)
    caller = nodes[call.caller_local_id]
    callee = nodes[call.callee_template_local_id]
    required = call_bindings(call)
    current = {
        binding["role"]: binding
        for binding in caller.as_record()["selected_function_bindings"]
    }
    if call.slot_name in caller.child_slot_names:
        # Successor reuse is allowed only for the same frozen slot and bindings.
        if any(current.get(binding["role"]) != binding for binding in required):
            raise ValueError("repeatable call collides with an existing child slot")
    else:
        if any(binding["role"] in current for binding in required):
            raise ValueError("repeatable call collides with an existing function role")
        current.update((binding["role"], binding) for binding in required)
        caller = replace(
            caller,
            topology_role="branch",
            child_slot_names=(*caller.child_slot_names, call.slot_name),
            selected_function_bindings=tuple(current.values()),
            function_definition_ids=tuple(
                sorted({
                    binding["definition_id"]
                    for binding in current.values()
                    if binding["source"] == "library"
                })
            ),
        )
    return caller, EdgeMaterializationPlan(
        parent_local_id=call.caller_local_id,
        child_local_id=call.callee_template_local_id,
        slot_name=call.slot_name,
        child_interface=callee.interface,
        prepare_request=call.prepare_request.definition_id,
        receive_result=call.receive_result.definition_id,
        build_child=BUILD_REPEATABLE_CHILD.definition_id,
        request_payload_contract=callee.request_payload_contract,
        result_payload_contract=callee.result_payload_contract,
        derivation_basis={
            "basis": f"frozen repeatable_calls.{call.caller_local_id}.{call.slot_name}"
        },
        repeatable_call=call,
    )


def validate_planned_calls(nodes, edges, expected_calls, *, ready):
    expected = {(call.caller_local_id, call.slot_name): call for call in expected_calls}
    actual = {
        (edge.parent_local_id, edge.slot_name): edge.repeatable_call for edge in edges
    }
    if len(actual) != len(edges) or any(
        expected.get(key) != value for key, value in actual.items()
    ):
        raise ValueError("materialization changes frozen repeatable call authority")
    if ready and actual != expected:
        raise ValueError("materialization must cover every frozen repeatable call")
    by_id = {node.local_id: node for node in nodes}
    for edge in edges:
        selected = {
            binding["role"]: binding
            for binding in by_id[edge.parent_local_id].as_record()[
                "selected_function_bindings"
            ]
        }
        if any(
            selected.get(binding["role"]) != binding
            for binding in call_bindings(edge.repeatable_call)
        ):
            raise ValueError("materialization changes frozen repeatable call functions")


def calls_record(edges):
    if not edges:
        return {}
    return {
        "repeatable_calls": {
            "version": 1,
            "edges": [edge.as_record() for edge in edges],
        }
    }


def calls_from_record(record):
    if "repeatable_calls" not in record:
        return ()
    value = _record(
        record["repeatable_calls"],
        "materialized repeatable calls",
        {"version", "edges"},
    )
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("unsupported materialized repeatable-call version")
    if not isinstance(value["edges"], list) or not value["edges"]:
        raise ValueError("materialized repeatable calls require a non-empty edge array")
    return tuple(EdgeMaterializationPlan.from_record(item) for item in value["edges"])


def call_extension_keys(value):
    return (
        {"repeatable_calls"}
        if isinstance(value, Mapping) and "repeatable_calls" in value
        else set()
    )
