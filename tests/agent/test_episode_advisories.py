"""Key Concept 12 (#82): advise when an Episode has no stopping decision."""

from __future__ import annotations

from types import SimpleNamespace

from agent.episode_advisories import one_shot_signals, workflow_advisories


def _contract(stopping, unit="One unit.", **continuation):
    return SimpleNamespace(stopping=stopping, unit=unit, numeric_control=SimpleNamespace(
        continuation=SimpleNamespace(arguments=continuation)))


def _workflow(*contracts):
    return SimpleNamespace(episodes=tuple(SimpleNamespace(local_id=f"e{i}", contract=c) for i, c in enumerate(contracts)))


PROBE = _contract(
    "Deterministic two-unit plan: the probe list is fixed at [asm_health, asm_collections]. After unit 2 the "
    "plan is exhausted, so predicted next marginal credit and its upper bound are 0.0 and the Episode closes. "
    "No model judgement participates in continuation.",
    max_predicted_marginal_hypervolume=0.0,
)
ITERATIVE = _contract(
    "Continue querying collections while paired-incidence rarefaction predicts new distinct passages; stop when the "
    "upper bound of the predicted marginal credit falls below 0.02.",
    unit="One query against the next most promising collection.",
    max_predicted_marginal_hypervolume=0.02,
)


def test_the_bring_up_probe_is_flagged_as_one_shot() -> None:
    (finding,) = workflow_advisories(_workflow(PROBE))
    assert finding["code"] == "episode_without_stopping_decision" and finding["blocking"] is False
    assert finding["episode_local_id"] == "e0"
    assert {"fixed_plan", "plan_exhausted", "zero_continuation_threshold"} <= set(finding["signals"])
    assert "tool" in finding["detail"]


def test_an_iterative_episode_is_not_flagged() -> None:
    assert one_shot_signals(ITERATIVE) == []
    assert workflow_advisories(_workflow(ITERATIVE)) == []


def test_a_single_weak_signal_is_not_enough() -> None:
    weak = _contract("Stop when the upper bound of predicted credit reaches zero.", max_predicted_marginal_hypervolume=0.0)
    assert one_shot_signals(weak) == ["zero_continuation_threshold"]
    assert workflow_advisories(_workflow(weak)) == []


def test_no_workflow_means_no_advice() -> None:
    assert workflow_advisories(None) == []


def test_duet_guidance_states_the_rule() -> None:
    from agent.prompt_builder import DUET_PROTOCOL_GUIDANCE

    assert "real stopping decision" in DUET_PROTOCOL_GUIDANCE
    assert "episode_without_stopping_decision" in DUET_PROTOCOL_GUIDANCE
