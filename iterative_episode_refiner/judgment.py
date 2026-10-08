"""Parent-local judgments over a returned verifier's original observations.

A report routes evidence; it is neither an oracle nor a scalar contribution.
These assessments are committed with the parent's ordinary unit receipt. They
do not execute checks, impersonate a Run, or overwrite the child's observations.
"""

from agent.duet_contracts import canonical_json, content_id
from episode_runtime.testing_harness.judgments import judge_value
from function_library.refinement_contract import ROLE_SPECIALIZATION

from .records import Ref
from .state_machine import derived


def judgment_purpose(view, assignment):
    """Verification inherits its parent's judgment, never a first-check default."""
    role = ROLE_SPECIALIZATION[assignment.body["role"]]
    if role == "verify":
        parent = assignment
        while ROLE_SPECIALIZATION[parent.body["role"]] == "verify":
            parent = view.read(Ref.from_record(parent.body["parent_assignment_ref"]), "assignment")
        if parent.body["role"] != "designer":
            raise ValueError("independent verification needs a Designer commission")
        role = "designer"
    return {
        "designer": "composition",
        "implementer": "local",
        "materialization_implementer": "local",
        "measure": "adequacy",
        "support": "support",
        "question": "question",
    }[role]


def returned_children(view, attempt, assignment, roles):
    """Only direct children actually called and returned in this parent unit."""
    children = set()
    for row in view.connection.execute(
        "SELECT attempt_id FROM refinement_operations WHERE campaign_id = ? "
        "AND invocation_id = ? AND logical_unit_id = ? AND commit_id IS NOT NULL "
        "ORDER BY rowid",
        (
            view.campaign_id.value,
            attempt.invocation_id.value,
            attempt.logical_unit_id.value,
        ),
    ):
        operation = view.read(row[0], "attempt")
        if operation.body["action"] == "enter_child":
            children.add(operation.body["payload"]["invocation_id"])
    for entry in view.entries("report"):
        report = entry.record
        if report.invocation_id.value not in children:
            continue
        child = view.entry("invocation", report.invocation_id.value)
        if (
            child.status == "returned"
            and child.record.body["role"] in roles
            and report.body["role"] == child.record.body["role"]
            and child.record.body["parent_assignment_ref"] == assignment.ref.as_record()
            and report.body["assignment_ref"] == child.record.ref.as_record()
        ):
            yield report


def returned_observation(view, observation, assignment):
    """An original observation reaches its parent through returned same-role work."""
    current = view.entry("invocation", observation.invocation_id.value)
    family = ROLE_SPECIALIZATION[assignment.body["role"]]
    while current.record.ref != assignment.ref:
        if (current.status not in {"returned", "superseded"}
                or ROLE_SPECIALIZATION[current.record.body["role"]] != family
                or current.record.body["parent_assignment_ref"] is None):
            return False
        parent = view.read(Ref.from_record(current.record.body["parent_assignment_ref"]), "assignment")
        parents = [row for row in view.entries("invocation") if row.record.ref == parent.ref]
        if len(parents) != 1:
            return False
        current = parents[0]
    return True


def _sources(view, attempt, assignment):
    from .measurement import dependency_hashes
    from .measures import selected_checks, selected_measure_ref

    family = ROLE_SPECIALIZATION[assignment.body["role"]]
    states = {entry.key: entry for entry in view.entries("check_state")}
    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    routes = ({
        "verify": ("acceptance_measure_ref", judgment_purpose(view, assignment)),
        "implementer": ("local_measure_ref", "local"),
        "materialization_implementer": ("local_measure_ref", "local"),
    } if family == "designer" else {
        role: ("local_measure_ref", judgment_purpose(view, assignment))
        for role, specialization in ROLE_SPECIALIZATION.items()
        if specialization == family and role != family
    })
    for report in returned_children(view, attempt, assignment, set(routes)):
        field, purpose = routes[report.body["role"]]
        measure = selected_measure_ref(view, assignment, field)
        members = {check.ref for check in selected_checks(view, policy, assignment, measure, purpose=purpose)}
        for determination in report.body["determinations"]:
            reference = determination["observation_ref"]
            if reference is None:
                continue
            observation = view.read(Ref.from_record(reference), "observation")
            check = view.entry("check", observation.body["check_key"]).record
            state = states.get(check.artifact_id.value)
            if (
                not returned_observation(view, observation,
                    view.read(Ref.from_record(report.body["assignment_ref"]), "assignment"))
                or check.body["purpose"] != purpose
                or check.ref not in members
                or state is None
                or state.record.ref != observation.ref
                or state.status
                not in {"pass", "fail", "inconclusive", "error", "blocked"}
                or dependency_hashes(check, view.candidate)
                != dict(observation.body["checked_dependency_hashes"])
            ):
                continue
            yield report, check, observation


