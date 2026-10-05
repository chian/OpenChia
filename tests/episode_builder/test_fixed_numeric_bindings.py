"""Fixed controller semantics must be supplied, not inferred by the planner."""

from dataclasses import replace
import json

import pytest

from episode_builder.service import EpisodeBuilder
from episode_builder.store import BuildStore
from function_library.materialization_checks import NODE_PLAN_CONSISTENCY
from function_library.reasoning import CONTROLLER
from iterative_episode_refiner.plan_repair import choices, revise_plan
from llm_call_library import CallOptions, ModelTransportResponse, model_transport_scope
from numeric_control_library import MARGINAL_DOMINATED_HYPERVOLUME
from tests.episode_runtime.test_reasoning_workflow import (
    _approved_request,
    _module_response,
    _plan_response,
)


@pytest.mark.asyncio
async def test_builder_supplies_the_controller_facts_it_requires(tmp_path):
    request = _approved_request(tmp_path)
    builds = BuildStore(tmp_path / "builds")
    fixed = {
        "controller.composer": CONTROLLER,
        "controller.credit": MARGINAL_DOMINATED_HYPERVOLUME,
    }
    supplied = {}

    async def model(call):
        prompt = json.loads(call.messages[-1]["content"])
        if "node" in prompt:
            supplied.update({
                binding["role"]: binding
                for binding in prompt["architecture_owned_numeric_bindings"]
            })
            response = _plan_response(prompt)
            response["selected_function_bindings"] = [
                binding for binding in response["selected_function_bindings"]
                if binding["role"] not in fixed
            ]
        else:
            response = _module_response(prompt)
        return ModelTransportResponse(text=json.dumps(response), route={})

    with model_transport_scope(model):
        receipt = await EpisodeBuilder(
            store=builds,
            planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"selector": {}, "executor": {}},
        ).build(request)

    assert receipt.materialized, receipt.deficits
    plan = builds.read_plan(receipt.plan_id)
    actual = {
        binding["role"]: binding
        for binding in plan.nodes[0].selected_function_bindings
    }
    for role, function in fixed.items():
        assert actual[role] == supplied[role]
        assert actual[role]["source"] == "library"
        assert actual[role]["definition_id"] == function.definition_id
        assert not actual[role]["arguments"]

    inputs = builds.inspection_inputs_for_receipt(receipt.receipt_id)
    node_id = plan.root_local_id
    proposed = choices(plan, node_id, request.frozen_workflow.workflow.repeatable_calls)
    proposed["selected_function_bindings"] = [
        binding for binding in proposed["selected_function_bindings"]
        if binding["role"] not in fixed
    ]
    repaired = revise_plan(plan, inputs, {node_id: proposed}, {node_id: {None}})
    assert not repaired.deficits, repaired.deficits
    assert repaired.nodes == plan.nodes

    # Saved artifacts are checked, not normalized into passing the same check.
    tampered = replace(plan.nodes[0], selected_function_bindings=tuple(
        {**binding, "arguments": {"unauthorized": True}}
        if binding["role"] == "controller.composer" else binding
        for binding in plan.nodes[0].selected_function_bindings
    ))
    finding = NODE_PLAN_CONSISTENCY.load()(
        request, replace(plan, nodes=(tampered,)), node_id
    )
    assert any(
        item["code"] == "numeric_binding_mismatch"
        for item in finding["diagnostics"]
    )
