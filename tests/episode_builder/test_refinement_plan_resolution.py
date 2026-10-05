"""A repaired implementation plan must not inherit its resolved old finding."""

from dataclasses import replace
import json

import pytest

from episode_builder.service import EpisodeBuilder
from episode_builder.store import BuildStore
from iterative_episode_refiner.plan_repair import choices, revise_plan
from llm_call_library import CallOptions, ModelTransportResponse, model_transport_scope
from tests.episode_runtime.test_reasoning_workflow import (
    _approved_request,
    _plan_response,
)


@pytest.mark.asyncio
async def test_plan_revision_rechecks_choices_without_retaining_resolved_old_ambiguity(
    tmp_path,
):
    request = _approved_request(tmp_path)
    builds = BuildStore(tmp_path)
    finding = {
        "field_path": "result_channel_names",
        "detail": "The implementation channel is unresolved.",
    }

    async def model(call):
        payload = _plan_response(json.loads(call.messages[-1]["content"]))
        payload["unresolved"] = [finding]
        return ModelTransportResponse(text=json.dumps(payload), route={})

    with model_transport_scope(model):
        receipt = await EpisodeBuilder(
            store=builds,
            planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"selector": {}, "executor": {}},
        ).build(request)
    assert not receipt.materialized
    inputs = builds.inspection_inputs_for_receipt(receipt.receipt_id)
    original = inputs.plan
    node_id = original.root_local_id
    assert any(item.code == "design_choice_unresolved" for item in original.deficits)
    payload = choices(
        original, node_id, request.frozen_workflow.workflow.repeatable_calls
    )
    payload["unresolved"] = []
    revised = revise_plan(original, inputs, {node_id: payload}, {node_id: {None}})
    assert not revised.deficits, revised.deficits
    assert builds.read_plan(original.plan_id) == original
    assert revised.nodes == original.nodes

    # The native consistency checks still reject changing the required channel
    # selection without corresponding bindings; clearing prose is insufficient.
    with pytest.raises((TypeError, ValueError)):
        broken = replace(revised.nodes[0], result_channel_ids=("wrong-channel",))
        replace(revised, nodes=(broken,)).validate_against(
            request, inputs.build_attempt
        )
