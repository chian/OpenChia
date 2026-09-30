"""Classic terminal surface for the OpenChia Duet and Episode system."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import time
from typing import Any

from prompt_toolkit.layout import FormattedTextControl, Window
from rich.markup import escape

from agent.duet_contracts import DuetMessageKind
from agent.episode_blueprints import CREATION_BLUEPRINT_FIELDS
from agent.openchia_host import OpenChiaHost
from cli import HermesCLI
from hermes_constants import get_hermes_home


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

    if status.get("creator_episode_id"):
        creator_state = str(progress.get("state") or state)
        candidate = int(progress.get("candidate_revision") or 0)
        credit = progress.get("method_credit")
        detail = f"candidate {candidate}"
        if credit is not None:
            detail += f" · credit {credit}"
        commands = "/approve · /guide · /pause · /logs" if state == "awaiting_workflow_approval" else "/guide · /pause · /logs"
        return f"Creator · {creator_state} · {detail}\n{commands}"

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
            "/episode · /review · /approve"
        )

    labels = {
        "goal": "intended outcome",
        "creator_contract.design_instructions": "Creator design instructions",
        "creator_contract.design_scope": "Creator design scope",
        "result": "concrete result",
        "unit": "repeatable cycle",
        "progress": "success evidence",
        "stopping": "stopping behavior",
        "execution_capability_names": "needed tools",
        "creator_contract": "Creator design scope",
        "deliverable": "deliverable boundary",
        "safety_bounds": "safety limits",
    }
    focus = labels.get(deficits[0], deficits[0]) if deficits else "contract coherence"
    return (
        f"Duet · shaping contract · {field_count}/{len(CREATION_BLUEPRINT_FIELDS)} fields · gap: {focus}\n"
        "/episode · /help"
    )


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
        "/episode": "Show or directly edit the Creator Episode configuration",
        "/duet": "Show closed Duet, Creator, and Run state",
        "/openchia": "Alias for /duet",
        "/approve": "Approve the ready contract or measured workflow",
        "/answer": "Record an exact human answer to an open contract field",
        "/review": "Run or show the advisory shadow contract review",
        "/guide": "Queue human guidance at the next Creator boundary",
        "/pause": "Stop the Creator at its next boundary",
        "/cancel": "Cancel the Creator at its next boundary",
        "/retry": "Request another design attempt at the next boundary",
        "/logs": "List persisted Run Episode logs",
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
        super().__init__(**kwargs)

    @staticmethod
    def _tool_names(agent: Any) -> tuple[str, ...]:
        import model_tools

        excluded = {
            "creator_log_read",
            "delegate_task",
            "duet_answer",
            "duet_contract_patch",
            "duet_decision",
            "duet_status",
            "episode_creator",
            "episode_progress",
            "tool_call",
            "tool_search",
            "workflow_candidate",
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

    def _agent_kwargs_for_episode(self, role: str, identity: str) -> dict[str, Any]:
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
            "session_id": f"{self.session_id}-{role}-{identity[-12:]}",
            "parent_session_id": self.session_id,
            "platform": "openchia",
            "side_agent": True,
        }

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

    def show_banner(self) -> None:
        """Show the OpenChia work path without inherited agent-workflow framing."""

        self.console.clear()
        self._console_print("[bold #8fb9a8]OPENCHIA[/]  human + LLM = Duet")
        self._console_print()
        self._console_print("  [DUET] -- approved contract --> [CREATOR]")
        self._console_print("     ^                              |")
        self._console_print("     | closed progress              | frozen design")
        self._console_print("     +-------------------------- [RUN]")
        self._console_print("                         typed measures + log")
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
            "[dim]The Duet specifies; the Creator experiments; Run Episodes return typed progress and logs.[/]"
        )

    def _tui_background_ui_active(self) -> bool:
        return bool(self._openchia_host and self._openchia_host.has_active_work())

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
    def _edit_json_document(document: dict[str, Any]) -> dict[str, Any] | None:
        editor = (
            os.environ.get("VISUAL")
            or os.environ.get("EDITOR")
            or ("notepad" if os.name == "nt" else "nano")
        )
        descriptor, path = tempfile.mkstemp(
            suffix=".json",
            prefix="openchia_episode_",
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            try:
                return_code = subprocess.call([*shlex.split(editor), path])
            except Exception:
                return_code = subprocess.call(
                    f"{editor} {shlex.quote(path)}",
                    shell=True,
                )
            if return_code != 0:
                raise RuntimeError(f"editor exited with status {return_code}")
            with open(path, "r", encoding="utf-8-sig") as handle:
                edited = handle.read().strip()
            if not edited:
                return None
            value = json.loads(edited)
            if not isinstance(value, dict):
                raise ValueError("Episode editor document must remain a JSON object")
            return value
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _show_episode_configuration(self) -> None:
        configuration = self._episode_host().episode_configuration()
        capabilities = configuration.pop("allowed_capabilities", [])
        configuration["allowed_capability_count"] = len(capabilities)
        configuration["capabilities_command"] = "/episode capabilities"
        self._print_openchia(json.dumps(configuration, indent=2, ensure_ascii=False))

    def _process_episode_command(self, stripped: str) -> bool:
        remainder = stripped[len("/episode") :].strip()
        action, _, arguments = remainder.partition(" ")
        action = action.lower() or "show"
        host = self._episode_host()
        if action in {"show", "status"}:
            self._show_episode_configuration()
            return True
        if action == "edit":
            revision, document = host.episode_editor_document()
            edited = self._edit_json_document(document)
            if edited is None or edited == document:
                self._print_openchia("Episode configuration unchanged.")
                return True
            draft = host.replace_episode_configuration(
                edited,
                expected_revision=revision,
            )
            self._print_openchia(
                f"Episode configuration saved as revision {draft['revision']}; "
                f"ready={draft['ready']}."
            )
            self._refresh_openchia()
            return True
        if action == "set":
            field_path, separator, raw_value = arguments.strip().partition(" ")
            if not separator:
                raise ValueError("Usage: /episode set FIELD JSON_VALUE")
            value = json.loads(raw_value)
            draft = host.update_episode_configuration(field_path, value=value)
            self._print_openchia(
                f"Set {field_path}; Episode configuration is revision "
                f"{draft['revision']} (ready={draft['ready']})."
            )
            self._refresh_openchia()
            return True
        if action in {"unset", "remove"}:
            field_path = arguments.strip()
            if not field_path:
                raise ValueError("Usage: /episode unset FIELD")
            draft = host.update_episode_configuration(field_path, remove=True)
            self._print_openchia(
                f"Removed {field_path}; Episode configuration is revision "
                f"{draft['revision']} (ready={draft['ready']})."
            )
            self._refresh_openchia()
            return True
        if action == "capabilities":
            names = host.episode_configuration()["allowed_capabilities"]
            self._print_openchia("Assignable Episode capabilities:\n" + "\n".join(names))
            return True
        raise ValueError(
            "Usage: /episode [show|edit|set FIELD JSON_VALUE|unset FIELD|capabilities]"
        )

    def process_command(self, cmd: str) -> bool:
        stripped = cmd.strip()
        lower = stripped.lower()
        if lower == "/help" or lower.startswith("/help "):
            self._print_openchia(
                "OpenChia controls:\n"
                "  /episode          show the complete editable Creator configuration\n"
                "  /episode edit     edit the complete configuration as JSON\n"
                "  /episode set FIELD JSON_VALUE   set one field or dotted path\n"
                "  /episode unset FIELD            remove one field or dotted path\n"
                "  /duet             show the closed Duet -> Creator -> Run state\n"
                "  /approve          approve the ready contract or measured workflow\n"
                "  /answer FIELD JSON_VALUE   record an exact human answer to an open field\n"
                "  /review           run or show the advisory shadow contract review\n"
                "  /guide TEXT       queue human guidance at the next Creator boundary\n"
                "  /pause            stop the Creator at its next boundary\n"
                "  /cancel           cancel the Creator at its next boundary\n"
                "  /retry            request another design attempt at the next boundary\n"
                "  /logs             list persisted Run Episode logs\n"
                "Session controls: /model, /status, /context, /history, /quit"
            )
            return True
        if lower == "/episode" or lower.startswith("/episode "):
            try:
                return self._process_episode_command(stripped)
            except Exception as exc:
                self._print_openchia(f"Episode configuration not changed: {exc}")
                return True
        if lower in {"/duet", "/openchia"}:
            self._print_openchia(render_openchia_status(self._status(refresh=True)))
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
                        "Host event: the human approved the current Creator contract. "
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
                    f"Guidance queued for the next Creator boundary: {decision_id.value}"
                )
            except Exception as exc:
                self._print_openchia(f"Guidance not queued: {exc}")
            self._refresh_openchia()
            return True
        decisions = {
            "/pause": DuetMessageKind.PAUSE,
            "/cancel": DuetMessageKind.CANCEL,
            "/retry": DuetMessageKind.RETRY,
        }
        if lower in decisions:
            try:
                decision_id = self._openchia_host.decide_creator(decisions[lower])
                self._print_openchia(
                    f"{decisions[lower].value} queued for the next Creator boundary: "
                    f"{decision_id.value}"
                )
            except Exception as exc:
                self._print_openchia(f"Decision not queued: {exc}")
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


__all__ = ["OpenChiaCLI", "render_openchia_status"]
