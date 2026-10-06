"""Approved refiner materialization for shared-harness integration checks.

Builder model replies are supplied; the planner, source admission and registered
role implementations are real. Execution uses the existing in-process linked
executor fixture, which does not establish native confinement.
"""

import json
from contextlib import asynccontextmanager
from episode_builder.service import EpisodeBuilder
from episode_library.refinement import DESIGNS
from function_library.episode_calls import BUILD_REPEATABLE_CHILD
from function_library.refinement import PREPARE_CHILD, RECEIVE_CHILD
from llm_call_library.transport import ModelTransportResponse, model_transport_scope
from llm_call_library import CallOptions
from iterative_episode_refiner.design import refinement_workflow_spec
from tests.episode_runtime.conftest import oid
from tests.episode_runtime.test_reasoning_workflow import _approved_request, _binding


def refiner_plan(prompt):
    design = next(
        item
        for item in DESIGNS
        if item.qualified_name == f"refinement.{prompt['node']['local_id']}"
    )
    bindings = list(prompt["architecture_owned_numeric_bindings"])
    slots = []
    for child in prompt["direct_children"]:
        name = child["interface"].removeprefix("refinement.")
        for role, function in (
            ("build_child", BUILD_REPEATABLE_CHILD),
            ("prepare_request", PREPARE_CHILD),
            ("receive_result", RECEIVE_CHILD),
        ):
            bindings.append(
                _binding(
                    f"edge.{name}.{role}",
                    function,
                    {"payload_contract": child["result_payload_contract"]}
                    if role == "receive_result"
                    else {},
                )
            )
        slots.append({
            "slot_name": name,
            "child_local_id": child["local_id"],
            "child_interface": child["interface"],
            "request_payload_contract": child["request_payload_contract"],
            "result_payload_contract": child["result_payload_contract"],
            "build_child": "Use the declared refiner child",
            "prepare_request": "Use the parent's admitted assignment",
            "receive_result": "Admit the typed host report",
            "basis": "Approved refinement reference",
        })
    return {
        "interface": design.binding.interface,
        "result_channel_names": ["report"],
        "request_payload_contract": design.binding.admit_request.as_record()[
            "arguments"
        ]["payload_contract"],
        "result_payload_contract": design.binding.build_result.as_record()["arguments"][
            "payload_contract"
        ],
        "selected_function_bindings": bindings,
        "generated_component_specs": [],
        "prompt_specs": [],
        "goal_state_spec": {"owner": "host refinement campaign"},
        "child_slots": slots,
        "derivation_basis": {"goal": "Approved fixed refiner roles and call graph"},
        "unresolved": [],
    }


