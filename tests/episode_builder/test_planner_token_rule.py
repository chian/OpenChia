"""The planner prompt states the exact closed-token rule that
HandoffPayloadContract enforces, so a plan cannot be admission-rejected for a
URL path written into state_values (seen live: ``state_values.asm_collections_path
must contain closed lowercase tokens``)."""

from __future__ import annotations

import re

from episode_builder import planner
from handoff_library import contracts


def test_prompt_quotes_the_enforced_token_pattern() -> None:
    pattern = contracts._TOKEN.pattern
    assert pattern in planner._PLANNER_SYSTEM_PROMPT
    assert "/api/v1/collections" in planner._PLANNER_SYSTEM_PROMPT


def test_the_examples_in_the_prompt_satisfy_the_rule() -> None:
    for token in ("api.v1.collections", "get"):
        assert contracts._TOKEN.fullmatch(token), token
    assert not contracts._TOKEN.fullmatch("/ragstack/asm-next/api/v1/collections")
