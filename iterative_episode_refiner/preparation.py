"""Prepare the real build's refinement task, without launching or approving it.

Materialization supplies exact requirements and candidate bytes, not a passing
judgment. The caller supplies the host-authorized policy and measures. Missing
predicates stay visible; this module never invents expected answers or a harness.
"""

from dataclasses import dataclass

from agent.duet_contracts import content_id, digest_record
from agent.episode_contracts import OpaqueId
from function_library.models import _thaw_json
from function_library.refinement_contract import CHILDREN

from .records import Ref, RefinementRecord
from .materialization_edits import source_paths
from .state_machine import judgment_lineage


@dataclass(frozen=True)
class PreparedRefinement:
    contract: RefinementRecord
    candidate: RefinementRecord
    root_assignment: RefinementRecord
    root_invocation_id: OpaqueId
    initial_checks: tuple[RefinementRecord, ...]


def _contract_requirements(specification, target_workflow):
    """Keep every contract field and call boundary; no LLM summary is authoritative.

    These are coverage anchors, not claims that one check can establish an entire
    prose field. The parent must ground its interpretation and retain any gaps.
    """
    requirements = []
    contract_targets = {
        episode.local_id: next(
            part.stable_target
            for part in episode.parts
            if part.name == "frozen_contract"
        )
        for episode in specification.episodes
    }
    for node in target_workflow.episodes:
        target = contract_targets[node.local_id]
        values = {
            **node.contract.as_record(),
            "workflow_parent_local_id": node.workflow_parent_local_id,
        }
        for field, value in values.items():
            key = content_id(
                "requirement",
                {
                    "workflow": specification.workflow_hash.value,
                    "local_id": node.local_id,
                    "field": field,
                },
            ).value
            requirements.append({
                "requirement_key": key,
                "evidence_scope": "contract_coverage",
                "local_id": node.local_id,
                "field": field,
                "approved_value": value,
                "source_target": target,
                "mandatory": True,
                "acceptance_predicate_ref": None,
            })
    # Repeatable calls are part of the approved architecture, not a source edit.
    for call in target_workflow.repeatable_calls:
        value = call.as_record()
        requirements.append({
            "evidence_scope": "contract_coverage",
            "requirement_key": content_id(
                "requirement",
                {"workflow": specification.workflow_hash.value, "call": value},
            ).value,
            "local_id": call.caller_local_id,
            "field": "repeatable_call",
            "approved_value": value,
            "source_target": "/workflow_global/parts/frozen_workflow",
            "mandatory": True,
            "acceptance_predicate_ref": None,
        })
    return requirements


def requirement_catalog(specification, workflow, handoff, handoff_ref):
    """Project the Builder's requirements without inventing a second static goal.

    Contract fields remain coverage anchors for parent-designed behavioral
    measures. The Builder's static evidence cannot discharge those anchors.
    """
    targets = {
        part.stable_target: episode.local_id
        for episode in specification.episodes
        for part in episode.parts
    }
    requirements = [
        {
            **row,
            "requirement_key": row["requirement_id"],
            "evidence_scope": "static_materialization",
            "local_id": targets.get(row["target"]),
            "source_target": row["target"],
        }
        for row in handoff["requirements"]
    ]
    requirements.extend(_contract_requirements(specification, workflow))
    return {
        "materialized_specification_id": specification.specification_id.value,
        "workflow_hash": specification.workflow_hash.value,
        "materialization_handoff_ref": handoff_ref.as_record(),
        "coverage": "Builder static requirements plus original contract coverage; behavioral measures remain parent-owned",
        "requirements": requirements,
    }


