"""Capability-exact agent factories for Duet and design review scopes."""

from __future__ import annotations

from typing import Any, Iterable, Optional

from agent.duet_contracts import DuetIdentity, DuetPolicy
from agent.duet_service import DuetService


def _tool_name(tool: object) -> Optional[str]:
    if not isinstance(tool, dict):
        return None
    function = tool.get("function")
    if not isinstance(function, dict):
        return None
    name = function.get("name")
    return name if isinstance(name, str) and name else None


def _install_exact_tools(agent: Any, names: Iterable[str]) -> None:
    """Replace every advertised/deferred tool surface with one closed allowlist."""

    allowed = frozenset(names)
    import model_tools

    catalog = model_tools.get_tool_definitions(
        quiet_mode=True,
        skip_tool_search_assembly=True,
    )
    by_name = {
        name: tool
        for tool in catalog
        if (name := _tool_name(tool)) is not None
    }
    missing = sorted(allowed - set(by_name))
    if missing:
        raise RuntimeError(f"required OpenChia tools are unavailable: {missing}")
    agent.tools = [by_name[name] for name in sorted(allowed)]
    agent.valid_tool_names = set(allowed)
    agent.enabled_toolsets = []
    agent.disabled_toolsets = []
    agent._tool_snapshot_generation = 2_147_483_647
    # Deferred discovery/call bridges must not retain a pre-filter catalog.
    agent._deferred_tool_names = frozenset()
    agent._tool_search_catalog = {}
    agent._openchia_capability_allowlist = allowed


def _duet_authority_scope(
    agent: Any,
    *,
    service: DuetService,
    identity: DuetIdentity,
    policy: DuetPolicy,
) -> dict[str, Any]:
    """Materialize the host policy boundary exposed by ``openchia_scope``."""

    return {
        "role": "duet",
        "authority_source": "host_policy",
        "authority_ids": {
            "duet_id": identity.duet_id.value,
            "policy_id": policy.policy_id.value,
        },
        "callable_tool_names": sorted(agent._openchia_capability_allowlist),
        "assignable_child_capability_names": sorted(
            service.allowed_episode_capabilities
        ),
        "tree_boundary": {
            "owns": "human_facing_design_of_the_episode_workflow",
            "may_design_descendant_task_tree": True,
            "may_launch_descendant_task_tree": False,
            "host_validates_and_freezes_approved_workflow": True,
            "episode_builder_materializes_before_launch": True,
        },
        "allowed_operations": [
            "inspect_scope",
            "read_duet_status",
            "gather_read_only_information",
            "persist_complete_episode_workflow_revision",
        ],
        "prohibited_operations": [
            "execute_task_work",
            "launch_descendant_task_tree",
            "self_approve_or_mint_approval",
            "modify_contract_approval_evidence_or_credit_policy",
            "assign_capabilities_outside_host_ceiling",
        ],
    }


def bind_duet_agent(
    agent: Any,
    *,
    service: DuetService,
    identity: DuetIdentity,
    policy: DuetPolicy,
) -> Any:
    """Turn an initialized AIAgent into the restricted LLM half of one Duet.

    Workflow launch is deliberately absent from the model tool surface. Human
    approval freezes the exact Duet-owned design; EpisodeBuilder must then
    materialize explicit task-specific Episode modules before launch.
    """

    if identity.policy_id != policy.policy_id:
        raise ValueError("Duet identity and policy IDs differ")
    _install_exact_tools(agent, policy.capability_allowlist)
    agent._openchia_role = "duet"
    agent._openchia_authority_scope = _duet_authority_scope(
        agent,
        service=service,
        identity=identity,
        policy=policy,
    )
    agent._duet_prompt_isolated = True
    agent._duet_service = service
    agent._duet_identity = identity
    agent.skip_context_files = True
    agent.load_soul_identity = False
    agent.skip_background_review = True
    agent._memory_store = None
    agent._memory_manager = None
    return agent


def build_duet_agent(
    *,
    service: DuetService,
    identity: DuetIdentity,
    policy: DuetPolicy,
    **agent_kwargs: Any,
) -> Any:
    """Construct the conversational LLM with search plus Duet protocol only."""

    from run_agent import AIAgent

    kwargs = {
        **agent_kwargs,
        "enabled_toolsets": [],
        "disabled_toolsets": [],
        "skip_context_files": True,
        "load_soul_identity": False,
        "skip_memory": True,
        "skip_background_review": True,
    }
    return bind_duet_agent(
        AIAgent(**kwargs),
        service=service,
        identity=identity,
        policy=policy,
    )


def build_workflow_critic_agent(**agent_kwargs: Any) -> Any:
    """Construct one stateless, tool-free workflow review lens."""

    from run_agent import AIAgent

    agent = AIAgent(
        **{
            **agent_kwargs,
            "enabled_toolsets": [],
            "disabled_toolsets": [],
            "skip_context_files": True,
            "load_soul_identity": False,
            "skip_memory": True,
            "skip_background_review": True,
        }
    )
    _install_exact_tools(agent, ())
    agent._openchia_role = "workflow_critic"
    agent._workflow_critic_prompt_isolated = True
    agent._persist_disabled = True
    agent._end_session_on_close = False
    return agent


__all__ = [
    "bind_duet_agent",
    "build_workflow_critic_agent",
    "build_duet_agent",
]
