"""Agent-level ("inline") tool executors shared by the sequential and concurrent tool paths.

These tools need live ``AIAgent`` state (stores, callbacks, session DB) and therefore
bypass the tool registry. Each executor is ``fn(agent, args, ctx) -> result``; the
table replaces two hand-maintained if/elif chains (``invoke_tool`` and
``execute_tool_calls_sequential``) that had drifted apart. Tool modules are imported
lazily at call time so ``patch("tools.x.y")`` in tests keeps working.
"""

from __future__ import annotations

from contextlib import nullcontext
import json
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable, Dict, Optional, Tuple


def tool_hook_ids(agent, effective_task_id: str, tool_call_id: Optional[str]) -> Dict[str, str]:
    """Identity kwargs every tool hook/middleware call carries (all coerced to ``""``)."""
    return {
        "task_id": effective_task_id or "",
        "session_id": getattr(agent, "session_id", "") or "",
        "tool_call_id": tool_call_id or "",
        "turn_id": getattr(agent, "_current_turn_id", "") or "",
        "api_request_id": getattr(agent, "_current_api_request_id", "") or "",
    }


def emit_terminal_post_tool_call(
    agent,
    *,
    function_name: str,
    function_args: dict,
    result: Any,
    effective_task_id: str,
    tool_call_id: Optional[str],
    duration_ms: int = 0,
    status: Optional[str] = None,
    error_type: Optional[str] = None,
    error_message: Optional[str] = None,
    middleware_trace: Optional[list] = None,
) -> None:
    """Emit the one terminal ``post_tool_call`` hook for a tool_call_id (best-effort)."""
    try:
        from model_tools import _emit_post_tool_call_hook
        _emit_post_tool_call_hook(
            function_name=function_name,
            function_args=function_args,
            result=result,
            **tool_hook_ids(agent, effective_task_id, tool_call_id),
            duration_ms=duration_ms,
            status=status,
            error_type=error_type,
            error_message=error_message,
            middleware_trace=list(middleware_trace or []),
        )
    except Exception:
        pass


def apply_transform_tool_result(
    agent,
    *,
    function_name: str,
    function_args: dict,
    result: Any,
    effective_task_id: str,
    tool_call_id: Optional[str],
    duration_ms: int = 0,
) -> Any:
    """Apply ``transform_tool_result`` to an inline-dispatched tool's result.

    Registry tools get this inside ``handle_function_call``; inline executors never
    reach it, so the agent paths call the same helper (after the terminal
    ``post_tool_call``) to keep the hook's "every tool" contract. Fail-open."""
    try:
        from model_tools import _CallIds, _apply_transform_tool_result_hook
        return _apply_transform_tool_result_hook(
            function_name, function_args, result, duration_ms,
            _CallIds(**tool_hook_ids(agent, effective_task_id, tool_call_id)),
        )
    except Exception:
        return result


@dataclass
class InlineToolContext:
    """Per-call state an inline executor may need beyond its arguments."""

    effective_task_id: str
    tool_call_id: Optional[str] = None
    messages: Optional[list] = None


InlineToolExecutor = Callable[[Any, dict, InlineToolContext], Any]

# ``(kwarg, args_key)`` → ``args.get(key)``; ``(kwarg, args_key, default)`` → ``args.get(key, default)``.
_ArgSpec = Tuple[Any, ...]


def _call_tool(module: str, func: str, args: dict, arg_specs: Tuple[_ArgSpec, ...], **fixed: Any) -> Any:
    """Import ``module.func`` lazily and call it with args mapped per ``arg_specs`` plus ``fixed``."""
    fn = getattr(import_module(module), func)
    return fn(**{spec[0]: args.get(*spec[1:]) for spec in arg_specs}, **fixed)


def _tool(
    module: str, func: str, *arg_specs: _ArgSpec, **fixed: Callable[[Any, InlineToolContext], Any],
) -> InlineToolExecutor:
    """Executor calling ``module.func`` with mapped args plus ``fixed`` kwargs computed from ``(agent, ctx)``."""
    def _exec(agent, args: dict, ctx: InlineToolContext) -> Any:
        return _call_tool(module, func, args, arg_specs, **{k: f(agent, ctx) for k, f in fixed.items()})
    return _exec


