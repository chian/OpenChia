"""Retain completed requirement instruments within one commissioned Measure.

These components are private construction work. The parent receives one
completed composite; a partial component cannot change a caller's measure.
"""

from agent.duet_contracts import canonical_json
from agent.episode_contracts import OpaqueId

from .records import EvidenceRef, Ref


def measure_owner(view, assignment):
    """Resolve the commissioning Measure through its specialized Parts only."""
    current = assignment
    while current.body["role"] == "measure_parts":
        current = view.read(Ref.from_record(current.body["parent_assignment_ref"]), "assignment")
    if current.body["role"] != "measure":
        raise ValueError("measure components require an enclosing Measure commission")
    return current


def readable_paths(view, assignment):
    """Checker inputs retain the commission's read scope through decomposition."""
    owner = measure_owner(view, assignment)
    parent = view.read(Ref.from_record(owner.body["parent_assignment_ref"]), "assignment")
    from .materialization_edits import target_source_paths

    return sorted(set(parent.body["writable_paths"]) | target_source_paths(
        view, parent.body["materialization_targets"]
    ))


def _returned_source(view, assignment, source):
    """A component crosses each direct child-return boundary before assembly."""
    if source.ref == assignment.ref:
        return True
    current = source
    while current.body["role"] == "measure_parts":
        entries = [row for row in view.entries("invocation") if row.record.ref == current.ref]
        if len(entries) != 1 or entries[0].status not in {"returned", "superseded"}:
            return False
        if not any(row.record.invocation_id.value == entries[0].key for row in view.entries("report")):
            return False
        current = view.read(Ref.from_record(current.body["parent_assignment_ref"]), "assignment")
        if current.ref == assignment.ref:
            return True
    return False


def completed_components(view, assignment, *, replacing=()):
    """Freeze original adequate components, excluding the current design scope."""
    result = {}
    for entry in view.entries("measure"):
        if entry.status not in {"partial", "admitted"}:
            continue
        admission = entry.record
        proposal = view.read(Ref.from_record(admission.body["proposal_ref"]), "measure_proposal")
        source = view.read(Ref.from_record(proposal.body["assignment_ref"]), "assignment")
        if not _returned_source(view, assignment, source):
            continue
        goal = view.data(Ref.from_record(assignment.body["goal_record_ref"]))
        if proposal.body["basis_ref"] != goal["measure_basis_ref"]:
            continue
        authored = set(proposal.body["requirement_keys"]) | set(proposal.body["components"])
        for row in admission.body["requirement_results"]:
            if (row["status"] == "pass" and row["requirement_key"] in authored
                    and row["requirement_key"] in goal["measure_request"]["requirement_keys"]):
                result[row["requirement_key"]] = admission.ref.as_record()
    return {key: reference for key, reference in sorted(result.items()) if key not in replacing}


def load_components(view, proposal):
    """Resolve exact previously admitted pieces, never live-changing membership."""
    assignment = view.read(Ref.from_record(proposal.body["assignment_ref"]), "assignment")
    goal = view.data(Ref.from_record(assignment.body["goal_record_ref"]))
    requested = set(goal["measure_request"]["requirement_keys"])
    components = proposal.body["components"]
    if not set(components) <= requested - set(proposal.body["requirement_keys"]):
        raise ValueError("retained components must belong to the commissioned requirements outside the current design")
    result = {}
    for key, raw in sorted(components.items()):
        reference = Ref.from_record(raw)
        entry = view.entry("measure", reference.artifact_id.value)
        admission = entry.record
        original = view.read(Ref.from_record(admission.body["proposal_ref"]), "measure_proposal")
        source = view.read(Ref.from_record(original.body["assignment_ref"]), "assignment")
        if (entry.status not in {"partial", "admitted"}
                or admission.ref != reference
                or entry.status != admission.body["status"]
                or not _returned_source(view, assignment, source)
                or measure_owner(view, source).ref != measure_owner(view, assignment).ref
                or original.body["basis_ref"] != proposal.body["basis_ref"]
                or original.body["purpose"] != proposal.body["purpose"]
                or key not in set(original.body["requirement_keys"]) | set(original.body["components"])
                or not any(row["requirement_key"] == key and row["status"] == "pass"
                           for row in admission.body["requirement_results"])):
            raise ValueError("component lacks this Measure's exact admitted requirement instrument")
        result[key] = admission
    return result


def retain_components(view, proposal, measure_ref, *, checks, bindings, evidence, assessed, controls):
    """Assemble ready pieces and explicit gaps under the original commission."""
    assignment = view.read(Ref.from_record(proposal.body["assignment_ref"]), "assignment")
    goal = view.data(Ref.from_record(assignment.body["goal_record_ref"]))
    requested = goal["measure_request"]["requirement_keys"]
    outcomes = {row["requirement_key"]: row for row in assessed}
    checks, bindings, evidence, controls = list(checks), list(bindings), list(evidence), list(controls)
    limitations = list(proposal.body["limitation_refs"])
    for key, admission in load_components(view, proposal).items():
        outcomes[key] = next(row for row in admission.body["requirement_results"]
                             if row["requirement_key"] == key)
        component_checks = [check for raw in admission.body["check_refs"]
                            for check in (view.read(Ref.from_record(raw), "check"),)
                            if check.body["requirement_key"] == key]
        if not component_checks:
            raise ValueError("an adequate component must retain its original checks")
        checks.extend(component_checks)
        bindings.extend({**check.body["execution_binding"],
                         "measure_ref": measure_ref.as_record(), "purpose": proposal.body["purpose"]}
                        for check in component_checks)
        controls.extend(row for row in admission.body["control_results"] if row["requirement_key"] == key)
        evidence.extend(admission.evidence_refs)
        limitations.extend(admission.body["limitation_refs"])
        evidence.append(EvidenceRef("duet_artifact", OpaqueId(view.head["duet_id"]),
                                    admission.artifact_id, admission.content_hash, ""))
    results = [outcomes.get(key, {
        "requirement_key": key, "status": "blocked", "cases": [],
        "reason": "This commissioned requirement has no adequate component yet.",
    }) for key in sorted(requested)]
    return (
        checks,
        tuple({canonical_json(binding): binding for binding in bindings}.values()),
        tuple(dict.fromkeys(evidence)),
        results,
        controls,
        [ref.as_record() for ref in dict.fromkeys(map(Ref.from_record, limitations))],
    )
