"""Classic terminal surface for the OpenChia Duet and Episode system."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from prompt_toolkit.layout import FormattedTextControl, Window
from rich.markup import escape

from agent.duet_contracts import OPENCHIA_CONTROL_PLANE_TOOLS, DuetMessageKind
from agent.episode_blueprints import CREATION_BLUEPRINT_FIELDS
from agent.openchia_host import EPISODE_FIELD_PLACEHOLDER, OpenChiaHost
from cli import HermesCLI
from hermes_constants import get_hermes_home


_MISSING = object()


@dataclass
class _BackgroundDuet:
    """One independently conversational Duet running beside the foreground Duet."""

    duet_id: str
    ordinal: int
    host: OpenChiaHost
    agent: Any
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    thread: threading.Thread | None = None
    last_error: str | None = None


def episode_configuration_changes(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    field_metadata: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return stable path-level changes between two Episode configurations."""

    metadata = field_metadata or {}
    changes: list[dict[str, Any]] = []

    def metadata_for(path: str) -> dict[str, Any]:
        candidate = path
        while candidate:
            if candidate in metadata:
                return dict(metadata[candidate])
            candidate, _, _leaf = candidate.rpartition(".")
        return {}

    def visit(path: str, old: Any, new: Any) -> None:
        if isinstance(old, Mapping) and isinstance(new, Mapping):
            for key in sorted(set(old) | set(new)):
                child_path = f"{path}.{key}" if path else str(key)
                visit(
                    child_path,
                    old.get(key, _MISSING),
                    new.get(key, _MISSING),
                )
            return
        if old is not _MISSING and new is not _MISSING and old == new:
            return
        if old is _MISSING:
            kind = "added"
        elif new is _MISSING:
            kind = "removed"
        else:
            kind = "changed"
        change = {"path": path, "kind": kind, **metadata_for(path)}
        if old is not _MISSING:
            change["before"] = old
        if new is not _MISSING:
            change["after"] = new
        changes.append(change)

    visit("", before, after)
    return tuple(changes)


def render_openchia_status(status: dict[str, Any] | None) -> str:
    """Render only changing state; the architecture diagram belongs in the banner."""

    if not status:
        return "Duet · describe the outcome you want · /help"
    progress = status.get("creator_progress") or {}
    state = str(status.get("state") or "unknown")
    revision = int(status.get("revision") or 0)
    field_count = int(status.get("field_count") or 0)
    deficits = tuple(status.get("requested_field_ids") or ())
    if status.get("launch"):
        run_state = str(status.get("final_run_state") or "launched")
        if status.get("final_error_code"):
            run_state += f" ({status['final_error_code']})"
        return f"Run · {run_state} · /logs"

    episode_workflow = status.get("episode_workflow") or {}
    if episode_workflow:
        workflow_revision = int(episode_workflow.get("revision") or 0)
        validation_state = str(
            episode_workflow.get("validation_state") or "draft"
        )
        if validation_state == "running":
            return (
                f"Episode workflow r{workflow_revision} · validating\n"
                "/episode · /duet"
            )
        if validation_state == "failed":
            error = episode_workflow.get("error_code") or "validation_failed"
            return (
                f"Episode workflow r{workflow_revision} · validation failed\n"
                f"Stopped: {error} · /episode · /design"
            )
        if validation_state == "measured":
            return (
                f"Episode workflow r{workflow_revision} · measured and ready\n"
                "/episode · /approve · /logs"
            )
        return (
            f"Episode workflow r{workflow_revision} · draft under validation\n"
            "/episode · /design"
        )

    if status.get("creator_episode_id"):
        creator_state = str(progress.get("state") or state)
        candidate = int(progress.get("candidate_revision") or 0)
        credit = progress.get("method_credit")
        activity = status.get("creator_activity") or {}
        attempt = int(activity.get("attempt") or 1)
        detail = f"attempt {attempt} · candidate {candidate}"
        if credit is not None:
            detail += f" · credit {credit}"
        if status.get("creator_failure"):
            failure = status["creator_failure"]
            code = failure.get("error_code") or failure.get("error_class") or "failed"
            commands = (
                "/design · /retry"
                if failure.get("retryable") is True
                else "/design"
            )
            return (
                f"Design pass · failed · {detail}\n"
                f"Stopped: {code} · {commands}"
            )
        if activity:
            step, step_count = _creator_stage_position(
                str(activity.get("stage") or "initializing")
            )
            current = _creator_activity_text(activity)
            commands = (
                "/approve · /design · /logs"
                if state == "awaiting_workflow_approval"
                else "/design · /guide · /pause"
            )
            return (
                f"Design pass · {creator_state} · {detail}\n"
                f"Stage {step}/{step_count}: {current} · {commands}"
            )
        return (
            f"Design pass · {creator_state} · {detail}\n"
            "/design · /guide · /pause"
        )

    if status.get("ready"):
        proposals = len(status.get("unconfirmed_proposal_ids") or ())
        assumption_note = f" · {proposals} unconfirmed proposal(s)" if proposals else ""
        review = status.get("contract_review")
        review_note = (
            "shadow review pending"
            if not isinstance(review, dict)
            else f"shadow review: {review.get('verdict', 'unknown')}"
        )
        return (
            f"Duet · contract r{revision} ready{assumption_note} · {review_note}\n"
            "/review · /approve"
        )

    labels = {
        "goal": "intended outcome",
        "creator_contract.design_context": "structured design context",
        "creator_contract.design_scope": "workflow design scope",
        "result": "concrete result",
        "unit": "repeatable cycle",
        "progress": "success evidence",
        "stopping": "stopping behavior",
        "execution_capability_names": "needed tools",
        "creator_contract": "workflow design scope",
        "deliverable": "deliverable boundary",
        "safety_bounds": "safety limits",
    }
    focus = labels.get(deficits[0], deficits[0]) if deficits else "contract coherence"
    return (
        f"Duet · shaping contract · {field_count}/{len(CREATION_BLUEPRINT_FIELDS)} fields · gap: {focus}\n"
        "/help"
    )


