"""Deterministic refinement over one exact Duet-approved build baseline.

The refiner is host machinery, not an Agent or Episode.  It persists exact
human notes, derives proposals, classifies candidate changes, and records the
decision that may later be presented for human approval.  It has no operation
that can mint or commit a Duet approval.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Mapping, Optional, Protocol

from agent.duet_contracts import (
    ContractDeficit,
    DuetApproval,
    DuetDesignState,
    DuetIdentity,
    DuetProtocolError,
    DuetProvenance,
    FrozenDuetWorkflow,
    WorkflowAdmissionAuthority,
    canonical_json,
    content_id,
)
from agent.duet_store import (
    DuetConflictError,
    DuetNotFoundError,
    DuetStore,
)
from agent.episode_blueprints import (
    workflow_blueprint_from_spec,
    workflow_draft_record,
)
from agent.episode_contracts import EpisodeWorkflowSpec, OpaqueId, Sha256Digest

from .contracts import (
    CurrentBuildAuthorization,
    DuetWorkspaceNote,
    ImplementationDirective,
    RefinementBaseline,
    RefinementChangeKind,
    RefinementCycleState,
    RefinementDecision,
    RefinementProposal,
    RefinementTarget,
    RefinementTargetLayer,
)


EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND = "episode_workflow_draft"
REFINEMENT_BASELINE_ARTIFACT_KIND = "refinement_baseline"
WORKSPACE_NOTE_ARTIFACT_KIND = "workspace_note"
WORKSPACE_NOTE_SUBMISSION_ARTIFACT_KIND = "workspace_note_submission"
REFINEMENT_PROPOSAL_ARTIFACT_KIND = "refinement_proposal"
REFINEMENT_DECISION_ARTIFACT_KIND = "refinement_decision"
MATERIALIZED_SPECIFICATION_ARTIFACT_KIND = "materialized_specification"
RUN_EVIDENCE_ARTIFACT_KIND = "run_evidence"


class RefinementAuthorityReader(Protocol):
    """Read-only authority capabilities required by the refiner."""

    def validate_duet_workflow(
        self,
        duet_id: OpaqueId,
        value: object,
    ) -> tuple[Optional[EpisodeWorkflowSpec], tuple[ContractDeficit, ...]]: ...

    def verify_workflow_approval(
        self,
        approval_id: OpaqueId,
    ) -> tuple[
        DuetApproval,
        FrozenDuetWorkflow,
        WorkflowAdmissionAuthority,
    ]: ...

    def resolve_current_build_authorization(
        self,
        duet_id: OpaqueId,
    ) -> CurrentBuildAuthorization: ...


def _artifact_spec(
    *,
    artifact_id: OpaqueId,
    duet_id: OpaqueId,
    kind: str,
    revision: int,
    content_hash: Sha256Digest,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id.value,
        "duet_id": duet_id.value,
        "kind": kind,
        "revision": revision,
        "content_hash": content_hash.value,
        "record": dict(record),
    }


def _pointer_escape(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _stable_workflow_record(value: object) -> object:
    """Key Episode arrays by local ID before computing deterministic paths."""

    if isinstance(value, Mapping):
        return {
            str(key): _stable_workflow_record(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        if all(
            isinstance(item, Mapping)
            and isinstance(item.get("local_id"), str)
            for item in value
        ):
            return {
                str(item["local_id"]): _stable_workflow_record(item)
                for item in value
            }
        return [_stable_workflow_record(item) for item in value]
    return value


def _changed_paths(before: object, after: object, path: str = "") -> set[str]:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        result: set[str] = set()
        for key in sorted(set(before) | set(after)):
            child = f"{path}/{_pointer_escape(str(key))}"
            if key not in before or key not in after:
                result.add(child)
            else:
                result.update(_changed_paths(before[key], after[key], child))
        return result
    if isinstance(before, list) and isinstance(after, list):
        result = set()
        for index in range(max(len(before), len(after))):
            child = f"{path}/{index}"
            if index >= len(before) or index >= len(after):
                result.add(child)
            else:
                result.update(_changed_paths(before[index], after[index], child))
        return result
    return set() if before == after else {path or "/"}


def _target_covers(target: RefinementTarget, path: str) -> bool:
    pointer = target.json_pointer
    return not pointer or path == pointer or path.startswith(pointer + "/")


class IterativeEpisodeRefiner:
    """Validate and persist iterative changes without granting authority."""

    def __init__(
        self,
        store: DuetStore,
        authority: RefinementAuthorityReader,
    ) -> None:
        self.store = store
        self.authority = authority
        self._candidate_lock = threading.RLock()

    def _duet_row(self, duet_id: OpaqueId) -> dict[str, Any]:
        row = self.store.get_duet(duet_id.value)
        if row is None:
            raise DuetNotFoundError("unknown Duet")
        return row

    def _assert_identity(self, identity: DuetIdentity) -> dict[str, Any]:
        row = self._duet_row(identity.duet_id)
        if row["identity"] != identity.as_record():
            raise DuetProtocolError(
                "human instruction authority does not match the Duet"
            )
        return row

    def load_baseline(self, baseline_id: OpaqueId) -> RefinementBaseline:
        artifact = self.store.get_artifact(baseline_id.value)
        if artifact is None or artifact["kind"] != REFINEMENT_BASELINE_ARTIFACT_KIND:
            raise DuetNotFoundError("refinement baseline not found")
        try:
            baseline = RefinementBaseline.from_record(artifact["record"])
        except (TypeError, ValueError) as exc:
            raise DuetProtocolError(
                "stored refinement baseline is malformed"
            ) from exc
        if (
            baseline.baseline_id != baseline_id
            or artifact["artifact_id"] != baseline.baseline_id.value
            or artifact["duet_id"] != baseline.duet_id.value
            or artifact["content_hash"] != baseline.content_hash.value
        ):
            raise DuetProtocolError("refinement baseline linkage is stale")
        return baseline

    def load_note(self, note_id: OpaqueId) -> DuetWorkspaceNote:
        artifact = self.store.get_artifact(note_id.value)
        if artifact is None or artifact["kind"] != WORKSPACE_NOTE_ARTIFACT_KIND:
            raise DuetNotFoundError("Duet workspace note not found")
        try:
            note = DuetWorkspaceNote.from_record(artifact["record"])
        except (TypeError, ValueError) as exc:
            raise DuetProtocolError(
                "stored refinement note is malformed"
            ) from exc
        if (
            note.note_id != note_id
            or artifact["duet_id"] != note.duet_id.value
            or artifact["content_hash"] != note.content_hash.value
        ):
            raise DuetProtocolError("refinement note linkage is stale")
        return note

    def load_proposal(self, proposal_id: OpaqueId) -> RefinementProposal:
        artifact = self.store.get_artifact(proposal_id.value)
        if artifact is None or artifact["kind"] != REFINEMENT_PROPOSAL_ARTIFACT_KIND:
            raise DuetNotFoundError("refinement proposal not found")
        try:
            proposal = RefinementProposal.from_record(artifact["record"])
        except (TypeError, ValueError) as exc:
            raise DuetProtocolError(
                "stored refinement proposal is malformed"
            ) from exc
        if (
            proposal.proposal_id != proposal_id
            or artifact["duet_id"] != proposal.duet_id.value
            or artifact["content_hash"] != proposal.content_hash.value
        ):
            raise DuetProtocolError("refinement proposal linkage is stale")
        return proposal

    def load_decision(self, decision_id: OpaqueId) -> RefinementDecision:
        artifact = self.store.get_artifact(decision_id.value)
        if artifact is None or artifact["kind"] != REFINEMENT_DECISION_ARTIFACT_KIND:
            raise DuetNotFoundError("refinement decision not found")
        try:
            decision = RefinementDecision.from_record(artifact["record"])
        except (TypeError, ValueError) as exc:
            raise DuetProtocolError(
                "stored refinement decision is malformed"
            ) from exc
        if (
            decision.decision_id != decision_id
            or artifact["duet_id"] != decision.duet_id.value
            or artifact["content_hash"] != decision.content_hash.value
        ):
            raise DuetProtocolError("refinement decision linkage is stale")
        return decision

    def verify_semantic_successor(
        self,
        *,
        approval: DuetApproval,
        frozen: FrozenDuetWorkflow,
        source_record: Mapping[str, Any],
    ) -> RefinementDecision:
        decision_id = frozen.refinement_decision_id
        if decision_id is None:
            raise DuetProtocolError("semantic successor has no refinement decision")
        decision = self.load_decision(decision_id)
        baseline = self.load_baseline(decision.baseline_id)
        proposal = self.load_proposal(decision.proposal_id)
        if (
            decision.kind is not RefinementChangeKind.DESIGN_SEMANTIC
            or proposal.content_hash != decision.proposal_hash
            or decision.content_hash != frozen.refinement_decision_hash
            or decision.successor_draft_artifact_id
            != frozen.source_draft_artifact_id
            or decision.successor_draft_hash != frozen.source_draft_hash
            or decision.result_workflow_hash != frozen.workflow_hash
            or source_record["refinement_id"] != decision.refinement_id.value
            or source_record["baseline_id"] != decision.baseline_id.value
            or source_record["proposal_id"] != decision.proposal_id.value
            or source_record["human_note_ids"]
            != [item.value for item in proposal.note_ids]
            or baseline.authority_head_approval_id
            != approval.predecessor_approval_id
            or baseline.workflow_hash != decision.baseline_workflow_hash
        ):
            raise DuetProtocolError(
                "semantic refinement decision does not match its workflow"
            )
        return decision

    def record_baseline(
        self,
        identity: DuetIdentity,
        baseline: RefinementBaseline,
    ) -> RefinementBaseline:
        row = self._assert_identity(identity)
        if row["state"] != DuetDesignState.SEALED.value:
            raise DuetProtocolError("refinement baseline requires a sealed Duet")
        if baseline.duet_id != identity.duet_id:
            raise DuetProtocolError("refinement baseline belongs to another Duet")
        authorization = self.authority.resolve_current_build_authorization(
            identity.duet_id
        )
        if (
            baseline.authority_head_approval_id
            != authorization.authority_approval.approval_id
            or baseline.workflow_approval_id
            != authorization.workflow_approval.approval_id
            or baseline.frozen_workflow_artifact_id
            != authorization.frozen_workflow.artifact_id
            or baseline.workflow_hash
            != authorization.frozen_workflow.workflow_hash
        ):
            raise DuetProtocolError(
                "refinement baseline does not bind current workflow authority"
            )
        materialized = self.store.get_artifact(
            baseline.materialized_specification_id.value
        )
        if (
            materialized is None
            or materialized["duet_id"] != identity.duet_id.value
            or materialized["kind"]
            != MATERIALIZED_SPECIFICATION_ARTIFACT_KIND
            or materialized["content_hash"]
            != baseline.materialized_specification_hash.value
        ):
            raise DuetProtocolError(
                "Materialized Specification artifact is missing or does not match"
            )
        if baseline.run_evidence_artifact_id is not None:
            evidence = self.store.get_artifact(
                baseline.run_evidence_artifact_id.value
            )
            if (
                evidence is None
                or evidence["duet_id"] != identity.duet_id.value
                or evidence["kind"] != RUN_EVIDENCE_ARTIFACT_KIND
                or evidence["content_hash"] != baseline.run_evidence_hash.value
            ):
                raise DuetProtocolError(
                    "optional Run evidence is missing or does not match"
                )
        self.store.put_artifacts_with_events(
            artifacts=(
                _artifact_spec(
                    artifact_id=baseline.baseline_id,
                    duet_id=identity.duet_id,
                    kind=REFINEMENT_BASELINE_ARTIFACT_KIND,
                    revision=authorization.frozen_workflow.revision,
                    content_hash=baseline.content_hash,
                    record=baseline.as_record(),
                ),
            ),
            events=(
                {
                    "event_type": "refinement_baseline_recorded",
                    "provenance": DuetProvenance.HOST_VALIDATION.value,
                    "record": {
                        "baseline_id": baseline.baseline_id.value,
                        "build_request_id": baseline.build_request_id.value,
                        "build_attempt_id": baseline.build_attempt_id.value,
                        "materialized_specification_id": (
                            baseline.materialized_specification_id.value
                        ),
                        "run_evidence_artifact_id": (
                            None
                            if baseline.run_evidence_artifact_id is None
                            else baseline.run_evidence_artifact_id.value
                        ),
                    },
                },
            ),
            idempotency_artifact_ids=(baseline.baseline_id.value,),
            duet_id=identity.duet_id.value,
            expected_state=DuetDesignState.SEALED.value,
            expected_authority_head_approval_id=(
                baseline.authority_head_approval_id.value
            ),
        )
        return baseline

    @staticmethod
    def _validate_target_against_baseline(
        target: RefinementTarget,
        baseline: RefinementBaseline,
    ) -> None:
        if target.layer is RefinementTargetLayer.WORKFLOW_SEMANTICS:
            if (
                target.artifact_id != baseline.frozen_workflow_artifact_id
                or target.artifact_hash != baseline.workflow_hash
            ):
                raise DuetProtocolError(
                    "workflow target does not bind the baseline workflow"
                )
        elif (
            target.artifact_id != baseline.materialized_specification_id
            or target.artifact_hash != baseline.materialized_specification_hash
        ):
            raise DuetProtocolError(
                "implementation target does not bind the baseline "
                "Materialized Specification"
            )

    def _validate_current_workspace_baseline(
        self,
        duet_id: OpaqueId,
        baseline: RefinementBaseline,
        row: Mapping[str, Any],
    ) -> None:
        if baseline.duet_id != duet_id:
            raise DuetProtocolError("workspace baseline belongs to another Duet")
        if (
            row["authority_head_approval_id"]
            != baseline.authority_head_approval_id.value
        ):
            raise DuetProtocolError(
                "workspace baseline authority is no longer current"
            )
        allowed_states = {
            DuetDesignState.SEALED.value,
            DuetDesignState.REFINING.value,
            DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value,
            DuetDesignState.AWAITING_REFINEMENT_APPROVAL.value,
        }
        if row["state"] not in allowed_states:
            raise DuetProtocolError(
                "Duet state does not expose a refinement workspace"
            )
        if row["state"] != DuetDesignState.SEALED.value:
            cycle = self.store.active_refinement_cycle(duet_id.value)
            if (
                cycle is None
                or cycle["baseline_artifact_id"] != baseline.baseline_id.value
            ):
                raise DuetProtocolError(
                    "active refinement does not use this workspace baseline"
                )

    def record_workspace_notes(
        self,
        identity: DuetIdentity,
        *,
        baseline_id: Optional[OpaqueId],
        body: str,
        targets: tuple[RefinementTarget, ...],
        idempotency_keys: tuple[str, ...],
    ) -> tuple[DuetWorkspaceNote, ...]:
        """Atomically persist one exact human instruction at all named targets."""

        row = self._assert_identity(identity)
        if (
            not isinstance(targets, tuple)
            or not targets
            or any(not isinstance(target, RefinementTarget) for target in targets)
        ):
            raise TypeError(
                "targets must be a non-empty tuple of RefinementTarget values"
            )
        if len({target.target_id for target in targets}) != len(targets):
            raise ValueError("workspace note targets must be unique")
        if (
            not isinstance(idempotency_keys, tuple)
            or len(idempotency_keys) != len(targets)
            or len(set(idempotency_keys)) != len(idempotency_keys)
            or any(
                not isinstance(key, str)
                or not key.strip()
                or "\x00" in key
                or len(key) > 512
                for key in idempotency_keys
            )
        ):
            raise ValueError(
                "idempotency_keys must uniquely cover the workspace note targets"
            )
        baseline: Optional[RefinementBaseline]
        if baseline_id is None:
            baseline = None
            if (
                row["authority_head_approval_id"] is not None
                or row["state"]
                not in {
                    DuetDesignState.DESIGNING.value,
                    DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value,
                }
                or any(
                    target.layer is not RefinementTargetLayer.WORKFLOW_SEMANTICS
                    for target in targets
                )
            ):
                raise DuetProtocolError(
                    "baseline-free notes require the mutable initial Architecture"
                )
            initial_drafts = tuple(
                artifact
                for artifact in self.store.artifacts_by_kind(
                    duet_id=identity.duet_id.value,
                    kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
                )
                if artifact["record"].get("refinement_id") is None
            )
            if not initial_drafts:
                raise DuetProtocolError(
                    "an Architecture draft must exist before it can be annotated"
                )
            current = initial_drafts[-1]
            if any(
                target.artifact_id.value != current["artifact_id"]
                or target.artifact_hash.value != current["content_hash"]
                for target in targets
            ):
                raise DuetProtocolError(
                    "Architecture note target is no longer the current draft"
                )
        else:
            baseline = self.load_baseline(baseline_id)
            self._validate_current_workspace_baseline(
                identity.duet_id,
                baseline,
                row,
            )
            for target in targets:
                self._validate_target_against_baseline(target, baseline)
        notes = tuple(
            DuetWorkspaceNote(
                duet_id=identity.duet_id,
                baseline_id=(None if baseline is None else baseline.baseline_id),
                human_authority_id=identity.human_authority_id,
                body=body,
                target=target,
            )
            for target in targets
        )
        request_records = tuple(
            {
                "duet_id": identity.duet_id.value,
                "idempotency_key": key,
                "baseline_id": (
                    None if baseline is None else baseline.baseline_id.value
                ),
                "target": note.target.as_record(),
                "body": body,
            }
            for note, key in zip(notes, idempotency_keys)
        )
        submission_ids = tuple(
            content_id(
                "workspace_note_submission",
                {
                    "duet_id": identity.duet_id.value,
                    "idempotency_key": key,
                },
            )
            for key in idempotency_keys
        )
        existing = tuple(
            self.store.get_artifact(submission_id.value)
            for submission_id in submission_ids
        )
        if any(artifact is not None for artifact in existing):
            if not all(artifact is not None for artifact in existing):
                raise DuetConflictError(
                    "atomic workspace note submission is only partially present"
                )
            restored = []
            for artifact, request_record, expected_note in zip(
                existing,
                request_records,
                notes,
            ):
                assert artifact is not None
                note_id = artifact["record"].get("note_id")
                if (
                    artifact["duet_id"] != identity.duet_id.value
                    or artifact["kind"]
                    != WORKSPACE_NOTE_SUBMISSION_ARTIFACT_KIND
                    or artifact["record"].get("request") != request_record
                    or not isinstance(note_id, str)
                ):
                    raise DuetConflictError(
                        "workspace note idempotency key names different content"
                    )
                restored_note = self.load_note(OpaqueId(note_id))
                if (
                    restored_note.as_record() != expected_note.as_record()
                    or artifact["record"].get("note_hash")
                    != restored_note.content_hash.value
                ):
                    raise DuetConflictError(
                        "workspace note idempotency record is stale"
                    )
                restored.append(restored_note)
            return tuple(restored)

        artifacts: list[Mapping[str, Any]] = []
        events: list[Mapping[str, Any]] = []
        for note, request_record, submission_id in zip(
            notes,
            request_records,
            submission_ids,
        ):
            submission_record = {
                "request": request_record,
                "note_id": note.note_id.value,
                "note_hash": note.content_hash.value,
            }
            artifacts.extend(
                (
                    _artifact_spec(
                        artifact_id=note.note_id,
                        duet_id=identity.duet_id,
                        kind=WORKSPACE_NOTE_ARTIFACT_KIND,
                        revision=0,
                        content_hash=note.content_hash,
                        record=note.as_record(),
                    ),
                    _artifact_spec(
                        artifact_id=submission_id,
                        duet_id=identity.duet_id,
                        kind=WORKSPACE_NOTE_SUBMISSION_ARTIFACT_KIND,
                        revision=0,
                        content_hash=Sha256Digest.of_record(submission_record),
                        record=submission_record,
                    ),
                )
            )
            events.append(
                {
                    "event_type": "workspace_note_recorded",
                    "provenance": DuetProvenance.HUMAN_INPUT.value,
                    "record": {
                        "note_id": note.note_id.value,
                        "baseline_id": (
                            None
                            if note.baseline_id is None
                            else note.baseline_id.value
                        ),
                        "target_id": note.target.target_id.value,
                    },
                }
            )
        self.store.put_artifacts_with_events(
            artifacts=tuple(artifacts),
            events=tuple(events),
            idempotency_artifact_ids=tuple(
                submission_id.value for submission_id in submission_ids
            ),
            duet_id=identity.duet_id.value,
            expected_state=row["state"],
            expected_authority_head_approval_id=row[
                "authority_head_approval_id"
            ],
        )
        return notes

    def list_workspace_notes(
        self,
        duet_id: OpaqueId,
        baseline_id: Optional[OpaqueId],
    ) -> tuple[DuetWorkspaceNote, ...]:
        row = self._duet_row(duet_id)
        baseline: Optional[RefinementBaseline]
        if baseline_id is None:
            baseline = None
            if (
                row["authority_head_approval_id"] is not None
                or row["state"]
                not in {
                    DuetDesignState.DESIGNING.value,
                    DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value,
                }
            ):
                raise DuetProtocolError(
                    "baseline-free notes belong to the mutable initial Architecture"
                )
        else:
            baseline = self.load_baseline(baseline_id)
            self._validate_current_workspace_baseline(duet_id, baseline, row)
        notes = []
        for artifact in self.store.artifacts_by_kind(
            duet_id=duet_id.value,
            kind=WORKSPACE_NOTE_ARTIFACT_KIND,
        ):
            note = self.load_note(OpaqueId(artifact["artifact_id"]))
            expected_id = None if baseline is None else baseline.baseline_id
            if note.baseline_id == expected_id:
                notes.append(note)
        return tuple(notes)

    def record_proposal(
        self,
        proposal: RefinementProposal,
    ) -> RefinementProposal:
        row = self._duet_row(proposal.duet_id)
        if row["state"] != DuetDesignState.SEALED.value:
            raise DuetProtocolError("proposal requires a sealed baseline")
        baseline = self.load_baseline(proposal.baseline_id)
        if baseline.duet_id != proposal.duet_id:
            raise DuetProtocolError("proposal baseline belongs to another Duet")
        if (
            row["authority_head_approval_id"]
            != baseline.authority_head_approval_id.value
        ):
            raise DuetProtocolError("proposal baseline is no longer current")
        for note_id in proposal.note_ids:
            note = self.load_note(note_id)
            if (
                note.duet_id != proposal.duet_id
                or note.baseline_id != proposal.baseline_id
            ):
                raise DuetProtocolError(
                    "proposal note belongs to another baseline"
                )
        for directive in proposal.implementation_directives:
            self._validate_target_against_baseline(directive.target, baseline)
        self.store.put_artifacts_with_events(
            artifacts=(
                _artifact_spec(
                    artifact_id=proposal.proposal_id,
                    duet_id=proposal.duet_id,
                    kind=REFINEMENT_PROPOSAL_ARTIFACT_KIND,
                    revision=0,
                    content_hash=proposal.content_hash,
                    record=proposal.as_record(),
                ),
            ),
            events=(
                {
                    "event_type": "refinement_proposal_recorded",
                    "provenance": DuetProvenance.LLM_PROPOSAL.value,
                    "record": {
                        "proposal_id": proposal.proposal_id.value,
                        "baseline_id": proposal.baseline_id.value,
                        "note_ids": [
                            item.value for item in proposal.note_ids
                        ],
                        "implementation_directive_ids": [
                            item.directive_id.value
                            for item in proposal.implementation_directives
                        ],
                    },
                },
            ),
            idempotency_artifact_ids=(proposal.proposal_id.value,),
            duet_id=proposal.duet_id.value,
            expected_state=DuetDesignState.SEALED.value,
            expected_authority_head_approval_id=(
                baseline.authority_head_approval_id.value
            ),
        )
        return proposal

    def begin(
        self,
        identity: DuetIdentity,
        proposal_id: OpaqueId,
    ) -> dict[str, Any]:
        row = self._assert_identity(identity)
        if row["state"] != DuetDesignState.SEALED.value:
            raise DuetProtocolError("only a sealed Duet can begin refinement")
        proposal = self.load_proposal(proposal_id)
        baseline = self.load_baseline(proposal.baseline_id)
        if (
            proposal.duet_id != identity.duet_id
            or baseline.duet_id != identity.duet_id
        ):
            raise DuetProtocolError(
                "refinement artifacts belong to another Duet"
            )
        if baseline.authority_head_approval_id.value != row[
            "authority_head_approval_id"
        ]:
            raise DuetProtocolError("refinement baseline is no longer current")
        current = self.authority.resolve_current_build_authorization(
            identity.duet_id
        )
        if (
            current.authority_approval.approval_id
            != baseline.authority_head_approval_id
            or current.workflow_approval.approval_id
            != baseline.workflow_approval_id
            or current.frozen_workflow.workflow_hash != baseline.workflow_hash
        ):
            raise DuetProtocolError("refinement baseline authority is stale")
        return self.store.begin_refinement_cycle(
            duet_id=identity.duet_id.value,
            baseline_artifact_id=baseline.baseline_id.value,
            proposal_artifact_id=proposal.proposal_id.value,
            expected_authority_head_approval_id=(
                baseline.authority_head_approval_id.value
            ),
            event_type="refinement_started",
            provenance=DuetProvenance.HUMAN_INPUT.value,
            event_record={
                "baseline_id": baseline.baseline_id.value,
                "proposal_id": proposal.proposal_id.value,
            },
        )

    def _semantic_targets(
        self,
        proposal: RefinementProposal,
    ) -> tuple[RefinementTarget, ...]:
        targets = []
        for note_id in proposal.note_ids:
            note = self.load_note(note_id)
            if note.target.layer is RefinementTargetLayer.WORKFLOW_SEMANTICS:
                targets.append(note.target)
        return tuple(targets)

    def record_candidate(
        self,
        *,
        duet_id: OpaqueId,
        workflow_blueprint: Mapping[str, Any],
        expected_workflow_hash: Optional[str],
        source_stage: str,
    ) -> dict[str, Any]:
        """Classify and persist one candidate against the active exact baseline."""

        if source_stage not in {"duet", "human_edit"}:
            raise ValueError("refinement source must be duet or human_edit")
        if not isinstance(workflow_blueprint, Mapping):
            raise ValueError("Episode workflow draft must be an object")
        with self._candidate_lock:
            duet_row = self._duet_row(duet_id)
            if duet_row["state"] != DuetDesignState.REFINING.value:
                raise DuetProtocolError(
                    "Duet has no refinement accepting a candidate"
                )
            cycle = self.store.active_refinement_cycle(duet_id.value)
            if (
                cycle is None
                or cycle["state"] != RefinementCycleState.REFINING.value
            ):
                raise DuetProtocolError(
                    "Duet has no refinement accepting a candidate"
                )
            baseline = self.load_baseline(
                OpaqueId(cycle["baseline_artifact_id"])
            )
            proposal = self.load_proposal(
                OpaqueId(cycle["proposal_artifact_id"])
            )
            workflow_approval, frozen, _ = (
                self.authority.verify_workflow_approval(
                    baseline.workflow_approval_id
                )
            )
            if (
                workflow_approval.approval_id != baseline.workflow_approval_id
                or frozen.artifact_id
                != baseline.frozen_workflow_artifact_id
                or frozen.workflow_hash != baseline.workflow_hash
            ):
                raise DuetProtocolError(
                    "refinement baseline workflow is stale"
                )
            drafts = self.store.artifacts_by_kind(
                duet_id=duet_id.value,
                kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
            )
            latest_draft = self.store.latest_artifact(
                duet_id=duet_id.value,
                kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
            )
            if latest_draft is None:
                raise DuetProtocolError(
                    "refinement baseline has no persisted Architecture draft"
                )
            cycle_drafts = tuple(
                item
                for item in drafts
                if item["record"].get("refinement_id")
                == cycle["refinement_id"]
            )
            prior = (
                cycle_drafts[-1]
                if cycle_drafts
                else self.store.get_artifact(
                    frozen.source_draft_artifact_id.value
                )
            )
            if prior is None:
                raise DuetProtocolError(
                    "refinement baseline source draft is missing"
                )
            actual_hash = prior["content_hash"]
            if expected_workflow_hash != actual_hash:
                raise DuetConflictError(
                    "Episode workflow changed while refinement was being edited"
                )
            raw_blueprint = json.loads(canonical_json(workflow_blueprint))
            workflow, deficits = self.authority.validate_duet_workflow(
                duet_id,
                raw_blueprint,
            )
            revision = int(latest_draft["revision"]) + 1
            refinement_source = (
                "refinement_human_edit"
                if source_stage == "human_edit"
                else "refinement_duet"
            )
            if workflow is None or deficits:
                record, blueprint_hash, artifact_id = workflow_draft_record(
                    duet_id=duet_id,
                    revision=revision,
                    source_stage=refinement_source,
                    blueprint=raw_blueprint,
                    workflow=workflow,
                    deficits=deficits,
                    refinement_id=OpaqueId(cycle["refinement_id"]),
                    baseline_id=baseline.baseline_id,
                    proposal_id=proposal.proposal_id,
                    human_note_ids=proposal.note_ids,
                )
                self.store.put_artifacts_with_transition(
                    artifacts=(
                        _artifact_spec(
                            artifact_id=artifact_id,
                            duet_id=duet_id,
                            kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
                            revision=revision,
                            content_hash=blueprint_hash,
                            record=record,
                        ),
                    ),
                    duet_id=duet_id.value,
                    expected_latest_artifact_kind=(
                        EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND
                    ),
                    expected_latest_artifact_id=latest_draft["artifact_id"],
                    expected_latest_artifact_hash=latest_draft[
                        "content_hash"
                    ],
                    expected_latest_artifact_revision=latest_draft[
                        "revision"
                    ],
                    expected_state=DuetDesignState.REFINING.value,
                    expected_authority_head_approval_id=duet_row[
                        "authority_head_approval_id"
                    ],
                    state=DuetDesignState.REFINING.value,
                    event_type="refinement_candidate_rejected",
                    provenance=DuetProvenance.HOST_VALIDATION.value,
                    event_record={
                        "refinement_id": cycle["refinement_id"],
                        "artifact_id": artifact_id.value,
                        "deficit_codes": [item.code for item in deficits],
                    },
                )
                artifact = self.store.get_artifact(artifact_id.value)
                if artifact is None:
                    raise DuetProtocolError(
                        "invalid refinement candidate was not durably stored"
                    )
                return artifact

            normalized_blueprint = workflow_blueprint_from_spec(workflow)
            result_blueprint_hash = Sha256Digest.of_record(normalized_blueprint)
            before = _stable_workflow_record(frozen.workflow.as_record())
            after = _stable_workflow_record(workflow.as_record())
            changed_paths = tuple(sorted(_changed_paths(before, after)))
            directive_ids = tuple(
                item.directive_id
                for item in proposal.implementation_directives
            )
            decision_kind: RefinementChangeKind
            draft_spec: Optional[dict[str, Any]] = None
            successor_id: Optional[OpaqueId] = None
            successor_hash: Optional[Sha256Digest] = None
            if changed_paths:
                semantic_targets = self._semantic_targets(proposal)
                uncovered = [
                    path
                    for path in changed_paths
                    if not any(
                        _target_covers(target, path)
                        for target in semantic_targets
                    )
                ]
                if uncovered:
                    raise DuetProtocolError(
                        "semantic candidate changes unannotated targets: "
                        + ", ".join(uncovered)
                    )
                decision_kind = RefinementChangeKind.DESIGN_SEMANTIC
                record, successor_hash, successor_id = workflow_draft_record(
                    duet_id=duet_id,
                    revision=revision,
                    source_stage=refinement_source,
                    blueprint=normalized_blueprint,
                    workflow=workflow,
                    deficits=(),
                    refinement_id=OpaqueId(cycle["refinement_id"]),
                    baseline_id=baseline.baseline_id,
                    proposal_id=proposal.proposal_id,
                    human_note_ids=proposal.note_ids,
                )
                draft_spec = _artifact_spec(
                    artifact_id=successor_id,
                    duet_id=duet_id,
                    kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
                    revision=revision,
                    content_hash=successor_hash,
                    record=record,
                )
            else:
                if not directive_ids:
                    raise DuetProtocolError(
                        "unchanged workflow requires an implementation directive"
                    )
                decision_kind = RefinementChangeKind.IMPLEMENTATION_PRESERVING
            decision = RefinementDecision(
                duet_id=duet_id,
                refinement_id=OpaqueId(cycle["refinement_id"]),
                baseline_id=baseline.baseline_id,
                proposal_id=proposal.proposal_id,
                proposal_hash=proposal.content_hash,
                kind=decision_kind,
                baseline_workflow_hash=baseline.workflow_hash,
                result_workflow_hash=workflow.workflow_hash,
                result_blueprint_hash=result_blueprint_hash,
                changed_workflow_paths=changed_paths,
                implementation_directive_ids=directive_ids,
                successor_draft_artifact_id=successor_id,
                successor_draft_hash=successor_hash,
            )
            decision_spec = _artifact_spec(
                artifact_id=decision.decision_id,
                duet_id=duet_id,
                kind=REFINEMENT_DECISION_ARTIFACT_KIND,
                revision=int(cycle["ordinal"]),
                content_hash=decision.content_hash,
                record=decision.as_record(),
            )
            next_state = (
                DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value
                if decision_kind is RefinementChangeKind.DESIGN_SEMANTIC
                else DuetDesignState.AWAITING_REFINEMENT_APPROVAL.value
            )
            artifacts = (
                (decision_spec,)
                if draft_spec is None
                else (draft_spec, decision_spec)
            )
            self.store.attach_refinement_decision(
                refinement_id=cycle["refinement_id"],
                duet_id=duet_id.value,
                decision_artifact_id=decision.decision_id.value,
                artifacts=artifacts,
                expected_latest_artifact_kind=(
                    EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND
                ),
                expected_latest_artifact_id=latest_draft["artifact_id"],
                expected_latest_artifact_hash=latest_draft["content_hash"],
                expected_latest_artifact_revision=latest_draft["revision"],
                expected_authority_head_approval_id=(
                    baseline.authority_head_approval_id.value
                ),
                state=next_state,
                event_type="refinement_decision_recorded",
                provenance=DuetProvenance.HOST_VALIDATION.value,
                event_record={
                    "refinement_id": cycle["refinement_id"],
                    "decision_id": decision.decision_id.value,
                    "kind": decision.kind.value,
                    "changed_workflow_paths": list(changed_paths),
                    "implementation_directive_ids": [
                        item.value for item in directive_ids
                    ],
                },
            )
            result_id = successor_id or decision.decision_id
            artifact = self.store.get_artifact(result_id.value)
            if artifact is None:
                raise DuetProtocolError(
                    "refinement result was not durably stored"
                )
            return artifact

    def request(
        self,
        identity: DuetIdentity,
        *,
        baseline_id: str,
        candidate_workflow_architecture: Mapping[str, Any],
        human_note_ids: tuple[str, ...],
        implementation_directives: tuple[Mapping[str, str], ...],
    ) -> dict[str, Any]:
        self._assert_identity(identity)
        baseline = self.load_baseline(OpaqueId(baseline_id))
        if baseline.duet_id != identity.duet_id:
            raise DuetProtocolError("refinement baseline belongs to another Duet")
        selected_notes = []
        for value in human_note_ids:
            note = self.load_note(OpaqueId(value))
            if note.baseline_id != baseline.baseline_id:
                raise DuetProtocolError(
                    "refinement note belongs to another baseline"
                )
            selected_notes.append(note)
        notes_by_id = {note.note_id.value: note for note in selected_notes}
        if len(notes_by_id) != len(human_note_ids):
            raise ValueError("human_note_ids must be unique")
        directives = []
        for value in implementation_directives:
            if set(value) != {"human_note_id", "target_id", "instruction"}:
                raise ValueError(
                    "implementation directive has an invalid shape"
                )
            note = notes_by_id.get(value["human_note_id"])
            if note is None or note.target.target_id.value != value["target_id"]:
                raise DuetProtocolError(
                    "implementation directive is not grounded in its cited note"
                )
            directives.append(
                ImplementationDirective(
                    target=note.target,
                    instruction=value["instruction"],
                )
            )
        workflow, deficits = self.authority.validate_duet_workflow(
            identity.duet_id,
            candidate_workflow_architecture,
        )
        if workflow is None or deficits:
            return {
                "accepted": False,
                "reason": "workflow_admission_failed",
                "validation_deficits": [item.as_record() for item in deficits],
            }
        proposal = RefinementProposal(
            duet_id=identity.duet_id,
            baseline_id=baseline.baseline_id,
            summary=(
                "Apply the selected human workspace notes and exact "
                "implementation directives."
            ),
            note_ids=tuple(note.note_id for note in selected_notes),
            implementation_directives=tuple(directives),
        )
        self.record_proposal(proposal)
        cycle = self.begin(identity, proposal.proposal_id)
        try:
            _approval, frozen, _authority = (
                self.authority.verify_workflow_approval(
                    baseline.workflow_approval_id
                )
            )
            candidate = self.record_candidate(
                duet_id=identity.duet_id,
                workflow_blueprint=candidate_workflow_architecture,
                expected_workflow_hash=frozen.source_draft_hash.value,
                source_stage="duet",
            )
            candidate_record = candidate["record"]
            if (
                candidate["kind"] == EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND
                and not bool(candidate_record.get("ready"))
            ):
                self.close(
                    identity,
                    refinement_id=OpaqueId(cycle["refinement_id"]),
                    terminal_state=RefinementCycleState.CANCELLED,
                )
                return {
                    "accepted": False,
                    "reason": "workflow_admission_failed",
                    "validation_deficits": list(
                        candidate_record.get("validation_deficits") or ()
                    ),
                }
        except Exception:
            active = self.store.active_refinement_cycle(identity.duet_id.value)
            if (
                active is not None
                and active["refinement_id"] == cycle["refinement_id"]
                and active["state"] == RefinementCycleState.REFINING.value
            ):
                self.close(
                    identity,
                    refinement_id=OpaqueId(cycle["refinement_id"]),
                    terminal_state=RefinementCycleState.CANCELLED,
                )
            raise
        active = self.store.active_refinement_cycle(identity.duet_id.value)
        if (
            active is None
            or active["refinement_id"] != cycle["refinement_id"]
            or not isinstance(active.get("decision_artifact_id"), str)
        ):
            raise DuetProtocolError(
                "refinement candidate produced no exact host decision"
            )
        decision = self.load_decision(
            OpaqueId(active["decision_artifact_id"])
        )
        return {
            "accepted": True,
            "refinement_id": cycle["refinement_id"],
            "proposal_id": proposal.proposal_id.value,
            "decision_id": decision.decision_id.value,
            "decision_kind": decision.kind.value,
            "state": active["state"],
            "changed_workflow_paths": list(decision.changed_workflow_paths),
            "implementation_directive_ids": [
                value.value for value in decision.implementation_directive_ids
            ],
        }

    def close(
        self,
        identity: DuetIdentity,
        *,
        refinement_id: OpaqueId,
        terminal_state: RefinementCycleState,
    ) -> None:
        row = self._assert_identity(identity)
        if not isinstance(refinement_id, OpaqueId):
            raise TypeError("refinement_id must be an OpaqueId")
        if terminal_state not in {
            RefinementCycleState.REJECTED,
            RefinementCycleState.CANCELLED,
        }:
            raise ValueError("terminal refinement state is invalid")
        cycle = self.store.active_refinement_cycle(identity.duet_id.value)
        if (
            cycle is None
            or cycle["refinement_id"] != refinement_id.value
        ):
            raise DuetProtocolError("Duet has no active refinement")
        if row["authority_head_approval_id"] != cycle[
            "baseline_authority_head_approval_id"
        ]:
            raise DuetProtocolError("refinement baseline authority is stale")
        self.store.close_refinement_cycle(
            refinement_id=cycle["refinement_id"],
            duet_id=identity.duet_id.value,
            expected_authority_head_approval_id=cycle[
                "baseline_authority_head_approval_id"
            ],
            terminal_state=terminal_state.value,
            event_type=f"refinement_{terminal_state.value}",
            provenance=DuetProvenance.HUMAN_INPUT.value,
            event_record={
                "refinement_id": cycle["refinement_id"],
                "terminal_state": terminal_state.value,
            },
        )

    def read_artifact(
        self,
        duet_id: OpaqueId,
        artifact_id: OpaqueId,
    ) -> dict[str, Any]:
        artifact = self.store.get_artifact(artifact_id.value)
        allowed = {
            REFINEMENT_BASELINE_ARTIFACT_KIND,
            WORKSPACE_NOTE_ARTIFACT_KIND,
            REFINEMENT_PROPOSAL_ARTIFACT_KIND,
            REFINEMENT_DECISION_ARTIFACT_KIND,
        }
        if (
            artifact is None
            or artifact["duet_id"] != duet_id.value
            or artifact["kind"] not in allowed
        ):
            raise DuetNotFoundError(
                "refinement artifact not found for this Duet"
            )
        loaders = {
            REFINEMENT_BASELINE_ARTIFACT_KIND: RefinementBaseline.from_record,
            WORKSPACE_NOTE_ARTIFACT_KIND: DuetWorkspaceNote.from_record,
            REFINEMENT_PROPOSAL_ARTIFACT_KIND: RefinementProposal.from_record,
            REFINEMENT_DECISION_ARTIFACT_KIND: RefinementDecision.from_record,
        }
        try:
            parsed = loaders[artifact["kind"]](artifact["record"])
        except (TypeError, ValueError) as exc:
            raise DuetProtocolError(
                "stored refinement artifact is malformed"
            ) from exc
        if parsed.content_hash.value != artifact["content_hash"]:
            raise DuetProtocolError("refinement artifact hash is stale")
        return {
            "artifact_id": artifact["artifact_id"],
            "kind": artifact["kind"],
            "revision": artifact["revision"],
            "content_hash": artifact["content_hash"],
            "record": parsed.as_record(),
        }

    def approved_chain(
        self,
        decision: RefinementDecision,
    ) -> tuple[
        RefinementBaseline,
        RefinementProposal,
        tuple[DuetWorkspaceNote, ...],
    ]:
        persisted = self.load_decision(decision.decision_id)
        if persisted.as_record() != decision.as_record():
            raise DuetProtocolError(
                "current refinement decision differs from its authority chain"
            )
        baseline = self.load_baseline(decision.baseline_id)
        proposal = self.load_proposal(decision.proposal_id)
        if proposal.content_hash != decision.proposal_hash:
            raise DuetProtocolError(
                "current refinement proposal differs from its decision"
            )
        notes = tuple(self.load_note(note_id) for note_id in proposal.note_ids)
        return baseline, proposal, notes


__all__ = [
    "EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND",
    "IterativeEpisodeRefiner",
    "MATERIALIZED_SPECIFICATION_ARTIFACT_KIND",
    "REFINEMENT_BASELINE_ARTIFACT_KIND",
    "REFINEMENT_DECISION_ARTIFACT_KIND",
    "REFINEMENT_PROPOSAL_ARTIFACT_KIND",
    "RUN_EVIDENCE_ARTIFACT_KIND",
    "RefinementAuthorityReader",
    "WORKSPACE_NOTE_ARTIFACT_KIND",
    "WORKSPACE_NOTE_SUBMISSION_ARTIFACT_KIND",
]
