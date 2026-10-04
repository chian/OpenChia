"""Host call state carried by the common Run journal, not a replay log.

The campaign owns edits, evidence and credit. This projection only preserves
the session's otherwise in-memory call bindings and open units. On its own it
neither authorizes continuation nor restores the worker's nested execution.
"""

from agent.duet_contracts import canonical_json
from agent.episode_contracts import OpaqueId
from episode_runtime.continuation import validate_resume_registration
from episode_runtime.protocol import episode_id_for_path
from function_library.epistemic_contract import exact
from function_library.refinement_contract import REQUEST_PAYLOAD, RESULT_PAYLOAD
from handoff_library import ParentRequestAddress, admit_parent_request
from method_loop import EpisodeGoal

from .records import Ref


_STATE_FIELDS = {
    "schema_version", "kind", "registration_ref", "campaign_ref", "campaign_head",
    "operation_ordinal", "root_episode_id", "calls", "pending_children",
}
_CALL_FIELDS = {
    "episode_id", "invocation_id", "assignment_ref", "episode_path", "goal",
    "request", "unit_id", "candidate_before_ref", "feedback_ref", "status",
}


def _reference(value):
    return None if value is None else value.as_record()


def _invocation(episode_id, call, status):
    return {
        "episode_id": episode_id,
        "invocation_id": call.invocation_id.value,
        "assignment_ref": call.assignment.ref.as_record(),
        "episode_path": [
            {"grain": grain, "key": key} for grain, key in call.path
        ],
        "goal": call.goal.as_record(),
        "request": _reference(call.request),
        "unit_id": None if call.unit_id is None else call.unit_id.value,
        "candidate_before_ref": _reference(call.candidate_before),
        "feedback_ref": _reference(call.feedback_ref),
        "status": status,
    }


def continuation_state(session):
    """Capture the same head for all active/prepared call references.

    Completed child history stays in the campaign. A child that has finished
    but has not yet returned must remain here: its parent is still waiting.
    """
    with session.view() as view:
        statuses = {entry.key: entry.status for entry in view.entries("invocation")}
        calls = [
            _invocation(episode_id, call, statuses[call.invocation_id.value])
            for episode_id, call in sorted(session.calls.items())
            if episode_id == session.root_id
            or statuses[call.invocation_id.value] not in {"returned", "superseded"}
        ]
        pending = [
            _invocation(episode_id, call, statuses[call.invocation_id.value])
            for episode_id, call in sorted(session.pending.items())
        ]
        return {
            "schema_version": 1,
            "kind": "refinement_session_state",
            "registration_ref": {
                "run_id": session.registration.run_id.value,
                "content_hash": session.registration.registration_hash.value,
            },
            "campaign_ref": session.contract.ref.as_record(),
            "campaign_head": dict(view.head),
            "operation_ordinal": session._operation_ordinal,
            "root_episode_id": session.root_id,
            "calls": calls,
            "pending_children": pending,
        }


