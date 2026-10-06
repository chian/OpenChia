"""Parent-declared return projections over the Episode's recorded measurements.

The declaration names the decision and measurements the caller needs. Evidence
identities stay in the durable report; this module does not score, stop, or admit
work. It is also used for the root's explicitly declared return to Duet.
"""

from collections import Counter
from collections.abc import Mapping

from agent.duet_contracts import canonical_json
from function_library.epistemic_contract import exact, names
from function_library.models import _thaw_json

from .records import Ref


RETURN_SHAPE = {
    "decision": "the decision this child result must help its parent make",
    "measurements": [{
        "name": "a descriptive heading for this measurement, not an identifier",
        "purpose": "local, acceptance, composition, adequacy, question, or support",
        "requirements": ["requirement addresses from the assigned scope"],
    }],
    "include": [
        "select needed sections: candidate_changes, investigation_findings, "
        "measurement_findings, environment_findings, check_review, open_decisions"
    ],
}

SECTIONS = frozenset({
    "candidate_changes", "investigation_findings", "measurement_findings",
    "check_review", "open_decisions", "environment_findings",
})
PURPOSES = frozenset({"local", "acceptance", "composition", "adequacy", "question", "support"})


def requirement_address(row):
    """Use the actual specification location, rather than aliasing a hash."""
    target = row["source_target"]
    if row["evidence_scope"] == "contract_coverage":
        field = row["field"].replace("~", "~0").replace("/", "~1")
        target += "/" + field
        if row["field"] == "repeatable_call":
            call = row["approved_value"]
            target += "/" + call["caller_local_id"] + "/" + call["slot_name"]
    return target


def requirement_catalog(view):
    rows = view.data(Ref.from_record(view.contract.body["requirement_catalog_ref"]))["requirements"]
    addresses = [requirement_address(row) for row in rows]
    if len(addresses) != len(set(addresses)):
        raise ValueError("requirement locations are ambiguous in this specification")
    return {row["requirement_key"]: row for row in rows}


def validate_return_contract(value, requirements):
    """Validate the parent's declaration without supplying missing decisions."""
    value = _thaw_json(value)
    exact(value, {"decision", "measurements", "include"}, "parent return contract")
    names([value["decision"]], "parent decision", nonempty=True)
    included = names(value["include"], "return sections")
    if not set(included) <= SECTIONS:
        raise ValueError("return contract selects an unknown information section")
    if not isinstance(value["measurements"], list):
        raise ValueError("return measurements must be an array")
    headings = []
    for item in value["measurements"]:
        exact(item, {"name", "purpose", "requirements"}, "return measurement")
        names([item["name"]], "measurement heading", nonempty=True)
        headings.append(item["name"])
        if item["purpose"] not in PURPOSES:
            raise ValueError("return measurement has an unknown judgment purpose")
        selected = names(item["requirements"], "reported requirements", nonempty=True)
        if not set(selected) <= set(requirements):
            raise ValueError("return measurement expands the child's requirement scope")
    if len(headings) != len(set(headings)):
        raise ValueError("return measurement headings must be distinct")
    if not headings and not included:
        raise ValueError("parent must specify the information its child returns")
    return value


def assigned_return_contract(view, assignment):
    catalog = requirement_catalog(view)
    scope = [requirement_address(catalog[key]) for key in assignment.body["scope_requirement_keys"]]
    return validate_return_contract(
        view.data(Ref.from_record(assignment.body["return_projection_ref"])), scope
    )


def _unique(values):
    return list({canonical_json(value): value for value in values}.values())


def _limitations(view, references):
    return _unique(view.data(Ref.from_record(ref)) for ref in references)


def _check_outcome(view, row):
    """Preserve distinctions and scalar observations, not execution transcripts."""
    result = {"status": row["outcome"], "applicable": False}
    check = view.read(row["check_key"], "check")
    predicate = view.data(Ref.from_record(check.body["predicate_ref"]))
    result["criterion"] = predicate["function_id"]
    expected = check.body["expected"]
    if isinstance(expected, (int, float, bool, str)) or expected is None:
        result["expected"] = expected
    test = row["test_result"]
    if test is None:
        return result
    from .measurement import dependency_hashes

    observation = view.read(Ref.from_record(row["observation_ref"]), "observation")
    result["observation_path"] = check.body["observation_path"]
    result["applicable"] = (
        dependency_hashes(check, view.candidate) == dict(observation.body["checked_dependency_hashes"])
        and row["outcome"] not in {"stale", "contradicted"}
    )
    # Admission already projected the observed value. Applying observation_path
    # a second time loses ordinary scalar results and masks that error as null.
    original = test["outcome"]["observed"]
    if isinstance(original, (int, float, bool, str)) or original is None:
        result["value"] = original
    else:
        result["observation"] = "structured evidence retained in the stored check result"
    if isinstance(original, Mapping) and "diagnostics" in original:
        result["diagnostics"] = [
            {key: diagnostic[key] for key in ("code", "detail", "blocking", "field_path") if key in diagnostic}
            for diagnostic in original["diagnostics"]
        ]
    result["limitations"] = _unique([
        *test["outcome"]["limitations"],
        *_limitations(view, test["limitation_refs"]),
    ])
    if test["counterexample_refs"]:
        result["counterexamples"] = _limitations(view, test["counterexample_refs"])
    return result


