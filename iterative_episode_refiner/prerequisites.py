"""Parent-local decision progress from admitted prerequisite results.

Making an instrument available or resolving a named choice can advance the
parent's search without proving its implementation correct. This projection
never copies child credit, treats a proposal as admission, or closes acceptance.
"""

from agent.duet_contracts import canonical_json, content_id

from .judgment import returned_children
from .records import Ref
from .state_machine import derived


def _measure_results(view, assignment, report):
    from .measure_admission import adequacy_fact_keys
    from .measures import admitted_measures

    child = view.read(Ref.from_record(report.body["assignment_ref"]), "assignment")
    goal = view.data(Ref.from_record(child.body["goal_record_ref"]))
    need = goal["measure_request"]
    available = {item.ref: item for item in admitted_measures(view, assignment)}
    for reference in report.body.get("measure_admission_refs", ()):
        admission = available.get(Ref.from_record(reference))
        if admission is None or admission.invocation_id != report.invocation_id:
            continue
        proposal = view.read(
            Ref.from_record(admission.body["proposal_ref"]), "measure_proposal"
        )
        if (
            proposal.body["assignment_ref"] != child.ref.as_record()
            or proposal.body["owner_assignment_ref"] != assignment.ref.as_record()
            or proposal.body["purpose"] != need["purpose"]
            or {row["requirement_key"] for row in admission.body["requirement_results"]}
            != set(need["requirement_keys"])
            or not set(need["requirement_keys"])
            <= set(assignment.body["scope_requirement_keys"])
        ):
            continue
        # Recompute requirement coverage from the admitted instrument; the
        # parent owns availability credit, not the child's partial-work score.
        facts = adequacy_fact_keys(view, proposal, admission.body["requirement_results"])
        yield {
            "decision": {
                "kind": "measure_available",
                "measure_ref": admission.body["measure_ref"],
                "purpose": need["purpose"],
                "requirement_keys": sorted(need["requirement_keys"]),
                "limitation_refs": admission.body["limitation_refs"],
            },
            "source": admission,
            "facts": facts,
        }


def _investigation_results(view, assignment, report):
    from .investigation import finding_record, findings

    child = view.read(Ref.from_record(report.body["assignment_ref"]), "assignment")
    reported = {
        canonical_json(item) for item in report.body.get("investigation_findings", ())
    }
    for finding in findings(view, child):
        if (
            not finding["resolved"]
            or canonical_json(finding) not in reported
            or finding["owner_assignment_ref"] != assignment.ref.as_record()
            or finding["requirement_key"]
            not in assignment.body["scope_requirement_keys"]
        ):
            continue
        observation = finding_record(view, finding)
        if finding.get("kind") == "research":
            yield {
                "decision": {
                    "kind": "research_available",
                    "finding_ref": observation.ref.as_record(),
                    "role": finding["role"], "state": finding["state"],
                    "requirement_keys": [finding["requirement_key"]],
                    "policy_strength": "advisory", "limitation_refs": [],
                },
                "source": observation, "facts": [finding["fact_key"]],
            }
            continue
        yield {
            "decision": {
                "kind": "question_resolved"
                if child.body["role"] == "question"
                else "support_available",
                "need_ref": finding["need_ref"],
                "decision_ref": finding["decision_ref"],
                "target_ref": finding["target_ref"],
                "state": finding["state"],
                "requirement_keys": [finding["requirement_key"]],
                "policy_strength": "advisory",
                "applicability_ref": finding["applicability_ref"],
                "limitation_refs": finding["limitation_refs"],
            },
            "source": observation,
            "facts": [finding["fact_key"]],
        }


def _results(view, assignment, report):
    return (
        _measure_results(view, assignment, report)
        if report.body["role"] == "measure"
        else _investigation_results(view, assignment, report)
    )


def parent_prerequisites(view, attempt, assignment):
    """Build exact assessments for independently meaningful returned decisions."""
    roles = set(assignment.body["allowed_child_bindings"]) & {
        "measure",
        "support",
        "question",
    }
    result = []
    for report in returned_children(view, attempt, assignment, roles):
        for item in _results(view, assignment, report):
            if not item["source"].evidence_refs:
                continue
            keys = sorted({
                content_id(
                    "refinement_fact",
                    {
                        "kind": item["decision"]["kind"],
                        "established_decision": key,
                    },
                ).value
                for key in item["facts"]
            })
            result.append(
                derived(
                    view,
                    attempt,
                    "prerequisite_assessment",
                    {
                        "assignment_ref": assignment.ref.as_record(),
                        "source_report_ref": report.ref.as_record(),
                        "source_record_ref": item["source"].ref.as_record(),
                        "decision": item["decision"],
                        "fact_keys": keys,
                    },
                    evidence=item["source"].evidence_refs,
                )
            )
    return tuple(result)


def prerequisite_status(view, assessment):
    """Historical decisions cannot suppress new or contradictory current evidence."""
    assignment = view.read(
        Ref.from_record(assessment.body["assignment_ref"]), "assignment"
    )
    report = view.read(
        Ref.from_record(assessment.body["source_report_ref"]), "parent_report"
    )
    return (
        "current"
        if any(
            item["source"].ref.as_record() == assessment.body["source_record_ref"]
            and canonical_json(item["decision"])
            == canonical_json(assessment.body["decision"])
            for item in _results(view, assignment, report)
        )
        else "stale"
    )
