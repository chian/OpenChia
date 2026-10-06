"""Measurement ownership in the repair loop, not an execution/test harness.

EstablishMeasure supplies an exact instrument proposal to its parent. Grounding
references are not themselves an admission decision. Only the shared host
validation service can establish adequacy and make new checks operative.
"""

from agent.duet_contracts import canonical_json
from function_library.epistemic_contract import exact

from .records import Ref


def _within_owner(view, owner_ref, assignment):
    pending, seen = [assignment], set()
    while pending:
        current = pending.pop()
        if current.ref in seen:
            continue
        seen.add(current.ref)
        if current.ref.as_record() == owner_ref:
            return True
        references = list(current.body["supersedes_assignment_refs"])
        if current.body["parent_assignment_ref"] is not None:
            references.append(current.body["parent_assignment_ref"])
        pending.extend(
            view.read(Ref.from_record(ref), "assignment") for ref in references
        )
    return False


def admitted_measures(view, assignment):
    return tuple(
        entry.record
        for entry in view.entries("measure")
        if entry.status == "admitted"
        and _within_owner(view, entry.record.body["owner_assignment_ref"], assignment)
    )


def authorized_check_refs(view, policy, assignment):
    from .measure_groups import admitted_members

    return tuple(
        dict.fromkeys(
            [Ref.from_record(item) for item in policy["check_refs"]]
            + [
                Ref.from_record(item)
                for measure in admitted_measures(view, assignment)
                for item in measure.body["check_refs"]
            ]
            + [check.ref for check, _ in admitted_members(view, policy, assignment)]
        )
    )


def evaluation_bindings(view, policy, assignment):
    from .measure_groups import admitted_members, member_bindings

    bindings = list(policy["evaluation_bindings"])
    bindings.extend(member_bindings(admitted_members(view, policy, assignment)))
    bindings = list({canonical_json(binding): binding for binding in bindings}.values())
    known = {canonical_json(binding) for binding in bindings}
    for measure in admitted_measures(view, assignment):
        contexts = measure.body.get("evaluation_bindings", ())
        if measure.body["evaluation_binding"] is not None:
            contexts = (measure.body["evaluation_binding"],)
        for binding in contexts:
            if canonical_json(binding) not in known:
                bindings.append(binding)
                known.add(canonical_json(binding))
    return tuple(bindings)


def bindings_for_check(bindings, check):
    """One check cannot overwrite its outcome with evidence from another case."""
    context = check.body.get("execution_binding")
    matches = (
        binding
        for binding in bindings
        if binding["measure_ref"] == check.body["measure_ref"]
        and binding["purpose"] == check.body["purpose"]
        and (
            context is None
            or all(
                canonical_json(binding[field]) == canonical_json(context[field])
                for field in ("harness_ref", "capability_ref", "input_refs")
            )
        )
    )
    return tuple({canonical_json(binding): binding for binding in matches}.values())


def unit_admissions(view, attempt):
    return tuple(
        entry.record
        for entry in view.entries("measure")
        if entry.record.invocation_id == attempt.invocation_id
        and entry.record.logical_unit_id == attempt.logical_unit_id
    )


def admission_decision(view, attempt):
    return next(
        (
            record
            for record in reversed(unit_admissions(view, attempt))
            if record.body["status"] == "rejected"
        ),
        None,
    )


def require_implementation_measure(view, assignment, reference, requirements, policy):
    """A design must name a usable coding measure before it invokes a coder."""
    frozen = set(authorized_check_refs(view, policy, assignment))
    covered = {
        row.record.body["requirement_key"]
        for row in view.entries("check")
        if row.record.ref in frozen
        and row.record.body["measure_ref"] == reference
        and row.record.body["purpose"] == "local"
        and row.record.body["mandatory"]
        and row.record.body["environment_ref"] == view.contract.body["environment_ref"]
    }
    if not set(requirements).issubset(covered):
        from .report_contract import requirement_address, requirement_catalog

        catalog = requirement_catalog(view)
        missing = sorted(requirement_address(catalog[key]) for key in set(requirements) - covered)
        raise ValueError(
            "implementation measure has unresolved requirement coverage: "
            f"{missing!r}. Establish those local checks, or return the unresolved "
            "need to Parts so it can assign a measurable prerequisite separately. "
            "Existing materialization checks can judge a static repair; they "
            "cannot replace later behavioral acceptance."
        )


def propose_measure(view, attempt, resolved):
    from .state_machine import actor, index, proposed
    from .measure_needs import request_prerequisite, return_prerequisite

    assignment = actor(view, attempt)
    if "return_prerequisite_ref" in attempt.body["payload"]:
        return return_prerequisite(view, attempt)
    if {"check_design", "check_review"} & set(attempt.body["payload"]):
        from .measure_design import propose

        return propose(view, attempt)
    if assignment.body["role"] != "measure":
        raise ValueError(
            "only the assigned EstablishMeasure child proposes an instrument"
        )
    if "prerequisite_request" in attempt.body["payload"]:
        return request_prerequisite(view, attempt)
    exact(attempt.body["payload"], {"proposal"}, "measure proposal")
    proposal = proposed(view, attempt, "proposal", "measure_proposal")
    body = proposal.body
    if (
        body["assignment_ref"] != assignment.ref.as_record()
        or body["owner_assignment_ref"] != assignment.body["parent_assignment_ref"]
    ):
        raise ValueError("measure proposal must return to the assigning parent")
    need = resolved.references["measure_request"]
    if (
        body["purpose"] != need["purpose"]
        or set(body["requirement_keys"]) != set(need["requirement_keys"])
        or not set(body["requirement_keys"]).issubset(
            assignment.body["contribution_requirement_keys"]
        )
    ):
        raise ValueError("measure proposal changes the parent's requested judgment")
    # This is an indexed proposal, not installed checks, an admitted measure,
    # positive credit, or permission to execute instrument code.
    return [proposal], [
        index("measure_proposal", proposal.artifact_id.value, proposal, "proposed")
    ]
