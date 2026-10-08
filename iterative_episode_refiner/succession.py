"""Parent-owned replacement of returned assignments and their judgment history.

The existing assignment/commit records carry succession. Nothing here restarts a
Run, changes an active criterion, or creates another persistence/replay path.
"""

from agent.duet_contracts import canonical_json
from function_library.refinement_contract import ROLE_SPECIALIZATION

from .evaluation_inputs import instrument_context
from .measures import (
    admitted_measures,
    bindings_for_check,
    evaluation_bindings,
    measurement_lineage,
    selected_checks,
    selected_measure_ref,
)
from .records import Ref


def _checks(view, policy, assignment, measure):
    return selected_checks(view, policy, assignment, measure)


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


def _instruments(view, policy, assignment, check, measure):
    if check.body["evidence_kind"] == "materialization":
        return frozenset()
    return frozenset(
        canonical_json(instrument_context(view, binding))
        for binding in bindings_for_check(
            evaluation_bindings(view, policy, assignment), check, measure_ref=measure
        )
    )


def _preserved_instruments(view, policy, assignment, check, measure):
    """A returned, admitted checker may replace its exact construction baseline.

    This is successor-assignment authority, not equivalence for progress credit.
    The new checker still has its own source-sensitive evidence and fact identity.
    """
    from .instrument_return import admitted_return

    preserved = set(_instruments(view, policy, assignment, check, measure))
    for entry in view.entries("measure"):
        admission = entry.record
        if (entry.status not in {"partial", "admitted"}
                or admission.body["measure_ref"] != check.body["measure_ref"]
                or check.ref.as_record() not in admission.body["check_refs"]):
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
            evaluation_bindings(view, policy, assignment), check, measure_ref=measure
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
    before_ref = selected_measure_ref(view, prior, field)
    if before_ref == successor.body[field]:
        return
    before = _checks(view, policy, prior, before_ref)
    after = _checks(view, policy, successor, successor.body[field])
    # The parent's explicitly commissioned Measure may correct a faulty check.
    # Its immutable basis identifies exactly which requirements it revised;
    # unrelated obligations retain their checks and instruments.
    revised = set()
    for admission in admitted_measures(view, successor):
        if (admission.body["measure_ref"] != successor.body[field]
                or admission.body["owner_assignment_ref"] != successor.body["parent_assignment_ref"]):
            continue
        proposal = view.read(Ref.from_record(admission.body["proposal_ref"]), "measure_proposal")
        basis = view.data(Ref.from_record(proposal.body["basis_ref"]))
        if basis["measure_ref"] == before_ref:
            revised.update(row["requirement_key"] for row in admission.body["requirement_results"])
    for check in before:
        if not check.body["mandatory"]:
            continue
        if check.body["requirement_key"] in revised and any(
            item.body["mandatory"] and item.body["requirement_key"] == check.body["requirement_key"]
            and item.body["purpose"] == check.body["purpose"] for item in after
        ):
            continue
        matches = [item for item in after if _criterion(item) == _criterion(check)]
        instruments = _instruments(view, policy, prior, check, before_ref)
        if not any(
            instruments <= _preserved_instruments(view, policy, successor, item, successor.body[field])
            for item in matches
        ):
            raise ValueError(
                "successor measure changes an obligation outside its parent's explicit Measure revision"
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
            selected_measure_ref(view, prior, field) != successor.body[field]
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
            or prior.record.body["coordinating_invocation_id"]
            != successor.body["coordinating_invocation_id"]
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
        ROLE_SPECIALIZATION[assignment.body["role"]] == "measure"
        and adequacy is not None
        and assignment.body["local_measure_ref"] != adequacy
    ):
        raise ValueError(
            "Measure and Measure Parts must use measure_admission_policy.adequacy_measure_ref "
            "as its local_measure_ref; the Target Workflow's implementation measure "
            "cannot judge check design. Correct the child assignment before calling it."
        )
    review = assigned_definition(view, assignment)
    for field in ("local_measure_ref", "acceptance_measure_ref"):
        measure = assignment.body[field]
        view.data(Ref.from_record(measure))
        if assignment.body["role"] in {"question", "support"}:
            parent = view.read(Ref.from_record(assignment.body["parent_assignment_ref"]), "assignment")
            if measure != selected_measure_ref(view, parent, field):
                raise ValueError("research leaves retain their parent's measurement authority")
            # Their own progress is scoped evidence-backed research coverage.
            # A missing executable target check is often why they were called.
            continue
        if (
            (ROLE_SPECIALIZATION[assignment.body["role"]] == "measure" or review is not None)
            and field == "local_measure_ref"
            and measure == adequacy
        ):
            continue
        if not selected_checks(view, policy, assignment, measure):
            raise ValueError(
                "assignment measure has no authorized checks in its inherited catalog"
            )


def judgment_history(view, assignment):
    """Reuse same-function history; an explicitly revised function is rebaselined.

    Historical receipts remain available for inspection. Their old numerical
    observations cannot be reinterpreted as samples from a different measure.
    """
    return {measurement_lineage(view, assignment): {}}


def credited_facts(view, assignment):
    return frozenset(
        mapping.get(key, key)
        for lineage, mapping in judgment_history(view, assignment).items()
        for key in view.credited(lineage)
    )
