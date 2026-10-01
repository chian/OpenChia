"""Numeric full-history paired-incidence estimation.

Rarefaction has one boundary: frozen tuples of non-negative numbers in,
position-aligned numeric yield bands out. Stable identities, result-column
names, Goals, evidence, normalization, hypervolume, and stopping decisions do
not enter this module.
"""

from __future__ import annotations

import math
from numbers import Real
from statistics import NormalDist
from typing import Callable, Mapping

from function_library import (
    FunctionEvaluationReport,
    FunctionEvaluationSpec,
    FunctionImplementation,
    FunctionLibrary,
    FunctionScenarioOutcome,
    LibraryFunction,
)

from .credit_assignment import (
    ADMISSION_FAILED,
    ADMISSION_OBSERVED,
    POSITION_ACCEPTED_DISTINCT,
    POSITION_FREQUENCY_OF_FREQUENCIES,
    POSITION_OBSERVED_SAMPLES,
    BandStatus,
    NumericBand,
    NumericIncidenceState,
    NumericYieldProjection,
)


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a real number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def validate_paired_incidence_parameters(
    parameters: Mapping[str, object],
) -> dict[str, float]:
    if not isinstance(parameters, Mapping):
        raise ValueError("paired_incidence parameters must be an object")
    if set(parameters) != {"uncertainty_alpha"}:
        raise ValueError(
            "paired_incidence parameters must contain exactly uncertainty_alpha"
        )
    alpha = _finite(parameters["uncertainty_alpha"], "uncertainty_alpha")
    if not 0.0 < alpha < 1.0:
        raise ValueError("uncertainty_alpha must satisfy 0 < alpha < 1")
    return {"uncertainty_alpha": alpha}


def _wilson_probability(
    successes: int,
    trials: int,
    component_alpha: float,
    output_alpha: float,
) -> NumericBand:
    if trials == 0:
        return NumericBand.unavailable(BandStatus.INSUFFICIENT)
    point = successes / trials
    z = NormalDist().inv_cdf(1.0 - component_alpha / 2.0)
    z2 = z * z
    denominator = 1.0 + z2 / trials
    center = (point + z2 / (2.0 * trials)) / denominator
    radius = (
        z
        * math.sqrt(point * (1.0 - point) / trials + z2 / (4.0 * trials**2))
        / denominator
    )
    return NumericBand.interval(
        point,
        min(point, max(0.0, center - radius)),
        max(point, min(1.0, center + radius)),
        output_alpha,
    )


def _conditional_next_yield(
    singleton_count: int,
    observed_samples: int,
    component_alpha: float,
    output_alpha: float,
) -> NumericBand:
    if observed_samples == 0:
        return NumericBand.unavailable(BandStatus.INSUFFICIENT)
    point = singleton_count / observed_samples
    # A Jeffreys gamma posterior leaves a finite, continuously contracting
    # outer bound when the singleton count is zero. No discrete run-length or
    # minimum-exposure gate is introduced.
    shape = singleton_count + 0.5
    posterior_mean = shape / observed_samples
    posterior_variance = shape / (observed_samples * observed_samples)
    radius = math.sqrt(posterior_variance / component_alpha)
    return NumericBand.interval(
        point,
        max(0.0, min(point, posterior_mean - radius)),
        max(point, posterior_mean + radius),
        output_alpha,
    )


def _remaining_richness(
    singleton_count: int,
    doubleton_count: int,
    observed_samples: int,
    conditional_next: NumericBand,
    component_alpha: float,
    output_alpha: float,
) -> NumericBand:
    if observed_samples == 0 or not conditional_next.ready:
        return NumericBand.unavailable(BandStatus.INSUFFICIENT)
    correction = (observed_samples - 1.0) / observed_samples
    chao = (
        correction
        * singleton_count
        * max(0.0, singleton_count - 1.0)
        / (2.0 * (doubleton_count + 1.0))
    )
    derivative_singletons = (
        correction
        * (2.0 * singleton_count - 1.0)
        / (2.0 * (doubleton_count + 1.0))
    )
    derivative_doubletons = (
        -correction
        * singleton_count
        * max(0.0, singleton_count - 1.0)
        / (2.0 * (doubleton_count + 1.0) ** 2)
    )
    variance = (
        derivative_singletons**2 * singleton_count
        + derivative_doubletons**2 * doubleton_count
    )
    radius = math.sqrt(max(0.0, variance) / component_alpha)
    point = max(chao, conditional_next.value)
    lower = max(0.0, min(point, chao - radius))
    upper = max(point, chao + radius, conditional_next.upper)
    return NumericBand.interval(point, lower, upper, output_alpha)


