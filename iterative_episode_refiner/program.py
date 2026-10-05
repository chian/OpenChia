"""Materialize the shipped refiner adapters through ordinary Builder admission.

The refiner's role code is registered library code, not a task for another LLM
to reinvent. These deterministic adapters still go through the same plan, source,
manifest and confined Run boundaries as any other Episode. No model response is
fabricated, and no generated module is imported on the host.
"""

from episode_builder.emitter import EpisodeModuleEmitter, complete_module_source
from episode_builder.planner import EpisodeMaterializationPlanner
from episode_library.refinement import resolve_reference
from episode_library.models import EpisodeReference
from function_library.episode_calls import BUILD_REPEATABLE_CHILD
from function_library.refinement import PREPARE_CHILD, RECEIVE_CHILD


def _selection(role, function, arguments=None):
    record = function.bind(
        role.replace(".", "_"), arguments=arguments or {}
    ).as_record()
    record.pop("name")
    return {
        "role": role,
        "source": "library",
        **record,
        "basis": "shipped refiner adapter",
    }


class RefinerPlanner(EpisodeMaterializationPlanner):
    async def _plan_node(
        self, node, *, child_plans, architecture_numeric_bindings, **_kwargs
    ):
        design = resolve_reference(node.episode_reference)
        if design is None:
            raise ValueError(
                "the refiner materializer accepts only registered refiner roles"
            )
        context = self.reference_resolver.resolve(node.episode_reference)
        selected = list(architecture_numeric_bindings)
        slots = []
        for child in child_plans:
            name = child.interface.removeprefix("refinement.")
            for role, function in (
                ("build_child", BUILD_REPEATABLE_CHILD),
                ("prepare_request", PREPARE_CHILD),
                ("receive_result", RECEIVE_CHILD),
            ):
                selected.append(
                    _selection(
                        f"edge.{name}.{role}",
                        function,
                        {"payload_contract": child.result_payload_contract}
                        if role == "receive_result"
                        else {},
                    )
                )
            slots.append({
                "slot_name": name,
                "child_local_id": child.local_id,
                "child_interface": child.interface,
                "request_payload_contract": child.as_record()[
                    "request_payload_contract"
                ],
                "result_payload_contract": child.as_record()["result_payload_contract"],
                "build_child": "Use the declared refiner child",
                "prepare_request": "Use the parent's admitted assignment",
                "receive_result": "Admit the typed host report",
                "basis": "Registered refiner call topology",
            })
        return (
            {
                "interface": design.binding.interface,
                "result_channel_names": ["report"],
                "request_payload_contract": design.binding.admit_request.as_record()[
                    "arguments"
                ]["payload_contract"],
                "result_payload_contract": design.binding.build_result.as_record()[
                    "arguments"
                ]["payload_contract"],
                "selected_function_bindings": selected,
                "generated_component_specs": [],
                "prompt_specs": [],
                "goal_state_spec": {"owner": "host refinement campaign"},
                "child_slots": slots,
                "derivation_basis": {
                    "goal": "Registered refiner roles and call topology"
                },
                "unresolved": [],
            },
            context,
            None,
        )


