"""Owner-controlled joint repair, with evidence preserved across child returns."""

from dataclasses import replace

from function_library.epistemic_contract import exact
from function_library.refinement_contract import ROLE_SPECIALIZATION

from .records import Ref
from .state_machine import actor, admit_assignment, derived, index, proposed


def ancestors(view, assignment):
    result = [assignment]
    while assignment.body["parent_assignment_ref"] is not None:
        assignment = view.read(
            Ref.from_record(assignment.body["parent_assignment_ref"]), "assignment"
        )
        result.append(assignment)
    return result


def relevant_conflicts(view, assignment):
    requirements = set(assignment.body["scope_requirement_keys"])
    return tuple(
        entry.record
        for entry in view.entries("conflict")
        if entry.status in {"suspected", "decision_required"}
        and requirements.intersection(entry.record.body["requirement_keys"])
    )


def pending_decisions(view, invocation_id):
    """Suspend descendants awaiting their owner, not its still-waiting ancestors."""
    assignment = view.entry("invocation", invocation_id).record
    path = {item.artifact_id.value for item in ancestors(view, assignment)}
    joints = {
        row.record.body["conflict_ref"]["artifact_id"]: row.record.body[
            "joint_assignment_ref"
        ]["artifact_id"]
        for row in view.entries("coordination")
    }
    return tuple(
        conflict
        for conflict in relevant_conflicts(view, assignment)
        if conflict.body["state"] == "decision_required"
        and conflict.body["scope_owner_invocation_id"] != invocation_id
        and view.entry(
            "invocation", conflict.body["scope_owner_invocation_id"]
        ).record.artifact_id.value in path
        and joints.get(conflict.artifact_id.value) not in path
    )


def return_owned_conflicts(view, attempt, parent):
    """Carry unresolved coordination upward with the owning child's normal return."""
    owned = [
        entry for entry in view.entries("conflict")
        if entry.status == "decision_required"
        and entry.record.body["scope_owner_invocation_id"] == attempt.invocation_id.value
    ]
    if not owned:
        return [], []
    coordinator = next(
        item for item in ancestors(view, parent)
        if ROLE_SPECIALIZATION[item.body["role"]] not in {"question", "support"}
    )
    invocations = [
        entry for entry in view.entries("invocation")
        if entry.record.ref == coordinator.ref
    ]
    if len(invocations) != 1:
        raise ValueError("returning conflict has no unique coordinating ancestor")
    owner_id = invocations[0].key
    records, deltas = [], []
    for entry in owned:
        conflict = entry.record
        if not set(conflict.body["requirement_keys"]) <= set(coordinator.body["scope_requirement_keys"]):
            raise ValueError("returning conflict exceeds its coordinating ancestor's scope")
        revised = replace(
            conflict,
            body={**conflict.body, "scope_owner_invocation_id": owner_id},
            predecessor_refs=(*conflict.predecessor_refs, conflict.ref, attempt.ref),
        )
        records.append(revised)
        deltas.extend((
            index("conflict", entry.key, conflict, "superseded"),
            index("conflict", revised.artifact_id.value, revised, "decision_required"),
        ))
    return records, deltas


def _owned_incident(view, attempt, reference):
    assignment = actor(view, attempt)
    ref = Ref.from_record(reference)
    entry = view.entry("conflict", ref.artifact_id.value)
    if (
        entry.record.ref != ref
        or entry.status != "decision_required"
        or ROLE_SPECIALIZATION[assignment.body["role"]] in {"question", "support"}
        or entry.record.body["scope_owner_invocation_id"] != attempt.invocation_id.value
    ):
        raise ValueError("only the active owning Episode may coordinate this incident")
    return entry.record


def _checks_and_guards(view, conflict):
    keys = {
        view.read(Ref.from_record(ref), "observation").body["check_key"]
        for ref in conflict.body["observation_refs"]
    }
    pending = list(keys)
    while pending:
        check = view.entry("check", pending.pop()).record
        for guard in check.body["guard_keys"]:
            if guard not in keys:
                keys.add(guard)
                pending.append(guard)
    if not keys:
        raise ValueError("a source revisit alone does not justify joint repair")
    return keys


