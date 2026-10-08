"""Host role attainment and numerical control from shared measurement history."""

from agent.duet_contracts import content_id
from function_library.refinement_control import BOUNDED_RAREFACTION, resolve_selection
from function_library.refinement_contract import ROLE_SPECIALIZATION
from numeric_control_library import MARGINAL_DOMINATED_HYPERVOLUME
from numeric_control_library.continuation import continuation_function_library
from numeric_control_library.controller import ComposedIncidenceController
from numeric_control_library.credit_assignment import (
    CreditObservation,
    CreditSnapshot,
    MarginalHypervolumeAssignment,
    ResultColumnSchema,
)
from numeric_control_library.rarefaction import rarefaction_function_library

from .records import Ref


CHANNEL = content_id("channel", "refinement-admitted-progress-v1").value


def _numeric_selection(library, selection):
    function = library.resolve(f"{selection['library']}.{selection['function_id']}")
    if (
        function.definition_id != selection["definition_id"]
        or function.interface != selection["interface"]
    ):
        raise ValueError("numerical definition differs from the approved contract")
    function.admit_arguments(selection["arguments"])
    return function


def attained(view, assignment, policy):
    """No omitted, stale or unformalized requirement can silently become green."""
    from .coordination import pending_decisions, relevant_conflicts
    from .judgment import current_check_states, judgment_purpose, measure_result
    from .measures import selected_checks, selected_measure_ref

    installed = {
        entry.record.artifact_id.value: entry.record for entry in view.entries("check")
    }
    states = {key: status for key, (_, status) in current_check_states(view).items()}
    role = assignment.body["role"]
    family = ROLE_SPECIALIZATION[role]
    investigation = role in {"support", "question"}
    if investigation:
        from .investigation import findings
        from .measure_design import assigned_definition

        if assigned_definition(view, assignment) is not None:
            # Research may inform an independent review; only the admitted review
            # satisfies that commission (unit_review owns its ordinary return).
            return False
        resolved = {
            item["requirement_key"] for item in findings(view, assignment) if item["resolved"]
        }
        invocations = [entry.key for entry in view.entries("invocation")
                       if entry.record.ref == assignment.ref]
        if len(invocations) != 1:
            raise ValueError("research attainment has no unique admitted invocation")
        return (
            set(assignment.body["contribution_requirement_keys"]) <= resolved
            and not pending_decisions(view, invocations[0])
        )
    admitted_measure = False
    if family == "measure":
        admitted = [
            entry.record
            for entry in view.entries("measure")
            if (entry.status == "admitted" if role == "measure" else
                entry.status == "partial" and all(row["status"] == "pass"
                    for row in entry.record.body["requirement_results"]))
            and view.read(
                Ref.from_record(entry.record.body["proposal_ref"]), "measure_proposal"
            ).body["assignment_ref"]
            == assignment.ref.as_record()
        ]
        admitted_measure = bool(admitted) and assignment.body[
            "local_measure_ref"
        ] == policy.get("measure_admission", {}).get("adequacy_measure_ref")
    measure = selected_measure_ref(view, assignment,
        "acceptance_measure_ref"
        if role == "designer"
        else "local_measure_ref"
    )
    purpose = judgment_purpose(view, assignment)
    required = []
    requirements = set(assignment.body["contribution_requirement_keys"])
    covered = set()
    for check in selected_checks(view, policy, assignment, measure, purpose=purpose):
        # Interpret the frozen check even before installation to decide whether
        # it is part of THIS role's measure. An unrelated missing check must not
        # keep an otherwise attained child alive indefinitely.
        ref = check.ref
        if (
            check.body["requirement_key"] not in requirements
            or not check.body["mandatory"]
        ):
            continue
        check = installed.get(ref.artifact_id.value)
        if check is None:
            # The exact policy's check cannot be interpreted from a missing
            # proposal. Missing checks are unresolved, not optional successes.
            return False
        if check.ref != ref:
            raise ValueError("installed check differs from frozen policy")
        covered.add(check.body["requirement_key"])
        required.append(check)
    if not admitted_measure and (covered != requirements or not required):
        return False
    acceptable = {"pass", "fail"} if family == "verify" or investigation else {"pass"}
    if any(states.get(check.artifact_id.value) not in acceptable for check in required):
        return False
    if any(
        states.get(guard) not in acceptable
        for check in required
        for guard in check.body["guard_keys"]
    ):
        return False
    if family in {"designer", "implementer", "materialization_implementer"} and not measure_result(
        view, assignment, reference=measure, purpose=purpose
    )["attained"]:
        return False
    invocations = [
        entry
        for entry in view.entries("invocation")
        if entry.record.ref == assignment.ref
    ]
    if len(invocations) != 1:
        raise ValueError("attainment has no unique admitted invocation")
    invocation = invocations[0]
    if pending_decisions(view, invocation.key) or any(
        item.body["state"] == "decision_required"
        and item.body["scope_owner_invocation_id"] == invocation.key
        for item in relevant_conflicts(view, assignment)
    ):
        return False
    if role == "designer" and assignment.body["parent_assignment_ref"] is None:
        from .readiness import root_readiness

        return not root_readiness(view, assignment, policy)["gaps"]
    return True


