"""The computation estimator is executable and keeps its model contract explicit."""

import json

import pytest

from episode_builder.planner import materializer_function_catalog
from function_library import FunctionImplementation
from numeric_control_library import VALUE_OF_COMPUTATION, BayesianTransitionModel
from numeric_control_library.rarefaction import rarefaction_function_library
from numeric_control_library.value_of_computation import (
    yield_estimator_function_library,
)


def test_catalog_resolves_and_runs_the_evaluated_estimator():
    definition = next(
        entry
        for entry in materializer_function_catalog()
        if entry["definition_id"] == VALUE_OF_COMPUTATION.definition_id
    )
    implementation = definition["implementation"]
    function = FunctionImplementation(
        module=implementation["module"],
        symbol=implementation["symbol"],
        is_async=implementation["is_async"],
    ).load()
    assert (
        yield_estimator_function_library.resolve(
            VALUE_OF_COMPUTATION.component_id
        ).load()
        is function
    )
    assert yield_estimator_function_library.evaluation_report(
        VALUE_OF_COMPUTATION.component_id
    ).passed

    model = BayesianTransitionModel()
    model.register_state("before", score=0, actions=("try", "untried"))
    model.register_state("after", score=1)
    model.observe(
        "executed:1",
        state="before",
        action="try",
        next_state="after",
        evidence_refs=["fixture:result"],
    )
    restored = BayesianTransitionModel.from_snapshot(
        json.loads(json.dumps(model.snapshot()))
    )
    arguments = VALUE_OF_COMPUTATION.admit_arguments({"lookahead": 2})
    report = function(restored, "before", **arguments)
    assert report.best_modeled_action == "try"
    assert report.estimates[0].expected_gain == 1
    assert "executed:1" in report.estimates[0].evidence_ids
    assert report.estimates[1].expected_gain is None


def test_model_estimator_cannot_masquerade_as_incidence_estimation():
    # Dispersion is not a confidence band; incidence counts cannot reconstruct
    # diagnostic states. Existing controllers retain their own admitted inputs.
    assert all(
        entry.interface != VALUE_OF_COMPUTATION.interface
        for entry in rarefaction_function_library.functions()
    )
    with pytest.raises(ValueError, match="unknown library function"):
        rarefaction_function_library.resolve(VALUE_OF_COMPUTATION.component_id)
    VALUE_OF_COMPUTATION.admit_arguments({})
    for arguments in (
        {"lookahead": 0},
        {"lookahead": True},
        {"lookahead": 1.5},
        {"uncertainty_alpha": 0.05},
    ):
        with pytest.raises(ValueError):
            VALUE_OF_COMPUTATION.admit_arguments(arguments)