def _measurement(view, assignment, body, declaration, catalog):
    purpose = declaration["purpose"]
    measure = assignment.body[
        "acceptance_measure_ref" if purpose in {"acceptance", "composition"} else "local_measure_ref"
    ]
    selected = set(declaration["requirements"])
    rows = [
        row for row in body["determinations"]
        if row["purpose"] == purpose and row["measure_ref"] == measure
        and requirement_address(catalog[row["requirement_key"]]) in selected
    ]
    counts = Counter(row["outcome"] for row in rows)
    applicable = Counter(
        row["outcome"] for row in rows if _check_outcome(view, row)["applicable"]
    )
    covered = {requirement_address(catalog[row["requirement_key"]]) for row in rows}
    outcomes = {}
    for address in declaration["requirements"]:
        relevant = [row for row in rows if requirement_address(catalog[row["requirement_key"]]) == address]
        outcomes[address] = _unique(_check_outcome(view, row) for row in relevant) or [{"status": "not_measured"}]
    from .measurement import dependency_hashes

    entry = view.entry("assignment", assignment.artifact_id.value)
    baseline = view.read(Ref.from_record(assignment.body["baseline_candidate_ref"]), "candidate")
    previous = {}
    for observation in view.entries("observation"):
        key = observation.record.body["check_key"]
        if observation.sequence < entry.sequence:
            previous[key] = observation.record
    changes = []
    for row in rows:
        current = _check_outcome(view, row)
        check = view.read(row["check_key"], "check")
        prior = previous.get(row["check_key"])
        comparable = prior is not None and (
            dict(prior.body["checked_dependency_hashes"]) == dependency_hashes(check, baseline)
        )
        before = {"status": prior.body["outcome"]} if comparable else {"status": "not_measured"}
        if comparable and isinstance(prior.body["observed_value"], (int, float, bool, str)):
            before["value"] = prior.body["observed_value"]
        after = {key: current[key] for key in ("status", "value") if key in current}
        if current["applicable"] and before != after:
            changes.append({
                "requirement": requirement_address(catalog[row["requirement_key"]]),
                "observation_path": check.body["observation_path"],
                "before": before, "after": after,
            })
    return {
        "purpose": purpose,
        "recorded_status_counts": dict(sorted(counts.items())),
        "applicable_status_counts": dict(sorted(applicable.items())),
        "unmeasured_requirements": sorted(selected - covered),
        "outcomes": outcomes,
        "changes_since_assignment": _unique(changes),
    }


def _candidate_changes(view, assignment, body, catalog):
    before = view.read(Ref.from_record(assignment.body["baseline_candidate_ref"]), "candidate")
    after = view.read(Ref.from_record(body["selected_candidate_ref"]), "candidate")
    paths = set(before.body["files"]) | set(after.body["files"])
    return {
        "changed_files": sorted(path for path in paths if before.body["files"].get(path) != after.body["files"].get(path)),
        "materialization_changed": before.body["materialization_ref"] != after.body["materialization_ref"],
        "comparison": "candidate at assignment entry versus candidate at return",
    }


def _measurement_findings(view, assignment, body, catalog):
    result = []
    for reference in body["measure_admission_refs"]:
        admission = view.read(Ref.from_record(reference), "measure_admission")
        proposal = view.read(Ref.from_record(admission.body["proposal_ref"]), "measure_proposal")
        controls = admission.body["control_results"]
        result.append({
            "purpose": proposal.body["purpose"],
            "requirements": [requirement_address(catalog[key]) for key in proposal.body["requirement_keys"]],
            "status": admission.body["status"],
            "reason": admission.body["reason"],
            "controls": {"total": len(controls), "matched": sum(row["expected"] == row["observed"] for row in controls)},
            "limitations": _limitations(view, proposal.body["limitation_refs"]),
        })
    return result


def _environment_findings(view, assignment, body, catalog):
    from .candidate_environment import findings

    # Parent communication contains requested findings and actionable paths.
    # Exact candidate/ledger/log identities remain in the child's audit record.
    own = [{key: row[key] for key in (
        "recipe_path", "subject", "status", "diagnostics", "resolved_distributions", "meaning",
    ) if key in row} for row in findings(view, invocation_id=body["invocation_id"])]
    children = [item for reference in body["child_report_refs"]
                for report in (view.read(Ref.from_record(reference), "parent_report"),)
                for item in report.body["return_value"].get("environment_findings", ())]
    return _unique([*own, *children])


