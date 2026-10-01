"""Shutdown signals remain system control events at the CLI interrupt boundary."""

from __future__ import annotations

import signal
import threading
from types import SimpleNamespace

import pytest

import cli
from agent.interrupt_control import interrupt_issuer
from hermes_cli.cli_chat_turn_mixin import CLIChatTurnMixin


def _bare_agent():
    """Build the real interrupt-control surface without initializing a provider."""
    from run_agent import AIAgent

    agent = AIAgent.__new__(AIAgent)
    agent._interrupt_requested = False
    agent._interrupt_message = None
    agent._tool_interrupt_reason = None
    agent._hard_interrupt_requested = threading.Event()
    agent._execution_thread_id = None
    agent._interrupt_thread_signal_pending = False
    agent._active_children = []
    agent._active_children_lock = threading.Lock()
    agent.quiet_mode = True
    return agent


@pytest.mark.platforms("posix")
def test_shutdown_signal_cannot_become_the_next_user_turn(monkeypatch):
    agent = _bare_agent()
    monkeypatch.setattr(cli, "_float_env", lambda *_args: 0.0)

    cli._interrupt_agent_for_signal(agent, signal.SIGHUP)

    assert agent._interrupt_requested is True
    assert agent._hard_interrupt_requested.is_set()
    assert agent._interrupt_message is None
    assert interrupt_issuer(agent) == "cli_shutdown_signal"

    surface = CLIChatTurnMixin()
    turn = SimpleNamespace(
        result={"interrupted": True, "interrupt_message": agent._interrupt_message}
    )
    stopped_thread = SimpleNamespace(is_alive=lambda: False)
    pending_message, show_marker = surface._chat_resolve_interrupt(
        turn,
        stopped_thread,
        interrupt_msg=None,
        response="",
    )
    assert pending_message is None
    assert show_marker is False
