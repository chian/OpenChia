"""Immutable models for Creator-designed task Episodes.

An Episode creation request crosses from a Creator Episode into the host, so
it may contain the child goal and the numeric measure the child will pursue.
The reverse channel is deliberately narrower: the host builds a
``ChildEpisodeUpdate`` from controller state, and that record has no field for
child-authored prose, tool output, exceptions, or model messages.

The records in this module are immutable and serialize to strict JSON-shaped
records.  Deserializers reject unknown keys rather than silently retaining a
second, unvalidated message channel.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional


EPISODE_CREATION_SCHEMA_VERSION = 4
EPISODE_WORKFLOW_SCHEMA_VERSION = 1
CHILD_EPISODE_UPDATE_SCHEMA_VERSION = 2
PARENT_UPDATE_PROJECTION_SCHEMA_VERSION = 3

_LEGACY_CHILD_EPISODE_UPDATE_SCHEMA_VERSION = 1

CREATOR_EPISODE_GRAIN = "creator_episode"
RUN_EPISODE_GRAIN = "run_episode"
TASK_EPISODE_GRAIN = "task_episode"

DURABLE_EVIDENCE_PROGRESS_ADAPTER = "durable_evidence_count_v1"
TERMINAL_RESULT_PROGRESS_ADAPTER = "terminal_result_count_v1"
CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER = "creator_method_credit_v1"
EVIDENCE_GATE_SCORE_PROGRESS_ADAPTER = "evidence_gate_score_v1"
DEFAULT_AGENT_EPISODE_UNIT = (
    "one Hermes model/tool iteration for the fixed task contract"
)
DEFAULT_CREATOR_EPISODE_UNIT = "one frozen workflow candidate Run Episode"
DEFAULT_AGENT_EPISODE_RESULT = "one host-validated terminal result artifact"
MAX_EPISODE_GOAL_CHARS = 4096
MAX_EPISODE_BLUEPRINT_TEXT_CHARS = 1024
MAX_EPISODE_LOCAL_ID_CHARS = 64
MAX_EPISODE_TOOL_NAME_CHARS = 256
CREATOR_CONTEXT_SCHEMA_VERSION = 1
MAX_CREATOR_CONTEXT_ARTIFACTS = 64
MAX_CREATOR_CONTEXT_ARTIFACT_BYTES = 131_072
MAX_CREATOR_CONTEXT_TOTAL_BYTES = 524_288

_OPAQUE_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}_[0-9a-f]{32,64}$")
_OPAQUE_ID_KIND = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_EPISODE_LOCAL_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def _record(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _keys(record: Mapping[str, Any], expected: set[str], name: str) -> None:
    actual = set(record)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(
            f"malformed {name}: missing={missing!r}, unknown={unknown!r}"
        )


def _text(
    value: object,
    name: str,
    *,
    max_chars: Optional[int] = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise ValueError(f"{name} must not contain NUL")
    if max_chars is not None and len(value) > max_chars:
        raise ValueError(f"{name} must be at most {max_chars} characters")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive_int(value: object, name: str) -> int:
    result = _non_negative_int(value, name)
    if result == 0:
        raise ValueError(f"{name} must be positive")
    return result


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _local_identifier(value: object, name: str) -> str:
    result = _text(value, name, max_chars=MAX_EPISODE_LOCAL_ID_CHARS)
    if not _EPISODE_LOCAL_ID.fullmatch(result):
        raise ValueError(
            f"{name} must start with a lowercase letter and contain only "
            "lowercase letters, digits, underscores, or hyphens"
        )
    return result


def _name_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be a tuple")
    if any(
        not isinstance(item, str)
        or not item.strip()
        or "\x00" in item
        or len(item) > MAX_EPISODE_TOOL_NAME_CHARS
        for item in value
    ):
        raise ValueError(
            f"{name} must contain non-empty names no longer than "
            f"{MAX_EPISODE_TOOL_NAME_CHARS} characters"
        )
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must contain unique names")
    return value


def _schema_version(value: object, expected: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise ValueError(f"unsupported {name} schema version")


def _optional_positive_int(value: object, name: str) -> Optional[int]:
    return None if value is None else _positive_int(value, name)


def _optional_positive_number(value: object, name: str) -> Optional[float]:
    if value is None:
        return None
    result = _number(value, name)
    if result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


def _enum(enum_type: type[Enum], value: object, name: str) -> Enum:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string enum value")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"unsupported {name}: {value!r}") from exc


def _load_json(payload: str, name: str) -> Mapping[str, Any]:
    if not isinstance(payload, str):
        raise ValueError(f"{name} JSON must be a string")
    try:
        value = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {name} JSON") from exc
    return _record(value, name)


def _dump_json(record: Mapping[str, Any]) -> str:
    return json.dumps(
        record,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class CapabilityInheritance(str, Enum):
    """A task child inherits execution capabilities, not orchestration control."""

    PARENT = "inherit_parent"


class ProgressDirection(str, Enum):
    """The direction in which a numeric measure represents progress."""

    INCREASE = "increase"
    DECREASE = "decrease"


class EpisodeCreditAggregation(str, Enum):
    """Closed host-owned rule for reducing diagnostic credit components."""

    NORMALIZED_WEIGHTED_SUM = "normalized_weighted_sum_v1"


class EpisodeCreatorStatusField(str, Enum):
    """Closed status fields the Duet may request from a design result."""

    WORKFLOW_VALID = "workflow_valid"
    MEASUREMENTS_COMPLETE = "measurements_complete"
    EVIDENCE_REQUIREMENTS_MET = "evidence_requirements_met"
    CREDIT_COMPLETE = "credit_complete"


class EpisodeDeliverableKind(str, Enum):
    """How a child makes its result usable outside its private transcript."""

    TYPED_STATUS = "typed_status"
    SHARED_STATE = "shared_state"


class ChildEpisodePhase(str, Enum):
    """Closed lifecycle vocabulary for a host-produced parent update."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    STOPPED = "stopped"
    BOUND_HIT = "bound_hit"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ChildEpisodeStopReason(str, Enum):
    """Closed numerical/runtime reasons; never child-authored explanations."""

    NONE = "none"
    TARGET_REACHED = "target_reached"
    NO_PROGRESS = "no_progress"
    DELIVERABLE_MISSING = "deliverable_missing"
    SOURCE_EXHAUSTED = "source_exhausted"
    SAFETY_BOUND = "safety_bound"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class OpaqueId:
    """A host-minted identifier with no prose-bearing payload.

    The suffix is hexadecimal entropy or a content digest.  Requiring this
    shape prevents a model-provided sentence from masquerading as an ID on the
    child-to-parent channel.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _OPAQUE_ID.fullmatch(self.value):
            raise ValueError(
                "opaque IDs must be <kind>_<32-to-64 lowercase hex characters>"
            )

    @classmethod
    def mint(cls, kind: str, material: bytes | str) -> "OpaqueId":
        if not isinstance(kind, str) or not _OPAQUE_ID_KIND.fullmatch(kind):
            raise ValueError("opaque ID kind must be a lowercase identifier")
        if isinstance(material, str):
            encoded = material.encode("utf-8")
        elif isinstance(material, bytes):
            encoded = material
        else:
            raise ValueError("opaque ID material must be bytes or text")
        return cls(f"{kind}_{hashlib.sha256(encoded).hexdigest()}")


@dataclass(frozen=True)
class Sha256Digest:
    """A tagged, lowercase SHA-256 digest."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _SHA256.fullmatch(self.value):
            raise ValueError("digest must be sha256 followed by 64 lowercase hex digits")

    @classmethod
    def of_bytes(cls, payload: bytes) -> "Sha256Digest":
        if not isinstance(payload, bytes):
            raise ValueError("digest payload must be bytes")
        return cls(f"sha256:{hashlib.sha256(payload).hexdigest()}")

    @classmethod
    def of_record(cls, record: Mapping[str, Any]) -> "Sha256Digest":
        return cls.of_bytes(_dump_json(record).encode("utf-8"))


