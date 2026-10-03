"""Table-driven OpenChia slash commands and compact status rendering."""

from __future__ import annotations

import json
from typing import Any


_HELP_TEXT = (
    "OpenChia controls:\n"
    "  /episode          browse Architecture and Materialized Specification\n"
    "  /episode edit     edit the mutable Workflow Architecture\n"
    "  /episode diff     show stable changes in both Workspace views\n"
    "  /duet             show the current design and approval state\n"
    "  /queue [PROMPT|add PROMPT|list|edit N PROMPT|rm N|move A B|clear]\n"
    "                    manage the foreground Duet's FIFO prompt queue\n"
    "  /bg new PROMPT     start a separate background Duet\n"
    "  /bg list           list background Duets open in this process\n"
    "  /bg DUET_ID send TEXT   FIFO-queue a turn for that background Duet\n"
    "  /bg DUET_ID episode [edit|diff] browse or edit its Workspace\n"
    "  /bg DUET_ID status|approve|decline inspect or decide authority\n"
    "  /bg DUET_ID build [status] materialize or inspect its build\n"
    "  /bg DUET_ID run [status] run or inspect its materialization\n"
    "  /bg DUET_ID evidence [RUN_ID] inspect terminal evidence\n"
    "  /bg DUET_ID logs [RUN_ID] inspect the terminal audit log\n"
    "  /bg DUET_ID cancel|close cancel owned work or close its context\n"
    "  /approve          approve the current Architecture or refinement\n"
    "  /decline          reject the pending refinement and keep the baseline\n"
    "  /build            start a fresh materialization attempt\n"
    "  /build status     inspect the current materialization attempt\n"
    "  /launch load FILE select project/model configuration for future launches\n"
    "  /launch [status|calls] inspect selected settings and actual routing receipts\n"
    "  /launch preview   resolve and display settings before launching (no model call)\n"
    "  /launch reload    reread the selected file for future launches\n"
    "  /launch reuse ID  reuse a recorded launch's resolved model settings\n"
    "  /bg DUET_ID launch ... configure that background Duet independently\n"
    "  /run              explicitly run the admitted materialization\n"
    "  /run status       inspect the current Run state\n"
    "  /run evidence [ID] inspect validated terminal Run evidence\n"
    "  /logs [RUN_ID]    inspect a validated terminal Run audit log\n"
    "  /stop             cancel every OpenChia-owned turn, build, and Run\n"
    "  /help             show this complete command list\n"
    "Canonical session controls:\n"
    "  /model /reasoning /fast /status /context /history /save /title\n"
    "  /compress /config /profile /statusbar /timestamps /focus /skin\n"
    "  /indicator /verbose /usage /copy /paste /image /redraw /quit"
)


def _elapsed_text(seconds: object) -> str:
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        total = 0
    minutes, remainder = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {remainder}s"
    return f"{remainder}s"


def render_openchia_status(status: dict[str, Any] | None) -> str:
    """Render the current authority and materialization heads in two lines."""

    if not status:
        return "Duet · describe the outcome you want\n/episode · /help"
    architecture = status.get("episode_architecture") or {}
    duet_state = str(status.get("state") or "designing")
    if not architecture:
        return f"Duet · {duet_state}\n/episode · /help"
    revision = int(architecture.get("revision") or 0)
    pending = architecture.get("pending_refinement")
    if pending:
        kind = str(pending.get("change_kind") or "refinement")
        first = f"Architecture r{revision} · {kind} awaits human decision"
        return first + "\n/episode · /approve · /decline"
    build = status.get("build") or {}
    build_state = str(build.get("state") or "not_started")
    progress = build.get("progress") or {}
    counts = progress.get("counts") or {}
    run = status.get("run") or {}
    run_state = str(run.get("state") or "not_started")
    if build_state in {"starting", "building", "cancel_requested"}:
        emitted = int(counts.get("episodes_emitted") or 0)
        total = int(counts.get("episodes_total") or 0)
        stage = str(progress.get("stage") or build_state)
        model_wait = build.get("model_wait") or {}
        wait_text = ""
        if model_wait.get("active"):
            elapsed = _elapsed_text(model_wait.get("elapsed_seconds"))
            if model_wait.get("response_seen"):
                wait_text = f"reply {elapsed} ago"
            else:
                wait_text = f"wait {elapsed}"
        return (
            f"Architecture r{revision} · approved\n"
            f"Builder · /stop"
            f"{' · ' + wait_text if wait_text else ''}"
            f" · {emitted}/{total} · {stage}"
        )
    if build_state == "materialized":
        if run_state in {"starting", "running", "cancel_requested"}:
            return (
                f"Architecture r{revision} · approved\n"
                f"Run · {run_state} · /run status · /stop"
            )
        if run_state in {"succeeded", "failed", "cancelled"}:
            return (
                f"Architecture r{revision} · approved\n"
                f"Run · {run_state} · /run evidence · /logs"
            )
        if run_state in {"cancelled_before_claim", "host_error"}:
            return (
                f"Architecture r{revision} · approved\n"
                f"Run · {run_state} · /run status"
            )
        return (
            f"Architecture r{revision} · approved\n"
            "Materialized Specification ready · /episode · /run"
        )
    if build_state == "blocked":
        deficits = int(counts.get("blocking_deficits") or 0)
        return (
            f"Architecture r{revision} · approved\n"
            f"Build {build_state} · {deficits} deficits · /episode · /build"
        )
    if build_state in {"host_error", "cancelled"}:
        return (
            f"Architecture r{revision} · approved\n"
            f"Build {build_state} · /build status"
        )
    if duet_state == "awaiting_workflow_approval":
        return f"Architecture r{revision} · ready\n/episode · /approve"
    if duet_state == "sealed":
        return f"Architecture r{revision} · approved\n/build · /episode"
    deficit_count = len(architecture.get("validation_deficits") or ())
    suffix = f" · {deficit_count} deficits" if deficit_count else ""
    return f"Architecture r{revision} · {duet_state}{suffix}\n/episode"


