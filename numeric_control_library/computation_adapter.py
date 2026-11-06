"""Reusable measured-outcome connection between an Episode and VOC forecasts.

The caller maps its task's scores, retained information and actions to immutable
states. This module journals those supplied measurements and exposes forecasts
at the existing method-loop controller boundary. It does not score scientific
work, choose actions, or infer exhaustion from an incomplete predictive model.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import math
from typing import Mapping

from function_library import (
    FunctionEvaluationReport,
    FunctionEvaluationSpec,
    FunctionImplementation,
    FunctionScenarioOutcome,
    LibraryFunction,
)
from method_loop import ClosedRecord, ControllerFactory

from .controller import controller_function_library
from .value_of_computation import (
    VALUE_OF_COMPUTATION,
    BayesianTransitionModel,
    ComputationReport,
    value_of_computation,
)


VERSION = "1.0-measured-computation-adapter"


def _names(values: tuple[str, ...], name: str, *, nonempty: bool = False) -> None:
    if (
        not isinstance(values, tuple)
        or (nonempty and not values)
        or any(not isinstance(value, str) or not value.strip() for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError(f"{name} must be a tuple of unique nonempty names")


@dataclass(frozen=True)
class ComputationState(ClosedRecord):
    """Caller-measured state; a diagnostic discovery needs a distinct identity."""

    state_id: str
    score: float
    evidence_refs: tuple[str, ...]
    actions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _names((self.state_id,), "state_id")
        if (
            isinstance(self.score, bool)
            or not isinstance(self.score, (int, float))
            or not math.isfinite(self.score)
        ):
            raise ValueError("score must be a finite measured number")
        _names(self.actions, "actions")
        _names(self.evidence_refs, "evidence_refs", nonempty=True)
        object.__setattr__(self, "score", float(self.score))

    def as_record(self) -> dict:
        return asdict(self)

    @classmethod
    def from_record(cls, record: Mapping[str, object]) -> ComputationState:
        if not isinstance(record, Mapping) or set(record) != {
            "state_id",
            "score",
            "actions",
            "evidence_refs",
        }:
            raise ValueError("computation state record has invalid fields")
        for field in ("actions", "evidence_refs"):
            if not isinstance(record[field], (tuple, list)):
                raise ValueError(f"{field} must be an array of names")
        return cls(
            record["state_id"],
            record["score"],
            tuple(record["evidence_refs"]),
            tuple(record["actions"]),
        )


@dataclass(frozen=True)
class ComputationObservation(ClosedRecord):
    """One attributed transition, including explicit revisions or withdrawal."""

    event_id: str
    state: ComputationState
    action: str
    next_state: ComputationState | None
    evidence_refs: tuple[str, ...]
    revision: int = 0
    status: str = "confirmed"

    def __post_init__(self) -> None:
        if not isinstance(self.state, ComputationState) or (
            self.next_state is not None
            and not isinstance(self.next_state, ComputationState)
        ):
            raise TypeError("observation states must be ComputationState values")
        _names(self.evidence_refs, "observation evidence_refs", nonempty=True)

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ComputationInput(ClosedRecord):
    """Current measurement and newly available observations or corrections.

    Current state is explicit: revising a historical event must not move the
    Episode back to that historical successor. Replayed identical observations
    are idempotent; unrelated new attempts require distinct event identities.
    """

    current_state: ComputationState
    observations: tuple[ComputationObservation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.current_state, ComputationState):
            raise TypeError("current_state must be a ComputationState")
        if not isinstance(self.observations, tuple) or any(
            not isinstance(item, ComputationObservation) for item in self.observations
        ):
            raise TypeError(
                "observations must be a tuple of ComputationObservation values"
            )

    def as_record(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ComputationFeedback(ClosedRecord):
    epoch: str
    current_state: str
    computation_value: ComputationReport
    credit_history: tuple[dict, ...]
    stop: bool = False
    requests_transition: bool = False

    @property
    def current_score(self) -> float:
        return self.computation_value.current_score

    def as_record(self) -> dict:
        return {**asdict(self), "current_score": self.current_score}


class ComputationAdvisor:
    """An episode-local advisor implementing the existing Controller protocol.

    ``state()`` exposes the report and signed observation history to a source's
    chooser. ``observe`` accepts only caller-measured inputs. No automatic stop
    follows from negative gains, unmodeled actions or finite forecast depth.
    """

    def __init__(
        self,
        *,
        epoch: str,
        initial_state: ComputationState,
        lookahead: int = 3,
        model_snapshot: dict | None = None,
    ) -> None:
        _names((epoch,), "epoch")
        VALUE_OF_COMPUTATION.admit_arguments({"lookahead": lookahead})
        self.epoch, self.lookahead = epoch, lookahead
        self._model = (
            BayesianTransitionModel()
            if model_snapshot is None
            else BayesianTransitionModel.from_snapshot(deepcopy(model_snapshot))
        )
        self._register(self._model, initial_state)
        self._current = initial_state

    @staticmethod
    def _register(model: BayesianTransitionModel, state: ComputationState) -> None:
        if not isinstance(state, ComputationState):
            raise TypeError("a measurement must be a ComputationState")
        model.register_state(
            state.state_id,
            score=state.score,
            actions=state.actions,
            metadata={"evidence_refs": list(state.evidence_refs)},
        )

    def observe(
        self, unit_label: str, value: object, *, is_root: bool
    ) -> ComputationFeedback:
        if not isinstance(value, ComputationInput):
            raise TypeError("ComputationAdvisor requires a ComputationInput")
        # Validate the entire update before committing any state or correction.
        staged = BayesianTransitionModel.from_snapshot(self._model.snapshot())
        for observation in value.observations:
            self._register(staged, observation.state)
            if observation.next_state is not None:
                self._register(staged, observation.next_state)
            staged.observe(
                observation.event_id,
                state=observation.state.state_id,
                action=observation.action,
                next_state=None
                if observation.next_state is None
                else observation.next_state.state_id,
                revision=observation.revision,
                status=observation.status,
                evidence_refs=observation.evidence_refs,
            )
        self._register(staged, value.current_state)
        self._model, self._current = staged, value.current_state
        return self.state()

    def state(self) -> ComputationFeedback:
        report = value_of_computation(
            self._model, self._current.state_id, lookahead=self.lookahead
        )
        history = []
        for observation in self._model.observation_history():
            before = self._model.score(observation["state"])
            after = (
                None
                if observation["next_state"] is None
                else self._model.score(observation["next_state"])
            )
            history.append({
                **observation,
                "score_before": before,
                "score_after": after,
                "score_delta": None if after is None else after - before,
            })
        return ComputationFeedback(
            self.epoch, self._current.state_id, report, tuple(history)
        )

    def transitioned(self, epoch: str) -> ComputationAdvisor:
        raise ValueError(
            "A new objective epoch needs explicitly remapped measurements; open a new advisor."
        )

    def snapshot(self) -> dict:
        return {
            "version": VERSION,
            "epoch": self.epoch,
            "lookahead": self.lookahead,
            "current_state": self._current.as_record(),
            "model": self._model.snapshot(),
        }

    @classmethod
    def from_snapshot(cls, snapshot: dict) -> ComputationAdvisor:
        if (
            not isinstance(snapshot, dict)
            or set(snapshot)
            != {"version", "epoch", "lookahead", "current_state", "model"}
            or snapshot["version"] != VERSION
        ):
            raise ValueError("unsupported computation-advisor snapshot")
        model = BayesianTransitionModel.from_snapshot(snapshot["model"])
        current = ComputationState.from_record(snapshot["current_state"])
        before = model.snapshot()
        cls._register(model, current)
        if model.snapshot() != before:
            raise ValueError(
                "snapshot current state was not present in its model journal"
            )
        return cls(
            epoch=snapshot["epoch"],
            initial_state=current,
            lookahead=snapshot["lookahead"],
            model_snapshot=snapshot["model"],
        )


def compose_computation_controller(
    *,
    epoch: str,
    initial_state: ComputationState,
    lookahead: int = 3,
    model_snapshot: dict | None = None,
) -> ControllerFactory:
    """Open a separate advisor for each Episode path using frozen initial data."""
    initial = ComputationAdvisor(
        epoch=epoch,
        initial_state=initial_state,
        lookahead=lookahead,
        model_snapshot=model_snapshot,
    ).snapshot()

    def open_controller(path):
        if not isinstance(path, tuple) or not path:
            raise ValueError("controller path must be a non-empty tuple")
        return ComputationAdvisor.from_snapshot(initial)

    return open_controller


_ADAPTER_SCENARIOS = ("feedback.measured_gain", "scope.isolated_unknown")


def evaluate_computation_adapter_scenarios(
    function, parameters
) -> FunctionEvaluationReport:
    start = ComputationState("start", 0, ("measurement:start",), ("try",))
    result = ComputationState("result", 1, ("measurement:result",))
    factory = function(epoch="admission", initial_state=start, **parameters)
    first, other = factory((("task", "first"),)), factory((("task", "other"),))
    first.observe(
        "attempt",
        ComputationInput(
            start,
            (
                ComputationObservation(
                    "attempt", start, "try", result, ("measurement:attempt",)
                ),
            ),
        ),
        is_root=True,
    )
    feedback = first.state()
    gain = feedback.computation_value.estimates[0].expected_gain
    measured = gain == 1 and feedback.credit_history[0]["score_delta"] == 1
    isolated = other.state().computation_value.estimates[0].expected_gain is None
    return FunctionEvaluationReport((
        FunctionScenarioOutcome(
            _ADAPTER_SCENARIOS[0],
            measured,
            {"expected_gain": gain},
            "" if measured else "Measured transitions must reach chooser feedback.",
        ),
        FunctionScenarioOutcome(
            _ADAPTER_SCENARIOS[1],
            isolated,
            {"isolated": float(isolated)},
            "" if isolated else "Fresh scopes must retain unknown predictions.",
        ),
    ))


COMPOSE_COMPUTATION_CONTROLLER = controller_function_library.register(
    LibraryFunction(
        library="controller_composition",
        function_id="compose_computation_controller",
        interface="controller.compose_predictive_computation",
        description=(
            "Connect caller-measured Episode states and revisable action observations to "
            "value-of-computation forecasts and signed history visible to its source chooser."
        ),
        implementation=FunctionImplementation(
            module=__name__, symbol="compose_computation_controller", is_async=False
        ),
        input_type="Runtime epoch, ComputationState, optional model snapshot, and keyword-only lookahead",
        output_type="method_loop.ControllerFactory",
        effect="Opens one isolated, evidence-bearing computation advisor per Episode path.",
        failure_contract=(
            "Reject malformed or conflicting measurements and revisions atomically. "
            "Unknown forecasts never cause a stop. New objectives require explicit remapping."
        ),
        evaluation=FunctionEvaluationSpec(
            implementation=FunctionImplementation(
                module=__name__,
                symbol="evaluate_computation_adapter_scenarios",
                is_async=False,
            ),
            scenario_ids=_ADAPTER_SCENARIOS,
            arguments={"lookahead": 2},
        ),
        provenance={
            "estimator_definition_id": VALUE_OF_COMPUTATION.definition_id,
            "measurement_owner": "Caller supplies state identities, measured score, actions and evidence references.",
            "feedback_boundary": "EpisodeView.controller_state.computation_value and credit_history",
            "continuation": "Advisory; source owns action selection and completion.",
            "parameter_schema": {
                "type": "object",
                "properties": {"lookahead": {"type": "integer", "minimum": 1}},
                "additionalProperties": False,
            },
        },
    )
)


__all__ = [
    "COMPOSE_COMPUTATION_CONTROLLER",
    "ComputationAdvisor",
    "ComputationFeedback",
    "ComputationInput",
    "ComputationObservation",
    "ComputationState",
    "compose_computation_controller",
]
