from types import SimpleNamespace

from agent.duet_contracts import (
    CreatorLaunchReceipt,
    CreatorLaunchState,
    DuetIdentity,
    DuetPolicy,
)
from agent.duet_service import DuetService
from agent.duet_store import DuetStore
from agent.episode_contracts import OpaqueId
from agent.openchia_agents import bind_duet_agent


def test_duet_agent_surface_is_exact_and_search_cannot_expand_it(tmp_path):
    identity = DuetIdentity(
        duet_id=OpaqueId.mint("duet", "capabilities"),
        human_authority_id=OpaqueId.mint("human", "capabilities"),
        policy_id=OpaqueId.mint("policy", "capabilities"),
        conversation_id=OpaqueId.mint("conversation", "capabilities"),
    )
    policy = DuetPolicy(policy_id=identity.policy_id)
    with DuetStore(tmp_path / "duet.sqlite3") as store:
        service = DuetService(store, allowed_episode_capabilities={"web_search"})
        service.open_duet(identity, policy)
        agent = SimpleNamespace(
            tools=[],
            valid_tool_names=set(),
            enabled_toolsets=None,
            disabled_toolsets=None,
            skip_context_files=False,
            load_soul_identity=True,
            skip_background_review=False,
            _memory_store=object(),
            _memory_manager=object(),
        )
        bind_duet_agent(
            agent,
            service=service,
            identity=identity,
            policy=policy,
            creator_launcher=lambda creator_id: CreatorLaunchReceipt(
                creator_episode_id=creator_id,
                execution_id=OpaqueId.mint("execution", creator_id.value),
                state=CreatorLaunchState.LAUNCHED,
            ),
        )

    assert agent.valid_tool_names == set(policy.capability_allowlist)
    assert "web_search" in agent.valid_tool_names
    assert "episode_creator" in agent.valid_tool_names
    assert "openchia_scope" in agent.valid_tool_names
    assert "tool_search" not in agent.valid_tool_names
    assert "terminal" not in agent.valid_tool_names
    assert "write_file" not in agent.valid_tool_names
    assert "patch" not in agent.valid_tool_names
    assert "execute_code" not in agent.valid_tool_names
    assert "delegate_task" not in agent.valid_tool_names
    assert agent._tool_search_catalog == {}
    assert agent._deferred_tool_names == frozenset()
    assert agent._openchia_authority_scope["role"] == "duet"
    assert agent._openchia_authority_scope["callable_tool_names"] == sorted(
        policy.capability_allowlist
    )
    assert agent._openchia_authority_scope[
        "assignable_child_capability_names"
    ] == ["web_search"]
    assert agent._openchia_authority_scope["tree_boundary"] == {
        "owns": "commission_and_admission_of_exactly_one_root_creator",
        "may_design_or_launch_descendant_task_tree": False,
        "maximum_creator_depth": policy.maximum_creator_depth,
        "creator_builds_descendant_work_graph": True,
        "host_admits_and_launches_descendants": True,
    }
