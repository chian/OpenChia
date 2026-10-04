"""Parent-owned replacement of returned assignments and their judgment history.

The existing assignment/commit records carry succession. Nothing here restarts a
Run, changes an active criterion, or creates another persistence/replay path.
"""

from agent.duet_contracts import canonical_json

from .evaluation_inputs import instrument_context
from .measures import (
    admitted_measures,
    authorized_check_refs,
    bindings_for_check,
    evaluation_bindings,
)
from .records import Ref


def predecessors(view, assignment):
    pending = list(assignment.body["supersedes_assignment_refs"])
    result = {}
    while pending:
        prior = view.read(Ref.from_record(pending.pop()), "assignment")
        if prior.ref in result:
            continue
        result[prior.ref] = prior
        pending.extend(prior.body["supersedes_assignment_refs"])
    return tuple(result.values())


def _checks(view, policy, assignment, measure):
    return tuple(
        check
        for ref in authorized_check_refs(view, policy, assignment)
        for check in (view.read(ref, "check"),)
        if check.body["measure_ref"] == measure
        and check.body["requirement_key"] in assignment.body["scope_requirement_keys"]
    )


def _criterion(check):
    # Record/measure identities and new evidence citations are not new criteria.
    # Guard identities remain exact; a claim of guard equivalence is not authority.
    return canonical_json({
        field: check.body[field]
        for field in (
            "requirement_key",
            "purpose",
            "evidence_kind",
            "predicate_ref",
            "expected",
            "environment_ref",
            "dependency_paths",
            "observation_path",
            "guard_keys",
            "mandatory",
        )
    })


def _instruments(view, policy, assignment, check):
    if check.body["evidence_kind"] == "materialization":
        return frozenset()
    return frozenset(
        canonical_json(instrument_context(view, binding))
        for binding in bindings_for_check(
            evaluation_bindings(view, policy, assignment), check
        )
    )


def _preserved_instruments(view, policy, assignment, check):
    """A returned, admitted checker may replace its exact construction baseline.

    This is successor-assignment authority, not equivalence for progress credit.
    The new checker still has its own source-sensitive evidence and fact identity.
    """
    from .instrument_return import admitted_return

    preserved = set(_instruments(view, policy, assignment, check))
    for admission in admitted_measures(view, assignment):
        if admission.body["measure_ref"] != check.body["measure_ref"]:
            continue
        proposal = view.read(
            Ref.from_record(admission.body["proposal_ref"]), "measure_proposal"
        )
        constructed = admitted_return(view, proposal)
        if constructed is None:
            continue
        original_by_revision = {
            Ref.from_record(revised): original
            for original, revised in constructed[1].items()
        }
        for binding in bindings_for_check(
            evaluation_bindings(view, policy, assignment), check
        ):
            original = original_by_revision.get(Ref.from_record(binding["harness_ref"]))
            if original is not None:
                preserved.add(
                    canonical_json(
                        instrument_context(
                            view, {**binding, "harness_ref": original.as_record()}
                        )
                    )
                )
    return frozenset(preserved)


def _preserve_measure(view, policy, prior, successor, field):
    if prior.body[field] == successor.body[field]:
        return
    before = _checks(view, policy, prior, prior.body[field])
    after = _checks(view, policy, successor, successor.body[field])
    for check in before:
        if not check.body["mandatory"]:
            continue
        matches = [item for item in after if _criterion(item) == _criterion(check)]
        instruments = _instruments(view, policy, prior, check)
        if not any(
            instruments <= _preserved_instruments(view, policy, successor, item)
            for item in matches
        ):
            raise ValueError(
                "successor measure removes or changes an established mandatory check, guard, or instrument"
            )