def _restore_call(session, view, row, *, pending, calls):
    from .runtime import Invocation

    exact(row, _CALL_FIELDS, "saved refinement invocation")
    episode_id = OpaqueId(row["episode_id"])
    if episode_id_for_path(session.registration.logical_run_id, row["episode_path"]) != episode_id:
        raise ValueError("saved refinement invocation has the wrong runtime identity")
    path = tuple((part["grain"], part["key"]) for part in row["episode_path"])
    entry = view.entry("invocation", OpaqueId(row["invocation_id"]).value)
    if entry.record.ref != Ref.from_record(row["assignment_ref"]) or entry.status != row["status"]:
        raise ValueError("saved refinement assignment or status differs from the campaign")
    assignment = entry.record
    request = None
    if episode_id.value == session.root_id:
        initial = session.calls[session.root_id]
        if pending or path != initial.path or entry.record.ref != initial.assignment.ref or row["request"] is not None:
            raise ValueError("saved refinement root differs from its approved launch")
        goal = initial.goal
    else:
        parent_id = episode_id_for_path(session.registration.logical_run_id, row["episode_path"][:-1]).value
        parent = calls.get(parent_id)
        if parent is None or assignment.body["parent_assignment_ref"] != parent.assignment.ref.as_record():
            raise ValueError("saved refinement child has no matching admitted parent")
        role = assignment.body["role"]
        node = session.nodes[role]
        parent_node = session.nodes_by_grain[parent.path[-1][0]]
        edge = session.edges.get((parent_node.local_id, role))
        if edge is None or edge.child_local_id != node.local_id or path != parent.path + ((node.grain_name, entry.key),):
            raise ValueError("saved refinement child differs from the fixed call topology")
        goal = EpisodeGoal.child(
            parent.goal,
            objective={
                "role": role, "assignment_id": assignment.artifact_id.value,
                "goal": session.store.evidence.reference(Ref.from_record(assignment.body["goal_record_ref"]), session.duet_id),
            },
            result_contract=RESULT_PAYLOAD.as_record(),
        )
        if pending:
            if entry.status != "ready" or any(row[key] is not None for key in ("request", "unit_id", "candidate_before_ref", "feedback_ref")):
                raise ValueError("saved prepared child is not an unentered ready assignment")
        else:
            if entry.status in {"ready", "returned", "superseded"} or view.entry("invocation", parent.invocation_id.value).status != "waiting":
                raise ValueError("saved entered child has no waiting parent")
            if row["request"] is None:
                raise ValueError("saved entered child lacks its admitted request")
            request = admit_parent_request(
                row["request"],
                ParentRequestAddress(row["request"]["request_id"], parent_id, episode_id.value, goal.goal_id, node.interface),
                REQUEST_PAYLOAD,
            )
            if dict(request.artifact_ids_by_role) != {
                "campaign": (session.campaign_id.value,),
                "assignment": (assignment.artifact_id.value,),
                "invocation": (entry.key,),
            }:
                raise ValueError("saved child request changed its assignment")
    if EpisodeGoal.from_record(row["goal"]) != goal:
        raise ValueError("saved refinement goal differs from its admitted assignment")
    candidate = None if row["candidate_before_ref"] is None else Ref.from_record(row["candidate_before_ref"])
    if candidate is not None:
        view.read(candidate, "candidate")
    unit = None if row["unit_id"] is None else OpaqueId(row["unit_id"])
    if unit is not None and (candidate is None or entry.status not in {"active", "waiting"}):
        raise ValueError("saved open unit lacks its candidate or live invocation")
    feedback = None if row["feedback_ref"] is None else Ref.from_record(row["feedback_ref"])
    if feedback is not None:
        session.store.evidence.reference(feedback, session.duet_id)
    return Invocation(OpaqueId(entry.key), assignment, path, goal, request, unit, candidate, feedback)


def restore_session(session):
    """Restore only host-recorded call metadata, without replaying any mutation.

    The shared journal is the sole input; callers cannot supply replacement
    state. This does not authorize the worker or turn prefix matching into a
    permission to resume. The executor must still admit its activation boundary.
    """
    from episode_runtime.testing.reconstruction import ReconstructionCursor

    registration = session.registration
    if registration.resume_from is None:
        raise ValueError("host restoration requires an exact interrupted Run")
    runs = session.store.evidence.runs
    validate_resume_registration(runs, registration)
    cursor = ReconstructionCursor(
        runs, registration.resume_from.run_id, artifacts=session.store.duet_store
    )
    saved = cursor.host_state
    if saved is None or saved["state"] is None:
        if cursor.prefix_verified:
            validate_unstarted_session(session)
            return
        raise ValueError("interrupted Run has no committed refinement host state")
    _restore_state(session, saved)


def validate_unstarted_session(session):
    """An empty worker history may start only the campaign's original state."""
    from episode_runtime.records.experiments import read_record

    claim = read_record(session.store.duet_store, "refinement_job", campaign_id=session.campaign_id.value)
    if claim is None:
        raise ValueError("unstarted refinement lacks its original campaign dispatch")
    with session.view() as view:
        current = {
            "campaign_ref": session.contract.ref.as_record(),
            "candidate_ref": view.candidate.ref.as_record(),
            "sequence": view.head["sequence"],
            "latest_commit_id": view.head["latest_commit_id"],
        }
        if canonical_json(current) != canonical_json(claim["record"]["starting_state"]):
            raise ValueError("unstarted refinement campaign changed after dispatch")


