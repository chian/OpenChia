"""Durable evidence reports with a separate caller-requested model projection."""

from agent.episode_contracts import OpaqueId
from agent.duet_store import DuetNotFoundError
from episode_runtime.records.outcomes import RequirementOutcome

from .records import Ref, RefinementRecord


def check_result(view, check, state):
    """Project an existing observation without rejudging or rebinding its candidate."""
    if state is None:
        return None
    observation = state.record
    body = observation.as_record()["body"]
    if (
        observation.kind != "observation"
        or body["check_key"] != check.artifact_id.value
    ):
        raise ValueError("check result requires its exact recorded observation")
    request = view.read(Ref.from_record(body["request_ref"]), "evaluation")
    criterion = check.as_record()["body"]
    experiment_ref, experiment_id, prediction = None, None, None
    if criterion["evidence_kind"] == "execution":
        try:
            binding = view.entry("evaluation_run", request.artifact_id.value).record
        except DuetNotFoundError:
            binding = None
        if binding is not None:
            experiment_ref = binding.body.get("experiment_ref")
        if experiment_ref is not None:
            from episode_runtime.testing_harness.contracts import ExperimentSpec

            experiment = view.data(Ref.from_record(experiment_ref))
            experiment_id = ExperimentSpec.from_record(experiment["spec"]).experiment_id
            prediction = next(
                (
                    row
                    for row in experiment["spec"]["requirements"]
                    if row["requirement_ref"] == check.ref.as_record()
                ),
                None,
            )
    result = RequirementOutcome(
        requirement_ref=dict(view.contract.body["requirement_catalog_ref"]),
        requirement_key=criterion["requirement_key"],
        measure_ref=criterion["measure_ref"],
        predicted=None if prediction is None else prediction["expected"],
        falsifying=None if prediction is None else prediction["falsifying"],
        status=body["outcome"],
        observed=body["observed_value"],
        criterion_expected=criterion["expected"],
        evidence_ref=observation.ref.as_record(),
        reason=None,
        limitations=(
            []
            if prediction is not None
            else [
                "No separate prediction or falsifying statement was recorded for this evaluation."
            ]
        )
        + [
            "This observation does not grant parent acceptance or progress credit; current applicability is reported separately.",
        ],
    )
    return {
        "candidate_ref": request.as_record()["body"]["candidate_ref"],
        "request_ref": request.ref.as_record(),
        "criterion_ref": check.ref.as_record(),
        "execution_ref": body["execution_ref"],
        "experiment_ref": experiment_ref,
        "experiment_id": experiment_id,
        "local_host_queries": None
        if experiment_id is None
        else {
            "results": {"experiment_id": experiment_id},
            "history": {"kind": "experiments", "experiment_id": experiment_id},
            "inventory": {
                "source": {"kind": "experiment", "experiment_id": experiment_id},
                "query": {},
            },
            "access": "Local host inspection only; these links do not grant a refiner child another invocation's experiment access.",
        },
        "outcome": result.model_dump(mode="json"),
        "counterexample_refs": body["counterexample_refs"],
        "limitation_refs": body["limitation_refs"],
    }
def report_overview(record):
    """Deliver the caller's stored projection, never expand its audit record."""
    return record.as_record()["body"]["return_value"]


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
            "test_result": check_result(view, check.record, entry),
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
    body = {
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
        }
    from .report_contract import project_return

    body["return_value"] = project_return(view, assignment, body)
    return RefinementRecord(
        "parent_report",
        view.campaign_id,
        body,
        view.contract.producer_ref,
        tuple(dict.fromkeys(evidence)),
        (latest_commit,),
        invocation_id,
    )
