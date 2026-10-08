"""Measurement ownership in the repair loop, not an execution/test harness.

EstablishMeasure supplies an exact instrument proposal to its parent. Grounding
references are not themselves an admission decision. Only the shared host
validation service can establish adequacy and make new checks operative.
"""

from agent.duet_contracts import canonical_json, content_id
from function_library.epistemic_contract import exact
from function_library.materialization_progress import RequirementMeasure
from function_library.refinement_contract import ROLE_SPECIALIZATION

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
    return tuple(
        dict.fromkeys(
            [Ref.from_record(item) for item in policy["check_refs"]]
            + [
                Ref.from_record(item)
                for measure in admitted_measures(view, assignment)
                for item in measure.body["check_refs"]
            ]
        )
    )


def evaluation_bindings(view, policy, assignment):
    bindings = list(policy["evaluation_bindings"])
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


def bindings_for_check(bindings, check, *, measure_ref=None):
    """One check cannot overwrite its outcome with evidence from another case."""
    context = check.body.get("execution_binding")
    if context is None and measure_ref is not None and measure_ref != check.body["measure_ref"]:
        # Initial Builder checks share their original policy's exact instrument.
        # A composite retains those records rather than minting renamed copies.
        original = {
            canonical_json({key: binding[key] for key in ("harness_ref", "capability_ref", "input_refs")}): binding
            for binding in bindings
            if binding["measure_ref"] == check.body["measure_ref"]
            and binding["purpose"] == check.body["purpose"]
        }
        if len(original) != 1:
            raise ValueError("a retained check needs its unambiguous original instrument")
        context = next(iter(original.values()))
    matches = (
        binding
        for binding in bindings
        if binding["measure_ref"] == (check.body["measure_ref"] if measure_ref is None else measure_ref)
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


def selected_measure_ref(view, assignment, field):
    """Owners select the exact result of their explicit, returned Measure call.

    Child assignments freeze this selection when they are created. Publishing a
    checker in a sibling branch does not change an existing assignment's check
    membership. A parent's next explicit Measure request can revise its result.
    """
    role = assignment.body["role"]
    if role != "designer":
        return assignment.body[field]
    purpose = "local" if field == "local_measure_ref" else "composition"
    candidates = [row.record for row in reversed(view.entries("measure"))
                  if row.status == "admitted"
                  and row.record.body["owner_assignment_ref"] == assignment.ref.as_record()]
    if not candidates:
        return assignment.body[field]
    returned = {
        row.record.invocation_id
        for row in view.entries("report")
        if row.record.body["role"] == "measure"
        and view.entry("invocation", row.record.invocation_id.value).status in {"returned", "superseded"}
    }
    for admission in candidates:
        if admission.invocation_id not in returned:
            continue
        proposal = view.read(Ref.from_record(admission.body["proposal_ref"]), "measure_proposal")
        if proposal.body["purpose"] == purpose:
            return admission.body["measure_ref"]
    return assignment.body[field]


def selected_checks(view, policy, assignment, reference, *, purpose=None):
    """Resolve immutable composite membership, or the initial fixed policy."""
    admissions = [record for record in admitted_measures(view, assignment)
                  if record.body["measure_ref"] == reference]
    if admissions:
        memberships = {canonical_json(record.body["measurement_function"])
                       for record in admissions}
        if len(memberships) != 1:
            raise ValueError("one measure identity has conflicting composite membership")
        function = RequirementMeasure.from_record(admissions[0].body["measurement_function"])
        keys = {key for row in function.requirements for key in row["check_ids"]}
        references = [ref for ref in admissions[0].body["check_refs"] if ref["artifact_id"] in keys]
    else:
        references = [raw for raw in policy["check_refs"]
                      if view.read(Ref.from_record(raw), "check").body["measure_ref"] == reference]
    scope = set(assignment.body["scope_requirement_keys"])
    return tuple(check for raw in references
                 for check in (view.read(Ref.from_record(raw), "check"),)
                 if check.body["requirement_key"] in scope
                 and (purpose is None or check.body["purpose"] == purpose))


def measure_function(view, policy, assignment, reference, *, purpose):
    """Load the admitted callable, or compose the frozen initial Builder checks.

    The initial policy is immutable too. Its requirement set includes uncovered
    requirements so that lack of a check remains visible in every scoped call.
    """
    admissions = [record for record in admitted_measures(view, assignment)
                  if record.body["measure_ref"] == reference]
    if admissions:
        bindings = {canonical_json(record.body["measurement_function"])
                    for record in admissions}
        if len(bindings) != 1:
            raise ValueError("one measure identity has conflicting callable definitions")
        for admission in admissions:
            proposal = view.read(Ref.from_record(admission.body["proposal_ref"]), "measure_proposal")
            if proposal.body["purpose"] != purpose:
                raise ValueError("a composite measure cannot change its judgment purpose")
        return RequirementMeasure.from_record(admissions[0].body["measurement_function"])
    catalog = view.data(Ref.from_record(view.contract.body["requirement_catalog_ref"]))
    checks = [view.read(Ref.from_record(raw), "check") for raw in policy["check_refs"]]
    return RequirementMeasure([{
        "requirement_id": row["requirement_key"],
        "mandatory": row["mandatory"],
        "check_ids": [check.artifact_id.value for check in checks
                      if check.body["measure_ref"] == reference
                      and check.body["purpose"] == purpose
                      and check.body["requirement_key"] == row["requirement_key"]],
    } for row in catalog["requirements"]])


def requirement_fact(view, reference, requirement_key):
    """One achievement per requirement under this exact composite definition."""
    return content_id("refinement_fact", {
        "requirement": requirement_key,
        "measure": reference,
        "environment": view.contract.body["environment_ref"],
    }).value


def measurement_lineage(view, assignment):
    """Numerical history belongs to the callable actually selected for this work."""
    from .state_machine import judgment_lineage

    return judgment_lineage({
        "role": assignment.body["role"],
        "local_measure_ref": selected_measure_ref(view, assignment, "local_measure_ref"),
    })


def measurement_baseline(view, assignment, reference):
    """A revised parent measure starts from its commissioned candidate."""
    if reference != assignment.body["local_measure_ref"]:
        for admission in admitted_measures(view, assignment):
            if admission.body["measure_ref"] == reference:
                proposal = view.read(Ref.from_record(admission.body["proposal_ref"]), "measure_proposal")
                basis = view.data(Ref.from_record(proposal.body["basis_ref"]))
                return view.read(Ref.from_record(basis["baseline_candidate_ref"]), "candidate")
        raise ValueError("revised measurement has no commissioned baseline")
    return view.read(Ref.from_record(assignment.body["baseline_candidate_ref"]), "candidate")


def measure_basis(view, policy, assignment, purpose):
    """Capture the parent's composition once, when it commissions Measure."""
    field = "local_measure_ref" if purpose == "local" else "acceptance_measure_ref"
    reference = selected_measure_ref(view, assignment, field)
    checks = selected_checks(view, policy, assignment, reference, purpose=purpose)
    available = evaluation_bindings(view, policy, assignment)
    contexts = {}
    for check in checks:
        matches = bindings_for_check(available, check, measure_ref=reference)
        if len(matches) != 1:
            raise ValueError("each retained check needs one exact execution binding")
        contexts[check.artifact_id.value] = {
            key: matches[0][key] for key in ("harness_ref", "capability_ref", "input_refs")
        }
    return {
        "owner_assignment_ref": assignment.ref.as_record(),
        "measure_ref": reference,
        "purpose": purpose,
        "requirement_keys": sorted(assignment.body["scope_requirement_keys"]),
        "check_refs": [check.ref.as_record() for check in checks],
        "check_bindings": contexts,
        "baseline_candidate_ref": view.candidate.ref.as_record(),
    }


def unit_admissions(view, attempt):
    return tuple(
        entry.record
        for entry in view.entries("measure")
        if entry.record.invocation_id == attempt.invocation_id
        and entry.record.logical_unit_id == attempt.logical_unit_id
    )


def implementation_covered_requirements(view, assignment, reference, policy):
    """Share the exact coding-check coverage between admission and planning input."""
    installed = {row.record.ref for row in view.entries("check")}
    return frozenset(
        check.body["requirement_key"]
        for check in selected_checks(view, policy, assignment, reference, purpose="local")
        if check.ref in installed and check.body["mandatory"]
        and check.body["environment_ref"] == view.contract.body["environment_ref"]
    )


def require_implementation_measure(view, assignment, reference, requirements, policy):
    """A design must name a usable coding measure before it invokes a coder."""
    covered = implementation_covered_requirements(view, assignment, reference, policy)
    if not set(requirements).issubset(covered):
        from .report_contract import requirement_address, requirement_catalog

        catalog = requirement_catalog(view)
        missing = sorted(requirement_address(catalog[key]) for key in set(requirements) - covered)
        raise ValueError(
            "implementation measure has unresolved requirement coverage: "
            f"{missing!r}. Establish those local checks, or return the unresolved "
            "need to Designer so it can commission the appropriate peer. "
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
    if ROLE_SPECIALIZATION[assignment.body["role"]] != "measure":
        raise ValueError(
            "only the assigned EstablishMeasure child proposes an instrument"
        )
    if "prerequisite_request" in attempt.body["payload"]:
        return request_prerequisite(view, attempt)
    exact(attempt.body["payload"], {"proposal"}, "measure proposal")
    proposal = proposed(view, attempt, "proposal", "measure_proposal")
    body = proposal.body
    from .measure_components import measure_owner

    if (
        body["assignment_ref"] != assignment.ref.as_record()
        or body["owner_assignment_ref"] != measure_owner(view, assignment).body["parent_assignment_ref"]
    ):
        raise ValueError("measure proposal must return to the assigning parent")
    need = resolved.references["measure_request"]
    if (
        body["purpose"] != need["purpose"]
        or not set(body["requirement_keys"]) <= set(need["requirement_keys"])
        or not set(body["requirement_keys"]).issubset(
            assignment.body["contribution_requirement_keys"]
        )
    ):
        raise ValueError("measure proposal changes the parent's requested judgment")
    from .measure_components import load_components

    load_components(view, proposal)
    # This is an indexed proposal, not installed checks, an admitted measure,
    # positive credit, or permission to execute instrument code.
    return [proposal], [
        index("measure_proposal", proposal.artifact_id.value, proposal, "proposed")
    ]