@dataclass(frozen=True)
class EpisodeCreatorContextReference:
    """One exact, content-addressed input to a Creator design commission."""

    artifact_id: OpaqueId
    content_hash: Sha256Digest
    artifact_kind: str
    schema_version: int
    purpose: str
    required: bool

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, OpaqueId):
            raise ValueError("context artifact_id must be an OpaqueId")
        if not isinstance(self.content_hash, Sha256Digest):
            raise ValueError("context content_hash must be a Sha256Digest")
        object.__setattr__(
            self,
            "artifact_kind",
            _local_identifier(self.artifact_kind, "context artifact_kind"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _positive_int(self.schema_version, "context artifact schema_version"),
        )
        object.__setattr__(
            self,
            "purpose",
            _local_identifier(self.purpose, "context artifact purpose"),
        )
        object.__setattr__(self, "required", _boolean(self.required, "required"))

    def as_record(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id.value,
            "content_hash": self.content_hash.value,
            "artifact_kind": self.artifact_kind,
            "schema_version": self.schema_version,
            "purpose": self.purpose,
            "required": self.required,
        }

    @classmethod
    def from_record(cls, value: object) -> "EpisodeCreatorContextReference":
        record = _record(value, "Creator context artifact reference")
        _keys(
            record,
            {
                "artifact_id",
                "content_hash",
                "artifact_kind",
                "schema_version",
                "purpose",
                "required",
            },
            "Creator context artifact reference",
        )
        return cls(
            artifact_id=OpaqueId(record["artifact_id"]),
            content_hash=Sha256Digest(record["content_hash"]),
            artifact_kind=record["artifact_kind"],
            schema_version=record["schema_version"],
            purpose=record["purpose"],
            required=record["required"],
        )


@dataclass(frozen=True)
class EpisodeCreatorContext:
    """Lossless context manifest; summaries carry no authority in this channel."""

    entrypoint_artifact_id: OpaqueId
    artifact_references: tuple[EpisodeCreatorContextReference, ...]
    unresolved_question_ids: tuple[OpaqueId, ...] = ()
    schema_version: int = field(
        default=CREATOR_CONTEXT_SCHEMA_VERSION,
        init=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.entrypoint_artifact_id, OpaqueId):
            raise ValueError("entrypoint_artifact_id must be an OpaqueId")
        if (
            not isinstance(self.artifact_references, tuple)
            or not self.artifact_references
            or any(
                not isinstance(item, EpisodeCreatorContextReference)
                for item in self.artifact_references
            )
        ):
            raise ValueError(
                "artifact_references must contain at least one Creator context reference"
            )
        if len(self.artifact_references) > MAX_CREATOR_CONTEXT_ARTIFACTS:
            raise ValueError(
                f"artifact_references may contain at most {MAX_CREATOR_CONTEXT_ARTIFACTS} items"
            )
        artifact_ids = tuple(item.artifact_id for item in self.artifact_references)
        if len(set(artifact_ids)) != len(artifact_ids):
            raise ValueError("Creator context artifact references must be unique")
        entrypoints = tuple(
            item
            for item in self.artifact_references
            if item.artifact_id == self.entrypoint_artifact_id
        )
        if len(entrypoints) != 1 or not entrypoints[0].required:
            raise ValueError(
                "entrypoint_artifact_id must name one required context artifact"
            )
        if not isinstance(self.unresolved_question_ids, tuple) or any(
            not isinstance(item, OpaqueId) for item in self.unresolved_question_ids
        ):
            raise ValueError("unresolved_question_ids must be a tuple of OpaqueIds")
        if len(set(self.unresolved_question_ids)) != len(
            self.unresolved_question_ids
        ):
            raise ValueError("unresolved_question_ids must be unique")

    @property
    def required_artifact_ids(self) -> tuple[OpaqueId, ...]:
        return tuple(
            item.artifact_id for item in self.artifact_references if item.required
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "entrypoint_artifact_id": self.entrypoint_artifact_id.value,
            "artifact_references": [
                item.as_record() for item in self.artifact_references
            ],
            "unresolved_question_ids": [
                item.value for item in self.unresolved_question_ids
            ],
        }

    @classmethod
    def from_record(cls, value: object) -> "EpisodeCreatorContext":
        record = _record(value, "Creator context")
        _keys(
            record,
            {
                "schema_version",
                "entrypoint_artifact_id",
                "artifact_references",
                "unresolved_question_ids",
            },
            "Creator context",
        )
        _schema_version(
            record["schema_version"],
            CREATOR_CONTEXT_SCHEMA_VERSION,
            "Creator context",
        )
        references = record["artifact_references"]
        question_ids = record["unresolved_question_ids"]
        if not isinstance(references, list) or not isinstance(question_ids, list):
            raise ValueError("Creator context collection fields must be arrays")
        return cls(
            entrypoint_artifact_id=OpaqueId(record["entrypoint_artifact_id"]),
            artifact_references=tuple(
                EpisodeCreatorContextReference.from_record(item)
                for item in references
            ),
            unresolved_question_ids=tuple(OpaqueId(item) for item in question_ids),
        )


@dataclass(frozen=True)
class NumericProgressMeasure:
    """One numeric quantity observed by the host controller."""

    metric_id: OpaqueId
    description: str
    unit: str
    direction: ProgressDirection
    baseline: float
    adapter_id: str = DURABLE_EVIDENCE_PROGRESS_ADAPTER

    def __post_init__(self) -> None:
        if not isinstance(self.metric_id, OpaqueId):
            raise ValueError("metric_id must be an OpaqueId")
        object.__setattr__(self, "description", _text(self.description, "description"))
        object.__setattr__(self, "unit", _text(self.unit, "unit"))
        if not isinstance(self.direction, ProgressDirection):
            raise ValueError("direction must be a ProgressDirection")
        object.__setattr__(self, "baseline", _number(self.baseline, "baseline"))
        object.__setattr__(
            self,
            "adapter_id",
            _text(self.adapter_id, "adapter_id"),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id.value,
            "description": self.description,
            "unit": self.unit,
            "direction": self.direction.value,
            "baseline": self.baseline,
            "adapter_id": self.adapter_id,
        }

    @classmethod
    def from_record(cls, value: object) -> "NumericProgressMeasure":
        record = _record(value, "numeric progress measure")
        _keys(
            record,
            {
                "metric_id",
                "description",
                "unit",
                "direction",
                "baseline",
                "adapter_id",
            },
            "numeric progress measure",
        )
        return cls(
            metric_id=OpaqueId(record["metric_id"]),
            description=record["description"],
            unit=record["unit"],
            direction=_enum(
                ProgressDirection, record["direction"], "progress direction"
            ),
            baseline=record["baseline"],
            adapter_id=record["adapter_id"],
        )


@dataclass(frozen=True)
class EpisodeDeliverableContract:
    """Host-checkable boundary for a child Episode's useful result.

    ``typed_status`` is for work where the parent's closed phase/progress update
    is itself sufficient. ``shared_state`` requires at least one claimed,
    committed effect from one of ``tool_names`` before the child may succeed.
    """

    kind: EpisodeDeliverableKind
    description: str
    tool_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EpisodeDeliverableKind):
            raise ValueError("deliverable kind must be an EpisodeDeliverableKind")
        object.__setattr__(
            self,
            "description",
            _text(
                self.description,
                "deliverable description",
                max_chars=MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
            ),
        )
        if not isinstance(self.tool_names, tuple) or any(
            not isinstance(name, str)
            or not name.strip()
            or "\x00" in name
            or len(name) > MAX_EPISODE_TOOL_NAME_CHARS
            for name in self.tool_names
        ):
            raise ValueError(
                "deliverable tool_names must be non-empty tool names no longer "
                f"than {MAX_EPISODE_TOOL_NAME_CHARS} characters"
            )
        if len(set(self.tool_names)) != len(self.tool_names):
            raise ValueError("deliverable tool_names must be unique")
        if self.kind is EpisodeDeliverableKind.TYPED_STATUS and self.tool_names:
            raise ValueError("typed_status deliverables cannot name materialization tools")
        if self.kind is EpisodeDeliverableKind.SHARED_STATE and not self.tool_names:
            raise ValueError("shared_state deliverables require materialization tools")

    @classmethod
    def typed_status(cls) -> "EpisodeDeliverableContract":
        return cls(
            kind=EpisodeDeliverableKind.TYPED_STATUS,
            description=(
                "The containing Episode needs only the host-typed terminal update."
            ),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "description": self.description,
            "tool_names": list(self.tool_names),
        }

    @classmethod
    def from_record(cls, value: object) -> "EpisodeDeliverableContract":
        record = _record(value, "Episode deliverable contract")
        _keys(
            record,
            {"kind", "description", "tool_names"},
            "Episode deliverable contract",
        )
        tool_names = record["tool_names"]
        if not isinstance(tool_names, list):
            raise ValueError("deliverable tool_names must be an array")
        return cls(
            kind=_enum(
                EpisodeDeliverableKind,
                record["kind"],
                "Episode deliverable kind",
            ),
            description=record["description"],
            tool_names=tuple(tool_names),
        )


