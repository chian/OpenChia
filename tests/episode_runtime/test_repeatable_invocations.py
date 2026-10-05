"""Method-loop call-boundary invariants, not a confined refiner acceptance run.

The exact functions below are deterministic test policies. Refiner host admission
and actual worker transport still need their own integration evidence.
"""

from dataclasses import replace
from types import MappingProxyType

import pytest

from agent.duet_contracts import content_id
from agent.episode_call_contracts import EpisodeRepeatableCallSpec
from agent.episode_contracts import EpisodeFunctionSelectionSpec
from episode_builder._contract_plan import EdgeMaterializationPlan
from episode_runtime.repeatable import admitted_builder
from function_library import FunctionImplementation, LibraryFunction
from function_library.reasoning import HostReceiptController
from handoff_library import DuetLaunchRequest, HandoffPayloadContract, ParentRequest
from method_loop import (
    Context,
    Episode,
    EpisodeGoal,
    EpisodeRequest,
    EpisodeTree,
    Grain,
    leaves,
)
from method_loop.identities import EpisodeRef


def schema(*, request, parent_request, invocation):
    assert isinstance(request.message, ParentRequest)
    return request


def attenuation(*, request, parent_request, invocation):
    return set(request.message.artifact_ids_by_role["slices"]) < set(
        parent_request.message.artifact_ids_by_role["slices"]
    )


def admission(*, request, parent_request, invocation):
    return invocation["slot_name"] == "nested_parts" and attenuation(
        request=request, parent_request=parent_request, invocation=invocation
    )


def policy(name):
    return LibraryFunction(
        library="test.calls",
        function_id=name,
        interface="test.call_policy",
        description="A deterministic unit-test scope predicate.",
        implementation=FunctionImplementation(
            module=__name__, symbol=name, is_async=False
        ),
        input_type="Typed child and parent requests plus runtime-owned invocation address",
        output_type="Typed request or exact admission boolean",
        effect="Pure validation.",
        failure_contract="Reject a non-subset scope.",
        provenance={"test_only": True},
    )


def selected(function):
    return EpisodeFunctionSelectionSpec(
        function.library,
        function.function_id,
        function.interface,
        function.definition_id,
        {},
    )


@pytest.mark.asyncio
async def test_child_construction_requires_current_parent_exact_address_and_all_policies():
    run_id = content_id("run", "call-test").value
    slice_a, slice_b = (content_id("slice", name).value for name in ("a", "b"))
    policies = tuple(policy(name) for name in ("schema", "attenuation", "admission"))
    contract = EpisodeRepeatableCallSpec(
        "parts",
        "nested_parts",
        "parts",
        selected(policies[0]),
        selected(policies[0]),
        selected(policies[0]),
        selected(policies[2]),
        selected(policies[1]),
    )
    payload = HandoffPayloadContract(
        artifact_roles=("slices",), required_artifact_roles=("slices",)
    )
    edge = EdgeMaterializationPlan(
        "parts",
        "parts",
        "nested_parts",
        "test.parts",
        "prepare",
        "receive",
        "build",
        payload.as_record(),
        payload.as_record(),
        {"basis": "unit test"},
        contract,
    )
    grain = Grain(
        "parts",
        "one refinement unit",
        "typed result",
        lambda _: HostReceiptController(),
    )
    context = Context(
        tree=EpisodeTree(
            root=grain, children={grain: (grain,)}, self_nesting=("parts",)
        ),
        run_id=run_id,
    )
    parent_goal = EpisodeGoal.root(objective="Refine slices", result_contract={})
    parent_request = EpisodeRequest(
        parent_goal,
        DuetLaunchRequest(
            content_id("request", "root").value,
            content_id("workflow", "test").value,
            parent_goal.goal_id,
            {"slices": (slice_a, slice_b)},
        ),
    )
    parent_path = context.enter(grain, "root")
    constructed = []

    def construct(key, request, goal_view, collaborators):
        episode = Episode(
            grain=grain,
            key=key,
            request=request,
            source=leaves((), lambda value: value, lambda unit, value: value),
            build_result=lambda record: request.message,
        )
        constructed.append(episode)
        return episode

    builder = admitted_builder(
        edge=edge,
        parent_path=parent_path,
        parent_request=parent_request,
        run_id=run_id,
        child_grain=grain,
        definitions=policies,
        current_path=lambda: context.path,
        construct=construct,
    )

    def child_request(key, scope):
        goal = EpisodeGoal.child(
            parent_goal, objective="Refine selected slices", result_contract={}
        )
        return EpisodeRequest(
            goal,
            ParentRequest(
                request_id=content_id("request", key).value,
                parent_episode_id=EpisodeRef(run_id, parent_path).episode_id,
                child_episode_id=EpisodeRef(
                    run_id, (*parent_path, (grain.name, key))
                ).episode_id,
                goal_id=goal.goal_id,
                child_interface="test.parts",
                artifact_ids_by_role={"slices": scope},
            ),
        )

    valid = child_request("first", (slice_a,))
    child = await builder("first", valid, MappingProxyType({}), {})
    assert child.request == valid and child.key == "first"
    with pytest.raises(ValueError, match="authority attenuation"):
        await builder(
            "wide", child_request("wide", (slice_a, slice_b)), MappingProxyType({}), {}
        )
    with pytest.raises(ValueError, match="does not match its invocation"):
        await builder("wrong_key", valid, MappingProxyType({}), {})
    with pytest.raises(ValueError, match="parent goal"):
        await builder(
            "first", replace(valid, goal=parent_goal), MappingProxyType({}), {}
        )
    context.leave(parent_path)
    with pytest.raises(ValueError, match="owning invocation"):
        await builder("first", valid, MappingProxyType({}), {})
    assert constructed == [child]
