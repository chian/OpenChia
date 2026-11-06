"""Library bindings for nano-graphrag's unchanged preferential-discovery model.

The implementation lives beside this file in ``preferential_discovery.py``.
Its ordered observation history and warm-start fit cannot be reconstructed from
the older Chao2 component's anonymous frequency-of-frequencies state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from function_library import (
    FunctionEvaluationReport,
    FunctionEvaluationSpec,
    FunctionImplementation,
    FunctionLibrary,
    FunctionScenarioOutcome,
    LibraryFunction,
    SourceSymbolReference,
)
from method_loop import ClosedRecord, ControllerFactory

from . import preferential_discovery as upstream
from .controller import controller_function_library


SOURCE_REPOSITORY = "https://github.com/chian/nano-graphrag"
SOURCE_REVISION = "60a167f9eeda0c9ea2ca294724174948947baf3f"
SOURCE_PATH = "question_pipeline/utilities/rarefaction.py"
SOURCE_SHA256 = "02af19652d69f368ee8875d3b27cad0bb2bbc8d1f8274344b72a4437092cdd35"

PreferentialChannelSchema = upstream.ChannelSchema
PreferentialControllerConfig = upstream.ControllerConfig
PreferentialDiscoveryEstimator = upstream._IncidenceEstimator
PreferentialEstimatorController = upstream.EstimatorController
PREFERENTIAL_OBSERVED = upstream.OBSERVATION_OBSERVED
PREFERENTIAL_FAILED = upstream.OBSERVATION_FAILED
PREFERENTIAL_EXCLUDED = upstream.OBSERVATION_EXCLUDED


@dataclass(frozen=True)
class PreferentialIncidenceObservation(upstream.IncidenceObservation, ClosedRecord):
    """The original observation admitted at OpenChia's closed-record boundary.

    Use inherited ``failed`` and ``excluded`` constructors to distinguish acquisition
    failure from an evaluated zero-discovery attempt and from a non-observation.
    """


def joint_preferential_discovery(
    *,
    scope_path: tuple[tuple[str, str], ...],
    epoch: str,
    channel: str = upstream.DEFAULT_CHANNEL,
    window_size: int = upstream.DEFAULT_WINDOW_SIZE,
    subsample_size: int = upstream.DEFAULT_SUBSAMPLE_SIZE,
    alpha: float = upstream.DEFAULT_ALPHA,
) -> PreferentialDiscoveryEstimator:
    """Open the original estimator, retaining ordered attempts and fit state.

    Call ``observe(label, identities, observation_status=...)`` once per completed
    unit and ``snapshot()`` for the fitted report. The two size parameters are
    minimum data requirements before fitting, not limits on execution or history.
    """

    return PreferentialDiscoveryEstimator(
        window_size=window_size,
        subsample_size=subsample_size,
        alpha=alpha,
        scope_path=scope_path,
        epoch=epoch,
        channel=channel,
    )


def compose_preferential_controller(
    *,
    epoch: str,
    channel_schema: PreferentialChannelSchema,
    control: PreferentialControllerConfig,
    window_size: int = upstream.DEFAULT_WINDOW_SIZE,
    subsample_size: int = upstream.DEFAULT_SUBSAMPLE_SIZE,
    alpha: float = upstream.DEFAULT_ALPHA,
    threshold_adapter: upstream.ThresholdAdapter | None = None,
) -> ControllerFactory:
    """Bind the original complete numerical component to ``Grain.controller``.

    Each invocation of the returned factory opens an independent, path-scoped
    estimator/controller, including all per-channel fits and threshold history.
    This composition consumes PreferentialIncidenceObservation, not CreditObservation.
    """

    return upstream.bind_controller(
        channel_schema=channel_schema,
        control=control,
        window_size=window_size,
        subsample_size=subsample_size,
        alpha=alpha,
        epoch=epoch,
        threshold_adapter=threshold_adapter,
    )


_PARAMETER_SCHEMA = {
    "type": "object",
    "properties": {
        "window_size": {"type": "integer", "minimum": 2},
        "subsample_size": {"type": "integer", "minimum": 1},
        "alpha": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
    },
    "additionalProperties": False,
}
_PROVENANCE = {
    "source_repository": SOURCE_REPOSITORY,
    "source_revision": SOURCE_REVISION,
    "source_path": SOURCE_PATH,
    "source_sha256": SOURCE_SHA256,
    "formula_version": upstream.RAREFACTION_FORMULA_VERSION,
    "estimator_version": upstream.INCIDENCE_ESTIMATOR_VERSION,
    "input_contract": "Ordered identity discoveries and observed/failed/excluded attempt status.",
    "inference": "Full-history warm-start MAP/BFGS; approximate Laplace uncertainty.",
    "parameter_schema": _PARAMETER_SCHEMA,
}
_SCENARIOS = (
    "startup.insufficient",
    "history.full",
    "exclusion.invariant",
    "scope.independent",
)


def evaluate_preferential_discovery_scenarios(
    implementation: Callable,
    parameters: Mapping[str, object],
) -> FunctionEvaluationReport:
    """Exercise the registered factory against required observation semantics."""

    scope = (("assessment", "fixture"),)
    estimator = implementation(scope_path=scope, epoch="fixture", **parameters)
    empty = estimator.snapshot()
    observations = parameters.get("window_size", upstream.DEFAULT_WINDOW_SIZE)
    for index in range(observations):
        estimator.observe(
            f"attempt:{index}",
            (f"result:{index}",) if index < 4 else (),
            observation_status=upstream.OBSERVATION_OBSERVED,
        )
    measured = estimator.snapshot()
    before = measured.control_statistics["expected_next_discoveries"]
    estimator.observe(
        "excluded",
        ("retained:excluded",),
        observation_status=upstream.OBSERVATION_EXCLUDED,
    )
    after = estimator.snapshot().control_statistics["expected_next_discoveries"]
    independent = implementation(scope_path=scope, epoch="other", **parameters)
    outcomes = (
        (
            "startup.insufficient",
            empty.expected_results.status_code == upstream.STATUS_INSUFFICIENT,
        ),
        (
            "history.full",
            measured.diagnostics["attempted_units"] == observations
            and measured.observed_results.value == min(4, observations)
            and before.status_code == upstream.STATUS_NORMAL,
        ),
        ("exclusion.invariant", before.as_record() == after.as_record()),
        ("scope.independent", independent.distinct == 0 and independent.units == 0),
    )
    return FunctionEvaluationReport(
        tuple(
            FunctionScenarioOutcome(
                scenario_id=name,
                passed=passed,
                measurements={"satisfied": float(passed)},
                failure=""
                if passed
                else f"preferential-discovery contract failed: {name}",
            )
            for name, passed in outcomes
        )
    )


preferential_function_library = FunctionLibrary(
    evaluated_interfaces=("rarefaction.preferential_incidence",),
)
JOINT_PREFERENTIAL_DISCOVERY = preferential_function_library.register(
    LibraryFunction(
        library="rarefaction",
        function_id="joint_preferential_discovery_v1",
        interface="rarefaction.preferential_incidence",
        description="Open nano-graphrag's ordered, full-history joint observation/discovery estimator.",
        implementation=FunctionImplementation(
            __name__, "joint_preferential_discovery", False
        ),
        input_type="scope_path, epoch and optional channel; window_size, subsample_size, alpha",
        output_type="PreferentialDiscoveryEstimator with observe and snapshot",
        effect="Retains ordered attempt history and numerical fit state; performs no acquisition.",
        failure_contract="Rejects invalid fit parameters; insufficient/unidentifiable estimates remain explicit.",
        source_symbols=(
            SourceSymbolReference(
                SOURCE_REPOSITORY,
                SOURCE_REVISION,
                SOURCE_PATH,
                "_IncidenceEstimator",
            ),
        ),
        evaluation=FunctionEvaluationSpec(
            FunctionImplementation(
                __name__, "evaluate_preferential_discovery_scenarios", False
            ),
            _SCENARIOS,
        ),
        provenance=_PROVENANCE,
    )
)

COMPOSE_PREFERENTIAL_CONTROLLER = controller_function_library.register(
    LibraryFunction(
        library="controller_composition",
        function_id="compose_preferential_controller",
        interface="controller.compose_preferential_incidence",
        description="Bind nano-graphrag's original estimator, hypervolume credit and numerical continuation per Episode path.",
        implementation=FunctionImplementation(
            __name__, "compose_preferential_controller", False
        ),
        input_type="epoch, PreferentialChannelSchema, PreferentialControllerConfig and optional fitting parameters/threshold adapter",
        output_type="ControllerFactory producing PreferentialEstimatorController",
        effect="Opens independent ordered histories at the existing Grain.controller boundary.",
        failure_contract="Requires original typed observations and valid numerical control; unavailable forecasts do not establish saturation.",
        source_symbols=(
            SourceSymbolReference(
                SOURCE_REPOSITORY,
                SOURCE_REVISION,
                SOURCE_PATH,
                "bind_controller",
            ),
        ),
        provenance={**_PROVENANCE, "controller_version": upstream.CONTROLLER_VERSION},
    )
)


__all__ = [
    "COMPOSE_PREFERENTIAL_CONTROLLER",
    "JOINT_PREFERENTIAL_DISCOVERY",
    "PREFERENTIAL_EXCLUDED",
    "PREFERENTIAL_FAILED",
    "PREFERENTIAL_OBSERVED",
    "PreferentialChannelSchema",
    "PreferentialControllerConfig",
    "PreferentialDiscoveryEstimator",
    "PreferentialEstimatorController",
    "PreferentialIncidenceObservation",
    "compose_preferential_controller",
    "joint_preferential_discovery",
]