@dataclass(frozen=True)
class ProgressStopCriteria:
    """Numerical completion and no-progress rules for one measure.

    The target is reached in ``NumericProgressMeasure.direction``.  The
    controller also stops without success when directional improvement across
    ``stagnation_observations`` is less than ``minimum_delta``.
    """

    target: float
    minimum_delta: float
    stagnation_observations: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", _number(self.target, "target"))
        delta = _number(self.minimum_delta, "minimum_delta")
        if delta <= 0:
            raise ValueError("minimum_delta must be positive")
        object.__setattr__(self, "minimum_delta", delta)
        window = _positive_int(
            self.stagnation_observations, "stagnation_observations"
        )
        if window < 2:
            raise ValueError(
                "stagnation_observations must be at least 2 so one evidence "
                "round is followed by a progress-report opportunity"
            )
        object.__setattr__(self, "stagnation_observations", window)

    def as_record(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "minimum_delta": self.minimum_delta,
            "stagnation_observations": self.stagnation_observations,
        }

    @classmethod
    def from_record(cls, value: object) -> "ProgressStopCriteria":
        record = _record(value, "progress stop criteria")
        _keys(
            record,
            {"target", "minimum_delta", "stagnation_observations"},
            "progress stop criteria",
        )
        return cls(
            target=record["target"],
            minimum_delta=record["minimum_delta"],
            stagnation_observations=record["stagnation_observations"],
        )


@dataclass(frozen=True)
class EpisodeSafetyBounds:
    """Optional hard caps; hitting one is not successful completion."""

    max_iterations: Optional[int] = None
    max_child_episodes: Optional[int] = None
    max_depth: Optional[int] = None
    max_elapsed_seconds: Optional[float] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_iterations",
            _optional_positive_int(self.max_iterations, "max_iterations"),
        )
        object.__setattr__(
            self,
            "max_child_episodes",
            _optional_positive_int(
                self.max_child_episodes, "max_child_episodes"
            ),
        )
        object.__setattr__(
            self,
            "max_depth",
            _optional_positive_int(self.max_depth, "max_depth"),
        )
        object.__setattr__(
            self,
            "max_elapsed_seconds",
            _optional_positive_number(
                self.max_elapsed_seconds, "max_elapsed_seconds"
            ),
        )
        if all(
            bound is None
            for bound in (
                self.max_iterations,
                self.max_child_episodes,
                self.max_depth,
                self.max_elapsed_seconds,
            )
        ):
            raise ValueError("a safety-bounds record must declare at least one bound")

    def as_record(self) -> dict[str, Any]:
        return {
            "max_iterations": self.max_iterations,
            "max_child_episodes": self.max_child_episodes,
            "max_depth": self.max_depth,
            "max_elapsed_seconds": self.max_elapsed_seconds,
        }

    @classmethod
    def from_record(cls, value: object) -> "EpisodeSafetyBounds":
        record = _record(value, "episode safety bounds")
        _keys(
            record,
            {
                "max_iterations",
                "max_child_episodes",
                "max_depth",
                "max_elapsed_seconds",
            },
            "episode safety bounds",
        )
        return cls(
            max_iterations=record["max_iterations"],
            max_child_episodes=record["max_child_episodes"],
            max_depth=record["max_depth"],
            max_elapsed_seconds=record["max_elapsed_seconds"],
        )


