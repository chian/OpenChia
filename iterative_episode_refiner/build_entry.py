"""Prepare a normal build for the existing nested refiner and shared harness.

Static checks come from the registered materialization checks. Missing behavioral instruments
remain explicit requirements for the parent; this entry never invents passing
answers or treats static admission as complete behavioral acceptance.
"""

from agent.duet_contracts import content_id
from episode_runtime.testing_harness.contracts import ExperimentSpec
from episode_runtime.testing_harness.criteria import register_criterion
from episode_runtime.records.experiments import put_data
from function_library.refinement_checks import EXACT_VALUE
from function_library.refinement_control import BOUNDED_RAREFACTION, SEMANTIC_YIELD
from function_library.materialization_progress import REQUIREMENT_SATISFACTION

from .preparation import prepare_refinement, start_refinement
from .measure_preparation import build_measure_policy


def selection(function):
    return {
        key: value
        for key, value in function.bind("entry").as_record().items()
        if key != "name"
    }


def prepare_build(host, campaigns, inputs, handoff, registration, runtime, model_slot_catalog):
    owner = host.identity.duet_id.value

    def data(kind, value):
        return campaigns.put_data(owner, kind, value)

    authority = data(
        "build_refinement_authority",
        {
            "target_approval_id": inputs.build_request.authority_approval.approval_id.value,
            "refiner_approval_id": registration.workflow_approval_id.value,
            "scope": "Construct and refine the Target Workflow's Materialization Spec and source, and validate its approved requirements.",
            "acceptance_may_be_weakened": False,
            "capabilities_may_be_expanded": False,
        },
    )
    environment = data("environment", runtime.as_record())
    local = data("local_measure", {
        "purpose": "local", "function": selection(REQUIREMENT_SATISFACTION),
        "membership": "The exact initial check_refs in this campaign's frozen policy.",
    })
    acceptance = data("acceptance_measure", {
        "purposes": ["acceptance", "composition"], "function": selection(REQUIREMENT_SATISFACTION),
        "membership": "The exact initial check_refs in this campaign's frozen policy.",
    })
    from episode_builder.inspection import project_materialized_specification

    target = inputs.build_request
    specification = project_materialized_specification(inputs)
    workflow = data("target_workflow", target.frozen_workflow.as_record())
    harness = data(
        "target_test",
        {
            "execution_kind": "target_workflow",
            "target_workflow_ref": workflow.as_record(),
        },
    )
    refiner = host.build_store.inspection_inputs_for_receipt(
        registration.build_receipt_id
    )
    policy = data(
        "campaign_policy",
        {
            "check_refs": [],
            "model_slot_catalog": model_slot_catalog,
            "research_profile_home": str(host.root.parent),
            # Planning can fail before a node enters the typed plan. Its approved
            # materialization target still exists and must remain repairable.
            "materialization_edit_targets": sorted(
                part.stable_target
                for episode in specification.episodes
                for part in episode.parts
                if part.name == "node_plan"
            ),
            "measure_admission": build_measure_policy(data),
            "numeric_control": refiner.build_request.frozen_workflow.workflow.episodes[
                0
            ].contract.numeric_control.as_record(),
            "yield_function": selection(SEMANTIC_YIELD),
            "opportunity_function": selection(BOUNDED_RAREFACTION),
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
                "observe_checker",
                "close_unit",
                "admit_plan",
                "apply_change",
                "propose_measure",
                "admit_measure",
                "bind_measure_control",
                "observe_measure_control",
                "admit_lesson",
                "coordinate_conflict",
                "resolve_conflict",
                "record_research_sources",
                "admit_research_findings",
            ],
            "evaluation_bindings": [
                {
                    "measure_ref": measure.as_record(),
                    "purpose": purpose,
                    "harness_ref": harness.as_record(),
                    "capability_ref": authority.as_record(),
                    "input_refs": [],
                }
                for measure, purpose in (
                    (local, "local"),
                    (acceptance, "acceptance"),
                    (acceptance, "composition"),
                )
            ],
        },
    )
    prepared = prepare_refinement(
        store=campaigns,
        inputs=inputs,
        handoff=handoff,
        campaign_id=content_id(
            "refinement_campaign", {"build_request": target.build_request_id.value}
        ),
        refiner_registration=registration,
        policy_ref=policy,
        authority_ref=authority,
        environment_ref=environment,
        local_measure_ref=local,
        acceptance_measure_ref=acceptance,
    )
    start_refinement(campaigns, prepared)
    return prepared


def build_experiment(host, prepared, inputs, binding, runtime):
    owner = inputs.build_request.frozen_workflow.duet_id.value
    receipt = {
        "artifact_id": inputs.receipt.receipt_id.value,
        "content_hash": inputs.receipt.content_hash.value,
    }
    environment = put_data(host.store, owner, "environment", runtime.as_record())
    scope = {
        "kind": "refinement",
        "entry_local_id": inputs.plan.root_local_id,
        "included_local_ids": sorted(node.local_id for node in inputs.plan.nodes),
        "component_definition_id": None,
        "unit_label": None,
        "invocation_path": [],
    }
    grounding = put_data(
        host.store,
        owner,
        "refinement_completion_contract",
        {
            "fact": "Only the host-admitted attained disposition represents discharged requirements.",
            "limitation": "The final verified-build record is additionally required for build success.",
        },
    )
    criterion = register_criterion(
        {
            "schema_version": 1,
            "build_receipt_ref": receipt,
            "environment_ref": environment,
            "requirement_key": "refiner-attainment",
            "description": "The refiner must discharge the original requirements, not merely return.",
            "scope": scope,
            "accepted_modes": ["live_fresh"],
            "input_payload": {},
            "predicate": selection(EXACT_VALUE),
            "observation_path": "/workflow_result/disposition",
            "expected_value": "attained",
            "positive_controls": ["attained"],
            "negative_controls": ["blocked", "yield_exhausted_unresolved", "cancelled"],
            "grounding_refs": [grounding],
            "limitations": ["The job also requires the host's verified-build record."],
        },
        builds=host.build_store,
        artifacts=host.store,
        duet_id=owner,
    )
    return ExperimentSpec.from_record({
        "schema_version": 1,
        "question": "Does the refiner produce an independently accepted build of this Target Workflow?",
        "rationale": "Construct and validate the approved Target Workflow through the nested Refiner Episodes.",
        "candidate_ref": receipt,
        "build_receipt_ref": receipt,
        "environment_ref": environment,
        "scope": scope,
        "boundary": {"parent_context_ref": None, "children": "execute"},
        "start": {"kind": "fresh", "artifact_ref": None, "input_payload": {}},
        "mode": "live_fresh",
        "recording_ref": None,
        "launch_ref": binding.reference,
        "campaign_ref": prepared.contract.ref.as_record(),
        "requirements": [
            {
                "requirement_ref": criterion["requirement_ref"],
                "measure_ref": criterion["measure_ref"],
                "expected": "The refiner attains the original requirements.",
                "falsifying": "Unresolved, interrupted, cancelled or missing acceptance is not a completed build.",
            }
        ],
        "unresolved_questions": [],
    })
