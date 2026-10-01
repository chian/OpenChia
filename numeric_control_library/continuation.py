"""Numerical continuation over projected marginal-credit uncertainty."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Mapping

from function_library import FunctionImplementation, FunctionLibrary, LibraryFunction

from .credit_assignment import NumericBand


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def validate_predicted_credit_parameters(
    parameters: Mapping[str, object],
) -> dict[str, float]:
    if not isinstance(parameters, Mapping):
        raise ValueError("predicted_credit_upper_bound parameters must be an object")
    expected = {"max_predicted_marginal_hypervolume"}
    if set(parameters) != expected:
        raise ValueError(
            "predicted_credit_upper_bound parameters must contain exactly "
            "max_predicted_marginal_hypervolume"
        )
    threshold = _finite(
        parameters["max_predicted_marginal_hypervolume"],
        "max_predicted_marginal_hypervolume",
    )
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(
            "max_predicted_marginal_hypervolume must be in [0, 1]"
        )
    return {"max_predicted_marginal_hypervolume": threshold}


@dataclass(frozen=True)
class ContinuationDecision:
    stop: bool
    outcome: str
    projected_credit: NumericBand
    threshold: float

    def __post_init__(self) -> None:
        if not isinstance(self.stop, bool):
            raise ValueError("stop must be boolean")
        if not isinstance(self.outcome, str) or not self.outcome:
            raise ValueError("outcome must be non-empty text")
        if not isinstance(self.projected_credit, NumericBand):
            raise TypeError("projected_credit must be a NumericBand")
        threshold = _finite(self.threshold, "threshold")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be in [0, 1]")
        if self.stop and (
            not self.projected_credit.ready
            or self.projected_credit.upper > threshold
        ):
            raise ValueError(
                "a stop requires a ready projected-credit upper bound at threshold"
            )
        object.__setattr__(self, "threshold", threshold)

    def as_record(self) -> dict[str, object]:
        return {
            "stop": self.stop,
            "outcome": self.outcome,
            "projected_credit": self.projected_credit.as_record(),
            "threshold": self.threshold,
            "decision_basis": "predicted_marginal_hypervolume_upper_bound",
        }


def predicted_credit_upper_bound(
    projected_credit: NumericBand,
    parameters: Mapping[str, object],
) -> ContinuationDecision:
    """Stop exactly when the projected-credit upper bound meets tolerance."""

    if not isinstance(projected_credit, NumericBand):
        raise TypeError("predicted_credit_upper_bound requires a NumericBand")
    normalized = validate_predicted_credit_parameters(parameters)
    threshold = normalized["max_predicted_marginal_hypervolume"]
    if not projected_credit.ready:
        return ContinuationDecision(
            stop=False,
            outcome=projected_credit.status.value,
            projected_credit=projected_credit,
            threshold=threshold,
        )
    stop = projected_credit.upper <= threshold
    return ContinuationDecision(
        stop=stop,
        outcome="yield_saturated" if stop else "continuing",
        projected_credit=projected_credit,
        threshold=threshold,
    )


continuation_function_library = FunctionLibrary()
PREDICTED_CREDIT_UPPER_BOUND = continuation_function_library.register(
    LibraryFunction(
        library="continuation_rules",
        function_id="predicted_credit_upper_bound",
        interface="continuation.numeric_credit_band",
        description=(
            "Stop only when the upper uncertainty bound on predicted next "
            "marginal dominated-hypervolume credit is at or below tolerance."
        ),
        implementation=FunctionImplementation(
            module="numeric_control_library.continuation",
            symbol="predicted_credit_upper_bound",
            is_async=False,
        ),
        input_type="NumericBand plus max_predicted_marginal_hypervolume",
        output_type="ContinuationDecision",
        effect="Pure numerical decision; no estimator or identity state.",
        failure_contract=(
            "Unavailable bands continue; malformed bands and thresholds are rejected."
        ),
        provenance={
            "sole_stop_statistic": "predicted_marginal_hypervolume_upper_bound",
            "parameter_schema": {
                "type": "object",
                "properties": {
                    "max_predicted_marginal_hypervolume": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    }
                },
                "required": ["max_predicted_marginal_hypervolume"],
                "additionalProperties": False,
            },
        },
    )
)


__all__ = [
    "PREDICTED_CREDIT_UPPER_BOUND",
    "ContinuationDecision",
    "continuation_function_library",
    "predicted_credit_upper_bound",
    "validate_predicted_credit_parameters",
]
