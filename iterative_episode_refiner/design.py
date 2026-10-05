"""The refiner's complete workflow proposal for ordinary Duet approval/build.

Template placement is just the materializer's concrete tree. The declared call
edges express actual ownership and reuse; they do not follow the target build.
Constructing this value neither approves it nor starts a Run.
"""

from agent.episode_call_contracts import EpisodeRepeatableCallSpec
from agent.episode_contract_models import (
    EpisodeCreationSpec,
    EpisodeDesignSpec,
    EpisodeFunctionSelectionSpec,
    EpisodeNumericalControlSpec,
    EpisodeWorkflowSpec,
)
from episode_library.models import EpisodeReference
from episode_library.refinement import DESIGNS
from function_library.refinement import (
    ADMIT_CALL,
    ATTENUATE,
    PREPARE_CHILD,
    RECEIVE_CHILD,
    REPORT_CHILD,
    REQUEST_SCHEMA,
)
from function_library.refinement_contract import RESULT_PAYLOAD, ROLES


# Every template has one concrete home. Other approved parents call that same
# template; only Parts has a recursive Parts slot or a Designer slot.
_PARENTS = {
    "launch": None,
    "parts": "launch",
    "designer": "parts",
    "implementer": "designer",
    "support": "parts",
    "question": "parts",
    "measure": "parts",
    "verify": "parts",
}


def _selection(function, *, arguments=None):
    return EpisodeFunctionSelectionSpec(
        library=function.library,
        function_id=function.function_id,
        interface=function.interface,
        definition_id=function.definition_id,
        arguments=arguments or {},
    )


def refinement_workflow_spec():
    designs = {
        item.qualified_name.removeprefix("refinement."): item for item in DESIGNS
    }
    episodes = []
    calls = []
    for name in _PARENTS:
        role = ROLES["parts" if name == "launch" else name]
        design = designs[name]
        binding = design.binding
        numeric = {}
        for kind in ("rarefaction", "continuation"):
            selected = getattr(binding.controller, kind).as_record()
            numeric[kind] = EpisodeFunctionSelectionSpec.from_record({
                key: value for key, value in selected.items() if key != "name"
            })
        episodes.append(
            EpisodeDesignSpec(
                local_id=name,
                workflow_parent_local_id=_PARENTS[name],
                contract=EpisodeCreationSpec(
                    goal=role.goal,
                    unit=role.unit,
                    result=binding.result,
                    progress=role.progress,
                    stopping=binding.stopping,
                    numeric_control=EpisodeNumericalControlSpec(**numeric),
                ),
                episode_reference=EpisodeReference(design.episode_id),
            )
        )
        for child in role.children:
            if _PARENTS[child] == name:
                continue
            calls.append(
                EpisodeRepeatableCallSpec(
                    caller_local_id=name,
                    slot_name=child,
                    callee_template_local_id=child,
                    prepare_request=_selection(PREPARE_CHILD),
                    receive_result=_selection(
                        RECEIVE_CHILD,
                        arguments={"payload_contract": RESULT_PAYLOAD.as_record()},
                    ),
                    synthesize_report=_selection(REPORT_CHILD),
                    request_schema=_selection(REQUEST_SCHEMA),
                    invocation_admission=_selection(ADMIT_CALL),
                    authority_attenuation=_selection(ATTENUATE),
                )
            )
    return EpisodeWorkflowSpec(tuple(episodes), tuple(calls))