@dataclass(frozen=True)
class EpisodeEvidenceRequirement:
    """Registered evidence type and minimum accepted count for one experiment."""

    requirement_id: str
    evidence_kind_id: str
    acceptance_source_id: str
    minimum_count: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requirement_id",
            _local_identifier(self.requirement_id, "requirement_id"),
        )
        object.__setattr__(
            self,
            "evidence_kind_id",
            _text(
                self.evidence_kind_id,
                "evidence_kind_id",
                max_chars=MAX_EPISODE_TOOL_NAME_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "acceptance_source_id",
            _text(
                self.acceptance_source_id,
                "acceptance_source_id",
                max_chars=MAX_EPISODE_TOOL_NAME_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "minimum_count",
            _positive_int(self.minimum_count, "minimum_count"),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "evidence_kind_id": self.evidence_kind_id,
            "acceptance_source_id": self.acceptance_source_id,
            "minimum_count": self.minimum_count,
        }

    @classmethod
    def from_record(cls, value: object) -> "EpisodeEvidenceRequirement":
        record = _record(value, "Episode evidence requirement")
        _keys(
            record,
            {
                "requirement_id",
                "evidence_kind_id",
                "acceptance_source_id",
                "minimum_count",
            },
            "Episode evidence requirement",
        )
        return cls(
            requirement_id=record["requirement_id"],
            evidence_kind_id=record["evidence_kind_id"],
            acceptance_source_id=record["acceptance_source_id"],
            minimum_count=record["minimum_count"],
        )


@dataclass(frozen=True)
class EpisodeCreditComponentSpec:
    """One registered numeric measurement's contribution to method credit."""

    component_id: str
    measurement_id: str
    direction: ProgressDirection
    normalization_baseline: float
    normalization_target: float
    weight: float
    evidence_requirement_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "component_id",
            _local_identifier(self.component_id, "component_id"),
        )
        object.__setattr__(
            self,
            "measurement_id",
            _text(
                self.measurement_id,
                "measurement_id",
                max_chars=MAX_EPISODE_TOOL_NAME_CHARS,
            ),
        )
        if not isinstance(self.direction, ProgressDirection):
            raise ValueError("direction must be a ProgressDirection")
        baseline = _number(
            self.normalization_baseline,
            "normalization_baseline",
        )
        target = _number(self.normalization_target, "normalization_target")
        if (
            self.direction is ProgressDirection.INCREASE and target <= baseline
        ) or (
            self.direction is ProgressDirection.DECREASE and target >= baseline
        ):
            raise ValueError(
                "normalization_target must lie strictly in the declared direction"
            )
        object.__setattr__(self, "normalization_baseline", baseline)
        object.__setattr__(self, "normalization_target", target)
        weight = _number(self.weight, "weight")
        if weight < 0:
            raise ValueError("weight must be non-negative")
        object.__setattr__(self, "weight", weight)
        requirement_ids = tuple(
            _local_identifier(item, "evidence_requirement_id")
            for item in self.evidence_requirement_ids
        ) if isinstance(self.evidence_requirement_ids, tuple) else ()
        if not isinstance(self.evidence_requirement_ids, tuple):
            raise ValueError("evidence_requirement_ids must be a tuple")
        if not requirement_ids:
            raise ValueError(
                "credit components require at least one evidence requirement"
            )
        if len(set(requirement_ids)) != len(requirement_ids):
            raise ValueError("evidence_requirement_ids must be unique")
        object.__setattr__(self, "evidence_requirement_ids", requirement_ids)

    def normalized_value(self, measured_value: float) -> float:
        value = _number(measured_value, "measured_value")
        if self.direction is ProgressDirection.INCREASE:
            numerator = value - self.normalization_baseline
            denominator = self.normalization_target - self.normalization_baseline
        else:
            numerator = self.normalization_baseline - value
            denominator = self.normalization_baseline - self.normalization_target
        return min(1.0, max(0.0, numerator / denominator))

    def as_record(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "measurement_id": self.measurement_id,
            "direction": self.direction.value,
            "normalization_baseline": self.normalization_baseline,
            "normalization_target": self.normalization_target,
            "weight": self.weight,
            "evidence_requirement_ids": list(self.evidence_requirement_ids),
        }

    @classmethod
    def from_record(cls, value: object) -> "EpisodeCreditComponentSpec":
        record = _record(value, "Episode credit component")
        _keys(
            record,
            {
                "component_id",
                "measurement_id",
                "direction",
                "normalization_baseline",
                "normalization_target",
                "weight",
                "evidence_requirement_ids",
            },
            "Episode credit component",
        )
        requirement_ids = record["evidence_requirement_ids"]
        if not isinstance(requirement_ids, list):
            raise ValueError("evidence_requirement_ids must be an array")
        return cls(
            component_id=record["component_id"],
            measurement_id=record["measurement_id"],
            direction=_enum(
                ProgressDirection,
                record["direction"],
                "credit direction",
            ),
            normalization_baseline=record["normalization_baseline"],
            normalization_target=record["normalization_target"],
            weight=record["weight"],
            evidence_requirement_ids=tuple(requirement_ids),
        )


@dataclass(frozen=True)
class EpisodeMethodCreditSpec:
    """Validated single-scalar method-credit rule with diagnostic components."""

    components: tuple[EpisodeCreditComponentSpec, ...]
    aggregation: EpisodeCreditAggregation = (
        EpisodeCreditAggregation.NORMALIZED_WEIGHTED_SUM
    )

    def __post_init__(self) -> None:
        if not isinstance(self.components, tuple) or not self.components:
            raise ValueError("credit components must be a non-empty tuple")
        if any(
            not isinstance(component, EpisodeCreditComponentSpec)
            for component in self.components
        ):
            raise ValueError(
                "credit components must contain EpisodeCreditComponentSpec values"
            )
        component_ids = tuple(item.component_id for item in self.components)
        if len(set(component_ids)) != len(component_ids):
            raise ValueError("credit component_id values must be unique")
        if not isinstance(self.aggregation, EpisodeCreditAggregation):
            raise ValueError("aggregation must be an EpisodeCreditAggregation")
        if sum(item.weight for item in self.components) <= 0:
            raise ValueError("credit component weights must have a positive total")

    def as_record(self) -> dict[str, Any]:
        return {
            "aggregation": self.aggregation.value,
            "components": [item.as_record() for item in self.components],
        }

    @classmethod
    def from_record(cls, value: object) -> "EpisodeMethodCreditSpec":
        record = _record(value, "Episode method credit")
        _keys(record, {"aggregation", "components"}, "Episode method credit")
        components = record["components"]
        if not isinstance(components, list):
            raise ValueError("credit components must be an array")
        return cls(
            components=tuple(
                EpisodeCreditComponentSpec.from_record(item)
                for item in components
            ),
            aggregation=_enum(
                EpisodeCreditAggregation,
                record["aggregation"],
                "credit aggregation",
            ),
        )


@dataclass(frozen=True)
class EpisodeCreatorReturnContract:
    """Exact allowlist for the typed design-experiment result projection."""

    measurement_ids: tuple[str, ...]
    credit_component_ids: tuple[str, ...]
    status_fields: tuple[EpisodeCreatorStatusField, ...] = ()

    def __post_init__(self) -> None:
        measurements = _name_tuple(self.measurement_ids, "measurement_ids")
        components = tuple(
            _local_identifier(item, "credit_component_id")
            for item in self.credit_component_ids
        ) if isinstance(self.credit_component_ids, tuple) else ()
        if not isinstance(self.credit_component_ids, tuple):
            raise ValueError("credit_component_ids must be a tuple")
        if len(set(components)) != len(components):
            raise ValueError("credit_component_ids must be unique")
        if not measurements or not components:
            raise ValueError(
                "creator return contracts require measurement and credit IDs"
            )
        if not isinstance(self.status_fields, tuple) or any(
            not isinstance(item, EpisodeCreatorStatusField)
            for item in self.status_fields
        ):
            raise ValueError(
                "status_fields must be a tuple of EpisodeCreatorStatusField values"
            )
        if len(set(self.status_fields)) != len(self.status_fields):
            raise ValueError("status_fields must be unique")
        object.__setattr__(self, "measurement_ids", measurements)
        object.__setattr__(self, "credit_component_ids", components)

    def as_record(self) -> dict[str, Any]:
        return {
            "measurement_ids": list(self.measurement_ids),
            "credit_component_ids": list(self.credit_component_ids),
            "status_fields": [item.value for item in self.status_fields],
        }

    @classmethod
    def from_record(cls, value: object) -> "EpisodeCreatorReturnContract":
        record = _record(value, "Episode creator return contract")
        _keys(
            record,
            {"measurement_ids", "credit_component_ids", "status_fields"},
            "Episode creator return contract",
        )
        measurement_ids = record["measurement_ids"]
        component_ids = record["credit_component_ids"]
        status_fields = record["status_fields"]
        if not all(
            isinstance(items, list)
            for items in (measurement_ids, component_ids, status_fields)
        ):
            raise ValueError("creator return contract fields must be arrays")
        return cls(
            measurement_ids=tuple(measurement_ids),
            credit_component_ids=tuple(component_ids),
            status_fields=tuple(
                _enum(
                    EpisodeCreatorStatusField,
                    item,
                    "creator status field",
                )
                for item in status_fields
            ),
        )


@dataclass(frozen=True)
class EpisodeCreatorContract:
    """Structured context and host-owned evaluation for a Creator Episode."""

    design_context: EpisodeCreatorContext
    design_scope: str
    assignable_capability_names: tuple[str, ...]
    may_assign_creator_capability: bool
    evidence_requirements: tuple[EpisodeEvidenceRequirement, ...]
    required_existing_evidence_ids: tuple[OpaqueId, ...]
    credit_assignment: EpisodeMethodCreditSpec
    return_contract: EpisodeCreatorReturnContract

    def __post_init__(self) -> None:
        if not isinstance(self.design_context, EpisodeCreatorContext):
            raise ValueError("design_context must be an EpisodeCreatorContext")
        object.__setattr__(
            self,
            "design_scope",
            _text(
                self.design_scope,
                "design_scope",
                max_chars=MAX_EPISODE_GOAL_CHARS,
            ),
        )
        capabilities = _name_tuple(
            self.assignable_capability_names,
            "assignable_capability_names",
        )
        object.__setattr__(self, "assignable_capability_names", capabilities)
        object.__setattr__(
            self,
            "may_assign_creator_capability",
            _boolean(
                self.may_assign_creator_capability,
                "may_assign_creator_capability",
            ),
        )
        if not isinstance(self.evidence_requirements, tuple) or not self.evidence_requirements:
            raise ValueError("evidence_requirements must be a non-empty tuple")
        if any(
            not isinstance(item, EpisodeEvidenceRequirement)
            for item in self.evidence_requirements
        ):
            raise ValueError(
                "evidence_requirements must contain EpisodeEvidenceRequirement values"
            )
        requirement_ids = {
            item.requirement_id for item in self.evidence_requirements
        }
        if len(requirement_ids) != len(self.evidence_requirements):
            raise ValueError("evidence requirement IDs must be unique")
        if not isinstance(self.required_existing_evidence_ids, tuple) or any(
            not isinstance(item, OpaqueId)
            for item in self.required_existing_evidence_ids
        ):
            raise ValueError(
                "required_existing_evidence_ids must be a tuple of OpaqueIds"
            )
        if len(set(self.required_existing_evidence_ids)) != len(
            self.required_existing_evidence_ids
        ):
            raise ValueError("required_existing_evidence_ids must be unique")
        if not isinstance(self.credit_assignment, EpisodeMethodCreditSpec):
            raise ValueError("credit_assignment must be EpisodeMethodCreditSpec")
        referenced_requirements = {
            requirement_id
            for component in self.credit_assignment.components
            for requirement_id in component.evidence_requirement_ids
        }
        if referenced_requirements != requirement_ids:
            raise ValueError(
                "credit components must reference every declared evidence requirement "
                "and no undeclared requirement"
            )
        if not isinstance(self.return_contract, EpisodeCreatorReturnContract):
            raise ValueError(
                "return_contract must be EpisodeCreatorReturnContract"
            )
        measurement_ids = {
            item.measurement_id for item in self.credit_assignment.components
        }
        component_ids = {
            item.component_id for item in self.credit_assignment.components
        }
        if not set(self.return_contract.measurement_ids).issubset(measurement_ids):
            raise ValueError(
                "return_contract names an undeclared measurement ID"
            )
        if not set(self.return_contract.credit_component_ids).issubset(component_ids):
            raise ValueError(
                "return_contract names an undeclared credit component ID"
            )

    def as_record(self) -> dict[str, Any]:
        return {
            "design_context": self.design_context.as_record(),
            "design_scope": self.design_scope,
            "assignable_capability_names": list(
                self.assignable_capability_names
            ),
            "may_assign_creator_capability": self.may_assign_creator_capability,
            "evidence_requirements": [
                item.as_record() for item in self.evidence_requirements
            ],
            "required_existing_evidence_ids": [
                item.value for item in self.required_existing_evidence_ids
            ],
            "credit_assignment": self.credit_assignment.as_record(),
            "return_contract": self.return_contract.as_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "EpisodeCreatorContract":
        record = _record(value, "Episode creator contract")
        _keys(
            record,
            {
                "design_context",
                "design_scope",
                "assignable_capability_names",
                "may_assign_creator_capability",
                "evidence_requirements",
                "required_existing_evidence_ids",
                "credit_assignment",
                "return_contract",
            },
            "Episode creator contract",
        )
        capabilities = record["assignable_capability_names"]
        requirements = record["evidence_requirements"]
        existing = record["required_existing_evidence_ids"]
        if not all(
            isinstance(items, list)
            for items in (capabilities, requirements, existing)
        ):
            raise ValueError("creator contract collection fields must be arrays")
        return cls(
            design_context=EpisodeCreatorContext.from_record(
                record["design_context"]
            ),
            design_scope=record["design_scope"],
            assignable_capability_names=tuple(capabilities),
            may_assign_creator_capability=record[
                "may_assign_creator_capability"
            ],
            evidence_requirements=tuple(
                EpisodeEvidenceRequirement.from_record(item)
                for item in requirements
            ),
            required_existing_evidence_ids=tuple(
                OpaqueId(item) for item in existing
            ),
            credit_assignment=EpisodeMethodCreditSpec.from_record(
                record["credit_assignment"]
            ),
            return_contract=EpisodeCreatorReturnContract.from_record(
                record["return_contract"]
            ),
        )


@dataclass(frozen=True)
class EpisodeCreationSpec:
    """Complete declarative request for a child Agent Episode."""

    goal: str
    progress: NumericProgressMeasure
    stopping: ProgressStopCriteria
    can_create_episodes: bool = False
    execution_capability_names: tuple[str, ...] = ()
    creator_contract: Optional[EpisodeCreatorContract] = None
    unit: str = DEFAULT_AGENT_EPISODE_UNIT
    result: str = DEFAULT_AGENT_EPISODE_RESULT
    deliverable: EpisodeDeliverableContract = field(
        default_factory=EpisodeDeliverableContract.typed_status
    )
    safety_bounds: Optional[EpisodeSafetyBounds] = None
    capability_inheritance: CapabilityInheritance = CapabilityInheritance.PARENT
    schema_version: int = field(
        default=EPISODE_CREATION_SCHEMA_VERSION, init=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "goal",
            _text(self.goal, "goal", max_chars=MAX_EPISODE_GOAL_CHARS),
        )
        if not isinstance(self.progress, NumericProgressMeasure):
            raise ValueError("progress must be a NumericProgressMeasure")
        if not isinstance(self.stopping, ProgressStopCriteria):
            raise ValueError("stopping must be ProgressStopCriteria")
        object.__setattr__(
            self,
            "can_create_episodes",
            _boolean(self.can_create_episodes, "can_create_episodes"),
        )
        object.__setattr__(
            self,
            "execution_capability_names",
            _name_tuple(
                self.execution_capability_names,
                "execution_capability_names",
            ),
        )
        if self.creator_contract is not None and not isinstance(
            self.creator_contract,
            EpisodeCreatorContract,
        ):
            raise ValueError(
                "creator_contract must be EpisodeCreatorContract or None"
            )
        if (self.creator_contract is not None) != self.can_create_episodes:
            raise ValueError(
                "creator_contract is required exactly when can_create_episodes is true"
            )
        object.__setattr__(
            self,
            "unit",
            _text(
                self.unit,
                "unit",
                max_chars=MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "result",
            _text(
                self.result,
                "result",
                max_chars=MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
            ),
        )
        if not isinstance(self.deliverable, EpisodeDeliverableContract):
            raise ValueError("deliverable must be an EpisodeDeliverableContract")
        if (
            self.progress.direction is ProgressDirection.INCREASE
            and self.stopping.target < self.progress.baseline
        ) or (
            self.progress.direction is ProgressDirection.DECREASE
            and self.stopping.target > self.progress.baseline
        ):
            raise ValueError(
                "stopping target must lie in the declared progress direction "
                "from the baseline"
            )
        if self.safety_bounds is not None and not isinstance(
            self.safety_bounds, EpisodeSafetyBounds
        ):
            raise ValueError("safety_bounds must be EpisodeSafetyBounds or None")
        if self.capability_inheritance is not CapabilityInheritance.PARENT:
            raise ValueError(
                "task Episodes must inherit parent execution capabilities"
            )

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "goal": self.goal,
            "unit": self.unit,
            "result": self.result,
            "progress": self.progress.as_record(),
            "stopping": self.stopping.as_record(),
            "can_create_episodes": self.can_create_episodes,
            "execution_capability_names": list(
                self.execution_capability_names
            ),
            "creator_contract": (
                None
                if self.creator_contract is None
                else self.creator_contract.as_record()
            ),
            "deliverable": self.deliverable.as_record(),
            "safety_bounds": (
                None if self.safety_bounds is None else self.safety_bounds.as_record()
            ),
            "capability_inheritance": self.capability_inheritance.value,
        }

    def to_json(self) -> str:
        return _dump_json(self.as_record())

    @property
    def spec_hash(self) -> Sha256Digest:
        return Sha256Digest.of_record(self.as_record())

    @classmethod
    def from_record(cls, value: object) -> "EpisodeCreationSpec":
        record = _record(value, "Episode creation spec")
        _keys(
            record,
            {
                "schema_version",
                "goal",
                "unit",
                "result",
                "progress",
                "stopping",
                "can_create_episodes",
                "execution_capability_names",
                "creator_contract",
                "deliverable",
                "safety_bounds",
                "capability_inheritance",
            },
            "Episode creation spec",
        )
        _schema_version(
            record["schema_version"],
            EPISODE_CREATION_SCHEMA_VERSION,
            "Episode creation",
        )
        inheritance = _enum(
            CapabilityInheritance,
            record["capability_inheritance"],
            "capability inheritance",
        )
        bounds = record["safety_bounds"]
        capability_names = record["execution_capability_names"]
        if not isinstance(capability_names, list):
            raise ValueError("execution_capability_names must be an array")
        creator_contract = record["creator_contract"]
        return cls(
            goal=record["goal"],
            unit=record["unit"],
            result=record["result"],
            progress=NumericProgressMeasure.from_record(record["progress"]),
            stopping=ProgressStopCriteria.from_record(record["stopping"]),
            can_create_episodes=record["can_create_episodes"],
            execution_capability_names=tuple(capability_names),
            creator_contract=(
                None
                if creator_contract is None
                else EpisodeCreatorContract.from_record(creator_contract)
            ),
            deliverable=EpisodeDeliverableContract.from_record(
                record["deliverable"]
            ),
            safety_bounds=(
                None if bounds is None else EpisodeSafetyBounds.from_record(bounds)
            ),
            capability_inheritance=inheritance,
        )

    @classmethod
    def from_json(cls, payload: str) -> "EpisodeCreationSpec":
        return cls.from_record(_load_json(payload, "Episode creation spec"))


@dataclass(frozen=True)
class EpisodeDesignSpec:
    """One locally addressable Episode node in a workflow declaration."""

    local_id: str
    workflow_parent_local_id: Optional[str]
    contract: EpisodeCreationSpec

    def __post_init__(self) -> None:
        local_id = _text(
            self.local_id,
            "local_id",
            max_chars=MAX_EPISODE_LOCAL_ID_CHARS,
        )
        if not _EPISODE_LOCAL_ID.fullmatch(local_id):
            raise ValueError(
                "local_id must start with a lowercase letter and contain only "
                "lowercase letters, digits, underscores, or hyphens"
            )
        object.__setattr__(self, "local_id", local_id)
        parent = self.workflow_parent_local_id
        if parent is not None:
            parent = _text(
                parent,
                "workflow_parent_local_id",
                max_chars=MAX_EPISODE_LOCAL_ID_CHARS,
            )
            if not _EPISODE_LOCAL_ID.fullmatch(parent):
                raise ValueError(
                    "workflow_parent_local_id must be a valid local_id"
                )
            object.__setattr__(self, "workflow_parent_local_id", parent)
        if not isinstance(self.contract, EpisodeCreationSpec):
            raise ValueError("contract must be an EpisodeCreationSpec")

    def as_record(self) -> dict[str, Any]:
        return {
            "local_id": self.local_id,
            "workflow_parent_local_id": self.workflow_parent_local_id,
            "contract": self.contract.as_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "EpisodeDesignSpec":
        record = _record(value, "Episode design spec")
        _keys(
            record,
            {"local_id", "workflow_parent_local_id", "contract"},
            "Episode design spec",
        )
        return cls(
            local_id=record["local_id"],
            workflow_parent_local_id=record["workflow_parent_local_id"],
            contract=EpisodeCreationSpec.from_record(record["contract"]),
        )


@dataclass(frozen=True)
class EpisodeWorkflowSpec:
    """A complete flat declaration of a nested Episode workflow."""

    episodes: tuple[EpisodeDesignSpec, ...]
    schema_version: int = field(
        default=EPISODE_WORKFLOW_SCHEMA_VERSION,
        init=False,
    )

    def __post_init__(self) -> None:
        if not isinstance(self.episodes, tuple) or not self.episodes:
            raise ValueError("episodes must be a non-empty tuple")
        if any(not isinstance(item, EpisodeDesignSpec) for item in self.episodes):
            raise ValueError("episodes must contain EpisodeDesignSpec values")
        by_id = {item.local_id: item for item in self.episodes}
        if len(by_id) != len(self.episodes):
            raise ValueError("workflow local_id values must be unique")
        for item in self.episodes:
            parent = item.workflow_parent_local_id
            if parent == item.local_id:
                raise ValueError("an Episode cannot be its own workflow parent")
            if parent is not None and parent not in by_id:
                raise ValueError(
                    f"unknown workflow_parent_local_id {parent!r}"
                )
        for item in self.episodes:
            seen: set[str] = set()
            cursor: Optional[str] = item.local_id
            while cursor is not None:
                if cursor in seen:
                    raise ValueError("workflow parent relationships must be acyclic")
                seen.add(cursor)
                cursor = by_id[cursor].workflow_parent_local_id

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "episodes": [item.as_record() for item in self.episodes],
        }

    def to_json(self) -> str:
        return _dump_json(self.as_record())

    @property
    def workflow_hash(self) -> Sha256Digest:
        return Sha256Digest.of_record(self.as_record())

    @classmethod
    def from_record(cls, value: object) -> "EpisodeWorkflowSpec":
        record = _record(value, "Episode workflow spec")
        _keys(
            record,
            {"schema_version", "episodes"},
            "Episode workflow spec",
        )
        _schema_version(
            record["schema_version"],
            EPISODE_WORKFLOW_SCHEMA_VERSION,
            "Episode workflow",
        )
        episodes = record["episodes"]
        if not isinstance(episodes, list):
            raise ValueError("episodes must be an array")
        return cls(tuple(EpisodeDesignSpec.from_record(item) for item in episodes))

    @classmethod
    def from_json(cls, payload: str) -> "EpisodeWorkflowSpec":
        return cls.from_record(_load_json(payload, "Episode workflow spec"))


@dataclass(frozen=True)
class EpisodeEvidenceMeasurement:
    """Accepted evidence identities satisfying one registered requirement."""

    requirement_id: str
    accepted_evidence_ids: tuple[OpaqueId, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "requirement_id",
            _local_identifier(self.requirement_id, "requirement_id"),
        )
        if not isinstance(self.accepted_evidence_ids, tuple) or any(
            not isinstance(item, OpaqueId)
            for item in self.accepted_evidence_ids
        ):
            raise ValueError(
                "accepted_evidence_ids must be a tuple of OpaqueIds"
            )
        if len(set(self.accepted_evidence_ids)) != len(
            self.accepted_evidence_ids
        ):
            raise ValueError("accepted_evidence_ids must be unique")

    @property
    def accepted_count(self) -> int:
        return len(self.accepted_evidence_ids)

    def as_record(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "accepted_count": self.accepted_count,
            "accepted_evidence_ids": [
                item.value for item in self.accepted_evidence_ids
            ],
        }


@dataclass(frozen=True)
class EpisodeMeasuredOutcome:
    """One host-measured numeric outcome with its accepted evidence."""

    measurement_id: str
    value: float
    evidence: tuple[EpisodeEvidenceMeasurement, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "measurement_id",
            _text(
                self.measurement_id,
                "measurement_id",
                max_chars=MAX_EPISODE_TOOL_NAME_CHARS,
            ),
        )
        object.__setattr__(self, "value", _number(self.value, "value"))
        if not isinstance(self.evidence, tuple) or any(
            not isinstance(item, EpisodeEvidenceMeasurement)
            for item in self.evidence
        ):
            raise ValueError(
                "evidence must be a tuple of EpisodeEvidenceMeasurement values"
            )
        requirement_ids = tuple(item.requirement_id for item in self.evidence)
        if len(set(requirement_ids)) != len(requirement_ids):
            raise ValueError(
                "an outcome may report each evidence requirement only once"
            )

    def as_record(self) -> dict[str, Any]:
        return {
            "measurement_id": self.measurement_id,
            "value": self.value,
            "evidence": [item.as_record() for item in self.evidence],
        }


@dataclass(frozen=True)
class EpisodeCreditComponentValue:
    """Host-computed diagnostic value retained beneath one scalar credit."""

    component_id: str
    measurement_id: str
    measured_value: float
    normalized_value: float
    weighted_value: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "component_id",
            _local_identifier(self.component_id, "component_id"),
        )
        object.__setattr__(
            self,
            "measurement_id",
            _text(
                self.measurement_id,
                "measurement_id",
                max_chars=MAX_EPISODE_TOOL_NAME_CHARS,
            ),
        )
        for name in ("measured_value", "normalized_value", "weighted_value"):
            object.__setattr__(self, name, _number(getattr(self, name), name))
        if not 0 <= self.normalized_value <= 1:
            raise ValueError("normalized_value must lie in [0, 1]")
        if not 0 <= self.weighted_value <= 1:
            raise ValueError("weighted_value must lie in [0, 1]")

    def as_record(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "measurement_id": self.measurement_id,
            "measured_value": self.measured_value,
            "normalized_value": self.normalized_value,
            "weighted_value": self.weighted_value,
        }


@dataclass(frozen=True)
class EpisodeWorkflowDesignResult:
    """Host-validated workflow proposal and host-computed experiment credit."""

    workflow: EpisodeWorkflowSpec
    measured_outcomes: tuple[EpisodeMeasuredOutcome, ...]
    credit_components: tuple[EpisodeCreditComponentValue, ...]
    method_credit: float

    def __post_init__(self) -> None:
        if not isinstance(self.workflow, EpisodeWorkflowSpec):
            raise ValueError("workflow must be EpisodeWorkflowSpec")
        if not isinstance(self.measured_outcomes, tuple) or any(
            not isinstance(item, EpisodeMeasuredOutcome)
            for item in self.measured_outcomes
        ):
            raise ValueError(
                "measured_outcomes must contain EpisodeMeasuredOutcome values"
            )
        if not isinstance(self.credit_components, tuple) or any(
            not isinstance(item, EpisodeCreditComponentValue)
            for item in self.credit_components
        ):
            raise ValueError(
                "credit_components must contain EpisodeCreditComponentValue values"
            )
        for name, values in (
            (
                "measurement_id",
                tuple(item.measurement_id for item in self.measured_outcomes),
            ),
            (
                "component_id",
                tuple(item.component_id for item in self.credit_components),
            ),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"workflow result {name} values must be unique")
        credit = _number(self.method_credit, "method_credit")
        if not 0 <= credit <= 1:
            raise ValueError("method_credit must lie in [0, 1]")
        if abs(
            credit - sum(item.weighted_value for item in self.credit_components)
        ) > 1e-12:
            raise ValueError(
                "method_credit must equal the host-computed component total"
            )
        object.__setattr__(self, "method_credit", credit)

    @classmethod
    def host_computed(
        cls,
        *,
        workflow: EpisodeWorkflowSpec,
        creator_contract: EpisodeCreatorContract,
        measured_outcomes: tuple[EpisodeMeasuredOutcome, ...],
    ) -> "EpisodeWorkflowDesignResult":
        """Validate accepted evidence and compute the declared scalar credit."""

        if not isinstance(creator_contract, EpisodeCreatorContract):
            raise ValueError("creator_contract must be EpisodeCreatorContract")
        outcomes = {item.measurement_id: item for item in measured_outcomes}
        if len(outcomes) != len(measured_outcomes):
            raise ValueError("measured outcome IDs must be unique")
        required_measurements = set(
            creator_contract.return_contract.measurement_ids
        )
        if not required_measurements.issubset(outcomes):
            raise ValueError("required measured outcomes are missing")
        requirements = {
            item.requirement_id: item
            for item in creator_contract.evidence_requirements
        }
        accepted_ids: set[OpaqueId] = set()
        for outcome in measured_outcomes:
            for measured in outcome.evidence:
                requirement = requirements.get(measured.requirement_id)
                if requirement is None:
                    raise ValueError(
                        "measured outcome cites an undeclared evidence requirement"
                    )
                if measured.accepted_count < requirement.minimum_count:
                    raise ValueError(
                        "measured outcome does not meet its evidence minimum"
                    )
                accepted_ids.update(measured.accepted_evidence_ids)
        if not set(
            creator_contract.required_existing_evidence_ids
        ).issubset(accepted_ids):
            raise ValueError("required existing evidence is absent from outcomes")
        total_weight = sum(
            item.weight for item in creator_contract.credit_assignment.components
        )
        component_values = []
        for component in creator_contract.credit_assignment.components:
            outcome = outcomes.get(component.measurement_id)
            if outcome is None:
                raise ValueError(
                    f"measurement {component.measurement_id!r} is missing"
                )
            outcome_requirements = {
                item.requirement_id for item in outcome.evidence
            }
            if not set(component.evidence_requirement_ids).issubset(
                outcome_requirements
            ):
                raise ValueError(
                    "credit component evidence requirements are incomplete"
                )
            normalized = component.normalized_value(outcome.value)
            component_values.append(
                EpisodeCreditComponentValue(
                    component_id=component.component_id,
                    measurement_id=component.measurement_id,
                    measured_value=outcome.value,
                    normalized_value=normalized,
                    weighted_value=component.weight * normalized / total_weight,
                )
            )
        return cls(
            workflow=workflow,
            measured_outcomes=measured_outcomes,
            credit_components=tuple(component_values),
            method_credit=sum(item.weighted_value for item in component_values),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "workflow": self.workflow.as_record(),
            "measured_outcomes": [
                item.as_record() for item in self.measured_outcomes
            ],
            "credit_components": [
                item.as_record() for item in self.credit_components
            ],
            "method_credit": self.method_credit,
        }


@dataclass(frozen=True)
class EpisodeWorkflowDesignProjection:
    """Prose-free allowlisted projection of a persisted design result."""

    artifact_id: OpaqueId
    workflow_hash: Sha256Digest
    episode_count: int
    workflow_root_count: int
    measured_outcomes: tuple[EpisodeMeasuredOutcome, ...]
    credit_components: tuple[EpisodeCreditComponentValue, ...]
    method_credit: float
    status_values: tuple[tuple[EpisodeCreatorStatusField, bool], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, OpaqueId):
            raise ValueError("artifact_id must be an OpaqueId")
        if not isinstance(self.workflow_hash, Sha256Digest):
            raise ValueError("workflow_hash must be a Sha256Digest")
        object.__setattr__(
            self,
            "episode_count",
            _positive_int(self.episode_count, "episode_count"),
        )
        object.__setattr__(
            self,
            "workflow_root_count",
            _positive_int(self.workflow_root_count, "workflow_root_count"),
        )
        if self.workflow_root_count > self.episode_count:
            raise ValueError("workflow_root_count cannot exceed episode_count")
        if not isinstance(self.measured_outcomes, tuple) or any(
            not isinstance(item, EpisodeMeasuredOutcome)
            for item in self.measured_outcomes
        ):
            raise ValueError("projection measured_outcomes are malformed")
        if not isinstance(self.credit_components, tuple) or any(
            not isinstance(item, EpisodeCreditComponentValue)
            for item in self.credit_components
        ):
            raise ValueError("projection credit_components are malformed")
        credit = _number(self.method_credit, "method_credit")
        if not 0 <= credit <= 1:
            raise ValueError("method_credit must lie in [0, 1]")
        object.__setattr__(self, "method_credit", credit)
        if not isinstance(self.status_values, tuple) or any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], EpisodeCreatorStatusField)
            or not isinstance(item[1], bool)
            for item in self.status_values
        ):
            raise ValueError("status_values are malformed")
        status_fields = tuple(item[0] for item in self.status_values)
        if len(set(status_fields)) != len(status_fields):
            raise ValueError("status_values must have unique fields")

    @classmethod
    def from_result(
        cls,
        *,
        artifact_id: OpaqueId,
        result: EpisodeWorkflowDesignResult,
        return_contract: EpisodeCreatorReturnContract,
    ) -> "EpisodeWorkflowDesignProjection":
        if not isinstance(result, EpisodeWorkflowDesignResult):
            raise ValueError("result must be EpisodeWorkflowDesignResult")
        outcomes = {
            item.measurement_id: item for item in result.measured_outcomes
        }
        components = {
            item.component_id: item for item in result.credit_components
        }
        selected_outcomes = tuple(
            outcomes[item] for item in return_contract.measurement_ids
        )
        selected_components = tuple(
            components[item] for item in return_contract.credit_component_ids
        )
        roots = sum(
            item.workflow_parent_local_id is None
            for item in result.workflow.episodes
        )
        return cls(
            artifact_id=artifact_id,
            workflow_hash=result.workflow.workflow_hash,
            episode_count=len(result.workflow.episodes),
            workflow_root_count=roots,
            measured_outcomes=selected_outcomes,
            credit_components=selected_components,
            method_credit=result.method_credit,
            status_values=tuple(
                (field, True) for field in return_contract.status_fields
            ),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id.value,
            "workflow_hash": self.workflow_hash.value,
            "episode_count": self.episode_count,
            "workflow_root_count": self.workflow_root_count,
            "measured_outcomes": [
                item.as_record() for item in self.measured_outcomes
            ],
            "credit_components": [
                item.as_record() for item in self.credit_components
            ],
            "method_credit": self.method_credit,
            "status": {
                field.value: value for field, value in self.status_values
            },
        }