def adapter_source(plan, contract, direct_edges):
    bindings = {
        item["role"]: dict(item)
        for item in plan.as_record()["selected_function_bindings"]
    }

    def selected(role):
        value = {
            key: bindings[role][key]
            for key in (
                "library",
                "function_id",
                "interface",
                "definition_id",
                "arguments",
            )
        }
        value["name"] = role.removeprefix("component.").replace(".", "_")
        return f"EpisodeFunctionBinding(**{value!r})"

    components = ",".join(
        selected(role) for role in bindings if role.startswith("component.")
    )
    slots = ",".join(
        f"EpisodeChildSlot(name={edge.slot_name!r}, accepted_interfaces=({edge.child_interface!r},), "
        f"build_child={selected('edge.' + edge.slot_name + '.build_child')}, "
        f"prepare_request={selected('edge.' + edge.slot_name + '.prepare_request')}, "
        f"receive_result={selected('edge.' + edge.slot_name + '.receive_result')})"
        for edge in direct_edges
    )
    root_builders = (
        ""
        if plan.parent_local_id is not None
        else """
def build_goal_state(request, collaborators):
    return refiner.build_goal_state(request, collaborators)
def scope_goal_state(goal_state, goal):
    return MappingProxyType({"goal": goal.objective})
"""
    )
    values = plan.as_record()
    return f"""
from types import MappingProxyType
from episode_library.models import EpisodeLibraryDesign
from function_library import refinement as refiner
from function_library.episode_calls import BUILD_REPEATABLE_CHILD
from method_loop import EpisodeBindingDeclaration, EpisodeChildSlot, EpisodeControllerBinding, EpisodeFunctionBinding, EpisodeTopologyRole
from handoff_library import HandoffPayloadContract, ADMIT_DUET_LAUNCH_REQUEST, ADMIT_PARENT_REQUEST
from numeric_control_library import MARGINAL_DOMINATED_HYPERVOLUME, PAIRED_INCIDENCE, PREDICTED_CREDIT_UPPER_BOUND
REQUEST_PAYLOAD_CONTRACT = HandoffPayloadContract.from_record({values["request_payload_contract"]!r})
RESULT_PAYLOAD_CONTRACT = HandoffPayloadContract.from_record({values["result_payload_contract"]!r})
PROMPTS = ()
EXECUTION_CAPABILITY_NAMES = {contract.execution_capability_names!r}
RESULT_CHANNEL_NAMES = {plan.result_channel_names!r}
RESULT_CHANNEL_IDS = {plan.result_channel_ids!r}
BINDING = EpisodeBindingDeclaration(
    grain_name={plan.grain_name!r}, interface={plan.interface!r}, topology_role=EpisodeTopologyRole.{plan.topology_role.upper()},
    goal={contract.goal!r}, unit={contract.unit!r}, result={contract.result!r},
    progress={contract.progress!r}, stopping={contract.stopping!r},
    admit_request={selected("admit_request")}, open_source={selected("open_source")},
    controller=EpisodeControllerBinding(schema={selected("controller.schema")}, composer={selected("controller.composer")},
        credit={selected("controller.credit")}, rarefaction={selected("controller.rarefaction")}, continuation={selected("controller.continuation")}),
    build_result={selected("build_result")}, components=({components},), child_slots=({slots}{"," if slots else ""}))
DESIGN = EpisodeLibraryDesign(qualified_name={plan.interface!r}, title="Registered refinement role", binding=BINDING,
    function_definitions=tuple(function for function in (*refiner.refinement_function_library.functions(),
        BUILD_REPEATABLE_CHILD, ADMIT_DUET_LAUNCH_REQUEST, ADMIT_PARENT_REQUEST,
        MARGINAL_DOMINATED_HYPERVOLUME, PAIRED_INCIDENCE, PREDICTED_CREDIT_UPPER_BOUND)
        if function.definition_id in {{selection.definition_id for selection in BINDING.function_bindings()}}), source_symbols=())
def build_controller_factory(goal_view, collaborators):
    return refiner.build_controller_factory(goal_view, collaborators)
{root_builders}
def build_episode(grain, key, request, goal_view, collaborators, child_builders):
    return refiner.build_refinement_episode(grain, key, request, goal_view, collaborators, child_builders,
        **BINDING.open_source.arguments, declared_channel_ids=RESULT_CHANNEL_IDS)
"""


class RefinerEmitter(EpisodeModuleEmitter):
    async def emit(
        self,
        *,
        contract,
        plan,
        direct_children,
        direct_edges,
        reference_context,
        target_module_name,
        forbidden_module_names=(),
        predecessor_module=None,
        **_kwargs,
    ):
        self._validate_inputs(
            contract,
            plan,
            direct_children,
            direct_edges,
            reference_context,
            target_module_name,
            predecessor_module,
        )
        if (
            resolve_reference(EpisodeReference(reference_context.design.episode_id))
            is None
        ):
            raise ValueError("the refiner emitter requires a registered refiner role")
        return complete_module_source(
            adapter_source(plan, contract, direct_edges),
            contract=contract,
            plan=plan,
            direct_edges=direct_edges,
            forbidden_module_names=forbidden_module_names,
            derivation_notes={
                "contract": "Registered refiner adapters; no model-authored program"
            },
        )
