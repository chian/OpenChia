import sys
from types import SimpleNamespace

import pytest

from hermes_cli.openchia_cli import OpenChiaCLI, render_openchia_status
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
