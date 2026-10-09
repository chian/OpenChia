"""Implementer coding over a plain chat-completions route (e.g. ANL Argo).

Regression for #61: after #66 every /build reaches the Code Implementer, and a
Duet pinned to an OpenAI-compatible ``chat_completions`` route failed with
"No Implementer coding adapter supports the owning Duet's pinned route".
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.refinement_coding import coding_backend
from agent.transports.refinement_chat import ChatCompletionsCodingSession


def _binding(api_mode: str = "chat_completions"):
    return SimpleNamespace(api_key="test-key", record={"route": {
        "api_mode": api_mode, "model": "Claude Opus 5", "provider": "custom",
        "base_url": "https://gateway.test/v1",
    }})


def _chunk(*, content=None, tool=None, finish=None):
    calls = None
    if tool is not None:
        index, call_id, name, arguments = tool
        calls = [SimpleNamespace(index=index, id=call_id, type="function",
                                 function=SimpleNamespace(name=name, arguments=arguments))]
    delta = SimpleNamespace(role="assistant", content=content, tool_calls=calls)
    return SimpleNamespace(id="c", model="Claude Opus 5", usage=None,
                           choices=[SimpleNamespace(index=0, delta=delta, finish_reason=finish)])


class ScriptedGateway:
    """Streams one scripted assistant turn per create() call, like Argo does."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        assert kwargs.get("stream") is True, "the adapter must stream (Argo refuses long non-streamed calls)"
        assert {tool["function"]["name"] for tool in kwargs["tools"]} >= {"read_file", "write_file", "run_command"}
        return iter(self.turns.pop(0))


def _session(tmp_path, gateway, events=None, **kwargs):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return ChatCompletionsCodingSession(
        binding=_binding(), workspace=workspace, state_dir=tmp_path / "state",
        instructions="You are the coding capability.", resume_thread_id=kwargs.pop("resume", None),
        on_event=(events.append if events is not None else (lambda _event: None)),
        client_factory=lambda route, key: gateway, **kwargs,
    ), workspace


def test_backend_selects_the_chat_adapter_for_chat_completions_routes() -> None:
    assert coding_backend(_binding()) is ChatCompletionsCodingSession
    with pytest.raises(ValueError):
        coding_backend(_binding("bedrock_converse"))


def test_turn_writes_files_through_tool_calls_and_returns_final_text(tmp_path) -> None:
    gateway = ScriptedGateway([
        [_chunk(tool=(0, "t1", "write_file", json.dumps({"path": "pkg/mod.py", "content": "X = 1\n"}))),
         _chunk(finish="tool_calls")],
        [_chunk(tool=(0, "t2", "run_command", json.dumps({"command": "cat pkg/mod.py"}))),
         _chunk(finish="tool_calls")],
        [_chunk(content="Wrote pkg/mod.py and checked it."), _chunk(finish="stop")],
    ])
    events = []
    session, workspace = _session(tmp_path, gateway, events)
    thread = session.ensure_started()
    turn = session.run_turn("Work on the assignment.")
    assert turn.error is None and not turn.interrupted
    assert turn.final_text == "Wrote pkg/mod.py and checked it."
    assert turn.tool_iterations == 2 and turn.thread_id == thread
    assert (workspace / "pkg/mod.py").read_text(encoding="utf-8-sig") == "X = 1\n"
    command_result = gateway.requests[2]["messages"][-1]
    assert command_result["role"] == "tool" and "exit 0" in command_result["content"] and "X = 1" in command_result["content"]
    kinds = [event["kind"] for event in events]
    assert kinds[0] == "turn_started" and kinds[-1] == "turn_completed" and "item_completed" in kinds
    assert (tmp_path / "state" / f"chat-{thread}.json").is_file()


def test_paths_outside_the_workspace_are_refused(tmp_path) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_text("do not read", encoding="utf-8")
    gateway = ScriptedGateway([
        [_chunk(tool=(0, "t1", "read_file", json.dumps({"path": "../secret.txt"}))), _chunk(finish="tool_calls")],
        [_chunk(tool=(0, "t2", "write_file", json.dumps({"path": "/tmp/escape.txt", "content": "x"}))),  # no-tmp: ok — escape attempt under test, refused by the adapter
         _chunk(finish="tool_calls")],
        [_chunk(content="done"), _chunk(finish="stop")],
    ])
    session, _ = _session(tmp_path, gateway)
    session.run_turn("go")
    outputs = [m["content"] for m in gateway.requests[2]["messages"] if m["role"] == "tool"]
    assert all("outside the coding workspace" in output for output in outputs)
    assert "do not read" not in json.dumps(gateway.requests[2]["messages"])


