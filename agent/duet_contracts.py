"""Typed authority and message contracts for the OpenChia Duet.

The Duet is the human--LLM collaboration that designs Episode workflows.
It is deliberately not an Episode.  These records keep human authority,
model proposals, host validation, and Episode execution as separate facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Mapping, Optional

from agent.episode_contracts import (
    EpisodeEgressRule,
    EpisodeWorkflowSpec,
    OpaqueId,
    Sha256Digest,
    validate_egress_host,
    validate_egress_name,
)


MAX_DEFICIT_DETAIL_CHARS = 512

_FIELD_PATH = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_CODE = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")


class DuetProtocolError(RuntimeError):
    """A Duet operation violates its persisted authority protocol."""


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


def _host_detail(value: object) -> Optional[str]:
    """Normalise host validation text: one line, NUL-free, bounded."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("detail must be text")
    text = " ".join(value.replace("\x00", "").split())
    return text[:MAX_DEFICIT_DETAIL_CHARS] or None


class DuetProvenance(str, Enum):
    HUMAN_INPUT = "human_input"
    LLM_PROPOSAL = "llm_proposal"
    HOST_VALIDATION = "host_validation"
    HUMAN_APPROVAL = "human_approval"


class DuetDesignState(str, Enum):
    DESIGNING = "designing"
    WAITING_ON_DUET = "waiting_on_duet"
    REFINING = "refining"
    AWAITING_WORKFLOW_APPROVAL = "awaiting_workflow_approval"
    AWAITING_REFINEMENT_APPROVAL = "awaiting_refinement_approval"
    SEALED = "sealed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ApprovalKind(str, Enum):
    WORKFLOW = "workflow"
    REFINEMENT = "refinement"


class DuetMessageKind(str, Enum):
    ANSWER = "answer"
    OVERRIDE = "override"
    PAUSE = "pause"
    CANCEL = "cancel"
    RETRY = "retry"


DUET_SEARCH_TOOLS = frozenset({"web_search", "web_extract"})
DUET_PROTOCOL_TOOLS = frozenset(
    {
        "openchia_scope",
        "duet_status",
        "duet_launch_propose",
        "episode_architecture_submit",
        "episode_workspace_read",
        "episode_refinement_request",
    }
)
DUET_ALLOWED_TOOLS = DUET_SEARCH_TOOLS | DUET_PROTOCOL_TOOLS
OPENCHIA_CONTROL_PLANE_TOOLS = DUET_PROTOCOL_TOOLS
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

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "DuetIdentity":
        required = {
            "duet_id",
            "human_authority_id",
            "policy_id",
            "conversation_id",
        }
        if not isinstance(record, Mapping) or set(record) != required:
            raise ValueError("stored Duet identity has an invalid shape")
        return cls(
            duet_id=OpaqueId(record["duet_id"]),
            human_authority_id=OpaqueId(record["human_authority_id"]),
            policy_id=OpaqueId(record["policy_id"]),
            conversation_id=OpaqueId(record["conversation_id"]),
        )


