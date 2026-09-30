from types import SimpleNamespace

from agent.duet_contracts import (
    DuetIdentity,
    DuetPolicy,
)
from agent.duet_service import DuetService
from agent.duet_store import DuetStore
from agent.episode_contracts import OpaqueId
from agent.openchia_agents import bind_duet_agent
from run_agent import AIAgent


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
        )

    assert agent.valid_tool_names == set(policy.capability_allowlist)
    assert "web_search" in agent.valid_tool_names
    assert "episode_workflow_update" in agent.valid_tool_names
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
        "owns": "human_facing_design_of_the_episode_workflow",
        "may_design_descendant_task_tree": True,
        "may_launch_descendant_task_tree": False,
        "maximum_creator_depth": policy.maximum_creator_depth,
        "implicit_root_creator": False,
        "host_validates_freezes_and_launches_approved_workflow": True,
        "creator_contracts_apply_only_to_explicit_creator_nodes": True,
    }


def test_bound_duet_can_complete_a_basic_codex_model_turn(tmp_path, monkeypatch):
    identity = DuetIdentity(
        duet_id=OpaqueId.mint("duet", "model-turn"),
        human_authority_id=OpaqueId.mint("human", "model-turn"),
        policy_id=OpaqueId.mint("policy", "model-turn"),
        conversation_id=OpaqueId.mint("conversation", "model-turn"),
    )
    policy = DuetPolicy(policy_id=identity.policy_id)
    agent = AIAgent(
        model="gpt-5-codex",
        base_url="https://chatgpt.com/backend-api/codex",
        api_key="test-codex-token",
        quiet_mode=True,
        max_iterations=2,
        skip_context_files=True,
        skip_memory=True,
    )
    agent._disable_streaming = True
    agent._cleanup_task_resources = lambda _task_id: None
    agent._persist_session = lambda _messages, history=None: None
    agent._save_trajectory = lambda _messages, _user_message, _completed: None
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="message",
                content=[
                    SimpleNamespace(
                        type="output_text",
                        text="model connection works",
                    )
                ],
            )
        ],
        usage=SimpleNamespace(
            input_tokens=5,
            output_tokens=3,
            total_tokens=8,
        ),
        status="completed",
        model="gpt-5-codex",
    )
    monkeypatch.setattr(
        agent,
        "_interruptible_api_call",
        lambda _api_kwargs: response,
    )

    with DuetStore(tmp_path / "model-turn.sqlite3") as store:
        service = DuetService(store, allowed_episode_capabilities={"web_search"})
        service.open_duet(identity, policy)
        bind_duet_agent(
            agent,
            service=service,
            identity=identity,
            policy=policy,
        )
        result = agent.run_conversation("Reply briefly.")

    assert result["completed"] is True
    assert result["final_response"] == "model connection works"
