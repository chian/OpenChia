"""Bounded parent projections over admitted records, never model summaries."""

from agent.episode_contracts import OpaqueId

from .records import Ref, RefinementRecord


def decision_context(view, reference):
    """Keep a checker gap actionable without copying its complete Run registration."""
    record = view.read(reference)
    if record.kind == "measure_prerequisite":
        from .measure_needs import decision_context as measurement_decision

        return measurement_decision(view, record)
    if record.kind != "evaluation_run" or "checking_gap" not in record.body:
        return record.as_record()
    request = view.read(Ref.from_record(record.body["request_ref"]), "evaluation")
    return {
        "record_ref": record.ref.as_record(),
        "kind": "checking_gap",
        "request_ref": request.ref.as_record(),
        "candidate_ref": record.body["candidate_ref"],
        "build_receipt_ref": record.body["build_receipt_ref"],
        "measure_ref": request.body["measure_ref"],
        "check_keys": request.body["check_keys"],
        "checking_gap": record.body["checking_gap"],
    }


def parent_report(view, invocation_id: OpaqueId) -> RefinementRecord:
    from .coordination import pending_decisions, relevant_conflicts
    from .judgment import judgment_purpose
    from .investigation import visible_findings
    from .evaluation_plan import unavailable_requests

    invocation = view.entry("invocation", invocation_id.value)
    assignment = invocation.record
    purpose = judgment_purpose(view, assignment)
    measure = assignment.body[
        "acceptance_measure_ref"
        if assignment.body["role"] in {"parts", "designer"}
        else "local_measure_ref"
    ]
    scope = set(assignment.body["scope_requirement_keys"])
    states = {entry.key: entry for entry in view.entries("check_state")}
    checks = [
        entry
        for entry in view.entries("check")
        if entry.record.body["requirement_key"] in scope
    ]
    determinations, preservation = [], []
    unresolved = set(scope)
    evidence = []
    for check in checks:
        entry = states.get(check.key)
        outcome = entry.status if entry else "not_run"
        determination = {
            "requirement_key": check.record.body["requirement_key"],
            "evidence_kind": check.record.body["evidence_kind"],
            "check_key": check.key,
            "candidate_ref": view.candidate.ref.as_record(),
            "measure_ref": check.record.body["measure_ref"],
            "environment_ref": check.record.body["environment_ref"],
            "purpose": check.record.body["purpose"],
            "outcome": outcome,
            "observation_ref": entry.record.ref.as_record() if entry else None,
        }
        determinations.append(determination)
        if entry:
            evidence.extend(entry.record.evidence_refs)
        if (
            check.record.body["requirement_key"]
            in assignment.body["preservation_requirement_keys"]
        ):
            preservation.append(determination)
    # A local pass is not independent part acceptance. Missing predicates remain
    # explicit gaps, and all mandatory checks for a requirement must agree.
    for requirement in scope:
        acceptance = [
            row
            for row in checks
            if row.record.body["requirement_key"] == requirement
            and row.record.body["purpose"] == purpose
            and row.record.body["measure_ref"] == measure
            and row.record.body["mandatory"]
        ]
        if acceptance and all(
            row.key in states and states[row.key].status == "pass" for row in acceptance
        ):
            unresolved.discard(requirement)
    conflicts = relevant_conflicts(view, assignment)
    evidence.extend(ref for conflict in conflicts for ref in conflict.evidence_refs)
    pending = pending_decisions(view, invocation_id.value)
    units = [
        entry.record
        for entry in view.entries("unit")
        if entry.record.invocation_id == invocation_id
    ]
    prerequisite_refs = [
        reference
        for unit in units[-8:]
        for reference in unit.body.get("prerequisite_assessment_refs", ())
    ]
    measure_admissions = [
        entry.record
        for entry in view.entries("measure")
        if entry.record.invocation_id == invocation_id
    ]
    for record in (
        *measure_admissions,
        *(
            view.read(Ref.from_record(ref), "prerequisite_assessment")
            for ref in prerequisite_refs
        ),
    ):
        evidence.extend(record.evidence_refs)
    latest = units[-1] if units else None
    decisions = {item.ref: item.ref.as_record() for item in pending}
    if latest is not None:
        if latest.body["decision_request_ref"] is not None:
            reference = Ref.from_record(latest.body["decision_request_ref"])
            decisions[reference] = reference.as_record()
        decisions.update({
            item.ref: item.ref.as_record()
            for item in unavailable_requests(
                view, invocation_id, latest.logical_unit_id
            )
        })
    termination = latest.body["disposition"] if latest else "continuing"
    if pending:
        termination = "needs_parent_decision"
    lessons = [
        entry.record
        for entry in view.entries("lesson")
        if entry.status == "active"
        and set(entry.record.body["requirement_keys"]).intersection(scope)
    ]
    candidate_ids = {view.candidate.artifact_id.value}
    for unit in units[-8:]:
        candidate_ids.add(unit.body["candidate_before_ref"]["artifact_id"])
        candidate_ids.add(unit.body["candidate_after_ref"]["artifact_id"])
    latest_commit = (
        view.read(view.head["latest_commit_id"]).ref
        if view.head["latest_commit_id"]
        else view.contract.ref
    )
    # The index cursor allows focused retrieval of the complete history. The
    # original observation references survive every parent boundary unchanged.
    return RefinementRecord(
        "parent_report",
        view.campaign_id,
        {
            "assignment_ref": assignment.ref.as_record(),
            "invocation_id": invocation_id.value,
            "role": assignment.body["role"],
            "scope_requirement_keys": sorted(scope),
            "selected_candidate_ref": view.candidate.ref.as_record(),
            "examined_candidate_refs": [
                view.read(key).ref.as_record() for key in sorted(candidate_ids)
            ],
            "measure_refs": [
                assignment.body["local_measure_ref"],
                assignment.body["acceptance_measure_ref"],
            ],
            "measure_proposal_refs": [
                entry.record.ref.as_record()
                for entry in view.entries("measure_proposal")
                if entry.record.body["assignment_ref"] == assignment.ref.as_record()
            ],
            "measure_admission_refs": [
                record.ref.as_record() for record in measure_admissions
            ],
            "source_admission_refs": [
                entry.record.ref.as_record()
                for entry in view.entries("evaluation_source")
                if entry.record.invocation_id == invocation_id
            ],
            "determinations": determinations,
            "investigation_findings": list(visible_findings(view, assignment)),
            "assessment_refs": [
                reference
                for unit in units[-8:]
                for reference in unit.body.get("assessment_refs", ())
            ],
            "prerequisite_assessment_refs": prerequisite_refs,
            "preservation_findings": preservation,
            "relevant_attempt_refs": [
                item.predecessor_refs[0].as_record() for item in units[-8:]
            ],
            "lesson_refs": [item.ref.as_record() for item in lessons],
            "unresolved_requirement_keys": sorted(unresolved),
            "decision_request_refs": list(decisions.values()),
            "child_report_refs": [
                row.record.ref.as_record()
                for row in view.entries("report")
                if view.read(
                    Ref.from_record(row.record.body["assignment_ref"]), "assignment"
                ).body["parent_assignment_ref"]
                == assignment.ref.as_record()
                and view.entry("invocation", row.record.invocation_id.value).status
                == "returned"
            ][-8:],
            "conflict_refs": [item.ref.as_record() for item in conflicts],
            "termination": termination,
            "continuation_ref": latest.body["continuation_ref"] if latest else None,
            "complete_index_ref": latest_commit.as_record(),
        },
        view.contract.producer_ref,
        tuple(dict.fromkeys(evidence)),
        (latest_commit,),
        invocation_id,
    )
