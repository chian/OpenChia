import sys
from queue import Queue
from types import SimpleNamespace

import pytest

from hermes_cli.openchia_cli import (
    OpenChiaCLI,
    episode_configuration_changes,
    render_openchia_status,
)
from hermes_cli.openchia_main import main


def test_openchia_rejects_noninteractive_launch_modes(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["openchia", "--oneshot", "hello"])
    with pytest.raises(SystemExit, match="interactive Duet session"):
        main()


def test_openchia_forces_the_ascii_classic_surface(monkeypatch):
    observed = []
    monkeypatch.setattr(sys, "argv", ["openchia"])
    monkeypatch.setattr(
        "hermes_cli.main.run_with_chat_cli_main",
        lambda callback, **kwargs: observed.append(
            (callback, kwargs, tuple(sys.argv))
        ),
    )

    main()

    assert observed[0][2] == ("openchia", "--cli")


def test_status_panel_is_compact_and_contextual():
    shaping = render_openchia_status(
        {
            "state": "needs_duet_input",
            "revision": 2,
            "field_count": 4,
            "requested_field_ids": ["progress", "stopping"],
            "ready": False,
        }
    )
    assert shaping.count("\n") == 1
    assert "gap: success evidence" in shaping
    assert "[DUET] -> [CREATOR]" not in shaping
    assert "/guide" not in shaping

    ready = render_openchia_status(
        {
            "state": "contract_candidate",
            "revision": 3,
            "field_count": 9,
            "requested_field_ids": [],
            "ready": True,
            "contract_review": {"verdict": "concern"},
            "unconfirmed_proposal_ids": ["goal"],
        }
    )
    assert "shadow review: concern" in ready
    assert "/review · /approve" in ready


def test_running_prompt_advertises_only_openchia_commands():
    cli = OpenChiaCLI.__new__(OpenChiaCLI)
    cli._voice_recording = False
    cli._voice_processing = False
    cli._sudo_state = None
    cli._secret_state = None
    cli._approval_state = None
    cli._slash_confirm_state = None
    cli._clarify_freetext = False
    cli._clarify_state = None
    cli._command_running = False
    cli._agent_running = True

    assert cli._tui_placeholder_text() == (
        "msg=interrupt · /queue · /bg · Ctrl+C cancel"
    )


def test_stop_is_available_and_delegates_to_the_interrupt_capable_base(monkeypatch):
    observed = []
    cli = OpenChiaCLI.__new__(OpenChiaCLI)
    monkeypatch.setattr(
        "cli.HermesCLI.process_command",
        lambda self, command: observed.append(command) or True,
    )

    assert cli._command_available("/stop") is True
    assert OpenChiaCLI.process_command(cli, "/stop") is True
    assert observed == ["/stop"]


def test_episode_capability_ceiling_excludes_every_control_plane_tool(monkeypatch):
    protocol_names = {
        "openchia_scope",
        "duet_status",
        "duet_contract_review",
        "creator_context_artifact",
        "creator_context_read",
        "creator_log_read",
        "workflow_review",
        "workflow_candidate",
        "episode_progress",
    }
    definitions = [
        {"type": "function", "function": {"name": name}}
        for name in sorted(protocol_names | {"web_search", "terminal"})
    ]
    monkeypatch.setattr(
        "model_tools.get_tool_definitions",
        lambda **kwargs: definitions,
    )

    names = OpenChiaCLI._tool_names(SimpleNamespace())

    assert names == ("terminal", "web_search")
    assert not protocol_names.intersection(names)


def test_background_command_starts_and_continues_duets():
    observed = []
    context = object()
    cli = OpenChiaCLI.__new__(OpenChiaCLI)
    cli._start_background_duet = lambda prompt: observed.append(("start", prompt))
    cli._ensure_runtime_credentials = lambda: True
    cli._background_duet_for = lambda duet_id, prompt: (
        observed.append(("find", duet_id, prompt)) or context
    )
    cli._run_background_duet_turn = lambda found, prompt: observed.append(
        ("continue", found, prompt)
    )

    assert OpenChiaCLI.process_command(cli, "/bg compare these ideas") is True
    assert OpenChiaCLI.process_command(
        cli,
        "/bg send duet_20260930_ab12cd refine the stopping rule",
    ) is True
    assert observed == [
        ("start", "compare these ideas"),
        ("find", "duet_20260930_ab12cd", "refine the stopping rule"),
        ("continue", context, "refine the stopping rule"),
    ]


