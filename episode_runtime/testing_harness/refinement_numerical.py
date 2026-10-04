"""Decode committed refinement control facts from the shared Run recording.

The recorded host decision supplies its already lineage-projected snapshot.
Today's campaign index is never substituted for that historical state.
"""

from agent.duet_contracts import canonical_json
from function_library.models import _thaw_json
from iterative_episode_refiner.records import RefinementRecord, Ref

from ..records.experiments import read_reference, read_run_intent


def prepare_trace(
    *, request, source, binding, recording, invocation, local, contract, artifacts
):
    intent = read_run_intent(artifacts, binding["record"]["intent_ref"], source)
    if intent["kind"] == "refinement.campaign.v1":
        campaign_ref = {key: intent[key] for key in ("artifact_id", "content_hash")}
    elif (
        intent["kind"] == "experiment.dispatch.v1"
        and intent["record"]["plan"].get("subject", {}).get("kind") == "refinement_job"
    ):
        campaign_ref = intent["record"]["spec"]["campaign_ref"]
    else:
        raise ValueError(
            "Refinement numerical replay needs the original execution's exact campaign intent."
        )
    if request["campaign_ref"] != campaign_ref:
        raise ValueError("Numerical experiment changes the source refiner's campaign.")
    owner = intent["duet_id"]
    campaign = RefinementRecord.from_record(
        read_reference(artifacts, campaign_ref, owner)["record"]
    )
    policy_ref = _thaw_json(campaign.body["policy_bundle_ref"])
    policy = read_reference(artifacts, policy_ref, owner)["record"]
    expected_numeric = contract.numeric_control.as_record()
    commits = []
    for exchange in recording["exchanges"]:
        if (
            exchange["kind"] != "refinement"
            or exchange["episode_id"] != invocation["episode_id"]
            or exchange["request"]["operation"] != "close_unit"
        ):
            continue
        response = exchange["response"]
        decision = RefinementRecord.from_record(response["numerical_decision"])
        receipt = RefinementRecord.from_record(response["measurement"])
        for record in (decision, receipt):
            stored = RefinementRecord.from_record(
                read_reference(artifacts, record.ref.as_record(), owner)["record"]
            )
            if stored != record or record.campaign_id != campaign.campaign_id:
                raise ValueError(
                    "Recorded numerical result differs from its committed campaign evidence."
                )
        if (
            decision.kind != "continuation"
            or receipt.kind != "unit_receipt"
            or receipt.body["continuation_ref"] != decision.ref.as_record()
            or response["receipt_ref"] != receipt.ref.as_record()
            or decision.invocation_id != receipt.invocation_id
            or decision.logical_unit_id != receipt.logical_unit_id
            or exchange["request"]["payload"]["unit_id"]
            != receipt.logical_unit_id.value
            or canonical_json(decision.body["numeric_control"])
            != canonical_json(expected_numeric)
            or canonical_json(decision.body["opportunity_function"])
            != canonical_json(policy["opportunity_function"])
        ):
            raise ValueError(
                "Refinement numerical evidence differs from its unit or frozen policy."
            )
        if "prior_remaining_opportunities" not in decision.body:
            raise ValueError(
                "This historical refinement decision lacks its prior opportunity bound; exact numerical replay is unavailable."
            )
        assignment_ref = Ref.from_record(receipt.body["assignment_ref"])
        assignment = RefinementRecord.from_record(
            read_reference(artifacts, assignment_ref.as_record(), owner)["record"]
        )
        if assignment.campaign_id != campaign.campaign_id:
            raise ValueError("Recorded unit assignment belongs to another campaign.")
        commits.append({
            "event_ref": exchange["response_event_ref"],
            "payload": {
                "unit_id": receipt.logical_unit_id.value,
                "numeric_step": _thaw_json(decision.body["numeric_step"]),
                "terminal_state": receipt.body["disposition"],
            },
            "decision": _thaw_json(decision.body),
            "decision_ref": decision.ref.as_record(),
            "receipt_ref": receipt.ref.as_record(),
        })
    if not commits:
        raise ValueError(
            f"{local}: no committed refinement control observations; an empty trace is not a pass."
        )
    if len({item["receipt_ref"]["artifact_id"] for item in commits}) != len(commits):
        raise ValueError("Recorded refinement invocation repeats a unit receipt.")
    return {
        "family": "refinement",
        "episode_id": invocation["episode_id"],
        "local_id": local,
        "episode_path": invocation["episode_path"],
        "policy_ref": policy_ref,
        "numeric_control": expected_numeric,
        "commits": commits,
    }


def evaluate_trace(trace):
    from iterative_episode_refiner.control import recompute_numerical_step

    units = []
    for committed in trace["commits"]:
        payload = committed["payload"]
        step = recompute_numerical_step(committed["decision"])
        units.append({
            "unit_id": payload["unit_id"],
            "source_event_ref": committed["event_ref"],
            "receipt_ref": committed["receipt_ref"],
            "decision_ref": committed["decision_ref"],
            "recorded": payload["numeric_step"],
            "recomputed": step,
            "matches": canonical_json(step) == canonical_json(payload["numeric_step"]),
            "source_terminal_state": payload["terminal_state"],
        })
    return units
