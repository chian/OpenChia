"""Classic terminal surface for the OpenChia Duet and Episode system."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from prompt_toolkit.layout import FormattedTextControl, Window
from rich.markup import escape

from agent.duet_contracts import OPENCHIA_CONTROL_PLANE_TOOLS
from agent.openchia_host import OpenChiaHost
from cli import OpenChiaCLIBase
from hermes_constants import get_hermes_home
from openchia_cli.openchia_background import OpenChiaBackgroundDuetsMixin
from openchia_cli.openchia_commands import (
    OpenChiaCommandMixin,
    render_openchia_status as _render_openchia_status,
)


_MISSING_EPISODE_VALUE = "<OPENCHIA: value required>"


class _HostPreparedDuetTurn(str):
    """An ordinary turn whose human instruction is already host-persisted."""



def code_identity_text() -> str:
    """Version plus the exact commit the running code came from.

    ``<display version> · <branch>@<10-char sha>[+dirty]`` from the shared
    provenance resolver (install stamp, then live git); ``version unknown``
    when neither is available, never an exception at banner time.
    """
    try:
        from openchia_cli.version_info import get_version_info

        info = get_version_info()
    except Exception:
        return "version unknown"
    # A tagless checkout's display version is "git.<sha>[.dirty]", which the
    # commit part below already says more precisely.
    parts = [] if info.base_version == "unknown" else [info.display_version]
    if info.commit:
        branch = f"{info.branch}@" if info.branch else ""
        parts.append(f"{branch}{info.commit[:10]}{'+dirty' if info.dirty else ''}")
    return " · ".join(parts) or info.display_version

class OpenChiaCLI(
    OpenChiaCommandMixin,
    OpenChiaBackgroundDuetsMixin,
    OpenChiaCLIBase,
):
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
        "/refiner": "Inspect live or historical Refiner work",
        "/episode": "Browse Architecture and Materialized Specification",
        "/duet": "Show the current design and approval state",
        "/queue": "Manage the foreground Duet's FIFO prompt queue",
        "/bg": "Open and operate independent background Duets",
        "/approve": "Approve the exact current Architecture or refinement",
        "/decline": "Decline the pending refinement proposal",
        "/build": "Start, inspect or continue the build → refine → validate job",
        "/launch": "Select and inspect explicit project/model launch configuration",
        "/run": "Run the admitted materialization or inspect Run evidence",
        "/logs": "Inspect one validated terminal Run audit log",
        "/stop": "Cancel every OpenChia-owned turn, build, and Run",
        "/help": "Show OpenChia controls",
    }
    _inherited_commands = frozenset(
        {
            "/model",
            "/reasoning",
            "/fast",
            "/status",
            "/context",
            "/history",
            "/save",
            "/title",
            "/compress",
            "/config",
            "/profile",
            "/statusbar",
            "/timestamps",
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
            "/exit",  # the base CLI's alias of /quit (openchia_cli/commands.py)
        }
    )

    def __init__(self, **kwargs: Any) -> None:
        self._openchia_host: OpenChiaHost | None = None
        self._openchia_status_cache: dict[str, Any] | None = None
        self._openchia_status_at = 0.0
        self._openchia_tearing_down = False
        super().__init__(**kwargs)
        self.busy_input_mode = "queue"
        self._initialize_background_duets()

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
        from openchia_cli.commands import COMMANDS

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
        from openchia_cli.cli_agent_setup_mixin import _current_runtime

        runtime = _current_runtime(self)
        return {
            "model": self.model,
            "api_key": runtime.get("api_key"),
            "base_url": runtime.get("base_url"),
            "provider": runtime.get("provider"),
            "requested_provider": runtime.get("requested_provider"),
            "api_mode": runtime.get("api_mode"),
            "auth_mode": runtime.get("auth_mode"),
            "cache_scope": runtime.get("cache_scope"),
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
        host = self._ensure_openchia_host()
        self._openchia_status_cache = None
        return host.bind_duet(agent)

    @staticmethod
    def _strict_run_executor_factory() -> Any:
        """systemd on a Linux host, otherwise a container (Docker/Rancher/Podman);
        ``OPENCHIA_RUN_EXECUTOR`` forces one, ``OPENCHIA_CONTAINER_IMAGE`` picks the image."""
        from episode_runtime import make_run_executor_factory

        repository_root = Path(__file__).resolve().parents[1]
        return make_run_executor_factory(repository_root=repository_root)

    def _ensure_openchia_host(self) -> OpenChiaHost:
        if self._openchia_host is None:
            self._openchia_host = OpenChiaHost(
                home=get_hermes_home(),
                session_id=self.session_id,
                available_tool_names=self._tool_names(None),
                agent_kwargs_factory=self._agent_kwargs_for_episode,
                run_executor_factory=self._strict_run_executor_factory(),
            )
        return self._openchia_host

    @staticmethod
    def _agent_init_failure_message(error: BaseException) -> str:
        from openchia_cli.cli_chat_error_copy import (
            openchia_duet_init_failure_message,
        )

        return openchia_duet_init_failure_message(error)

    def show_banner(self) -> None:
        """Show the OpenChia work path without inherited agent-workflow framing."""

        self.console.clear()
        self._console_print(
            f"[bold #8fb9a8]OPENCHIA[/]  human + LLM = Duet   [dim]{code_identity_text()}[/]"
        )
        self._console_print()
        self._console_print("  [DUET] <----> [WORKFLOW ARCHITECTURE]")
        self._console_print("                       | approve + build")
        self._console_print("                       v")
        self._console_print("              [MATERIALIZED SPECIFICATION]")
        self._console_print("                       | explicit run")
        self._console_print("                       v")
        self._console_print("                   [RUN EVIDENCE]")
        self._console_print()

    def _tui_welcome_branding(self, welcome_skin: Any) -> tuple[str, str]:
        color = "#8fb9a8"
        if welcome_skin is not None:
            color = welcome_skin.get_color("banner_text", color)
        return (
            f"OpenChia Duet ready ({code_identity_text()}). Describe the outcome, "
            "then use /duet to inspect or /help for controls.",
            color,
        )

    def _print_random_tip(self) -> None:
        self._console_print(
            "[dim]Use /episode to move between the Duet-owned Architecture and its exact materialization.[/]"
        )

    def _tui_background_ui_active(self) -> bool:
        host_work = bool(
            self._openchia_host and self._openchia_host.has_active_work()
        )
        return host_work or self._background_ui_active()

    def _status(self, *, refresh: bool = False) -> dict[str, Any] | None:
        host = self._openchia_host
        if (
            host is None
            and getattr(self, "_resumed", False)
            and getattr(self, "conversation_history", None)
        ):
            host = self._ensure_openchia_host()
        if host is None:
            return None
        now = time.monotonic()
        if (
            refresh
            or self._openchia_status_cache is None
            or now - self._openchia_status_at >= 0.5
        ):
            status = host.status()
            self._openchia_status_cache = status
            self._openchia_status_at = now
        return self._openchia_status_cache

    def _panel_text(self) -> str:
        try:
            return _render_openchia_status(self._status())
        except Exception as exc:
            return (
                f"OpenChia status unavailable: {type(exc).__name__}\n"
                "/duet · /help"
            )

    def _get_extra_tui_widgets(self) -> list[Any]:
        return [
            Window(
                FormattedTextControl(self._panel_text),
                height=2,
                style="class:openchia.status",
            )
        ]

    def _build_tui_layout_children(self, **kwargs: Any) -> list[Any]:
        """Detach the inherited subagent monitor before composing OpenChia chrome."""

        self._subagent_monitor = None
        self._subagent_dock_widget = None
        return super()._build_tui_layout_children(**kwargs)

    def _tui_build_key_bindings(self) -> Any:
        """Retain base editing keys without inherited subagent-monitor controls."""

        bindings = super()._tui_build_key_bindings()
        blocked = {
            ("c-t",),
            ("f6",),
            ("c-r",),
            ("f7",),
        }

        def normalized(binding: Any) -> tuple[str, ...]:
            return tuple(
                str(getattr(key, "value", key)).lower()
                for key in binding.keys
            )

        bindings.bindings[:] = [
            binding
            for binding in bindings.bindings
            if normalized(binding) not in blocked
        ]
        return bindings

    def _get_status_bar_snapshot(self) -> dict[str, Any]:
        snapshot = super()._get_status_bar_snapshot()
        snapshot["active_background_subagents"] = 0
        return snapshot

    def _tui_placeholder_text(self) -> str:
        if self._agent_running:
            return "message=queued · /episode · /queue · /bg · /stop"
        return super()._tui_placeholder_text()

    def _tui_enter_while_busy(
        self,
        text: str,
        images: list[Any],
        payload: Any,
    ) -> None:
        """FIFO every ordinary busy submission for a later complete Duet turn."""

        from cli import _cprint

        self._pending_input.put(payload)
        preview = (
            text
            if text
            else f"[{len(images)} image{'s' if len(images) != 1 else ''} attached]"
        )
        suffix = "..." if len(preview) > 80 else ""
        _cprint(f"  Queued for the next Duet turn: {preview[:80]}{suffix}")

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
        return self._ensure_openchia_host()

    @staticmethod
    def _persisted_instruction_turn(
        prompt: str,
        notes: tuple[dict[str, Any], ...],
    ) -> _HostPreparedDuetTurn:
        if len(notes) != 2:
            raise RuntimeError(
                "a stable global instruction must have two persisted layer candidates"
            )
        candidates: list[tuple[str, str, str]] = []
        for note in notes:
            if not isinstance(note, Mapping) or note.get("body") != prompt:
                raise RuntimeError(
                    "global instruction persistence returned another human instruction"
                )
            note_id = note.get("note_id")
            target = note.get("target")
            if not isinstance(note_id, str) or not isinstance(target, Mapping):
                raise RuntimeError(
                    "global instruction persistence omitted its exact identity"
                )
            target_id = target.get("target_id")
            layer = target.get("layer")
            if not isinstance(target_id, str) or not isinstance(layer, str):
                raise RuntimeError(
                    "global instruction persistence omitted its target identity"
                )
            candidates.append((layer, note_id, target_id))
        if {value[0] for value in candidates} != {
            "workflow_semantics",
            "materialization_implementation",
        }:
            raise RuntimeError(
                "global instruction candidates do not cover both refinement layers"
            )
        candidate_lines = "\n".join(
            f"- {layer}: note_id={note_id}; target_id={target_id}"
            for layer, note_id, target_id in sorted(candidates)
        )
        return _HostPreparedDuetTurn(
            "A new human instruction for the current built Target Workflow has been "
            "persisted as these exact refinement candidates:\n"
            f"{candidate_lines}\n"
            "Read the exact saved instruction with episode_workspace_read "
            "using each note_id. Select the layer addressed by the human "
            "instruction and continue through the normal Duet refinement "
            "conversation."
        )

    def _prepare_human_duet_turn(
        self,
        host: OpenChiaHost,
        message: Any,
    ) -> Any:
        if isinstance(message, _HostPreparedDuetTurn) or not isinstance(
            message,
            str,
        ):
            return message
        key = f"global_instruction_{uuid.uuid4().hex}"
        notes = host.record_global_instruction(message, key)
        if not notes:
            return message
        return self._persisted_instruction_turn(message, notes)

    def chat(
        self,
        message: Any,
        images: list | None = None,
        voice_input: bool = False,
    ) -> str | None:
        """Route stable-build human turns through durable Duet instructions."""

        try:
            message = self._prepare_human_duet_turn(
                self._ensure_openchia_host(),
                message,
            )
        except Exception as exc:
            self._print_openchia(
                f"Human instruction was not persisted for the Duet: {exc}"
            )
            return None
        return super().chat(message, images=images, voice_input=voice_input)

    @staticmethod
    def _json_value(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _render_workspace_changes(
        self,
        label: str,
        from_identity: object,
        to_identity: object,
        changes: tuple[dict[str, Any], ...],
    ) -> str:
        if not changes:
            return f"{label} changes {from_identity} -> {to_identity}: none"
        markers = {"added": "+", "removed": "-", "changed": "~"}
        lines = [f"{label} changes {from_identity} -> {to_identity}:"]
        for change in changes:
            lines.append(f"  {markers[change['kind']]} {change['path']}")
            if "before" in change:
                lines.append(f"      before: {self._json_value(change['before'])}")
            if "after" in change:
                lines.append(f"      after:  {self._json_value(change['after'])}")
        return "\n".join(lines)

    @staticmethod
    def _workspace_followup_prompt(
        note_ids: tuple[str, ...],
        *,
        baseline_id: str | None,
    ) -> _HostPreparedDuetTurn:
        joined = ", ".join(note_ids)
        if baseline_id is None:
            action = (
                "Use these human notes while completing the Workflow "
                "Architecture, and submit the complete Architecture when it "
                "is ready for approval."
            )
        else:
            action = (
                "Use these human notes to propose the corresponding successor "
                "Architecture or implementation refinement against baseline "
                f"{baseline_id}."
            )
        return _HostPreparedDuetTurn(
            "I saved Episode Workspace notes with these exact IDs: "
            f"{joined}. Read each exact saved note with "
            f"episode_workspace_read using note_id. {action}"
        )

    def _open_episode_workspace(
        self,
        *,
        host: OpenChiaHost | None = None,
        edit_architecture: bool = False,
        duet_turn_active: bool | None = None,
        enqueue_followup: Any = None,
    ) -> None:
        active_host = self._episode_host() if host is None else host
        if duet_turn_active is None:
            duet_turn_active = bool(host is None and self._agent_running)
        workspace = active_host.episode_workspace_snapshot()
        architecture = workspace["architecture_snapshot"]
        architecture_changed_paths = tuple(
            workspace.get("changed_paths", ())
        )
        materialized = workspace["materialized_snapshot"]
        materialized_changed_paths = tuple(
            workspace.get("materialized_changed_paths", ())
        )
        from openchia_cli.openchia_episode_editor import open_episode_workspace

        result = open_episode_workspace(
            architecture_snapshot=architecture,
            materialized_snapshot=materialized,
            notes=workspace["notes"],
            save_note=active_host.record_workspace_note,
            notes_enabled=bool(workspace.get("notes_enabled", True)),
            architecture_changed_paths=architecture_changed_paths,
            materialized_changed_paths=materialized_changed_paths,
            edit_architecture=(edit_architecture and not duet_turn_active),
            architecture_edit_notice=(
                "Duet turn active: Architecture edits wait; browsing remains available."
                if edit_architecture and duet_turn_active
                else None
            ),
            missing_value=_MISSING_EPISODE_VALUE,
        )
        if result.architecture_configuration is not None:
            try:
                receipt = active_host.record_architecture_revision(
                    candidate_workflow_architecture=(
                        result.architecture_configuration
                    ),
                    expected_artifact_id=(
                        result.expected_architecture_artifact_id
                    ),
                    expected_content_hash=(
                        result.expected_architecture_content_hash
                    ),
                    expected_revision=result.expected_architecture_revision,
                    human_note_ids=result.saved_note_ids,
                )
            except Exception as exc:
                self._print_openchia(
                    f"Architecture replacement was rejected: {exc}"
                )
            else:
                self._print_openchia(
                    f"Saved Workflow Architecture revision {receipt['revision']} "
                    f"({receipt['artifact_id']})."
                )
        if result.saved_note_ids:
            prompt = self._workspace_followup_prompt(
                result.saved_note_ids,
                baseline_id=workspace["baseline_id"],
            )
            if enqueue_followup is None:
                self._pending_input.put(prompt)
                self._print_openchia(
                    f"Queued one Duet turn for {len(result.saved_note_ids)} "
                    "saved workspace note(s)."
                )
            else:
                enqueue_followup(prompt)
        self._refresh_openchia()

    def _show_episode_changes(
        self,
        *,
        host: OpenChiaHost | None = None,
    ) -> None:
        active_host = self._episode_host() if host is None else host
        workspace = active_host.episode_workspace_snapshot()
        sections = [
            self._render_workspace_changes(
                "Architecture",
                workspace.get("architecture_change_from"),
                workspace.get("architecture_change_to"),
                tuple(workspace.get("architecture_changes", ())),
            )
        ]
        materialized = workspace["materialized_snapshot"]
        if materialized is None:
            sections.append("Materialized Specification: not available")
        else:
            sections.append(
                self._render_workspace_changes(
                    "Materialized Specification",
                    workspace.get("materialized_change_from"),
                    workspace.get("materialized_change_to"),
                    tuple(workspace.get("materialized_changes", ())),
                )
            )
        self._print_openchia("\n\n".join(sections))

    @staticmethod
    def _is_episode_command(command: str) -> bool:
        stripped = command.strip()
        lower = stripped.lower()
        return lower == "/episode" or lower.startswith("/episode ")

    @staticmethod
    def _is_background_episode_command(command: str) -> bool:
        parts = command.strip().lower().split()
        return (
            len(parts) >= 3
            and parts[0] == "/bg"
            and parts[1].startswith("duet_")
            and parts[2] == "episode"
        )

    def _tui_enter_inline_command(
        self,
        event: Any,
        text: str,
        has_images: bool,
    ) -> bool:
        """Dispatch OpenChia commands now; no slash input enters a Duet turn."""

        is_workspace = (
            self._is_episode_command(text)
            or self._is_background_episode_command(text)
        )
        if is_workspace:
            from prompt_toolkit.application import run_in_terminal

            event.app.current_buffer.reset(append_to_history=True)
            run_in_terminal(
                lambda: self.process_command(text),
                in_executor=True,
            )
            event.app.invalidate()
            return True
        if not text.strip().startswith("/"):
            return False
        if super()._tui_enter_inline_command(event, text, has_images):
            return True
        if not self._agent_running:
            return False
        try:
            keep_running = self.process_command(text)
            if not keep_running:
                self._should_exit = True
                if event.app.is_running:
                    event.app.exit()
        except Exception as exc:
            self._print_openchia(f"Command failed: {exc}")
        event.app.current_buffer.reset(append_to_history=True)
        event.app.invalidate()
        return True

    def _tui_shutdown(self) -> None:
        """Close OpenChia-owned Duet hosts before inherited CLI teardown."""

        foreground_host = self._openchia_host
        if foreground_host is not None:
            for cancel in (
                foreground_host.cancel_run,
                foreground_host.cancel_build,
            ):
                try:
                    cancel()
                except Exception:
                    pass
        self._close_owned_background_duets()
        try:
            super()._tui_shutdown()
        finally:
            self._openchia_host = None
            if foreground_host is not None:
                try:
                    foreground_host.close()
                except Exception:
                    pass


__all__ = [
    "OpenChiaCLI",
]
