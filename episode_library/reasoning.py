"""Generic reasoning: adaptive inquiry inside an exact host-governed contract.

Materialize an ordinary Episode with explicitly selected model slots, the host receipt
controller, and build_reasoning_result. The runtime injects the learning
transport; generated modules must never implement a replacement ledger.
The exact EpistemicContract is required in the human-approved Architecture.
"""

from function_library.epistemic import epistemic_function_library
from function_library.reasoning import OPEN_SOURCE, BUILD_RESULT, CONTROLLER, SCHEMA
from handoff_library import ADMIT_PARENT_REQUEST
from method_loop import (
    EpisodeBindingDeclaration,
    EpisodeControllerBinding,
    EpisodeTopologyRole,
)
from numeric_control_library import (
    MARGINAL_DOMINATED_HYPERVOLUME,
    PAIRED_INCIDENCE,
    PREDICTED_CREDIT_UPPER_BOUND,
)

from .models import EpisodeLibraryDesign


BINDING = EpisodeBindingDeclaration(
    grain_name="reasoning",
    interface="reasoning.generic",
    topology_role=EpisodeTopologyRole.LEAF,
    goal="Resolve a declared qualitative question using admitted evidence and durable scoped learning.",
    unit="One adaptive action from the frozen action set, followed by host admission and measurement.",
    result="Typed supported formulations, answer criteria, unresolved uncertainties and conditional lessons.",
    progress="Distinct admitted operative epistemic state transitions, measured by the host.",
    stopping="The registered numerical continuation rule resolves false after projected yield rarefies.",
    admit_request=ADMIT_PARENT_REQUEST.bind("admit_request"),
    # Reference choices are visible binding arguments; materialization selects
    # names from the project's approved launch catalog for each operation.
    open_source=OPEN_SOURCE.bind("open_source", arguments={
        "selection_model_type": "reasoning", "execution_model_type": "reasoning",
    }),
    controller=EpisodeControllerBinding(
        schema=SCHEMA.bind("schema"),
        composer=CONTROLLER.bind("compose_controller"),
        credit=MARGINAL_DOMINATED_HYPERVOLUME.bind("credit"),
        rarefaction=PAIRED_INCIDENCE.bind(
            "rarefaction", arguments={"uncertainty_alpha": 0.05}
        ),
        continuation=PREDICTED_CREDIT_UPPER_BOUND.bind(
            "continuation", arguments={"max_predicted_marginal_hypervolume": 0.01}
        ),
    ),
    build_result=BUILD_RESULT.bind("build_result"),
    components=tuple(
        f.bind(f"epistemic_{f.interface.split('.')[-1]}")
        for f in epistemic_function_library.functions()
    ),
)
DESIGN = EpisodeLibraryDesign(
    qualified_name="reasoning.generic",
    title="Generic evidence-grounded reasoning",
    binding=BINDING,
    function_definitions=(
        ADMIT_PARENT_REQUEST,
        OPEN_SOURCE,
        BUILD_RESULT,
        CONTROLLER,
        SCHEMA,
        MARGINAL_DOMINATED_HYPERVOLUME,
        PAIRED_INCIDENCE,
        PREDICTED_CREDIT_UPPER_BOUND,
        *epistemic_function_library.functions(),
    ),
    source_symbols=(),
)
