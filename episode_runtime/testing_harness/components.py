"""Resolve component inputs and exact candidate bindings for the common service."""

import inspect

from ..components import ComponentScope, call_arguments, component_input
from .recordings import load_recording


def bound_definition(binding):
    from episode_builder.planner import _library_functions

    matches = [
        item
        for item in _library_functions()
        if item.definition_id == binding["definition_id"]
    ]
    if len(matches) != 1:
        raise ValueError(
            "component definition is unavailable in the existing function catalog"
        )
    definition = matches[0]
    definition.admit_arguments(binding["arguments"])
    return definition


def describe_bindings(node, definition_id):
    result = []
    for binding in node.as_record()["selected_function_bindings"]:
        if binding["source"] != "library" or binding["definition_id"] != definition_id:
            continue
        definition = bound_definition(binding)
        result.append({
            "binding": binding,
            "input_type": definition.input_type,
            "output_type": definition.output_type,
            "call_signature": [
                {
                    "name": parameter.name,
                    "kind": parameter.kind.name.lower(),
                    "required": parameter.default is inspect.Parameter.empty
                    and parameter.kind
                    not in {
                        inspect.Parameter.VAR_POSITIONAL,
                        inspect.Parameter.VAR_KEYWORD,
                    },
                }
                for parameter in inspect.signature(
                    definition.load()
                ).parameters.values()
            ],
            "configuration_is_frozen": True,
        })
    return result


def selected_inputs(request, *, artifacts, runs, duet_id):
    if request["start"]["kind"] == "fresh":
        return component_input(request["start"]["input_payload"])
    if request["start"]["kind"] != "saved_inputs" or runs is None:
        raise ValueError("component saved inputs require their Run recording")
    source, _ = load_recording(
        artifacts, runs, request["start"]["artifact_ref"], duet_id
    )
    scope = source.execution_scope
    if not isinstance(scope, ComponentScope):
        raise ValueError(
            "component saved inputs require a component recording, not workflow root inputs"
        )
    if (
        scope.entry_local_id != request["scope"]["entry_local_id"]
        or scope.binding["definition_id"] != request["scope"]["component_definition_id"]
    ):
        raise ValueError("saved component inputs belong to another owner or definition")
    return component_input(scope.input_payload)


def resolve_component_scope(request, *, inputs, artifacts, runs):
    payload = selected_inputs(
        request,
        artifacts=artifacts,
        runs=runs,
        duet_id=inputs.build_request.frozen_workflow.duet_id.value,
    )
    nodes = {node.local_id: node for node in inputs.plan.nodes}
    node = nodes[request["scope"]["entry_local_id"]]
    matches = [
        binding
        for binding in node.selected_function_bindings
        if binding["source"] == "library"
        and binding["definition_id"] == request["scope"]["component_definition_id"]
        and binding["role"] == payload["binding_role"]
    ]
    if len(matches) != 1:
        raise ValueError(
            "component inputs must name one exact bound library role from this candidate"
        )
    target = bound_definition(matches[0]).load()
    try:
        inspect.signature(target).bind(**call_arguments(matches[0], payload))
    except TypeError as exc:
        raise ValueError(
            f"component inputs do not fit its registered call signature: {exc}"
        ) from exc
    ancestry = [node.grain_name]
    parent = node.parent_local_id
    while parent is not None:
        ancestor = nodes[parent]
        ancestry.append(ancestor.grain_name)
        parent = ancestor.parent_local_id
    scope = ComponentScope(
        kind="component",
        entry_local_id=node.local_id,
        included_local_ids=(node.local_id,),
        included_grains=(node.grain_name,),
        path_grains=tuple(reversed(ancestry)),
        workflow_hash=inputs.build_request.frozen_workflow.workflow_hash.value,
        binding=matches[0],
        input_payload=payload,
    )
    scope.validate_plan(inputs.plan)
    return scope