def _product_band(
    left: NumericBand,
    right: NumericBand,
    output_alpha: float,
) -> NumericBand:
    if not left.ready or not right.ready:
        status = (
            BandStatus.UNIDENTIFIABLE
            if BandStatus.UNIDENTIFIABLE in (left.status, right.status)
            else BandStatus.INSUFFICIENT
        )
        return NumericBand.unavailable(status)
    return NumericBand.interval(
        left.value * right.value,
        left.lower * right.lower,
        left.upper * right.upper,
        output_alpha,
    )


def paired_incidence(
    state: NumericIncidenceState,
    parameters: Mapping[str, object],
) -> NumericYieldProjection:
    """Estimate position-aligned richness and next yield from numeric state."""

    if not isinstance(state, NumericIncidenceState):
        raise TypeError("paired_incidence requires a NumericIncidenceState")
    normalized = validate_paired_incidence_parameters(parameters)
    alpha = normalized["uncertainty_alpha"]
    # Richness and next-yield uncertainty are estimated per position, plus one
    # shared usability probability. Bonferroni supplies one explicit common
    # allocation; the registered provenance identifies the approximate pieces.
    component_alpha = alpha / (2.0 * state.width + 1.0)
    observed_units = state.admission_counts[ADMISSION_OBSERVED]
    failed_units = state.admission_counts[ADMISSION_FAILED]
    usability = _wilson_probability(
        observed_units,
        observed_units + failed_units,
        component_alpha,
        alpha,
    )

    totals: list[NumericBand] = []
    next_yields: list[NumericBand] = []
    conditional_yields: list[NumericBand] = []
    for row in state.positions:
        accepted_distinct = row[POSITION_ACCEPTED_DISTINCT]
        observed_samples = row[POSITION_OBSERVED_SAMPLES]
        frequencies = row[POSITION_FREQUENCY_OF_FREQUENCIES]
        singleton_count = frequencies[1] if observed_samples >= 1 else 0
        doubleton_count = frequencies[2] if observed_samples >= 2 else 0
        conditional = _conditional_next_yield(
            singleton_count,
            observed_samples,
            component_alpha,
            alpha,
        )
        remaining = _remaining_richness(
            singleton_count,
            doubleton_count,
            observed_samples,
            conditional,
            component_alpha,
            alpha,
        )
        if remaining.ready:
            total = NumericBand.interval(
                accepted_distinct + remaining.value,
                accepted_distinct + remaining.lower,
                accepted_distinct + remaining.upper,
                alpha,
            )
        else:
            total = NumericBand.unavailable(remaining.status)
        totals.append(total)
        conditional_yields.append(conditional)
        next_yields.append(_product_band(conditional, usability, alpha))
    return NumericYieldProjection(
        source_state=state,
        expected_totals=tuple(totals),
        expected_next_yields=tuple(next_yields),
        conditional_next_yields=tuple(conditional_yields),
        usable_observation_probability=usability,
        joint_uncertainty_alpha=alpha,
    )


_PAIRED_INCIDENCE_SCENARIOS = (
    "empty.history",
    "singleton.signal",
    "failure.adjustment",
    "position.equivariance",
    "uncertainty.contraction",
    "deterministic.repeat",
)


def _evaluated_projection(
    implementation: Callable[
        [NumericIncidenceState, Mapping[str, object]],
        NumericYieldProjection,
    ],
    state: NumericIncidenceState,
    parameters: Mapping[str, object],
) -> NumericYieldProjection:
    projection = implementation(state, parameters)
    if not isinstance(projection, NumericYieldProjection):
        raise TypeError("rarefaction scenarios require NumericYieldProjection output")
    return projection


def _scenario(
    scenario_id: str,
    passed: bool,
    measurements: Mapping[str, Real],
    failure: str,
) -> FunctionScenarioOutcome:
    return FunctionScenarioOutcome(
        scenario_id=scenario_id,
        passed=passed,
        measurements=measurements,
        failure="" if passed else failure,
    )


