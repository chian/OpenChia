"""Builder reference evidence includes implementations, not just catalog prose."""

import json
from dataclasses import replace

import pytest

from agent.episode_contracts import Sha256Digest
from episode_builder.emitter import EpisodeModuleEmitter
from episode_builder.reference import EpisodeReferenceResolver
from episode_builder.service import EpisodeBuilder
from episode_builder.store import BuildStore
from llm_call_library import CallOptions
from llm_call_library.transport import ModelTransportResponse, model_transport_scope
from tests.episode_runtime.test_reasoning_workflow import (
    _approved_request,
    _module_response,
    _plan_response,
)


@pytest.mark.asyncio
async def test_reference_implementations_reach_both_calls_and_are_bound_to_plan(
    tmp_path,
):
    request = _approved_request(tmp_path)
    store = BuildStore(tmp_path)
    observed = {}

    async def model(call):
        prompt = json.loads(call.messages[-1]["content"])
        if "node" in prompt:
            observed["planning"] = prompt["reference"]
            response = _plan_response(prompt)
        else:
            observed["emission"] = prompt["reference_implementation_evidence"]
            response = _module_response(prompt)
        return ModelTransportResponse(text=json.dumps(response), route={})

    with model_transport_scope(model):
        receipt = await EpisodeBuilder(
            store=store,
            planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"selector": {}, "executor": {}},
        ).build(request)

    assert receipt.status == "materialized", receipt.deficits
    design = request.frozen_workflow.workflow.episodes[0]
    context = EpisodeReferenceResolver().resolve(design.episode_reference)
    reference = observed["planning"]
    assert reference == observed["emission"] == context.as_record()
    required_modules = {
        function.implementation.module
        for function in context.design.function_definitions
    }
    assert set(reference["implementation_sources"]) == required_modules
    assert all(reference["implementation_sources"].values())

    node = store.read_plan(receipt.plan_id).nodes[0]
    assert node.reference_evidence_hash == Sha256Digest.of_record(reference)
    # A changed implementation must not silently become evidence for the same
    # admitted plan, even when all library definition identifiers are unchanged.
    changed_sources = dict(context.implementation_sources)
    module = next(iter(changed_sources))
    changed_sources[module] += "\n# revised implementation evidence\n"
    changed = replace(context, implementation_sources=changed_sources)
    with pytest.raises(ValueError, match="reference evidence differs"):
        EpisodeModuleEmitter._validate_inputs(
            design.contract, node, {}, (), changed, node.module_name, None
        )
