"""Independent background Duet lifecycle and command handling."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from agent.openchia_host import OpenChiaHost
from hermes_constants import get_hermes_home


_BACKGROUND_USAGE = "Usage: /bg new PROMPT | /bg list | /bg DUET_ID ACTION"
_BACKGROUND_ACTION_USAGE = (
    "Usage: /bg DUET_ID "
    "<send|status|episode|approve|decline|build|run|cancel|evidence|logs|close>"
)


@dataclass
class _BackgroundDuet:
    """One independently conversational Duet beside the foreground Duet."""

    duet_id: str
    ordinal: int
    host: OpenChiaHost
    agent: Any
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    pending_prompts: deque[str] = field(default_factory=deque)
    thread: threading.Thread | None = None
    last_error: str | None = None


class OpenChiaBackgroundDuetsMixin:
    """Own background Duet contexts, FIFO turns, and their command surface."""

    _background_root_dispatch = {
        "list": "_background_root_list",
        "new": "_background_root_new",
    }
    _background_action_dispatch = {
        "send": "_background_action_send",
        "status": "_background_action_status",
        "episode": "_background_action_episode",
        "approve": "_background_action_approve",
        "decline": "_background_action_decline",
        "build": "_background_action_build",
        "launch": "_background_action_launch",
        "run": "_background_action_run",
        "cancel": "_background_action_cancel",
        "evidence": "_background_action_evidence",
        "logs": "_background_action_logs",
        "close": "_background_action_close",
    }

    def _initialize_background_duets(self) -> None:
        self._background_duets: dict[str, _BackgroundDuet] = {}
        self._background_duets_lock = threading.RLock()

    def _background_ui_active(self) -> bool:
        with self._background_duets_lock:
            return any(
                (
                    context.thread is not None
                    and context.thread.is_alive()
                )
                or context.host.has_active_work()
                for context in self._background_duets.values()
            )

    def _background_duet_agent_kwargs(
        self,
        duet_id: str,
        prompt: str,
        session_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if session_meta is None:
            route = self._resolve_turn_agent_config(prompt)
            saved_config = {}
        else:
            from openchia_cli.cli_model_switch_mixin import stored_session_route
            from openchia_cli.runtime_provider import resolve_runtime_provider

            raw = session_meta.get("model_config")
            try:
                saved_config = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError as exc:
                raise ValueError("The background Duet's saved model configuration is invalid JSON.") from exc
            if saved_config is None:
                saved_config = {}
            if not isinstance(saved_config, dict):
                raise ValueError("The background Duet's saved model configuration must be an object.")
            # This new agent has no current route. Empty values prevent the
            # shared resolver from treating the foreground route as restored.
            saved = stored_session_route(session_meta, current_model="", current_provider="")
            if saved is None:
                raise ValueError("The background Duet has no saved model route.")
            model, provider, endpoint, api_mode, _changed = saved
            runtime = resolve_runtime_provider(
                requested=provider, explicit_base_url=endpoint, target_model=model,
            )
            if api_mode:
                runtime["api_mode"] = api_mode
            route = {"model": model, "runtime": runtime,
                     "request_overrides": saved_config.get("request_overrides")}
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
            "reasoning_config": saved_config.get("reasoning_config", self.reasoning_config),
            "service_tier": saved_config.get("service_tier", self.service_tier),
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
        session_meta: dict[str, Any] | None = None,
    ) -> _BackgroundDuet:
        """Build a side conversation through the foreground host protocol."""

        from run_agent import AIAgent

        kwargs = self._background_duet_agent_kwargs(duet_id, prompt, session_meta)
        agent = AIAgent(**kwargs)
        host: OpenChiaHost | None = None
        try:
            # Store the background route before its first turn. A later reopen
            # must not silently inherit the foreground Duet's new provider.
            agent._session_init_model_config.update({
                "gateway_runtime": {
                    "provider": kwargs["requested_provider"] or agent.provider,
                    "base_url": agent.base_url,
                    "api_mode": agent.api_mode,
                },
                "service_tier": kwargs["service_tier"],
                "request_overrides": kwargs["request_overrides"],
            })
            agent._ensure_db_session()
            host = OpenChiaHost(
                home=get_hermes_home(),
                session_id=duet_id,
                available_tool_names=self._tool_names(agent),
                agent_kwargs_factory=lambda role, identity: {
                    "provider": agent.provider,
                    "model": agent.model,
                    "api_key": agent.api_key,
                    "base_url": agent.base_url,
                    "api_mode": agent.api_mode,
                    "session_id": duet_id,
                },
                run_executor_factory=self._strict_run_executor_factory(),
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
        """Reopen a persisted background Duet by its displayed identity."""

        if not duet_id.startswith("duet_") or self._session_db is None:
            return None
        try:
            session_meta = self._session_db.get_session(duet_id)
            if session_meta is None:
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
            session_meta=session_meta,
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
        *,
        prepared: bool = False,
    ) -> None:
        if not prepared:
            try:
                prompt = self._prepare_human_duet_turn(
                    context.host,
                    prompt,
                )
            except Exception as exc:
                self._print_openchia(
                    "Human instruction was not persisted for background Duet "
                    f"{context.duet_id}: {exc}"
                )
                return
        with self._background_duets_lock:
            running = bool(context.thread and context.thread.is_alive())
            if running:
                context.pending_prompts.append(prompt)
                position = len(context.pending_prompts)
        if running:
            self._print_openchia(
                f"Queued for background Duet {context.duet_id} "
                f"at FIFO position {position}."
            )
            return

        preview = prompt[:60] + ("..." if len(prompt) > 60 else "")
        self._print_openchia(
            f"Background Duet #{context.ordinal} working: \"{preview}\"\n"
            f"Duet ID: {context.duet_id}\n"
            f"Continue it later with: /bg {context.duet_id} send TEXT"
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
            with self._background_duets_lock:
                context.thread = None
                if self._openchia_tearing_down:
                    context.pending_prompts.clear()
                    next_prompt = None
                else:
                    next_prompt = (
                        context.pending_prompts.popleft()
                        if context.pending_prompts
                        else None
                    )
            if not self._agent_running:
                self._spinner_text = ""
            if next_prompt is not None:
                self._run_background_duet_turn(
                    context,
                    next_prompt,
                    prepared=True,
                )

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
        with self._background_duets_lock:
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
        from .openchia_commands import ACTIVE_BUILD_STATES, ACTIVE_RUN_STATES, RESUMABLE_RUN_STATES

        with self._background_duets_lock:
            contexts = sorted(
                self._background_duets.values(),
                key=lambda item: item.ordinal,
            )
        if not contexts:
            self._print_openchia(
                "No background Duets are open in this process.\n"
                "Start one with: /bg new PROMPT\n"
                "Reopen one with: /bg DUET_ID send TEXT"
            )
            return
        lines = ["Background Duets:"]
        for context in contexts:
            running = bool(context.thread and context.thread.is_alive())
            try:
                host_status = context.host.status()
                duet_state = host_status.get("state", "unknown")
            except Exception:
                host_status = {}
                duet_state = "unavailable"
            state = "working" if running else "idle"
            run_state = str(
                (host_status.get("run") or {}).get("state") or "not_started"
            )
            build_state = str(
                (host_status.get("build") or {}).get("state") or "not_started"
            )
            if not running and run_state in ACTIVE_RUN_STATES:
                state = f"run:{run_state}"
            elif not running and build_state in ACTIVE_BUILD_STATES:
                state = f"build:{build_state}"
            elif not running and run_state in RESUMABLE_RUN_STATES | {"ownership_unknown", "host_error"}:
                state = f"run:{run_state}"
            if context.last_error:
                state = "error"
            queued = len(context.pending_prompts)
            queue_note = f" · {queued} queued" if queued else ""
            lines.append(
                f"  #{context.ordinal} {context.duet_id} · {state}{queue_note} · {duet_state}"
            )
            if state == f"run:{run_state}" and run_state in RESUMABLE_RUN_STATES:
                lines.append(f"    /bg {context.duet_id} run continue · /bg {context.duet_id} run status")
            elif state == "run:ownership_unknown":
                lines.append(f"    /bg {context.duet_id} run status")
        lines.append("Continue one with: /bg DUET_ID send TEXT")
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
        close_errors: list[str] = []
        for label, closer in (
            ("agent", context.agent.close),
            ("host", context.host.close),
        ):
            try:
                closer()
            except Exception as exc:
                close_errors.append(f"{label}: {exc}")
        with self._background_duets_lock:
            self._background_duets.pop(duet_id, None)
        if close_errors:
            self._print_openchia(
                f"Background Duet {duet_id} left the live context; cleanup errors: "
                + "; ".join(close_errors)
            )
            return
        self._print_openchia(
            f"Background Duet {duet_id} closed; its persisted session remains resumable."
        )

    def _background_root_list(self, arguments: str) -> None:
        if arguments:
            self._print_openchia(_BACKGROUND_USAGE)
            return
        self._list_background_duets()

    def _background_root_new(self, arguments: str) -> None:
        prompt = arguments.strip()
        if not prompt:
            self._print_openchia("Usage: /bg new PROMPT")
            return
        self._start_background_duet(prompt)

    def _background_action_send(
        self,
        context: _BackgroundDuet,
        duet_id: str,
        arguments: str,
    ) -> None:
        prompt = arguments.strip()
        if not prompt:
            self._print_openchia("Usage: /bg DUET_ID send TEXT")
            return
        self._run_background_duet_turn(context, prompt)

    def _background_action_status(
        self,
        context: _BackgroundDuet,
        duet_id: str,
        arguments: str,
    ) -> None:
        if arguments:
            self._print_openchia(_BACKGROUND_ACTION_USAGE)
            return
        try:
            self._print_openchia(
                json.dumps(
                    context.host.status(),
                    indent=2,
                    ensure_ascii=False,
                )
            )
        except Exception as exc:
            self._print_openchia(
                f"Background Duet {duet_id} status is unavailable: {exc}"
            )

    def _background_action_episode(
        self,
        context: _BackgroundDuet,
        duet_id: str,
        arguments: str,
    ) -> None:
        mode = arguments.strip().lower()
        if mode == "diff":
            self._show_episode_changes(host=context.host)
            return
        if mode not in {"", "edit"}:
            self._print_openchia("Usage: /bg DUET_ID episode [edit|diff]")
            return
        try:
            self._open_episode_workspace(
                host=context.host,
                edit_architecture=mode == "edit",
                duet_turn_active=bool(
                    context.thread and context.thread.is_alive()
                ),
                enqueue_followup=lambda prompt: (
                    self._run_background_duet_turn(
                        context,
                        prompt,
                        prepared=True,
                    )
                ),
            )
        except Exception as exc:
            self._print_openchia(
                f"Background Episode Workspace unavailable: {exc}"
            )

    def _background_action_approve(
        self,
        context: _BackgroundDuet,
        duet_id: str,
        arguments: str,
    ) -> None:
        if arguments:
            self._print_openchia(_BACKGROUND_ACTION_USAGE)
            return
        try:
            receipt = context.host.approve_current()
            self._print_openchia(
                f"Background Duet {duet_id} approved {receipt.kind} "
                f"artifact {receipt.artifact_id.value} under approval "
                f"{receipt.approval_id.value}."
            )
        except Exception as exc:
            self._print_openchia(
                f"Background Duet approval not recorded: {exc}"
            )

    def _background_action_decline(
        self,
        context: _BackgroundDuet,
        duet_id: str,
        arguments: str,
    ) -> None:
        if arguments:
            self._print_openchia(_BACKGROUND_ACTION_USAGE)
            return
        try:
            context.host.decline_current_refinement()
            self._print_openchia(
                f"Background Duet {duet_id} declined its pending refinement."
            )
        except Exception as exc:
            self._print_openchia(
                f"Background refinement was not declined: {exc}"
            )

    def _background_action_build(
        self,
        context: _BackgroundDuet,
        duet_id: str,
        arguments: str,
    ) -> None:
        mode = arguments.strip().lower()
        if mode not in {"", "status", "continue"}:
            self._print_openchia("Usage: /bg DUET_ID build [status|continue]")
            return
        try:
            if mode == "status":
                build = context.host.build_status()
                self._print_openchia(
                    json.dumps(build, indent=2, ensure_ascii=False)
                )
            else:
                build = context.host.continue_build() if mode == "continue" else context.host.start_build()
                self._print_openchia(
                    f"Background Duet {duet_id} {'continued' if mode == 'continue' else 'started fresh'} build "
                    f"{build['build_request_id']}."
                )
        except Exception as exc:
            self._print_openchia(
                f"Background EpisodeBuilder operation failed: {exc}"
            )

    def _background_action_launch(self, context: _BackgroundDuet, duet_id: str, arguments: str) -> None:
        from openchia_cli.episode_launch_command import launch_command
        try:
            result = launch_command(context.host, arguments)
            self._print_openchia(json.dumps(result, indent=2, ensure_ascii=False))
        except Exception as exc:
            self._print_openchia(f"Background Duet {duet_id} launch configuration: {exc}")

    def _background_action_run(
        self,
        context: _BackgroundDuet,
        duet_id: str,
        arguments: str,
    ) -> None:
        mode = arguments.strip().lower()
        if mode not in {"", "status", "continue"}:
            self._print_openchia("Usage: /bg DUET_ID run [status|continue]")
            return
        try:
            if mode == "status":
                run = context.host.run_status()
                self._print_openchia(
                    json.dumps(run, indent=2, ensure_ascii=False)
                )
            else:
                run = context.host.continue_run() if mode == "continue" else context.host.start_run()
                self._print_openchia(
                    f"Background Duet {duet_id} {'requested continuation of' if mode == 'continue' else 'started'} Run {run['run_id']}."
                )
        except Exception as exc:
            self._print_openchia(f"Background Run operation failed: {exc}")

    def _background_action_cancel(
        self,
        context: _BackgroundDuet,
        duet_id: str,
        arguments: str,
    ) -> None:
        if arguments:
            self._print_openchia(_BACKGROUND_ACTION_USAGE)
            return
        turn_cancelled = False
        if context.thread is not None and context.thread.is_alive():
            try:
                from agent.interrupt_compat import request_hard_interrupt

                request_hard_interrupt(context.agent)
                turn_cancelled = True
            except Exception as exc:
                self._print_openchia(
                    f"Background Duet turn cancellation failed: {exc}"
                )
        try:
            run_cancelled = context.host.cancel_run()
        except Exception as exc:
            run_cancelled = False
            self._print_openchia(f"Background Run cancellation failed: {exc}")
        try:
            build_cancelled = context.host.cancel_build()
        except Exception as exc:
            build_cancelled = False
            self._print_openchia(f"Background build cancellation failed: {exc}")
        if turn_cancelled:
            self._print_openchia(
                f"Background Duet {duet_id} turn cancellation requested."
            )
        if run_cancelled:
            self._print_openchia(
                f"Background Duet {duet_id} requested Run cancellation."
            )
        if build_cancelled:
            self._print_openchia(
                f"Background Duet {duet_id} requested build cancellation."
            )
        if not turn_cancelled and not run_cancelled and not build_cancelled:
            self._print_openchia(
                f"Background Duet {duet_id} has no active turn, Build, or Run."
            )

    def _background_run_artifact(
        self,
        context: _BackgroundDuet,
        duet_id: str,
        arguments: str,
        *,
        kind: str,
    ) -> None:
        identity = arguments.strip() or None
        if identity is not None and len(identity.split()) != 1:
            self._print_openchia(f"Usage: /bg DUET_ID {kind} [RUN_ID]")
            return
        try:
            record = (
                context.host.run_evidence(identity)
                if kind == "evidence"
                else context.host.run_audit_log(identity)
            )
            if record is None:
                self._print_openchia(
                    f"Background Duet {duet_id} has no validated terminal "
                    f"Run {kind}."
                )
            else:
                self._print_openchia(
                    json.dumps(record, indent=2, ensure_ascii=False)
                )
        except Exception as exc:
            self._print_openchia(f"Background Run {kind} unavailable: {exc}")

    def _background_action_evidence(
        self,
        context: _BackgroundDuet,
        duet_id: str,
        arguments: str,
    ) -> None:
        self._background_run_artifact(
            context,
            duet_id,
            arguments,
            kind="evidence",
        )

    def _background_action_logs(
        self,
        context: _BackgroundDuet,
        duet_id: str,
        arguments: str,
    ) -> None:
        self._background_run_artifact(
            context,
            duet_id,
            arguments,
            kind="logs",
        )

    def _background_action_close(
        self,
        context: _BackgroundDuet,
        duet_id: str,
        arguments: str,
    ) -> None:
        if arguments:
            self._print_openchia(_BACKGROUND_ACTION_USAGE)
            return
        self._close_background_duet(duet_id)

    def _process_background_duet_command(self, stripped: str) -> bool:
        payload = stripped[len("/bg") :].strip()
        if not payload:
            self._print_openchia(_BACKGROUND_USAGE)
            return True
        first, _, remainder = payload.partition(" ")
        root_handler_name = self._background_root_dispatch.get(first.lower())
        if root_handler_name is not None:
            getattr(self, root_handler_name)(remainder.strip())
            return True
        if not first.startswith("duet_"):
            self._print_openchia(_BACKGROUND_USAGE)
            return True
        duet_id = first
        action, _, arguments = remainder.strip().partition(" ")
        action = action.lower()
        handler_name = self._background_action_dispatch.get(action)
        if handler_name is None:
            self._print_openchia(_BACKGROUND_ACTION_USAGE)
            return True
        arguments = arguments.strip()
        if action == "send" and not arguments:
            self._print_openchia("Usage: /bg DUET_ID send TEXT")
            return True
        with self._background_duets_lock:
            context = self._background_duets.get(duet_id)
        restore_prompt = arguments if action == "send" else action
        try:
            context = context or self._background_duet_for(
                duet_id,
                restore_prompt,
            )
        except Exception as exc:
            self._print_openchia(
                f"Background Duet {duet_id} could not reopen: {exc}"
            )
            return True
        if context is None:
            self._print_openchia(f"Background Duet not found: {duet_id}")
            return True
        getattr(self, handler_name)(context, duet_id, arguments)
        return True

    def _request_background_cancellation(self) -> int:
        from agent.interrupt_compat import request_hard_interrupt

        cancellations = 0
        with self._background_duets_lock:
            contexts = tuple(self._background_duets.values())
        for context in contexts:
            context_cancellations = 0
            if context.thread is not None and context.thread.is_alive():
                try:
                    request_hard_interrupt(context.agent)
                    cancellations += 1
                    context_cancellations += 1
                except Exception as exc:
                    self._print_openchia(
                        f"Background Duet {context.duet_id} turn cancellation failed: {exc}"
                    )
            for label, cancel in (
                ("Run", context.host.cancel_run),
                ("build", context.host.cancel_build),
            ):
                try:
                    cancelled = cancel()
                except Exception as exc:
                    self._print_openchia(
                        f"Background Duet {context.duet_id} {label} cancellation failed: {exc}"
                    )
                else:
                    if cancelled:
                        cancellations += 1
                        context_cancellations += 1
            if context_cancellations:
                self._print_openchia(
                    f"Background Duet {context.duet_id} cancellation requested."
                )
        return cancellations

    def _close_owned_background_duets(self) -> None:
        """Cancel and close every independently owned background Duet context."""

        self._openchia_tearing_down = True
        with self._background_duets_lock:
            contexts = tuple(self._background_duets.values())
            self._background_duets.clear()
            for context in contexts:
                context.pending_prompts.clear()
        from agent.interrupt_compat import request_hard_interrupt

        for context in contexts:
            if context.thread is not None and context.thread.is_alive():
                try:
                    request_hard_interrupt(context.agent)
                except Exception:
                    pass
            for cancel in (
                context.host.cancel_run,
                context.host.cancel_build,
            ):
                try:
                    cancel()
                except Exception:
                    pass
        for context in contexts:
            try:
                context.agent.close()
            except Exception:
                pass
            try:
                context.host.close()
            except Exception:
                pass


__all__ = ["OpenChiaBackgroundDuetsMixin"]