def evaluate_paired_incidence_scenarios(
    implementation: Callable[
        [NumericIncidenceState, Mapping[str, object]],
        NumericYieldProjection,
    ],
    parameters: Mapping[str, object],
) -> FunctionEvaluationReport:
    """Exercise estimator invariants on deterministic, identity-free histories."""

    normalized = validate_paired_incidence_parameters(parameters)
    empty = NumericIncidenceState(
        positions=((0, 0, (0,)),),
        admission_counts=(0, 0),
    )
    singleton_rich = NumericIncidenceState(
        positions=((4, 4, (0, 4, 0, 0, 0)),),
        admission_counts=(4, 0),
    )
    repeat_rich = NumericIncidenceState(
        positions=((2, 4, (0, 0, 2, 0, 0)),),
        admission_counts=(4, 0),
    )
    singleton_with_failures = NumericIncidenceState(
        positions=singleton_rich.positions,
        admission_counts=(4, 4),
    )
    two_positions = NumericIncidenceState(
        positions=singleton_rich.positions + repeat_rich.positions,
        admission_counts=(4, 0),
    )
    swapped_positions = NumericIncidenceState(
        positions=repeat_rich.positions + singleton_rich.positions,
        admission_counts=(4, 0),
    )
    lower_information = NumericIncidenceState(
        positions=((2, 4, (0, 2, 0, 0, 0)),),
        admission_counts=(4, 0),
    )
    higher_information = NumericIncidenceState(
        positions=((4, 8, (0, 4, 0, 0, 0, 0, 0, 0, 0)),),
        admission_counts=(8, 0),
    )

    empty_projection = _evaluated_projection(implementation, empty, normalized)
    empty_bands = (
        empty_projection.expected_totals
        + empty_projection.expected_next_yields
        + empty_projection.conditional_next_yields
        + (empty_projection.usable_observation_probability,)
    )
    empty_passed = all(
        band.status is BandStatus.INSUFFICIENT for band in empty_bands
    )

    singleton_projection = _evaluated_projection(
        implementation,
        singleton_rich,
        normalized,
    )
    repeat_projection = _evaluated_projection(
        implementation,
        repeat_rich,
        normalized,
    )
    singleton_conditional = singleton_projection.conditional_next_yields[0]
    repeat_conditional = repeat_projection.conditional_next_yields[0]
    singleton_next = singleton_projection.expected_next_yields[0]
    repeat_next = repeat_projection.expected_next_yields[0]
    singleton_passed = (
        singleton_conditional.ready
        and repeat_conditional.ready
        and singleton_next.ready
        and repeat_next.ready
        and singleton_conditional.value > repeat_conditional.value
        and singleton_next.value > repeat_next.value
    )

    failure_projection = _evaluated_projection(
        implementation,
        singleton_with_failures,
        normalized,
    )
    failure_conditional = failure_projection.conditional_next_yields[0]
    failure_next = failure_projection.expected_next_yields[0]
    failure_passed = (
        failure_conditional == singleton_conditional
        and failure_projection.usable_observation_probability.value
        < singleton_projection.usable_observation_probability.value
        and failure_next.value < singleton_next.value
    )

    ordered_projection = _evaluated_projection(
        implementation,
        two_positions,
        normalized,
    )
    swapped_projection = _evaluated_projection(
        implementation,
        swapped_positions,
        normalized,
    )
    expected_total_delta = max(
        abs(
            ordered_projection.expected_totals[index].value
            - swapped_projection.expected_totals[1 - index].value
        )
        for index in range(2)
    )
    expected_yield_delta = max(
        abs(
            ordered_projection.expected_next_yields[index].value
            - swapped_projection.expected_next_yields[1 - index].value
        )
        for index in range(2)
    )
    position_passed = (
        expected_total_delta == 0.0 and expected_yield_delta == 0.0
    )

    lower_projection = _evaluated_projection(
        implementation,
        lower_information,
        normalized,
    )
    higher_projection = _evaluated_projection(
        implementation,
        higher_information,
        normalized,
    )
    lower_band = lower_projection.conditional_next_yields[0]
    higher_band = higher_projection.conditional_next_yields[0]
    lower_width = lower_band.upper - lower_band.lower
    higher_width = higher_band.upper - higher_band.lower
    contraction_passed = (
        lower_band.ready
        and higher_band.ready
        and lower_band.value == higher_band.value
        and higher_width < lower_width
    )

    repeated_projection = _evaluated_projection(
        implementation,
        singleton_rich,
        normalized,
    )
    deterministic_passed = repeated_projection == singleton_projection

    return FunctionEvaluationReport(
        outcomes=(
            _scenario(
                "empty.history",
                empty_passed,
                {
                    "band.count": len(empty_bands),
                    "insufficient.count": sum(
                        band.status is BandStatus.INSUFFICIENT
                        for band in empty_bands
                    ),
                },
                "empty history must remain numerically insufficient",
            ),
            _scenario(
                "singleton.signal",
                singleton_passed,
                {
                    "singleton.conditional": singleton_conditional.value,
                    "repeat.conditional": repeat_conditional.value,
                    "singleton.next": singleton_next.value,
                    "repeat.next": repeat_next.value,
                },
                "singleton-rich incidence must project more discovery than repeats",
            ),
            _scenario(
                "failure.adjustment",
                failure_passed,
                {
                    "without.failure.usability": (
                        singleton_projection.usable_observation_probability.value
                    ),
                    "with.failure.usability": (
                        failure_projection.usable_observation_probability.value
                    ),
                    "without.failure.next": singleton_next.value,
                    "with.failure.next": failure_next.value,
                },
                "failed observations must affect usability, not conditional richness",
            ),
            _scenario(
                "position.equivariance",
                position_passed,
                {
                    "expected.total.max.delta": expected_total_delta,
                    "expected.yield.max.delta": expected_yield_delta,
                },
                "permuting anonymous vector positions must permute outputs exactly",
            ),
            _scenario(
                "uncertainty.contraction",
                contraction_passed,
                {
                    "lower.information.width": lower_width,
                    "higher.information.width": higher_width,
                    "shared.point": lower_band.value,
                },
                "equal-rate histories with more information must narrow uncertainty",
            ),
            _scenario(
                "deterministic.repeat",
                deterministic_passed,
                {"equal": float(deterministic_passed)},
                "identical numeric inputs must produce identical projections",
            ),
        )
    )