def _callback_tool(module: str, func: str, callback_attr: str, *arg_specs: _ArgSpec) -> InlineToolExecutor:
    """Executor for a GUI-callback tool: mapped args plus ``callback=getattr(agent, callback_attr, None)``."""
    return _tool(module, func, *arg_specs, callback=lambda agent, ctx: getattr(agent, callback_attr, None))


def _session_search(agent, args: dict, ctx: InlineToolContext) -> Any:
    session_db = agent._get_session_db_for_recall()
    if not session_db:
        from hermes_state import format_session_db_unavailable

        return json.dumps({"success": False, "error": format_session_db_unavailable()})
    return _call_tool(
        "tools.session_search_tool", "session_search", args,
        (
            ("query", "query", ""), ("role_filter", "role_filter"), ("limit", "limit", 3),
            ("session_id", "session_id"), ("around_message_id", "around_message_id"),
            ("window", "window", 5), ("sort", "sort"), ("profile", "profile"),
            ("detail", "detail", "adaptive"), ("after", "after"), ("before", "before"),
            ("exclude_session_ids", "exclude_session_ids"),
        ),
        db=session_db, current_session_id=agent.session_id,
    )


def _memory(agent, args: dict, ctx: InlineToolContext) -> Any:
    result = _call_tool(
        "tools.memory_tool", "memory_tool", args,
        (
            ("action", "action"), ("target", "target", "memory"), ("content", "content"),
            ("old_text", "old_text"), ("new_text", "new_text"), ("operations", "operations"),
        ),
        store=agent._memory_store,
    )
    # Mirror built-in memory writes to external providers; gating lives in
    # MemoryManager.notify_memory_tool_write.
    if agent._memory_manager:
        agent._memory_manager.notify_memory_tool_write(
            result,
            args,
            build_metadata=lambda: agent._build_memory_write_metadata(
                task_id=ctx.effective_task_id,
                tool_call_id=ctx.tool_call_id,
            ),
        )
    return result


_read_preview = _callback_tool(
    "tools.read_preview_tool", "read_preview_tool", "read_preview_callback",
    ("start", "start"), ("count", "count"),
)


def _desktop_preview(agent, args: dict, ctx: InlineToolContext) -> Any:
    # action=read needs the GUI callback (agent-level); open/close go through the
    # registry handler like any other tool.
    if (args.get("action") or "").strip() == "read":
        return _read_preview(agent, args, ctx)
    from tools.preview_tool import _handle_preview

    return _handle_preview(args)


def _manage_connections(agent, args: dict, ctx: InlineToolContext) -> Any:
    # The GUI callback lives on the agent; registry dispatch never forwards it.
    from tools.connectors import manage_connections
    from tools.connectors.gateway import config as gateway_config

    result = manage_connections(
        args, session_id=getattr(agent, "session_id", None), tool_call_id=ctx.tool_call_id,
        connection_callback=getattr(agent, "connection_callback", None),
        connectors_available=gateway_config.connectors_available,
    )
    _scope_in_connected_mcp_servers(agent, result)
    return result


def _scope_in_connected_mcp_servers(agent, result: Any) -> None:
    """Add the MCP servers this call connected to the agent's toolset selection.

    ``tool_describe``/``tool_call`` resolve names inside that selection, and it was fixed when the
    agent was built, so a server registered a moment ago is otherwise "not found" for the rest of
    the turn the result calls it available in. Only the selection changes; ``agent.tools`` does
    not, so the sent tool schema bytes stay the same."""
    enabled = getattr(agent, "enabled_toolsets", None)
    if enabled is None or "no_mcp" in enabled:  # None already means every toolset
        return
    try:
        targets = json.loads(result).get("targets") or []
    except (AttributeError, TypeError, ValueError):
        return
    connected = [str(t.get("name")) for t in targets if isinstance(t, dict)
                 and t.get("kind") == "mcp" and t.get("state") == "connected" and t.get("tools")]
    added = [name for name in connected if name not in enabled]
    if added:
        agent.enabled_toolsets = [*enabled, *added]


