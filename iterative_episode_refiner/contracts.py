"""Immutable contracts for iteratively refining one materialized workflow.

The refinement workspace is descriptive until a human approves an exact
decision.  Notes and proposals never grant execution authority.  A baseline
binds the currently approved workflow to one exact materialized build; run
evidence is optional because a human may annotate and refine a build without
first registering a Run.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional

from agent.duet_contracts import (
    DuetApproval,
    FrozenDuetWorkflow,
    WorkflowAdmissionAuthority,
    content_id,
    digest_record,
)
from agent.episode_contracts import OpaqueId, Sha256Digest


def _mapping(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} has an invalid shape")
    return value


def _text(value: object, name: str, *, maximum: int = 8192) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be non-empty text without NUL bytes")
    if len(value) > maximum:
        raise ValueError(f"{name} must be at most {maximum} characters")
    return value


def _opaque(value: object, name: str) -> OpaqueId:
    if not isinstance(value, OpaqueId):
        raise ValueError(f"{name} must be an OpaqueId")
    return value


def _digest(value: object, name: str) -> Sha256Digest:
    if not isinstance(value, Sha256Digest):
        raise ValueError(f"{name} must be a Sha256Digest")
    return value


def _opaque_tuple(value: object, name: str) -> tuple[OpaqueId, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be a tuple")
    result = tuple(_opaque(item, name) for item in value)
    if len({item.value for item in result}) != len(result):
        raise ValueError(f"{name} must contain unique identities")
    return result


def _json_pointer(value: object, name: str) -> str:
    if not isinstance(value, str) or "\x00" in value or len(value) > 2048:
        raise ValueError(f"{name} must be a bounded JSON pointer")
    if value and not value.startswith("/"):
        raise ValueError(f"{name} must be empty or start with '/'")
    return value


def _optional_opaque(value: object, name: str) -> Optional[OpaqueId]:
    if value is None:
        return None
    return _opaque(value, name)


def _optional_digest(value: object, name: str) -> Optional[Sha256Digest]:
    if value is None:
        return None
    return _digest(value, name)


class RefinementTargetLayer(str, Enum):
    WORKFLOW_SEMANTICS = "workflow_semantics"
    MATERIALIZATION_IMPLEMENTATION = "materialization_implementation"


class RefinementChangeKind(str, Enum):
    DESIGN_SEMANTIC = "design_semantic"
    IMPLEMENTATION_PRESERVING = "implementation_preserving"


class RefinementCycleState(str, Enum):
    REFINING = "refining"
    AWAITING_WORKFLOW_APPROVAL = "awaiting_workflow_approval"
    AWAITING_REFINEMENT_APPROVAL = "awaiting_refinement_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RefinementBaseline:
    """Exact approved workflow/build pair from which refinement starts."""

    duet_id: OpaqueId
    authority_head_approval_id: OpaqueId
    workflow_approval_id: OpaqueId
    frozen_workflow_artifact_id: OpaqueId
    workflow_hash: Sha256Digest
    build_request_id: OpaqueId
    build_attempt_id: OpaqueId
    build_receipt_id: OpaqueId
    build_receipt_hash: Sha256Digest
    materialized_specification_id: OpaqueId
    materialized_specification_hash: Sha256Digest
    build_manifest_id: Optional[OpaqueId] = None
    build_manifest_hash: Optional[Sha256Digest] = None
    run_evidence_artifact_id: Optional[OpaqueId] = None
    run_evidence_hash: Optional[Sha256Digest] = None

    def __post_init__(self) -> None:
        for name in (
            "duet_id",
            "authority_head_approval_id",
            "workflow_approval_id",
            "frozen_workflow_artifact_id",
            "build_request_id",
            "build_attempt_id",
            "build_receipt_id",
            "materialized_specification_id",
        ):
            _opaque(getattr(self, name), name)
        _digest(self.workflow_hash, "workflow_hash")
        _digest(self.build_receipt_hash, "build_receipt_hash")
        _digest(
            self.materialized_specification_hash,
            "materialized_specification_hash",
        )
        manifest_id = _optional_opaque(
            self.build_manifest_id,
            "build_manifest_id",
        )
        manifest_hash = _optional_digest(
            self.build_manifest_hash,
            "build_manifest_hash",
        )
        if (manifest_id is None) != (manifest_hash is None):
            raise ValueError(
                "build manifest identity and hash must both be present or absent"
            )
        evidence_id = _optional_opaque(
            self.run_evidence_artifact_id,
            "run_evidence_artifact_id",
        )
        evidence_hash = _optional_digest(
            self.run_evidence_hash,
            "run_evidence_hash",
        )
        if (evidence_id is None) != (evidence_hash is None):
            raise ValueError(
                "run evidence identity and hash must both be present or absent"
            )

    def identity_record(self) -> dict[str, Any]:
        return {
            "duet_id": self.duet_id.value,
            "authority_head_approval_id": self.authority_head_approval_id.value,
            "workflow_approval_id": self.workflow_approval_id.value,
            "frozen_workflow_artifact_id": (
                self.frozen_workflow_artifact_id.value
            ),
            "workflow_hash": self.workflow_hash.value,
            "build_request_id": self.build_request_id.value,
            "build_attempt_id": self.build_attempt_id.value,
            "build_receipt_id": self.build_receipt_id.value,
            "build_receipt_hash": self.build_receipt_hash.value,
            "materialized_specification_id": (
                self.materialized_specification_id.value
            ),
            "materialized_specification_hash": (
                self.materialized_specification_hash.value
            ),
            "build_manifest_id": (
                None
                if self.build_manifest_id is None
                else self.build_manifest_id.value
            ),
            "build_manifest_hash": (
                None
                if self.build_manifest_hash is None
                else self.build_manifest_hash.value
            ),
            "run_evidence_artifact_id": (
                None
                if self.run_evidence_artifact_id is None
                else self.run_evidence_artifact_id.value
            ),
            "run_evidence_hash": (
                None
                if self.run_evidence_hash is None
                else self.run_evidence_hash.value
            ),
        }

    @property
    def baseline_id(self) -> OpaqueId:
        return content_id("refinement_baseline", self.identity_record())

    @property
    def content_hash(self) -> Sha256Digest:
        return digest_record(self.identity_record())

    def as_record(self) -> dict[str, Any]:
        return {
            "baseline_id": self.baseline_id.value,
            "content_hash": self.content_hash.value,
            **self.identity_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "RefinementBaseline":
        record = _mapping(
            value,
            {
                "baseline_id",
                "content_hash",
                "duet_id",
                "authority_head_approval_id",
                "workflow_approval_id",
                "frozen_workflow_artifact_id",
                "workflow_hash",
                "build_request_id",
                "build_attempt_id",
                "build_receipt_id",
                "build_receipt_hash",
                "materialized_specification_id",
                "materialized_specification_hash",
                "build_manifest_id",
                "build_manifest_hash",
                "run_evidence_artifact_id",
                "run_evidence_hash",
            },
            "refinement baseline",
        )
        baseline = cls(
            duet_id=OpaqueId(record["duet_id"]),
            authority_head_approval_id=OpaqueId(
                record["authority_head_approval_id"]
            ),
            workflow_approval_id=OpaqueId(record["workflow_approval_id"]),
            frozen_workflow_artifact_id=OpaqueId(
                record["frozen_workflow_artifact_id"]
            ),
            workflow_hash=Sha256Digest(record["workflow_hash"]),
            build_request_id=OpaqueId(record["build_request_id"]),
            build_attempt_id=OpaqueId(record["build_attempt_id"]),
            build_receipt_id=OpaqueId(record["build_receipt_id"]),
            build_receipt_hash=Sha256Digest(record["build_receipt_hash"]),
            materialized_specification_id=OpaqueId(
                record["materialized_specification_id"]
            ),
            materialized_specification_hash=Sha256Digest(
                record["materialized_specification_hash"]
            ),
            build_manifest_id=(
                None
                if record["build_manifest_id"] is None
                else OpaqueId(record["build_manifest_id"])
            ),
            build_manifest_hash=(
                None
                if record["build_manifest_hash"] is None
                else Sha256Digest(record["build_manifest_hash"])
            ),
            run_evidence_artifact_id=(
                None
                if record["run_evidence_artifact_id"] is None
                else OpaqueId(record["run_evidence_artifact_id"])
            ),
            run_evidence_hash=(
                None
                if record["run_evidence_hash"] is None
                else Sha256Digest(record["run_evidence_hash"])
            ),
        )
        if (
            baseline.baseline_id.value != record["baseline_id"]
            or baseline.content_hash.value != record["content_hash"]
        ):
            raise ValueError("refinement baseline identity is stale")
        return baseline


@dataclass(frozen=True)
class RefinementTarget:
    """Host-captured exact artifact location to which prose or a directive applies."""

    layer: RefinementTargetLayer
    artifact_id: OpaqueId
    artifact_hash: Sha256Digest
    json_pointer: str
    episode_local_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.layer, RefinementTargetLayer):
            raise ValueError("layer must be a RefinementTargetLayer")
        _opaque(self.artifact_id, "artifact_id")
        _digest(self.artifact_hash, "artifact_hash")
        object.__setattr__(
            self,
            "json_pointer",
            _json_pointer(self.json_pointer, "json_pointer"),
        )
        if self.episode_local_id is not None:
            object.__setattr__(
                self,
                "episode_local_id",
                _text(
                    self.episode_local_id,
                    "episode_local_id",
                    maximum=256,
                ),
            )

    def identity_record(self) -> dict[str, Any]:
        return {
            "layer": self.layer.value,
            "artifact_id": self.artifact_id.value,
            "artifact_hash": self.artifact_hash.value,
            "json_pointer": self.json_pointer,
            "episode_local_id": self.episode_local_id,
        }

    @property
    def target_id(self) -> OpaqueId:
        return content_id("refinement_target", self.identity_record())

    @property
    def content_hash(self) -> Sha256Digest:
        return digest_record(self.identity_record())

    def as_record(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id.value,
            "content_hash": self.content_hash.value,
            **self.identity_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "RefinementTarget":
        record = _mapping(
            value,
            {
                "target_id",
                "content_hash",
                "layer",
                "artifact_id",
                "artifact_hash",
                "json_pointer",
                "episode_local_id",
            },
            "refinement target",
        )
        try:
            layer = RefinementTargetLayer(record["layer"])
        except (TypeError, ValueError) as exc:
            raise ValueError("refinement target layer is invalid") from exc
        target = cls(
            layer=layer,
            artifact_id=OpaqueId(record["artifact_id"]),
            artifact_hash=Sha256Digest(record["artifact_hash"]),
            json_pointer=record["json_pointer"],
            episode_local_id=record["episode_local_id"],
        )
        if (
            target.target_id.value != record["target_id"]
            or target.content_hash.value != record["content_hash"]
        ):
            raise ValueError("refinement target identity is stale")
        return target


@dataclass(frozen=True)
class DuetWorkspaceNote:
    """Immutable human prose anchored to one exact persisted workspace part.

    ``baseline_id`` is absent while the Duet is assembling its first mutable
    Architecture.  Once a build attempt exists, it binds the note to the exact
    refinement baseline shown beside the Architecture and Materialized views.
    """

    duet_id: OpaqueId
    baseline_id: Optional[OpaqueId]
    human_authority_id: OpaqueId
    body: str
    target: RefinementTarget

    def __post_init__(self) -> None:
        _opaque(self.duet_id, "duet_id")
        _optional_opaque(self.baseline_id, "baseline_id")
        _opaque(self.human_authority_id, "human_authority_id")
        object.__setattr__(
            self,
            "body",
            _text(self.body, "body", maximum=32768),
        )
        if not isinstance(self.target, RefinementTarget):
            raise ValueError("target must be a RefinementTarget")

    def identity_record(self) -> dict[str, Any]:
        return {
            "duet_id": self.duet_id.value,
            "baseline_id": (
                None if self.baseline_id is None else self.baseline_id.value
            ),
            "human_authority_id": self.human_authority_id.value,
            "body": self.body,
            "target": self.target.as_record(),
        }

    @property
    def note_id(self) -> OpaqueId:
        return content_id("workspace_note", self.identity_record())

    @property
    def content_hash(self) -> Sha256Digest:
        return digest_record(self.identity_record())

    def as_record(self) -> dict[str, Any]:
        return {
            "note_id": self.note_id.value,
            "content_hash": self.content_hash.value,
            **self.identity_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "DuetWorkspaceNote":
        record = _mapping(
            value,
            {
                "note_id",
                "content_hash",
                "duet_id",
                "baseline_id",
                "human_authority_id",
                "body",
                "target",
            },
            "Duet workspace note",
        )
        note = cls(
            duet_id=OpaqueId(record["duet_id"]),
            baseline_id=(
                None
                if record["baseline_id"] is None
                else OpaqueId(record["baseline_id"])
            ),
            human_authority_id=OpaqueId(record["human_authority_id"]),
            body=record["body"],
            target=RefinementTarget.from_record(record["target"]),
        )
        if (
            note.note_id.value != record["note_id"]
            or note.content_hash.value != record["content_hash"]
        ):
            raise ValueError("Duet workspace note identity is stale")
        return note


@dataclass(frozen=True)
class ImplementationDirective:
    """Approved-candidate instruction for one exact materialization target."""

    target: RefinementTarget
    instruction: str

    def __post_init__(self) -> None:
        if not isinstance(self.target, RefinementTarget):
            raise ValueError("target must be a RefinementTarget")
        if self.target.layer is not RefinementTargetLayer.MATERIALIZATION_IMPLEMENTATION:
            raise ValueError("implementation directive target has the wrong layer")
        object.__setattr__(
            self,
            "instruction",
            _text(self.instruction, "instruction", maximum=16384),
        )

    def identity_record(self) -> dict[str, Any]:
        return {
            "target": self.target.as_record(),
            "instruction": self.instruction,
        }

    @property
    def directive_id(self) -> OpaqueId:
        return content_id("implementation_directive", self.identity_record())

    @property
    def content_hash(self) -> Sha256Digest:
        return digest_record(self.identity_record())

    def as_record(self) -> dict[str, Any]:
        return {
            "directive_id": self.directive_id.value,
            "content_hash": self.content_hash.value,
            **self.identity_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "ImplementationDirective":
        record = _mapping(
            value,
            {"directive_id", "content_hash", "target", "instruction"},
            "implementation directive",
        )
        directive = cls(
            target=RefinementTarget.from_record(record["target"]),
            instruction=record["instruction"],
        )
        if (
            directive.directive_id.value != record["directive_id"]
            or directive.content_hash.value != record["content_hash"]
        ):
            raise ValueError("implementation directive identity is stale")
        return directive


@dataclass(frozen=True)
class RefinementProposal:
    """Immutable selection of workspace notes and implementation directives."""

    duet_id: OpaqueId
    baseline_id: OpaqueId
    summary: str
    note_ids: tuple[OpaqueId, ...]
    implementation_directives: tuple[ImplementationDirective, ...] = ()

    def __post_init__(self) -> None:
        _opaque(self.duet_id, "duet_id")
        _opaque(self.baseline_id, "baseline_id")
        object.__setattr__(
            self,
            "summary",
            _text(self.summary, "summary", maximum=16384),
        )
        note_ids = _opaque_tuple(self.note_ids, "note_ids")
        directives = self.implementation_directives
        if not isinstance(directives, tuple) or any(
            not isinstance(item, ImplementationDirective) for item in directives
        ):
            raise ValueError(
                "implementation_directives must be a tuple of directives"
            )
        directive_ids = [item.directive_id.value for item in directives]
        if len(set(directive_ids)) != len(directive_ids):
            raise ValueError("implementation directives must be unique")
        if not note_ids and not directives:
            raise ValueError("refinement proposal must select a note or directive")
        object.__setattr__(self, "note_ids", note_ids)

    def identity_record(self) -> dict[str, Any]:
        return {
            "duet_id": self.duet_id.value,
            "baseline_id": self.baseline_id.value,
            "summary": self.summary,
            "note_ids": [item.value for item in self.note_ids],
            "implementation_directives": [
                item.as_record() for item in self.implementation_directives
            ],
        }

    @property
    def proposal_id(self) -> OpaqueId:
        return content_id("refinement_proposal", self.identity_record())

    @property
    def content_hash(self) -> Sha256Digest:
        return digest_record(self.identity_record())

    def as_record(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id.value,
            "content_hash": self.content_hash.value,
            **self.identity_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "RefinementProposal":
        record = _mapping(
            value,
            {
                "proposal_id",
                "content_hash",
                "duet_id",
                "baseline_id",
                "summary",
                "note_ids",
                "implementation_directives",
            },
            "refinement proposal",
        )
        note_ids = record["note_ids"]
        directives = record["implementation_directives"]
        if not isinstance(note_ids, list) or not isinstance(directives, list):
            raise ValueError("refinement proposal arrays are malformed")
        proposal = cls(
            duet_id=OpaqueId(record["duet_id"]),
            baseline_id=OpaqueId(record["baseline_id"]),
            summary=record["summary"],
            note_ids=tuple(OpaqueId(item) for item in note_ids),
            implementation_directives=tuple(
                ImplementationDirective.from_record(item) for item in directives
            ),
        )
        if (
            proposal.proposal_id.value != record["proposal_id"]
            or proposal.content_hash.value != record["content_hash"]
        ):
            raise ValueError("refinement proposal identity is stale")
        return proposal


@dataclass(frozen=True)
class RefinementDecision:
    """Host-classified exact result of applying one refinement proposal."""

    duet_id: OpaqueId
    refinement_id: OpaqueId
    baseline_id: OpaqueId
    proposal_id: OpaqueId
    proposal_hash: Sha256Digest
    kind: RefinementChangeKind
    baseline_workflow_hash: Sha256Digest
    result_workflow_hash: Sha256Digest
    result_blueprint_hash: Sha256Digest
    changed_workflow_paths: tuple[str, ...]
    implementation_directive_ids: tuple[OpaqueId, ...]
    successor_draft_artifact_id: Optional[OpaqueId] = None
    successor_draft_hash: Optional[Sha256Digest] = None

    def __post_init__(self) -> None:
        for name in (
            "duet_id",
            "refinement_id",
            "baseline_id",
            "proposal_id",
        ):
            _opaque(getattr(self, name), name)
        for name in (
            "proposal_hash",
            "baseline_workflow_hash",
            "result_workflow_hash",
            "result_blueprint_hash",
        ):
            _digest(getattr(self, name), name)
        if not isinstance(self.kind, RefinementChangeKind):
            raise ValueError("kind must be a RefinementChangeKind")
        if not isinstance(self.changed_workflow_paths, tuple):
            raise ValueError("changed_workflow_paths must be a tuple")
        paths = tuple(
            _json_pointer(item, "changed_workflow_paths")
            for item in self.changed_workflow_paths
        )
        if any(not item for item in paths):
            raise ValueError("changed workflow paths cannot name the whole record")
        if tuple(sorted(set(paths))) != paths:
            raise ValueError("changed_workflow_paths must be sorted and unique")
        directive_ids = _opaque_tuple(
            self.implementation_directive_ids,
            "implementation_directive_ids",
        )
        successor_id = _optional_opaque(
            self.successor_draft_artifact_id,
            "successor_draft_artifact_id",
        )
        successor_hash = _optional_digest(
            self.successor_draft_hash,
            "successor_draft_hash",
        )
        if (successor_id is None) != (successor_hash is None):
            raise ValueError(
                "successor draft identity and hash must both be present or absent"
            )
        if self.kind is RefinementChangeKind.DESIGN_SEMANTIC:
            if self.baseline_workflow_hash == self.result_workflow_hash:
                raise ValueError("semantic decision must change the workflow")
            if not paths or successor_id is None:
                raise ValueError(
                    "semantic decision requires changed paths and a successor draft"
                )
        else:
            if self.baseline_workflow_hash != self.result_workflow_hash:
                raise ValueError(
                    "implementation-preserving decision cannot change the workflow"
                )
            if paths or successor_id is not None:
                raise ValueError(
                    "implementation-preserving decision cannot create a workflow draft"
                )
            if not directive_ids:
                raise ValueError(
                    "implementation-preserving decision requires a directive"
                )

    def identity_record(self) -> dict[str, Any]:
        return {
            "duet_id": self.duet_id.value,
            "refinement_id": self.refinement_id.value,
            "baseline_id": self.baseline_id.value,
            "proposal_id": self.proposal_id.value,
            "proposal_hash": self.proposal_hash.value,
            "kind": self.kind.value,
            "baseline_workflow_hash": self.baseline_workflow_hash.value,
            "result_workflow_hash": self.result_workflow_hash.value,
            "result_blueprint_hash": self.result_blueprint_hash.value,
            "changed_workflow_paths": list(self.changed_workflow_paths),
            "implementation_directive_ids": [
                item.value for item in self.implementation_directive_ids
            ],
            "successor_draft_artifact_id": (
                None
                if self.successor_draft_artifact_id is None
                else self.successor_draft_artifact_id.value
            ),
            "successor_draft_hash": (
                None
                if self.successor_draft_hash is None
                else self.successor_draft_hash.value
            ),
        }

    @property
    def decision_id(self) -> OpaqueId:
        return content_id("refinement_decision", self.identity_record())

    @property
    def content_hash(self) -> Sha256Digest:
        return digest_record(self.identity_record())

    def as_record(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id.value,
            "content_hash": self.content_hash.value,
            **self.identity_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "RefinementDecision":
        record = _mapping(
            value,
            {
                "decision_id",
                "content_hash",
                "duet_id",
                "refinement_id",
                "baseline_id",
                "proposal_id",
                "proposal_hash",
                "kind",
                "baseline_workflow_hash",
                "result_workflow_hash",
                "result_blueprint_hash",
                "changed_workflow_paths",
                "implementation_directive_ids",
                "successor_draft_artifact_id",
                "successor_draft_hash",
            },
            "refinement decision",
        )
        changed_paths = record["changed_workflow_paths"]
        directive_ids = record["implementation_directive_ids"]
        if not isinstance(changed_paths, list) or not isinstance(
            directive_ids,
            list,
        ):
            raise ValueError("refinement decision arrays are malformed")
        try:
            kind = RefinementChangeKind(record["kind"])
        except (TypeError, ValueError) as exc:
            raise ValueError("refinement decision kind is invalid") from exc
        decision = cls(
            duet_id=OpaqueId(record["duet_id"]),
            refinement_id=OpaqueId(record["refinement_id"]),
            baseline_id=OpaqueId(record["baseline_id"]),
            proposal_id=OpaqueId(record["proposal_id"]),
            proposal_hash=Sha256Digest(record["proposal_hash"]),
            kind=kind,
            baseline_workflow_hash=Sha256Digest(
                record["baseline_workflow_hash"]
            ),
            result_workflow_hash=Sha256Digest(record["result_workflow_hash"]),
            result_blueprint_hash=Sha256Digest(
                record["result_blueprint_hash"]
            ),
            changed_workflow_paths=tuple(changed_paths),
            implementation_directive_ids=tuple(
                OpaqueId(item) for item in directive_ids
            ),
            successor_draft_artifact_id=(
                None
                if record["successor_draft_artifact_id"] is None
                else OpaqueId(record["successor_draft_artifact_id"])
            ),
            successor_draft_hash=(
                None
                if record["successor_draft_hash"] is None
                else Sha256Digest(record["successor_draft_hash"])
            ),
        )
        if (
            decision.decision_id.value != record["decision_id"]
            or decision.content_hash.value != record["content_hash"]
        ):
            raise ValueError("refinement decision identity is stale")
        return decision


@dataclass(frozen=True)
class CurrentBuildAuthorization:
    """Current authority head resolved to its exact workflow/refinement chain."""

    authority_approval: DuetApproval
    workflow_approval: DuetApproval
    frozen_workflow: FrozenDuetWorkflow
    admission_authority: WorkflowAdmissionAuthority
    refinement_decision: Optional[RefinementDecision]


__all__ = [
    "CurrentBuildAuthorization",
    "DuetWorkspaceNote",
    "ImplementationDirective",
    "RefinementBaseline",
    "RefinementChangeKind",
    "RefinementCycleState",
    "RefinementDecision",
    "RefinementProposal",
    "RefinementTarget",
    "RefinementTargetLayer",
]