def refiner_module(prompt):
    plan, contract = prompt["admitted_node_plan"], prompt["frozen_episode_contract"]
    bindings = {item["role"]: item for item in plan["selected_function_bindings"]}

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
        f"EpisodeChildSlot(name={edge['slot_name']!r}, accepted_interfaces=({edge['child_interface']!r},), "
        f"build_child={selected('edge.' + edge['slot_name'] + '.build_child')}, "
        f"prepare_request={selected('edge.' + edge['slot_name'] + '.prepare_request')}, "
        f"receive_result={selected('edge.' + edge['slot_name'] + '.receive_result')})"
        for edge in prompt.get("direct_edges", [])
    )
    root_builders = (
        ""
        if plan["parent_local_id"] is not None
        else """
def build_goal_state(request, collaborators):
    return refiner.build_goal_state(request, collaborators)
def scope_goal_state(goal_state, goal):
    return MappingProxyType({"goal": goal.objective})
"""
    )
    source = f"""
from types import MappingProxyType
from episode_library.models import EpisodeLibraryDesign
from function_library import refinement as refiner
from function_library.episode_calls import BUILD_REPEATABLE_CHILD
from method_loop import EpisodeBindingDeclaration, EpisodeChildSlot, EpisodeControllerBinding, EpisodeFunctionBinding, EpisodeTopologyRole
from handoff_library import HandoffPayloadContract, ADMIT_DUET_LAUNCH_REQUEST, ADMIT_PARENT_REQUEST
from numeric_control_library import MARGINAL_DOMINATED_HYPERVOLUME, PAIRED_INCIDENCE, PREDICTED_CREDIT_UPPER_BOUND
REQUEST_PAYLOAD_CONTRACT = HandoffPayloadContract.from_record({plan["request_payload_contract"]!r})
RESULT_PAYLOAD_CONTRACT = HandoffPayloadContract.from_record({plan["result_payload_contract"]!r})
PROMPTS = ()
EXECUTION_CAPABILITY_NAMES = {tuple(contract["execution_capability_names"])!r}
RESULT_CHANNEL_NAMES = {tuple(plan["result_channel_names"])!r}
RESULT_CHANNEL_IDS = {tuple(plan["result_channel_ids"])!r}
BINDING = EpisodeBindingDeclaration(
    grain_name={plan["grain_name"]!r}, interface={plan["interface"]!r}, topology_role=EpisodeTopologyRole.{plan["topology_role"].upper()},
    goal={contract["goal"]!r}, unit={contract["unit"]!r}, result={contract["result"]!r},
    progress={contract["progress"]!r}, stopping={contract["stopping"]!r},
    admit_request={selected("admit_request")}, open_source={selected("open_source")},
    controller=EpisodeControllerBinding(schema={selected("controller.schema")}, composer={selected("controller.composer")},
        credit={selected("controller.credit")}, rarefaction={selected("controller.rarefaction")}, continuation={selected("controller.continuation")}),
    build_result={selected("build_result")}, components=({components},), child_slots=({slots}{"," if slots else ""}))
DESIGN = EpisodeLibraryDesign(qualified_name={plan["interface"]!r}, title="Admitted refinement role", binding=BINDING,
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
    return {
        "module_source": source,
        "derivation_notes": {
            "contract": "Fixed library role, approved call topology and host campaign"
        },
    }


async def build_refiner(tmp_path, builds):
    request = _approved_request(
        tmp_path, workflow=refinement_workflow_spec(), duet_id=oid("refiner_duet")
    )

    async def model(request):
        prompt = json.loads(request.messages[-1]["content"])
        response = refiner_plan(prompt) if "node" in prompt else refiner_module(prompt)
        return ModelTransportResponse(text=json.dumps(response), route={})

    with model_transport_scope(model):
        receipt = await EpisodeBuilder(
            store=builds,
            planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"refinement": {}},
        ).build(request)
    assert receipt.materialized, [item.as_record() for item in receipt.deficits]
    return request, receipt


async def build_campaign_source(tmp_path, builds):
    """A distinct approved source, executed by the stock reasoning loop."""
    from agent.episode_contracts import EpisodeCreationSpec
    from tests.episode_runtime.conftest import numerical_control
    from tests.episode_runtime.test_epistemic_learning import contract
    from tests.episode_runtime.test_reasoning_workflow import (
        _module_response,
        _plan_response,
    )

    request = _approved_request(
        tmp_path,
        duet_id=oid("campaign_source_duet"),
        spec=EpisodeCreationSpec(
            goal="Observe the independently recorded empty search without claiming progress.",
            progress="Only admitted durable transitions earn credit.",
            stopping="The registered numerical continuation decides when to return.",
            numeric_control=numerical_control(0.9),
            epistemic=contract(),
        ),
    )

    async def model(call):
        prompt = json.loads(call.messages[-1]["content"])
        response = _plan_response(prompt) if "node" in prompt else _module_response(prompt)
        return ModelTransportResponse(text=json.dumps(response), route={})

    with model_transport_scope(model):
        receipt = await EpisodeBuilder(
            store=builds,
            planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"selector": {}, "executor": {}},
        ).build(request)
    assert receipt.materialized, [item.as_record() for item in receipt.deficits]
    return request, receipt


async def build_checker(tmp_path, builds):
    from function_library.refinement import REPORT_CHILD
    from agent.episode_contracts import (
        EpisodeCreationSpec,
        EpisodeDesignSpec,
        EpisodeWorkflowSpec,
    )
    from handoff_library import (
        ADMIT_PARENT_REQUEST,
        ADMIT_CHILD_RESULT,
        HandoffPayloadContract,
    )
    from numeric_control_library import COMPOSE_INCIDENCE_CONTROLLER
    from tests.episode_runtime.conftest import numerical_control
    from function_library.scheduling_benchmark import optimal_schedule
    from tests.episode_runtime.test_reasoning_workflow import (
        _plan_response,
        _module_response,
    )

    contract = EpisodeCreationSpec(
        goal="Check one supplied minimum against the independently enumerated optimum.",
        progress="One exact supplied-answer judgment recorded.",
        stopping="Registered continuation over the finite supplied-answer observations.",
        numeric_control=numerical_control(0.9),
    )
    workflow = EpisodeWorkflowSpec((
        EpisodeDesignSpec("launch", None, contract),
        EpisodeDesignSpec("check", "launch", contract),
    ))
    request = _approved_request(
        tmp_path, duet_id=oid("checker_duet"), workflow=workflow
    )
    payload = HandoffPayloadContract(
        measurement_names=("minimum",), required_measurement_names=("minimum",)
    ).as_record()
    result_payload = HandoffPayloadContract(
        flag_names=("checker_pass",), required_flag_names=("checker_pass",)
    ).as_record()
    optimum, _ = optimal_schedule()
    checker_source = f"""