def _creator_stage_position(stage: str) -> tuple[int, int]:
    positions = {
        "initializing": 1,
        "gathering_context": 1,
        "designing": 2,
        "reviewing": 3,
        "revising": 3,
        "submitting": 4,
        "running_candidate": 5,
        "evaluating": 6,
        "completed": 6,
        "failed": 6,
    }
    return positions.get(stage, 1), 6


def _creator_activity_text(activity: Mapping[str, Any]) -> str:
    code = str(activity.get("activity_code") or "creator_working")
    details = activity.get("details") or {}
    labels = {
        "creator_attempt_started": "initializing the internal design runtime",
        "design_cycle_started": "drafting a workflow candidate",
        "creator_context_read": "reading approved design context",
        "creator_run_log_read": "inspecting a prior Run log",
        "workflow_review_started": "running independent workflow review",
        "workflow_review_completed": "revising from workflow findings",
        "workflow_review_failed": "repairing an invalid review request",
        "workflow_candidate_submitting": "validating the candidate schema",
        "workflow_candidate_admitted": "candidate admitted",
        "workflow_candidate_rejected": "repairing a rejected candidate",
        "candidate_run_started": "testing the candidate workflow",
        "candidate_run_evaluating": "evaluating host evidence",
        "creator_attempt_completed": "design attempt complete",
        "creator_attempt_failed": "design attempt stopped",
    }
    text = labels.get(code, code.replace("_", " "))
    if code == "workflow_review_started" and isinstance(details.get("lenses"), list):
        text += f" ({len(details['lenses'])} lenses)"
    elif code == "workflow_review_completed" and details.get("finding_count") is not None:
        text += f" ({details['finding_count']} findings)"
    return text


def render_creator_diagnostics(status: dict[str, Any] | None) -> str:
    """Render a structured internal design trace and terminal diagnosis."""

    if not status or not status.get("creator_episode_id"):
        return "No internal Episode design pass is active."
    progress = status.get("creator_progress") or {}
    activity = status.get("creator_activity") or {}
    attempt = int(activity.get("attempt") or 1)
    lines = [
        f"Design attempt {attempt}: {progress.get('state') or status.get('state', 'unknown')}",
        f"Candidate revision: {int(progress.get('candidate_revision') or 0)}",
    ]
    history = status.get("creator_activity_history") or []
    if history:
        lines.append("Recent stages:")
        for item in history:
            observed = float(item.get("observed_at") or 0)
            started = float(item.get("attempt_started_at") or observed)
            elapsed = max(0, int(observed - started))
            lines.append(
                f"  {elapsed:>4}s  {item.get('stage', 'unknown')}: "
                f"{_creator_activity_text(item)}"
            )
    failure = status.get("creator_failure")
    if failure:
        error_code = (
            failure.get("error_code")
            or failure.get("error_class")
            or "unknown_error"
        )
        lines.extend(
            [
                "Failure:",
                f"  Code: {error_code}",
                "  Owner: "
                + (
                    "internal design"
                    if failure.get("owner") == "creator"
                    else str(failure.get("owner", "unknown"))
                ),
                f"  Stage: {failure.get('failed_stage', 'unknown')}",
                f"  Message: {failure.get('message') or 'No message recorded.'}",
            ]
        )
        submission = (failure.get("details") or {}).get("candidate_submission")
        if isinstance(submission, Mapping):
            lines.append(
                "  Candidate rejection: "
                f"{submission.get('reason', 'unknown')}"
            )
            if submission.get("message"):
                lines.append(f"  Validation detail: {submission['message']}")
        if failure.get("contract_change_required") is False:
            lines.append("  Approved design-brief change required: no")
    review = status.get("workflow_review") or {}
    lenses = review.get("lenses") or []
    if lenses:
        lines.append("Latest independent workflow review:")
        for lens in lenses:
            codes = ", ".join(lens.get("finding_codes") or ()) or "no findings"
            lines.append(
                f"  {lens.get('lens', 'unknown')}: "
                f"{lens.get('verdict', 'unknown')} — {codes}"
            )
    if failure:
        if failure.get("retryable") is True:
            lines.append("Next action: use /retry to start a new bounded design attempt.")
        else:
            lines.append(
                "Next action: inspect the platform error above; retry is withheld until "
                "the runtime problem is fixed."
            )
    else:
        lines.append("Current work: " + _creator_activity_text(activity))
    return "\n".join(lines)


