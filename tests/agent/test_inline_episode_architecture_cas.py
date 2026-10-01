"""The Architecture-submit executor folds model spellings of "no draft yet" onto None.

A live Duet (2026-10-01) sent its first-draft CAS guard as the string ``"null"``
(then ``""`` and ``"none"``) — on the then-current tool that field was
``expected_workflow_hash``; on ``episode_architecture_submit`` it is
``expected_content_hash`` beside ``expected_artifact_id`` / ``expected_revision``.
The host compared against ``None`` and rejected all six submissions as conflicts.
The CAS fields are ``string | null`` (``integer | null``), and a real draft identity
never spells like those words, so folding them is safe.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent.inline_tool_executors import _absent_draft_field, _episode_architecture_submit


def _run(args: dict) -> tuple[dict, list[dict]]:
    seen: list[dict] = []

    def submitter(**kwargs):
        seen.append(kwargs)
        return {"accepted": True, "revision": 1}

    agent = SimpleNamespace(_episode_architecture_submitter=submitter)
    result = json.loads(_episode_architecture_submit(agent, args, ctx=None))
    return result, seen


@pytest.mark.parametrize("spelling", ["null", "NULL", "none", "", "  null "])
def test_string_spellings_of_absence_become_none(spelling):
    assert _absent_draft_field(spelling) is None


@pytest.mark.parametrize("value", [None, "sha256:abc", "artifact_1", 3, 0, False, ["null"]])
def test_real_values_pass_through_unchanged(value):
    assert _absent_draft_field(value) is value


def test_first_draft_with_string_null_fields_reaches_the_host_as_none():
    result, seen = _run({
        "candidate_workflow_architecture": {"episodes": []},
        "expected_artifact_id": "null",
        "expected_content_hash": "null",
        "expected_revision": "none",
        "human_note_ids": [],
    })
    assert result["accepted"] is True
    assert seen[0]["expected_artifact_id"] is None
    assert seen[0]["expected_content_hash"] is None
    assert seen[0]["expected_revision"] is None


def test_real_draft_identity_is_still_required_to_move_together():
    result, seen = _run({
        "candidate_workflow_architecture": {"episodes": []},
        "expected_artifact_id": "artifact_1",
        "expected_content_hash": "null",   # folded to None -> mismatched with artifact_id
        "expected_revision": 2,
        "human_note_ids": [],
    })
    assert result["accepted"] is False
    assert result["reason"] == "ValueError"
    assert seen == []


def test_exact_draft_identity_passes_through():
    result, seen = _run({
        "candidate_workflow_architecture": {"episodes": []},
        "expected_artifact_id": "artifact_1",
        "expected_content_hash": "sha256:" + "0" * 64,
        "expected_revision": 2,
        "human_note_ids": [],
    })
    assert result["accepted"] is True
    assert seen[0]["expected_revision"] == 2
