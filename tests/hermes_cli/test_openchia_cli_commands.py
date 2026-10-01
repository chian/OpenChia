"""OpenChia's command surface must inherit every exit spelling the base CLI accepts.

`/exit` is the base CLI's alias of `/quit` (hermes_cli/commands.py), but OpenChia's
inherited-command allowlist only carried `/quit`, so `/exit` was rejected with
"That command is outside the OpenChia Duet/Episode surface" and the only way out
was `/quit` or Ctrl+C.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from hermes_cli.openchia_cli import OpenChiaCLI


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