class OpenChiaCLI(HermesCLI):
    """OpenChia terminal surface whose conversational role is the Duet."""

    _surface_branding = {
        "agent_name": "OpenChia",
        "assistant_label": "Duet",
        "command_name": "openchia",
        "goodbye": "OpenChia Duet closed.",
        "help_header": "OPENCHIA COMMANDS",
        "prompt_symbol": "❯",
        "response_label": "DUET",
        "status_symbol": "◈",
        "welcome": "OpenChia Duet ready.",
    }
    _openchia_commands = {
        "/episode": "Inspect or tree-edit the nested Episode workflow",
        "/duet": "Show the current design, validation, and Run state",
        "/openchia": "Alias for /duet",
        "/design": "Show internal drafting stages, failure evidence, and next action",
        "/queue": "Queue a message for the foreground Duet's next turn",
        "/bg": "Start or continue a separate background Duet",
        "/approve": "Approve the ready design brief or measured Episode workflow",
        "/answer": "Record an exact human answer to an open design field",
        "/review": "Run or show the advisory design-brief review",
        "/guide": "Queue human guidance at the next design boundary",
        "/pause": "Stop the design pass at its next boundary",
        "/cancel": "Cancel the design pass at its next boundary",
        "/retry": "Request another design attempt at the next boundary",
        "/logs": "List persisted Run Episode logs",
        "/stop": "Interrupt the current turn and stop owned background work",
        "/help": "Show OpenChia controls",
    }
    _inherited_commands = frozenset(
        {
            "/model",
            "/reasoning",
            "/fast",
            "/status",
            "/context",
            "/ctx",
            "/history",
            "/save",
            "/title",
            "/compress",
            "/compact",
            "/config",
            "/profile",
            "/statusbar",
            "/sb",
            "/timestamps",
            "/ts",
            "/focus",
            "/skin",
            "/indicator",
            "/verbose",
            "/usage",
            "/copy",
            "/paste",
            "/image",
            "/redraw",
            "/quit",
            "/exit",
        }
    )

    def __init__(self, **kwargs: Any) -> None:
        self._openchia_host: OpenChiaHost | None = None
        self._openchia_status_cache: dict[str, Any] | None = None
        self._openchia_status_at = 0.0
        self._episode_view_revision: int | None = None
        self._episode_view_configuration: dict[str, Any] | None = None
        self._episode_last_changes: tuple[
            int, int, tuple[dict[str, Any], ...]
        ] | None = None
        super().__init__(**kwargs)
        self._background_duets: dict[str, _BackgroundDuet] = {}
        self._background_duets_lock = threading.RLock()

    @staticmethod
    def _tool_names(agent: Any) -> tuple[str, ...]:
        import model_tools

        excluded = set(OPENCHIA_CONTROL_PLANE_TOOLS) | {
            "delegate_task",
            "tool_call",
            "tool_search",
        }
        names = set()
        for tool in model_tools.get_tool_definitions(
            quiet_mode=True,
            skip_tool_search_assembly=True,
        ):
            function = tool.get("function") if isinstance(tool, dict) else None
            name = function.get("name") if isinstance(function, dict) else None
            if isinstance(name, str) and name and name not in excluded:
                names.add(name)
        return tuple(sorted(names))

    def _surface_commands(self) -> dict[str, dict[str, str]]:
        return {
            command: {"description": description}
            for command, description in self._openchia_commands.items()
        }

    def _command_available(self, slash_command: str) -> bool:
        command = slash_command.lower().split(maxsplit=1)[0]
        return command in self._openchia_commands or command in self._inherited_commands

    def _build_command_palette_entries(self) -> list[tuple[str, str, str]]:
        entries = [
            (command, "OpenChia", description)
            for command, description in self._openchia_commands.items()
        ]
        from hermes_cli.commands import COMMANDS

        entries.extend(
            (command, "Session", COMMANDS[command])
            for command in sorted(self._inherited_commands)
            if command in COMMANDS
        )
        return entries

    def _agent_kwargs_for_episode_under(
        self,
        parent_session_id: str,
        role: str,
        identity: str,
    ) -> dict[str, Any]:
        from hermes_cli.cli_agent_setup_mixin import _current_runtime

        runtime = _current_runtime(self)
        return {
            "model": self.model,
            "api_key": runtime.get("api_key"),
            "base_url": runtime.get("base_url"),
            "provider": runtime.get("provider"),
            "requested_provider": runtime.get("requested_provider"),
            "api_mode": runtime.get("api_mode"),
            "acp_command": runtime.get("command"),
            "acp_args": runtime.get("args"),
            "credential_pool": runtime.get("credential_pool"),
            "max_iterations": self.max_turns,
            "run_budget_seconds": getattr(self, "run_budget_seconds", None),
            "verbose_logging": self.verbose,
            "quiet_mode": True,
            "tool_progress_mode": "off",
            "reasoning_config": self.reasoning_config,
            "service_tier": self.service_tier,
            "providers_allowed": self._providers_only,
            "providers_ignored": self._providers_ignore,
            "providers_order": self._providers_order,
            "provider_sort": self._provider_sort,
            "provider_require_parameters": self._provider_require_params,
            "provider_data_collection": self._provider_data_collection,
            "openrouter_min_coding_score": self._openrouter_min_coding_score,
            "fallback_model": self._fallback_model,
            "session_id": f"{parent_session_id}-{role}-{identity[-12:]}",
            "parent_session_id": parent_session_id,
            "platform": "openchia",
            "side_agent": True,
        }

    def _agent_kwargs_for_episode(self, role: str, identity: str) -> dict[str, Any]:
        return self._agent_kwargs_for_episode_under(
            self.session_id,
            role,
            identity,
        )

    def _configure_new_agent(self, agent: Any) -> Any:
        if self._openchia_host is None:
            self._openchia_host = OpenChiaHost(
                home=get_hermes_home(),
                session_id=self.session_id,
                available_tool_names=self._tool_names(agent),
                agent_kwargs_factory=self._agent_kwargs_for_episode,
            )
        self._openchia_status_cache = None
        return self._openchia_host.bind_duet(agent)

    @staticmethod
    def _agent_init_failure_message(error: BaseException) -> str:
        from hermes_cli.cli_chat_error_copy import (
            openchia_duet_init_failure_message,
        )

        return openchia_duet_init_failure_message(error)

    def show_banner(self) -> None:
        """Show the OpenChia work path without inherited agent-workflow framing."""

        self.console.clear()
        self._console_print("[bold #8fb9a8]OPENCHIA[/]  human + LLM = Duet")
        self._console_print()
        self._console_print("  [DUET] -- draft --> [EPISODE WORKFLOW]")
        self._console_print("                         | validate")
        self._console_print("                         v")
        self._console_print("                       [RUN]")
        self._console_print()

    def _tui_welcome_branding(self, welcome_skin: Any) -> tuple[str, str]:
        color = "#8fb9a8"
        if welcome_skin is not None:
            color = welcome_skin.get_color("banner_text", color)
        return (
            "OpenChia Duet ready. Describe the outcome, then use /duet to inspect or /help for controls.",
            color,
        )

    def _print_random_tip(self) -> None:
        self._console_print(
            "[dim]The Duet shapes the workflow; validation Runs return typed progress and logs.[/]"
        )

    def _tui_background_ui_active(self) -> bool:
        host_work = bool(
            self._openchia_host and self._openchia_host.has_active_work()
        )
        with self._background_duets_lock:
            duet_work = any(
                context.thread is not None and context.thread.is_alive()
                for context in self._background_duets.values()
            )
        return host_work or duet_work

    def _status(self, *, refresh: bool = False) -> dict[str, Any] | None:
        host = self._openchia_host
        if host is None:
            return None
        now = time.monotonic()
        if (
            refresh
            or self._openchia_status_cache is None
            or now - self._openchia_status_at >= 0.5
        ):
            status = host.status()
            draft = host.service.latest_draft(host.identity.duet_id)
            configuration = draft.materialized()
            status["field_count"] = sum(
                field in configuration for field in CREATION_BLUEPRINT_FIELDS
            )
            status["configuration"] = configuration
            self._openchia_status_cache = status
            self._openchia_status_at = now
        return self._openchia_status_cache

    def _panel_text(self) -> str:
        try:
            return render_openchia_status(self._status())
        except Exception as exc:
            return f"OpenChia status unavailable: {type(exc).__name__}"

    def _get_extra_tui_widgets(self) -> list[Any]:
        return [
            Window(
                FormattedTextControl(self._panel_text),
                height=2,
                style="class:openchia.status",
            )
        ]

    def _build_tui_style_dict(self) -> dict[str, str]:
        styles = super()._build_tui_style_dict()
        styles["openchia.status"] = "fg:#8fb9a8"
        return styles

    def _refresh_openchia(self) -> None:
        self._openchia_status_cache = None
        with __import__("contextlib").suppress(Exception):
            self._invalidate()

    def _print_openchia(self, text: str) -> None:
        self._console_print(escape(text))

    def _episode_host(self) -> OpenChiaHost:
        if self._openchia_host is None and not self._init_agent():
            raise RuntimeError("OpenChia could not initialize the Duet")
        if self._openchia_host is None:
            raise RuntimeError("OpenChia host is unavailable")
        return self._openchia_host

    @staticmethod
    def _json_value(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _render_episode_changes(
        self,
        from_revision: int,
        to_revision: int,
        changes: tuple[dict[str, Any], ...],
    ) -> str:
        if not changes:
            return f"Episode changes r{from_revision} -> r{to_revision}: none"
        markers = {"added": "+", "removed": "-", "changed": "~"}
        lines = [f"Episode changes r{from_revision} -> r{to_revision}:"]
        for change in changes:
            provenance = change.get("provenance")
            suffix = f" [{provenance}]" if provenance else ""
            lines.append(
                f"  {markers[change['kind']]} {change['path']}{suffix}"
            )
            if "before" in change:
                lines.append(f"      before: {self._json_value(change['before'])}")
            if "after" in change:
                lines.append(f"      after:  {self._json_value(change['after'])}")
        return "\n".join(lines)

    def _current_episode_changes(
        self,
        snapshot: Mapping[str, Any],
    ) -> tuple[int, int, tuple[dict[str, Any], ...]]:
        revision = int(snapshot["revision"])
        previous_revision = self._episode_view_revision
        previous = self._episode_view_configuration
        if previous_revision is None or previous is None:
            return revision, revision, ()
        changes = episode_configuration_changes(
            previous,
            snapshot["configuration"],
            field_metadata=snapshot.get("fields") or {},
        )
        return previous_revision, revision, changes

    def _remember_episode_view(self, snapshot: Mapping[str, Any]) -> None:
        self._episode_view_revision = int(snapshot["revision"])
        self._episode_view_configuration = json.loads(
            json.dumps(snapshot["configuration"], ensure_ascii=False)
        )

    def _show_episode_configuration(self) -> None:
        host = self._episode_host()
        snapshot = host.episode_workflow_configuration()
        changes = self._current_episode_changes(snapshot)
        self._episode_last_changes = changes
        from hermes_cli.openchia_episode_editor import view_episode_document

        view_episode_document(
            snapshot["configuration"],
            missing_value=EPISODE_FIELD_PLACEHOLDER,
        )
        self._remember_episode_view(snapshot)

    def _show_episode_changes(self) -> None:
        snapshot = self._episode_host().episode_workflow_configuration()
        changes = self._current_episode_changes(snapshot)
        if changes[2]:
            self._episode_last_changes = changes
        elif changes[0] == changes[1] and self._episode_last_changes is not None:
            changes = self._episode_last_changes
        self._print_openchia(self._render_episode_changes(*changes))

    @staticmethod
    def _is_episode_command(command: str) -> bool:
        stripped = command.strip()
        lower = stripped.lower()
        return lower == "/episode" or lower.startswith("/episode ")

    def _tui_enter_inline_command(self, event: Any, text: str, has_images: bool) -> bool:
        """Keep Episode inspection responsive while the Duet is producing a turn."""

        if (
            self._agent_running
            and not has_images
            and self._is_episode_command(text)
        ):
            action = text.strip()[len("/episode") :].strip().split(maxsplit=1)
            if not action or action[0].lower() in {"show", "status", "edit"}:
                from prompt_toolkit.application import run_in_terminal

                event.app.current_buffer.reset(append_to_history=True)
                run_in_terminal(
                    lambda: self.process_command(text),
                    in_executor=True,
                )
            else:
                self.process_command(text)
                event.app.current_buffer.reset(append_to_history=True)
            event.app.invalidate()
            return True
        return super()._tui_enter_inline_command(event, text, has_images)

    def _process_episode_command(self, stripped: str) -> bool:
        remainder = stripped[len("/episode") :].strip()
        action, _, arguments = remainder.partition(" ")
        action = action.lower() or "show"
        host = self._episode_host()
        if action in {"show", "status"}:
            self._show_episode_configuration()
            return True
        if action in {"diff", "changes"}:
            self._show_episode_changes()
            return True
        if action == "edit":
            with host.episode_workflow_edit_session() as snapshot:
                document = snapshot["configuration"]
                self._show_episode_changes()
                from hermes_cli.openchia_episode_editor import edit_episode_document

                edited = edit_episode_document(
                    document,
                    missing_value=EPISODE_FIELD_PLACEHOLDER,
                )
                if edited is None or edited == document:
                    self._remember_episode_view(
                        host.episode_workflow_configuration()
                    )
                    self._print_openchia("Episode workflow unchanged.")
                    return True
                revision = host.record_episode_workflow_revision(
                    edited,
                    source_artifact_id=snapshot["source_artifact_id"],
                    expected_workflow_hash=snapshot["content_hash"],
                )
                self._remember_episode_view(
                    host.episode_workflow_configuration()
                )
            self._print_openchia(
                f"Episode workflow saved as revision {revision['revision']}; "
                "host validation is running."
            )
            self._refresh_openchia()
            return True
        raise ValueError(
            "Usage: /episode [show|diff|edit]"
        )

    def _background_duet_agent_kwargs(
        self,
        duet_id: str,
        prompt: str,
    ) -> dict[str, Any]:
        route = self._resolve_turn_agent_config(prompt)
        runtime = route["runtime"]
        return {
            "model": route["model"],
            "api_key": runtime.get("api_key"),
            "base_url": runtime.get("base_url"),
            "provider": runtime.get("provider"),
            "requested_provider": runtime.get("requested_provider"),
            "api_mode": runtime.get("api_mode"),
            "acp_command": runtime.get("command"),
            "acp_args": runtime.get("args"),
            "credential_pool": runtime.get("credential_pool"),
            "max_iterations": self.max_turns,
            "run_budget_seconds": getattr(self, "run_budget_seconds", None),
            "enabled_toolsets": [],
            "disabled_toolsets": [],
            "verbose_logging": False,
            "quiet_mode": True,
            "tool_progress_mode": "off",
            "reasoning_config": self.reasoning_config,
            "service_tier": self.service_tier,
            "request_overrides": route.get("request_overrides"),
            "providers_allowed": self._providers_only,
            "providers_ignored": self._providers_ignore,
            "providers_order": self._providers_order,
            "provider_sort": self._provider_sort,
            "provider_require_parameters": self._provider_require_params,
            "provider_data_collection": self._provider_data_collection,
            "openrouter_min_coding_score": self._openrouter_min_coding_score,
            "fallback_model": self._fallback_model,
            "session_id": duet_id,
            "parent_session_id": self.session_id,
            "platform": "openchia",
            "side_agent": True,
            "session_db": self._session_db,
            "skip_context_files": True,
            "load_soul_identity": False,
            "skip_memory": True,
            "skip_background_review": True,
        }

    def _create_background_duet(
        self,
        duet_id: str,
        prompt: str,
        *,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> _BackgroundDuet:
        """Build a side conversation through the same host and Duet binding as the foreground."""

        from run_agent import AIAgent

        agent = AIAgent(**self._background_duet_agent_kwargs(duet_id, prompt))
        host: OpenChiaHost | None = None
        try:
            host = OpenChiaHost(
                home=get_hermes_home(),
                session_id=duet_id,
                available_tool_names=self._tool_names(agent),
                agent_kwargs_factory=lambda role, identity: self._agent_kwargs_for_episode_under(
                    duet_id,
                    role,
                    identity,
                ),
            )
            agent = host.bind_duet(agent)
        except Exception:
            try:
                agent.close()
            finally:
                if host is not None:
                    host.close()
            raise

        agent._print_fn = lambda *_args, **_kwargs: None

        def thinking(text: str) -> None:
            if not self._agent_running:
                self._spinner_text = text
                if self._app:
                    self._app.invalidate()

        agent.thinking_callback = thinking
        self._background_task_counter += 1
        return _BackgroundDuet(
            duet_id=duet_id,
            ordinal=self._background_task_counter,
            host=host,
            agent=agent,
            conversation_history=list(conversation_history or []),
        )

    def _restore_background_duet(
        self,
        duet_id: str,
        prompt: str,
    ) -> _BackgroundDuet | None:
        """Reopen a persisted background Duet when its displayed ID is supplied."""

        if not duet_id.startswith("duet_") or self._session_db is None:
            return None
        try:
            if self._session_db.get_session(duet_id) is None:
                return None
            history = self._session_db.get_messages_as_conversation(
                duet_id,
                repair_alternation=True,
            )
        except Exception:
            return None
        context = self._create_background_duet(
            duet_id,
            prompt,
            conversation_history=history,
        )
        with self._background_duets_lock:
            self._background_duets[duet_id] = context
        return context

    def _background_duet_for(
        self,
        duet_id: str,
        prompt: str,
    ) -> _BackgroundDuet | None:
        with self._background_duets_lock:
            context = self._background_duets.get(duet_id)
        return context or self._restore_background_duet(duet_id, prompt)

    def _run_background_duet_turn(
        self,
        context: _BackgroundDuet,
        prompt: str,
    ) -> None:
        if context.thread is not None and context.thread.is_alive():
            self._print_openchia(
                f"Background Duet {context.duet_id} is already working. "
                "Start another with /bg PROMPT or wait before sending a follow-up."
            )
            return

        preview = prompt[:60] + ("..." if len(prompt) > 60 else "")
        self._print_openchia(
            f"Background Duet #{context.ordinal} working: \"{preview}\"\n"
            f"Duet ID: {context.duet_id}\n"
            f"Continue it later with: /bg send {context.duet_id} TEXT"
        )

        def produce() -> str:
            try:
                result = context.agent.run_conversation(
                    user_message=prompt,
                    conversation_history=list(context.conversation_history),
                    task_id=f"{context.duet_id}:{uuid.uuid4().hex[:8]}",
                )
                if result and isinstance(result.get("messages"), list):
                    context.conversation_history = list(result["messages"])
                response = result.get("final_response", "") if result else ""
                if not response and result and result.get("error"):
                    response = f"Error: {result['error']}"
                context.last_error = None
                return response
            except Exception as exc:
                context.last_error = str(exc)
                raise

        def done() -> None:
            self._background_tasks.pop(context.duet_id, None)
            context.thread = None
            if not self._agent_running:
                self._spinner_text = ""

        thread = self._side_worker(
            produce,
            name=f"background-duet-{context.duet_id}",
            fail_label=f"Background Duet #{context.ordinal}",
            header_lines=[
                f"  Background Duet #{context.ordinal}",
                f"  Duet ID: {context.duet_id}",
            ],
            title_suffix=f"(background Duet #{context.ordinal})",
            empty_note="  (No response generated)",
            bell=True,
            on_done=done,
        )
        context.thread = thread
        self._background_tasks[context.duet_id] = thread
        thread.start()

    def _start_background_duet(self, prompt: str) -> None:
        if not self._ensure_runtime_credentials():
            self._print_openchia(
                "Cannot start a background Duet without valid model credentials."
            )
            return
        duet_id = (
            f"duet_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        )
        try:
            context = self._create_background_duet(duet_id, prompt)
        except Exception as exc:
            self._print_openchia(f"Background Duet could not start: {exc}")
            return
        with self._background_duets_lock:
            self._background_duets[duet_id] = context
        self._run_background_duet_turn(context, prompt)

    def _list_background_duets(self) -> None:
        with self._background_duets_lock:
            contexts = sorted(
                self._background_duets.values(),
                key=lambda item: item.ordinal,
            )
        if not contexts:
            self._print_openchia(
                "No background Duets are open in this process.\n"
                "Start one with: /bg PROMPT\n"
                "Reopen a persisted one with: /bg send DUET_ID TEXT"
            )
            return
        lines = ["Background Duets:"]
        for context in contexts:
            running = bool(context.thread and context.thread.is_alive())
            try:
                duet_state = context.host.status().get("state", "unknown")
            except Exception:
                duet_state = "unavailable"
            state = "working" if running else "idle"
            if context.last_error:
                state = "error"
            lines.append(
                f"  #{context.ordinal} {context.duet_id} · {state} · {duet_state}"
            )
        lines.append("Continue one with: /bg send DUET_ID TEXT")
        self._print_openchia("\n".join(lines))

    def _close_background_duet(self, duet_id: str) -> None:
        with self._background_duets_lock:
            context = self._background_duets.get(duet_id)
        if context is None:
            self._print_openchia(f"Background Duet not found: {duet_id}")
            return
        if (context.thread and context.thread.is_alive()) or context.host.has_active_work():
            self._print_openchia(
                f"Background Duet {duet_id} is working and remains open."
            )
            return
        try:
            context.agent.close()
        finally:
            context.host.close()
        with self._background_duets_lock:
            self._background_duets.pop(duet_id, None)
        self._print_openchia(
            f"Background Duet {duet_id} closed; its persisted session remains resumable."
        )

    def _process_background_duet_command(self, stripped: str) -> bool:
        payload = stripped[len("/bg") :].strip()
        if not payload or payload.lower() == "list":
            self._list_background_duets()
            return True
        action, _, remainder = payload.partition(" ")
        action_lower = action.lower()
        if action_lower == "new":
            if not remainder.strip():
                self._print_openchia("Usage: /bg [new] PROMPT")
            else:
                self._start_background_duet(remainder.strip())
            return True
        if action_lower == "send":
            duet_id, separator, prompt = remainder.strip().partition(" ")
            if not separator or not prompt.strip():
                self._print_openchia("Usage: /bg send DUET_ID TEXT")
                return True
            if not self._ensure_runtime_credentials():
                self._print_openchia(
                    "Cannot continue a background Duet without valid model credentials."
                )
                return True
            try:
                context = self._background_duet_for(duet_id, prompt.strip())
            except Exception as exc:
                self._print_openchia(
                    f"Background Duet {duet_id} could not reopen: {exc}"
                )
                return True
            if context is None:
                self._print_openchia(f"Background Duet not found: {duet_id}")
            else:
                self._run_background_duet_turn(context, prompt.strip())
            return True
        if action_lower == "status":
            duet_id = remainder.strip()
            if not duet_id:
                self._print_openchia("Usage: /bg status DUET_ID")
                return True
            try:
                context = self._background_duet_for(duet_id, "status")
            except Exception as exc:
                self._print_openchia(
                    f"Background Duet {duet_id} status is unavailable: {exc}"
                )
                return True
            if context is None:
                self._print_openchia(f"Background Duet not found: {duet_id}")
            else:
                self._print_openchia(
                    json.dumps(context.host.status(), indent=2, ensure_ascii=False)
                )
            return True
        if action_lower == "close":
            duet_id = remainder.strip()
            if not duet_id:
                self._print_openchia("Usage: /bg close DUET_ID")
            else:
                self._close_background_duet(duet_id)
            return True
        self._start_background_duet(payload)
        return True

    def process_command(self, cmd: str) -> bool:
        stripped = cmd.strip()
        lower = stripped.lower()
        if lower == "/help" or lower.startswith("/help "):
            self._print_openchia(
                "OpenChia controls:\n"
                "  /episode          inspect the designed Episode workflow as a nested tree\n"
                "  /episode edit     edit one bounded part of that Episode workflow\n"
                "  /episode diff     show exact workflow changes since the last view\n"
                "  /duet             show the current design, validation, and Run state\n"
                "  /design           show drafting stages or failure diagnostics\n"
                "  /queue PROMPT      queue a message for the foreground Duet's next turn\n"
                "  /bg PROMPT         start a separate background Duet\n"
                "  /bg send ID TEXT   continue a background Duet\n"
                "  /bg list           list background Duets open in this process\n"
                "  /bg status ID      inspect a background Duet's state\n"
                "  /bg close ID       close its live context while keeping persisted state\n"
                "  /approve          approve the ready brief or measured Episode workflow\n"
                "  /answer FIELD JSON_VALUE   record an exact answer to an open design field\n"
                "  /review           run or show the advisory design-brief review\n"
                "  /guide TEXT       queue human guidance at the next design boundary\n"
                "  /pause            stop the design pass at its next boundary\n"
                "  /cancel           cancel the design pass at its next boundary\n"
                "  /retry            request another design attempt at the next boundary\n"
                "  /logs             list persisted Run Episode logs\n"
                "  /stop             interrupt the current turn and stop owned background work\n"
                "Session controls: /model, /status, /context, /history, /quit"
            )
            return True
        if lower == "/bg" or lower.startswith("/bg "):
            return self._process_background_duet_command(stripped)
        if lower == "/episode" or lower.startswith("/episode "):
            try:
                return self._process_episode_command(stripped)
            except Exception as exc:
                self._print_openchia(f"Episode workflow not changed: {exc}")
                return True
        if lower in {"/duet", "/openchia"}:
            self._print_openchia(render_openchia_status(self._status(refresh=True)))
            return True
        if lower == "/design":
            self._print_openchia(
                render_creator_diagnostics(self._status(refresh=True))
            )
            return True
        if lower == "/answer" or lower.startswith("/answer "):
            arguments = stripped[len("/answer") :].strip()
            field_path, separator, raw_value = arguments.partition(" ")
            if not separator:
                self._print_openchia("Usage: /answer FIELD JSON_VALUE")
                return True
            try:
                value = json.loads(raw_value)
                answer = self._episode_host().record_human_answer(field_path, value)
                self._print_openchia(
                    f"Recorded human answer for {answer.field_path}: "
                    f"{answer.answer_id.value}"
                )
                self._pending_agent_seed = (
                    "Host event: the human recorded an exact answer for "
                    f"{answer.field_path}. Read duet_status and submit answer artifact "
                    f"{answer.answer_id.value} with duet_answer. Do not paraphrase or "
                    "replace its value."
                )
            except Exception as exc:
                self._print_openchia(f"Human answer not recorded: {exc}")
            self._refresh_openchia()
            return True
        if lower == "/approve":
            if self._openchia_host is None:
                self._print_openchia("Send a message first so the Duet can form a contract.")
                return True
            try:
                receipt = self._openchia_host.approve_current()
                self._print_openchia(
                    f"Approved {receipt.kind}: {receipt.artifact_id.value}"
                )
                if receipt.kind == "creator_contract":
                    self._pending_agent_seed = (
                        "Host event: the human approved the internal design brief. "
                        "Read duet_status, then submit that exact approved artifact with "
                        "episode_creator."
                    )
            except Exception as exc:
                self._print_openchia(f"Approval not recorded: {exc}")
            self._refresh_openchia()
            return True
        if lower == "/review":
            try:
                review = self._episode_host().review_contract()
                self._print_openchia(json.dumps(review, indent=2, ensure_ascii=False))
            except Exception as exc:
                self._print_openchia(f"Contract review unavailable: {exc}")
            self._refresh_openchia()
            return True
        if lower.startswith("/guide"):
            instruction = stripped[len("/guide") :].strip()
            if not instruction:
                self._print_openchia("Usage: /guide TEXT")
                return True
            try:
                decision_id = self._openchia_host.guide_creator(instruction)
                self._print_openchia(
                    f"Guidance queued for the next design boundary: {decision_id.value}"
                )
            except Exception as exc:
                self._print_openchia(f"Guidance not queued: {exc}")
            self._refresh_openchia()
            return True
        decisions = {
            "/pause": DuetMessageKind.PAUSE,
            "/cancel": DuetMessageKind.CANCEL,
        }
        if lower in decisions:
            try:
                decision_id = self._openchia_host.decide_creator(decisions[lower])
                self._print_openchia(
                    f"{decisions[lower].value} queued for the next design boundary: "
                    f"{decision_id.value}"
                )
            except Exception as exc:
                self._print_openchia(f"Decision not queued: {exc}")
            self._refresh_openchia()
            return True
        if lower == "/retry":
            try:
                decision_id, receipt = self._openchia_host.retry_creator()
                if receipt is None:
                    message = (
                        "Retry queued for the next live design boundary: "
                        f"{decision_id.value}"
                    )
                else:
                    message = (
                        "Design retry started: "
                        f"{receipt.execution_id.value} "
                        f"(decision {decision_id.value})"
                    )
                self._print_openchia(message)
            except Exception as exc:
                self._print_openchia(f"Design retry not started: {exc}")
            self._refresh_openchia()
            return True
        if lower == "/logs":
            locations = () if self._openchia_host is None else self._openchia_host.run_log_locations()
            if not locations:
                self._print_openchia("No Run Episode logs have been persisted yet.")
            else:
                self._print_openchia("Run Episode logs:\n" + "\n".join(locations[-10:]))
            return True
        if stripped.startswith("/") and not self._command_available(stripped):
            self._print_openchia(
                "That command is outside the OpenChia Duet/Episode surface. "
                "Use /help for available controls."
            )
            return True
        return super().process_command(cmd)


__all__ = [
    "OpenChiaCLI",
    "episode_configuration_changes",
    "render_creator_diagnostics",
    "render_openchia_status",
]
