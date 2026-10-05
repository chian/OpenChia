"""Reference testing Episode; task-specific access and criteria require approval."""

from dataclasses import replace

from function_library.epistemic import default_components
from function_library.epistemic_contract import EpistemicContract
from function_library.testing import (
    ADMISSION,
    OPEN_SOURCE,
    RESULT_PROJECTION,
    testing_function_library,
)
from function_library.testing_admission import MEASUREMENT_KIND
from .models import EpisodeLibraryDesign
from .reasoning import BINDING as REASONING_BINDING, DESIGN as REASONING_DESIGN


def testing_learning_contract(*, goal_class, domain, environment):
    components = default_components()
    for role, function in (
        ("admission", ADMISSION),
        ("result_projection", RESULT_PROJECTION),
    ):
        selection = function.bind(role).as_record()
        selection.pop("name")
        components[role] = selection
    return EpistemicContract(
        goal_class=goal_class,
        domain=domain,
        allowed_actions=("history", "inventory", "preview", "run", "continue", "results", "status", "compare", "recording", "boundary"),
        environment=environment,
        assumptions=(),
        required_fields=("measurement",),
        required_evidence=(MEASUREMENT_KIND,),
        components=components,
    )


BINDING = replace(
    REASONING_BINDING,
    grain_name="testing",
    interface="reasoning.testing",
    goal="Design and perform justified experiments on assigned Episode candidates.",
    unit="Choose an experiment or evidence inspection, then propose supported findings for host admission.",
    result="Measured requirement findings, evidence, limitations and unresolved questions; no implicit parent acceptance.",
    open_source=OPEN_SOURCE.bind(
        "open_source", arguments=REASONING_BINDING.open_source.arguments
    ),
    components=REASONING_BINDING.components
    + tuple(
        function.bind(f"testing_{function.function_id}")
        for function in testing_function_library.functions()
        if function is not OPEN_SOURCE
    ),
)
DESIGN = EpisodeLibraryDesign(
    qualified_name="reasoning.testing",
    title="Evidence-directed Episode testing",
    binding=BINDING,
    function_definitions=tuple(
        function
        for function in REASONING_DESIGN.function_definitions
        if function.definition_id != REASONING_BINDING.open_source.definition_id
    )
    + testing_function_library.functions(),
    source_symbols=(),
)
