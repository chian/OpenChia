"""Registered refinement control: numeric opportunities, never a turn budget."""

from .epistemic_contract import exact, names
from .models import FunctionImplementation, LibraryFunction
from .registry import FunctionLibrary
from numeric_control_library.credit_assignment import (
    NumericBand,
    NumericYieldProjection,
)
from numeric_control_library.rarefaction import paired_incidence


def semantic_yield(*, prior_fact_keys, admitted_fact_keys):
    prior = set(names(prior_fact_keys, "prior facts"))
    admitted = set(names(admitted_fact_keys, "admitted facts"))
    fresh = sorted(admitted - prior)
    return {
        "semantic_fact_keys": fresh,
        "credit_before": len(prior),
        "credit_after": len(prior) + len(fresh),
        "realized_yield": len(fresh),
    }


def bounded_rarefaction(state, parameters, *, remaining_opportunities):
    """Only an independently established numeric zero bypasses estimation.

    Unknown opportunity count delegates to the existing estimator. A model's
    exhausted ideas, an absent action, and an interrupted process are not zero.
    """
    if remaining_opportunities is None:
        return paired_incidence(state, parameters)
    if type(remaining_opportunities) is not int or remaining_opportunities != 0:
        raise ValueError("v1 accepts only an unknown or proven-zero opportunity bound")
    base = paired_incidence(state, parameters)
    zero = tuple(NumericBand.exact(0) for _ in state.positions)
    return NumericYieldProjection(
        source_state=state,
        expected_totals=tuple(NumericBand.exact(row[0]) for row in state.positions),
        expected_next_yields=zero,
        conditional_next_yields=zero,
        usable_observation_probability=NumericBand.exact(1),
        joint_uncertainty_alpha=base.joint_uncertainty_alpha,
    )


refinement_control_library = FunctionLibrary()


def _register(name, symbol, interface, description):
    return refinement_control_library.register(
        LibraryFunction(
            library="refinement_control",
            function_id=name,
            interface=interface,
            description=description,
            implementation=FunctionImplementation(
                module=__name__, symbol=symbol, is_async=False
            ),
            input_type="Host-admitted durable facts or numerical sufficient statistics",
            output_type="Exact realized measurement or numerical projected-yield bands",
            effect="Deterministic; no model, network, persistence mutation or semantic budgets.",
            failure_contract="Reject unsupported opportunity bounds and duplicate/non-typed facts.",
            provenance={"schema_version": 1},
        )
    )


SEMANTIC_YIELD = _register(
    "semantic_yield_v1",
    "semantic_yield",
    "refinement.yield",
    "Count new admitted semantic facts; restoring an old pass earns no new credit.",
)
BOUNDED_RAREFACTION = _register(
    "bounded_rarefaction_v1",
    "bounded_rarefaction",
    "refinement.rarefaction",
    "Use paired incidence unless host-validated attainment establishes zero remaining opportunities.",
)


def resolve_selection(selection, expected):
    exact(
        selection,
        {"library", "function_id", "interface", "definition_id", "arguments"},
        "refinement function selection",
    )
    function = refinement_control_library.resolve(
        f"{selection['library']}.{selection['function_id']}"
    )
    if (
        function != expected
        or function.definition_id != selection["definition_id"]
        or function.interface != selection["interface"]
        or selection["arguments"]
    ):
        raise ValueError("refinement control differs from the approved v1 definition")
    return function.load()
