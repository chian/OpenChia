"""Reusable, finite-lookahead Bayesian value-of-computation yield estimation.

``value_of_computation(model, state, lookahead=...)`` compares the measured score
available now with the expected score after an action and adaptive continuation.
Scores are *terminal values*, not rewards to accumulate every time an artifact
is revisited. A useful diagnosis can therefore have zero immediate gain, and
temporary credit cannot be harvested by cycling through the same scores.

The model supplies states, available actions and posterior-predictive outcomes.
A state must retain information that changes subsequent decisions, even when
its score is unchanged. Hypothetical observations are passed back to the model
so Bayesian learning can affect decisions *inside* a forecast. This is not an
assumption that every failed attempt teaches something.

``BayesianTransitionModel`` is a small reference implementation: categorical
transitions with explicit Dirichlet pseudocounts and/or observed transitions.
Its event journal supports provisional observations, corrections and replay.
It makes no similarity assumptions between different states. Forecasts without
declared support are conditional on the outcomes observed so far; unobserved
possibilities have not been ruled out. Empty data is unknown, not zero yield.

Lookahead describes a forecast, never a limit on episode execution. This module
does not execute tools, stop episodes, impose run allowances, or award scores.
The caller owns scientific measurements and evidence qualification.

Background: Hay et al., Selecting Computations (2012),
https://proceedings.mlr.press/r10/hay12a.html ; Callaway et al., Learning to
Select Computations (2018), https://arxiv.org/abs/1711.06892 . Our finite-depth
posterior-predictive tree is an approximation, not their optimal policy.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass
from functools import lru_cache
import json
import math
from typing import Hashable, Mapping, Protocol

from function_library import (
    FunctionEvaluationReport,
    FunctionEvaluationSpec,
    FunctionImplementation,
    FunctionLibrary,
    FunctionScenarioOutcome,
    LibraryFunction,
    SourceSymbolReference,
)


VERSION = "1.0-posterior-predictive-voc"
__all__ = [
    "BayesianTransitionModel",
    "ComputationEstimate",
    "ComputationReport",
    "HypotheticalObservation",
    "Prediction",
    "PredictiveModel",
    "Transition",
    "value_of_computation",
    "VALUE_OF_COMPUTATION",
    "yield_estimator_function_library",
]


def _number(value, name):
    if (
        isinstance(value, bool)
        or not isinstance(value, (float, int))
        or not math.isfinite(value)
    ):
        raise ValueError(name + " must be a finite number")
    return float(value)


def _name(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + " must be a nonempty string")
    return value


def _json(value):
    return json.loads(json.dumps(value, allow_nan=False, sort_keys=True))


@dataclass(frozen=True)
class HypotheticalObservation:
    state: Hashable
    action: str
    next_state: Hashable


@dataclass(frozen=True)
class Transition:
    probability: float
    next_state: Hashable


@dataclass(frozen=True)
class Prediction:
    transitions: tuple[Transition, ...]
    basis: str
    evidence_ids: tuple[str, ...] = ()


class PredictiveModel(Protocol):
    """Injected model; predictions must not mutate actual observations.

    ``history`` contains only imagined outcomes along the current tree branch.
    Return None when an action lacks a predictive distribution. Correlated
    latent models can update their beliefs using the same history interface.
    """

    def score(self, state: Hashable) -> float: ...
    def actions(self, state: Hashable) -> tuple[str, ...]: ...
    def predict(
        self, state: Hashable, action: str, history: tuple[HypotheticalObservation, ...]
    ) -> Prediction | None: ...


@dataclass(frozen=True)
class ComputationEstimate:
    action: str
    expected_gain: float | None
    immediate_gain: float | None
    continuation_gain: float | None
    expected_terminal_score: float | None
    predictive_stddev: float | None
    probability_improvement: float | None
    basis: str
    evidence_ids: tuple[str, ...]
    unmodeled_decisions: tuple[tuple[Hashable, str], ...]


@dataclass(frozen=True)
class ComputationReport:
    current_score: float
    lookahead: int
    estimates: tuple[ComputationEstimate, ...]
    best_modeled_action: str | None
    recommendation: str
    unmodeled_decisions: tuple[tuple[Hashable, str], ...]
    version: str = VERSION

    def as_record(self):
        """JSON-compatible when the supplied state identities are JSON values."""
        return asdict(self)


def value_of_computation(
    model: PredictiveModel, state: Hashable, *, lookahead: int = 3
) -> ComputationReport:
    """Forecast action value, allowing adaptive follow-up and holding current work.

    Each action is forced for its own estimate, so negative gains are preserved.
    Subsequent decisions choose the largest *expected* terminal score, including
    the option to hold the then-current state. They do not see future outcomes.
    ``continuation_gain`` is the extra modeled benefit beyond the first action.
    ``predictive_stddev`` is outcome dispersion, NOT a confidence interval on the
    estimated mean. No estimate establishes that the entire search is exhausted.

    Missing predictions stay visible at every examined state. Modeled gains in
    an incomplete tree are conditional forecasts, not guaranteed lower bounds.
    A Bayesian model is useful only to the extent its predictions are calibrated.
    """
    if isinstance(lookahead, bool) or not isinstance(lookahead, int) or lookahead < 1:
        raise ValueError("lookahead must be a positive integer describing the forecast")
    hash(state)
    initial = _number(model.score(state), "score")

    def actions(at):
        result = tuple(model.actions(at))
        for action in result:
            _name(action, "action")
        if len(set(result)) != len(result):
            raise ValueError("available actions must be unique")
        return result

    def predict(at, action, history):
        prediction = model.predict(at, action, history)
        if prediction is None:
            return None
        if not isinstance(prediction, Prediction) or not prediction.transitions:
            raise ValueError("predict must return a nonempty Prediction or None")
        _name(prediction.basis, "prediction basis")
        probabilities = []
        for transition in prediction.transitions:
            if not isinstance(transition, Transition):
                raise ValueError("prediction outcomes must be Transition instances")
            probability = _number(transition.probability, "transition probability")
            if probability <= 0 or probability > 1:
                raise ValueError("transition probabilities must lie in (0, 1]")
            hash(transition.next_state)
            probabilities.append(probability)
        if not math.isclose(
            math.fsum(probabilities), 1.0, rel_tol=1e-10, abs_tol=1e-12
        ):
            raise ValueError("transition probabilities must sum to one")
        return prediction

    # Moments of the terminal score under the adaptively selected continuation.
    # Gaps include all examined alternatives, including ones not selected.
    @lru_cache(maxsize=None)
    def optimal(at, remaining, history):
        score = _number(model.score(at), "score")
        best = (score, score * score, float(score > initial))
        gaps, evidence = set(), set()
        if remaining:
            for action in actions(at):
                prediction = predict(at, action, history)
                if prediction is None:
                    gaps.add((at, action))
                    continue
                moments, _, child_gaps, child_evidence = evaluate(
                    at, action, prediction, remaining, history
                )
                gaps.update(child_gaps)
                evidence.update(child_evidence)
                if moments[0] > best[0]:
                    best = moments
        return best, frozenset(gaps), frozenset(evidence)

    def evaluate(at, action, prediction, remaining, history):
        moments = [[], [], []]
        immediate = []
        gaps, evidence = set(), set(prediction.evidence_ids)
        for transition in prediction.transitions:
            p, following = transition.probability, transition.next_state
            observed = HypotheticalObservation(at, action, following)
            child, child_gaps, child_evidence = optimal(
                following, remaining - 1, (*history, observed)
            )
            for i in range(3):
                moments[i].append(p * child[i])
            immediate.append(p * _number(model.score(following), "score"))
            gaps.update(child_gaps)
            evidence.update(child_evidence)
        return (
            tuple(math.fsum(parts) for parts in moments),
            math.fsum(immediate),
            gaps,
            evidence,
        )

    estimates, all_gaps = [], set()
    best_action, best_value = None, initial
    sort_gaps = lambda gaps: tuple(
        sorted(gaps, key=lambda item: (repr(item[0]), item[1]))
    )
    for action in actions(state):
        prediction = predict(state, action, ())
        if prediction is None:
            gaps = ((state, action),)
            estimate = ComputationEstimate(
                action, None, None, None, None, None, None, "unmodeled", (), gaps
            )
        else:
            moments, immediate, gaps, evidence = evaluate(
                state, action, prediction, lookahead, ()
            )
            mean, second, improved = moments
            estimate = ComputationEstimate(
                action,
                mean - initial,
                immediate - initial,
                mean - immediate,
                mean,
                math.sqrt(max(0.0, second - mean * mean)),
                min(1.0, max(0.0, improved)),
                prediction.basis,
                tuple(sorted(evidence)),
                sort_gaps(gaps),
            )
            if mean > best_value:
                best_action, best_value = action, mean
        all_gaps.update(estimate.unmodeled_decisions)
        estimates.append(estimate)
    recommendation = (
        "modeled_improvement"
        if best_action is not None
        else "unmodeled_options"
        if all_gaps
        else "no_gain_within_model_and_lookahead"
    )
    return ComputationReport(
        initial,
        lookahead,
        tuple(estimates),
        best_action,
        recommendation,
        sort_gaps(all_gaps),
    )


class BayesianTransitionModel:
    """An auditable Bayesian categorical transition model with revisable data.

    Priors, if supplied, are explicit positive Dirichlet pseudocounts. Without
    priors, the empirical predictive distribution is the zero-pseudocount limit
    over observed outcomes only. It cannot invent unseen successes or certify
    their absence. No observation is invented to make an action look promising.

    Revisions replace a single observation's statistical contribution. They do
    not append an independent negative sample or create another successful
    sample when provisional evidence is confirmed. Every revision is retained.
    Separate actual events (including failures) need separate event identities.
    """

    def __init__(self):
        self._states = {}
        self._priors = {}
        self._observations = {}
        self._counts = {}
        self._journal = []

    def register_state(self, state, *, score, actions=(), metadata=None):
        _name(state, "state")
        score = _number(score, "score")
        if isinstance(actions, str):
            raise ValueError("actions must be a sequence, not a string")
        actions = tuple(_name(item, "action") for item in actions)
        if len(actions) != len(set(actions)):
            raise ValueError("available actions must be unique")
        record = {"score": score, "actions": list(actions), "metadata": _json(metadata)}
        if state in self._states:
            if self._states[state] != record:
                raise ValueError(
                    "state identity is immutable; changed measurements need a new state"
                )
            return False
        self._states[state] = record
        self._journal.append({
            "operation": "register_state",
            "arguments": {"state": state, **deepcopy(record)},
        })
        return True

    def score(self, state):
        return self._states[state]["score"]

    def actions(self, state):
        return tuple(self._states[state]["actions"])

    def _cell(self, state, action):
        if state not in self._states or action not in self.actions(state):
            raise ValueError(
                "observation or prior refers to an unavailable state/action"
            )
        return state, action

    def declare_prior(self, state, action, pseudocounts, *, evidence_refs):
        cell = self._cell(state, action)
        if cell in self._priors:
            raise ValueError("a cell's prior is frozen")
        if not isinstance(pseudocounts, dict) or not pseudocounts:
            raise ValueError("supply explicit nonempty Dirichlet pseudocounts")
        counts = {}
        for following, raw in pseudocounts.items():
            if following not in self._states:
                raise ValueError("prior refers to an unregistered successor")
            value = _number(raw, "pseudocount")
            if value <= 0:
                raise ValueError("pseudocounts must be positive")
            counts[following] = value
        refs = self._refs(evidence_refs)
        if set(self._counts.get(cell, {})) - set(counts):
            raise ValueError(
                "declared prior support excludes an already observed outcome"
            )
        self._priors[cell] = {"pseudocounts": counts, "evidence_refs": refs}
        self._journal.append({
            "operation": "declare_prior",
            "arguments": {
                "state": state,
                "action": action,
                "pseudocounts": counts,
                "evidence_refs": refs,
            },
        })

    @staticmethod
    def _refs(refs):
        if not isinstance(refs, (tuple, list)) or not refs:
            raise ValueError(
                "stored observations and declared priors need evidence_refs"
            )
        return list(dict.fromkeys(_name(ref, "evidence reference") for ref in refs))

    def observe(
        self,
        event_id,
        *,
        state,
        action,
        next_state=None,
        revision=0,
        status="confirmed",
        evidence_refs,
    ):
        _name(event_id, "event_id")
        cell = self._cell(state, action)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("revision must be a nonnegative integer")
        if status not in {"confirmed", "provisional", "pending", "withdrawn"}:
            raise ValueError("unknown observation status")
        active = status in {"confirmed", "provisional"}
        if active and next_state not in self._states:
            raise ValueError("an observed outcome needs a registered successor")
        if not active and next_state is not None:
            raise ValueError(
                "pending/withdrawn observations must not supply an outcome"
            )
        if (
            active
            and cell in self._priors
            and next_state not in self._priors[cell]["pseudocounts"]
        ):
            raise ValueError(
                "outcome lies outside declared prior support; revise the model explicitly"
            )
        record = {
            "event_id": event_id,
            "state": state,
            "action": action,
            "next_state": next_state,
            "revision": revision,
            "status": status,
            "evidence_refs": self._refs(evidence_refs),
        }
        previous = self._observations.get(event_id)
        if previous == record:
            return False
        if previous is None:
            if revision != 0:
                raise ValueError("a new observation must start at revision zero")
        elif (previous["state"], previous["action"]) != cell or revision != previous[
            "revision"
        ] + 1:
            raise ValueError(
                "corrections must retain origin and advance revision by one"
            )
        counts = self._counts.setdefault(cell, Counter())
        if previous and previous["status"] in {"confirmed", "provisional"}:
            counts[previous["next_state"]] -= 1
            if not counts[previous["next_state"]]:
                del counts[previous["next_state"]]
        if active:
            counts[next_state] += 1
        self._observations[event_id] = record
        self._journal.append({"operation": "observe", "arguments": deepcopy(record)})
        return True

    def predict(self, state, action, history=()):
        cell = self._cell(state, action)
        prior = self._priors.get(cell)
        weights = Counter({} if prior is None else prior["pseudocounts"])
        weights.update(self._counts.get(cell, {}))
        for observed in history:
            if (observed.state, observed.action) == cell:
                if observed.next_state not in self._states:
                    raise ValueError("hypothetical successor was not registered")
                weights[observed.next_state] += 1
        total = math.fsum(weights.values())
        if not total:
            return None
        evidence = [
            item["event_id"]
            for item in self._observations.values()
            if (item["state"], item["action"]) == cell
            and item["status"] in {"confirmed", "provisional"}
        ]
        if prior:
            evidence.extend(prior["evidence_refs"])
        return Prediction(
            tuple(
                Transition(weight / total, following)
                for following, weight in sorted(weights.items())
                if weight
            ),
            "dirichlet_posterior_predictive" if prior else "observed_support_only",
            tuple(sorted(set(evidence))),
        )

    def observation_history(self):
        return deepcopy([
            entry["arguments"]
            for entry in self._journal
            if entry["operation"] == "observe"
        ])

    def snapshot(self):
        return {"version": VERSION, "journal": deepcopy(self._journal)}

    @classmethod
    def from_snapshot(cls, snapshot):
        if (
            not isinstance(snapshot, dict)
            or set(snapshot) != {"version", "journal"}
            or snapshot["version"] != VERSION
        ):
            raise ValueError("unsupported computation-model snapshot")
        model = cls()
        for entry in snapshot["journal"]:
            if (
                not isinstance(entry, dict)
                or set(entry) != {"operation", "arguments"}
                or entry["operation"]
                not in {"register_state", "declare_prior", "observe"}
            ):
                raise ValueError("unsupported computation-model journal operation")
            before = len(model._journal)
            getattr(model, entry["operation"])(**deepcopy(entry["arguments"]))
            if len(model._journal) != before + 1 or model._journal[-1] != entry:
                raise ValueError("computation-model journal does not replay exactly")
        return model


_COMPUTATION_SCENARIOS = (
    "diagnosis.adaptive_followup",
    "observation.corrected_once",
    "prediction.unknown_is_not_zero",
)


def evaluate_value_of_computation_scenarios(
    function, parameters: Mapping[str, object]
) -> FunctionEvaluationReport:
    """Admit the estimator against small, analytically solvable decisions."""
    model = BayesianTransitionModel()
    for state, score, actions in (
        ("unknown", 0, ("diagnose", "blind_revision", "new_action")),
        ("left", 0, ("fix_left", "fix_right")),
        ("right", 0, ("fix_left", "fix_right")),
        ("qualified", 1, ()),
        ("failed", 0, ()),
    ):
        model.register_state(state, score=score, actions=actions)
    model.declare_prior(
        "unknown",
        "diagnose",
        {"left": 1, "right": 1},
        evidence_refs=["scenario:two_possible_defects"],
    )
    model.declare_prior(
        "unknown",
        "blind_revision",
        {"qualified": 1, "failed": 1},
        evidence_refs=["scenario:blind_revision"],
    )
    for state in ("left", "right"):
        for action in model.actions(state):
            model.observe(
                f"{state}:{action}",
                state=state,
                action=action,
                next_state="qualified" if action == f"fix_{state}" else "failed",
                evidence_refs=["scenario:known_repair"],
            )
    before = model.snapshot()
    report = function(model, "unknown", **parameters)
    estimates = {item.action: item for item in report.estimates}
    diagnosis = estimates["diagnose"]
    adaptive = (
        report.best_modeled_action == "diagnose"
        and diagnosis.immediate_gain == 0
        and diagnosis.expected_gain == 1
        and diagnosis.continuation_gain == 1
        and model.snapshot() == before
    )

    corrected = BayesianTransitionModel()
    corrected.register_state("before", score=0, actions=("build",))
    corrected.register_state("credited", score=1)
    corrected.register_state("invalid", score=0)
    corrected.observe(
        "attempt",
        state="before",
        action="build",
        next_state="credited",
        status="provisional",
        evidence_refs=["scenario:provisional"],
    )
    corrected.observe(
        "attempt",
        state="before",
        action="build",
        next_state="invalid",
        revision=1,
        evidence_refs=["scenario:correction"],
    )
    corrected_report = function(corrected, "before", **parameters)
    corrected_gain = corrected_report.estimates[0].expected_gain
    unknown = (
        estimates["new_action"].expected_gain is None
        and ("unknown", "new_action") in report.unmodeled_decisions
    )
    return FunctionEvaluationReport(
        outcomes=(
            FunctionScenarioOutcome(
                _COMPUTATION_SCENARIOS[0],
                adaptive,
                {
                    "expected_gain": diagnosis.expected_gain,
                    "immediate_gain": diagnosis.immediate_gain,
                },
                ""
                if adaptive
                else "Diagnosis must earn value through adaptive follow-up without mutating evidence.",
            ),
            FunctionScenarioOutcome(
                _COMPUTATION_SCENARIOS[1],
                corrected_gain == 0,
                {"expected_gain": corrected_gain},
                ""
                if corrected_gain == 0
                else "A corrected observation must replace the provisional sample.",
            ),
            FunctionScenarioOutcome(
                _COMPUTATION_SCENARIOS[2],
                unknown,
                {"unmodeled_decisions": len(report.unmodeled_decisions)},
                "" if unknown else "An action without predictions must remain unknown.",
            ),
        )
    )


# The incidence controller's anonymous frequency counts cannot supply action
# transitions. Keep its interface and admission rules intact; this definition
# declares the predictive-model boundary used by a compatible caller.
yield_estimator_function_library = FunctionLibrary(
    evaluated_interfaces=("yield.posterior_predictive",),
)
VALUE_OF_COMPUTATION = yield_estimator_function_library.register(
    LibraryFunction(
        library="yield_estimation",
        function_id="value_of_computation",
        interface="yield.posterior_predictive",
        description=(
            "Estimate per-action score gains after adaptive computation, including "
            "diagnostic actions with no immediate gain and revisable observations."
        ),
        implementation=FunctionImplementation(
            module=__name__,
            symbol="value_of_computation",
            is_async=False,
        ),
        input_type="PredictiveModel, current state, and keyword-only lookahead",
        output_type="ComputationReport",
        effect="Pure numerical forecast; no execution, credit assignment, or stopping decision.",
        failure_contract=(
            "Reject malformed model predictions and invalid lookahead. Missing "
            "predictions remain unknown. Predictive dispersion is not a confidence band."
        ),
        evaluation=FunctionEvaluationSpec(
            implementation=FunctionImplementation(
                module=__name__,
                symbol="evaluate_value_of_computation_scenarios",
                is_async=False,
            ),
            scenario_ids=_COMPUTATION_SCENARIOS,
            arguments={"lookahead": 2},
        ),
        provenance={
            "algorithm": VERSION,
            "objective": "posterior_predictive_expected_terminal_score_minus_current_score",
            "uncertainty": "predictive_outcome_stddev_not_estimator_confidence",
            "caller_contract": "Explicit action/state model; not numeric-incidence statistics.",
            "parameter_schema": {
                "type": "object",
                "properties": {"lookahead": {"type": "integer", "minimum": 1}},
                "additionalProperties": False,
            },
        },
        source_symbols=(
            SourceSymbolReference(
                repository="https://github.com/chian/millenial_biology",
                revision="f4d1ed2d0aeca2386d45f1f720461f53dd2c7a39",
                path="value_of_computation.py",
                symbol="value_of_computation",
            ),
        ),
    )
)
