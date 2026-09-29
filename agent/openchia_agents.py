"""Capability-exact agent factories for Duet, Creator, and task scopes."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

from agent.creator_episode import CreatorRunLogStore, RunLogReference
from agent.duet_contracts import CreatorLaunchReceipt, DuetIdentity, DuetPolicy
from agent.duet_service import DuetService
from agent.episode_contracts import OpaqueId
from agent.generic_creator_models import GenericCreatorInstanceSpec
from agent.generic_creator_runtime import IsolatedExecutorAttestation
from agent.openchia_execution_boundary import OpenChiaExecutionBoundary


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


def bind_duet_agent(
    agent: Any,
    *,
    service: DuetService,
    identity: DuetIdentity,
    policy: DuetPolicy,
    creator_launcher: Callable[[OpaqueId], CreatorLaunchReceipt],
) -> Any:
    """Turn an initialized AIAgent into the restricted LLM half of one Duet.

    ``creator_launcher`` is keyed by the admitted Creator ID and must be
    idempotent: an exact tool-call retry must return the same execution claim,
    never start a duplicate design loop.
    """

    if identity.policy_id != policy.policy_id:
        raise ValueError("Duet identity and policy IDs differ")
    if not callable(creator_launcher):
        raise TypeError("Duet binding requires a task-specific Creator launcher")
    _install_exact_tools(agent, policy.capability_allowlist)
    agent._openchia_role = "duet"
    agent._duet_prompt_isolated = True
    agent._duet_service = service
    agent._duet_identity = identity
    agent._duet_creator_launcher = creator_launcher
    agent._duet_creator_receipts = {}
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
    creator_launcher: Callable[[OpaqueId], CreatorLaunchReceipt],
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
        creator_launcher=creator_launcher,
    )


def build_duet_contract_critic_agent(**agent_kwargs: Any) -> Any:
    """Construct a stateless, tool-free semantic reviewer for one Duet draft."""

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
    agent._openchia_role = "duet_contract_critic"
    agent._duet_contract_critic_prompt_isolated = True
    agent._persist_disabled = True
    agent._end_session_on_close = False
    return agent


def build_creator_agent(
    *,
    capability_names: Iterable[str],
    log_store: CreatorRunLogStore,
    log_references: Iterable[RunLogReference] = (),
    workflow_reviewer: Optional[Callable[[dict[str, Any], tuple[str, ...]], dict[str, Any]]] = None,
    execution_boundary: Any = None,
    **agent_kwargs: Any,
) -> Any:
    """Construct one design specialist with scoped access to its own run logs."""

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
    _install_exact_tools(
        agent,
        {*capability_names, "creator_log_read", "workflow_review", "workflow_candidate"},
    )
    agent._openchia_role = "creator"
    agent._creator_episode_prompt_isolated = True
    agent._creator_log_store = log_store
    agent._creator_log_references = {
        item.artifact_id.value: item for item in log_references
    }
    if workflow_reviewer is not None and not callable(workflow_reviewer):
        raise TypeError("workflow_reviewer must be callable")
    agent._creator_workflow_reviewer = workflow_reviewer
    agent._creator_reviewed_workflow_hashes = set()
    if execution_boundary is not None:
        agent._openchia_execution_boundary = execution_boundary
    agent._persist_disabled = True
    agent._end_session_on_close = False
    return agent


def build_creator_workflow_critic_agent(**agent_kwargs: Any) -> Any:
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
    agent._openchia_role = "creator_workflow_critic"
    agent._creator_workflow_critic_prompt_isolated = True
    agent._persist_disabled = True
    agent._end_session_on_close = False
    return agent


def build_generic_creator_agent(
    *,
    spec: GenericCreatorInstanceSpec,
    creator_capability_names: Iterable[str] = (),
    workspace_roots: Iterable[str],
    protected_roots: Iterable[str],
    isolated_executor: Optional[IsolatedExecutorAttestation],
    execution_boundary: Optional[OpenChiaExecutionBoundary] = None,
    owned_process_sessions: Iterable[str] = (),
    log_store: CreatorRunLogStore,
    log_references: Iterable[RunLogReference] = (),
    workflow_reviewer: Optional[Callable[[dict[str, Any], tuple[str, ...]], dict[str, Any]]] = None,
    **agent_kwargs: Any,
) -> Any:
    """Construct a generic Creator with a mandatory mechanical boundary."""

    from pathlib import Path

    creator_capabilities = frozenset(creator_capability_names)
    if not creator_capabilities.issubset(spec.assignable_capabilities):
        raise ValueError("generic Creator capabilities must be a subset of its assignable grant")
    if creator_capabilities & {
        "write_file", "patch", "terminal", "execute_code", "process_manage"
    }:
        raise ValueError(
            "generic Creator control loops cannot directly exercise effectful task capabilities"
        )
    boundary = execution_boundary or OpenChiaExecutionBoundary(
        workspace_roots=tuple(Path(item) for item in workspace_roots),
        protected_roots=tuple(Path(item) for item in protected_roots),
        isolated_executor=isolated_executor,
        owned_process_sessions=frozenset(owned_process_sessions),
    )
    return build_creator_agent(
        capability_names=creator_capabilities,
        log_store=log_store,
        log_references=log_references,
        workflow_reviewer=workflow_reviewer,
        execution_boundary=boundary,
        **agent_kwargs,
    )


def build_generic_task_episode_agent(
    *,
    parent_spec: GenericCreatorInstanceSpec,
    capability_names: Iterable[str],
    episode_id: str,
    accepted_evidence_ids: Iterable[str],
    workspace_roots: Iterable[str],
    protected_roots: Iterable[str],
    isolated_executor: Optional[IsolatedExecutorAttestation],
    execution_boundary: Optional[OpenChiaExecutionBoundary] = None,
    owned_process_sessions: Iterable[str] = (),
    **agent_kwargs: Any,
) -> Any:
    """Build a generic Creator's task Episode with inherited authority."""

    from pathlib import Path

    capabilities = frozenset(capability_names)
    if not capabilities.issubset(parent_spec.assignable_capabilities):
        raise ValueError("task Episode capabilities must be inherited from its Creator")
    effectful = capabilities & {
        "write_file", "patch", "terminal", "execute_code", "process_manage"
    }
    effective_attestation = (
        execution_boundary.isolated_executor
        if execution_boundary is not None
        else isolated_executor
    )
    if effectful and (
        effective_attestation is None or not effective_attestation.permits_effectful_recursion
    ):
        raise ValueError("effectful task Episodes require an attested isolated executor")
    boundary = execution_boundary or OpenChiaExecutionBoundary(
        workspace_roots=tuple(Path(item) for item in workspace_roots),
        protected_roots=tuple(Path(item) for item in protected_roots),
        isolated_executor=isolated_executor,
        owned_process_sessions=frozenset(owned_process_sessions),
    )
    return build_task_episode_agent(
        capability_names=capabilities,
        episode_id=episode_id,
        accepted_evidence_ids=accepted_evidence_ids,
        execution_boundary=boundary,
        **agent_kwargs,
    )


def build_task_episode_agent(
    *,
    capability_names: Iterable[str],
    episode_id: str,
    accepted_evidence_ids: Iterable[str],
    execution_boundary: Any = None,
    **agent_kwargs: Any,
) -> Any:
    """Construct one fixed-contract executor; it has no creation authority."""

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
    _install_exact_tools(agent, {*capability_names, "episode_progress"})
    agent._openchia_role = "task_episode"
    agent._task_episode_prompt_isolated = True
    agent._active_episode_id = episode_id
    agent._active_episode_evidence_ids = frozenset(accepted_evidence_ids)
    agent._episode_progress_reports = []
    if execution_boundary is not None:
        agent._openchia_execution_boundary = execution_boundary
    agent._persist_disabled = True
    agent._end_session_on_close = False
    return agent


__all__ = [
    "bind_duet_agent",
    "build_creator_agent",
    "build_generic_creator_agent",
    "build_generic_task_episode_agent",
    "build_creator_workflow_critic_agent",
    "build_duet_contract_critic_agent",
    "build_duet_agent",
    "build_task_episode_agent",
]
