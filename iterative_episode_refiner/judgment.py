"""Parent-local judgments over a returned verifier's original observations.

A report routes evidence; it is neither an oracle nor a scalar contribution.
These assessments are committed with the parent's ordinary unit receipt. They
do not execute checks, impersonate a Run, or overwrite the child's observations.
"""

from agent.duet_contracts import canonical_json, content_id
from episode_runtime.testing.judgments import judge_value

from .records import Ref
from .state_machine import derived


def judgment_purpose(view, assignment):
    """Verification inherits its parent's judgment, never a first-check default."""
    role = assignment.body["role"]
    if role == "verify":
        parent = view.read(
            Ref.from_record(assignment.body["parent_assignment_ref"]), "assignment"
        )
        if parent.body["role"] not in {"parts", "designer"}:
            raise ValueError("independent verification needs a Parts or Designer owner")
        role = parent.body["role"]
    return {
        "parts": "composition",
        "designer": "acceptance",
        "implementer": "local",
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


def _sources(view, attempt, assignment):
    from .measurement import dependency_hashes

    purpose = {"parts": "composition", "designer": "acceptance"}[
        assignment.body["role"]
    ]
    states = {entry.key: entry for entry in view.entries("check_state")}
    for report in returned_children(view, attempt, assignment, {"verify"}):
        for determination in report.body["determinations"]:
            reference = determination["observation_ref"]
            if reference is None:
                continue
            observation = view.read(Ref.from_record(reference), "observation")
            check = view.entry("check", observation.body["check_key"]).record
            state = states.get(check.artifact_id.value)
            if (
                observation.invocation_id != report.invocation_id
                or check.body["purpose"] != purpose
                or check.body["measure_ref"]
                != assignment.body["acceptance_measure_ref"]
                or state is None
                or state.record.ref != observation.ref
                or state.status
                not in {"pass", "fail", "inconclusive", "error", "blocked"}
                or dependency_hashes(check, view.candidate)
                != dict(observation.body["checked_dependency_hashes"])
            ):
                continue
            yield report, check, observation


def _compatible(view, policy, check, source_check, observation):
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
        binding["measure_ref"] == check.body["measure_ref"]
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
        )
    )


def parent_assessments(view, attempt, assignment):
    """Re-evaluate the parent's frozen criterion; never read child credit."""
    from .measurement import dependency_hashes
    from .measures import authorized_check_refs

    if assignment.body["role"] not in {"parts", "designer"}:
        return ()
    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    authorized = set(authorized_check_refs(view, policy, assignment))
    sources = tuple(_sources(view, attempt, assignment))
    assessments = []
    for entry in view.entries("check"):
        check = entry.record
        if (
            check.ref not in authorized
            or check.body["measure_ref"] != assignment.body["local_measure_ref"]
            or check.body["requirement_key"]
            not in assignment.body["contribution_requirement_keys"]
        ):
            continue
        matches = [
            (report, observation)
            for report, source_check, observation in sources
            if _compatible(view, policy, check, source_check, observation)
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
    if check.body["evidence_kind"] == "execution":
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


def operative_check_facts(view, assignment, assessments=()):
    """Project each role's own evidence; repair success and inquiry differ.

    Used independently at unit close, numerical control and publication. The
    caller awarding credit additionally requires evidence from its own unit.
    """
    from .materialization import satisfied_requirements
    from .measurement import check_fact
    from .measures import authorized_check_refs

    if assignment.body["role"] in {"support", "question"}:
        from .investigation import findings

        return {
            item["fact_key"]: (
                view.read(Ref.from_record(item["observation_ref"]), "observation"),
            )
            for item in findings(view, assignment)
            if item["resolved"]
        }
    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    authorized = set(authorized_check_refs(view, policy, assignment))
    states = current_check_states(view, assessments)
    verification = assignment.body["role"] == "verify"
    acceptable = {"pass", "fail"} if verification else {"pass"}
    static_satisfied = (
        set() if verification else satisfied_requirements(view, assignment, assessments)
    )
    purpose = judgment_purpose(view, assignment)
    # Parent-local judgments can use a different purpose from acceptance. They
    # are still exact, independently re-derived assessments, not child scores.
    facts = {}
    for key, (record, status) in states.items():
        check = view.entry("check", key).record
        if (
            check.ref not in authorized
            or check.body["measure_ref"] != assignment.body["local_measure_ref"]
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
            if record.kind != "observation":
                continue
            request = view.read(
                Ref.from_record(record.body["request_ref"]), "evaluation"
            )
            fact = verification_fact(view, check, status, request)
        else:
            if (
                check.body["evidence_kind"] == "materialization"
                and check.body["requirement_key"] not in static_satisfied
            ):
                continue
            fact = check_fact(view, check)
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
