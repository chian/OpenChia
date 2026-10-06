"""Bind an experiment's candidate identity to its actual admitted source bytes."""

from dataclasses import replace

from agent.duet_contracts import canonical_json

from ..records.experiments import read_reference


def resolve_candidate(request, inputs, *, artifacts, builds, subject=None):
    receipt = {
        "artifact_id": inputs.receipt.receipt_id.value,
        "content_hash": inputs.receipt.content_hash.value,
    }
    actual = {
        module.module_name.replace(".", "/") + ".py": module.source_hash.value
        for module in inputs.emitted_modules
    }
    reference = request["candidate_ref"]
    if reference == receipt:
        # The existing BuildReceipt already names an immutable candidate. Do
        # not manufacture a second candidate registry or trust a prose label.
        return {
            "kind": "admitted_build",
            "candidate_ref": receipt,
            "source_files": actual,
            "workflow_ref": {
                "artifact_id": inputs.build_request.frozen_workflow.artifact_id.value,
                "content_hash": inputs.build_request.frozen_workflow.workflow_hash.value,
            },
        }
    campaign_source = subject is not None and subject["kind"] == "campaign_evaluation"
    duet_id = subject["owner_duet_id"] if campaign_source else inputs.build_request.frozen_workflow.duet_id.value
    row = read_reference(artifacts, reference, duet_id)
    from iterative_episode_refiner.records import RefinementRecord

    if row["kind"] != "refinement.candidate.v1" or request["campaign_ref"] is None:
        raise ValueError(
            "candidate_ref must be the exact BuildReceipt reference or a typed refinement candidate with its campaign; an arbitrary candidate label is not a source identity"
        )
    candidate = RefinementRecord.from_record(row["record"])
    contract = RefinementRecord.from_record(
        read_reference(artifacts, request["campaign_ref"], duet_id)["record"]
    )
    if contract.kind != "campaign" or candidate.campaign_id != contract.campaign_id:
        raise ValueError("candidate and campaign identities differ")
    from iterative_episode_refiner.candidate_source import project_candidate_sources
    from iterative_episode_refiner.evidence import EvidenceReader

    reader = EvidenceReader(artifacts, builds, None)
    # Generated modules are only parsed/admitted here, never imported or run.
    projection = project_candidate_sources(
        reader, contract, candidate, subject["binding"] if campaign_source else None
    )
    from iterative_episode_refiner.candidate_environment import validate_manifest

    validate_manifest(reader, contract, candidate, projection, inputs)
    plan = replace(
        projection.plan,
        build_request_id=inputs.build_request.build_request_id,
        build_attempt_id=inputs.build_attempt.build_attempt_id,
    )
    if (
        projection.deficits
        or actual != projection.completed_files
        or canonical_json(plan.as_record()) != canonical_json(inputs.plan.as_record())
        or canonical_json(projection.baseline.build_request.frozen_workflow.as_record())
        != canonical_json(inputs.build_request.frozen_workflow.as_record())
    ):
        raise ValueError(
            "admitted build differs from the candidate's exact projected source or materialization plan"
        )
    return {
        "kind": "refinement_candidate",
        "candidate_ref": reference,
        "campaign_ref": request["campaign_ref"],
        "source_files": actual,
        "workflow_ref": projection.scope.workflow_ref,
    }
