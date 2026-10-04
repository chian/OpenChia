"""An exact prepared refinement campaign as a shared experiment subject."""

from dataclasses import replace

from agent.duet_contracts import canonical_json, content_id, digest_record
from iterative_episode_refiner.campaign_store import CampaignView, CampaignStore
from iterative_episode_refiner.evidence import EvidenceReader
from iterative_episode_refiner.records import RefinementRecord

from ..records.experiments import read_record, read_reference
from .inputs import workflow_template


def refinement_subject(request, *, inputs, artifacts, builds, runs=None):
    if request["scope"]["kind"] != "refinement" and request["mode"] != "numerical":
        return None
    reference = request["campaign_ref"]
    if reference is None:
        raise ValueError("Select the exact prepared refinement campaign.")
    stored = artifacts.get_artifact(reference["artifact_id"])
    if stored is None or stored["kind"] != "refinement.campaign.v1":
        raise ValueError(
            "Refinement scope requires an admitted campaign, not a Target Workflow."
        )
    owner = stored["duet_id"]
    contract = RefinementRecord.from_record(
        read_reference(artifacts, reference, owner)["record"]
    )
    owner_state = artifacts.get_duet(owner)
    if (
        owner_state is None
        or owner_state["authority_head_approval_id"]
        != contract.body["target_approval_ref"]["artifact_id"]
    ):
        raise ValueError(
            "The refinement campaign no longer matches its owner's current target authority."
        )
    reader = EvidenceReader(artifacts, builds, runs)
    reader.validate_contract(contract)
    approval = inputs.build_request.workflow_approval
    manifest = inputs.manifest
    if (
        contract.body["refiner_workflow_approval_ref"]
        != {
            "artifact_id": approval.approval_id.value,
            "content_hash": digest_record(approval.as_record()).value,
        }
        or manifest is None
        or contract.body["refiner_manifest_ref"]
        != {
            "artifact_id": manifest.manifest_id.value,
            "content_hash": digest_record(manifest.as_record()).value,
        }
    ):
        raise ValueError(
            "The experiment build is not the campaign's exact approved refiner."
        )
    receipt = {
        "artifact_id": inputs.receipt.receipt_id.value,
        "content_hash": inputs.receipt.content_hash.value,
    }
    if request["candidate_ref"] != receipt:
        raise ValueError(
            "A refinement-job candidate is its exact admitted refiner build, not the target candidate."
        )
    with artifacts.transaction() as connection:
        view = CampaignView(connection, contract.campaign_id)
        if view.contract.ref != contract.ref:
            raise ValueError(
                "Prepared campaign differs from the experiment's campaign."
            )
        root = [
            entry
            for entry in view.entries("invocation")
            if entry.record.body["parent_assignment_ref"] is None
        ]
        entry_unit = content_id(
            "refinement_unit",
            {"campaign": contract.campaign_id.value, "stage": "entry"},
        ).value
        later = connection.execute(
            "SELECT 1 FROM refinement_operations WHERE campaign_id = ? AND (logical_unit_id != ? OR action NOT IN ('assign', 'install_check')) LIMIT 1",
            (contract.campaign_id.value, entry_unit),
        ).fetchone()
        pristine = (
            len(root) == 1
            and root[0].status == "active"
            and len(view.entries("invocation")) == 1
            and not view.entries("unit")
            and view.head["candidate_id"] == view.head["initial_candidate_id"]
            and later is None
        )
        starting_state = {
            "campaign_ref": reference,
            "candidate_ref": view.candidate.ref.as_record(),
            "sequence": view.head["sequence"],
            "latest_commit_id": view.head["latest_commit_id"],
        }
    claim = read_record(
        artifacts, "refinement_job", campaign_id=contract.campaign_id.value
    )
    if (
        request["mode"] != "numerical"
        and claim is not None
        and claim["record"]["experiment_id"] != _experiment_id(request)
    ):
        raise ValueError(
            "This campaign is already bound to another experiment. Prepare a separate campaign for a changed experiment; continuation is not a fresh Run."
        )
    if request["mode"] != "numerical" and claim is None and not pristine:
        raise ValueError(
            "This campaign already contains refinement work. Select continuation or prepare a new campaign; existing state is not a fresh starting point."
        )
    return {
        "kind": "refinement_job",
        "reference": reference,
        "owner_duet_id": owner,
        "recording_owner_duet_id": inputs.build_request.frozen_workflow.duet_id.value,
        "campaign_id": contract.campaign_id.value,
        "starting_state": None if request["mode"] == "numerical" else starting_state,
        "launch_template": workflow_template(
            inputs.build_request.frozen_workflow,
            request["start"]["input_payload"] or None,
        ),
        "execution_scope": None,
        "limitations": [
            "Executes the complete authorized refiner against one prepared campaign, including normal build jobs.",
            "A fresh experiment cannot restart or overwrite an already worked campaign.",
            "Recorded or checkpoint execution needs coherent campaign restoration; fresh live execution is never substituted.",
        ],
    }


def _experiment_id(request):
    from .contracts import ExperimentSpec

    return ExperimentSpec.from_record(request).experiment_id


def make_session(service, subject, registration, package, *, terminal_recovery=False):
    from iterative_episode_refiner.runtime import RefinementSession

    if service.refinement_evaluations is None:
        raise ValueError(
            "Refinement execution requires the owning host's shared target-evaluation service."
        )
    evaluations = service.refinement_evaluations
    if (
        evaluations.executor is not service.executor
        or evaluations.builder.store is not service.builds
    ):
        raise ValueError(
            "Refinement evaluations must use this exact shared Builder and Run executor."
        )
    from agent.episode_contracts import OpaqueId

    return RefinementSession(
        store=CampaignStore(
            service.artifacts,
            EvidenceReader(service.artifacts, service.builds, service.runs),
        ),
        campaign_id=OpaqueId(subject["campaign_id"]),
        registration=registration,
        source_package_path=package,
        evaluations=evaluations,
        terminal_recovery=terminal_recovery,
    )


def validate_session_intent(artifacts, intent, session):
    if intent["kind"] != "experiment.dispatch.v1":
        raise ValueError(
            "Refinement experiment session requires an exact shared dispatch."
        )
    body = intent["record"]
    if (
        body["spec"]["scope"]["kind"] != "refinement"
        or body["spec"]["campaign_ref"] != session.contract.ref.as_record()
        or body["plan"].get("subject", {}).get("kind") != "refinement_job"
        or intent["duet_id"] != session.duet_id
        or canonical_json(body["registration"])
        != canonical_json(replace(session.registration, resume_from=None).as_record())
    ):
        raise ValueError("Refinement host session differs from the frozen experiment.")
