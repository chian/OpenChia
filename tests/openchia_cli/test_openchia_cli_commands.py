"""OpenChia's command surface must inherit every exit spelling the base CLI accepts.

`/exit` is the base CLI's alias of `/quit` (openchia_cli/commands.py), but OpenChia's
inherited-command allowlist only carried `/quit`, so `/exit` was rejected with
"That command is outside the OpenChia Duet/Episode surface" and the only way out
was `/quit` or Ctrl+C.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from openchia_cli.duet_cli import OpenChiaCLI


def _stub():
    return SimpleNamespace(
        _openchia_commands=OpenChiaCLI._openchia_commands,
        _inherited_commands=OpenChiaCLI._inherited_commands,
    )


@pytest.mark.parametrize("command", ["/exit", "/quit", "/EXIT", "/exit --delete"])
def test_exit_spellings_are_available(command):
    assert OpenChiaCLI._command_available(_stub(), command) is True


@pytest.mark.parametrize("command", ["/delegate", "/skills", "/tools"])
def test_non_surface_commands_stay_rejected(command):
    assert OpenChiaCLI._command_available(_stub(), command) is False


@pytest.mark.parametrize("state,command", [
    ("continuing", "/stop"),
    ("interrupted", "/run continue"),
    ("resource_limited", "/run continue"),
    ("cancelled", "/run continue"),
    ("cancelled_before_claim", "/run continue"),
    ("ownership_unknown", "/run status"),
    ("invalid", "/run evidence"),
])
def test_run_recovery_status_is_not_rendered_as_idle_verified_workflow(state, command):
    from openchia_cli.openchia_commands import render_openchia_status

    rendered = render_openchia_status({
        "episode_architecture": {"revision": 1}, "state": "sealed",
        "build": {"state": "verified"}, "run": {"state": state},
    })
    assert state in rendered
    assert command in rendered
    assert "Target Workflow verified" not in rendered
    if state == "ownership_unknown":
        assert "/run continue" not in rendered


@pytest.mark.parametrize("build_state,run_state,expected", [
    ("verified", "continuing", "run:continuing"),
    ("verified", "interrupted", "run:interrupted"),
    ("verified", "ownership_unknown", "run:ownership_unknown"),
    ("continuing", "interrupted", "build:continuing"),
])
def test_background_listing_exposes_the_same_recovery_state(build_state, run_state, expected):
    from threading import RLock
    from openchia_cli.openchia_background import OpenChiaBackgroundDuetsMixin

    output = []
    context = SimpleNamespace(
        duet_id="duet_saved", ordinal=1, thread=None, last_error=None, pending_prompts=[],
        host=SimpleNamespace(status=lambda: {
            "state": "sealed", "build": {"state": build_state}, "run": {"state": run_state},
        }),
    )
    cli = SimpleNamespace(
        _background_duets={context.duet_id: context}, _background_duets_lock=RLock(),
        _print_openchia=output.append,
    )
    OpenChiaBackgroundDuetsMixin._list_background_duets(cli)
    assert expected in output[0]
    assert ("/bg duet_saved run continue" in output[0]) == (expected == "run:interrupted")