from method_loop import Leaf
from handoff_library import ChildResult
from numeric_control_library.credit_assignment import CreditObservation
from numeric_control_library.controller import compose_controller
from function_library.reasoning import reasoning_credit_schema

def checker_controller():
    return compose_controller(
        schema=reasoning_credit_schema(), epoch="known-answer-check",
        credit_function=MARGINAL_DOMINATED_HYPERVOLUME,
        rarefaction_function=PAIRED_INCIDENCE,
        continuation_function=PREDICTED_CREDIT_UPPER_BOUND,
        credit_parameters=BINDING.controller.credit.arguments,
        rarefaction_parameters=BINDING.controller.rarefaction.arguments,
        continuation_parameters=BINDING.controller.continuation.arguments,
    )

class KnownAnswerSource:
    def __init__(self, request):
        self.request = request
        self.judgment = None
    def next(self, view):
        if self.judgment is not None:
            return None
        return Leaf(unit=self.request.message.measurements["minimum"],
                    extract=lambda value: value == {optimum!r},
                    result=self.record, label="check-known-answer")
    def record(self, value, judgment):
        self.judgment = judgment
        return CreditObservation.observed({{reasoning_credit_schema().columns[0]: ({oid("known_answer_observation").value!r},)}})
    def build_result(self, record):
        if self.judgment is None:
            raise ValueError("No answer was checked")
        return ChildResult(request_id=self.request.message.request_id,
                           child_episode_id=record.episode_id,
                           child_interface=BINDING.interface,
                           flags={{"checker_pass": self.judgment}})

def build_checker_episode(grain, key, request):
    source = KnownAnswerSource(request)
    return Episode(grain=grain, key=key, request=request, source=source, build_result=source.build_result)