def _compatible(view, policy, check, source_check, observation, measure_ref):
    from .measures import bindings_for_check, evaluation_bindings

    # Equal JSON paths in different instruments do not denote equal evidence.
    # The parent must already authorize this exact instrument/input context.
    for field in (
        "requirement_key",
        "evidence_kind",
        "environment_ref",
        "dependency_paths",
        "observation_path",
    ):
        if check.body[field] != source_check.body[field]:
            return False
    if check.body["evidence_kind"] == "materialization":
        return all(
            check.body[field] == source_check.body[field]
            for field in ("predicate_ref", "expected")
        )
    request = view.read(Ref.from_record(observation.body["request_ref"]), "evaluation")
    return any(
        binding["measure_ref"] == measure_ref
        and binding["purpose"] == check.body["purpose"]
        and all(
            canonical_json(binding[field]) == canonical_json(request.body[field])
            for field in ("harness_ref", "capability_ref", "input_refs")
        )
        for binding in bindings_for_check(
            evaluation_bindings(
                view,
                policy,
                view.entry("invocation", observation.invocation_id.value).record,
            ),
            check,
            measure_ref=measure_ref,
        )
    )


def parent_assessments(view, attempt, assignment):
    """Re-evaluate the parent's frozen criterion; never read child credit."""
    from .measurement import dependency_hashes
    from .measures import selected_checks, selected_measure_ref

    family = ROLE_SPECIALIZATION[assignment.body["role"]]
    if family not in {"designer", "implementer", "materialization_implementer", "verify"}:
        return ()
    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    measure = selected_measure_ref(view, assignment, "local_measure_ref")
    purpose = "local" if family == "designer" else judgment_purpose(view, assignment)
    checks = selected_checks(view, policy, assignment, measure, purpose=purpose)
    sources = tuple(_sources(view, attempt, assignment))
    assessments = []
    for check in checks:
        if (
            check.body["requirement_key"]
            not in assignment.body["contribution_requirement_keys"]
        ):
            continue
        matches = [
            (report, observation)
            for report, source_check, observation in sources
            if _compatible(view, policy, check, source_check, observation, measure)
        ]
        if not matches:
            continue
        observations = {item.artifact_id.value: item for _, item in matches}
        values = {
            canonical_json(item.body["observed_value"])
            for item in observations.values()
        }
        outcomes = {item.body["outcome"] for item in observations.values()}
        # Disagreement or a failed acquisition is not a favorable determination.
        outcome = "inconclusive"
        if len(values) == 1 and outcomes <= {"pass", "fail", "inconclusive"}:
            original = next(iter(observations.values()))
            if check.body["evidence_kind"] == "materialization":
                outcome = (
                    original.body["outcome"] if len(outcomes) == 1 else "inconclusive"
                )
            else:
                predicate = view.data(Ref.from_record(check.body["predicate_ref"]))
                outcome = judge_value(
                    predicate,
                    observed=original.body["observed_value"],
                    expected=check.body["expected"],
                )
        if outcome not in {"pass", "fail", "inconclusive"}:
            raise ValueError("parent predicate returned an invalid determination")
        reports = {report.artifact_id.value: report for report, _ in matches}
        assessments.append(
            derived(
                view,
                attempt,
                "parent_assessment",
                {
                    "assignment_ref": assignment.ref.as_record(),
                    "check_key": check.artifact_id.value,
                    "candidate_ref": view.candidate.ref.as_record(),
                    "checked_dependency_hashes": dependency_hashes(
                        check, view.candidate
                    ),
                    "source_report_refs": [
                        reports[key].ref.as_record() for key in sorted(reports)
                    ],
                    "source_observation_refs": [
                        observations[key].ref.as_record()
                        for key in sorted(observations)
                    ],
                    "outcome": outcome,
                },
                evidence=tuple(
                    dict.fromkeys(
                        ref
                        for key in sorted(observations)
                        for ref in observations[key].evidence_refs
                    )
                ),
            )
        )
    return tuple(assessments)


def current_check_states(view, assessments=()):
    """A judgment projection, not replacement of the shared observation index."""
    from .measurement import dependency_hashes

    checks = {entry.key: entry.record for entry in view.entries("check")}
    states = {
        entry.key: (entry.record, entry.status)
        for entry in view.entries("check_state")
        if dependency_hashes(checks[entry.key], view.candidate)
        == dict(entry.record.body["checked_dependency_hashes"])
    }
    for assessment in assessments:
        key = assessment.body["check_key"]
        if dependency_hashes(checks[key], view.candidate) == dict(
            assessment.body["checked_dependency_hashes"]
        ):
            states[key] = (assessment, assessment.body["outcome"])
    return states


def verification_fact(view, check, outcome, request=None):
    """A supported determination, not a reward for a failed repair attempt.

    Wrong output variants, source revisions and repeated Runs do not create new
    evidence classes. The exact criterion and instrument inputs do. Static check
    determinations stay distinct from the enclosing all-check repair milestone.
    """
    if outcome not in {"pass", "fail"}:
        raise ValueError("verification progress needs a decisive determination")
    context = None
    if check.body["evidence_kind"] in {"execution", "checking_program"}:
        if request is None:
            raise ValueError("runtime determination needs its admitted instrument")
        from .evaluation_inputs import instrument_context

        context = instrument_context(view, request.body)
    return content_id(
        "verification_fact",
        {
            **{
                field: check.body[field]
                for field in (
                    "requirement_key",
                    "evidence_kind",
                    "predicate_ref",
                    "expected",
                    "environment_ref",
                    "dependency_paths",
                    "observation_path",
                )
            },
            "instrument": context,
            "outcome": outcome,
        },
    ).value


