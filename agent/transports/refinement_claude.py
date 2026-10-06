"""Claude Code's existing print/stream-json workflow in Implementer's workspace.

Claude owns its coding loop. This adapter translates its session and results;
OpenChia owns assignment, candidate admission, measurement and continuation.
"""

import json
import queue
import subprocess
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from agent.anthropic_credentials import anthropic_route_is_oauth
from agent.deadline import kill_process_tree
from agent.delegation_context import delegated_child_subprocess_env
from agent.refinement_coding import CodingTurn
from openchia_cli._subprocess_compat import windows_hide_flags
from openchia_cli.active_sessions import _process_start_time
from tools.environments.local import hermes_subprocess_env


class ClaudeCodingSession:
    runtime_id = "claude_code"

    def __init__(self, *, binding, workspace, state_dir, instructions,
                 resume_thread_id, on_event, claude_bin="claude"):
        route = binding.record["route"]
        if route["api_mode"] != "anthropic_messages" or not binding.api_key:
            raise ValueError("Claude Code requires the owning Duet's Anthropic Messages route and credential")
        self._thread_id = resume_thread_id or str(uuid.uuid4())
        self._workspace = Path(workspace)
        self._state_dir = Path(state_dir)
        self._on_event = on_event
        self._interrupt = threading.Event()
        self._events = queue.Queue()
        self._stderr = deque(maxlen=20)
        self._proc = None
        self._readers = []
        self._closed = False
        self._model = route["model"]
        self._env = delegated_child_subprocess_env(hermes_subprocess_env(inherit_credentials=False))
        # Native account/settings state must not select another Duet or endpoint.
        for name in tuple(self._env):
            if name.startswith(("CLAUDE_", "ANTHROPIC_")) or name == "CLAUDECODE":
                del self._env[name]
        oauth = anthropic_route_is_oauth(route["base_url"], binding.api_key, provider=route["provider"])
        self._env.update({
            "CLAUDE_CONFIG_DIR": str(self._state_dir),
            "ANTHROPIC_BASE_URL": route["base_url"],
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "CLAUDE_CODE_OAUTH_TOKEN" if oauth else "ANTHROPIC_API_KEY": binding.api_key,
        })
        coding_tools = "Read,Write,Edit,Bash,Glob,Grep"
        self._args = [
            claude_bin, "--print", "--input-format", "stream-json",
            "--output-format", "stream-json", "--verbose",
            "--model", self._model, "--append-system-prompt", instructions,
            "--tools", coding_tools, "--allowedTools", coding_tools,
            "--permission-mode", "dontAsk", "--setting-sources", "",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--settings", '{"disableAllHooks":true,"autoMemoryEnabled":false}',
            "--disable-slash-commands", "--no-chrome",
            "--resume" if resume_thread_id else "--session-id", self._thread_id,
        ]
        effort = (route.get("reasoning") or {}).get("effort")
        if effort:
            self._args.extend(("--effort", effort))

    def ensure_started(self):
        if self._closed:
            raise RuntimeError("Claude Code session is closed")
        if self._proc is None:
            self._state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._proc = subprocess.Popen(
                self._args, cwd=self._workspace, env=self._env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1, creationflags=windows_hide_flags(),
            )
            for stream, output in ((self._proc.stdout, self._events.put),
                                   (self._proc.stderr, self._stderr.append)):
                reader = threading.Thread(target=self._read, args=(stream, output), daemon=True)
                self._readers.append(reader)
                reader.start()
        return self._thread_id

    @staticmethod
    def _read(stream, output):
        for line in stream:
            output(line)

    def process_identity(self):
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError("Claude Code session is not running")
        started = _process_start_time(self._proc.pid)
        if started is None:
            raise RuntimeError("Claude Code process identity is unavailable")
        return {"pid": self._proc.pid, "process_start_time": started}

    def request_interrupt(self):
        self._interrupt.set()

    def _observe(self, event):
        error = event.get("error")
        if event.get("type") == "system" and event.get("subtype") == "api_retry":
            error = error or event.get("error_status") or "Claude Code provider retry"
        if event.get("type") == "result" and event.get("is_error"):
            error = event.get("errors") or event.get("result") or event.get("subtype")
        kind = "api_error" if error else {
            "assistant": "item_started", "user": "item_completed", "result": "turn_completed",
        }.get(event.get("type"), "activity")
        self._on_event({"kind": kind, "native": event, "error": error})
        return error

    def run_turn(self, prompt, *, turn_timeout=None):
        self.ensure_started()
        turn_id = str(uuid.uuid4())
        if self._interrupt.is_set():
            return CodingTurn(thread_id=self._thread_id, turn_id=turn_id, interrupted=True)
        self._on_event({"kind": "turn_started", "native": {"session_id": self._thread_id, "turn_id": turn_id}})
        self._proc.stdin.write(json.dumps({
            "type": "user", "session_id": self._thread_id,
            "message": {"role": "user", "content": prompt},
        }) + "\n")
        self._proc.stdin.flush()
        deadline = None if turn_timeout is None else time.monotonic() + turn_timeout
        tool_calls = set()
        while not self._interrupt.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                break
            try:
                line = self._events.get(timeout=0.1)
            except queue.Empty:
                if self._proc.poll() is not None:
                    raise RuntimeError("Claude Code exited without a result: " + "".join(self._stderr))
                continue
            event = json.loads(line)
            if event.get("session_id", self._thread_id) != self._thread_id:
                raise ValueError("Claude Code returned another session's result")
            if event.get("type") == "system" and event.get("subtype") == "init":
                if event.get("model") != self._model:
                    raise ValueError("Claude Code selected a model outside the owning Duet's binding")
            for block in (event.get("message") or {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls.add(block["id"])
            error = self._observe(event)
            if error or event.get("type") == "result":
                if not error and event.get("subtype") != "success":
                    error = "Claude Code did not complete the coding turn"
                return CodingTurn(
                    final_text=event.get("result", ""), thread_id=self._thread_id,
                    turn_id=turn_id, tool_iterations=len(tool_calls),
                    error=str(error) if error else None, native_result=event,
                )
        self.close()
        return CodingTurn(thread_id=self._thread_id, turn_id=turn_id,
                          tool_iterations=len(tool_calls), interrupted=True)

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._proc is not None:
            # Stream-input mode keeps the parent alive between turns, so the
            # existing whole-tree terminator can still identify its children.
            if self._proc.poll() is None:
                kill_process_tree(self._proc.pid)
            self._proc.wait(timeout=5)
            for reader in self._readers:
                reader.join(timeout=5)
            for stream in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
                stream.close()