def _manage_catalog(agent, args: dict, ctx: InlineToolContext) -> Any:
    # The card callback lives on the agent; only a desktop chat draws catalog rows.
    from tools.connectors.catalog_tool import manage_catalog

    return manage_catalog(
        args, session_id=getattr(agent, "session_id", None), tool_call_id=ctx.tool_call_id,
        connection_callback=getattr(agent, "connection_callback", None),
        card_surface=getattr(agent, "platform", None) == "desktop",
    )


def _setup_mcp_shim(agent, args: dict, ctx: InlineToolContext) -> Any:
    # Replay shim for conversations whose cached prompt still names setup_mcp.
    # Not in _LEGACY_TOOL_ALIASES: inline tools bypass handle_function_call.
    return _manage_connections(agent, {
        "action": args.get("action", "install"),
        "connectors": [{"name": args.get("server", ""), "mcp": True}],
    }, ctx)


def _episode_progress(agent, args: dict, ctx: InlineToolContext) -> Any:
    """Register accepted evidence identities; the model never supplies a score."""
    if not isinstance(getattr(agent, "_active_episode_id", None), str):
        return json.dumps({"accepted": False, "reason": "no_active_episode"})
    evidence_ids = args.get("accepted_evidence_ids")
    if (
        not isinstance(evidence_ids, list)
        or not evidence_ids
        or any(not isinstance(item, str) or not item for item in evidence_ids)
        or len(set(evidence_ids)) != len(evidence_ids)
    ):
        return json.dumps(
            {"accepted": False, "reason": "invalid_evidence_ids"},
            sort_keys=True,
        )
    registered = getattr(agent, "_active_episode_evidence_ids", frozenset())
    if not isinstance(registered, (set, frozenset)):
        registered = frozenset()
    unknown = sorted(set(evidence_ids) - set(registered))
    if unknown:
        return json.dumps(
            {
                "accepted": False,
                "reason": "unregistered_evidence",
                "unknown_count": len(unknown),
            },
            sort_keys=True,
        )
    reports = getattr(agent, "_episode_progress_reports", None)
    if not isinstance(reports, list):
        reports = []
        agent._episode_progress_reports = reports
    prior = {item for report in reports for item in report}
    newly_accepted = tuple(item for item in evidence_ids if item not in prior)
    reports.append(newly_accepted)
    return json.dumps(
        {
            "accepted": True,
            "accepted_count": len(newly_accepted),
            "total_distinct_count": len(prior | set(newly_accepted)),
        },
        sort_keys=True,
    )


def _duet_context(agent):
    service = getattr(agent, "_duet_service", None)
    identity = getattr(agent, "_duet_identity", None)
    if service is None or identity is None:
        raise RuntimeError("no active host-bound Duet")
    return service, identity


def _duet_draft_write(agent):
    lock = getattr(agent, "_openchia_draft_write_lock", None)
    return lock if lock is not None else nullcontext()


def _openchia_scope(agent, args: dict, ctx: InlineToolContext) -> Any:
    """Return the immutable host-authored role boundary, never model prose."""

    scope = getattr(agent, "_openchia_authority_scope", None)
    if not isinstance(scope, dict):
        return json.dumps(
            {"accepted": False, "reason": "no_host_bound_openchia_scope"},
            sort_keys=True,
        )
    # Serialize through JSON so callers cannot receive or mutate the host's live dict.
    return json.dumps(
        {"accepted": True, "scope": scope},
        ensure_ascii=False,
        sort_keys=True,
    )