def test_edit_requires_a_unique_match(tmp_path) -> None:
    gateway = ScriptedGateway([
        [_chunk(tool=(0, "t1", "edit_file", json.dumps({"path": "a.py", "old_string": "x", "new_string": "y"}))),
         _chunk(finish="tool_calls")],
        [_chunk(content="ok"), _chunk(finish="stop")],
    ])
    session, workspace = _session(tmp_path, gateway)
    (workspace / "a.py").write_text("x = x\n", encoding="utf-8")
    session.run_turn("go")
    assert "occurs 2 times" in gateway.requests[1]["messages"][-1]["content"]
    assert (workspace / "a.py").read_text(encoding="utf-8-sig") == "x = x\n"


def test_provider_failure_is_a_visible_error_not_a_crash(tmp_path) -> None:
    class Broken:
        chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(RuntimeError("500 upstream"))))

    events = []
    session, _ = _session(tmp_path, Broken(), events)
    turn = session.run_turn("go")
    assert turn.error and "500 upstream" in turn.error
    assert any(event["kind"] == "api_error" for event in events)


def test_interrupt_before_turn_returns_interrupted(tmp_path) -> None:
    session, _ = _session(tmp_path, ScriptedGateway([]))
    session.ensure_started()
    session.request_interrupt()
    assert session.run_turn("go").interrupted


def test_resume_restores_the_saved_conversation(tmp_path) -> None:
    first = ScriptedGateway([[_chunk(content="first"), _chunk(finish="stop")]])
    session, _ = _session(tmp_path, first)
    thread = session.ensure_started()
    session.run_turn("one")
    session.close()
    second = ScriptedGateway([[_chunk(content="second"), _chunk(finish="stop")]])
    resumed, _ = _session(tmp_path, second, resume=thread)
    resumed.run_turn("two")
    sent = second.requests[0]["messages"]
    assert [m["content"] for m in sent if m["role"] == "user"] == ["one", "two"]


def test_step_budget_ends_the_turn_without_failing_the_run(tmp_path) -> None:
    # A CodingTurn error stops the owning Run (iterative_episode_refiner/coding.py);
    # exhausting the budget must instead hand the edits so far to host admission.
    looping = [[_chunk(tool=(0, f"t{i}", "list_files", "{}")), _chunk(finish="tool_calls")] for i in range(5)]
    gateway = ScriptedGateway(looping)
    session, _ = _session(tmp_path, gateway, max_steps=5)
    turn = session.run_turn("go")
    assert turn.error is None and not turn.interrupted
    assert "5-step budget" in turn.final_text and turn.native_result["finish"] == "step_budget"
    # The model was told to write before the budget ran out.
    warned = [m for m in gateway.requests[-1]["messages"] if m["role"] == "user" and "model steps remain" in m["content"]]
    assert warned


