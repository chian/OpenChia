"""Read-only result of the explicit refiner Run, not successor approval.

The RunStore remains the authority for transport termination. Campaign records
provide the exact candidate and original decisions for the caller's next choice.
No model summary, human note, or replacement workflow is manufactured here.
"""

from dataclasses import dataclass

from episode_runtime.audit_contracts import RunEvidence
from episode_runtime.contracts import RunTerminalStatus

from .records import Ref, RefinementRecord


_REPORTED_RETURNS = {RunTerminalStatus.SUCCEEDED, RunTerminalStatus.BLOCKED}


@dataclass(frozen=True)
class RefinementRunResult:
    campaign_ref: Ref
    run_evidence: RunEvidence
    root_report: RefinementRecord
    candidate: RefinementRecord
    decision_records: tuple[RefinementRecord, ...]
    source_admission_refs: tuple[Ref, ...]
    verified_build: RefinementRecord | None = None
    verification_gaps: tuple[dict, ...] = ()
    review_handoff: RefinementRecord | None = None

    @property
    def has_terminal_report(self):
        return self.run_evidence.terminal_status in _REPORTED_RETURNS

    @property
    def disposition(self):
        if not self.has_terminal_report:
            return self.run_evidence.terminal_status.value
        return self.root_report.body["termination"]

    @property
    def build_status(self):
        return "verified" if self.verified_build is not None else "unresolved"

    def as_record(self):
        return {
            "schema_id": "openchia.refinement.run-result",
            "schema_version": 1,
            "campaign_ref": self.campaign_ref.as_record(),
            "run_evidence": self.run_evidence.as_record(),
            "disposition": self.disposition,
            "build_status": self.build_status,
            "has_terminal_report": self.has_terminal_report,
            "root_report": self.root_report.as_record(),
            "candidate": self.candidate.as_record(),
            "decision_records": [item.as_record() for item in self.decision_records],
            "source_admission_refs": [
                ref.as_record() for ref in self.source_admission_refs
            ],
            "verified_build": self.verified_build.as_record()
            if self.verified_build
            else None,
            "verification_gaps": list(self.verification_gaps),
            "review_handoff": self.review_handoff.as_record()
            if self.review_handoff
            else None,
        }


def _decisions(view, root_report):
    """Follow only committed typed child reports, never the Run's raw text."""
    pending, seen, decisions = [root_report], set(), {}
    while pending:
        report = pending.pop()
        if report.ref in seen:
            continue
        seen.add(report.ref)
        for ref in report.body["decision_request_refs"]:
            record = view.read(Ref.from_record(ref))
            decisions[record.ref] = record
        for ref in report.body.get("child_report_refs", ()):
            child = view.read(Ref.from_record(ref), "parent_report")
            assignment = view.read(
                Ref.from_record(child.body["assignment_ref"]), "assignment"
            )
            if (
                assignment.body["parent_assignment_ref"]
                != report.body["assignment_ref"]
            ):
                raise ValueError("result report links a child from another assignment")
            pending.append(child)
    return tuple(decisions.values())


def project_result(session, evidence):
    """Project the actual terminal evidence for this already-bound host session."""
    if (
        evidence.run_id != session.registration.run_id
        or evidence.registration_hash != session.registration.registration_hash
    ):
        raise ValueError("refinement result belongs to another Run")
    committed = session.store.evidence.runs.read_evidence(evidence.run_id)
    if committed != evidence:
        raise ValueError("refinement result differs from committed Run evidence")
    reported = committed.terminal_status in _REPORTED_RETURNS
    if reported:
        session.validate_return(committed.terminal_status.value, committed.typed_status)
    with session.view() as view:
        if reported:
            report = view.read(
                committed.typed_status["workflow_result"]["report_id"], "parent_report"
            )
        else:
            from .reports import parent_report

            # This is the last known campaign state, not fabricated completion.
            report = parent_report(view, session.calls[session.root_id].invocation_id)
        candidate = view.read(
            Ref.from_record(report.body["selected_candidate_ref"]), "candidate"
        )
        return RefinementRunResult(
            campaign_ref=view.contract.ref,
            run_evidence=committed,
            root_report=report,
            candidate=candidate,
            decision_records=_decisions(view, report),
            source_admission_refs=tuple(
                row.record.ref
                for row in view.entries("evaluation_source")
                if row.record.body["candidate_ref"] == candidate.ref.as_record()
                and row.status == "admitted"
            ),
        )
