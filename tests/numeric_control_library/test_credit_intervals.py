"""Analytical checks of marginal-credit bounds under shared normalization."""

from itertools import product
import math

import pytest

from numeric_control_library.credit_assignment import (
    CreditObservation,
    MarginalHypervolumeAssignment,
    NumericBand,
    NumericYieldProjection,
    ResultColumnSchema,
)


def projected_credit(counts, totals, yields):
    columns = tuple(f"column_{index:024x}" for index in range(len(counts)))
    assignment = MarginalHypervolumeAssignment(
        ResultColumnSchema(columns, (0.0,) * len(counts))
    )
    assignment.admit(CreditObservation.observed({
        column: tuple(f"identity_{position:012x}{index:012x}" for index in range(count))
        for position, (column, count) in enumerate(zip(columns, counts))
    }))
    admission = assignment.admit(CreditObservation.failed(
        {column: () for column in columns}, code="acquisition_failed"
    ))

    def projection(snapshot):
        return NumericYieldProjection(
            snapshot.numeric_state, totals, yields, yields,
            NumericBand.exact(1), 0.05,
        )

    return assignment.assign(
        admission, projection(admission.before), projection(admission.after)
    ).projected_next


def test_zero_yield_has_zero_credit_despite_uncertain_total():
    counts = (3, 2, 0)
    totals = (
        NumericBand.interval(6, 3, 21, 0.05),
        NumericBand.interval(5, 2, 12, 0.05),
        NumericBand.exact(0),
    )
    credit = projected_credit(counts, totals, (NumericBand.exact(0),) * 3)
    # Total-richness uncertainty cannot produce an increment when all next
    # yields are identically zero, including an exactly empty coordinate.
    assert credit == NumericBand.exact(0)


def test_upper_credit_encloses_shared_scale_scenarios_and_is_attainable():
    # The first coordinate's maximum is inside its scale interval where the
    # projected value first stops clipping at one. Merely pairing the lower
    # scale endpoints would underestimate the attainable marginal credit.
    counts = (3, 2)
    totals = (
        NumericBand.interval(6, 3, 21, 0.05),
        NumericBand.interval(5, 2, 12, 0.05),
    )
    yields = (
        NumericBand.interval(0.4, 0.1, 4, 0.05),
        NumericBand.interval(0.3, 0.1, 0.9, 0.05),
    )
    credit = projected_credit(counts, totals, yields)
    scale_ranges = [
        (max(count + 1, total.lower), max(count + 1, total.upper))
        for count, total in zip(counts, totals)
    ]
    scenarios = []
    for count, total, increment, (lo, hi) in zip(counts, totals, yields, scale_ranges):
        scenarios.append(tuple(product(
            sorted({lo, hi, max(lo, min(hi, total.value)),
                    max(lo, min(hi, count + increment.upper))}),
            (increment.lower, increment.value, increment.upper),
        )))
    values = []
    for scenario in product(*scenarios):
        before = math.prod(count / scale for count, (scale, _) in zip(counts, scenario))
        after = math.prod(
            min(1, (count + increment) / scale)
            for count, (scale, increment) in zip(counts, scenario)
        )
        marginal = after - before
        assert credit.lower <= marginal + 1e-15
        assert marginal <= credit.upper + 1e-15
        values.append(marginal)
    assert credit.upper == pytest.approx(max(values), rel=1e-14, abs=1e-15)
    # Changing column order leaves the numerical result unchanged.
    reversed_credit = projected_credit(counts[::-1], totals[::-1], yields[::-1])
    assert reversed_credit == credit
