"""Small registered host predicates, not model-authored quality ratings."""

from collections.abc import Mapping

from .epistemic_contract import exact
from .epistemic_schemas import canonical
from .models import FunctionImplementation, LibraryFunction
from .registry import FunctionLibrary


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
