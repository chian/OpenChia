"""build_goal_state must return a method_loop.GoalState; the contract says so
and admission rejects a plain mapping before the Run. Regression for
``RuntimeLinkError: build_goal_state must return GoalState`` inside a Run."""

from __future__ import annotations

import ast

import method_loop
from episode_builder import admission, emitter


def test_contract_members_match_the_protocol() -> None:
    members = emitter._MODULE_CONTRACT["goal_state_protocol"]["members"]
    assert members == sorted(method_loop.GoalState.__protocol_attrs__)
    assert {"state_id", "preview", "commit"} <= set(members)
    assert "method_loop.GoalPreview" in admission.constructor_signatures()
    assert admission.constructor_signatures()["method_loop.GoalPreview"]["required"] == [
        "controller_input", "candidate_result_ids", "state_id",
    ]


def test_plain_mapping_return_is_a_deficit() -> None:
    found = admission._goal_state_return_deficits(ast.parse(
        "def build_goal_state(request, collaborators):\n"
        "    return {'probe_order': (), 'probe_ledger': Ledger()}\n"
    ))
    assert len(found) == 1 and "method_loop.GoalState" in found[0]
    assert admission._goal_state_return_deficits(ast.parse(
        "def build_goal_state(request, collaborators):\n    return types.MappingProxyType({})\n"
    ))


def test_protocol_object_returns_pass() -> None:
    assert admission._goal_state_return_deficits(ast.parse(
        "def build_goal_state(request, collaborators):\n    return ProbeGoalState(_PROBE_KEY_ORDER)\n"
    )) == ()
    assert admission._goal_state_return_deficits(ast.parse(
        "def build_goal_state(request, collaborators):\n    return ReasoningGoalState()\n"
    )) == ()