def restore_terminal_session(session):
    """Reattach host projection to its own terminal Run, without executing it."""
    from episode_runtime.contracts import RunEventKind
    from episode_runtime.testing.recordings import event_reference
    from episode_runtime.records.host_operations import read_receipt

    runs = session.store.evidence.runs
    snapshot = runs.read_terminal_snapshot(session.registration.run_id)
    saved = None
    for event in snapshot.events:
        if event.kind is RunEventKind.REFINEMENT_RESPONDED:
            saved = {"event_ref": event_reference(event), "state": event.payload.get("session_state")}
        elif event.kind is RunEventKind.REFINEMENT_REQUESTED:
            receipt = read_receipt(session.store.duet_store, session.registration, event)
            if receipt is not None:
                saved = {"event_ref": event_reference(event), "state": receipt["session_state"]}
    if saved is None or saved["state"] is None:
        raise ValueError("terminal Run lacks its host projection state")
    _restore_state(session, saved)


def _restore_state(session, saved):
    from json import loads

    saved = loads(canonical_json(saved))
    registration = session.registration
    runs = session.store.evidence.runs
    state = saved["state"]
    producing_registration = runs.read_registration(OpaqueId(saved["event_ref"]["run_id"]))
    exact(state, _STATE_FIELDS, "saved refinement session")
    if (
        type(state["schema_version"]) is not int or state["schema_version"] != 1
        or state["kind"] != "refinement_session_state"
        or state["registration_ref"] != {
            "run_id": producing_registration.run_id.value,
            "content_hash": producing_registration.registration_hash.value,
        }
        or state["campaign_ref"] != session.contract.ref.as_record()
        or state["root_episode_id"] != session.root_id
    ):
        raise ValueError("saved refinement state belongs to another Run or campaign")
    ordinal = state["operation_ordinal"]
    if type(ordinal) is not int or ordinal < 0:
        raise ValueError("saved refinement operation ordinal must be nonnegative")
    calls, pending, invocation_ids = {}, {}, set()
    with session.view() as view:
        session.store._authority(view.connection, view.head["duet_id"], view.head["authority_head_id"])
        session.store._authority(view.connection, registration.duet_id.value, registration.authority_head_approval_id.value)
        if canonical_json(view.head) != canonical_json(state["campaign_head"]):
            raise ValueError("campaign changed after the saved host response; continuation cannot substitute newer state")
        for key, destination in (("calls", calls), ("pending_children", pending)):
            rows = state[key]
            if not isinstance(rows, list):
                raise ValueError("saved refinement calls must be arrays")
            for row in rows:
                exact(row, _CALL_FIELDS, "saved refinement invocation")
            for row in sorted(rows, key=lambda item: len(item["episode_path"])):
                if row["episode_id"] in calls or row["episode_id"] in pending or row["invocation_id"] in invocation_ids:
                    raise ValueError("saved refinement state repeats an invocation")
                call = _restore_call(session, view, row, pending=key == "pending_children", calls=calls)
                destination[row["episode_id"]] = call
                invocation_ids.add(call.invocation_id.value)
        required = {
            row.key for row in view.entries("invocation")
            if row.status not in {"ready", "returned", "superseded"}
        }
        if session.root_id not in calls or {call.invocation_id.value for call in calls.values()} != required:
            raise ValueError("saved refinement state omits a live or unreturned invocation")
    session.calls, session.pending = calls, pending
    session._operation_ordinal = ordinal


def validate_restored_state(session, saved):
    """Recheck at activation; reconstruction may not silently pick up new edits."""
    with session.view() as view:
        session.store._authority(view.connection, view.head["duet_id"], view.head["authority_head_id"])
        session.store._authority(view.connection, session.registration.duet_id.value, session.registration.authority_head_approval_id.value)
        if canonical_json(view.head) != canonical_json(saved["campaign_head"]):
            raise ValueError("campaign changed during reconstruction; start a new experiment")
    expected = dict(saved)
    expected["registration_ref"] = {
        "run_id": session.registration.run_id.value,
        "content_hash": session.registration.registration_hash.value,
    }
    if canonical_json(session.continuation_state()) != canonical_json(expected):
        raise ValueError("restored host call state changed during reconstruction")