def _check_reviews(view, assignment, body, catalog):
    own = [
        {key: _thaw_json(row.record.body[key]) for key in ("criteria", "counterexamples", "limitations")}
        for row in view.entries("measure_review")
        if row.record.body["assignment_ref"] == assignment.ref.as_record()
    ]
    children = [
        review
        for reference in body["child_report_refs"]
        for report in (view.read(Ref.from_record(reference), "parent_report"),)
        for review in report.body["return_value"].get("check_review", ())
    ]
    return _unique([*own, *children])


def _investigation_findings(view, assignment, body, catalog):
    return [
        {
            "requirement": requirement_address(catalog[row["requirement_key"]]),
            "state": row["state"], "resolved": row["resolved"],
            "decision": view.data(Ref.from_record(row["decision_ref"])),
            "target": view.data(Ref.from_record(row["target_ref"])),
            "applicability": view.data(Ref.from_record(row["applicability_ref"])),
            "limitations": _limitations(view, row["limitation_refs"]),
        }
        for row in body["investigation_findings"]
    ]


def _decision_need(view, record, catalog):
    need = record.body["need"]
    return [{"assignment_prerequisite": True,
             "kind": need["kind"], "purpose": need["purpose"],
             "requirements": [requirement_address(catalog[key]) for key in need["requirement_keys"]]}]


def _decision_evaluation(view, record, catalog):
    return [{"kind": gap["kind"], "detail": gap["detail"],
             "requirements": [requirement_address(catalog[key]) for key in gap["requirement_keys"]]}
            for gap in record.body["availability"]["gaps"]]


def _decision_run(view, record, catalog):
    gap = record.body["checking_gap"]
    return [{"kind": gap["kind"], "detail": gap["detail"]}]


def _decision_conflict(view, record, catalog):
    return [{"kind": record.body["kind"], "state": record.body["state"],
             "requirements": [requirement_address(catalog[key]) for key in record.body["requirement_keys"]]}]


def _decision_review(view, record, catalog):
    failed = [key for key, value in record.body["criteria"].items() if not value["satisfied"]]
    return [{
        "kind": "check_review",
        "revision_required": bool(failed or record.body["counterexamples"]),
        "failed_criteria": failed,
        "counterexamples": len(record.body["counterexamples"]),
    }]


def _decision_admission(view, record, catalog):
    proposal = view.read(Ref.from_record(record.body["proposal_ref"]), "measure_proposal")
    return [{
        "kind": "measure_admission", "status": record.body["status"],
        "purpose": proposal.body["purpose"], "reason": record.body["reason"],
        "requirements": [requirement_address(catalog[key]) for key in proposal.body["requirement_keys"]],
    }]


def _decision_source(view, record, catalog):
    receipt = view.data(Ref.from_record(record.body["build_receipt_ref"]))
    return [{
        "kind": "source_admission", "admitted": record.body["admitted"],
        "deficits": receipt["deficits"],
    }]


_DECISION_PROJECTORS = {
    "measure_prerequisite": _decision_need,
    "evaluation": _decision_evaluation,
    "evaluation_run": _decision_run,
    "conflict": _decision_conflict,
    "measure_review": _decision_review,
    "measure_admission": _decision_admission,
    "evaluation_source": _decision_source,
}


def _open_decisions(view, assignment, body, catalog):
    result = []
    for reference in body["decision_request_refs"]:
        record = view.read(Ref.from_record(reference))
        projector = _DECISION_PROJECTORS.get(record.kind)
        if projector is None:
            raise ValueError(f"no declared decision projection for {record.kind}")
        result.extend(projector(view, record, catalog))
    return _unique(result)

_SECTION_PROJECTORS = {
    "candidate_changes": _candidate_changes,
    "measurement_findings": _measurement_findings,
    "environment_findings": _environment_findings,
    "check_review": _check_reviews,
    "investigation_findings": _investigation_findings,
    "open_decisions": _open_decisions,
}


def project_return(view, assignment, body):
    """Execute exactly this caller's information request, keeping audit separate."""
    contract = assigned_return_contract(view, assignment)
    catalog = requirement_catalog(view)
    return {
        "decision": contract["decision"],
        "disposition": body["termination"],
        "measurements": {
            item["name"]: _measurement(view, assignment, body, item, catalog)
            for item in contract["measurements"]
        },
        **{name: _SECTION_PROJECTORS[name](view, assignment, body, catalog)
           for name in contract["include"]},
    }
