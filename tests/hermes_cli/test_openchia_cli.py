import sys

import pytest

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
