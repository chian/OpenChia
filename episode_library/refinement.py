"""The seven roles of one nested IterativeEpisodeRefiner.

All roles share one host operation path and one evaluation path. Parts owns
decomposition; Designer owns implementation and independent part acceptance.
The host connects these entries to normal build finalization through the shared
experiment service; importing the library alone starts no work.

Materialization keeps one result channel named ``report``. Generated ABI wrappers
delegate build_episode to BUILD_EPISODE with the frozen role and their own
RESULT_CHANNEL_IDS as declared_channel_ids. BUILD_RESULT and RECEIVE_CHILD bind
RESULT_PAYLOAD and the exact applicable node/edge result channel IDs. Only the
launch module exports the root goal builders; its scope_goal_state returns a
fresh MappingProxyType({"goal": goal.objective}), as the library child caller does.
The launch and Parts entries share the same Parts source/controller. Their
different request admission functions must never be interchanged.
"""

from function_library.episode_calls import BUILD_REPEATABLE_CHILD
from function_library.refinement import (
    ADMIT_CALL,
    ATTENUATE,
    BUILD_EPISODE,
    BUILD_RESULT,
    CONTROLLER,
    OPEN_SOURCE,
    PREPARE_CHILD,
    RECEIVE_CHILD,
    REQUEST_SCHEMA,
    SCHEMA,
    refinement_function_library,
)
from function_library.refinement_contract import REQUEST_PAYLOAD, RESULT_PAYLOAD, ROLES
from handoff_library import (
    ADMIT_DUET_LAUNCH_REQUEST,
    ADMIT_PARENT_REQUEST,
    HandoffPayloadContract,
)
from method_loop import (
    EpisodeBindingDeclaration,
    EpisodeChildSlot,
    EpisodeControllerBinding,
    EpisodeTopologyRole,
)
from numeric_control_library import (
    MARGINAL_DOMINATED_HYPERVOLUME,
    PAIRED_INCIDENCE,
    PREDICTED_CREDIT_UPPER_BOUND,
)

from .models import EpisodeLibraryDesign


def _design(name, *, launch=False):
    role = ROLES[name]
    entry = "launch" if launch else name
    admission = ADMIT_DUET_LAUNCH_REQUEST if launch else ADMIT_PARENT_REQUEST
    request_payload = HandoffPayloadContract() if launch else REQUEST_PAYLOAD
    guards = tuple(
        function.bind(f"repeatable_{child}_{suffix}")
        for child in role.children
        for suffix, function in (
            ("request_schema", REQUEST_SCHEMA),
            ("invocation_admission", ADMIT_CALL),
            ("authority_attenuation", ATTENUATE),
        )
    )
    binding = EpisodeBindingDeclaration(
        grain_name=f"refine_{entry}",
        interface=f"refinement.{entry}",
        topology_role=EpisodeTopologyRole.BRANCH
        if role.children
        else EpisodeTopologyRole.LEAF,
        goal=role.goal,
        unit=role.unit,
        result="A correlated host-derived report of exact candidate evidence and unresolved requirements.",
        progress=role.progress,
        stopping="The host's registered yield rule returns; external stops and parent decisions stay distinct.",
        admit_request=admission.bind(
            "admit_request",
            arguments={"payload_contract": request_payload.as_record()},
        ),
        open_source=OPEN_SOURCE.bind(
            "open_source", arguments={"role": name, "model_type": "refinement"}
        ),
        controller=EpisodeControllerBinding(
            schema=SCHEMA.bind("schema"),
            composer=CONTROLLER.bind("compose_controller"),
            credit=MARGINAL_DOMINATED_HYPERVOLUME.bind("credit"),
            rarefaction=PAIRED_INCIDENCE.bind(
                "rarefaction", arguments={"uncertainty_alpha": 0.05}
            ),
            continuation=PREDICTED_CREDIT_UPPER_BOUND.bind(
                "continuation",
                arguments={"max_predicted_marginal_hypervolume": 0.01},
            ),
        ),
        build_result=BUILD_RESULT.bind(
            "build_result", arguments={"payload_contract": RESULT_PAYLOAD.as_record()}
        ),
        components=(
            BUILD_EPISODE.bind(
                "build_episode", arguments={"role": name, "model_type": "refinement"}
            ),
            *guards,
        ),
        child_slots=tuple(
            EpisodeChildSlot(
                name=child,
                accepted_interfaces=(f"refinement.{child}",),
                build_child=BUILD_REPEATABLE_CHILD.bind(f"build_{child}"),
                prepare_request=PREPARE_CHILD.bind(f"prepare_{child}"),
                receive_result=RECEIVE_CHILD.bind(
                    f"receive_{child}",
                    arguments={"payload_contract": RESULT_PAYLOAD.as_record()},
                ),
            )
            for child in role.children
        ),
    )
    definitions = {
        function.definition_id: function
        for function in (
            *refinement_function_library.functions(),
            admission,
            BUILD_REPEATABLE_CHILD,
            MARGINAL_DOMINATED_HYPERVOLUME,
            PAIRED_INCIDENCE,
            PREDICTED_CREDIT_UPPER_BOUND,
        )
    }
    selected = {item.definition_id for item in binding.function_bindings()}
    return EpisodeLibraryDesign(
        qualified_name=binding.interface,
        title=role.title,
        binding=binding,
        function_definitions=tuple(definitions[key] for key in sorted(selected)),
        source_symbols=(),
    )


# The launch binding is not an eighth role or an extra unit. Both Parts entries
# execute the same loop; only their incoming address/contract differs. Recursive
# calls target the parent-request entry, never the empty Duet launch boundary.
LAUNCH_DESIGN = _design("parts", launch=True)
ROLE_DESIGNS = tuple(_design(name) for name in ROLES)
DESIGNS = (LAUNCH_DESIGN, *ROLE_DESIGNS)


def resolve_reference(reference):
    """Resolve only an exact registered refiner reference, not a name lookalike."""
    if reference is None:
        return None
    return next(
        (item for item in DESIGNS if item.episode_id == reference.episode_id), None
    )


def execution_bindings(binding):
    """The fixed adapters selected by a refiner reference, not generated policy."""
    components = {item.name: item for item in binding.components}
    return (
        ("admit_request", binding.admit_request),
        ("open_source", binding.open_source),
        ("build_result", binding.build_result),
        ("controller.schema", binding.controller.schema),
        ("controller.composer", binding.controller.composer),
        ("controller.credit", binding.controller.credit),
        ("component.build_episode", components["build_episode"]),
    )


def materialization_bindings(reference):
    design = resolve_reference(reference)
    if design is None:
        return ()
    return tuple(
        {
            "role": role,
            "source": "library",
            **{
                key: value
                for key, value in selection.as_record().items()
                if key != "name"
            },
            "basis": f"frozen episode_reference.{design.episode_id}.{role}",
        }
        for role, selection in execution_bindings(design.binding)
    )
