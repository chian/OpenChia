"""Measured returns reach adaptive Episode choices through the registered adapter."""

from copy import deepcopy
import json
from math import comb

import pytest

from episode_builder.planner import materializer_function_catalog
from function_library import FunctionImplementation
from method_loop import (
    Context,
    ControllerRuntime,
    Episode,
    EpisodeGoal,
    EpisodeRequest,
    EpisodeTree,
    Grain,
    Leaf,
)
from numeric_control_library import (
    COMPOSE_COMPUTATION_CONTROLLER,
    BayesianTransitionModel,
    ComputationAdvisor,
    ComputationInput,
    ComputationObservation,
    ComputationState,
)
from numeric_control_library.controller import controller_function_library


class ThresholdWorld:
    """Executed finite verifier; its two defects have identical measured scores."""

    def __init__(self, threshold):
        self.threshold, self.known = threshold, False

    def measurement(self):
        controls = [
            (sum(comb(4, k) for k in range(count, 5)) <= 5, count >= self.threshold)
            for count in (0, 1, 3, 4)
        ]
        score = (
            sum(observed for expected, observed in controls if expected) / 2
            + sum(not observed for expected, observed in controls if not expected) / 2
            - 1
        )
        if score == 1:
            name, actions = "qualified", ()
        elif score == 0:
            name, actions = "damaged", ()
        elif self.known:
            name = "too_strict" if self.threshold == 4 else "too_permissive"
            actions = ("lower", "raise", "untried")
        else:
            name, actions = "unknown", ("diagnose", "lower", "raise", "untried")
        return ComputationState(
            name, score, ("fixture:measured-binomial-controls:" + name,), actions
        )

    def execute(self, action, event_id):
        before = self.measurement()
        if action == "diagnose":
            self.known = True
        elif action in ("lower", "raise"):
            self.threshold += -1 if action == "lower" else 1
        elif action != "untried":
            raise ValueError("unavailable action")
        after = self.measurement()
        return ComputationInput(
            after,
            (
                ComputationObservation(
                    event_id,
                    before,
                    action,
                    after,
                    ("execution:" + event_id,),
                ),
            ),
        )


@pytest.mark.parametrize("threshold,repair", [(4, "lower"), (1, "raise")])
def test_registered_connection_drives_real_episode_choices_from_measured_returns(
    threshold, repair
):
    definition = next(
        item
        for item in materializer_function_catalog()
        if item["definition_id"] == COMPOSE_COMPUTATION_CONTROLLER.definition_id
    )
    implementation = definition["implementation"]
    compose = FunctionImplementation(
        implementation["module"], implementation["symbol"], implementation["is_async"]
    ).load()
    assert controller_function_library.evaluation_report(
        COMPOSE_COMPUTATION_CONTROLLER.component_id
    ).passed
    training = ComputationAdvisor(
        epoch="fixture", initial_state=ThresholdWorld(4).measurement()
    )
    for original in (4, 1):
        for known in (False, True):
            for action in (
                ("lower", "raise") if known else ("diagnose", "lower", "raise")
            ):
                world = ThresholdWorld(original)
                world.known = known
                transition = world.execute(
                    action, f"training:{original}:{known}:{action}"
                )
                training.observe("training", transition, is_root=True)

    world = ThresholdWorld(threshold)
    initial = world.measurement()
    arguments = COMPOSE_COMPUTATION_CONTROLLER.admit_arguments({"lookahead": 2})
    factory = compose(
        epoch="fixture",
        initial_state=initial,
        model_snapshot=training.snapshot()["model"],
        **arguments,
    )
    delivered, choices = [], []

    class Source:
        def next(self, view):
            feedback = view.controller_state
            delivered.append(feedback.as_record())
            # Completion follows the independently measured task condition.
            if world.measurement().score == 1:
                return None
            action = feedback.computation_value.best_modeled_action
            assert action in world.measurement().actions
            choices.append(action)
            event_id = f"held-out:{threshold}:{view.units_consumed}"
            return Leaf(
                action,
                lambda selected: world.execute(selected, event_id),
                lambda selected, measured: measured,
                event_id,
            )

    grain = Grain(
        "verifier_repair",
        "One chosen diagnostic or revision",
        "Measured control results",
        factory,
    )
    goal = EpisodeGoal.for_grain(
        grain, objective={"task": "Pass the independent binomial controls"}
    )
    episode = Episode(
        grain,
        "held-out",
        Source(),
        EpisodeRequest(goal, initial),
        build_result=lambda record: record.controller_state,
    )
    record = episode.run(
        Context(tree=EpisodeTree(grain, {}), run_id=f"held-out:{threshold}")
    )
    assert choices == ["diagnose", repair]
    assert delivered[0]["current_score"] == delivered[1]["current_score"] == 0.5
    assert delivered[0]["current_state"] != delivered[1]["current_state"]
    diagnosis = next(
        item
        for item in delivered[0]["computation_value"]["estimates"]
        if item["action"] == "diagnose"
    )
    assert diagnosis["immediate_gain"] == 0
    assert diagnosis["expected_gain"] == 0.5
    assert any(
        item["action"] == "untried" and item["expected_gain"] is None
        for item in delivered[0]["computation_value"]["estimates"]
    )
    assert [item["score_delta"] for item in delivered[-1]["credit_history"][-2:]] == [
        0,
        0.5,
    ]
    assert record.controller_state.current_score == 1
    assert record.ended_by == "exhausted"
    assert not any(unit.controller_step.stop for unit in record.unit_records)
    assert record.unit_records[0].controller_input.observations[0].evidence_refs