def observation_inputs(view, attempt, assignment, assessments=None, prerequisites=None):
    from .materialization import baseline_fact_keys
    from .judgment import operative_check_facts, parent_assessments
    from .measures import unit_admissions
    from .prerequisites import parent_prerequisites

    if assessments is None:
        assessments = parent_assessments(view, attempt, assignment)
    if prerequisites is None:
        prerequisites = parent_prerequisites(view, attempt, assignment)
    observations = [
        entry.record
        for entry in view.entries("observation")
        if entry.record.logical_unit_id == attempt.logical_unit_id
        and entry.record.invocation_id == attempt.invocation_id
    ]
    research = [
        entry.record
        for entry in view.entries("research_finding")
        if entry.record.logical_unit_id == attempt.logical_unit_id
        and entry.record.invocation_id == attempt.invocation_id
        and entry.record.evidence_refs
    ]
    lessons = [
        entry
        for entry in view.entries("lesson")
        if entry.status == "active"
        and entry.record.invocation_id == attempt.invocation_id
        and entry.record.logical_unit_id == attempt.logical_unit_id
    ]
    measures = unit_admissions(view, attempt)
    measured_instrument = any(
        item.body["status"] == "admitted"
        or any(row["status"] in {"pass", "fail", "error"} for row in item.body["control_results"])
        for item in measures
    )
    usable = bool(lessons or prerequisites or measured_instrument or research) or any(
        item.body["outcome"] in {"pass", "fail"}
        for item in (*observations, *assessments)
    )
    keys = (
        set(operative_check_facts(view, assignment, assessments))
        | {key for entry in lessons for key in entry.record.body["fact_keys"]}
        | {key for measure in measures for key in measure.body["fact_keys"]}
        | {key for item in prerequisites for key in item.body["fact_keys"]}
    )
    keys -= baseline_fact_keys(view, assignment)
    return keys if usable else set(), usable


def _controller(policy, remaining, *, snapshot=None):
    selection = policy["numeric_control"]
    rarefaction = _numeric_selection(
        rarefaction_function_library, selection["rarefaction"]
    )
    continuation = _numeric_selection(
        continuation_function_library, selection["continuation"]
    )
    bounded = resolve_selection(policy["opportunity_function"], BOUNDED_RAREFACTION)
    def estimate(state, parameters):
        value = remaining()
        if value is None:
            return rarefaction.load()(state, parameters)
        return bounded(state, parameters, remaining_opportunities=value)

    return ComposedIncidenceController(
        epoch="refinement-v1",
        schema=ResultColumnSchema((CHANNEL,), (0.0,)),
        credit_function=MARGINAL_DOMINATED_HYPERVOLUME,
        rarefaction_function=BOUNDED_RAREFACTION,
        continuation_function=continuation,
        credit_parameters={},
        rarefaction_parameters=selection["rarefaction"]["arguments"],
        continuation_parameters=selection["continuation"]["arguments"],
        credit_factory=MARGINAL_DOMINATED_HYPERVOLUME.load() if snapshot is None else lambda schema, parameters: MarginalHypervolumeAssignment.from_snapshot(schema, snapshot),
        rarefaction_implementation=estimate,
        continuation_implementation=continuation.load(),
    )


def numerical_decision(view, assignment, policy, observation_keys, *, usable):
    from .succession import judgment_history

    remaining = None
    controller = _controller(policy, lambda: remaining)
    # Same-function succession retains its observations. A commissioned revision
    # has a new baseline and never reinterprets an old function's yield history.
    lineages = judgment_history(view, assignment)
    history = []
    for entry in view.entries("unit"):
        mapping = lineages.get(entry.record.body["judgment_lineage"])
        if mapping is not None:
            history.append((entry.record, mapping))
    for receipt, mapping in history:
        decision = view.read(
            Ref.from_record(receipt.body["continuation_ref"]), "continuation"
        )
        remaining = decision.body["remaining_opportunities"]
        factory = (
            CreditObservation.observed
            if decision.body["usable_observation"]
            else CreditObservation.failed
        )
        controller.observe(
            receipt.artifact_id.value,
            factory(
                {
                    CHANNEL: sorted({
                        mapping.get(key, key)
                        for key in decision.body["observation_keys"]
                    })
                },
                code="observed"
                if decision.body["usable_observation"]
                else "acquisition_failed",
            ),
            is_root=True,
        )
    role_attained = attained(view, assignment, policy)
    previous_remaining = remaining
    remaining = 0 if role_attained else None
    factory = CreditObservation.observed if usable else CreditObservation.failed
    step = controller.observe(
        "current-unit",
        factory(
            {CHANNEL: sorted(observation_keys) if usable else ()},
            code="observed" if usable else "acquisition_failed",
        ),
        is_root=True,
    )
    return {
        "numeric_step": step.as_record(),
        "remaining_opportunities": remaining,
        "prior_remaining_opportunities": previous_remaining,
        "attained": role_attained,
        "observation_keys": sorted(observation_keys) if usable else [],
        "usable_observation": usable,
        "stop": step.stop,
        "numeric_control": policy["numeric_control"],
        "opportunity_function": policy["opportunity_function"],
    }


def recompute_numerical_step(decision):
    """Re-evaluate one committed decision from its exact sufficient statistics."""
    if "prior_remaining_opportunities" not in decision:
        raise ValueError("This historical decision lacks its prior opportunity bound; it cannot be replayed exactly.")
    for name in ("remaining_opportunities", "prior_remaining_opportunities"):
        value = decision[name]
        if value is not None and (type(value) is not int or value != 0):
            raise ValueError("Recorded opportunity bound must be unknown or a host-proven zero.")
    before = CreditSnapshot.from_record(decision["numeric_step"]["admission"]["before"])
    remaining = decision["prior_remaining_opportunities"]
    controller = _controller(decision, lambda: remaining, snapshot=before)
    remaining = decision["remaining_opportunities"]
    factory = CreditObservation.observed if decision["usable_observation"] else CreditObservation.failed
    return controller.observe(
        "recorded-unit",
        factory({CHANNEL: tuple(decision["observation_keys"])}, code="observed" if decision["usable_observation"] else "acquisition_failed"),
        is_root=True,
    ).as_record()