def test_step_budget_is_configurable(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENCHIA_CODING_MAX_STEPS", "7")
    session, _ = _session(tmp_path, ScriptedGateway([]))
    assert session._max_steps == 7
    monkeypatch.setenv("OPENCHIA_CODING_MAX_STEPS", "nonsense")
    session, _ = _session(tmp_path, ScriptedGateway([]))
    assert session._max_steps == 60


def test_wrong_route_is_rejected(tmp_path) -> None:
    with pytest.raises(ValueError):
        ChatCompletionsCodingSession(
            binding=_binding("codex_responses"), workspace=tmp_path, state_dir=tmp_path / "s",
            instructions="", resume_thread_id=None, on_event=lambda _e: None,
        )


def test_transient_stream_drop_is_retried_without_failing_the_turn(tmp_path, monkeypatch) -> None:
    import httpx
    import agent.transports.refinement_chat as chat

    monkeypatch.setattr(chat, "RETRY_BACKOFF_SECONDS", (0, 0, 0))
    good = ScriptedGateway([[_chunk(content="done"), _chunk(finish="stop")]])
    failures = {"left": 2}

    def create(**kwargs):
        if failures["left"]:
            failures["left"] -= 1
            raise httpx.RemoteProtocolError("peer closed connection without sending complete message body (incomplete chunked read)")
        return good._create(**kwargs)

    gateway = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    events = []
    session, _ = _session(tmp_path, gateway, events)
    turn = session.run_turn("go")
    assert turn.error is None and turn.final_text == "done"
    retries = [e for e in events if e["kind"] == "activity" and e["native"].get("retry")]
    assert [e["native"]["retry"] for e in retries] == [1, 2]
    assert not any(e["kind"] == "api_error" for e in events)


def test_persistent_transient_failure_still_surfaces(tmp_path, monkeypatch) -> None:
    import httpx
    import agent.transports.refinement_chat as chat

    monkeypatch.setattr(chat, "RETRY_BACKOFF_SECONDS", (0, 0, 0))

    def create(**_kwargs):
        raise httpx.RemoteProtocolError("incomplete chunked read")

    gateway = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    session, _ = _session(tmp_path, gateway)
    turn = session.run_turn("go")
    assert turn.error and "incomplete chunked read" in turn.error


def test_exploration_nudge_after_steps_without_a_write(tmp_path, monkeypatch) -> None:
    import agent.transports.refinement_chat as chat

    monkeypatch.setattr(chat, "EXPLORATION_NUDGE_STEPS", 3)
    turns = [[_chunk(tool=(0, f"t{i}", "list_files", "{}")), _chunk(finish="tool_calls")] for i in range(3)]
    turns.append([_chunk(content="ok"), _chunk(finish="stop")])
    gateway = ScriptedGateway(turns)
    session, _ = _session(tmp_path, gateway)
    session.run_turn("go")
    nudges = [m for m in gateway.requests[-1]["messages"] if m["role"] == "user" and "without a source edit" in m["content"]]
    assert len(nudges) == 1


def test_compaction_keeps_the_head_of_old_tool_outputs(tmp_path, monkeypatch) -> None:
    import agent.transports.refinement_chat as chat

    monkeypatch.setattr(chat, "MAX_HISTORY_CHARS", 2_000)
    session, _ = _session(tmp_path, ScriptedGateway([]))
    session.ensure_started()
    session._messages += [{"role": "tool", "tool_call_id": f"c{i}", "content": f"HEAD{i}" + "x" * 3_000} for i in range(6)]
    session._compact()
    elided = [m for m in session._messages if m.get("role") == "tool" and "elided" in m["content"]]
    assert elided and all(m["content"].startswith("HEAD") for m in elided)


# ---------------------------------------------------------------- guardrails (2026-10-09)


def test_process_identity_is_a_session_sentinel_not_the_host(tmp_path) -> None:
    import os
    from openchia_cli.active_sessions import _pid_liveness

    session, _ = _session(tmp_path, ScriptedGateway([]))
    identity = session.process_identity()
    assert identity["pid"] != os.getpid()
    assert _pid_liveness(identity["pid"], identity["process_start_time"]) is True
    session.close()
    # After close the refiner can resume the invocation's workspace.
    assert _pid_liveness(identity["pid"], identity["process_start_time"]) is False


def test_provider_notice_fails_the_turn_instead_of_becoming_a_result(tmp_path) -> None:
    notice = ("⚠️ **IMPORTANT USAGE NOTICE FROM ARGO** 🚫 **ACCESS REVOKED** Your Argo usage limit has "
              "been exceeded. Reason: Monthly limit exceeded.")
    gateway = ScriptedGateway([[_chunk(content=notice), _chunk(finish="stop")]])
    events = []
    session, _ = _session(tmp_path, gateway, events)
    turn = session.run_turn("go")
    assert turn.error and "Provider refused service" in turn.error and "Monthly limit exceeded" in turn.error
    assert any(e["kind"] == "api_error" for e in events)


def test_turn_ends_without_error_after_too_many_steps_without_an_edit(tmp_path, monkeypatch) -> None:
    import agent.transports.refinement_chat as chat

    monkeypatch.setattr(chat, "NO_WRITE_STOP_STEPS", 3)
    monkeypatch.setattr(chat, "EXPLORATION_NUDGE_STEPS", 2)
    looping = [[_chunk(tool=(0, f"t{i}", "list_files", "{}")), _chunk(finish="tool_calls")] for i in range(3)]
    gateway = ScriptedGateway(looping)
    session, _ = _session(tmp_path, gateway)
    turn = session.run_turn("go")
    assert turn.error is None and turn.native_result["finish"] == "no_progress"
    assert len(gateway.requests) == 3


def test_turn_ends_at_the_input_token_budget(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENCHIA_CODING_MAX_INPUT_TOKENS", "10")
    looping = [[_chunk(tool=(0, f"t{i}", "list_files", "{}")), _chunk(finish="tool_calls")] for i in range(5)]
    gateway = ScriptedGateway(looping)
    session, _ = _session(tmp_path, gateway)
    turn = session.run_turn("go")
    assert turn.error is None and turn.native_result["finish"] == "token_budget"
    assert len(gateway.requests) == 1  # the system prompt alone exceeds 10 tokens
