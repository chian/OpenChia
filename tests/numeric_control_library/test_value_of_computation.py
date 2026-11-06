"""Behavioral tests of posterior learning and adaptive computation selection."""

from copy import deepcopy
import json
import math
import unittest

from numeric_control_library.value_of_computation import (
    BayesianTransitionModel,
    Prediction,
    Transition,
    value_of_computation,
)


def learn(model, state, action, following, n=1, *, prefix=None, status="confirmed"):
    for i in range(n):
        model.observe(
            f"{prefix or state + ':' + action + ':' + following}:{i}",
            state=state,
            action=action,
            next_state=following,
            status=status,
            evidence_refs=["test:executed-transition"],
        )


def diagnosis_model():
    model = BayesianTransitionModel()
    for state, score, actions in [
        ("unknown_defect", 0, ("diagnose", "blind_revision", "novel_action")),
        ("left_defect", 0, ("fix_left", "fix_right")),
        ("right_defect", 0, ("fix_left", "fix_right")),
        ("qualified", 1, ()),
        ("failed", 0, ()),
    ]:
        model.register_state(state, score=score, actions=actions)
    learn(model, "unknown_defect", "diagnose", "left_defect", 5)
    learn(model, "unknown_defect", "diagnose", "right_defect", 5)
    learn(model, "unknown_defect", "blind_revision", "qualified", 5)
    learn(model, "unknown_defect", "blind_revision", "failed", 5)
    for state, correct in [("left_defect", "fix_left"), ("right_defect", "fix_right")]:
        for action in model.actions(state):
            learn(
                model, state, action, "qualified" if action == correct else "failed", 3
            )
    return model


def estimates(report):
    return {item.action: item for item in report.estimates}


