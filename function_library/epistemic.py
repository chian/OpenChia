"""Versioned epistemic functions registered through the common function library."""

from .models import FunctionImplementation, LibraryFunction
from .registry import FunctionLibrary
from .epistemic_schemas import ATTEMPT_SHAPE


epistemic_function_library = FunctionLibrary()


def _register(role, symbol, module, description):
    return epistemic_function_library.register(
        LibraryFunction(
            library="epistemic",
            function_id=f"{role}_v1",
            interface=f"epistemic.{role}",
            description=description,
            implementation=FunctionImplementation(
                module=f"function_library.{module}", symbol=symbol, is_async=False
            ),
            input_type="Frozen contract and closed typed records",
            output_type="Validated typed state projection",
            effect="Deterministic host function over committed evidence; no model or network calls.",
            failure_contract="Reject unknown fields, unsupported claims, scope escalation and uncommitted evidence.",
            provenance={
                "schema_version": 1,
                **({"result_shape": ATTEMPT_SHAPE} if role == "result_schema" else {}),
                "parameter_schema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        )
    )


RESULT_SCHEMA = _register(
    "result_schema",
    "validate_attempt",
    "epistemic_schemas",
    "Validate the closed generic reasoning unit result, version 1.",
)
STATE_PROJECTOR = _register(
    "state_projector",
    "project_candidates",
    "epistemic_schemas",
    "Project candidate operations without admitting them.",
)
ADMISSION = _register(
    "admission",
    "admit_candidates",
    "epistemic_admission",
    "Admit scoped evidence-backed learning with conservative equivalence checks.",
)
YIELD_FUNCTION = _register(
    "yield_function",
    "measure_yield",
    "epistemic_admission",
    "Measure distinct operative state transitions; failure and narration alone yield zero.",
)
RESULT_PROJECTION = _register(
    "result_projection",
    "project_result",
    "epistemic_schemas",
    "Project active formulations, answer contracts, lessons and retired routes as data.",
)


def default_components():
    return {
        function.interface.split(".")[-1]: {
            key: function.bind("component").as_record()[key]
            for key in (
                "library",
                "function_id",
                "interface",
                "definition_id",
                "arguments",
            )
        }
        for function in epistemic_function_library.functions()
    }


def resolve_component(role, selection):
    function = epistemic_function_library.resolve(
        f"{selection['library']}.{selection['function_id']}"
    )
    if (
        function.interface != f"epistemic.{role}"
        or function.interface != selection["interface"]
        or function.definition_id != selection["definition_id"]
    ):
        raise ValueError(
            "epistemic function identity/version does not match the frozen contract"
        )
    function.admit_arguments(selection["arguments"])
    return function
