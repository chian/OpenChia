"""Owner-controlled joint repair, with evidence preserved across child returns."""

from dataclasses import replace

from function_library.epistemic_contract import exact

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
        and joints.get(conflict.artifact_id.value) not in path
    )


def _owned_incident(view, attempt, reference):
    assignment = actor(view, attempt)
    ref = Ref.from_record(reference)
    entry = view.entry("conflict", ref.artifact_id.value)
    if (
        entry.record.ref != ref
        or entry.status != "decision_required"
        or assignment.body["role"] != "parts"
        or entry.record.body["scope_owner_invocation_id"] != attempt.invocation_id.value
    ):
        raise ValueError("only the active owning Parts may coordinate this incident")
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
        for child, parent in zip(path, path[1:]):
            if parent.ref == owner.ref:
                branches[child.artifact_id.value] = child
                break
        else:
            raise ValueError("incident has no affected branch under this Parts owner")
    return tuple(branches.values())


def coordinate_conflict(view, attempt, resolved):
    payload = exact(
        attempt.body["payload"],
        {"conflict_ref", "assignment", "invocation_id"},
        "joint assignment",
    )
    conflict = _owned_incident(view, attempt, payload["conflict_ref"])
    if any(
        entry.key == conflict.artifact_id.value
        for entry in view.entries("coordination")
    ):
        raise ValueError("incident already has a joint assignment")
    owner = view.entry("invocation", attempt.invocation_id.value).record
    assignment = proposed(view, attempt, "assignment", "assignment")
    checks = _checks_and_guards(view, conflict)
    requirements = {
        view.entry("check", key).record.body["requirement_key"] for key in checks
    }
    branches = _affected_branches(view, conflict, owner)
    if assignment.body["role"] != "designer" or not requirements.issubset(
        assignment.body["contribution_requirement_keys"]
    ):
        raise ValueError("joint Designer must accept both behaviors and their guards")
    if set(
        Ref.from_record(ref) for ref in assignment.body["supersedes_assignment_refs"]
    ) != {item.ref for item in branches}:
        raise ValueError(
            "joint assignment must retain and supersede all affected branches"
        )
    # A renamed or newly minted measure is not permission to forget old credit.
    # Semantic measure revisions need explicit predecessor admission; v1 joint
    # coordination therefore retains the existing exact local/acceptance measures.
    for branch in branches:
        if any(
            assignment.body[key] != branch.body[key]
            for key in ("local_measure_ref", "acceptance_measure_ref")
        ):
            raise ValueError(
                "joint repair must preserve the admitted measures and credit lineage"
            )
    records, deltas = admit_assignment(
        view, attempt, resolved, assignment, payload["invocation_id"]
    )
    branch_ids = {item.artifact_id.value for item in branches}
    for entry in view.entries("invocation"):
        if entry.record.artifact_id.value in branch_ids:
            continue  # already superseded by assignment admission
        if any(
            item.artifact_id.value in branch_ids
            for item in ancestors(view, entry.record)
        ):
            if entry.status in {"active", "waiting", "needs_parent_decision"}:
                raise ValueError(
                    "affected child stages must return before coordination"
                )
            deltas.append(index("invocation", entry.key, entry.record, "superseded"))
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
