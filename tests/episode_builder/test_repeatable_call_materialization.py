"""Exact call authority survives the real approval/build/source-admission path.

The policies here are existing registered pointers used as identity sentinels;
this test does not execute them as recursive policies or claim host transport.
"""

import json
import sys
from dataclasses import replace

import pytest

from agent.episode_call_contracts import EpisodeRepeatableCallSpec
from agent.episode_contracts import EpisodeFunctionSelectionSpec
from episode_builder._contract_chain import WorkflowMaterializationPlan
from episode_builder.service import EpisodeBuilder
from episode_builder.store import BuildStore
from episode_runtime.contracts import RunRegistration
from episode_runtime.linker import prepare_source_package
from handoff_library import ADMIT_PARENT_REQUEST, ADMIT_CHILD_RESULT, DuetLaunchRequest
from llm_call_library.transport import ModelTransportResponse, model_transport_scope
from tests.episode_runtime.test_reasoning_workflow import (
    _approved_request,
    _plan_response,
    _module_response,
)
from tests.episode_runtime.conftest import claim_store, oid


def selected(function):
    return EpisodeFunctionSelectionSpec(
        function.library,
        function.function_id,
        function.interface,
        function.definition_id,
        {},
    )


def call():
    request = selected(ADMIT_PARENT_REQUEST)
    return EpisodeRepeatableCallSpec(
        "inquiry",
        "nested_parts",
        "inquiry",
        request,
        selected(ADMIT_CHILD_RESULT),
        request,
        request,
        request,
    )


async def build(tmp_path, calls):
    request = _approved_request(tmp_path, repeatable_calls=calls)
    store = BuildStore(tmp_path)

    async def model(request):
        prompt = json.loads(request.messages[-1]["content"])
        response = (
            _plan_response(prompt) if "node" in prompt else _module_response(prompt)
        )
        return ModelTransportResponse(text=json.dumps(response), route={})

    with model_transport_scope(model):
        receipt = await EpisodeBuilder(store=store).build(request)
    return request, store, receipt


@pytest.mark.asyncio
async def test_approved_self_call_is_materialized_without_changing_the_concrete_tree(
    tmp_path,
):
    request, store, receipt = await build(tmp_path, (call(),))
    assert receipt.status == "materialized", [
        item.as_record() for item in receipt.deficits
    ]
    plan = store.read_plan(receipt.plan_id)
    attempt = store.read_build_attempt(receipt.build_attempt_id)
    plan.validate_against(request, attempt)
    assert plan.edges == ()
    assert plan.repeatable_calls[0].repeatable_call == call()
    assert plan.nodes[0].child_slot_names == (call().slot_name,)
    assert WorkflowMaterializationPlan.from_record(plan.as_record()) == plan
    report = store.read_admission_report(receipt.admission_report_id)
    assert report.admitted
    inert = claim_store(tmp_path / "inert-attestation")[1]
    manifest = store.read_manifest(receipt.manifest_id)
    registration = RunRegistration.from_admitted_build(
        build_request=request,
        build_attempt=attempt,
        build_receipt=receipt,
        build_manifest=manifest,
        runtime_identity=inert.runtime_identity,
        runtime_policy=inert.runtime_policy,
        launch_request=DuetLaunchRequest(
            oid("launch").value,
            request.frozen_workflow.artifact_id.value,
            oid("goal").value,
            {},
        ),
    )
    prepared = prepare_source_package(
        registration, store.source_package_path(manifest.manifest_id)
    )
    events = []

    async def event_sink(kind, episode_id, payload):
        events.append((kind, episode_id, payload))

    try:
        linked = prepared.activate().link(event_sink=event_sink)
        assert linked.context.tree.self_nesting == (plan.nodes[0].grain_name,)
        assert linked.context.tree.allowed_children(plan.nodes[0].grain_name) == (
            linked.root_episode.grain,
        )
        assert events == []  # Linking has not executed a child or awarded progress.
    finally:
        for module in prepared.modules.values():
            sys.modules.pop(module.module_name, None)

    # Strip both the call and its slot/function declarations, leaving an internally
    # consistent but unauthorized plan. Exact approval must still reject it.
    node = plan.nodes[0]
    bindings = tuple(
        binding
        for binding in node.selected_function_bindings
        if not (
            binding["role"].startswith("edge.nested_parts.")
            or binding["role"].startswith("component.repeatable_nested_parts_")
        )
    )
    stripped = replace(
        node,
        topology_role="leaf",
        child_slot_names=(),
        selected_function_bindings=bindings,
        function_definition_ids=tuple(
            sorted({
                binding["definition_id"]
                for binding in bindings
                if binding["source"] == "library"
            })
        ),
    )
    forged = replace(plan, nodes=(stripped,), repeatable_calls=())
    assert forged.plan_id != plan.plan_id
    with pytest.raises(ValueError, match="every frozen repeatable call"):
        forged.validate_against(request, attempt)

    changed = [
        dict(binding) for binding in node.as_record()["selected_function_bindings"]
    ]
    next(
        binding
        for binding in changed
        if binding["role"].endswith("authority_attenuation")
    )["arguments"] = {"invented_permission": True}
    forged = replace(
        plan, nodes=(replace(node, selected_function_bindings=tuple(changed)),)
    )
    with pytest.raises(ValueError, match="changes frozen repeatable call functions"):
        forged.validate_against(request, attempt)


@pytest.mark.asyncio
async def test_unresolved_repeatable_policy_blocks_build_without_emitting_a_partial_authority(
    tmp_path,
):
    missing = replace(call().invocation_admission, definition_id="function_" + "0" * 64)
    request, store, receipt = await build(
        tmp_path, (replace(call(), invocation_admission=missing),)
    )
    assert receipt.status == "blocked"
    assert any(item.code == "repeatable_call_invalid" for item in receipt.deficits)
    assert receipt.manifest_id is None
    plan = store.read_plan(receipt.plan_id)
    assert not plan.ready
    plan.validate_against(request, store.read_build_attempt(receipt.build_attempt_id))