def test_corrections_replay_atomic_updates_and_scope_isolation():
    before = ComputationState("before", 0, ("measurement:before",), ("build",))
    credited = ComputationState("credited", 1, ("measurement:credited",))
    invalid = ComputationState("invalid", 0, ("measurement:invalid",))
    current = ComputationState("current", 0.4, ("measurement:current",), ("novel",))
    compose = controller_function_library.resolve(
        COMPOSE_COMPUTATION_CONTROLLER.component_id
    ).load()
    factory = compose(epoch="fixed", initial_state=before)
    runtime = ControllerRuntime()
    first = runtime.open_scope((("task", "first"),), factory)
    second = runtime.open_scope((("task", "second"),), factory)
    other = runtime.controller(second).snapshot()
    provisional = ComputationObservation(
        "attempt",
        before,
        "build",
        credited,
        ("measurement:provisional",),
        status="provisional",
    )
    runtime.advance(first, "initial return", ComputationInput(credited, (provisional,)))
    correction = ComputationObservation(
        "attempt", before, "build", invalid, ("measurement:correction",), revision=1
    )
    # A historical correction and the actual current state are separate inputs.
    corrected = runtime.advance(
        first, "check", ComputationInput(current, (correction,))
    )
    assert corrected.current_state == "current" and corrected.current_score == 0.4
    assert [item["score_delta"] for item in corrected.credit_history] == [1, 0]
    model = BayesianTransitionModel.from_snapshot(
        runtime.controller(first).snapshot()["model"]
    )
    assert [
        (item.probability, item.next_state)
        for item in model.predict("before", "build").transitions
    ] == [(1, "invalid")]
    saved = json.loads(json.dumps(runtime.controller(first).snapshot()))
    restored = ComputationAdvisor.from_snapshot(saved)
    assert restored.state() == corrected
    restored.observe(
        "duplicate delivery", ComputationInput(current, (correction,)), is_root=True
    )
    assert json.loads(json.dumps(restored.snapshot())) == saved
    assert runtime.controller(second).snapshot() == other
    assert runtime.state(second).computation_value.estimates[0].expected_gain is None

    pending = ComputationObservation(
        "pending", before, "build", None, ("measurement:pending",), status="pending"
    )
    withdrawal = ComputationObservation(
        "attempt",
        before,
        "build",
        None,
        ("measurement:withdrawal",),
        revision=2,
        status="withdrawn",
    )
    restored.observe(
        "withdraw", ComputationInput(before, (pending, withdrawal)), is_root=True
    )
    feedback = restored.state()
    assert feedback.computation_value.estimates[0].expected_gain is None
    assert feedback.credit_history[-1]["score_delta"] is None
    assert not feedback.stop and not feedback.requests_transition

    unchanged = restored.snapshot()
    valid_first = ComputationObservation(
        "new-attempt", before, "build", invalid, ("measurement:new-attempt",)
    )
    with pytest.raises(ValueError, match="revision"):
        restored.observe(
            "bad batch",
            ComputationInput(current, (valid_first, correction)),
            is_root=True,
        )
    assert restored.snapshot() == unchanged
    with pytest.raises(ValueError, match="immutable"):
        restored.observe(
            "bad state",
            ComputationInput(
                ComputationState("before", 2, ("measurement:different",), ("build",))
            ),
            is_root=True,
        )
    assert restored.snapshot() == unchanged
    with pytest.raises(ValueError, match="remapped"):
        restored.transitioned("another-objective")
    tampered = deepcopy(unchanged)
    tampered["current_state"]["state_id"] = "not-in-the-journal"
    with pytest.raises(ValueError, match="not present"):
        ComputationAdvisor.from_snapshot(tampered)
