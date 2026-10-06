"""Interpret behavioral assignment choices against the parent's existing scope.

Specification addresses identify requirements by what they are. Measure bindings
are inherited; replacement and prerequisite routing are explicit operations,
not model-authored artifact identities.
"""

from agent.duet_contracts import canonical_json
from function_library.epistemic_contract import exact, names

from .records import Ref
from .report_contract import requirement_address


def requirement_keys(session, assignment, addresses):
    names(addresses, "requirement locations", nonempty=True)
    available = {
        requirement_address(row): row["requirement_key"]
        for row in session.requirements
        if row["requirement_key"] in assignment.body["scope_requirement_keys"]
    }
    missing = set(addresses) - available.keys()
    if missing:
        raise ValueError(f"requirements are outside this assignment: {sorted(missing)}")
    return [available[address] for address in addresses]


def assigned_addresses(session, assignment, field="contribution_requirement_keys"):
    selected = set(assignment.body[field])
    return [requirement_address(row) for row in session.requirements if row["requirement_key"] in selected]


def owned_slices(view, assignment, requirements):
    partition = view.data(Ref.from_record(assignment.body["scope_partition_ref"]))
    selected = [row for row in partition["slices"]
                if row["slice_key"] in assignment.body["owned_slice_keys"]
                and set(row["requirement_keys"]) <= set(requirements)]
    covered = {key for row in selected for key in row["requirement_keys"]}
    if covered != set(requirements):
        raise ValueError("the requested work must cover whole parent-declared requirement slices")
    return [row["slice_key"] for row in selected]


def replacements(view, assignment, role, requirements, replace_previous):
    if type(replace_previous) is not bool:
        raise ValueError("replace_previous must explicitly be true or false")
    if not replace_previous:
        return []
    candidates = [
        row.record for row in view.entries("invocation")
        if row.status == "returned"
        and row.record.body["parent_assignment_ref"] == assignment.ref.as_record()
        and row.record.body["role"] == role
        and set(row.record.body["contribution_requirement_keys"]) == set(requirements)
        and view.entry("assignment", row.record.artifact_id.value).status != "superseded"
    ]
    if not candidates:
        raise ValueError("there is no returned assignment of this role for these requirements to replace")
    # The operation means the most recently returned execution of this same work,
    # not a semantic guess at which arbitrary stored artifact the model meant.
    return [candidates[-1].ref.as_record()]


def prerequisite_choice(session, view, assignment, choice, *, include_inherited=False):
    exact(choice, {"kind", "purpose", "requirements"}, "returned prerequisite choice")
    requirements = requirement_keys(session, assignment, choice["requirements"])
    inherited = set()
    if include_inherited:
        goal = view.data(Ref.from_record(assignment.body["goal_record_ref"]))
        inherited = set(map(Ref.from_record, goal.get("prerequisite_refs", ())))
    matches = [
        row.record for row in view.entries("measure_need")
        if row.status == "requested"
        and (
            row.record.body["owner_assignment_ref"] == assignment.ref.as_record()
            or row.record.ref in inherited
        )
        # Replacement preserves explicitly inherited needs from its returned
        # predecessor, whose invocation is now marked superseded.
        and view.entry("invocation", row.record.invocation_id.value).status in (
            {"returned", "superseded"} if row.record.ref in inherited else {"returned"}
        )
        and row.record.body["need"]["kind"] == choice["kind"]
        and row.record.body["need"]["purpose"] == choice["purpose"]
        and set(row.record.body["need"]["requirement_keys"]) == set(requirements)
    ]
    if len({canonical_json(record.body["need"]) for record in matches}) != 1:
        raise ValueError("prerequisite choice must identify one returned need by kind, purpose and requirement scope")
    # Repeated returns can record the same exact need. Use the latest eligible
    # provenance; assignment inheritance retains its earlier references too.
    return matches[-1].ref.as_record()


def conflict_choice(session, view, assignment, choice):
    if choice is None:
        return None
    exact(choice, {"kind", "requirements"}, "coordination conflict")
    requirements = requirement_keys(session, assignment, choice["requirements"])
    matches = [row.record for row in view.entries("conflict")
               if row.status == "decision_required"
               and row.record.body["kind"] == choice["kind"]
               and set(row.record.body["requirement_keys"]) == set(requirements)
               and row.record.body["scope_owner_invocation_id"] == assignment.body["owning_parts_invocation_id"]]
    if len(matches) != 1:
        raise ValueError("coordination choice must identify one owned conflict by kind and requirement scope")
    return matches[0].ref.as_record()
