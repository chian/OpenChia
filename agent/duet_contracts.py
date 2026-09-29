"""Typed authority and message contracts for the OpenChia Duet.

The Duet is the human--LLM collaboration that commissions Creator Episodes.
It is deliberately not an Episode.  These records keep human authority,
model proposals, host validation, and Episode execution as separate facts.
Only closed, JSON-shaped records cross from Creator Episodes back into the
Duet conversation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Optional

from agent.episode_contracts import (
    EpisodeCreationSpec,
    EpisodeWorkflowDesignProjection,
    EpisodeWorkflowSpec,
    OpaqueId,
    Sha256Digest,
)


DUET_SCHEMA_VERSION = 1
DEFAULT_CREATOR_PROPOSAL_BOUND = 8

_FIELD_PATH = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_CODE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")


def _text(value: object, name: str, *, maximum: int = 8192) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be non-empty text without NUL bytes")
    if len(value) > maximum:
        raise ValueError(f"{name} must be at most {maximum} characters")
    return value


def _identifier(value: object, name: str) -> str:
    value = _text(value, name, maximum=128)
    if _CODE.fullmatch(value) is None:
        raise ValueError(f"{name} has an invalid identifier shape")
    return value


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _json_value(value: object, name: str = "value") -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{name} contains a non-string key")
            result[key] = _json_value(item, f"{name}.{key}")
        return result
    if isinstance(value, (tuple, list)):
        return [_json_value(item, f"{name}[]") for item in value]
    raise ValueError(f"{name} contains a non-JSON value")


def canonical_json(value: object) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be a tuple")
    result = tuple(_identifier(item, name) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must contain unique values")
    return result


def _opaque(value: object, name: str) -> OpaqueId:
    if not isinstance(value, OpaqueId):
        raise ValueError(f"{name} must be an OpaqueId")
    return value


class DuetProvenance(str, Enum):
    HUMAN_INPUT = "human_input"
    LLM_PROPOSAL = "llm_proposal"
    HOST_VALIDATION = "host_validation"
    HUMAN_APPROVAL = "human_approval"


class DuetDesignState(str, Enum):
    COLLECTING_CONTRACT = "collecting_contract"
    NEEDS_DUET_INPUT = "needs_duet_input"
    CONTRACT_CANDIDATE = "contract_candidate"
    AWAITING_CREATOR_APPROVAL = "awaiting_creator_approval"
    CREATOR_ADMITTED = "creator_admitted"
    DESIGNING = "designing"
    WAITING_ON_DUET = "waiting_on_duet"
    VALIDATING_WORKFLOW = "validating_workflow"
    EXPERIMENTING = "experimenting"
    REFINING = "refining"
    AWAITING_WORKFLOW_APPROVAL = "awaiting_workflow_approval"
    SEALED = "sealed"
    LAUNCHED = "launched"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    NO_PROGRESS = "no_progress"
    BOUND_HIT = "bound_hit"
    FAILED = "failed"


class ApprovalKind(str, Enum):
    CREATOR_CONTRACT = "creator_contract"
    WORKFLOW = "workflow"


class DuetMessageKind(str, Enum):
    ANSWER = "answer"
    OVERRIDE = "override"
    PAUSE = "pause"
    CANCEL = "cancel"
    RETRY = "retry"


class CreatorLaunchState(str, Enum):
    """Closed acknowledgement from the task-specific Creator launcher."""

    LAUNCHED = "launched"
    RUNNING = "running"
    COMPLETED = "completed"


class FieldImpact(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


DUET_SEARCH_TOOLS = frozenset({"web_search", "web_extract"})
DUET_PROTOCOL_TOOLS = frozenset(
    {
        "duet_contract_patch",
        "duet_contract_review",
        "duet_status",
        "duet_answer",
        "duet_decision",
        "episode_creator",
    }
)
DUET_ALLOWED_TOOLS = DUET_SEARCH_TOOLS | DUET_PROTOCOL_TOOLS
DUET_FORBIDDEN_TOOLS = frozenset(
    {
        "terminal",
        "process_manage",
        "read_file",
        "write_file",
        "patch",
        "search_files",
        "execute_code",
        "delegate_task",
        "skill_manage",
        "manage_catalog",
        "tool_search",
        "tool_call",
    }
)


@dataclass(frozen=True)
class DuetIdentity:
    duet_id: OpaqueId
    human_authority_id: OpaqueId
    policy_id: OpaqueId
    conversation_id: OpaqueId

    def __post_init__(self) -> None:
        for name in (
            "duet_id",
            "human_authority_id",
            "policy_id",
            "conversation_id",
        ):
            _opaque(getattr(self, name), name)

    def as_record(self) -> dict[str, str]:
        return {
            "duet_id": self.duet_id.value,
            "human_authority_id": self.human_authority_id.value,
            "policy_id": self.policy_id.value,
            "conversation_id": self.conversation_id.value,
        }


@dataclass(frozen=True)
class DuetPolicy:
    policy_id: OpaqueId
    capability_allowlist: tuple[str, ...] = tuple(sorted(DUET_ALLOWED_TOOLS))
    minimum_method_credit: float = 0.0
    creator_proposal_bound: int = DEFAULT_CREATOR_PROPOSAL_BOUND
    maximum_creator_depth: int = 1

    def __post_init__(self) -> None:
        _opaque(self.policy_id, "policy_id")
        allowlist = _string_tuple(self.capability_allowlist, "capability_allowlist")
        unknown = set(allowlist) - DUET_ALLOWED_TOOLS
        forbidden = set(allowlist) & DUET_FORBIDDEN_TOOLS
        if unknown or forbidden:
            raise ValueError(
                "Duet capability allowlist exceeds the host-owned surface: "
                f"{sorted(unknown | forbidden)}"
            )
        object.__setattr__(self, "capability_allowlist", allowlist)
        credit = _number(self.minimum_method_credit, "minimum_method_credit")
        if not 0 <= credit <= 1:
            raise ValueError("minimum_method_credit must lie in [0, 1]")
        object.__setattr__(self, "minimum_method_credit", credit)
        object.__setattr__(
            self,
            "creator_proposal_bound",
            _integer(self.creator_proposal_bound, "creator_proposal_bound", minimum=1),
        )
        object.__setattr__(
            self,
            "maximum_creator_depth",
            _integer(self.maximum_creator_depth, "maximum_creator_depth", minimum=1),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id.value,
            "capability_allowlist": list(self.capability_allowlist),
            "minimum_method_credit": self.minimum_method_credit,
            "creator_proposal_bound": self.creator_proposal_bound,
            "maximum_creator_depth": self.maximum_creator_depth,
        }


@dataclass(frozen=True)
class ContractFieldRecord:
    field_path: str
    value: Any
    provenance: DuetProvenance
    source_ids: tuple[OpaqueId, ...] = ()
    validation_codes: tuple[str, ...] = ()
    approved: bool = False
    impact: FieldImpact = FieldImpact.MEDIUM

    def __post_init__(self) -> None:
        path = _text(self.field_path, "field_path", maximum=256)
        if _FIELD_PATH.fullmatch(path) is None:
            raise ValueError("field_path must be a dotted lowercase identifier")
        object.__setattr__(self, "field_path", path)
        object.__setattr__(self, "value", _json_value(self.value, path))
        if not isinstance(self.provenance, DuetProvenance):
            raise ValueError("provenance must be a DuetProvenance")
        if not isinstance(self.source_ids, tuple) or any(
            not isinstance(item, OpaqueId) for item in self.source_ids
        ):
            raise ValueError("source_ids must be a tuple of OpaqueIds")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids must be unique")
        codes = _string_tuple(self.validation_codes, "validation_codes")
        object.__setattr__(self, "validation_codes", codes)
        if not isinstance(self.approved, bool):
            raise ValueError("approved must be boolean")
        if not isinstance(self.impact, FieldImpact):
            raise ValueError("impact must be a FieldImpact")

    @property
    def human_fixed(self) -> bool:
        return self.provenance is DuetProvenance.HUMAN_INPUT or self.approved

    def as_record(self) -> dict[str, Any]:
        return {
            "field_path": self.field_path,
            "value": self.value,
            "provenance": self.provenance.value,
            "source_ids": [item.value for item in self.source_ids],
            "validation_codes": list(self.validation_codes),
            "approved": self.approved,
            "impact": self.impact.value,
        }


@dataclass(frozen=True)
class ContractDeficit:
    code: str
    field_path: str
    blocking: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _identifier(self.code, "code"))
        if _FIELD_PATH.fullmatch(self.field_path) is None:
            raise ValueError("deficit field_path is invalid")
        if not isinstance(self.blocking, bool):
            raise ValueError("blocking must be boolean")

    def as_record(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field_path": self.field_path,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class CreatorContractDraft:
    draft_id: OpaqueId
    duet_id: OpaqueId
    revision: int
    fields: tuple[ContractFieldRecord, ...]
    deficits: tuple[ContractDeficit, ...] = ()

    def __post_init__(self) -> None:
        _opaque(self.draft_id, "draft_id")
        _opaque(self.duet_id, "duet_id")
        object.__setattr__(self, "revision", _integer(self.revision, "revision"))
        if not isinstance(self.fields, tuple) or any(
            not isinstance(item, ContractFieldRecord) for item in self.fields
        ):
            raise ValueError("fields must contain ContractFieldRecord values")
        paths = tuple(item.field_path for item in self.fields)
        if len(set(paths)) != len(paths):
            raise ValueError("draft field paths must be unique")
        if not isinstance(self.deficits, tuple) or any(
            not isinstance(item, ContractDeficit) for item in self.deficits
        ):
            raise ValueError("deficits must contain ContractDeficit values")

    @property
    def ready(self) -> bool:
        return not any(item.blocking for item in self.deficits)

    def materialized(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for field_record in sorted(self.fields, key=lambda item: item.field_path):
            cursor = result
            parts = field_record.field_path.split(".")
            for part in parts[:-1]:
                child = cursor.setdefault(part, {})
                if not isinstance(child, dict):
                    raise ValueError("draft contains overlapping scalar and object paths")
                cursor = child
            if parts[-1] in cursor and isinstance(cursor[parts[-1]], dict):
                raise ValueError("draft contains overlapping scalar and object paths")
            cursor[parts[-1]] = field_record.value
        return result

    @property
    def content_hash(self) -> Sha256Digest:
        return Sha256Digest.of_record(self.materialized())

    def as_record(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id.value,
            "duet_id": self.duet_id.value,
            "revision": self.revision,
            "fields": [item.as_record() for item in self.fields],
            "deficits": [item.as_record() for item in self.deficits],
            "ready": self.ready,
            "content_hash": self.content_hash.value,
        }


@dataclass(frozen=True)
class InformationRequest:
    request_id: OpaqueId
    duet_id: OpaqueId
    revision: int
    field_path: str
    reason_code: str
    answer_schema: Mapping[str, Any]
    option_ids: tuple[str, ...] = ()
    impact: FieldImpact = FieldImpact.MEDIUM
    blocking: bool = True

    def __post_init__(self) -> None:
        _opaque(self.request_id, "request_id")
        _opaque(self.duet_id, "duet_id")
        object.__setattr__(self, "revision", _integer(self.revision, "revision"))
        if _FIELD_PATH.fullmatch(self.field_path) is None:
            raise ValueError("field_path is invalid")
        object.__setattr__(self, "reason_code", _identifier(self.reason_code, "reason_code"))
        object.__setattr__(self, "answer_schema", MappingProxyType(_json_value(self.answer_schema)))
        object.__setattr__(self, "option_ids", _string_tuple(self.option_ids, "option_ids"))
        if not isinstance(self.impact, FieldImpact):
            raise ValueError("impact must be a FieldImpact")
        if not isinstance(self.blocking, bool):
            raise ValueError("blocking must be boolean")

    def as_record(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id.value,
            "duet_id": self.duet_id.value,
            "revision": self.revision,
            "field_path": self.field_path,
            "reason_code": self.reason_code,
            "answer_schema": dict(self.answer_schema),
            "option_ids": list(self.option_ids),
            "impact": self.impact.value,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class DuetAnswer:
    answer_id: OpaqueId
    request_id: OpaqueId
    duet_id: OpaqueId
    revision: int
    field_path: str
    value: Any
    human_authority_id: OpaqueId

    def __post_init__(self) -> None:
        for name in ("answer_id", "request_id", "duet_id", "human_authority_id"):
            _opaque(getattr(self, name), name)
        object.__setattr__(self, "revision", _integer(self.revision, "revision"))
        if _FIELD_PATH.fullmatch(self.field_path) is None:
            raise ValueError("field_path is invalid")
        object.__setattr__(self, "value", _json_value(self.value))

    def as_record(self) -> dict[str, Any]:
        return {
            "answer_id": self.answer_id.value,
            "request_id": self.request_id.value,
            "duet_id": self.duet_id.value,
            "revision": self.revision,
            "field_path": self.field_path,
            "value": self.value,
            "human_authority_id": self.human_authority_id.value,
        }


@dataclass(frozen=True)
class CreatorGuidance:
    """Trusted human instruction delivered to a Creator at a unit boundary."""

    guidance_id: OpaqueId
    duet_id: OpaqueId
    creator_episode_id: OpaqueId
    expected_unit_index: int
    instruction: str
    human_authority_id: OpaqueId

    def __post_init__(self) -> None:
        for name in (
            "guidance_id",
            "duet_id",
            "creator_episode_id",
            "human_authority_id",
        ):
            _opaque(getattr(self, name), name)
        object.__setattr__(
            self,
            "expected_unit_index",
            _integer(self.expected_unit_index, "expected_unit_index"),
        )
        object.__setattr__(
            self,
            "instruction",
            _text(self.instruction, "instruction", maximum=8192),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "guidance_id": self.guidance_id.value,
            "duet_id": self.duet_id.value,
            "creator_episode_id": self.creator_episode_id.value,
            "expected_unit_index": self.expected_unit_index,
            "instruction": self.instruction,
            "human_authority_id": self.human_authority_id.value,
        }


@dataclass(frozen=True)
class FrozenCreatorContract:
    artifact_id: OpaqueId
    duet_id: OpaqueId
    draft_id: OpaqueId
    revision: int
    content_hash: Sha256Digest
    contract: EpisodeCreationSpec

    def __post_init__(self) -> None:
        for name in ("artifact_id", "duet_id", "draft_id"):
            _opaque(getattr(self, name), name)
        object.__setattr__(self, "revision", _integer(self.revision, "revision"))
        if not isinstance(self.content_hash, Sha256Digest):
            raise ValueError("content_hash must be a Sha256Digest")
        if not isinstance(self.contract, EpisodeCreationSpec):
            raise ValueError("contract must be an EpisodeCreationSpec")
        if self.content_hash != self.contract.spec_hash:
            raise ValueError("frozen contract hash does not match its content")
        if not self.contract.can_create_episodes or self.contract.creator_contract is None:
            raise ValueError("a frozen Creator contract must grant explicit Creator capability")

    def as_record(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id.value,
            "duet_id": self.duet_id.value,
            "draft_id": self.draft_id.value,
            "revision": self.revision,
            "content_hash": self.content_hash.value,
            "contract": self.contract.as_record(),
        }


@dataclass(frozen=True)
class DuetApproval:
    approval_id: OpaqueId
    duet_id: OpaqueId
    human_authority_id: OpaqueId
    kind: ApprovalKind
    artifact_id: OpaqueId
    content_hash: Sha256Digest
    revision: int

    def __post_init__(self) -> None:
        for name in ("approval_id", "duet_id", "human_authority_id", "artifact_id"):
            _opaque(getattr(self, name), name)
        if not isinstance(self.kind, ApprovalKind):
            raise ValueError("kind must be an ApprovalKind")
        if not isinstance(self.content_hash, Sha256Digest):
            raise ValueError("content_hash must be a Sha256Digest")
        object.__setattr__(self, "revision", _integer(self.revision, "revision"))

    def as_record(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id.value,
            "duet_id": self.duet_id.value,
            "human_authority_id": self.human_authority_id.value,
            "kind": self.kind.value,
            "artifact_id": self.artifact_id.value,
            "content_hash": self.content_hash.value,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class CreatorProgressEnvelope:
    creator_episode_id: OpaqueId
    sequence: int
    state: DuetDesignState
    candidate_revision: int
    deficit_count: int
    validation_codes: tuple[str, ...]
    accepted_evidence_ids: tuple[OpaqueId, ...]
    method_credit: Optional[float]

    def __post_init__(self) -> None:
        _opaque(self.creator_episode_id, "creator_episode_id")
        object.__setattr__(self, "sequence", _integer(self.sequence, "sequence"))
        if not isinstance(self.state, DuetDesignState):
            raise ValueError("state must be a DuetDesignState")
        object.__setattr__(self, "candidate_revision", _integer(self.candidate_revision, "candidate_revision"))
        object.__setattr__(self, "deficit_count", _integer(self.deficit_count, "deficit_count"))
        object.__setattr__(self, "validation_codes", _string_tuple(self.validation_codes, "validation_codes"))
        if not isinstance(self.accepted_evidence_ids, tuple) or any(
            not isinstance(item, OpaqueId) for item in self.accepted_evidence_ids
        ):
            raise ValueError("accepted_evidence_ids must be a tuple of OpaqueIds")
        if len(set(self.accepted_evidence_ids)) != len(self.accepted_evidence_ids):
            raise ValueError("accepted_evidence_ids must be unique")
        if self.method_credit is not None:
            credit = _number(self.method_credit, "method_credit")
            if not 0 <= credit <= 1:
                raise ValueError("method_credit must lie in [0, 1]")
            object.__setattr__(self, "method_credit", credit)

    def as_record(self) -> dict[str, Any]:
        return {
            "creator_episode_id": self.creator_episode_id.value,
            "sequence": self.sequence,
            "state": self.state.value,
            "candidate_revision": self.candidate_revision,
            "deficit_count": self.deficit_count,
            "validation_codes": list(self.validation_codes),
            "accepted_evidence_ids": [item.value for item in self.accepted_evidence_ids],
            "method_credit": self.method_credit,
        }


@dataclass(frozen=True)
class CreatorLaunchReceipt:
    """Host-produced receipt proving that admission reached an execution host."""

    creator_episode_id: OpaqueId
    execution_id: OpaqueId
    state: CreatorLaunchState

    def __post_init__(self) -> None:
        _opaque(self.creator_episode_id, "creator_episode_id")
        _opaque(self.execution_id, "execution_id")
        if not isinstance(self.state, CreatorLaunchState):
            raise ValueError("state must be a CreatorLaunchState")

    def as_record(self) -> dict[str, str]:
        return {
            "creator_episode_id": self.creator_episode_id.value,
            "execution_id": self.execution_id.value,
            "state": self.state.value,
        }


@dataclass(frozen=True)
class FrozenWorkflowDesign:
    """A host-validated workflow design frozen before its Run Episode starts."""

    artifact_id: OpaqueId
    duet_id: OpaqueId
    creator_episode_id: OpaqueId
    revision: int
    workflow_hash: Sha256Digest
    workflow: EpisodeWorkflowSpec

    def __post_init__(self) -> None:
        for name in ("artifact_id", "duet_id", "creator_episode_id"):
            _opaque(getattr(self, name), name)
        object.__setattr__(
            self,
            "revision",
            _integer(self.revision, "revision", minimum=1),
        )
        if not isinstance(self.workflow_hash, Sha256Digest):
            raise ValueError("workflow_hash must be a Sha256Digest")
        if not isinstance(self.workflow, EpisodeWorkflowSpec):
            raise ValueError("workflow must be an EpisodeWorkflowSpec")
        if self.workflow_hash != self.workflow.workflow_hash:
            raise ValueError("workflow hash does not match its content")

    def as_record(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id.value,
            "duet_id": self.duet_id.value,
            "creator_episode_id": self.creator_episode_id.value,
            "revision": self.revision,
            "workflow_hash": self.workflow_hash.value,
            "workflow": self.workflow.as_record(),
        }


@dataclass(frozen=True)
class WorkflowCandidate:
    artifact_id: OpaqueId
    duet_id: OpaqueId
    creator_episode_id: OpaqueId
    revision: int
    workflow_hash: Sha256Digest
    workflow: EpisodeWorkflowSpec
    projection: EpisodeWorkflowDesignProjection

    def __post_init__(self) -> None:
        for name in ("artifact_id", "duet_id", "creator_episode_id"):
            _opaque(getattr(self, name), name)
        object.__setattr__(self, "revision", _integer(self.revision, "revision", minimum=1))
        if not isinstance(self.workflow_hash, Sha256Digest):
            raise ValueError("workflow_hash must be a Sha256Digest")
        if not isinstance(self.workflow, EpisodeWorkflowSpec):
            raise ValueError("workflow must be an EpisodeWorkflowSpec")
        if self.workflow_hash != self.workflow.workflow_hash:
            raise ValueError("workflow hash does not match its content")
        if not isinstance(self.projection, EpisodeWorkflowDesignProjection):
            raise ValueError("projection must be an EpisodeWorkflowDesignProjection")

    def as_record(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id.value,
            "duet_id": self.duet_id.value,
            "creator_episode_id": self.creator_episode_id.value,
            "revision": self.revision,
            "workflow_hash": self.workflow_hash.value,
            "workflow": self.workflow.as_record(),
            "projection": self.projection.as_record(),
        }


@dataclass(frozen=True)
class WorkflowApproval:
    approval: DuetApproval

    def __post_init__(self) -> None:
        if not isinstance(self.approval, DuetApproval):
            raise ValueError("approval must be a DuetApproval")
        if self.approval.kind is not ApprovalKind.WORKFLOW:
            raise ValueError("WorkflowApproval requires a workflow approval")

    def as_record(self) -> dict[str, Any]:
        return self.approval.as_record()


@dataclass(frozen=True)
class DuetDecision:
    message_id: OpaqueId
    duet_id: OpaqueId
    creator_episode_id: OpaqueId
    kind: DuetMessageKind
    expected_unit_index: int
    code: str
    field_ids: tuple[str, ...] = ()
    guidance_artifact_ids: tuple[OpaqueId, ...] = ()

    def __post_init__(self) -> None:
        for name in ("message_id", "duet_id", "creator_episode_id"):
            _opaque(getattr(self, name), name)
        if not isinstance(self.kind, DuetMessageKind):
            raise ValueError("kind must be a DuetMessageKind")
        object.__setattr__(self, "expected_unit_index", _integer(self.expected_unit_index, "expected_unit_index"))
        object.__setattr__(self, "code", _identifier(self.code, "code"))
        object.__setattr__(self, "field_ids", _string_tuple(self.field_ids, "field_ids"))
        if not isinstance(self.guidance_artifact_ids, tuple) or any(
            not isinstance(item, OpaqueId) for item in self.guidance_artifact_ids
        ):
            raise ValueError("guidance_artifact_ids must be a tuple of OpaqueIds")
        if len(set(self.guidance_artifact_ids)) != len(self.guidance_artifact_ids):
            raise ValueError("guidance_artifact_ids must be unique")

    def as_record(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id.value,
            "duet_id": self.duet_id.value,
            "creator_episode_id": self.creator_episode_id.value,
            "kind": self.kind.value,
            "expected_unit_index": self.expected_unit_index,
            "code": self.code,
            "field_ids": list(self.field_ids),
            "guidance_artifact_ids": [
                item.value for item in self.guidance_artifact_ids
            ],
        }


def content_id(kind: str, value: object) -> OpaqueId:
    """Mint a stable opaque identifier from canonical JSON content."""

    return OpaqueId.mint(kind, canonical_json(value))


def digest_record(value: object) -> Sha256Digest:
    return Sha256Digest.of_bytes(canonical_json(value).encode("utf-8"))


__all__ = [
    "ApprovalKind",
    "ContractDeficit",
    "ContractFieldRecord",
    "CreatorGuidance",
    "CreatorLaunchReceipt",
    "CreatorLaunchState",
    "CreatorContractDraft",
    "CreatorProgressEnvelope",
    "DEFAULT_CREATOR_PROPOSAL_BOUND",
    "DUET_ALLOWED_TOOLS",
    "DUET_FORBIDDEN_TOOLS",
    "DUET_PROTOCOL_TOOLS",
    "DUET_SCHEMA_VERSION",
    "DUET_SEARCH_TOOLS",
    "DuetAnswer",
    "DuetApproval",
    "DuetDecision",
    "DuetDesignState",
    "DuetIdentity",
    "DuetMessageKind",
    "DuetPolicy",
    "DuetProvenance",
    "FieldImpact",
    "FrozenCreatorContract",
    "FrozenWorkflowDesign",
    "InformationRequest",
    "WorkflowApproval",
    "WorkflowCandidate",
    "canonical_json",
    "content_id",
    "digest_record",
]
