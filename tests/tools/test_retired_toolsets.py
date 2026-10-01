"""Toolsets this fork removed must be ignored, not reported as typos at startup."""
from __future__ import annotations

from toolsets import RETIRED_TOOLSETS, TOOLSETS, validate_toolset


def test_delegation_is_retired_and_not_a_live_toolset():
    assert "delegation" in RETIRED_TOOLSETS
    assert "delegation" not in TOOLSETS
    assert validate_toolset("delegation") is False


def test_retired_names_never_overlap_live_toolsets():
    assert not (RETIRED_TOOLSETS & set(TOOLSETS))
