"""Implementer's coding capability over an OpenAI-compatible chat-completions route.

Codex and Claude Code bring their own coding loops; a plain chat-completions
route (for example ANL's Argo gateway) does not. This adapter supplies the
smallest equivalent loop in-process: the owning Duet's pinned model, called
through the same streamed chat-completions path the launch transport uses, with
a fixed set of workspace-confined tools (list, read, write, edit, run).

OpenChia still owns the assignment, candidate admission, measurement and
continuation. Every path the model names is resolved inside the coding
workspace; commands run there with a scrubbed environment, a bounded runtime,
and are killed with their whole process tree on timeout or interrupt.
"""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from agent.refinement_coding import CodingTurn

MAX_TOOL_STEPS = 80
MAX_TOOL_OUTPUT_CHARS = 40_000
MAX_HISTORY_CHARS = 600_000
DEFAULT_COMMAND_TIMEOUT = 120
MAX_COMMAND_TIMEOUT = 600
DEFAULT_MAX_TOKENS = 32_768

TOOLS = [
    {"type": "function", "function": {
        "name": "list_files",
        "description": "List files under a workspace directory (recursive). Optional glob pattern on the relative path.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Directory relative to the workspace; default '.'"},
            "pattern": {"type": "string", "description": "fnmatch pattern on relative paths, e.g. '*.py'"},
        }, "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a text file in the workspace. Returns numbered lines.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "description": "1-based first line; default 1"},
            "limit": {"type": "integer", "description": "Maximum lines; default 2000"},
        }, "required": ["path"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create or overwrite a text file in the workspace with the complete content.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"},
        }, "required": ["path", "content"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Replace an exact, unique string in a workspace file (or every occurrence with replace_all).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "old_string": {"type": "string"},
            "new_string": {"type": "string"}, "replace_all": {"type": "boolean"},
        }, "required": ["path", "old_string", "new_string"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "run_command",
        "description": ("Run a shell command with the workspace as working directory, for diagnostics "
                        "(tests, linters, grep). No network or installer use. Returns exit code and output tail."),
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"},
            "timeout_seconds": {"type": "integer", "description": f"Default {DEFAULT_COMMAND_TIMEOUT}, max {MAX_COMMAND_TIMEOUT}"},
        }, "required": ["command"], "additionalProperties": False},
    }},
]


class WorkspacePathError(ValueError):
    pass