class ValueOfComputationTests(unittest.TestCase):
    def test_diagnosis_is_valuable_only_through_adaptive_followup(self):
        model = diagnosis_model()
        myopic = value_of_computation(model, "unknown_defect", lookahead=1)
        adaptive = value_of_computation(model, "unknown_defect", lookahead=2)
        self.assertEqual(myopic.best_modeled_action, "blind_revision")
        self.assertEqual(estimates(myopic)["diagnose"].expected_gain, 0)
        self.assertEqual(adaptive.best_modeled_action, "diagnose")
        diagnosis = estimates(adaptive)["diagnose"]
        self.assertEqual(diagnosis.immediate_gain, 0)
        self.assertEqual(diagnosis.continuation_gain, 1)
        self.assertEqual(diagnosis.expected_gain, 1)
        self.assertEqual(diagnosis.probability_improvement, 1)
        self.assertEqual(diagnosis.predictive_stddev, 0)
        self.assertIn("unknown_defect:diagnose:left_defect:0", diagnosis.evidence_ids)
        self.assertIn("left_defect:fix_left:qualified:0", diagnosis.evidence_ids)

    def test_planning_updates_beliefs_without_contaminating_real_observations(self):
        model = BayesianTransitionModel()
        model.register_state("start", score=0, actions=("uncertain", "safe"))
        model.register_state("success", score=1)
        model.register_state("safe_result", score=0.4)
        model.declare_prior(
            "start",
            "uncertain",
            {"start": 1, "success": 1},
            evidence_refs=["declared:beta(1,1)"],
        )
        learn(model, "start", "safe", "safe_result")
        before = model.snapshot()
        report = value_of_computation(model, "start", lookahead=2)
        # Initially p(success)=1/2. After one failure p(success)=1/3,
        # so continuation chooses the .4 safe option, not another uncertain try.
        self.assertAlmostEqual(
            estimates(report)["uncertain"].expected_gain, 0.5 * 1 + 0.5 * 0.4
        )
        self.assertAlmostEqual(estimates(report)["uncertain"].immediate_gain, 0.5)
        self.assertAlmostEqual(estimates(report)["uncertain"].continuation_gain, 0.2)
        self.assertEqual(model.snapshot(), before)
        learn(model, "start", "uncertain", "start")
        next_report = value_of_computation(model, "start", lookahead=1)
        self.assertAlmostEqual(estimates(next_report)["uncertain"].expected_gain, 1 / 3)
        self.assertEqual(next_report.best_modeled_action, "safe")

    def test_retraction_can_enable_repair_despite_a_negative_first_gain(self):
        model = BayesianTransitionModel()
        model.register_state("provisional", score=0.4, actions=("check",))
        model.register_state("diagnosed_invalid", score=0, actions=("repair",))
        model.register_state("qualified", score=1)
        learn(model, "provisional", "check", "diagnosed_invalid")
        learn(model, "diagnosed_invalid", "repair", "qualified")
        myopic = value_of_computation(model, "provisional", lookahead=1)
        self.assertAlmostEqual(myopic.estimates[0].expected_gain, -0.4)
        self.assertIsNone(myopic.best_modeled_action)
        adaptive = value_of_computation(model, "provisional", lookahead=2)
        self.assertEqual(adaptive.best_modeled_action, "check")
        self.assertAlmostEqual(adaptive.estimates[0].expected_gain, 0.6)
        self.assertAlmostEqual(adaptive.estimates[0].immediate_gain, -0.4)
        self.assertAlmostEqual(adaptive.estimates[0].continuation_gain, 1)

    def test_recycling_provisional_scores_cannot_create_reward(self):
        model = BayesianTransitionModel()
        model.register_state("credited", score=0.4, actions=("retract",))
        model.register_state("empty", score=0, actions=("recreate",))
        learn(model, "credited", "retract", "empty")
        learn(model, "empty", "recreate", "credited")
        for depth in (2, 3, 6):
            report = value_of_computation(model, "credited", lookahead=depth)
            self.assertEqual(report.estimates[0].expected_gain, 0)
            self.assertIsNone(report.best_modeled_action)

    def test_unknown_does_not_become_zero_or_a_stop_signal(self):
        model = BayesianTransitionModel()
        model.register_state("new", score=0, actions=("try",))
        report = value_of_computation(model, "new")
        self.assertIsNone(report.estimates[0].expected_gain)
        self.assertEqual(report.unmodeled_decisions, (("new", "try"),))
        self.assertEqual(report.recommendation, "unmodeled_options")
        self.assertNotIn("stop", report.as_record())

    def test_unmodeled_followups_remain_visible_beyond_first_action(self):
        model = BayesianTransitionModel()
        model.register_state("before", score=0, actions=("diagnose",))
        model.register_state("after", score=0, actions=("new_revision",))
        learn(model, "before", "diagnose", "after")
        report = value_of_computation(model, "before", lookahead=2)
        self.assertEqual(report.estimates[0].expected_gain, 0)
        self.assertEqual(
            report.estimates[0].unmodeled_decisions, (("after", "new_revision"),)
        )
        self.assertEqual(report.recommendation, "unmodeled_options")

    def test_value_is_expected_adaptive_score_not_clairvoyant_maximum(self):
        model = BayesianTransitionModel()
        model.register_state("before", score=0, actions=("choose",))
        model.register_state("decision", score=0, actions=("left", "right"))
        model.register_state("good", score=1)
        model.register_state("bad", score=0)
        learn(model, "before", "choose", "decision")
        for action in ("left", "right"):
            learn(model, "decision", action, "good")
            learn(model, "decision", action, "bad")
        report = value_of_computation(model, "before", lookahead=2)
        self.assertEqual(report.estimates[0].expected_gain, 0.5)
        self.assertEqual(report.estimates[0].predictive_stddev, 0.5)

    def test_model_state_can_retain_a_discovery_without_changing_score(self):
        model = diagnosis_model()
        self.assertEqual(model.score("unknown_defect"), model.score("left_defect"))
        self.assertNotEqual(
            model.actions("unknown_defect"), model.actions("left_defect")
        )
        self.assertEqual(
            value_of_computation(model, "left_defect").best_modeled_action, "fix_left"
        )


