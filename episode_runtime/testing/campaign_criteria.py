"""Use admitted refinement checks without copying or relaxing their criteria.

An experimental requirement names the exact check record; its measure reference
remains the parent's measure. Reading a check does not install it, grant access
to another assignment, publish a campaign observation, or award parent credit.
"""

from agent.duet_contracts import canonical_json
from agent.duet_store import DuetNotFoundError
from function_library.models import _thaw_json
from function_library.refinement_checks import resolve_predicate
from iterative_episode_refiner.campaign_store import CampaignView
from iterative_episode_refiner.checking import checker_definition
from iterative_episode_refiner.evaluation_inputs import native_template
from iterative_episode_refiner.measures import bindings_for_check
from iterative_episode_refiner.records import Ref, RefinementRecord

from ..records.experiments import read_reference


def admitted_check(view, requirement):
    """Resolve the installed check without replacing its parent-assigned measure."""
    check = view.read(Ref.from_record(requirement["requirement_ref"]), "check")
    try:
        installed = view.entry("check", check.artifact_id.value)
    except DuetNotFoundError as exc:
        raise ValueError("measurement check has not been admitted in this campaign") from exc
    if installed.record.ref != check.ref:
        raise ValueError("measurement check differs from its admitted identity")
    if check.body["measure_ref"] != requirement["measure_ref"]:
        raise ValueError("experiment changes the check's parent-assigned measure")
    catalog = view.data(Ref.from_record(view.contract.body["requirement_catalog_ref"]))
    if check.body["requirement_key"] not in {
        row["requirement_key"] for row in catalog["requirements"]
    }:
        raise ValueError("measurement has no original requirement in this campaign")
    return check


def check_bindings(view, check):
    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    bindings = list(policy["evaluation_bindings"])
    for entry in view.entries("measure"):
        admitted = entry.record.body
        if entry.status != "admitted" or check.ref.as_record() not in admitted["check_refs"]:
            continue
        if admitted["evaluation_binding"] is not None:
            bindings.append(admitted["evaluation_binding"])
        bindings.extend(admitted.get("evaluation_bindings", ()))
    return bindings_for_check(bindings, check)


def resolve_campaign_criterion(
    requirement,
    request,
    *,
    artifacts,
    duet_id,
    workflow,
    launch_inputs,
    builds=None,
    runs=None,
):
    check_row = read_reference(artifacts, requirement["requirement_ref"], duet_id)
    if check_row["kind"] != "refinement.check.v1":
        return {
            "eligible": False,
            "reason": "Use a registered experimental criterion or an exact admitted refinement check and its parent measure.",
        }
    if request["campaign_ref"] is None:
        raise ValueError("a refinement check requires its exact campaign")
    check = RefinementRecord.from_record(check_row["record"])
    contract_row = read_reference(artifacts, request["campaign_ref"], duet_id)
    if contract_row["kind"] != "refinement.campaign.v1":
        raise ValueError("refinement measurement requires a campaign contract")
    contract = RefinementRecord.from_record(contract_row["record"])
    if check.campaign_id != contract.campaign_id:
        raise ValueError("refinement check belongs to another campaign")
    with artifacts.transaction() as connection:
        view = CampaignView(connection, contract.campaign_id)
        if view.contract.ref != contract.ref or view.head["duet_id"] != duet_id:
            raise ValueError("measurement campaign is not the admitted contract")
        check = admitted_check(view, requirement)
        body = check.as_record()["body"]
        for reference in (*body["origin_refs"], *body["grounding_refs"]):
            read_reference(artifacts, reference, duet_id)
        if body["evidence_kind"] != "execution":
            return {
                "eligible": False,
                "reason": "This check requires Builder materialization evidence; a Run result cannot replace it.",
            }
        choices = check_bindings(view, check)
        if len(choices) != 1:
            return {
                "eligible": False,
                "reason": "The admitted check needs exactly one instrument/input binding.",
            }
        binding = choices[0]
        checker = checker_definition(view, binding)
        from iterative_episode_refiner.evidence import EvidenceReader
        from iterative_episode_refiner.instrument_builds import source_scope

        instrument = view.data(Ref.from_record(binding["harness_ref"]))
        if instrument.get("execution_kind") == "target_workflow":
            source_workflow = view.data(Ref.from_record(contract.body["target_workflow_ref"]))
        else:
            candidate = view.read(Ref.from_record(request["candidate_ref"]), "candidate")
            source = source_scope(EvidenceReader(artifacts, builds, runs), contract, candidate, binding)
            source_workflow = source.baseline.build_request.frozen_workflow.as_record()
        if canonical_json(source_workflow) != canonical_json(workflow.as_record()):
            raise ValueError("measurement belongs to a different approved workflow")
        template = native_template(view, binding).as_record()
        template.pop("request_id")
        predicate = view.data(Ref.from_record(body["predicate_ref"]))
        if predicate["interface"] != "refinement.predicate":
            raise ValueError(
                "runtime check requires a registered observation predicate"
            )
        resolve_predicate(predicate)

    # Refinement checks address the terminal event. Generic measurements address
    # its typed status; do not reinterpret arbitrary audit paths as result data.
    prefix = "/payload/typed_status"
    path = body["observation_path"]
    if path != prefix and not path.startswith(prefix + "/"):
        return {
            "eligible": False,
            "reason": "The check does not project a typed terminal result; no result-path substitution is permitted.",
        }
    conditions = (
        (
            request["environment_ref"] == body["environment_ref"],
            "different_environment",
        ),
        (
            request["scope"]["kind"] == "workflow",
            "scope_does_not_establish_this_requirement",
        ),
        (request["mode"] != "numerical", "mode_has_no_new_typed_result"),
        (launch_inputs == template, "different_or_unresolved_inputs"),
    )
    reasons = [reason for applies, reason in conditions if not applies]
    checking = None
    if checker is not None and not reasons:
        from .instruments import preview_instrument

        checking = preview_instrument(
            checker,
            request,
            artifacts=artifacts,
            builds=builds,
            runs=runs,
            duet_id=duet_id,
        )
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "criterion": {
            "requirement_key": body["requirement_key"],
            "predicate": _thaw_json(predicate),
            "observation_path": path[len(prefix) :],
            "expected_value": body["expected"],
            "limitations": [
                "The check's original campaign admission is reused, not newly established by this experiment.",
                "A predicate result covers this scope and evidence mode; campaign observation admission, independent parent acceptance and credit remain separate.",
            ],
        },
        "requirement_ref": requirement["requirement_ref"],
        "measure_ref": requirement["measure_ref"],
        "implementation_ref": None,
        "authority": "campaign_admitted_check",
        "campaign_ref": request["campaign_ref"],
        "execution_binding": _thaw_json(binding),
        "instrument": checking,
    }
