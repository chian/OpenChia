"""Resolve a campaign's declared instrument or reference through shared execution.

The campaign revision supplies the candidate identity; its admitted check binding
selects the executable namespace. Neither grants general access to another Duet.
"""

from agent.duet_contracts import canonical_json
from function_library.models import _thaw_json
from iterative_episode_refiner.campaign_store import CampaignView
from iterative_episode_refiner.evaluation_inputs import native_template
from iterative_episode_refiner.records import Ref, RefinementRecord

from ..records.experiments import read_record, read_reference
from .campaign_criteria import admitted_check, check_bindings


def campaign_subject(request, *, inputs, artifacts, builds, runs=None):
    reference = request["requirements"][0]["requirement_ref"]
    row = artifacts.get_artifact(reference["artifact_id"])
    if row is None or row["kind"] != "refinement.check.v1":
        return None
    owner = row["duet_id"]
    if request["campaign_ref"] is None:
        raise ValueError("a refinement check requires its exact campaign")
    contract = RefinementRecord.from_record(
        read_reference(artifacts, request["campaign_ref"], owner)["record"]
    )
    with artifacts.transaction() as connection:
        view = CampaignView(connection, contract.campaign_id)
        if view.contract.ref != contract.ref or view.head["duet_id"] != owner:
            raise ValueError("experiment campaign is not the admitted contract")
        first = admitted_check(view, request["requirements"][0])
        choices = check_bindings(view, first, measure_ref=request["requirements"][0]["measure_ref"])
        if len(choices) != 1:
            return None  # The ordinary criterion preview reports this missing binding.
        binding = choices[0]
        instrument = view.data(Ref.from_record(binding["harness_ref"]))
        kind = instrument.get("execution_kind")
        if kind == "target_workflow":
            return None
        if kind not in {"instrument_build", "reference_workflow"}:
            raise ValueError("campaign check has no declared executable source")
        for requirement in request["requirements"]:
            check = admitted_check(view, requirement)
            if check.body["evidence_kind"] != "execution" or canonical_json(
                check_bindings(view, check, measure_ref=requirement["measure_ref"])
            ) != canonical_json([binding]):
                raise ValueError("one experiment must use one declared campaign source binding")
        candidate = view.read(Ref.from_record(request["candidate_ref"]), "candidate")
        if candidate.campaign_id != contract.campaign_id:
            raise ValueError("candidate belongs to another campaign")
        template = native_template(view, binding)
    state = artifacts.get_duet(owner)
    if state is None or state["authority_head_approval_id"] != contract.body["target_approval_ref"]["artifact_id"]:
        raise ValueError("campaign no longer has its original target authority")
    source_owner = inputs.build_request.frozen_workflow.duet_id.value
    subject = {
        "kind": "campaign_evaluation",
        "source_kind": kind,
        "reference": request["campaign_ref"],
        "owner_duet_id": owner,
        "recording_owner_duet_id": source_owner,
        "binding": _thaw_json(binding),
        "launch_template": template,
    }
    from .candidates import resolve_candidate

    # Re-derived at dispatch and execution, not trusted from the preview.
    resolve_candidate(request, inputs, artifacts=artifacts, builds=builds, subject=subject)
    validate_campaign_reuse(
        request, artifacts=artifacts, owner=owner, source_owner=source_owner,
        allowed=[item["requirement_ref"] for item in request["requirements"]],
    )
    return subject


def validate_campaign_reuse(request, *, artifacts, owner, source_owner, allowed):
    references = [request["recording_ref"], request["start"]["artifact_ref"]]
    boundary = request["boundary"]["parent_context_ref"]
    if boundary is not None and not (
        request["mode"] == "numerical" and boundary == request["recording_ref"]
    ):
        row = read_reference(artifacts, boundary, source_owner)
        if row["kind"] not in {"experiment.boundary.v1", "experiment.unit_boundary.v1"}:
            raise ValueError("experiment boundary must be a shared Run projection")
        record = row["record"].get("invocation", row["record"])
        references.append(record["recording_ref"])
    for reference in references:
        if reference is None:
            continue
        row = read_reference(artifacts, reference, source_owner)
        if row["kind"] != "experiment.recording.v1":
            raise ValueError("saved experiment inputs must name a shared recording")
        execution = read_record(artifacts, "execution", run_id=row["record"]["registration_ref"]["run_id"])
        if execution is None:
            raise ValueError("saved recording has no shared execution record")
        dispatch = read_reference(artifacts, execution["record"]["intent_ref"], owner)
        if dispatch["kind"] != "experiment.dispatch.v1":
            raise ValueError("recording is not assigned refinement experiment evidence")
        source = dispatch["record"]["spec"]
        if (
            source["campaign_ref"] != request["campaign_ref"]
            or source["candidate_ref"] != request["candidate_ref"]
            or any(item["requirement_ref"] not in allowed for item in source["requirements"])
        ):
            raise ValueError("recording belongs to another candidate or assigned checks")
