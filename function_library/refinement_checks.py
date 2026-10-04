"""Small registered host predicates, not model-authored quality ratings."""

from collections.abc import Mapping

from .epistemic_contract import exact
from .epistemic_schemas import canonical
from .models import FunctionImplementation, LibraryFunction
from .registry import FunctionLibrary
from .record_conditions import CONDITION_LANGUAGE


def exact_value(*, observed, expected):
    """Keep JSON types exact: True is not the integer 1."""
    return "pass" if canonical(observed) == canonical(expected) else "fail"


def grounding_payload(*, observed, expected):
    """Shape only; the separate frozen acquisition policy must authorize truth."""
    exact(expected, {"control_kind"}, "grounding acquisition shape")
    if expected["control_kind"] not in {"predicate", "execution"}:
        raise ValueError("unknown grounding control kind")
    try:
        result = exact(
            observed,
            {"expected", "positive_controls", "negative_controls"},
            "grounding result",
        )
        canonical(result)
        controls = [result["positive_controls"], result["negative_controls"]]
        if any(
            not isinstance(values, (list, tuple)) or not values for values in controls
        ):
            return "fail"
        field = (
            "observed" if expected["control_kind"] == "predicate" else "typed_status"
        )
        seen = set()
        for values in controls:
            for value in values:
                exact(value, {field}, "independent control input")
                if field == "typed_status" and not isinstance(value[field], Mapping):
                    return "fail"
                key = canonical(value)
                if key in seen:
                    return "fail"
                seen.add(key)
    except (ValueError, TypeError):
        return "fail"
    return "pass"


refinement_check_library = FunctionLibrary()
EXACT_VALUE = refinement_check_library.register(
    LibraryFunction(
        library="refinement_checks",
        function_id="exact_value_v1",
        interface="refinement.predicate",
        description="Compare an independently grounded expected JSON value with committed observations.",
        implementation=FunctionImplementation(
            module="function_library.refinement_checks",
            symbol="exact_value",
            is_async=False,
        ),
        input_type="Committed typed observed value and frozen grounded expected value",
        output_type="pass | fail",
        effect="Pure canonical comparison; does not establish grounding or execution authority.",
        failure_contract="Reject non-finite or non-JSON values; never coerce a malformed answer.",
        provenance={
            "schema_version": 1,
            "parameter_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    )
)

GROUNDING_PAYLOAD = refinement_check_library.register(
    LibraryFunction(
        library="refinement_checks",
        function_id="grounding_payload_v1",
        interface="refinement.predicate",
        description="Validate a typed grounding payload from a separately authorized evidence source; not a truth or adequacy verdict.",
        implementation=FunctionImplementation(
            module="function_library.refinement_checks",
            symbol="grounding_payload",
            is_async=False,
        ),
        input_type="Committed expected value and positive/negative control inputs; fixed control kind",
        output_type="pass | fail",
        effect="Pure shape validation. Only the frozen source/projection authority can make the values usable grounding.",
        failure_contract="Reject malformed, empty, repeated or contradictory control inputs; no model self-certification.",
        provenance={
            "schema_version": 1,
            "parameter_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    )
)


OPTIMAL_SCHEDULE = refinement_check_library.register(
    LibraryFunction(
        library="refinement_checks",
        function_id="optimal_resource_schedule_v1",
        interface="refinement.predicate",
        description="Check the fixed seven-job schedule for feasibility, truthful completion time and independently enumerated optimality; explanation text is not a correctness signal.",
        implementation=FunctionImplementation(
            module="function_library.scheduling_benchmark",
            symbol="check_optimal_schedule",
            is_async=False,
        ),
        input_type="String-valued schedule, makespan and optimality_argument fields; expected benchmark_id=seven_job_resource_schedule_v1",
        output_type="pass | fail",
        effect="Pure host calculation over the fixed benchmark; accepts all optimal witnesses and preserves the original answer as measurement evidence.",
        failure_contract="Reject malformed, infeasible, nonoptimal or incorrectly reported schedules; reject unknown benchmark identities; prose cannot award a pass.",
        provenance={
            "schema_version": 1,
            "parameter_schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    )
)


RECORD_CONDITIONS = refinement_check_library.register(
    LibraryFunction(
        library="refinement_checks",
        function_id="record_conditions_v1",
        interface="refinement.predicate",
        description="Evaluate typed structural conditions and relationships over actual recorded evidence, including array quantifiers and existing registered answer predicates. Does not create fields or certify model claims.",
        implementation=FunctionImplementation(
            module="function_library.record_conditions",
            symbol="record_conditions",
            is_async=False,
        ),
        input_type="Observed JSON record; expected is one condition from provenance.condition_language.",
        output_type="pass | fail | inconclusive",
        effect="Pure record projection and comparison. No code evaluation, network, state mutation or model scoring.",
        failure_contract="Reject unknown conditions or predicates. Missing data stays inconclusive, including under negation; exact JSON types are preserved.",
        provenance={
            "schema_version": 1,
            "parameter_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            "condition_language": CONDITION_LANGUAGE,
        },
    )
)


def resolve_predicate(selection):
    from .materialization_checks import materialization_check_library

    library = {
        "refinement_checks": refinement_check_library,
        "materialization_checks": materialization_check_library,
    }[selection["library"]]
    function = library.resolve(f"{selection['library']}.{selection['function_id']}")
    if (
        function.definition_id != selection["definition_id"]
        or function.interface != selection["interface"]
    ):
        raise ValueError("check definition differs from its frozen selection")
    function.admit_arguments(selection["arguments"])
    if function.interface == "materialization.validation" and selection["arguments"]:
        raise ValueError(
            "materialization checks consume host-resolved typed artifacts, not arbitrary arguments"
        )
    return function.load()
