"""Registered, deterministic sources of requirement-specific measurement evidence.

These functions receive the original approved task, never candidate output. A
non-applicable source returns None; it cannot invent an interpretation of prose.
The result is available evidence, not an admitted measure or acceptance verdict.
"""

from .epistemic_contract import exact
from .models import FunctionImplementation, LibraryFunction
from .registry import FunctionLibrary


refinement_grounding_library = FunctionLibrary()
SCHEDULE_REQUIREMENT = refinement_grounding_library.register(
    LibraryFunction(
        library="refinement_grounding",
        function_id="schedule_requirement_v1",
        interface="refinement.requirement_grounding",
        description="Ground the exact seven-job scheduling goal using independent exhaustive enumeration; does not cover other contract fields or nested result routing.",
        implementation=FunctionImplementation(
            module="function_library.scheduling_benchmark",
            symbol="ground_requirement",
            is_async=False,
        ),
        input_type="Original approved workflow and one original requirement",
        output_type="Grounded predicate, controls, observation contract and limitations, or None",
        effect="Pure task-only derivation; never reads candidate code, proposed answers or model scores.",
        failure_contract="No match for a different goal, changed problem data or unsupported result routing.",
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


def resolve_grounding(selection):
    exact(
        selection,
        {"library", "function_id", "interface", "definition_id", "arguments"},
        "requirement grounding function",
    )
    function = refinement_grounding_library.resolve(
        f"{selection['library']}.{selection['function_id']}"
    )
    if (
        selection["definition_id"] != function.definition_id
        or selection["interface"] != function.interface
    ):
        raise ValueError("grounding function differs from its frozen selection")
    function.admit_arguments(selection["arguments"])
    return function.load()
