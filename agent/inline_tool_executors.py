"""Agent-level ("inline") tool executors shared by the sequential and concurrent tool paths.

These tools need live ``AIAgent`` state (stores, callbacks, session DB) and therefore
bypass the tool registry. Each executor is ``fn(agent, args, ctx) -> result``; the
table replaces two hand-maintained if/elif chains (``invoke_tool`` and
``execute_tool_calls_sequential``) that had drifted apart. Tool modules are imported
lazily at call time so ``patch("tools.x.y")`` in tests keeps working.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable, Dict, Mapping, Optional, Tuple


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


def _duet_context(agent):
    service = getattr(agent, "_duet_service", None)
    identity = getattr(agent, "_duet_identity", None)
    if service is None or identity is None:
        raise RuntimeError("no active host-bound Duet")
    return service, identity


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


def _duet_status(agent, args: dict, ctx: InlineToolContext) -> Any:
    try:
        service, identity = _duet_context(agent)
        status = service.duet_status(identity.duet_id)
        reader = getattr(agent, "_duet_launch_reader", None)
        if callable(reader):
            status["launch"] = reader()
        return json.dumps(status, sort_keys=True)
    except Exception as exc:
        return json.dumps({"accepted": False, "reason": type(exc).__name__}, sort_keys=True)


def _duet_launch_propose(agent, args: dict, ctx: InlineToolContext) -> Any:
    try:
        _duet_context(agent)
        proposer = getattr(agent, "_duet_launch_proposer", None)
        if not callable(proposer):
            raise RuntimeError("no host-bound launch configuration proposer")
        return json.dumps(proposer(args["configuration"]), sort_keys=True)
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        return json.dumps({"accepted": False, "reason": type(exc).__name__, "detail": str(exc)}, sort_keys=True)


_ABSENT_DRAFT_SPELLINGS = frozenset({"", "null", "none"})


def _absent_draft_field(value: Any) -> Any:
    """Fold the model-facing spellings of "no draft yet" onto ``None``.

    The CAS fields are declared ``string | null`` (``integer | null``), but a model
    may still spell absence as the string ``"null"``, ``"none"`` or ``""`` — observed
    in a live Duet whose six first-draft submissions were all rejected as conflicts.
    A real draft identity, hash or revision never looks like those, so folding
    them onto ``None`` cannot weaken the guard: a prior draft still requires its
    exact values.
    """
    if isinstance(value, str) and value.strip().lower() in _ABSENT_DRAFT_SPELLINGS:
        return None
    return value


def _episode_architecture_submit(agent, args: dict, ctx: InlineToolContext) -> Any:
    try:
        callback = getattr(agent, "_episode_architecture_submitter", None)
        if not callable(callback):
            raise RuntimeError("no host-bound Architecture submitter")
        candidate = args.get("candidate_workflow_architecture")
        artifact_id = _absent_draft_field(args.get("expected_artifact_id"))
        content_hash = _absent_draft_field(args.get("expected_content_hash"))
        revision = _absent_draft_field(args.get("expected_revision"))
        note_ids = args.get("human_note_ids")
        if not isinstance(candidate, Mapping):
            raise ValueError("proposed Target Workflow Architecture must be an object")
        if (artifact_id is None) != (content_hash is None) or (
            artifact_id is None
        ) != (revision is None):
            raise ValueError(
                "expected draft identity, hash, and revision must all be present or null"
            )
        if artifact_id is not None and (
            not isinstance(artifact_id, str)
            or not artifact_id.strip()
            or not isinstance(content_hash, str)
            or not content_hash.strip()
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
        ):
            raise ValueError("expected draft CAS fields are invalid")
        if (
            not isinstance(note_ids, list)
            or any(not isinstance(item, str) or not item.strip() for item in note_ids)
            or len(set(note_ids)) != len(note_ids)
        ):
            raise ValueError("human_note_ids must be unique saved identities")
        result = callback(
            candidate_workflow_architecture=dict(candidate),
            expected_artifact_id=artifact_id,
            expected_content_hash=content_hash,
            expected_revision=revision,
            human_note_ids=tuple(note_ids),
        )
        if (
            not isinstance(result, Mapping)
            or not isinstance(result.get("accepted"), bool)
        ):
            raise RuntimeError("host returned a malformed Architecture response")
        return json.dumps(dict(result), ensure_ascii=False, sort_keys=True)
    except Exception as exc:
        return json.dumps(
            {
                "accepted": False,
                "reason": type(exc).__name__,
                "message": str(exc)[:2048],
            },
            sort_keys=True,
        )


def _episode_workspace_read(agent, args: dict, ctx: InlineToolContext) -> Any:
    try:
        callback = getattr(agent, "_episode_workspace_reader", None)
        if not callable(callback):
            raise RuntimeError("no host-bound Episode workspace reader")
        target_id = args.get("target_id")
        note_id = args.get("note_id")
        if (target_id is None) == (note_id is None):
            raise ValueError("provide exactly one of target_id or note_id")
        lookup_name = "target_id" if target_id is not None else "note_id"
        lookup_id = target_id if target_id is not None else note_id
        if not isinstance(lookup_id, str) or not lookup_id.strip():
            raise ValueError(f"{lookup_name} must be a non-empty opaque identity")
        result = callback(**{lookup_name: lookup_id})
        required = {
            "baseline_id",
            "part_kind",
            "selected_part",
            "target_metadata",
            "human_notes",
            "evidence",
        }
        if not isinstance(result, Mapping) or set(result) != required:
            raise RuntimeError("host returned a malformed workspace selection")
        baseline_id = result["baseline_id"]
        if (
            baseline_id is not None
            and (
                not isinstance(baseline_id, str)
                or not baseline_id.strip()
            )
        ):
            raise RuntimeError("host returned invalid workspace baseline metadata")
        if result["part_kind"] not in {"architecture", "materialized"}:
            raise RuntimeError("host returned invalid workspace identity metadata")
        if result["part_kind"] == "materialized" and baseline_id is None:
            raise RuntimeError("materialized workspace selection has no baseline")
        target = result["target_metadata"]
        expected_target_fields = {
            "target_id",
            "content_hash",
            "layer",
            "artifact_id",
            "artifact_hash",
            "json_pointer",
            "episode_local_id",
        }
        if (
            not isinstance(target, Mapping)
            or set(target) != expected_target_fields
        ):
            raise RuntimeError("host returned stale target metadata")
        notes = result["human_notes"]
        if not isinstance(notes, list) or any(
            not isinstance(note, Mapping)
            or set(note) != {"note_id", "target_id", "body"}
            or not isinstance(note["note_id"], str)
            or not isinstance(note["target_id"], str)
            or not isinstance(note["body"], str)
            for note in notes
        ):
            raise RuntimeError("host returned malformed saved human notes")
        if target_id is not None and target.get("target_id") != target_id:
            raise RuntimeError("host returned another current target")
        if note_id is not None and not any(
            note["note_id"] == note_id
            and note["target_id"] == target.get("target_id")
            for note in notes
        ):
            raise RuntimeError("host returned another saved note or target")
        return json.dumps(
            {
                "accepted": True,
                "workspace": {
                    "baseline_id": baseline_id,
                    "part_kind": result["part_kind"],
                    "target_metadata": dict(target),
                    "human_notes": [dict(note) for note in notes],
                },
                "untrusted_reference_data": {
                    "boundary": "UNTRUSTED_REFERENCE_DATA",
                    "selected_part": result["selected_part"],
                    "evidence": result["evidence"],
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    except Exception as exc:
        return json.dumps(
            {
                "accepted": False,
                "reason": type(exc).__name__,
                "message": str(exc)[:2048],
            },
            sort_keys=True,
        )


def _episode_refinement_request(agent, args: dict, ctx: InlineToolContext) -> Any:
    try:
        callback = getattr(agent, "_episode_refinement_requester", None)
        if not callable(callback):
            raise RuntimeError("no host-bound Episode refinement requester")
        baseline_id = args.get("baseline_id")
        candidate = args.get("candidate_workflow_architecture")
        note_ids = args.get("human_note_ids")
        directives = args.get("implementation_directives")
        if not isinstance(baseline_id, str) or not baseline_id.strip():
            raise ValueError("baseline_id must be a non-empty opaque identity")
        if not isinstance(candidate, Mapping):
            raise ValueError("proposed Target Workflow Architecture must be an object")
        if (
            not isinstance(note_ids, list)
            or not note_ids
            or any(not isinstance(item, str) or not item.strip() for item in note_ids)
            or len(set(note_ids)) != len(note_ids)
        ):
            raise ValueError("human_note_ids must be unique saved identities")
        if not isinstance(directives, list):
            raise ValueError("implementation_directives must be an array")
        normalized_directives = []
        for directive in directives:
            if (
                not isinstance(directive, Mapping)
                or set(directive)
                != {"human_note_id", "target_id", "instruction"}
            ):
                raise ValueError("implementation directive has an invalid shape")
            normalized = {
                "human_note_id": directive["human_note_id"],
                "target_id": directive["target_id"],
                "instruction": directive["instruction"],
            }
            if any(
                not isinstance(normalized[name], str)
                or not normalized[name].strip()
                or "\x00" in normalized[name]
                for name in normalized
            ):
                raise ValueError("implementation directive fields must be text")
            if normalized["human_note_id"] not in note_ids:
                raise ValueError(
                    "implementation directive must cite a selected human note"
                )
            normalized_directives.append(normalized)
        result = callback(
            baseline_id=baseline_id,
            candidate_workflow_architecture=dict(candidate),
            human_note_ids=tuple(note_ids),
            implementation_directives=tuple(normalized_directives),
        )
        if (
            not isinstance(result, Mapping)
            or not isinstance(result.get("accepted"), bool)
        ):
            raise RuntimeError("host returned a malformed refinement response")
        return json.dumps(dict(result), ensure_ascii=False, sort_keys=True)
    except Exception as exc:
        return json.dumps(
            {
                "accepted": False,
                "reason": type(exc).__name__,
                "message": str(exc)[:2048],
            },
            sort_keys=True,
        )


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
    "duet_status": _duet_status,
    "duet_launch_propose": _duet_launch_propose,
    "episode_architecture_submit": _episode_architecture_submit,
    "episode_workspace_read": _episode_workspace_read,
    "episode_refinement_request": _episode_refinement_request,
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