def prepare_refinement(
    *,
    store,
    workspace,
    baseline,
    campaign_id,
    refiner_registration,
    policy_ref,
    authority_ref,
    environment_ref,
    local_measure_ref,
    acceptance_measure_ref,
    guidance_catalog_ref=None,
):
    """Assemble a host proposal from an exact materialized baseline.

    Nothing enters the operative campaign here. The explicit host entry point
    must admit the prepared contract before calling ``start_refinement``.
    Policy/measures are inputs from that authority, not model-provided defaults.
    """
    specification, receipt, _manifest = workspace.materialized_context(baseline)
    builds = store.evidence.builds
    inputs = builds.inspection_inputs_for_receipt(receipt.receipt_id)
    request = inputs.build_request
    duet_id = baseline.duet_id.value
    handoff = store.evidence.materialization_handoff(receipt, duet_id)
    if handoff["materialized_specification"] != specification.as_record():
        raise ValueError("materialization handoff differs from the selected baseline")
    if (
        request.frozen_workflow.duet_id != baseline.duet_id
        or request.frozen_workflow.workflow_hash != baseline.workflow_hash
        or request.workflow_approval.approval_id != baseline.workflow_approval_id
    ):
        raise ValueError("target build differs from the selected approved baseline")
    approval_row = store.duet_store.get_approval(
        baseline.authority_head_approval_id.value
    )
    if approval_row is None or approval_row.pop("revoked"):
        raise ValueError("target refinement authority is absent or revoked")
    target_approval = Ref(
        baseline.authority_head_approval_id, digest_record(approval_row)
    )
    store.evidence.approval(target_approval, duet_id)
    refiner_approval = Ref(
        refiner_registration.workflow_approval_id,
        refiner_registration.workflow_approval_hash,
    )
    store.evidence.approval(refiner_approval)

    def data(kind, value):
        return store.put_data(duet_id, kind, value)

    policy = _thaw_json(store.evidence.reference(policy_ref, duet_id))
    if "root_assignment_ref" in policy:
        raise ValueError(
            "preparation derives the root assignment from the actual build"
        )
    for reference in (
        authority_ref,
        environment_ref,
        local_measure_ref,
        acceptance_measure_ref,
    ):
        store.evidence.reference(reference, duet_id)
    if guidance_catalog_ref is not None:
        store.evidence.reference(guidance_catalog_ref, duet_id)
    materialization_ref = data("materialization", specification.as_record())
    workflow_ref = data("target_workflow", request.frozen_workflow.as_record())
    receipt_ref = data("target_build_receipt", receipt.as_record())
    handoff_ref = data("materialization_handoff", handoff)
    catalog = requirement_catalog(
        specification, request.frozen_workflow.workflow, handoff, handoff_ref
    )
    catalog_ref = data("requirement_catalog", catalog)
    from .measure_preparation import prepare_grounding

    policy = prepare_grounding(
        data=data,
        read_data=lambda ref: store.evidence.reference(ref, duet_id),
        policy=policy,
        catalog=catalog,
        catalog_ref=catalog_ref,
        workflow=request.frozen_workflow.workflow.as_record(),
        workflow_ref=workflow_ref,
        environment_ref=environment_ref,
    )
    requirement_keys = [row["requirement_key"] for row in catalog["requirements"]]
    checks = tuple(
        RefinementRecord.from_record(
            store.evidence.reference(Ref.from_record(ref), duet_id)
        )
        for ref in policy["check_refs"]
    )
    if any(
        check.kind != "check"
        or check.campaign_id != campaign_id
        or check.body["requirement_key"] not in requirement_keys
        or check.body["environment_ref"] != environment_ref.as_record()
        for check in checks
    ):
        raise ValueError(
            "initial checks must retain this build's requirements and environment"
        )
    if any(check.body["evidence_kind"] == "materialization" for check in checks):
        raise ValueError("initial static checks come from the exact Builder handoff")
    if "observe_materialization" not in policy["allowed_action_classes"]:
        raise ValueError(
            "campaign policy must authorize host materialization observations"
        )
    from .materialization import initial_checks

    checks += initial_checks(
        store,
        duet_id=duet_id,
        campaign_id=campaign_id,
        authority_ref=authority_ref,
        environment_ref=environment_ref,
        handoff=handoff,
        handoff_ref=handoff_ref,
        local_measure_ref=local_measure_ref,
        acceptance_measure_ref=acceptance_measure_ref,
    )
    policy["check_refs"] = [check.ref.as_record() for check in checks]
    planned_paths = source_paths(request.frozen_workflow.workflow, inputs.plan)
    files = dict(handoff["candidate"]["files"])
    if set(files) - set(planned_paths.values()):
        raise ValueError("handoff contains source outside its materialized plan")
    from .instrument_builds import prepare_sources

    instrument_builds, instrument_files, instrument_paths = prepare_sources(
        store, duet_id, policy, request.frozen_workflow
    )
    if set(files).intersection(instrument_files):
        raise ValueError("instrument namespace overlaps primary source")
    files.update(instrument_files)
    instrument_builds_ref = (
        data("instrument_builds", {"builds": instrument_builds})
        if instrument_builds
        else None
    )
    # Missing plans/modules retain their host-derived paths from the approved
    # workflow. They are editable candidates, not fabricated plans or source.
    candidate = RefinementRecord(
        "candidate",
        campaign_id,
        {
            "parent_candidate_ref": None,
            "target_approval_ref": target_approval.as_record(),
            "materialization_ref": materialization_ref.as_record(),
            "files": files,
            "implementation_directive_refs": [],
            "change_set_ref": None,
            "source_admission_ref": None,
        },
        authority_ref,
    )
    root_invocation = content_id(
        "refinement_invocation", {"campaign": campaign_id.value, "role": "root"}
    )
    goal_ref = data(
        "assigned_goal",
        {
            "goal": "Finalize this materialized build against all of its original approved requirements.",
            "baseline": baseline.as_record(),
            "requirement_catalog_ref": catalog_ref.as_record(),
            "materialization_handoff_ref": handoff_ref.as_record(),
            "initial_findings": handoff["diagnostics"],
        },
    )
    partition_ref = data(
        "scope_partition",
        {
            "requirement_catalog_ref": catalog_ref.as_record(),
            "slices": [
                {"slice_key": key, "requirement_keys": [key]}
                for key in requirement_keys
            ],
            "coverage": "all original requirement keys; subdivisions need parent admission",
        },
    )
    from function_library.refinement_contract import root_return_contract
    from .report_contract import requirement_address

    projection_ref = data("return_projection", root_return_contract(
        requirement_address(row) for row in catalog["requirements"]
    ))
    control_ref = data("campaign_policy", policy)
    body = {
        "parent_assignment_ref": None,
        "owning_parts_invocation_id": root_invocation.value,
        "role": "parts",
        "scope_requirement_keys": requirement_keys,
        "contribution_requirement_keys": requirement_keys,
        "scope_partition_ref": partition_ref.as_record(),
        "owned_slice_keys": requirement_keys,
        "baseline_candidate_ref": candidate.ref.as_record(),
        "goal_record_ref": goal_ref.as_record(),
        "authority_ref": authority_ref.as_record(),
        "input_refs": [
            catalog_ref.as_record(),
            materialization_ref.as_record(),
            handoff_ref.as_record(),
        ],
        "preservation_requirement_keys": requirement_keys,
        "dependency_refs": [],
        "local_measure_ref": local_measure_ref.as_record(),
        "acceptance_measure_ref": acceptance_measure_ref.as_record(),
        "progress_manifest_ref": catalog_ref.as_record(),
        "allowed_action_classes": policy["allowed_action_classes"],
        "allowed_child_bindings": list(CHILDREN["parts"]),
        "instruction_refs": [],
        "history_query_ref": catalog_ref.as_record(),
        "return_projection_ref": projection_ref.as_record(),
        "control_bundle_ref": control_ref.as_record(),
        "supersedes_assignment_refs": [],
        "writable_paths": sorted([*planned_paths.values(), *instrument_paths]),
        "protected_paths": sorted(
            set(specification.expected_source_package_files)
            - set(planned_paths.values())
        ),
        "judgment_lineage": "",  # derived before record construction
    }
    body["judgment_lineage"] = judgment_lineage(body)
    assignment = RefinementRecord("assignment", campaign_id, body, authority_ref)
    policy["root_assignment_ref"] = assignment.ref.as_record()
    bound_policy_ref = data("campaign_policy", policy)
    contract = RefinementRecord(
        "campaign",
        campaign_id,
        {
            "duet_id": duet_id,
            "target_approval_ref": target_approval.as_record(),
            "target_workflow_ref": workflow_ref.as_record(),
            "initial_build_receipt_ref": receipt_ref.as_record(),
            "initial_materialization_ref": materialization_ref.as_record(),
            "refiner_workflow_approval_ref": refiner_approval.as_record(),
            "refiner_manifest_ref": Ref(
                refiner_registration.manifest_id, refiner_registration.manifest_hash
            ).as_record(),
            "requirement_catalog_ref": catalog_ref.as_record(),
            "authority_ref": authority_ref.as_record(),
            "policy_bundle_ref": bound_policy_ref.as_record(),
            "environment_ref": environment_ref.as_record(),
            "guidance_catalog_ref": None
            if guidance_catalog_ref is None
            else guidance_catalog_ref.as_record(),
            "final_projection_ref": projection_ref.as_record(),
            **(
                {"instrument_builds_ref": instrument_builds_ref.as_record()}
                if instrument_builds_ref
                else {}
            ),
        },
        authority_ref,
    )
    return PreparedRefinement(contract, candidate, assignment, root_invocation, checks)


