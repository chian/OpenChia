"""The Duet banner names the version and exact commit of the running code."""

from __future__ import annotations

from openchia_cli import duet_cli
from openchia_cli.version_info import VersionInfo


def test_identity_text_names_version_branch_and_commit(monkeypatch) -> None:
    info = VersionInfo("0.0.0", "0.0.0+12.g80bacaaa", 12, "80bacaaa6880f39b7b297f39835", "main", "git", dirty=True)
    monkeypatch.setattr("openchia_cli.version_info.get_version_info", lambda: info)
    assert duet_cli.code_identity_text() == "0.0.0+12 · main@80bacaaa68+dirty"


def test_tagless_checkout_shows_branch_and_commit_once(monkeypatch) -> None:
    info = VersionInfo("unknown", "git.a335059.dirty", None, "a335059aee0123456789", "main", "git", dirty=True)
    monkeypatch.setattr("openchia_cli.version_info.get_version_info", lambda: info)
    assert duet_cli.code_identity_text() == "main@a335059aee+dirty"


def test_identity_text_degrades_to_unknown(monkeypatch) -> None:
    def boom():
        raise RuntimeError("no provenance")

    monkeypatch.setattr("openchia_cli.version_info.get_version_info", boom)
    assert duet_cli.code_identity_text() == "version unknown"


def test_welcome_line_carries_the_identity(monkeypatch) -> None:
    monkeypatch.setattr(duet_cli, "code_identity_text", lambda: "0.0.0+12 · main@80bacaaa68")
    text, _ = duet_cli.OpenChiaCLI._tui_welcome_branding(object(), None)
    assert text.startswith("OpenChia Duet ready (0.0.0+12 · main@80bacaaa68).")