def _truncate(text: str, limit: int = MAX_TOOL_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    head = limit // 4
    return text[:head] + f"\n…[{len(text) - limit} characters elided]…\n" + text[-(limit - head):]


class ChatCompletionsCodingSession:
    runtime_id = "chat_completions_tools"

    def __init__(self, *, binding, workspace, state_dir, instructions, resume_thread_id, on_event,
                 client_factory: Callable[[dict, str | None], Any] | None = None,
                 max_steps: int = MAX_TOOL_STEPS):
        route = binding.record["route"]
        if route["api_mode"] != "chat_completions":
            raise ValueError("The chat-completions coding adapter requires the owning Duet's chat_completions route")
        self._route = route
        self._key = binding.api_key
        self._workspace = Path(workspace).resolve()
        self._state_dir = Path(state_dir)
        self._instructions = instructions
        self._on_event = on_event
        self._thread_id = resume_thread_id or uuid.uuid4().hex
        self._resuming = resume_thread_id is not None
        self._client_factory = client_factory or self._default_client
        self._max_steps = max_steps
        self._interrupt = threading.Event()
        self._lock = threading.Lock()
        self._http = None
        self._command = None
        self._messages: list[dict] = []
        self._started = False
        self._closed = False

    # -- protocol ---------------------------------------------------------------------------

    def ensure_started(self) -> str:
        if self._closed:
            raise RuntimeError("chat-completions coding session is closed")
        if not self._started:
            self._state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            saved = self._history_path()
            if self._resuming and saved.is_file():
                self._messages = json.loads(saved.read_text(encoding="utf-8-sig"))
            else:
                self._messages = [{"role": "system", "content": self._instructions}]
            self._started = True
        return self._thread_id

    def process_identity(self) -> dict:
        from openchia_cli.active_sessions import _process_start_time

        pid = os.getpid()
        started = _process_start_time(pid)
        if started is None:
            raise RuntimeError("coding session process identity is unavailable")
        return {"pid": pid, "process_start_time": started}

    def request_interrupt(self) -> None:
        self._interrupt.set()
        with self._lock:
            http, command = self._http, self._command
        if http is not None:
            try:
                http.close()
            except Exception:
                pass
        if command is not None and command.poll() is None:
            from agent.deadline import kill_process_tree

            kill_process_tree(command.pid)

    def run_turn(self, prompt: str, *, turn_timeout: float | None = None) -> CodingTurn:
        self.ensure_started()
        turn_id = uuid.uuid4().hex
        if self._interrupt.is_set():
            return CodingTurn(thread_id=self._thread_id, turn_id=turn_id, interrupted=True)
        self._emit("turn_started", {"thread_id": self._thread_id, "turn_id": turn_id})
        self._messages.append({"role": "user", "content": prompt})
        deadline = None if turn_timeout is None else time.monotonic() + turn_timeout
        tool_iterations = 0
        final_text = ""
        for _step in range(self._max_steps):
            if self._interrupt.is_set() or (deadline is not None and time.monotonic() >= deadline):
                self._save()
                return CodingTurn(thread_id=self._thread_id, turn_id=turn_id,
                                  tool_iterations=tool_iterations, interrupted=True)
            try:
                message = self._complete()
            except Exception as exc:  # provider failure: visible, never retried here
                if self._interrupt.is_set():
                    self._save()
                    return CodingTurn(thread_id=self._thread_id, turn_id=turn_id,
                                      tool_iterations=tool_iterations, interrupted=True)
                error = f"{type(exc).__name__}: {exc}"
                self._emit("api_error", {"turn_id": turn_id}, error=error)
                self._save()
                return CodingTurn(thread_id=self._thread_id, turn_id=turn_id,
                                  tool_iterations=tool_iterations, error=error)
            calls = list(getattr(message, "tool_calls", None) or [])
            content = getattr(message, "content", None) or ""
            record: dict[str, Any] = {"role": "assistant", "content": content}
            if calls:
                record["tool_calls"] = [{
                    "id": call.id, "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments or "{}"},
                } for call in calls]
            self._messages.append(record)
            if not calls:
                final_text = content
                self._save()
                self._emit("turn_completed", {"turn_id": turn_id, "tool_iterations": tool_iterations})
                return CodingTurn(final_text=final_text, thread_id=self._thread_id, turn_id=turn_id,
                                  tool_iterations=tool_iterations,
                                  native_result={"finish": "stop", "steps": _step + 1})
            for call in calls:
                tool_iterations += 1
                name = call.function.name
                self._emit("item_started", {"tool": name, "call_id": call.id})
                output = self._dispatch(name, call.function.arguments or "{}")
                self._emit("item_completed", {"tool": name, "call_id": call.id, "output_chars": len(output)})
                self._messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
            self._compact()
            self._save()
        error = f"coding turn exceeded {self._max_steps} model steps without a final message"
        self._emit("api_error", {"turn_id": turn_id}, error=error)
        return CodingTurn(thread_id=self._thread_id, turn_id=turn_id,
                          tool_iterations=tool_iterations, error=error)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.request_interrupt()
        if self._started:
            self._save()

    # -- model call -------------------------------------------------------------------------

    def _default_client(self, route: dict, key: str | None):
        import httpx
        from openai import OpenAI, Omit

        def strip_auth(outgoing):
            if key is None:
                outgoing.headers.pop("authorization", None)

        http = httpx.Client(trust_env=False, timeout=None, follow_redirects=False,
                            event_hooks={"request": [strip_auth]})
        with self._lock:
            self._http = http
        return OpenAI(api_key=key or "no-auth", base_url=route["base_url"], http_client=http,
                      max_retries=0, timeout=None, organization="", project="",
                      default_headers={"OpenAI-Organization": Omit(), "OpenAI-Project": Omit()})

    def _complete(self):
        from agent.auxiliary_client import (
            _create_with_progress_once, _provider_requires_stream, aux_progress_hook,
            auxiliary_max_tokens_param,
        )

        route = self._route
        client = self._client_factory(route, self._key)
        try:
            kwargs: dict[str, Any] = {
                "model": route["model"], "messages": [dict(item) for item in self._messages], "tools": TOOLS,
                "tool_choice": "auto",
            }
            kwargs.update(auxiliary_max_tokens_param(DEFAULT_MAX_TOKENS, model=route["model"]))
            reasoning = route.get("reasoning")
            if isinstance(reasoning, dict) and reasoning.get("effort"):
                kwargs["reasoning_effort"] = reasoning["effort"] if reasoning.get("enabled", True) else "none"
            # Streaming keeps long calls alive on gateways that refuse non-streamed
            # requests (Argo) and lets the host see activity; the helper re-aggregates
            # content and tool-call deltas into the ordinary ChatCompletion shape.
            force = _provider_requires_stream(route.get("provider", ""), route["base_url"])
            with aux_progress_hook(lambda: self._emit("activity", {})):
                response = _create_with_progress_once(client, kwargs, "implementer_coding", force_stream=force)
            return response.choices[0].message
        finally:
            with self._lock:
                http, self._http = self._http, None
            if http is not None:
                http.close()

    # -- tools ------------------------------------------------------------------------------

    def _dispatch(self, name: str, raw_arguments: str) -> str:
        try:
            arguments = json.loads(raw_arguments) if raw_arguments.strip() else {}
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be a JSON object")
            handler = {
                "list_files": self._list_files, "read_file": self._read_file,
                "write_file": self._write_file, "edit_file": self._edit_file,
                "run_command": self._run_command,
            }.get(name)
            if handler is None:
                return f"error: unknown tool {name!r}"
            return _truncate(handler(**arguments))
        except TypeError as exc:
            return f"error: bad arguments for {name}: {exc}"
        except Exception as exc:
            return f"error: {type(exc).__name__}: {exc}"

    def _resolve(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative or "\x00" in relative:
            raise WorkspacePathError("path must be non-empty text")
        candidate = (self._workspace / relative).resolve()
        if candidate != self._workspace and self._workspace not in candidate.parents:
            raise WorkspacePathError(f"{relative!r} is outside the coding workspace")
        return candidate

    def _list_files(self, path: str = ".", pattern: str | None = None) -> str:
        root = self._resolve(path)
        if not root.is_dir():
            return f"error: {path!r} is not a directory"
        entries = []
        for item in sorted(root.rglob("*")):
            if item.is_dir():
                continue
            relative = item.relative_to(self._workspace).as_posix()
            if pattern and not fnmatch.fnmatch(relative, pattern) and not fnmatch.fnmatch(item.name, pattern):
                continue
            entries.append(f"{relative}\t{item.stat().st_size}")
            if len(entries) >= 1000:
                entries.append("…[listing truncated at 1000 files]")
                break
        return "\n".join(entries) or "(no files)"

    def _read_file(self, path: str, offset: int = 1, limit: int = 2000) -> str:
        target = self._resolve(path)
        if not target.is_file():
            return f"error: {path!r} is not a file"
        lines = target.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        start = max(1, int(offset))
        chosen = lines[start - 1:start - 1 + max(1, int(limit))]
        body = "\n".join(f"{start + index}\t{line}" for index, line in enumerate(chosen))
        return body + (f"\n…[{len(lines)} lines total]" if start - 1 + len(chosen) < len(lines) else "")

    def _write_file(self, path: str, content: str) -> str:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote {path} ({len(content)} characters)"

    def _edit_file(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
        target = self._resolve(path)
        if not target.is_file():
            return f"error: {path!r} is not a file"
        text = target.read_text(encoding="utf-8-sig")
        count = text.count(old_string)
        if not old_string or count == 0:
            return "error: old_string not found"
        if count > 1 and not replace_all:
            return f"error: old_string occurs {count} times; make it unique or set replace_all"
        target.write_text(text.replace(old_string, new_string) if replace_all
                          else text.replace(old_string, new_string, 1), encoding="utf-8")
        return f"edited {path} ({count if replace_all else 1} replacement(s))"

    def _run_command(self, command: str, timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT) -> str:
        from agent.deadline import kill_process_tree
        from agent.delegation_context import delegated_child_subprocess_env
        from tools.environments.local import hermes_subprocess_env

        if self._interrupt.is_set():
            return "error: interrupted"
        timeout = max(1, min(int(timeout_seconds), MAX_COMMAND_TIMEOUT))
        env = delegated_child_subprocess_env(hermes_subprocess_env(inherit_credentials=False))
        process = subprocess.Popen(
            ["/bin/sh", "-c", command], cwd=self._workspace, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", start_new_session=True,
        )
        with self._lock:
            self._command = process
        try:
            output, _ = process.communicate(timeout=timeout)
            status = f"exit {process.returncode}"
        except subprocess.TimeoutExpired:
            kill_process_tree(process.pid)
            output, _ = process.communicate()
            status = f"timed out after {timeout}s (process tree killed)"
        finally:
            with self._lock:
                self._command = None
        return f"{status}\n{output or ''}"

    # -- state ------------------------------------------------------------------------------

    def _history_path(self) -> Path:
        return self._state_dir / f"chat-{self._thread_id}.json"

    def _save(self) -> None:
        path = self._history_path()
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._messages, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)

    def _compact(self) -> None:
        """Elide the oldest tool outputs once the conversation outgrows its budget."""
        total = sum(len(json.dumps(item, ensure_ascii=False)) for item in self._messages)
        for item in self._messages[1:-4]:
            if total <= MAX_HISTORY_CHARS:
                break
            if item.get("role") == "tool" and len(item["content"]) > 200:
                total -= len(item["content"]) - 60
                item["content"] = "[earlier tool output elided to fit the context budget]"

    def _emit(self, kind: str, native: dict, *, error: str | None = None) -> None:
        self._on_event({"kind": kind, "native": native, "error": error})