rarefaction_function_library = FunctionLibrary(
    evaluated_interfaces=("rarefaction.numeric_incidence",),
)
PAIRED_INCIDENCE = rarefaction_function_library.register(
    LibraryFunction(
        library="rarefaction",
        function_id="paired_incidence",
        interface="rarefaction.numeric_incidence",
        description=(
            "Estimate full-history paired-incidence richness and expected next "
            "yield bands independently at each anonymous vector position."
        ),
        implementation=FunctionImplementation(
            module="numeric_control_library.rarefaction",
            symbol="paired_incidence",
            is_async=False,
        ),
        input_type="NumericIncidenceState plus uncertainty_alpha",
        output_type="NumericYieldProjection",
        effect="Pure numerical estimation; no identity or decision state.",
        failure_contract=(
            "Returns insufficient bands when no usable incidence sample exists; "
            "rejects malformed numeric state and invalid confidence alpha."
        ),
        evaluation=FunctionEvaluationSpec(
            implementation=FunctionImplementation(
                module="numeric_control_library.rarefaction",
                symbol="evaluate_paired_incidence_scenarios",
                is_async=False,
            ),
            scenario_ids=_PAIRED_INCIDENCE_SCENARIOS,
            arguments={"uncertainty_alpha": 0.05},
        ),
        provenance={
            "richness_formula": "bias_corrected_chao2_delta_approximation",
            "next_yield_formula": "incidence_singleton_rate",
            "usability_formula": "wilson_observation_probability",
            "uncertainty_formula": "bonferroni_delta_approximation",
            "uncertainty_note": (
                "Bonferroni allocation over Wilson, Jeffreys-gamma Chebyshev, "
                "and plug-in Chao2 delta intervals; the Chao2 interval is an "
                "explicit approximation, not an exact coverage claim."
            ),
            "parameter_schema": {
                "type": "object",
                "properties": {
                    "uncertainty_alpha": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "exclusiveMaximum": 1,
                    }
                },
                "required": ["uncertainty_alpha"],
                "additionalProperties": False,
            },
        },
    )
)


__all__ = [
    "PAIRED_INCIDENCE",
    "evaluate_paired_incidence_scenarios",
    "paired_incidence",
    "rarefaction_function_library",
    "validate_paired_incidence_parameters",
]