def measure_result(view, assignment, *, reference, purpose, assessments=(), requirement_keys=None):
    """Apply the fixed composition to evidence valid for the current candidate.

    Checks retain their individual outcomes. Guard failures and unresolved or
    contradicted evidence prevent a pass from becoming requirement attainment.
    """
    from .measures import measure_function, selected_checks

    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    function = measure_function(view, policy, assignment, reference, purpose=purpose)
    states = current_check_states(view, assessments)
    observations = []
    for check in selected_checks(view, policy, assignment, reference, purpose=purpose):
        state = states.get(check.artifact_id.value)
        if state is None or not state[0].evidence_refs:
            continue
        record, status = state
        if status not in {"pass", "fail", "blocked", "error"}:
            status = "not_checked"
        if status == "pass" and any(
            guard not in states or states[guard][1] != "pass"
            or not states[guard][0].evidence_refs
            for guard in check.body["guard_keys"]
        ):
            status = "blocked"
        observations.append({
            "check_id": check.artifact_id.value,
            "candidate_ref": view.candidate.ref.as_record(),
            "status": status,
        })
    return function(
        observations=observations,
        candidate_ref=view.candidate.ref.as_record(),
        requirement_ids=(assignment.body["contribution_requirement_keys"]
                         if requirement_keys is None else requirement_keys),
    )


def operative_check_facts(view, assignment, assessments=()):
    """Project each role's own evidence; repair success and inquiry differ.

    Used independently at unit close, numerical control and publication. The
    caller awarding credit additionally requires evidence from its own unit.
    """
    from .measures import requirement_fact, selected_checks, selected_measure_ref

    if assignment.body["role"] in {"support", "question"}:
        from .investigation import finding_record, findings

        return {
            item["fact_key"]: (finding_record(view, item),)
            for item in findings(view, assignment)
            if item["resolved"]
        }
    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    measure = selected_measure_ref(view, assignment, "local_measure_ref")
    authorized = {check.ref for check in selected_checks(view, policy, assignment, measure)}
    states = current_check_states(view, assessments)
    family = ROLE_SPECIALIZATION[assignment.body["role"]]
    verification = family == "verify"
    acceptable = {"pass", "fail"} if verification else {"pass"}
    if family in {"designer", "implementer", "materialization_implementer"}:
        result = measure_result(view, assignment, reference=measure, purpose="local",
                                assessments=assessments)
        return {
            requirement_fact(view, measure, requirement): tuple(
                record for key, (record, status) in states.items()
                if view.entry("check", key).record.ref in authorized
                and view.entry("check", key).record.body["purpose"] == "local"
                and view.entry("check", key).record.body["requirement_key"] == requirement
                and status == "pass" and record.evidence_refs
            )
            for requirement in result["current_satisfied_requirement_ids"]
        }
    purpose = judgment_purpose(view, assignment)
    # Parent-local judgments can use a different purpose from acceptance. They
    # are still exact, independently re-derived assessments, not child scores.
    facts = {}
    for key, (record, status) in states.items():
        check = view.entry("check", key).record
        if (
            check.ref not in authorized
            or check.body["requirement_key"]
            not in assignment.body["contribution_requirement_keys"]
            or status not in acceptable
            or not record.evidence_refs
        ):
            continue
        if record.kind != "parent_assessment" and check.body["purpose"] != purpose:
            continue
        if any(
            guard not in states or states[guard][1] not in acceptable
            for guard in check.body["guard_keys"]
        ):
            continue
        if verification:
            source = record
            if record.kind == "parent_assessment":
                source = view.read(Ref.from_record(record.body["source_observation_refs"][0]), "observation")
            elif record.kind != "observation":
                continue
            request = view.read(
                Ref.from_record(source.body["request_ref"]), "evaluation"
            )
            fact = verification_fact(view, check, status, request)
        else:
            fact = requirement_fact(view, measure, check.body["requirement_key"])
        facts.setdefault(fact, []).append(record)
    return {key: tuple(records) for key, records in facts.items()}


def assessment_status(view, assessment):
    """Historical assessments are not current merely because they are stored."""
    from .measurement import dependency_hashes

    check = view.entry("check", assessment.body["check_key"]).record
    if dependency_hashes(check, view.candidate) != dict(
        assessment.body["checked_dependency_hashes"]
    ):
        return "stale"
    states = {entry.key: entry for entry in view.entries("check_state")}
    for ref in assessment.body["source_observation_refs"]:
        observation = view.read(Ref.from_record(ref), "observation")
        state = states.get(observation.body["check_key"])
        if (
            state is None
            or state.record.ref != observation.ref
            or state.status not in {"pass", "fail", "inconclusive"}
        ):
            return "stale"
    return assessment.body["outcome"]
