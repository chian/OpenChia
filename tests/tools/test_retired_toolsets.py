"""Toolsets this fork removed must be ignored, not reported as typos at startup."""
from __future__ import annotations

from toolsets import RETIRED_TOOLSETS, TOOLSETS, validate_toolset


def test_delegation_is_retired_and_not_a_live_toolset():
    assert "delegation" in RETIRED_TOOLSETS
    assert "delegation" not in TOOLSETS
    assert validate_toolset("delegation") is False


def test_retired_names_never_overlap_live_toolsets():
    assert not (RETIRED_TOOLSETS & set(TOOLSETS))


def test_early_platform_validator_ignores_retired_names(monkeypatch, caplog):
    """``_warn_all_invalid_platform_toolsets`` runs before ``_init_toolsets``; a platform list
    that is only retired names must stay silent, and a mixed list must name only the typo."""
    import logging

    from openchia_cli import tools_config

    monkeypatch.setattr(tools_config, "_warned_invalid_platform_toolsets", set())
    with caplog.at_level(logging.WARNING, logger=tools_config.logger.name):
        tools_config._warn_all_invalid_platform_toolsets("cli", ["delegation"])
    assert caplog.records == []

    caplog.clear()
    monkeypatch.setattr(tools_config, "_warned_invalid_platform_toolsets", set())
    with caplog.at_level(logging.WARNING, logger=tools_config.logger.name):
        tools_config._warn_all_invalid_platform_toolsets("cli", ["delegation", "no_such_toolset"])
    assert len(caplog.records) == 1
    assert "no_such_toolset" in caplog.records[0].getMessage()
    assert "delegation" not in caplog.records[0].getMessage()

    live = next(iter(TOOLSETS))  # any toolset that really exists in this build
    caplog.clear()
    monkeypatch.setattr(tools_config, "_warned_invalid_platform_toolsets", set())
    with caplog.at_level(logging.WARNING, logger=tools_config.logger.name):
        tools_config._warn_all_invalid_platform_toolsets("cli", ["delegation", live])
    assert caplog.records == []