"""

    async def model(request):
        prompt = json.loads(request.messages[-1]["content"])
        if "node" in prompt:
            response = _plan_response(prompt)
            child = prompt["node"]["local_id"] == "check"
            response["interface"] = "test.checker." + prompt["node"]["local_id"]
            if child:
                response["request_payload_contract"] = payload
                response["result_payload_contract"] = result_payload
                response["selected_function_bindings"][0] = _binding(
                    "admit_request", ADMIT_PARENT_REQUEST, {"payload_contract": payload}
                )
                response["selected_function_bindings"][5]["arguments"] = {
                    "payload_contract": result_payload
                }
            response["selected_function_bindings"][3] = _binding(
                "controller.composer", COMPOSE_INCIDENCE_CONTROLLER
            )
            for edge in prompt["direct_children"]:
                slot = edge["local_id"]
                response["selected_function_bindings"].append(
                    _binding(f"component.report_{slot}", REPORT_CHILD)
                )
                for role, function in (
                    ("build_child", BUILD_REPEATABLE_CHILD),
                    ("prepare_request", ADMIT_PARENT_REQUEST),
                    ("receive_result", ADMIT_CHILD_RESULT),
                ):
                    response["selected_function_bindings"].append(
                        _binding(
                            f"edge.{slot}.{role}",
                            function,
                            {"payload_contract": edge["result_payload_contract"]}
                            if role == "receive_result"
                            else {},
                        )
                    )
                response["child_slots"].append({
                    "slot_name": slot,
                    "child_local_id": slot,
                    "child_interface": edge["interface"],
                    "request_payload_contract": edge["request_payload_contract"],
                    "result_payload_contract": edge["result_payload_contract"],
                    "build_child": "Use the declared checking child",
                    "prepare_request": "Pass the declared typed input",
                    "receive_result": "Retain typed checker flag",
                    "basis": "Approved checker test entry",
                })
        else:
            response = _module_response(
                prompt,
                extra_source=checker_source,
                controller_expression="checker_controller()",
                episode_expression="build_checker_episode(grain, key, request)",
            )
            response["module_source"] = (
                "from function_library.refinement import refinement_function_library\n"
                + response["module_source"].replace(
                    "*epistemic_function_library.functions()",
                    "*refinement_function_library.functions(), *epistemic_function_library.functions()",
                )
            )
        return ModelTransportResponse(text=json.dumps(response), route={})

    with model_transport_scope(model):
        receipt = await EpisodeBuilder(
            store=builds,
            planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"selector": {}, "executor": {}},
        ).build(request)
    assert receipt.materialized, [row.as_record() for row in receipt.deficits]
    return request, receipt


@asynccontextmanager
async def prepared_refiner(
    tmp_path,
    runtime_identity,
    *,
    runtime_check=None,
    runtime_checks=(),
    allow_source_edits=False,
    executor_type=None,
    independent_checker=False,
    independent_measure=False,
    campaign_source_kind=None,
    target_workflow=None,
    registered_grounding=False,
    grouped_measures=False,
    target_builder=None,
):
    from agent.duet_contracts import DuetIdentity, content_id, digest_record
    from agent.duet_service import DuetService
    from agent.duet_store import DuetStore
    from episode_runtime.testing_harness.execution import register_build
    from episode_runtime.testing_harness.inputs import workflow_template
    from episode_runtime.contracts import RuntimePolicy
    from function_library.refinement_control import BOUNDED_RAREFACTION, SEMANTIC_YIELD
    from iterative_episode_refiner.campaign_store import CampaignStore
    from iterative_episode_refiner.contracts import RefinementBaseline
    from iterative_episode_refiner.evaluation import RefinementEvaluations
    from iterative_episode_refiner.evidence import EvidenceReader
    from iterative_episode_refiner.preparation import (
        prepare_refinement,
        start_refinement,
    )
    from iterative_episode_refiner.runtime import RefinementSession
    from iterative_episode_refiner.measure_preparation import build_measure_policy
    from iterative_episode_refiner.measure_groups import group_definition
    from iterative_episode_refiner.records import RefinementRecord
    from iterative_episode_refiner.service import IterativeEpisodeRefiner
    from iterative_episode_refiner.workspace import RefinementWorkspace
    from tests.episode_builder.test_repeatable_call_materialization import (
        build,
        selected,
    )
    from tests.episode_runtime.testing_harness.test_scoped_execution import LinkedExecutor

    target, builds, receipt = await (target_builder or build)(tmp_path, (), workflow=target_workflow)
    refiner, refiner_receipt = await build_refiner(tmp_path, builds)
    checker = (
        await build_checker(tmp_path, builds)
        if independent_checker or independent_measure
        else None
    )
    if campaign_source_kind not in {None, "instrument_build", "reference_workflow"}:
        raise ValueError("unknown campaign source fixture")
    campaign_source = (
        await build_campaign_source(tmp_path, builds)
        if campaign_source_kind is not None else None
    )
    inputs = builds.inspection_inputs_for_receipt(refiner_receipt.receipt_id)
    executor = (executor_type or LinkedExecutor)(
        tmp_path / "execution", runtime_identity
    )
    registration, package = register_build(
        executor,
        builds,
        inputs,
        workflow_template(refiner.frozen_workflow, None),
        RuntimePolicy(),
    )
    with DuetStore(tmp_path / "duet.db") as artifacts:
        owner = target.frozen_workflow.duet_id.value
        identity = DuetIdentity.from_record(artifacts.get_duet(owner)["identity"])
        authority = DuetService(artifacts, allowed_episode_capabilities=())
        refiner_service = IterativeEpisodeRefiner(artifacts, authority)
        specification = builds.project_receipt(receipt.receipt_id)
        artifacts.put_artifact(
            artifact_id=specification.specification_id.value,
            duet_id=owner,
            kind="materialized_specification",
            revision=target.frozen_workflow.revision,
            content_hash=specification.content_hash.value,
            record=specification.as_record(),
        )
        manifest = builds.read_manifest(receipt.manifest_id)
        baseline = refiner_service.record_baseline(
            identity,
            RefinementBaseline(
                duet_id=target.frozen_workflow.duet_id,
                authority_head_approval_id=target.authority_approval.approval_id,
                workflow_approval_id=target.workflow_approval.approval_id,
                frozen_workflow_artifact_id=target.frozen_workflow.artifact_id,
                workflow_hash=target.frozen_workflow.workflow_hash,
                build_request_id=target.build_request_id,
                build_attempt_id=receipt.build_attempt_id,
                build_receipt_id=receipt.receipt_id,
                build_receipt_hash=receipt.content_hash,
                materialized_specification_id=specification.specification_id,
                materialized_specification_hash=specification.content_hash,
                build_manifest_id=manifest.manifest_id,
                build_manifest_hash=digest_record(manifest.as_record()),
            ),
        )
        workspace = RefinementWorkspace(
            identity=identity,
            authority=authority,
            refiner=refiner_service,
            store=artifacts,
            build_store=builds,
            run_store=executor.run_store,
        )
        campaigns = CampaignStore(
            artifacts, EvidenceReader(artifacts, builds, executor.run_store)
        )

        def data(kind, value):
            return campaigns.put_data(owner, kind, value)

        authority_ref = data(
            "test_authority",
            {
                "target_approval": target.authority_approval.as_record(),
                "refiner_approval": refiner.workflow_approval.as_record(),
            },
        )
        local = data("local_measure", group_definition("local") if grouped_measures else {"purpose": "local"})
        acceptance = data("acceptance_measure", group_definition("acceptance", "composition") if grouped_measures else {"purpose": "independent acceptance"})
        workflow_ref = data("target_workflow", target.frozen_workflow.as_record())
        checker_ref = None
        if checker is not None:
            from episode_runtime.testing_harness.inputs import workflow_template

            checker_request, checker_receipt = checker
            checker_ref = data(
                "checker",
                {
                    "workflow_ref": data(
                        "checker_workflow", checker_request.frozen_workflow.as_record()
                    ).as_record(),
                    "build_receipt_ref": data(
                        "checker_build", checker_receipt.as_record()
                    ).as_record(),
                    "authority_approval_ref": {
                        "artifact_id": checker_request.authority_approval.approval_id.value,
                        "content_hash": digest_record(
                            checker_request.authority_approval.as_record()
                        ).value,
                    },
                    "launch_ref": data(
                        "checker_inputs",
                        workflow_template(checker_request.frozen_workflow).as_record(),
                    ).as_record(),
                    "result_inputs": [
                        {
                            "field": "measurements",
                            "key": "minimum",
                            "result_path": "/minimum_completion",
                        }
                    ],
                    "entry_local_id": "check",
                    "entry_context": "declared_goal_initial_state",
                },
            )
        harness = data(
            "target_test",
            {
                "execution_kind": "target_workflow",
                "target_workflow_ref": workflow_ref.as_record(),
                **(
                    {"checker_ref": checker_ref.as_record()}
                    if checker_ref is not None
                    else {}
                ),
            },
        )
        environment = data("environment", {"fixture": "approved_target_and_refiner"})
        measure_policy = {}
        if campaign_source is not None:
            source_request, source_receipt = campaign_source
            source_inputs = builds.inspection_inputs_for_receipt(source_receipt.receipt_id)
            source_root = next(
                node for node in source_inputs.plan.nodes
                if node.local_id == source_inputs.plan.root_local_id
            )
            descriptor = {
                "workflow_ref": data("source_workflow", source_request.frozen_workflow.as_record()).as_record(),
                "build_receipt_ref": data("source_build", source_receipt.as_record()).as_record(),
                "authority_approval_ref": {
                    "artifact_id": source_request.authority_approval.approval_id.value,
                    "content_hash": digest_record(source_request.authority_approval.as_record()).value,
                },
                "launch_ref": data("source_inputs", workflow_template(source_request.frozen_workflow).as_record()).as_record(),
            }
            input_contract = data("source_input_contract", source_root.request_payload_contract)
            if campaign_source_kind == "reference_workflow":
                reference = data("reference_source", {
                    **descriptor,
                    "request_payload_contract_ref": input_contract.as_record(),
                })
                harness = data("source_test", {
                    "execution_kind": campaign_source_kind,
                    "reference_ref": reference.as_record(),
                })
            else:
                checker_source = data("editable_checker", {**descriptor, "result_inputs": []})
                instrument = data("instrument_spec", {
                    "purpose": "local",
                    "requirement_keys": [content_id("requirement", {
                        "workflow": specification.workflow_hash.value,
                        "local_id": target.frozen_workflow.workflow.episodes[0].local_id,
                        "field": "goal",
                    }).value],
                    "checker_ref": checker_source.as_record(),
                    "input_contract_ref": input_contract.as_record(),
                    "output_contract_ref": data("source_output_contract", source_root.result_payload_contract).as_record(),
                    "local_measure_ref": local.as_record(),
                    "acceptance_measure_ref": acceptance.as_record(),
                    "grounding_refs": [data("source_grounding", {"claim": "An empty failed attempt admits no state and earns zero credit."}).as_record()],
                    "positive_control_refs": [data("source_control", {"credit": 0, "expected": "pass"}).as_record()],
                    "negative_control_refs": [data("source_control", {"credit": 1, "expected": "fail"}).as_record()],
                    "limitation_refs": [],
                })
                measure_policy = {
                    "measure_admission": {
                        "adequacy_measure_ref": data("source_adequacy", {"claim": "Original fixed zero-credit criterion"}).as_record(),
                        "grounding_refs": [],
                        "instrument_build_refs": [instrument.as_record()],
                    },
                    "editable_instrument_refs": [instrument.as_record()],
                }
                harness = data("source_test", {
                    "execution_kind": campaign_source_kind,
                    "instrument_build_ref": instrument.as_record(),
                })
        if independent_measure:
            from function_library.refinement_checks import EXACT_VALUE
            from function_library.scheduling_benchmark import optimal_schedule

            optimum, witness = optimal_schedule()
            case = {
                "requirement_key": content_id(
                    "requirement",
                    {
                        "workflow": specification.workflow_hash.value,
                        "local_id": target.frozen_workflow.workflow.episodes[
                            0
                        ].local_id,
                        "field": "goal",
                    },
                ).value,
                "purpose": "local",
                "expected": True,
                "observation_path": "/payload/typed_status/workflow_result/flags/checker_pass",
                "dependency_paths": None,
                "environment_ref": environment.as_record(),
                "oracle_ref": checker_ref.as_record(),
                "input_domain_ref": data(
                    "answer_domain",
                    {
                        "minimum_completion": "integer",
                        "optimum": optimum,
                        "witness": witness,
                    },
                ).as_record(),
                "observation_schema_ref": data(
                    "checker_schema", {"checker_pass": "boolean"}
                ).as_record(),
                "decision_function_ref": data(
                    "predicate", selected(EXACT_VALUE).as_record()
                ).as_record(),
                "independence_policy_ref": data(
                    "independence",
                    {
                        "source": "exhaustive scheduling solver",
                        "candidate_self_verdict": False,
                    },
                ).as_record(),
                "uncertainty_policy_ref": data(
                    "uncertainty",
                    {
                        "claim": "two exact known-answer controls, not all possible inputs"
                    },
                ).as_record(),
                "limitation_refs": [],
                "positive_control_refs": [
                    data(
                        "control",
                        {
                            "typed_status": {"minimum_completion": optimum},
                            "expected_outcome": "pass",
                        },
                    ).as_record()
                ],
                "negative_control_refs": [
                    data(
                        "control",
                        {
                            "typed_status": {"minimum_completion": optimum + 1},
                            "expected_outcome": "fail",
                        },
                    ).as_record()
                ],
                "execution_binding": {
                    "harness_ref": harness.as_record(),
                    "capability_ref": authority_ref.as_record(),
                    "input_refs": [],
                },
                "guard_keys": [],
            }
            measure_policy = {
                "measure_admission": {
                    "adequacy_measure_ref": data(
                        "adequacy",
                        {
                            "criterion": "checker distinguishes all independently grounded controls"
                        },
                    ).as_record(),
                    "grounding_refs": [data("grounded_case", case).as_record()],
                }
            }
        checks = []
        for runtime_check in (
            [runtime_check] if runtime_check is not None else runtime_checks
        ):
            from function_library.refinement_checks import EXACT_VALUE

            predicate = data("predicate", selected(EXACT_VALUE).as_record())
            grounding = data("grounding", runtime_check["grounding"])
            check = RefinementRecord(
                "check",
                oid("campaign"),
                {
                    "requirement_key": content_id(
                        "requirement",
                        {
                            "workflow": specification.workflow_hash.value,
                            "local_id": target.frozen_workflow.workflow.episodes[
                                0
                            ].local_id,
                            "field": runtime_check.get("requirement_field", "goal"),
                        },
                    ).value,
                    "evidence_kind": "execution",
                    "origin_refs": [grounding.as_record()],
                    "measure_ref": (
                        acceptance
                        if runtime_check.get("purpose") in {"acceptance", "composition"}
                        else local
                    ).as_record(),
                    "purpose": runtime_check.get("purpose", "local"),
                    "predicate_ref": predicate.as_record(),
                    "expected": runtime_check["expected"],
                    "dependency_paths": None,
                    "environment_ref": environment.as_record(),
                    "mandatory": True,
                    "guard_keys": [],
                    "grounding_refs": [grounding.as_record()],
                    "observation_path": runtime_check["observation_path"],
                },
                authority_ref,
            )
            with artifacts.transaction() as connection:
                campaigns._put(connection, owner, check)
            checks.append(check.ref.as_record())
        policy_ref = data(
            "policy",
            {
                **measure_policy,
                **({"measure_admission": build_measure_policy(data)} if registered_grounding else {}),
                **({"measure_group_refs": [local.as_record(), acceptance.as_record()]} if grouped_measures else {}),
                **({
                    "investigation_need_refs": [data("source_need", {
                        "need_key": "inspect-independent-source",
                        "role": "support",
                        "requirement_key": check.body["requirement_key"],
                        "measure_ref": local.as_record(),
                        "check_ref": check.ref.as_record(),
                        "decision_ref": data("source_decision", {"question": "Does this source preserve zero credit for empty failure?"}).as_record(),
                        "target_ref": workflow_ref.as_record(),
                        "applicability_ref": environment.as_record(),
                        "limitation_refs": [],
                        "outcomes": {"pass": "applicable", "fail": "inapplicable"},
                    }).as_record()],
                } if campaign_source is not None else {}),
                "check_refs": checks,
                "numeric_control": refiner.frozen_workflow.workflow.episodes[
                    0
                ].contract.numeric_control.as_record(),
                "yield_function": selected(SEMANTIC_YIELD).as_record(),
                "opportunity_function": selected(BOUNDED_RAREFACTION).as_record(),
                "allowed_action_classes": [
                    "assign",
                    "install_check",
                    "enter_child",
                    "return_child",
                    "select_action",
                    "request_evaluation",
                    "record_evaluation_source",
                    "bind_evaluation_run",
                    "observe",
                    "observe_materialization",
                    "close_unit",
                    *(["admit_plan", "apply_change"] if allow_source_edits else []),
                    *(
                        [
                            "propose_measure",
                            "admit_measure",
                            "bind_measure_control",
                            "observe_measure_control",
                        ]
                        if independent_measure or registered_grounding
                        else []
                    ),
                ],
                "evaluation_bindings": [
                    {
                        "measure_ref": measure.as_record(),
                        "purpose": purpose,
                        "harness_ref": harness.as_record(),
                        "capability_ref": authority_ref.as_record(),
                        "input_refs": [],
                    }
                    for measure, purpose in (
                        (local, "local"),
                        (acceptance, "acceptance"),
                        (acceptance, "composition"),
                        *(((local, "support"),) if campaign_source is not None else ()),
                    )
                ],
            },
        )
        prepared = prepare_refinement(
            store=campaigns,
            workspace=workspace,
            baseline=baseline,
            campaign_id=oid("campaign"),
            refiner_registration=registration,
            policy_ref=policy_ref,
            authority_ref=authority_ref,
            environment_ref=environment,
            local_measure_ref=local,
            acceptance_measure_ref=acceptance,
        )
        start_refinement(campaigns, prepared)
        evaluations = RefinementEvaluations(
            builder=EpisodeBuilder(
                store=builds,
                planning_options=CallOptions(model_type="planner"),
                emission_options=CallOptions(model_type="writer"),
                model_slot_catalog={"refinement": {}, "selector": {}, "executor": {}},
            ),
            executor=executor,
        )
        if executor_type is None:
            # The in-process executor supplies results and has no staged OS
            # runtime. State tests disclose that limitation; live fixtures use
            # the real backend's environment description instead.
            evaluations._environment_context = {
                "runtime": {"kind": "inert fixture; no dependency installation"},
                "libraries": {"base": ["fixture runtime"]},
                "package_management": {"mechanism": "unavailable in this fixture"},
                "workspace": {"managed_root": str(executor.run_store.root)},
                "installation_access": {"network": False},
                "runtime_access": {}, "credential_references": [],
            }
        session = RefinementSession(
            store=campaigns,
            campaign_id=prepared.contract.campaign_id,
            registration=registration,
            source_package_path=package,
            evaluations=evaluations,
        )
        yield session