def _duet_contract_patch(agent, args: dict, ctx: InlineToolContext) -> Any:
    from agent.duet_contracts import (
        ContractFieldRecord,
        DuetProvenance,
        FieldImpact,
    )

    try:
        service, identity = _duet_context(agent)
        raw_patches = args.get("patches")
        if not isinstance(raw_patches, list) or not raw_patches:
            raise ValueError("patches must be a non-empty array")
        patches = tuple(
            ContractFieldRecord(
                field_path=item["field_path"],
                value=item["value"],
                provenance=DuetProvenance.LLM_PROPOSAL,
                impact=FieldImpact(item["impact"]),
            )
            for item in raw_patches
            if isinstance(item, dict)
        )
        if len(patches) != len(raw_patches):
            raise ValueError("every patch must be an object")
        with _duet_draft_write(agent):
            draft = service.patch_contract(
                identity.duet_id,
                expected_revision=args.get("expected_revision"),
                patches=patches,
                actor=DuetProvenance.LLM_PROPOSAL,
            )
        return json.dumps(
            {
                "draft_id": draft.draft_id.value,
                "revision": draft.revision,
                "ready": draft.ready,
                "content_hash": draft.content_hash.value,
                "deficits": [item.as_record() for item in draft.deficits],
            },
            sort_keys=True,
        )
    except Exception as exc:
        return json.dumps(
            {"accepted": False, "reason": type(exc).__name__}, sort_keys=True
        )


def _duet_status(agent, args: dict, ctx: InlineToolContext) -> Any:
    try:
        service, identity = _duet_context(agent)
        return json.dumps(service.duet_status(identity.duet_id), sort_keys=True)
    except Exception as exc:
        return json.dumps({"accepted": False, "reason": type(exc).__name__}, sort_keys=True)


def _episode_workflow_read(agent, args: dict, ctx: InlineToolContext) -> Any:
    from agent.episode_contracts import OpaqueId

    try:
        service, identity = _duet_context(agent)
        return json.dumps(
            service.read_episode_workflow_draft(
                identity.duet_id,
                OpaqueId(args.get("artifact_id")),
            ),
            sort_keys=True,
        )
    except Exception as exc:
        return json.dumps(
            {"accepted": False, "reason": type(exc).__name__},
            sort_keys=True,
        )


def _duet_contract_review(agent, args: dict, ctx: InlineToolContext) -> Any:
    try:
        reviewer = getattr(agent, "_duet_contract_reviewer", None)
        if not callable(reviewer):
            raise RuntimeError("no shadow contract reviewer is bound")
        return json.dumps(reviewer(), sort_keys=True)
    except Exception as exc:
        return json.dumps(
            {"accepted": False, "reason": type(exc).__name__}, sort_keys=True
        )


def _duet_answer(agent, args: dict, ctx: InlineToolContext) -> Any:
    from agent.episode_contracts import OpaqueId

    try:
        service, _identity = _duet_context(agent)
        with _duet_draft_write(agent):
            draft = service.submit_duet_answer(
                OpaqueId(args.get("answer_artifact_id"))
            )
        return json.dumps(
            {
                "accepted": True,
                "revision": draft.revision,
                "ready": draft.ready,
                "deficit_codes": [item.code for item in draft.deficits],
            },
            sort_keys=True,
        )
    except Exception as exc:
        return json.dumps({"accepted": False, "reason": type(exc).__name__}, sort_keys=True)


def _duet_decision(agent, args: dict, ctx: InlineToolContext) -> Any:
    from agent.episode_contracts import OpaqueId

    try:
        service, _identity = _duet_context(agent)
        accepted = service.submit_duet_decision(
            OpaqueId(args.get("decision_artifact_id"))
        )
        return json.dumps({"accepted": accepted}, sort_keys=True)
    except Exception as exc:
        return json.dumps({"accepted": False, "reason": type(exc).__name__}, sort_keys=True)


def _episode_creator(agent, args: dict, ctx: InlineToolContext) -> Any:
    from agent.episode_contracts import OpaqueId, Sha256Digest
    from agent.duet_contracts import CreatorLaunchReceipt

    try:
        service, _identity = _duet_context(agent)
        launcher = getattr(agent, "_duet_creator_launcher", None)
        if not callable(launcher):
            raise RuntimeError("no task-specific Creator launcher is bound")
        with _duet_draft_write(agent):
            episode_id = service.submit_episode_creator(
                contract_artifact_id=OpaqueId(args.get("contract_artifact_id")),
                content_hash=Sha256Digest(args.get("content_hash")),
                human_approval_id=OpaqueId(args.get("human_approval_id")),
            )
        receipts = getattr(agent, "_duet_creator_receipts", None)
        if not isinstance(receipts, dict):
            receipts = {}
            agent._duet_creator_receipts = receipts
        receipt = receipts.get(episode_id.value)
        if receipt is None:
            receipt = launcher(episode_id)
        if not isinstance(receipt, CreatorLaunchReceipt):
            raise TypeError("Creator launcher must return CreatorLaunchReceipt")
        if receipt.creator_episode_id != episode_id:
            raise ValueError("Creator launch receipt identifies another admission")
        receipts[episode_id.value] = receipt
        return json.dumps(
            {"accepted": True, **receipt.as_record()},
            sort_keys=True,
        )
    except Exception as exc:
        return json.dumps({"accepted": False, "reason": type(exc).__name__}, sort_keys=True)


