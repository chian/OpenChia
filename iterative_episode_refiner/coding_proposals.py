"""Captured coding proposals stay in the store, outside worker control frames.

The model event authenticates the small reference. Resolving it supplies the
exact unadmitted bytes to the existing proposal admission and working history.
This is not a child-report projection or a grant to open arbitrary artifacts.
"""

import json

from agent.episode_contracts import OpaqueId, Sha256Digest
from episode_runtime.protocol import episode_id_for_path

from .records import Ref


def capture_proposal(session, call, candidate, task, model_task, proposal, turn_ref):
    reference = session.put_data("coding_proposal", {
        "campaign_id": session.campaign_id.value,
        "run_id": session.registration.run_id.value,
        "episode_id": episode_id_for_path(session.registration.logical_run_id, [
            {"grain": grain, "key": key} for grain, key in call.path
        ]).value,
        "invocation_id": call.invocation_id.value,
        "unit_id": call.unit_id.value,
        "candidate_ref": candidate.as_record(),
        "assignment_ref": call.assignment.ref.as_record(),
        "task": task, "model_task": model_task,
        "coding_turn_ref": turn_ref.as_record(),
        "response_text": json.dumps(proposal),
    })
    return json.dumps({"coding_proposal_ref": reference.as_record()}), {
        "coding_proposal_id": reference.artifact_id.value,
        "coding_proposal_hash": reference.content_hash.value,
    }


def proposal_text(session, event, *, call=None, task=None):
    """Resolve only the captured artifact bound to this committed model event."""
    payload = event["payload"]
    route = payload["route"]
    if "coding_proposal_id" not in route:
        return payload["response_text"]
    reference = Ref(OpaqueId(route["coding_proposal_id"]), Sha256Digest(route["coding_proposal_hash"]))
    if json.loads(payload["response_text"]) != {"coding_proposal_ref": reference.as_record()}:
        raise ValueError("coding proposal response differs from its host-captured reference")
    saved = session.store.evidence.reference(reference, session.duet_id)
    if (
        session.store.data_reference(session.duet_id, "coding_proposal", saved) != reference
        or saved["campaign_id"] != session.campaign_id.value
        or saved["run_id"] != event["run_id"]
        or saved["episode_id"] != event["episode_id"]
        or saved["model_task"] != route["task"]
        or any(saved[key] != route[key] for key in ("invocation_id", "unit_id"))
        or saved["coding_turn_ref"] != {
            "artifact_id": route["coding_turn_ref"], "content_hash": route["coding_turn_hash"],
        }
    ):
        raise ValueError("coding proposal does not belong to this recorded call")
    if call is not None:
        with session.view() as view:
            if (
                saved["invocation_id"] != call.invocation_id.value
                or saved["unit_id"] != call.unit_id.value
                or saved["assignment_ref"] != call.assignment.ref.as_record()
                or saved["candidate_ref"] != view.candidate.ref.as_record()
                or saved["task"] != task
            ):
                raise ValueError("coding proposal differs from the active assignment, unit or candidate")
    return saved["response_text"]