def test_queue_command_feeds_the_foreground_duet_turn_queue():
    cli = OpenChiaCLI.__new__(OpenChiaCLI)
    cli._pending_input = Queue()
    cli._agent_running = True
    cli._pending_resume_sessions = None
    cli._expand_paste_references = lambda text: text

    assert OpenChiaCLI.process_command(
        cli,
        "/queue revisit the progress measure",
    ) is True
    assert cli._pending_input.get_nowait() == "revisit the progress measure"


def test_background_context_is_bound_through_an_openchia_host(monkeypatch):
    observed = {}

    class Agent:
        def __init__(self, **kwargs):
            observed["agent_kwargs"] = kwargs

        def close(self):
            observed["agent_closed"] = True

    class Host:
        def __init__(self, **kwargs):
            observed["host_kwargs"] = kwargs

        def bind_duet(self, agent):
            observed["bound"] = agent
            agent.bound_as_duet = True
            return agent

        def close(self):
            observed["host_closed"] = True

    monkeypatch.setattr("run_agent.AIAgent", Agent)
    monkeypatch.setattr("hermes_cli.openchia_cli.OpenChiaHost", Host)

    cli = OpenChiaCLI.__new__(OpenChiaCLI)
    cli._background_task_counter = 0
    cli._agent_running = False
    cli._app = None
    cli._background_duet_agent_kwargs = lambda duet_id, prompt: {
        "session_id": duet_id,
        "parent_session_id": "foreground",
    }
    cli._tool_names = lambda agent: ("web_search",)

    context = cli._create_background_duet(
        "duet_20260930_ab12cd",
        "explore a second thought",
    )

    assert context.agent.bound_as_duet is True
    assert context.host is not None
    assert observed["agent_kwargs"]["session_id"] == "duet_20260930_ab12cd"
    assert observed["host_kwargs"]["session_id"] == "duet_20260930_ab12cd"
    assert observed["bound"] is context.agent


def test_episode_configuration_changes_are_path_level_and_keep_provenance():
    changes = episode_configuration_changes(
        {
            "goal": "old",
            "progress": {"metric": "coverage", "target": 0.5},
            "unit": "one cycle",
        },
        {
            "goal": "new",
            "progress": {"metric": "coverage", "target": 0.8},
            "result": "one workflow",
        },
        field_metadata={
            "goal": {"provenance": "llm_proposal"},
            "progress.target": {"provenance": "human_input"},
            "result": {"provenance": "llm_proposal"},
        },
    )

    assert [(item["path"], item["kind"]) for item in changes] == [
        ("goal", "changed"),
        ("progress.target", "changed"),
        ("result", "added"),
        ("unit", "removed"),
    ]
    assert changes[0]["provenance"] == "llm_proposal"
    assert changes[1]["before"] == 0.5
    assert changes[1]["after"] == 0.8


def test_episode_read_executes_immediately_during_duet_turn():
    observed = []

    class Buffer:
        def reset(self, *, append_to_history=False):
            observed.append(("reset", append_to_history))

    class App:
        current_buffer = Buffer()

        def invalidate(self):
            observed.append(("invalidate", True))

    cli = OpenChiaCLI.__new__(OpenChiaCLI)
    cli._agent_running = True
    cli.process_command = lambda command: observed.append(("command", command))
    event = SimpleNamespace(app=App())

    assert cli._tui_enter_inline_command(event, "/episode", False) is True
    assert observed == [
        ("command", "/episode"),
        ("reset", True),
        ("invalidate", True),
    ]


def test_answer_command_records_and_exposes_exact_artifact_to_duet():
    observed = {}

    class Host:
        def record_human_answer(self, field_path, value):
            observed["answer"] = (field_path, value)
            return SimpleNamespace(
                field_path=field_path,
                answer_id=SimpleNamespace(value="answer_" + "a" * 64),
            )

    cli = OpenChiaCLI.__new__(OpenChiaCLI)
    cli._openchia_host = Host()
    cli._pending_agent_seed = None
    cli._print_openchia = lambda text: observed.setdefault("printed", text)
    cli._refresh_openchia = lambda: observed.setdefault("refreshed", True)

    assert OpenChiaCLI.process_command(
        cli,
        '/answer goal "Design the measured workflow."',
    ) is True
    assert observed["answer"] == ("goal", "Design the measured workflow.")
    assert "answer_" + "a" * 64 in cli._pending_agent_seed
    assert "duet_answer" in cli._pending_agent_seed