def _creator_context_artifact(agent, args: dict, ctx: InlineToolContext) -> Any:
    try:
        role = getattr(agent, "_openchia_role", None)
        if role == "duet":
            service, identity = _duet_context(agent)
            duet_id = identity.duet_id
            producer_id = None
        elif role == "creator":
            service = getattr(agent, "_creator_context_service", None)
            producer_id = getattr(agent, "_creator_episode_id", None)
            if service is None or producer_id is None:
                raise RuntimeError("no active Creator context authority")
            duet_id = service.creator_contract(producer_id).duet_id
        else:
            raise RuntimeError("context artifacts require an active Duet or Creator")
        reference = service.register_creator_context_artifact(
            duet_id,
            artifact_kind=args.get("artifact_kind"),
            schema_version=args.get("schema_version"),
            purpose=args.get("purpose"),
            required=args.get("required"),
            content=args.get("content"),
            producer_creator_episode_id=producer_id,
        )
        return json.dumps(
            {"accepted": True, "reference": reference.as_record()},
            sort_keys=True,
        )
    except Exception as exc:
        return json.dumps(
            {"accepted": False, "reason": type(exc).__name__},
            sort_keys=True,
        )


def _creator_context_read(agent, args: dict, ctx: InlineToolContext) -> Any:
    try:
        artifact_id = args.get("artifact_id")
        if not isinstance(artifact_id, str):
            raise ValueError("artifact_id must be a string")
        if getattr(agent, "_openchia_role", None) == "duet":
            from agent.episode_contracts import OpaqueId

            service, identity = _duet_context(agent)
            artifact = service.read_creator_context_artifact(
                identity.duet_id,
                OpaqueId(artifact_id),
            )
            return json.dumps(
                {
                    **artifact,
                    "delivery": "exact_whole_artifact_v1",
                    "authority": "duet_context_ledger",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        artifacts = getattr(agent, "_creator_context_artifacts", None)
        reads = getattr(agent, "_creator_context_read_ids", None)
        if not isinstance(artifacts, dict) or not isinstance(reads, set):
            raise RuntimeError("no active Creator context scope")
        artifact = artifacts.get(artifact_id)
        if artifact is None:
            raise PermissionError("context artifact is not authorized for this Creator")
        reads.add(artifact_id)
        _publish_creator_activity(
            agent,
            "gathering_context",
            "creator_context_read",
            {
                "artifact_id": artifact_id,
                "required": artifact_id
                in getattr(agent, "_creator_required_context_ids", frozenset()),
                "remaining_required_count": len(
                    _required_creator_context_unread(agent)
                ),
            },
        )
        return json.dumps(
            {
                "artifact_id": artifact_id,
                "reference": artifact["reference"],
                "content": artifact["content"],
                "delivery": "exact_whole_artifact_v1",
                "authority": "approved_creator_contract",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    except Exception as exc:
        return json.dumps(
            {"accepted": False, "reason": type(exc).__name__},
            sort_keys=True,
        )


def _required_creator_context_unread(agent) -> list[str]:
    required = getattr(agent, "_creator_required_context_ids", frozenset())
    reads = getattr(agent, "_creator_context_read_ids", set())
    if not isinstance(required, (set, frozenset)) or not isinstance(reads, set):
        return []
    return sorted(set(required) - reads)


def _publish_creator_activity(
    agent: Any,
    stage: str,
    activity_code: str,
    details: dict[str, Any],
) -> None:
    """Best-effort bridge from Creator protocol tools to host activity state."""

    publisher = getattr(agent, "_creator_activity_publisher", None)
    if not callable(publisher):
        return
    try:
        publisher(stage, activity_code, details)
    except Exception:
        return


def _creator_protocol_result(agent: Any, name: str, result: dict[str, Any]) -> str:
    setattr(agent, name, dict(result))
    return json.dumps(result, sort_keys=True)


def _creator_log_read(agent, args: dict, ctx: InlineToolContext) -> Any:
    try:
        log_store = getattr(agent, "_creator_log_store", None)
        references = getattr(agent, "_creator_log_references", None)
        if log_store is None or not isinstance(references, dict):
            raise RuntimeError("no active Creator log scope")
        reference = references.get(args.get("log_artifact_id"))
        if reference is None:
            raise PermissionError("log artifact is not owned by this Creator")
        content = log_store.read(
            reference,
            offset=args.get("offset", 0),
            limit=args.get("limit", 65_536),
        )
        _publish_creator_activity(
            agent,
            "gathering_context",
            "creator_run_log_read",
            {"log_artifact_id": reference.artifact_id.value},
        )
        return json.dumps(
            {
                "log_artifact_id": reference.artifact_id.value,
                "digest": reference.digest.value,
                "location": reference.location,
                "content": content,
                "untrusted": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    except Exception as exc:
        return json.dumps({"accepted": False, "reason": type(exc).__name__}, sort_keys=True)


def _workflow_candidate(agent, args: dict, ctx: InlineToolContext) -> Any:
    from agent.duet_service import WorkflowAdmissionError
    from agent.episode_contracts import Sha256Digest

    submit = getattr(agent, "_creator_workflow_submit", None)
    if not callable(submit):
        return _creator_protocol_result(
            agent,
            "_creator_last_candidate_result",
            {"accepted": False, "reason": "no_active_creator_design_cycle"},
        )
    unread_context = _required_creator_context_unread(agent)
    if unread_context:
        return _creator_protocol_result(
            agent,
            "_creator_last_candidate_result",
            {
                "accepted": False,
                "reason": "required_context_unread",
                "artifact_ids": unread_context,
            },
        )
    workflow = args.get("workflow")
    if not isinstance(workflow, dict):
        return _creator_protocol_result(
            agent,
            "_creator_last_candidate_result",
            {"accepted": False, "reason": "invalid_workflow_blueprint"},
        )
    recorder = getattr(agent, "_creator_workflow_draft_recorder", None)
    if callable(recorder):
        try:
            recorder(workflow, "candidate")
        except Exception as exc:
            return _creator_protocol_result(
                agent,
                "_creator_last_candidate_result",
                {
                    "accepted": False,
                    "reason": "workflow_draft_persistence_failed",
                    "message": str(exc)[:2048],
                },
            )
    blueprint_hash = Sha256Digest.of_record(workflow).value
    reviewed_hashes = getattr(agent, "_creator_reviewed_workflow_hashes", set())
    if blueprint_hash not in reviewed_hashes:
        result = {
            "accepted": False,
            "reason": "workflow_review_required",
            "workflow_blueprint_hash": blueprint_hash,
        }
        _publish_creator_activity(
            agent,
            "revising",
            "workflow_candidate_rejected",
            {"reason": result["reason"]},
        )
        return _creator_protocol_result(
            agent,
            "_creator_last_candidate_result",
            result,
        )
    _publish_creator_activity(
        agent,
        "submitting",
        "workflow_candidate_submitting",
        {"workflow_blueprint_hash": blueprint_hash},
    )
    try:
        candidate = submit(workflow)
        result = {
            "accepted": True,
            "shadow_reviewed": blueprint_hash in reviewed_hashes,
            "candidate_artifact_id": candidate.artifact_id.value,
            "revision": candidate.revision,
            "workflow_hash": candidate.workflow.workflow_hash.value,
            "episode_count": len(candidate.workflow.episodes),
        }
        _publish_creator_activity(
            agent,
            "submitting",
            "workflow_candidate_admitted",
            {
                "candidate_artifact_id": candidate.artifact_id.value,
                "candidate_revision": candidate.revision,
                "episode_count": len(candidate.workflow.episodes),
            },
        )
        return _creator_protocol_result(
            agent,
            "_creator_last_candidate_result",
            result,
        )
    except WorkflowAdmissionError as exc:
        result = {
            "accepted": False,
            "reason": "workflow_admission_failed",
            "deficits": [item.as_record() for item in exc.deficits],
        }
        _publish_creator_activity(
            agent,
            "revising",
            "workflow_candidate_rejected",
            {
                "reason": result["reason"],
                "deficit_codes": [item.code for item in exc.deficits],
            },
        )
        return _creator_protocol_result(
            agent,
            "_creator_last_candidate_result",
            result,
        )
    except Exception as exc:
        result = {
            "accepted": False,
            "reason": type(exc).__name__,
            "message": str(exc)[:2048],
        }
        _publish_creator_activity(
            agent,
            "revising",
            "workflow_candidate_rejected",
            {"reason": result["reason"], "message": result["message"]},
        )
        return _creator_protocol_result(
            agent,
            "_creator_last_candidate_result",
            result,
        )


def _workflow_review(agent, args: dict, ctx: InlineToolContext) -> Any:
    from agent.episode_contracts import Sha256Digest

    reviewer = getattr(agent, "_creator_workflow_reviewer", None)
    if not callable(reviewer):
        return json.dumps(
            {"accepted": False, "reason": "no_active_workflow_reviewer"},
            sort_keys=True,
        )
    unread_context = _required_creator_context_unread(agent)
    if unread_context:
        return json.dumps(
            {
                "accepted": False,
                "reason": "required_context_unread",
                "artifact_ids": unread_context,
            },
            sort_keys=True,
        )
    workflow = args.get("workflow")
    lenses = args.get("lenses")
    if not isinstance(workflow, dict) or not isinstance(lenses, list):
        return json.dumps(
            {"accepted": False, "reason": "invalid_review_request"},
            sort_keys=True,
        )
    recorder = getattr(agent, "_creator_workflow_draft_recorder", None)
    if callable(recorder):
        try:
            recorder(workflow, "review")
        except Exception as exc:
            return json.dumps(
                {
                    "accepted": False,
                    "reason": "workflow_draft_persistence_failed",
                    "message": str(exc)[:2048],
                },
                sort_keys=True,
            )
    blueprint_hash = Sha256Digest.of_record(workflow).value
    _publish_creator_activity(
        agent,
        "reviewing",
        "workflow_review_started",
        {
            "workflow_blueprint_hash": blueprint_hash,
            "lenses": list(lenses),
        },
    )
    try:
        result = reviewer(workflow, tuple(lenses))
        if isinstance(result, dict) and result.get("accepted") is True:
            reviewed = getattr(agent, "_creator_reviewed_workflow_hashes", None)
            if isinstance(reviewed, set):
                reviewed.add(blueprint_hash)
        lens_results = result.get("lenses") if isinstance(result, dict) else None
        finding_count = 0
        blocking_lenses = []
        if isinstance(lens_results, dict):
            for lens, review in lens_results.items():
                if not isinstance(review, dict):
                    continue
                finding_count += len(review.get("findings") or ())
                if review.get("verdict") == "block":
                    blocking_lenses.append(lens)
        _publish_creator_activity(
            agent,
            "revising" if finding_count else "designing",
            "workflow_review_completed",
            {
                "workflow_blueprint_hash": blueprint_hash,
                "finding_count": finding_count,
                "blocking_lenses": sorted(blocking_lenses),
            },
        )
        if isinstance(result, dict):
            agent._creator_last_review_result = dict(result)
        return json.dumps(result, sort_keys=True)
    except Exception as exc:
        result = {
            "accepted": False,
            "reason": type(exc).__name__,
            "message": str(exc)[:2048],
        }
        agent._creator_last_review_result = dict(result)
        _publish_creator_activity(
            agent,
            "revising",
            "workflow_review_failed",
            {"reason": result["reason"], "message": result["message"]},
        )
        return json.dumps(result, sort_keys=True)


# Order is the historical if/elif order of ``execute_tool_calls_sequential``.
INLINE_TOOL_EXECUTORS: Dict[str, InlineToolExecutor] = {
    "todo_list": _tool(
        "tools.todo_tool", "todo_tool", ("todos", "todos"), ("merge", "merge", False),
        store=lambda agent, ctx: agent._todo_store,
    ),
    # Bot Mode teammate DM is injected, not registered: only a canonical Bot
    # Chat session carries the schema, and the tool re-gates on the title.
    "message_agent": _tool(
        "tools.bot_mode_dm", "message_agent_tool", ("target", "target", ""), ("message", "message", ""),
        task_id=lambda agent, ctx: ctx.effective_task_id, agent=lambda agent, ctx: agent,
    ),
    "session_search": _session_search,
    "memory": _memory,
    "clarify": _tool(
        "tools.clarify_tool", "clarify_tool",
        ("question", "question", ""), ("choices", "choices"), ("multi_select", "multi_select", False),
        ("questions", "questions"),
        callback=lambda agent, ctx: agent.clarify_callback,
    ),
    "read_terminal": _callback_tool(
        "tools.read_terminal_tool", "read_terminal_tool", "read_terminal_callback",
        ("start_line", "start_line"), ("count", "count"),
    ),
    "desktop_preview": _desktop_preview,
    "drive_preview": _callback_tool(
        "tools.drive_preview_tool", "drive_preview_tool", "drive_preview_callback",
        ("action", "action", ""), ("ref", "ref"), ("selector", "selector"), ("text", "text"),
        ("key", "key"), ("submit", "submit"), ("amount", "amount"), ("to", "to"), ("limit", "max"),
    ),
    "annotate_preview": _callback_tool(
        "tools.annotate_preview_tool", "annotate_preview_tool", "drive_preview_callback",
        ("action", "action", "add"), ("ref", "ref"), ("selector", "selector"), ("label", "label"),
    ),
    "read_window_below": _callback_tool(
        "tools.read_window_tool", "read_window_below_tool", "read_window_below_callback",
    ),
    "gui_tour": _callback_tool(
        "tools.tour_tool", "tour_tool", "tour_callback",
        ("action", "action", ""), ("surface", "surface"), ("selector", "selector"), ("title", "title"),
        ("text", "text"), ("side", "side"), ("steps", "steps"), ("step_index", "step_index"),
    ),
    "manage_connections": _manage_connections,
    "manage_catalog": _manage_catalog,
    "setup_mcp": _setup_mcp_shim,
    "openchia_scope": _openchia_scope,
    "duet_contract_patch": _duet_contract_patch,
    "duet_contract_review": _duet_contract_review,
    "duet_status": _duet_status,
    "episode_workflow_read": _episode_workflow_read,
    "duet_answer": _duet_answer,
    "duet_decision": _duet_decision,
    "episode_creator": _episode_creator,
    "creator_context_artifact": _creator_context_artifact,
    "creator_context_read": _creator_context_read,
    "creator_log_read": _creator_log_read,
    "workflow_review": _workflow_review,
    "workflow_candidate": _workflow_candidate,
    "episode_progress": _episode_progress,
}

# ``invoke_tool`` (concurrent path) consults the memory manager right after these three
# names and before the remaining inline tools; ``message_agent`` falls through to the
# registry there (Bot Mode DM is only injected into the sequential path's schema).
INVOKE_TOOL_PRE_MEMORY_MANAGER_NAMES = frozenset({"todo_list", "session_search", "memory"})


def resolve_invoke_tool_executor(agent, function_name: str) -> Optional[InlineToolExecutor]:
    """Inline executor for ``invoke_tool`` (concurrent path), or None for registry dispatch.

    Precedence: todo_list/session_search/memory, then memory-manager tools, then the
    remaining inline tools (``message_agent`` excluded).
    """
    if function_name in INVOKE_TOOL_PRE_MEMORY_MANAGER_NAMES:
        return INLINE_TOOL_EXECUTORS[function_name]
    memory_manager = agent._memory_manager
    if memory_manager and memory_manager.has_tool(function_name):
        return lambda agent, args, ctx: agent._memory_manager.handle_tool_call(function_name, args)
    if function_name == "message_agent":
        return None
    return INLINE_TOOL_EXECUTORS.get(function_name)