__all__ = [
    "CHILD_EPISODE_UPDATE_SCHEMA_VERSION",
    "CREATOR_CONTEXT_SCHEMA_VERSION",
    "CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER",
    "EVIDENCE_GATE_SCORE_PROGRESS_ADAPTER",
    "DEFAULT_AGENT_EPISODE_RESULT",
    "DEFAULT_AGENT_EPISODE_UNIT",
    "DEFAULT_CREATOR_EPISODE_UNIT",
    "DURABLE_EVIDENCE_PROGRESS_ADAPTER",
    "EPISODE_CREATION_SCHEMA_VERSION",
    "EPISODE_WORKFLOW_SCHEMA_VERSION",
    "MAX_EPISODE_BLUEPRINT_TEXT_CHARS",
    "MAX_EPISODE_GOAL_CHARS",
    "MAX_EPISODE_TOOL_NAME_CHARS",
    "MAX_CREATOR_CONTEXT_ARTIFACTS",
    "MAX_CREATOR_CONTEXT_ARTIFACT_BYTES",
    "MAX_CREATOR_CONTEXT_TOTAL_BYTES",
    "PARENT_UPDATE_PROJECTION_SCHEMA_VERSION",
    "CapabilityInheritance",
    "ChildEpisodePhase",
    "ChildEpisodeStopReason",
    "EpisodeDeliverableContract",
    "EpisodeDeliverableKind",
    "EpisodeCreationSpec",
    "EpisodeCreatorContract",
    "EpisodeCreatorContext",
    "EpisodeCreatorContextReference",
    "EpisodeCreatorReturnContract",
    "EpisodeCreatorStatusField",
    "EpisodeCreditAggregation",
    "EpisodeCreditComponentSpec",
    "EpisodeCreditComponentValue",
    "EpisodeDesignSpec",
    "EpisodeEvidenceMeasurement",
    "EpisodeEvidenceRequirement",
    "EpisodeMeasuredOutcome",
    "EpisodeMethodCreditSpec",
    "EpisodeSafetyBounds",
    "EpisodeWorkflowDesignProjection",
    "EpisodeWorkflowDesignResult",
    "EpisodeWorkflowSpec",
    "NumericProgressMeasure",
    "OpaqueId",
    "CREATOR_EPISODE_GRAIN",
    "RUN_EPISODE_GRAIN",
    "ProgressDirection",
    "ProgressStopCriteria",
    "Sha256Digest",
    "TASK_EPISODE_GRAIN",
    "TERMINAL_RESULT_PROGRESS_ADAPTER",
]