class OpenChiaCommandMixin:
    """Dispatch the OpenChia command vocabulary through one handler table."""

    _openchia_command_dispatch = {
        "/help": "_handle_openchia_help",
        "/bg": "_handle_openchia_background",
        "/episode": "_handle_openchia_episode",
        "/duet": "_handle_openchia_duet",
        "/build": "_handle_openchia_build",
        "/launch": "_handle_openchia_launch",
        "/run": "_handle_openchia_run",
        "/logs": "_handle_openchia_logs",
        "/approve": "_handle_openchia_approve",
        "/decline": "_handle_openchia_decline",
        "/stop": "_handle_openchia_stop",
    }
    _run_command_dispatch = {
        "": "_run_start",
        "status": "_run_show_status",
        "evidence": "_run_show_evidence",
    }

    @staticmethod
    def _command_arguments(stripped: str) -> str:
        _command, _separator, arguments = stripped.partition(" ")
        return arguments.strip()

    def _handle_openchia_help(self, stripped: str) -> bool:
        self._print_openchia(_HELP_TEXT)
        return True

    def _handle_openchia_background(self, stripped: str) -> bool:
        return self._process_background_duet_command(stripped)

    def _handle_openchia_episode(self, stripped: str) -> bool:
        try:
            return self._process_episode_command(stripped)
        except Exception as exc:
            self._print_openchia(f"Episode Workspace unavailable: {exc}")
            return True

    def _process_episode_command(self, stripped: str) -> bool:
        remainder = stripped[len("/episode") :].strip()
        if not remainder:
            self._open_episode_workspace()
            return True
        action, _, arguments = remainder.partition(" ")
        action = action.lower()
        if arguments:
            raise ValueError("Usage: /episode [edit|diff]")
        if action == "diff":
            self._show_episode_changes()
            return True
        if action == "edit":
            self._open_episode_workspace(edit_architecture=True)
            return True
        raise ValueError("Usage: /episode [edit|diff]")

    def _handle_openchia_duet(self, stripped: str) -> bool:
        if self._command_arguments(stripped):
            self._print_openchia("Usage: /duet")
            return True
        self._ensure_openchia_host()
        self._print_openchia(
            render_openchia_status(self._status(refresh=True))
        )
        return True

    def _handle_openchia_build(self, stripped: str) -> bool:
        action = self._command_arguments(stripped).lower()
        if action == "status":
            try:
                self._print_openchia(
                    json.dumps(
                        self._episode_host().build_status(),
                        indent=2,
                        ensure_ascii=False,
                    )
                )
            except Exception as exc:
                self._print_openchia(
                    f"EpisodeBuilder status unavailable: {exc}"
                )
            return True
        if action:
            self._print_openchia("Usage: /build [status]")
            return True
        try:
            build = self._episode_host().start_build()
            attempt = build.get("build_attempt_id") or "pending"
            self._print_openchia(
                "EpisodeBuilder started fresh request "
                f"{build['build_request_id']} (attempt {attempt}). "
                "Use /build status to inspect progress."
            )
        except Exception as exc:
            self._print_openchia(f"EpisodeBuilder did not start: {exc}")
        self._refresh_openchia()
        return True

    def _handle_openchia_launch(self, stripped: str) -> bool:
        from openchia_cli.episode_launch_command import launch_command
        try:
            result = launch_command(self._episode_host(), self._command_arguments(stripped))
            self._print_openchia(json.dumps(result, indent=2, ensure_ascii=False))
        except Exception as exc:
            self._print_openchia(f"Launch configuration: {exc}")
        return True

    def _run_start(self, parts: tuple[str, ...]) -> None:
        if parts:
            self._print_openchia("Usage: /run [status|evidence [RUN_ID]]")
            return
        try:
            run = self._episode_host().start_run()
            self._print_openchia(
                f"Run {run['run_id']} started from admitted build "
                f"{run['build_receipt_id']}. Use /run status to inspect it."
            )
        except Exception as exc:
            self._print_openchia(f"Run did not start: {exc}")
        self._refresh_openchia()

    def _run_show_status(self, parts: tuple[str, ...]) -> None:
        if len(parts) != 1:
            self._print_openchia("Usage: /run [status|evidence [RUN_ID]]")
            return
        try:
            status = self._episode_host().run_status()
            self._print_openchia(
                json.dumps(status, indent=2, ensure_ascii=False)
            )
        except Exception as exc:
            self._print_openchia(f"Run status unavailable: {exc}")

    def _run_show_evidence(self, parts: tuple[str, ...]) -> None:
        if len(parts) > 2:
            self._print_openchia("Usage: /run [status|evidence [RUN_ID]]")
            return
        run_id = parts[1] if len(parts) == 2 else None
        try:
            evidence = self._episode_host().run_evidence(run_id)
            if evidence is None:
                self._print_openchia(
                    "No validated terminal Run evidence is available."
                )
            else:
                self._print_openchia(
                    json.dumps(evidence, indent=2, ensure_ascii=False)
                )
        except Exception as exc:
            self._print_openchia(f"Run evidence unavailable: {exc}")

    def _handle_openchia_run(self, stripped: str) -> bool:
        parts = tuple(self._command_arguments(stripped).split())
        action = parts[0].lower() if parts else ""
        handler_name = self._run_command_dispatch.get(action)
        if handler_name is None:
            self._print_openchia("Usage: /run [status|evidence [RUN_ID]]")
            return True
        getattr(self, handler_name)(parts)
        return True

    def _handle_openchia_logs(self, stripped: str) -> bool:
        run_id = self._command_arguments(stripped) or None
        if run_id is not None and len(run_id.split()) != 1:
            self._print_openchia("Usage: /logs [RUN_ID]")
            return True
        try:
            audit_log = self._episode_host().run_audit_log(run_id)
            if audit_log is None:
                self._print_openchia(
                    "No validated terminal Run audit log is available."
                )
            else:
                self._print_openchia(
                    json.dumps(audit_log, indent=2, ensure_ascii=False)
                )
        except Exception as exc:
            self._print_openchia(f"Run audit log unavailable: {exc}")
        return True

    def _handle_openchia_approve(self, stripped: str) -> bool:
        if self._command_arguments(stripped):
            self._print_openchia("Usage: /approve")
            return True
        try:
            receipt = self._episode_host().approve_current()
            self._print_openchia(
                f"Approved {receipt.kind} artifact "
                f"{receipt.artifact_id.value} under approval "
                f"{receipt.approval_id.value}."
            )
        except Exception as exc:
            self._print_openchia(f"Approval not recorded: {exc}")
        self._refresh_openchia()
        return True

    def _handle_openchia_decline(self, stripped: str) -> bool:
        if self._command_arguments(stripped):
            self._print_openchia("Usage: /decline")
            return True
        try:
            self._episode_host().decline_current_refinement()
            self._print_openchia(
                "Declined the pending refinement; the approved baseline remains current."
            )
        except Exception as exc:
            self._print_openchia(f"Refinement was not declined: {exc}")
        self._refresh_openchia()
        return True

    def _handle_openchia_stop(self, stripped: str) -> bool:
        if self._command_arguments(stripped):
            self._print_openchia("Usage: /stop")
            return True
        from agent.interrupt_compat import request_hard_interrupt

        cancellations = 0
        if self._agent_running and self.agent is not None:
            try:
                request_hard_interrupt(self.agent)
                cancellations += 1
                self._print_openchia(
                    "Foreground Duet turn cancellation requested."
                )
            except Exception as exc:
                self._print_openchia(
                    f"Foreground Duet turn cancellation failed: {exc}"
                )
        if self._openchia_host is not None:
            try:
                run_cancelled = self._openchia_host.cancel_run()
            except Exception as exc:
                run_cancelled = False
                self._print_openchia(
                    f"Run cancellation was not requested: {exc}"
                )
            try:
                build_cancelled = self._openchia_host.cancel_build()
            except Exception as exc:
                build_cancelled = False
                self._print_openchia(
                    f"EpisodeBuilder cancellation was not requested: {exc}"
                )
            if run_cancelled:
                cancellations += 1
                self._print_openchia("Run cancellation requested.")
            if build_cancelled:
                cancellations += 1
                self._print_openchia(
                    "EpisodeBuilder cancellation requested."
                )
        cancellations += self._request_background_cancellation()
        if not cancellations:
            self._print_openchia("No OpenChia-owned work is active.")
        self._refresh_openchia()
        return True

    def process_command(self, cmd: str) -> bool:
        stripped = cmd.strip()
        command = stripped.split(maxsplit=1)[0].lower() if stripped else ""
        handler_name = self._openchia_command_dispatch.get(command)
        if handler_name is not None:
            return getattr(self, handler_name)(stripped)
        if stripped.startswith("/") and not self._command_available(stripped):
            self._print_openchia(
                "That command is outside the OpenChia Duet/Episode surface. "
                "Use /help for available controls."
            )
            return True
        return super().process_command(cmd)


__all__ = ["OpenChiaCommandMixin", "render_openchia_status"]
