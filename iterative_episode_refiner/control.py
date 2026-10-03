"""Host role attainment and numerical control from shared measurement history."""

from agent.duet_contracts import content_id
from function_library.refinement_control import BOUNDED_RAREFACTION, resolve_selection
from numeric_control_library import MARGINAL_DOMINATED_HYPERVOLUME
from numeric_control_library.continuation import continuation_function_library
from numeric_control_library.controller import ComposedIncidenceController
from numeric_control_library.credit_assignment import (
    CreditObservation,
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
    from .judgment import current_check_states, judgment_purpose
    from .measures import authorized_check_refs

    installed = {
        entry.record.artifact_id.value: entry.record for entry in view.entries("check")
    }
    states = {key: status for key, (_, status) in current_check_states(view).items()}
    role = assignment.body["role"]
    investigation = role in {"support", "question"}
    if investigation:
        from .investigation import findings, needs

        assigned = {
            item["need"]["need_key"] for item in needs(view, policy, assignment)
        }
        resolved = {
            item["need_key"] for item in findings(view, assignment) if item["resolved"]
        }
        if not assigned or assigned != resolved:
            return False
    admitted_measure = False
    if role == "measure":
        admitted = [
            entry.record
            for entry in view.entries("measure")
            if entry.status == "admitted"
            and view.read(
                Ref.from_record(entry.record.body["proposal_ref"]), "measure_proposal"
            ).body["assignment_ref"]
            == assignment.ref.as_record()
        ]
        admitted_measure = bool(admitted) and assignment.body[
            "local_measure_ref"
        ] == policy.get("measure_admission", {}).get("adequacy_measure_ref")
    measure = (
        assignment.body["acceptance_measure_ref"]
        if role in {"parts", "designer"}
        else assignment.body["local_measure_ref"]
    )
    purpose = judgment_purpose(view, assignment)
    required = []
    requirements = set(assignment.body["contribution_requirement_keys"])
    covered = set()
    for ref in authorized_check_refs(view, policy, assignment):
        # Interpret the frozen check even before installation to decide whether
        # it is part of THIS role's measure. An unrelated missing check must not
        # keep an otherwise attained child alive indefinitely.
        check = view.read(ref, "check")
        if (
            check.body["measure_ref"] != measure
            or check.body["purpose"] != purpose
            or check.body["requirement_key"] not in requirements
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
    acceptable = {"pass", "fail"} if role == "verify" or investigation else {"pass"}
    if any(states.get(check.artifact_id.value) not in acceptable for check in required):
        return False
    if any(
        states.get(guard) not in acceptable
        for check in required
        for guard in check.body["guard_keys"]
    ):
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
    if role == "parts" and assignment.body["parent_assignment_ref"] is None:
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
    lessons = [
        entry
        for entry in view.entries("lesson")
        if entry.status == "active"
        and entry.record.invocation_id == attempt.invocation_id
        and entry.record.logical_unit_id == attempt.logical_unit_id
    ]
    measures = [
        item
        for item in unit_admissions(view, attempt)
        if item.body["status"] == "admitted"
    ]
    usable = bool(lessons or measures or prerequisites) or any(
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


def numerical_decision(view, assignment, policy, observation_keys, *, usable):
    from .succession import judgment_history

    selection = policy["numeric_control"]
    rarefaction = _numeric_selection(
        rarefaction_function_library, selection["rarefaction"]
    )
    continuation = _numeric_selection(
        continuation_function_library, selection["continuation"]
    )
    bounded = resolve_selection(policy["opportunity_function"], BOUNDED_RAREFACTION)
    remaining = None

    def estimate(state, parameters):
        if remaining is None:
            return rarefaction.load()(state, parameters)
        return bounded(state, parameters, remaining_opportunities=remaining)

    controller = ComposedIncidenceController(
        epoch="refinement-v1",
        schema=ResultColumnSchema((CHANNEL,), (0.0,)),
        credit_function=MARGINAL_DOMINATED_HYPERVOLUME,
        rarefaction_function=BOUNDED_RAREFACTION,
        continuation_function=continuation,
        credit_parameters={},
        rarefaction_parameters=selection["rarefaction"]["arguments"],
        continuation_parameters=selection["continuation"]["arguments"],
        credit_factory=MARGINAL_DOMINATED_HYPERVOLUME.load(),
        rarefaction_implementation=estimate,
        continuation_implementation=continuation.load(),
    )
    # Succession retains actual observations. Equivalent criterion keys are
    # projected into the successor, never counted as a fresh successful unit.
    lineages = judgment_history(view, assignment)
    history = []
    for entry in view.entries("unit"):
        prior_assignment = view.read(
            Ref.from_record(entry.record.body["assignment_ref"]), "assignment"
        )
        mapping = lineages.get(prior_assignment.body["judgment_lineage"])
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
        "attained": role_attained,
        "observation_keys": sorted(observation_keys) if usable else [],
        "usable_observation": usable,
        "stop": step.stop,
        "numeric_control": selection,
        "opportunity_function": policy["opportunity_function"],
    }