def validate_replacements(view, attempt, parent, successor, policy):
    """Only the assigning parent may replace its fully returned direct children."""
    refs = [
        Ref.from_record(ref) for ref in successor.body["supersedes_assignment_refs"]
    ]
    if len(set(refs)) != len(refs):
        raise ValueError("successor cannot name a predecessor twice")
    # Changing the measure for the same assigned work cannot evade history by
    # calling the replacement a fresh child. Same-measure repeat invocations
    # already share their numerical lineage and need not supersede each other.
    for entry in reversed(view.entries("invocation")):
        prior = entry.record
        if (
            entry.status != "returned"
            or prior.body["parent_assignment_ref"] != parent.ref.as_record()
            or prior.body["role"] != successor.body["role"]
            or any(
                set(prior.body[field]) != set(successor.body[field])
                for field in ("contribution_requirement_keys", "owned_slice_keys")
            )
        ):
            continue
        if prior.ref not in refs and any(
            prior.body[field] != successor.body[field]
            for field in ("local_measure_ref", "acceptance_measure_ref")
        ):
            raise ValueError(
                "a changed measure for this work must explicitly replace its returned assignment"
            )
        break
    replacements = []
    for ref in refs:
        prior = view.entry("assignment", ref.artifact_id.value)
        if (
            prior.record.ref != ref
            or prior.status == "superseded"
            or prior.record.body["parent_assignment_ref"] != parent.ref.as_record()
            or prior.record.body["owning_parts_invocation_id"]
            != successor.body["owning_parts_invocation_id"]
        ):
            raise ValueError(
                "replacement must name this parent's current direct assignment"
            )
        previous = prior.record
        if (
            previous.body["role"] != successor.body["role"]
            and attempt.body["action"] != "coordinate_conflict"
        ):
            raise ValueError("ordinary succession retains the assigned role")
        for field in (
            "scope_requirement_keys",
            "contribution_requirement_keys",
            "preservation_requirement_keys",
            "owned_slice_keys",
            "protected_paths",
        ):
            if not set(previous.body[field]).issubset(successor.body[field]):
                raise ValueError(f"successor drops predecessor {field}")
        if previous.body["authority_ref"] != successor.body["authority_ref"]:
            raise ValueError("succession cannot replace approval authority")
        invocations = [
            entry for entry in view.entries("invocation") if entry.record.ref == ref
        ]
        if len(invocations) != 1 or invocations[0].status != "returned":
            raise ValueError("predecessor must return before its parent replaces it")
        if not any(
            row.record.invocation_id.value == invocations[0].key
            for row in view.entries("report")
        ):
            raise ValueError(
                "replacement requires the predecessor's committed parent report"
            )
        for field in ("local_measure_ref", "acceptance_measure_ref"):
            _preserve_measure(view, policy, previous, successor, field)
        replacements.append((previous, invocations[0].key))
    return tuple(replacements)


def require_measures(view, policy, assignment):
    """A successor may use its inherited admitted catalog, never an arbitrary ID."""
    from .measure_design import assigned_definition

    adequacy = policy.get("measure_admission", {}).get("adequacy_measure_ref")
    if (
        assignment.body["role"] == "measure"
        and adequacy is not None
        and assignment.body["local_measure_ref"] != adequacy
    ):
        raise ValueError(
            "EstablishMeasure must use measure_admission_policy.adequacy_measure_ref "
            "as its local_measure_ref; the Target Workflow's implementation measure "
            "cannot judge check design. Correct the child assignment before calling it."
        )
    review = assigned_definition(view, assignment)
    checks = tuple(
        view.read(ref, "check")
        for ref in authorized_check_refs(view, policy, assignment)
    )
    for field in ("local_measure_ref", "acceptance_measure_ref"):
        measure = assignment.body[field]
        view.data(Ref.from_record(measure))
        if (
            (assignment.body["role"] == "measure" or review is not None)
            and field == "local_measure_ref"
            and measure == adequacy
        ):
            continue
        if not any(check.body["measure_ref"] == measure for check in checks):
            raise ValueError(
                "assignment measure has no authorized checks in its inherited catalog"
            )


def judgment_history(view, assignment):
    """Map equivalent predecessor facts into this frozen judgment's key space."""
    from .measurement import check_fact

    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    current = _checks(view, policy, assignment, assignment.body["local_measure_ref"])
    signatures = {}
    for check in current:
        signature = (_criterion(check), _instruments(view, policy, assignment, check))
        signatures[signature] = check_fact(view, check)
    lineages = {assignment.body["judgment_lineage"]: {}}
    for prior in predecessors(view, assignment):
        if prior.body["role"] != assignment.body["role"]:
            continue  # A different role's score is not this role's history.
        lineage = prior.body["judgment_lineage"]
        mapping = lineages.setdefault(lineage, {})
        for check in _checks(view, policy, prior, prior.body["local_measure_ref"]):
            signature = (_criterion(check), _instruments(view, policy, prior, check))
            if signature in signatures:
                mapping[check_fact(view, check)] = signatures[signature]
    return lineages


def credited_facts(view, assignment):
    return frozenset(
        mapping.get(key, key)
        for lineage, mapping in judgment_history(view, assignment).items()
        for key in view.credited(lineage)
    )