def _affected_branches(view, conflict, owner):
    """Find actual direct children, not a worker-supplied ancestry summary."""
    branches = {}
    for reference in conflict.body["involved_assignment_refs"]:
        path = ancestors(view, view.read(Ref.from_record(reference), "assignment"))
        if path[0].ref == owner.ref:
            continue
        for child, parent in zip(path, path[1:]):
            if parent.ref == owner.ref:
                branches[child.artifact_id.value] = child
                break
        else:
            raise ValueError("incident has no affected branch under this coordinating Episode")
    return tuple(branches.values())


def coordinate_conflict(view, attempt, resolved):
    payload = exact(
        attempt.body["payload"],
        {"conflict_ref", "assignment", "invocation_id"},
        "joint assignment",
    )
    conflict = _owned_incident(view, attempt, payload["conflict_ref"])
    owner = view.entry("invocation", attempt.invocation_id.value).record
    for entry in view.entries("coordination"):
        if entry.key != conflict.artifact_id.value:
            continue
        prior_ref = Ref.from_record(entry.record.body["joint_assignment_ref"])
        if any(
            row.record.ref == prior_ref and row.status != "returned"
            for row in view.entries("invocation")
        ):
            raise ValueError("the current coordinated contribution must return first")
    assignment = proposed(view, attempt, "assignment", "assignment")
    checks = _checks_and_guards(view, conflict)
    requirements = {
        view.entry("check", key).record.body["requirement_key"] for key in checks
    }
    branches = _affected_branches(view, conflict, owner)
    if not requirements.intersection(assignment.body["contribution_requirement_keys"]):
        raise ValueError("coordinated work must address an affected requirement or guard")
    records, deltas = admit_assignment(
        view, attempt, resolved, assignment, payload["invocation_id"]
    )
    branch_ids = {item.artifact_id.value for item in branches}
    for entry in view.entries("invocation"):
        if entry.record.artifact_id.value in branch_ids or any(
            item.artifact_id.value in branch_ids
            for item in ancestors(view, entry.record)
        ):
            if entry.status in {"active", "waiting", "needs_parent_decision"}:
                raise ValueError(
                    "affected child stages must return before coordination"
                )
    # The owner may need contributions from several distinct specialties. Each
    # receives its own grant; all original checks remain required for resolution.
    # Ordinary explicit replacement still enforces its full succession contract.
    coordination = derived(
        view,
        attempt,
        "coordination",
        {
            "conflict_ref": conflict.ref.as_record(),
            "joint_assignment_ref": assignment.ref.as_record(),
            "original_assignment_refs": conflict.body["involved_assignment_refs"],
            "required_check_keys": sorted(checks),
        },
        evidence=conflict.evidence_refs,
    )
    return [*records, coordination], [
        *deltas,
        index("coordination", conflict.artifact_id.value, coordination),
    ]


def resolve_conflict(view, attempt, resolved):
    payload = exact(attempt.body["payload"], {"conflict_ref"}, "conflict resolution")
    conflict = _owned_incident(view, attempt, payload["conflict_ref"])
    coordination = view.entry("coordination", conflict.artifact_id.value).record
    observations = []
    for key in coordination.body["required_check_keys"]:
        entry = view.entry("check_state", key)
        request = view.read(
            Ref.from_record(entry.record.body["request_ref"]), "evaluation"
        )
        if (
            entry.status != "pass"
            or Ref.from_record(request.body["candidate_ref"]) != view.candidate.ref
        ):
            raise ValueError(
                "joint resolution requires all preserved checks on one current candidate"
            )
        observations.append(entry.record)
    evidence = tuple(
        dict.fromkeys(ref for item in observations for ref in item.evidence_refs)
    )
    resolution = derived(
        view,
        attempt,
        "conflict_resolution",
        {
            "conflict_ref": conflict.ref.as_record(),
            "coordination_ref": coordination.ref.as_record(),
            "candidate_ref": view.candidate.ref.as_record(),
            "observation_refs": [item.ref.as_record() for item in observations],
            "required_check_keys": coordination.body["required_check_keys"],
        },
        evidence=evidence,
    )
    revised = replace(
        conflict,
        body={
            **conflict.body,
            "state": "resolved",
            "resolution_ref": resolution.ref.as_record(),
        },
        predecessor_refs=(*conflict.predecessor_refs, conflict.ref),
        evidence_refs=tuple(dict.fromkeys((*conflict.evidence_refs, *evidence))),
    )
    return [resolution, revised], [
        index("conflict", conflict.artifact_id.value, revised, "resolved")
    ]