@dataclass(frozen=True)
class DuetPolicy:
    policy_id: OpaqueId
    capability_allowlist: tuple[str, ...] = tuple(sorted(DUET_ALLOWED_TOOLS))

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
    def as_record(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id.value,
            "capability_allowlist": list(self.capability_allowlist),
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "DuetPolicy":
        required = {
            "policy_id",
            "capability_allowlist",
        }
        if not isinstance(record, Mapping) or set(record) != required:
            raise ValueError("stored Duet policy has an invalid shape")
        allowlist = record["capability_allowlist"]
        if not isinstance(allowlist, list):
            raise ValueError("stored Duet capability_allowlist must be a list")
        return cls(
            policy_id=OpaqueId(record["policy_id"]),
            capability_allowlist=tuple(allowlist),
        )


@dataclass(frozen=True)
class ContractDeficit:
    """One host validation failure anchored to a blueprint field.

    ``detail`` is the host validator's own message so the Duet LLM can act on
    *why* a field was rejected.  It is host-authored only: it comes from an
    exception raised by host code, never from a model- or human-supplied field.
    """

    code: str
    field_path: str
    blocking: bool = True
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _identifier(self.code, "code"))
        if _FIELD_PATH.fullmatch(self.field_path) is None:
            raise ValueError("deficit field_path is invalid")
        if not isinstance(self.blocking, bool):
            raise ValueError("blocking must be boolean")
        object.__setattr__(self, "detail", _host_detail(self.detail))

    def as_record(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field_path": self.field_path,
            "blocking": self.blocking,
            "detail": self.detail,
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
    predecessor_approval_id: Optional[OpaqueId]

    def __post_init__(self) -> None:
        for name in ("approval_id", "duet_id", "human_authority_id", "artifact_id"):
            _opaque(getattr(self, name), name)
        if not isinstance(self.kind, ApprovalKind):
            raise ValueError("kind must be an ApprovalKind")
        if not isinstance(self.content_hash, Sha256Digest):
            raise ValueError("content_hash must be a Sha256Digest")
        object.__setattr__(self, "revision", _integer(self.revision, "revision"))
        if self.predecessor_approval_id is not None:
            _opaque(self.predecessor_approval_id, "predecessor_approval_id")
            if self.predecessor_approval_id == self.approval_id:
                raise ValueError("an approval cannot name itself as predecessor")

    def as_record(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id.value,
            "duet_id": self.duet_id.value,
            "human_authority_id": self.human_authority_id.value,
            "kind": self.kind.value,
            "artifact_id": self.artifact_id.value,
            "content_hash": self.content_hash.value,
            "revision": self.revision,
            "predecessor_approval_id": (
                None
                if self.predecessor_approval_id is None
                else self.predecessor_approval_id.value
            ),
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "DuetApproval":
        required = {
            "approval_id",
            "duet_id",
            "human_authority_id",
            "kind",
            "artifact_id",
            "content_hash",
            "revision",
            "predecessor_approval_id",
        }
        if not isinstance(record, Mapping) or set(record) != required:
            raise ValueError("stored Duet approval has an invalid shape")
        try:
            kind = ApprovalKind(record["kind"])
        except (TypeError, ValueError) as exc:
            raise ValueError("stored Duet approval kind is invalid") from exc
        return cls(
            approval_id=OpaqueId(record["approval_id"]),
            duet_id=OpaqueId(record["duet_id"]),
            human_authority_id=OpaqueId(record["human_authority_id"]),
            kind=kind,
            artifact_id=OpaqueId(record["artifact_id"]),
            content_hash=Sha256Digest(record["content_hash"]),
            revision=record["revision"],
            predecessor_approval_id=(
                None
                if record["predecessor_approval_id"] is None
                else OpaqueId(record["predecessor_approval_id"])
            ),
        )


def _sorted_unique(value: object, name: str, admit) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be a tuple")
    result = tuple(admit(item, name) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must contain unique values")
    return tuple(sorted(result))


@dataclass(frozen=True)
class WorkflowAdmissionAuthority:
    """Host-owned ceiling for admitting one Duet-designed workflow.

    This is not an Episode and never runs a model. Its sole purpose is to
    freeze the host capability boundary used to validate and launch the
    human-approved workflow. ``egress_hosts`` and ``egress_credential_names``
    bound every Episode egress rule: the exact hosts an approved workflow may
    name and the operator-held credentials it may refer to by name.
    """

    duet_id: OpaqueId
    assignable_capability_names: tuple[str, ...]
    egress_hosts: tuple[str, ...] = ()
    egress_credential_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _opaque(self.duet_id, "duet_id")
        object.__setattr__(
            self,
            "assignable_capability_names",
            _string_tuple(
                self.assignable_capability_names,
                "assignable_capability_names",
            ),
        )
        object.__setattr__(
            self,
            "egress_hosts",
            _sorted_unique(self.egress_hosts, "egress_hosts", validate_egress_host),
        )
        object.__setattr__(
            self,
            "egress_credential_names",
            _sorted_unique(
                self.egress_credential_names,
                "egress_credential_names",
                validate_egress_name,
            ),
        )

    def egress_rule_violations(self, rule: EpisodeEgressRule) -> tuple[str, ...]:
        """Return the ceiling dimensions (``host``, ``credential``) ``rule`` exceeds."""

        if not isinstance(rule, EpisodeEgressRule):
            raise TypeError("rule must be an EpisodeEgressRule")
        violations = []
        if rule.host not in self.egress_hosts:
            violations.append("host")
        if (
            rule.credential is not None
            and rule.credential not in self.egress_credential_names
        ):
            violations.append("credential")
        return tuple(violations)

    def authority_record(self) -> dict[str, Any]:
        return {
            "duet_id": self.duet_id.value,
            "assignable_capability_names": list(
                self.assignable_capability_names
            ),
            "egress_hosts": list(self.egress_hosts),
            "egress_credential_names": list(self.egress_credential_names),
        }

    @property
    def content_hash(self) -> Sha256Digest:
        return Sha256Digest.of_record(self.authority_record())

    @property
    def authority_id(self) -> OpaqueId:
        return content_id("admission", self.authority_record())

    def as_record(self) -> dict[str, Any]:
        return {
            "authority_id": self.authority_id.value,
            "content_hash": self.content_hash.value,
            **self.authority_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "WorkflowAdmissionAuthority":
        if not isinstance(value, Mapping):
            raise ValueError("workflow admission authority must be a mapping")
        expected = {
            "duet_id",
            "assignable_capability_names",
            "egress_hosts",
            "egress_credential_names",
            "authority_id",
            "content_hash",
        }
        if set(value) != expected:
            raise ValueError("workflow admission authority has an invalid shape")
        arrays = {}
        for name in (
            "assignable_capability_names",
            "egress_hosts",
            "egress_credential_names",
        ):
            if not isinstance(value[name], list):
                raise ValueError(f"{name} must be an array")
            arrays[name] = tuple(value[name])
        authority = cls(duet_id=OpaqueId(value["duet_id"]), **arrays)
        if (
            authority.authority_id.value != value["authority_id"]
            or authority.content_hash.value != value["content_hash"]
        ):
            raise ValueError("workflow admission authority identity is stale")
        return authority


@dataclass(frozen=True)
class FrozenDuetWorkflow:
    """One Duet-owned workflow frozen under exact host admission authority."""

    artifact_id: OpaqueId
    duet_id: OpaqueId
    revision: int
    workflow_hash: Sha256Digest
    workflow: EpisodeWorkflowSpec
    admission_authority_id: OpaqueId
    admission_authority_hash: Sha256Digest
    source_draft_artifact_id: OpaqueId
    source_draft_hash: Sha256Digest
    refinement_decision_id: Optional[OpaqueId]
    refinement_decision_hash: Optional[Sha256Digest]

    def __post_init__(self) -> None:
        for name in (
            "artifact_id",
            "duet_id",
            "admission_authority_id",
            "source_draft_artifact_id",
        ):
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
        if not isinstance(self.admission_authority_hash, Sha256Digest):
            raise ValueError("admission_authority_hash must be a Sha256Digest")
        if not isinstance(self.source_draft_hash, Sha256Digest):
            raise ValueError("source_draft_hash must be a Sha256Digest")
        if self.refinement_decision_id is not None:
            _opaque(self.refinement_decision_id, "refinement_decision_id")
        if self.refinement_decision_hash is not None and not isinstance(
            self.refinement_decision_hash,
            Sha256Digest,
        ):
            raise ValueError(
                "refinement_decision_hash must be a Sha256Digest"
            )
        if (self.refinement_decision_id is None) != (
            self.refinement_decision_hash is None
        ):
            raise ValueError(
                "refinement decision identity and hash must both be present or absent"
            )

    def as_record(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id.value,
            "duet_id": self.duet_id.value,
            "revision": self.revision,
            "workflow_hash": self.workflow_hash.value,
            "workflow": self.workflow.as_record(),
            "admission_authority_id": self.admission_authority_id.value,
            "admission_authority_hash": self.admission_authority_hash.value,
            "source_draft_artifact_id": self.source_draft_artifact_id.value,
            "source_draft_hash": self.source_draft_hash.value,
            "refinement_decision_id": (
                None
                if self.refinement_decision_id is None
                else self.refinement_decision_id.value
            ),
            "refinement_decision_hash": (
                None
                if self.refinement_decision_hash is None
                else self.refinement_decision_hash.value
            ),
        }

    @classmethod
    def from_record(cls, value: object) -> "FrozenDuetWorkflow":
        if (
            not isinstance(value, Mapping)
            or set(value)
            != {
                "artifact_id",
                "duet_id",
                "revision",
                "workflow_hash",
                "workflow",
                "admission_authority_id",
                "admission_authority_hash",
                "source_draft_artifact_id",
                "source_draft_hash",
                "refinement_decision_id",
                "refinement_decision_hash",
            }
        ):
            raise ValueError("frozen Duet workflow has an invalid shape")
        return cls(
            artifact_id=OpaqueId(value["artifact_id"]),
            duet_id=OpaqueId(value["duet_id"]),
            revision=value["revision"],
            workflow_hash=Sha256Digest(value["workflow_hash"]),
            workflow=EpisodeWorkflowSpec.from_record(value["workflow"]),
            admission_authority_id=OpaqueId(value["admission_authority_id"]),
            admission_authority_hash=Sha256Digest(
                value["admission_authority_hash"]
            ),
            source_draft_artifact_id=OpaqueId(
                value["source_draft_artifact_id"]
            ),
            source_draft_hash=Sha256Digest(value["source_draft_hash"]),
            refinement_decision_id=(
                None
                if value["refinement_decision_id"] is None
                else OpaqueId(value["refinement_decision_id"])
            ),
            refinement_decision_hash=(
                None
                if value["refinement_decision_hash"] is None
                else Sha256Digest(value["refinement_decision_hash"])
            ),
        )


def content_id(kind: str, value: object) -> OpaqueId:
    """Mint a stable opaque identifier from canonical JSON content."""

    return OpaqueId.mint(kind, canonical_json(value))


def digest_record(value: object) -> Sha256Digest:
    return Sha256Digest.of_bytes(canonical_json(value).encode("utf-8"))


__all__ = [
    "ApprovalKind",
    "ContractDeficit",
    "DUET_ALLOWED_TOOLS",
    "DUET_FORBIDDEN_TOOLS",
    "DUET_PROTOCOL_TOOLS",
    "OPENCHIA_CONTROL_PLANE_TOOLS",
    "DUET_SEARCH_TOOLS",
    "DuetApproval",
    "DuetDesignState",
    "DuetIdentity",
    "DuetMessageKind",
    "DuetPolicy",
    "DuetProvenance",
    "DuetProtocolError",
    "FrozenDuetWorkflow",
    "WorkflowAdmissionAuthority",
    "canonical_json",
    "content_id",
    "digest_record",
]
