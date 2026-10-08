"""Evidence handoff from the executing refiner to the existing Duet proposal path.

Publishing a review bundle neither starts a successor nor supplies human notes.
The ordinary approval service may attach it to an explicitly requested proposal.
Target Workflow code remains evidence until the successor's own admission/validation.
"""

from dataclasses import replace

from agent.duet_contracts import DuetProtocolError
from agent.duet_store import DuetConflictError

from .campaign_store import CampaignView
from .contracts import RefinementBaseline
from .outcome import project_result
from .records import Ref, RefinementRecord
from .reports import parent_report


def _baseline(view, root_report):
    assignment = view.read(
        Ref.from_record(root_report.body["assignment_ref"]), "assignment"
    )
    if (
        assignment.body["parent_assignment_ref"] is not None
        or assignment.body["role"] != "designer"
    ):
        raise ValueError("Duet review requires the root Designer report")
    goal = view.data(Ref.from_record(assignment.body["goal_record_ref"]))
    if goal["baseline"] is None:
        # Fresh construction has no prior materialized workspace to annotate.
        # Its review remains anchored by campaign, authority and candidate.
        return None
    baseline = RefinementBaseline.from_record(goal["baseline"])
    if (
        baseline.duet_id.value != view.head["duet_id"]
        or baseline.authority_head_approval_id.value
        != view.contract.body["target_approval_ref"]["artifact_id"]
    ):
        raise ValueError("review baseline differs from the campaign's target authority")
    target_workflow = view.data(Ref.from_record(view.contract.body["target_workflow_ref"]))
    inputs = view.data(Ref.from_record(view.contract.body["initial_build_inputs_ref"]))
    materialization = view.data(
        Ref.from_record(view.contract.body["initial_materialization_ref"])
    )
    if (
        target_workflow["artifact_id"] != baseline.frozen_workflow_artifact_id.value
        or target_workflow["workflow_hash"] != baseline.workflow_hash.value
        or inputs["receipt_id"] != baseline.build_receipt_id.value
        or materialization["specification_id"]
        != baseline.materialized_specification_id.value
        or materialization["content_hash"]
        != baseline.materialized_specification_hash.value
    ):
        raise ValueError("review baseline differs from the original campaign build")
    return baseline


def attach_review(session, result):
    """Archive a validated return/snapshot without interpreting it as approval."""
    actual = project_result(session, result.run_evidence)
    if (
        actual.candidate.ref != result.candidate.ref
        or actual.root_report.ref != result.root_report.ref
    ):
        raise DuetConflictError("refinement changed before its review handoff")
    with session.view() as view:
        report = parent_report(view, result.root_report.invocation_id)
        if (
            report.ref != result.root_report.ref
            or view.candidate.ref != result.candidate.ref
        ):
            raise DuetConflictError(
                "review must retain the exact returned candidate and report"
            )
        baseline = _baseline(view, report)
        if result.verified_build is not None:
            verified = view.read(result.verified_build.ref, "verified_build")
            if (
                verified.body["root_report_ref"] != report.ref.as_record()
                or verified.body["candidate_ref"] != result.candidate.ref.as_record()
            ):
                raise ValueError(
                    "review verification belongs to another returned build"
                )
        review = RefinementRecord(
            "review_handoff",
            view.campaign_id,
            {
                "campaign_ref": view.contract.ref.as_record(),
                "baseline_ref": None if baseline is None else Ref(
                    baseline.baseline_id, baseline.content_hash
                ).as_record(),
                "target_approval_ref": view.contract.body["target_approval_ref"],
                "candidate_ref": result.candidate.ref.as_record(),
                "root_report_ref": report.ref.as_record(),
                "refiner_run_ref": Ref(
                    result.run_evidence.evidence_id, result.run_evidence.content_hash
                ).as_record(),
                "has_terminal_report": result.has_terminal_report,
                "disposition": result.disposition,
                "decision_refs": [
                    record.ref.as_record() for record in actual.decision_records
                ],
                "source_admission_refs": [
                    ref.as_record() for ref in actual.source_admission_refs
                ],
                "verified_build_ref": result.verified_build.ref.as_record()
                if result.verified_build
                else None,
                "verification_gaps": list(result.verification_gaps),
                "complete_index_ref": report.body["complete_index_ref"],
            },
            view.contract.producer_ref,
            predecessor_refs=(report.ref,),
            invocation_id=report.invocation_id,
        )
        exists = view.connection.execute(
            "SELECT 1 FROM artifacts WHERE artifact_id = ?", (review.artifact_id.value,)
        ).fetchone()
        # External stops may have only a last-known report projection. Its status
        # above stays explicitly nonterminal; persistence cannot make it attained.
        session.store._put(view.connection, session.duet_id, report)
        session.store._put(view.connection, session.duet_id, review)
        if exists is None:
            session.store.duet_store._append_event(
                view.connection,
                duet_id=session.duet_id,
                event_type="refinement_review_prepared",
                provenance="host_validation",
                record={"review_handoff_ref": review.ref.as_record()},
            )
    return replace(result, review_handoff=review)


def validate_review_handoff(store, review_id, baseline):
    """Attach only current, same-baseline evidence to a human-initiated proposal.

    This validates supporting evidence linkage, not the replacement Architecture
    or its approval. Those remain the existing Duet service's responsibility.
    """
    artifact = store.get_artifact(review_id.value)
    if artifact is None:
        raise DuetProtocolError("refinement review handoff is missing")
    review = RefinementRecord.from_record(artifact["record"])
    if (
        review.kind != "review_handoff"
        or review.artifact_id != review_id
        or artifact["duet_id"] != baseline.duet_id.value
        or artifact["content_hash"] != review.content_hash.value
        or review.body["baseline_ref"]
        != Ref(baseline.baseline_id, baseline.content_hash).as_record()
    ):
        raise DuetProtocolError(
            "review handoff belongs to another baseline or identity"
        )
    with store.transaction() as connection:
        view = CampaignView(connection, review.campaign_id)
        report = view.read(
            Ref.from_record(review.body["root_report_ref"]), "parent_report"
        )
        expected = parent_report(view, report.invocation_id)
        if (
            _baseline(view, report) != baseline
            or view.contract.ref.as_record() != review.body["campaign_ref"]
            or view.contract.body["target_approval_ref"]
            != review.body["target_approval_ref"]
            or view.candidate.ref.as_record() != review.body["candidate_ref"]
            or expected.ref != report.ref
            or report.body["complete_index_ref"] != review.body["complete_index_ref"]
        ):
            raise DuetConflictError(
                "review no longer describes the exact campaign return"
            )
        # All decisions are reference data. No returned text is a human note or
        # an instruction to mutate an active workflow or auto-approve a successor.
        for reference in review.body["decision_refs"]:
            view.read(Ref.from_record(reference))
    return review
