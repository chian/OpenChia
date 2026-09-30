"""Capability-exact agent factories for Duet, Creator, and task scopes."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Optional

from agent.creator_episode import CreatorRunLogStore, RunLogReference
from agent.duet_contracts import DuetIdentity, DuetPolicy
from agent.duet_service import DuetService
from agent.episode_contracts import EpisodeCreationSpec, OpaqueId
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


def _duet_authority_scope(
    agent: Any,
    *,
    service: DuetService,
    identity: DuetIdentity,
    policy: DuetPolicy,
) -> dict[str, Any]:
    """Materialize the host policy boundary exposed by ``openchia_scope``."""

    return {
        "schema_version": 1,
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
            "maximum_creator_depth": policy.maximum_creator_depth,
            "implicit_root_creator": False,
            "host_validates_freezes_and_launches_approved_workflow": True,
            "creator_contracts_apply_only_to_explicit_creator_nodes": True,
        },
        "allowed_operations": [
            "inspect_scope",
            "read_duet_status",
            "gather_read_only_information",
            "commit_creator_node_context_artifact",
            "read_context_artifact",
            "persist_complete_episode_workflow_revision",
            "submit_host_recorded_creator_boundary_decision",
        ],
        "prohibited_operations": [
            "execute_task_work",
            "launch_descendant_task_tree",
            "self_approve_or_mint_approval",
            "modify_contract_approval_evidence_or_credit_policy",
            "assign_capabilities_outside_host_ceiling",
        ],
    }


def _creator_authority_scope(
    agent: Any,
    *,
    creator_episode_id: Optional[OpaqueId],
    creation_spec: Optional[EpisodeCreationSpec],
    generic_spec: Optional[GenericCreatorInstanceSpec],
) -> dict[str, Any]:
    """Materialize one immutable Creator grant without deriving it from prose."""

    if creation_spec is not None and generic_spec is not None:
        raise ValueError("Creator authority must use one contract model")
    if creation_spec is not None:
        contract = creation_spec.creator_contract
        if contract is None:
            raise ValueError("Creator authority requires a Creator contract")
        authority_id = (
            None if creator_episode_id is None else creator_episode_id.value
        )
        assignable = contract.assignable_capability_names
        may_create_creators = contract.may_assign_creator_capability
        bounds = (
            None
            if creation_spec.safety_bounds is None
            else creation_spec.safety_bounds.as_record()
        )
        authority_hash = creation_spec.spec_hash.value
        authority_kind = "episode_creator_contract"
    elif generic_spec is not None:
        authority_id = generic_spec.instance_id
        assignable = generic_spec.assignable_capabilities
        may_create_creators = generic_spec.may_create_child_creators
        bounds = {
            "max_iterations": generic_spec.maximum_iterations,
            "max_child_episodes": generic_spec.maximum_child_episodes,
            "max_depth": generic_spec.maximum_depth,
            "max_elapsed_seconds": generic_spec.maximum_elapsed_time,
        }
        authority_hash = generic_spec.content_hash.value
        authority_kind = "generic_creator_instance"
    else:
        authority_id = (
            None if creator_episode_id is None else creator_episode_id.value
        )
        assignable = ()
        may_create_creators = False
        bounds = None
        authority_hash = None
        authority_kind = "unbound_creator_test_surface"
    callable_tools = set(agent._openchia_capability_allowlist)
    allowed_operations = [
        "inspect_scope",
        "read_owned_run_logs",
        "submit_complete_workflow_candidate",
    ]
    if "creator_context_read" in callable_tools:
        allowed_operations.append("read_required_exact_context")
    if "creator_context_artifact" in callable_tools:
        allowed_operations.append("commit_descendant_context_artifact")
    return {
        "schema_version": 1,
        "role": "creator",
        "authority_source": "immutable_host_admission",
        "authority_kind": authority_kind,
        "authority_id": authority_id,
        "authority_hash": authority_hash,
        "callable_tool_names": sorted(agent._openchia_capability_allowlist),
        "assignable_child_capability_names": sorted(assignable),
        "may_create_child_creators": may_create_creators,
        "safety_bounds": bounds,
        "tree_boundary": {
            "owns": "design_of_the_descendant_episode_work_graph",
            "may_submit_complete_workflow_blueprint": True,
            "may_directly_launch_descendants": False,
            "host_admits_and_launches_descendants": True,
            "child_authority_must_be_inherited": True,
        },
        "allowed_operations": allowed_operations,
        "prohibited_operations": [
            "change_parent_goal_success_criteria_or_approval",
            "change_evidence_acceptance_or_credit_weights",
            "self_approve_or_directly_launch_episode",
            "assign_capabilities_outside_inherited_grant",
            "read_sibling_branch_artifacts",
            "modify_active_host_or_control_plane",
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
    approval freezes the exact Duet-owned workflow and lets the host execute it
    directly. Creator agents exist only for Creator nodes declared in that workflow.
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


def build_creator_agent(
    *,
    capability_names: Iterable[str],
    log_store: CreatorRunLogStore,
    log_references: Iterable[RunLogReference] = (),
    workflow_draft_recorder: Optional[
        Callable[[dict[str, Any], str], dict[str, Any]]
    ] = None,
    execution_boundary: Any = None,
    context_service: Any = None,
    creator_episode_id: Optional[OpaqueId] = None,
    context_artifacts: Optional[Mapping[str, Mapping[str, Any]]] = None,
    creation_spec: Optional[EpisodeCreationSpec] = None,
    generic_spec: Optional[GenericCreatorInstanceSpec] = None,
    **agent_kwargs: Any,
) -> Any:
    """Construct one design specialist with scoped access to its own run logs."""

    from run_agent import AIAgent

    agent: Any = AIAgent(
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
    protocol_tools = {
        "openchia_scope",
        "creator_log_read",
        "workflow_candidate",
    }
    if context_service is not None and creator_episode_id is not None:
        protocol_tools.add("creator_context_artifact")
    if context_artifacts is not None:
        protocol_tools.add("creator_context_read")
    _install_exact_tools(agent, {*capability_names, *protocol_tools})
    agent._openchia_role = "creator"
    agent._openchia_authority_scope = _creator_authority_scope(
        agent,
        creator_episode_id=creator_episode_id,
        creation_spec=creation_spec,
        generic_spec=generic_spec,
    )
    agent._creator_episode_prompt_isolated = True
    agent._creator_log_store = log_store
    agent._creator_log_references = {
        item.artifact_id.value: item for item in log_references
    }
    if workflow_draft_recorder is not None and not callable(workflow_draft_recorder):
        raise TypeError("workflow_draft_recorder must be callable")
    agent._creator_workflow_draft_recorder = workflow_draft_recorder
    agent._creator_context_service = context_service
    agent._creator_episode_id = creator_episode_id
    agent._creator_context_artifacts = {
        key: dict(value) for key, value in (context_artifacts or {}).items()
    }
    agent._creator_required_context_ids = frozenset(
        artifact_id
        for artifact_id, artifact in agent._creator_context_artifacts.items()
        if artifact["reference"]["required"]
    )
    agent._creator_context_read_ids = set()
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
    workflow_draft_recorder: Optional[
        Callable[[dict[str, Any], str], dict[str, Any]]
    ] = None,
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
        workflow_draft_recorder=workflow_draft_recorder,
        execution_boundary=boundary,
        generic_spec=spec,
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
    "build_duet_agent",
    "build_task_episode_agent",
]
