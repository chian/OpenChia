"""Independent assertions at campaign publication, before any operative write."""

import json

from agent.duet_contracts import canonical_json, digest_record
from agent.duet_store import DuetConflictError
from function_library.epistemic_contract import exact

from .records import Ref


def validate_commit(view, commit):
    from .materialization import baseline_fact_keys
    from .judgment import operative_check_facts, parent_assessments
    from .prerequisites import parent_prerequisites
    from .succession import credited_facts
    from .measure_controls import validated_control_facts

    if commit.kind != "commit" or commit.body["sequence"] != view.head["sequence"] + 1:
        raise ValueError("campaign commit skips its predecessor")
    predecessor = commit.body["previous_commit_ref"]
    actual = (
        view.read(view.head["latest_commit_id"]).ref.as_record()
        if view.head["latest_commit_id"]
        else None
    )
    if predecessor != actual:
        raise DuetConflictError("campaign commit has a stale predecessor")
    attempt = view.read(Ref.from_record(commit.body["attempt_ref"]), "attempt")
    receipts, credits = [], []
    touched = set()
    for delta in commit.body["deltas"]:
        kind = delta["kind"]
        if kind == "head":
            exact(delta, {"kind", "before", "after"}, "candidate delta")
            if delta["before"] != view.head["candidate_id"] or "head" in touched:
                raise DuetConflictError("candidate delta is stale or repeated")
            touched.add("head")
            candidate = view.read(delta["after"], "candidate")
            if (
                Ref.from_record(candidate.body["parent_candidate_ref"])
                != view.candidate.ref
            ):
                raise ValueError("candidate delta lacks its exact parent")
        elif kind == "index":
            exact(
                delta,
                {"kind", "collection", "key", "record_id", "status"},
                "index delta",
            )
            key = (delta["collection"], delta["key"])
            if key in touched:
                raise ValueError("one transaction cannot overwrite an index twice")
            touched.add(key)
            record = view.read(delta["record_id"])
            if delta["collection"] in {"measure_definition", "measure_review"}:
                from .measure_design import propose

                records, expected_deltas = propose(view, attempt)
                if attempt.body["action"] != "propose_measure" or record.ref != records[0].ref or delta != expected_deltas[0]:
                    raise ValueError("check design or review differs from its authorized proposal")
            if delta["collection"] == "measure_need":
                from .measure_needs import request_prerequisite, return_prerequisite

                derive = (
                    return_prerequisite
                    if "return_prerequisite_ref" in attempt.body["payload"]
                    else request_prerequisite
                )
                expected_records, expected_deltas = derive(view, attempt)
                if (
                    attempt.body["action"] != "propose_measure"
                    or record.ref != expected_records[0].ref
                    or delta != expected_deltas[0]
                ):
                    raise ValueError(
                        "measurement prerequisite differs from authorized need"
                    )
            if delta["collection"] == "measure" and delta["status"] == "admitted":
                from .measure_admission import validate_admission

                validate_admission(view, record)
            if delta["collection"] == "unit":
                if (
                    record.kind != "unit_receipt"
                    or record.invocation_id != attempt.invocation_id
                    or record.logical_unit_id != attempt.logical_unit_id
                ):
                    raise ValueError("unit receipt has another attempt's provenance")
                receipts.append(record)
        elif kind == "credit":
            exact(
                delta,
                {"kind", "lineage", "key", "record_id", "receipt_id"},
                "credit delta",
            )
            credits.append(delta)
        else:
            raise ValueError("unknown campaign delta")
    if credits and (len(receipts) != 1 or attempt.body["action"] != "close_unit"):
        raise ValueError("only a committed unit close may award progress")
    for receipt in receipts:
        assignment = view.read(
            Ref.from_record(receipt.body["assignment_ref"]), "assignment"
        )
        lineage = assignment.body["judgment_lineage"]
        assessments = parent_assessments(view, attempt, assignment)
        if list(receipt.body.get("assessment_refs", ())) != [
            item.ref.as_record() for item in assessments
        ]:
            raise ValueError(
                "parent assessments differ from the independently derived evidence projection"
            )
        for assessment in assessments:
            view.read(assessment.ref, "parent_assessment")
        prerequisites = parent_prerequisites(view, attempt, assignment)
        if list(receipt.body.get("prerequisite_assessment_refs", ())) != [
            item.ref.as_record() for item in prerequisites
        ]:
            raise ValueError(
                "parent prerequisite decisions differ from their original admitted evidence"
            )
        for assessment in prerequisites:
            view.read(assessment.ref, "prerequisite_assessment")
        _validate_continuation(view, attempt, assignment, receipt)
        known = credited_facts(view, assignment)
        baseline_keys = baseline_fact_keys(view, assignment)
        check_facts = operative_check_facts(view, assignment, assessments)
        for key, observation in validated_control_facts(
            view, assignment_ref=assignment.ref
        ).items():
            check_facts[key] = (*check_facts.get(key, ()), observation)
        for assessment in prerequisites:
            for key in assessment.body["fact_keys"]:
                check_facts[key] = (*check_facts.get(key, ()), assessment)
        keys = [delta["key"] for delta in credits]
        if len(set(keys)) != len(keys) or set(keys).intersection(known | baseline_keys):
            raise ValueError("equivalent progress cannot earn credit twice")
        if sorted(keys) != list(receipt.body["semantic_fact_keys"]):
            raise ValueError("measurement differs from its admitted fact set")
        for name, expected in (
            ("credit_before", len(known)),
            ("credit_after", len(known) + len(keys)),
            ("realized_yield", len(keys)),
        ):
            if type(receipt.body[name]) is not int or receipt.body[name] != expected:
                raise ValueError(
                    "credit is not independently derived from campaign history"
                )
        for delta in credits:
            if (
                delta["receipt_id"] != receipt.artifact_id.value
                or delta["lineage"] != lineage
            ):
                raise ValueError("credit does not belong to this judgment")
            fact = view.read(delta["record_id"])
            if (
                not fact.evidence_refs
                or fact.invocation_id != attempt.invocation_id
                or fact.logical_unit_id != attempt.logical_unit_id
            ):
                raise ValueError("credit requires this unit's committed evidence")
            if fact.kind in {
                "observation",
                "parent_assessment",
                "prerequisite_assessment",
                "measure_control_observation",
            }:
                if not any(
                    record.ref == fact.ref
                    for record in check_facts.get(delta["key"], ())
                ):
                    raise ValueError(
                        "credit requires this role's operative evidence under its frozen measure and guards"
                    )
            elif fact.kind == "lesson":
                operative = view.entry("lesson", fact.artifact_id.value)
                if (
                    operative.record.ref != fact.ref
                    or operative.status != "active"
                    or delta["key"] not in fact.body["fact_keys"]
                ):
                    raise ValueError(
                        "credit requires newly admitted operative learning"
                    )
            elif fact.kind == "measure_admission":
                from .measure_admission import validate_admission

                operative = view.entry("measure", fact.artifact_id.value)
                if (
                    operative.status != "admitted"
                    or delta["key"] not in fact.body["fact_keys"]
                ):
                    raise ValueError("unadmitted instruments cannot earn progress")
                validate_admission(view, fact)
            else:
                raise ValueError("patches, failures and narration do not earn credit")


