"""Trusted numerical adapters for Agent Episode progress.

The model selects an adapter identifier and supplies goal strings.  The host
owns the adapter's unit, arithmetic, admissible numeric lattice, and observation
source.  Adding another way to measure progress therefore extends this table;
it never adds a branch to the generic :mod:`method_loop` Episode.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import sys

from agent.episode_contracts import (
    CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
    DURABLE_EVIDENCE_PROGRESS_ADAPTER,
    TERMINAL_RESULT_PROGRESS_ADAPTER,
    NumericProgressMeasure,
    ProgressDirection,
    ProgressStopCriteria,
)


_MAX_FINITE_FLOAT = sys.float_info.max


class ProgressObservationKind(str, Enum):
    CREATOR_METHOD_CREDIT = "creator_method_credit"
    DURABLE_EVIDENCE = "durable_evidence"
    TERMINAL_RESULT = "terminal_result"


@dataclass(frozen=True)
class ProgressAdapter:
    adapter_id: str
    description: str
    unit: str
    observation_kind: ProgressObservationKind
    model_selectable: bool

    def validate(
        self,
        measure: NumericProgressMeasure,
        stopping: ProgressStopCriteria,
    ) -> None:
        if measure.adapter_id != self.adapter_id:
            raise ValueError("progress measure names a different adapter")
        if self.observation_kind in {
            ProgressObservationKind.DURABLE_EVIDENCE,
            ProgressObservationKind.TERMINAL_RESULT,
        }:
            values = {
                "baseline": measure.baseline,
                "target": stopping.target,
                "minimum_delta": stopping.minimum_delta,
            }
            if any(
                value < 0 or not float(value).is_integer()
                for value in values.values()
            ):
                raise ValueError(
                    f"{self.adapter_id} requires non-negative integer-valued "
                    "baseline, target, and minimum_delta"
                )
        if stopping.target == measure.baseline:
            raise ValueError("an Episode progress target must require measured work")
        if self.observation_kind is ProgressObservationKind.DURABLE_EVIDENCE:
            if (
                measure.direction is not ProgressDirection.INCREASE
                or measure.baseline != 0
            ):
                raise ValueError(
                    "durable_evidence_count_v1 requires increase from baseline 0"
                )
        if self.observation_kind is ProgressObservationKind.TERMINAL_RESULT:
            if (
                measure.direction is not ProgressDirection.INCREASE
                or measure.baseline != 0
                or stopping.target != 1
                or stopping.minimum_delta != 1
            ):
                raise ValueError(
                    "terminal_result_count_v1 requires increase, baseline 0, "
                    "target 1, and minimum_delta 1"
                )
        if self.observation_kind is ProgressObservationKind.CREATOR_METHOD_CREDIT:
            if (
                measure.direction is not ProgressDirection.INCREASE
                or measure.baseline != 0
                or not 0 < stopping.target <= 1
                or stopping.minimum_delta > 1
            ):
                raise ValueError(
                    "creator_method_credit_v1 requires increase from baseline 0 "
                    "toward a target in (0, 1] with minimum_delta <= 1"
                )

    def observed_value(self, value: object) -> float:
        result = finite_number(value, f"{self.adapter_id} observation")
        if not result.is_integer():
            raise ValueError(
                f"{self.adapter_id} observations must be integer-valued"
            )
        return result


_ADAPTERS = {
    CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER: ProgressAdapter(
        adapter_id=CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
        description="Host-computed method credit from complete Run Episode outcomes",
        unit="normalized method credit",
        observation_kind=ProgressObservationKind.CREATOR_METHOD_CREDIT,
        model_selectable=False,
    ),
    DURABLE_EVIDENCE_PROGRESS_ADAPTER: ProgressAdapter(
        adapter_id=DURABLE_EVIDENCE_PROGRESS_ADAPTER,
        description="Newly claimed committed successful result identities",
        unit="committed successful result identities",
        observation_kind=ProgressObservationKind.DURABLE_EVIDENCE,
        model_selectable=True,
    ),
    TERMINAL_RESULT_PROGRESS_ADAPTER: ProgressAdapter(
        adapter_id=TERMINAL_RESULT_PROGRESS_ADAPTER,
        description="Host-accepted terminal result proposals",
        unit="terminal result proposals",
        observation_kind=ProgressObservationKind.TERMINAL_RESULT,
        model_selectable=True,
    ),
}


def finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _saturated_add(left: object, right: object, *, name: str) -> float:
    lhs = finite_number(left, f"{name} left operand")
    rhs = finite_number(right, f"{name} right operand")
    if rhs > 0.0 and lhs > _MAX_FINITE_FLOAT - rhs:
        return _MAX_FINITE_FLOAT
    if rhs < 0.0 and lhs < -_MAX_FINITE_FLOAT - rhs:
        return -_MAX_FINITE_FLOAT
    result = lhs + rhs
    if not math.isfinite(result):
        raise ValueError(f"{name} produced a non-finite result")
    return result


def saturated_difference(left: object, right: object, *, name: str) -> float:
    rhs = finite_number(right, f"{name} right operand")
    return _saturated_add(left, -rhs, name=name)


def progress_adapter(adapter_id: str) -> ProgressAdapter:
    try:
        return _ADAPTERS[adapter_id]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unknown progress adapter {adapter_id!r}") from exc


def model_progress_adapters() -> tuple[ProgressAdapter, ...]:
    return tuple(adapter for adapter in _ADAPTERS.values() if adapter.model_selectable)


def validate_progress_contract(
    measure: NumericProgressMeasure,
    stopping: ProgressStopCriteria,
    *,
    model_created: bool,
) -> ProgressAdapter:
    adapter = progress_adapter(measure.adapter_id)
    if model_created and not adapter.model_selectable:
        raise ValueError(
            f"progress adapter {adapter.adapter_id!r} is host-only"
        )
    adapter.validate(measure, stopping)
    return adapter


def advance_progress(
    previous: object,
    measure: NumericProgressMeasure,
    observed_units: int,
) -> float:
    adapter = progress_adapter(measure.adapter_id)
    if (
        isinstance(observed_units, bool)
        or not isinstance(observed_units, int)
        or observed_units < 0
    ):
        raise ValueError("observed progress units must be a non-negative integer")
    try:
        magnitude = float(observed_units)
    except OverflowError:
        magnitude = _MAX_FINITE_FLOAT
    if not math.isfinite(magnitude):
        magnitude = _MAX_FINITE_FLOAT
    signed = (
        magnitude
        if measure.direction is ProgressDirection.INCREASE
        else -magnitude
    )
    return _saturated_add(
        previous,
        signed,
        name=f"{adapter.adapter_id} progress",
    )


__all__ = [
    "ProgressAdapter",
    "ProgressObservationKind",
    "advance_progress",
    "finite_number",
    "model_progress_adapters",
    "progress_adapter",
    "saturated_difference",
    "validate_progress_contract",
]
