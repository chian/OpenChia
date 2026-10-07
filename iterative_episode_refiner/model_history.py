"""Full within-invocation history, projected from existing committed evidence.

This is working input, not a child report or an instruction channel. Rejected
outputs remain data; remembering a proposal does not admit it or award credit.
No recency window or model-authored summary hides earlier attempts.
"""

from agent.episode_contracts import OpaqueId, Sha256Digest
from episode_runtime.protocol import episode_id_for_path

from .coding_proposals import proposal_text
from .records import Ref
from .report_contract import _check_outcome, _open_decisions, requirement_address, requirement_catalog
from .reports import check_result


def _data_rows(view, kind, field, value):
    rows = view.connection.execute(
        "SELECT artifact_id, content_hash FROM artifacts WHERE duet_id = ? "
        "AND kind = ? AND json_extract(record_json, ?) = ? ORDER BY rowid",
        (view.head["duet_id"], f"refinement.{kind}.v1", field, value),
    )
    for row in rows:
        reference = Ref(OpaqueId(row["artifact_id"]), Sha256Digest(row["content_hash"]))
        yield reference, view.data(reference)


def _proposals(session, view, call):
    """Read already authenticated proposal artifacts, not whole Run transcripts."""
    episode_id = episode_id_for_path(session.registration.logical_run_id, [
        {"grain": grain, "key": key} for grain, key in call.path
    ])
    rejections = {
        Ref.from_record(value["proposal_ref"]): value["reason"]
        for _, value in _data_rows(view, "proposal_rejection",
                                  "$.assignment_ref.artifact_id", call.assignment.artifact_id.value)
    }
    # A logical Episode identity survives continuation. Proposal artifacts have
    # already passed the host producer check and retain their original order.
    return [{
        "task": value["task"],
        "output": proposal_text(session, value["event"]),
        # A recorded proposal is not proof of admission or a successful repair.
        "status": "rejected" if reference in rejections else "recorded",
        "rejection_reason": rejections.get(reference),
    } for reference, value in _data_rows(view, "model_proposal", "$.event.episode_id", episode_id.value)]


def iteration_history(session, view, call):
    from .candidate_environment import findings

    units = [entry.record for entry in view.entries("unit")
             if entry.record.invocation_id == call.invocation_id]
    catalog = requirement_catalog(view)
    observations = {entry.record.ref: entry for entry in view.entries("observation")}
    history = []
    for unit in units:
        body = unit.body
        results = []
        for reference in body["evaluation_refs"]:
            entry = observations[Ref.from_record(reference)]
            observation = entry.record
            check = view.read(observation.body["check_key"], "check")
            results.append({
                "requirement": requirement_address(catalog[check.body["requirement_key"]]),
                "purpose": check.body["purpose"],
                **_check_outcome(view, {
                    "check_key": check.artifact_id.value,
                    "outcome": observation.body["outcome"],
                    "observation_ref": observation.ref.as_record(),
                    "test_result": check_result(view, check, entry),
                }),
            })
        history.append({
            "ordinal": body["ordinal"],
            "evaluation_results": results,
            "candidate_changed": body["candidate_before_ref"] != body["candidate_after_ref"],
            "realized_yield": body["realized_yield"],
            "disposition": body["disposition"],
            "open_decisions": _open_decisions(view, call.assignment, {
                "decision_request_refs": [body["decision_request_ref"]]
                if body["decision_request_ref"] is not None else [],
            }, catalog),
        })
    return {
        "completed_units": len(history), "units": history,
        "proposals": _proposals(session, view, call),
        "environment_preparations": findings(view, invocation_id=call.invocation_id.value),
    }