def _validate_continuation(view, attempt, assignment, receipt):
    from .control import numerical_decision, observation_inputs
    from .coordination import pending_decisions
    from .evaluation_admission import source_decision
    from .evaluation_plan import unavailable_request
    from .measures import admission_decision
    from .measure_needs import unit_prerequisite
    from .measure_design import unit_review

    policy_ref = Ref.from_record(view.contract.body["policy_bundle_ref"])
    row = view.connection.execute(
        "SELECT record_json FROM artifacts WHERE artifact_id = ?",
        (policy_ref.artifact_id.value,),
    ).fetchone()
    policy = json.loads(row[0])
    if digest_record(policy) != policy_ref.content_hash:
        raise ValueError("frozen control policy content changed")
    decision = view.read(
        Ref.from_record(receipt.body["continuation_ref"]), "continuation"
    )
    keys, usable = observation_inputs(view, attempt, assignment)
    expected = numerical_decision(view, assignment, policy, keys, usable=usable)
    if (
        decision.invocation_id != attempt.invocation_id
        or decision.logical_unit_id != attempt.logical_unit_id
        or canonical_json(decision.body) != canonical_json(expected)
    ):
        raise ValueError(
            "continuation is not independently derived from admitted history"
        )
    disposition = "continuing"
    conflicts = pending_decisions(view, attempt.invocation_id.value)
    request = (
        source_decision(view, attempt)
        or admission_decision(view, attempt)
        or unit_prerequisite(view, attempt)
        or unit_review(view, attempt)
        or unavailable_request(view, attempt)
    )
    decision_request = conflicts[0] if conflicts else request
    if decision_request is not None:
        disposition = "needs_parent_decision"
    elif expected["stop"]:
        disposition = (
            "attained" if expected["attained"] else "yield_exhausted_unresolved"
        )
    if receipt.body["disposition"] != disposition:
        raise ValueError(
            "receipt disposition differs from host continuation/coordination"
        )
    expected_ref = (
        decision_request.ref.as_record() if decision_request is not None else None
    )
    if receipt.body["decision_request_ref"] != expected_ref:
        raise ValueError(
            "unit return must retain the original host-derived decision request"
        )