class ObservationJournalTests(unittest.TestCase):
    def setUp(self):
        self.model = BayesianTransitionModel()
        self.model.register_state("before", score=0, actions=("build",))
        self.model.register_state("credited", score=0.4)
        self.model.register_state("invalid", score=0)

    def observe(self, **kwargs):
        return self.model.observe(
            "attempt",
            state="before",
            action="build",
            evidence_refs=["evidence:attempt"],
            **kwargs,
        )

    def test_promotion_corrects_same_sample_and_does_not_multiply_credit(self):
        self.observe(next_state="credited", status="provisional")
        self.observe(next_state="credited", status="confirmed", revision=1)
        self.assertFalse(
            self.observe(next_state="credited", status="confirmed", revision=1)
        )
        learn(self.model, "before", "build", "invalid", prefix="independent-failure")
        self.assertEqual(
            value_of_computation(self.model, "before").estimates[0].expected_gain, 0.2
        )
        self.assertEqual(len(self.model.observation_history()), 3)

    def test_correction_replaces_origin_return_without_second_negative_sample(self):
        self.observe(next_state="credited", status="provisional")
        self.assertEqual(
            value_of_computation(self.model, "before").estimates[0].expected_gain, 0.4
        )
        self.observe(next_state="invalid", status="confirmed", revision=1)
        prediction = self.model.predict("before", "build")
        self.assertEqual(prediction.transitions, (Transition(1, "invalid"),))
        self.assertEqual(
            value_of_computation(self.model, "before").estimates[0].expected_gain, 0
        )
        self.assertEqual(len(self.model.observation_history()), 2)

    def test_pending_is_not_a_failed_observation_and_withdrawal_is_not_failure(self):
        self.observe(status="pending")
        self.assertIsNone(self.model.predict("before", "build"))
        self.observe(next_state="credited", revision=1, status="provisional")
        self.observe(revision=2, status="withdrawn")
        self.assertIsNone(self.model.predict("before", "build"))
        self.assertEqual(len(self.model.observation_history()), 3)

    def test_replay_preserves_revisions_and_forecasts(self):
        self.observe(status="pending")
        self.observe(next_state="credited", status="provisional", revision=1)
        self.observe(next_state="invalid", status="confirmed", revision=2)
        snapshot = json.loads(json.dumps(self.model.snapshot()))
        restored = BayesianTransitionModel.from_snapshot(snapshot)
        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual(
            value_of_computation(restored, "before"),
            value_of_computation(self.model, "before"),
        )
        snapshot["journal"][-1]["arguments"]["revision"] = 7
        with self.assertRaisesRegex(ValueError, "revision"):
            BayesianTransitionModel.from_snapshot(snapshot)

    def test_stale_or_cross_origin_corrections_are_rejected_without_mutation(self):
        self.observe(next_state="credited")
        before = self.model.snapshot()
        for revision in (0, 2, -1, True):
            with self.assertRaises(ValueError):
                self.observe(next_state="invalid", revision=revision)
        self.model.register_state("other", score=0, actions=("build",))
        before = self.model.snapshot()
        with self.assertRaisesRegex(ValueError, "origin"):
            self.model.observe(
                "attempt",
                state="other",
                action="build",
                next_state="invalid",
                revision=1,
                evidence_refs=["evidence:correction"],
            )
        self.assertEqual(self.model.snapshot(), before)

    def test_states_and_evidence_are_defensively_copied(self):
        metadata = {"retained_results": ["control:1"]}
        self.model.register_state("facts", score=0, metadata=metadata)
        metadata["retained_results"].append("invented")
        snapshot = self.model.snapshot()
        self.assertEqual(
            snapshot["journal"][-1]["arguments"]["metadata"],
            {"retained_results": ["control:1"]},
        )
        snapshot["journal"].clear()
        self.assertTrue(self.model.snapshot()["journal"])
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.model.register_state("facts", score=1)


class ModelContractTests(unittest.TestCase):
    def test_invalid_predictive_models_are_rejected(self):
        class Model:
            def score(self, state):
                return 0

            def actions(self, state):
                return ("try",)

            def predict(self, state, action, history):
                return self.prediction

        model = Model()
        for transitions in [
            (),
            (Transition(0.2, "s"),),
            (Transition(float("nan"), "s"),),
            (Transition(-1, "s"),),
            (Transition(True, "s"),),
        ]:
            model.prediction = Prediction(transitions, "declared-test")
            with self.assertRaises(ValueError):
                value_of_computation(model, "s")
        for depth in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                value_of_computation(
                    diagnosis_model(), "unknown_defect", lookahead=depth
                )

    def test_explicit_priors_are_frozen_and_not_fabricated_observations(self):
        model = diagnosis_model()
        model.declare_prior(
            "unknown_defect",
            "novel_action",
            {"qualified": 1, "failed": 3},
            evidence_refs=["prior:declared-assumption"],
        )
        self.assertEqual(
            estimates(value_of_computation(model, "unknown_defect", lookahead=1))[
                "novel_action"
            ].expected_gain,
            0.25,
        )
        with self.assertRaisesRegex(ValueError, "frozen"):
            model.declare_prior(
                "unknown_defect",
                "novel_action",
                {"qualified": 99},
                evidence_refs=["prior:changed"],
            )

    def test_out_of_support_observation_falsifies_the_declared_prior(self):
        model = diagnosis_model()
        model.declare_prior(
            "unknown_defect",
            "novel_action",
            {"qualified": 1},
            evidence_refs=["prior:closed"],
        )
        before = model.snapshot()
        with self.assertRaisesRegex(ValueError, "outside declared prior support"):
            learn(model, "unknown_defect", "novel_action", "failed")
        self.assertEqual(model.snapshot(), before)

    def test_prior_cannot_discard_an_existing_observed_outcome(self):
        model = diagnosis_model()
        with self.assertRaisesRegex(ValueError, "excludes an already observed outcome"):
            model.declare_prior(
                "unknown_defect",
                "diagnose",
                {"left_defect": 1},
                evidence_refs=["prior:bad"],
            )


if __name__ == "__main__":
    unittest.main()