def start_refinement(store, prepared: PreparedRefinement):
    """Install the caller-admitted preparation through the shared state boundary."""
    store.start(prepared.contract, prepared.candidate)
    invocation = prepared.root_invocation_id
    unit = content_id(
        "refinement_unit",
        {"campaign": prepared.contract.campaign_id.value, "stage": "entry"},
    )
    attempt = RefinementRecord(
        "attempt",
        prepared.contract.campaign_id,
        {
            "operation_id": content_id(
                "refinement_operation",
                {"assignment": prepared.root_assignment.artifact_id.value},
            ).value,
            "invocation_id": invocation.value,
            "logical_unit_id": unit.value,
            "action": "assign",
            "payload": {
                "assignment": prepared.root_assignment.as_record(),
                "invocation_id": invocation.value,
            },
        },
        prepared.contract.producer_ref,
        invocation_id=invocation,
        logical_unit_id=unit,
    )
    store.commit_attempt(attempt)
    for check in prepared.initial_checks:
        installation = RefinementRecord(
            "attempt",
            prepared.contract.campaign_id,
            {
                "operation_id": content_id(
                    "refinement_operation", {"initial_check": check.artifact_id.value}
                ).value,
                "invocation_id": invocation.value,
                "logical_unit_id": unit.value,
                "action": "install_check",
                "payload": {"check": check.as_record()},
            },
            prepared.contract.producer_ref,
            invocation_id=invocation,
            logical_unit_id=unit,
        )
        store.commit_attempt(installation)
