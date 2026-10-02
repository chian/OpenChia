"""Immutable models for Duet-designed Episodes.

An Episode contract contains the task goal and the numeric measure the Episode
will pursue. The runtime's narrower reverse channel is owned by
``handoff_library.ChildResult`` and the generic method-loop completion record;
neither carries Episode-authored instructions.

The records in this module are immutable and serialize to strict JSON-shaped
records.  Deserializers reject unknown keys rather than silently retaining a
second, unvalidated message channel.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional

from episode_library.models import EpisodeReference
from function_library.epistemic_contract import EpistemicContract


DEFAULT_EPISODE_UNIT = (
    "one complete attempt-observe-credit-continuation cycle"
)
DEFAULT_EPISODE_RESULT = "one result satisfying the Episode goal"
MAX_EPISODE_GOAL_CHARS = 4096
MAX_EPISODE_BLUEPRINT_TEXT_CHARS = 1024
MAX_EPISODE_LOCAL_ID_CHARS = 64
MAX_EPISODE_TOOL_NAME_CHARS = 256

_OPAQUE_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}_[0-9a-f]{32,64}$")
_OPAQUE_ID_KIND = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_EPISODE_LOCAL_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_FUNCTION_COMPONENT = re.compile(r"^[a-z][a-z0-9_.-]*$")
_FUNCTION_DEFINITION_ID = re.compile(r"^function_[0-9a-f]{64}$")


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


class EpisodeContractError(ValueError):
    """A contract record failed validation.

    ``field_path`` names the blueprint field that failed as a tuple of path
    segments from the record root, so a host can anchor a deficit to the exact
    field without parsing the message text.  It is empty only for errors raised
    outside any field scope.
    """

    def __init__(self, message: str, *, field_path: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.field_path = field_path


@contextmanager
def contract_field(name: str):
    """Attribute any validation error raised inside the block to field ``name``.

    Nested scopes compose outer-to-inner, so field ownership remains exact.
    """

    try:
        yield
    except EpisodeContractError as exc:
        raise EpisodeContractError(
            str(exc), field_path=(name, *exc.field_path)
        ) from exc
    except (TypeError, ValueError) as exc:
        raise EpisodeContractError(str(exc), field_path=(name,)) from exc


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


def _freeze_json(value: object, name: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} numbers must be finite")
        return value
    if isinstance(value, Mapping):
        keys = tuple(value)
        if any(not isinstance(key, str) or not key for key in keys):
            raise ValueError(f"{name} keys must be non-empty strings")
        return MappingProxyType(
            {
                key: _freeze_json(value[key], f"{name}.{key}")
                for key in sorted(keys)
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(
            _freeze_json(item, f"{name}[{index}]")
            for index, item in enumerate(value)
        )
    raise ValueError(f"{name} must contain only JSON-shaped values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


class CapabilityInheritance(str, Enum):
    """A child inherits execution capabilities, not orchestration control."""

    PARENT = "inherit_parent"


class EpisodeDeliverableKind(str, Enum):
    """How a child makes its result usable outside its private transcript."""

    TYPED_STATUS = "typed_status"
    SHARED_STATE = "shared_state"


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
class EpisodeFunctionSelectionSpec:
    """One exact reusable-function selection owned by the Architecture."""

    library: str
    function_id: str
    interface: str
    definition_id: str
    arguments: Mapping[str, object]

    def __post_init__(self) -> None:
        for name in ("library", "function_id", "interface"):
            value = _text(getattr(self, name), name)
            if _FUNCTION_COMPONENT.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase dotted name")
        if (
            not isinstance(self.definition_id, str)
            or _FUNCTION_DEFINITION_ID.fullmatch(self.definition_id) is None
        ):
            raise ValueError(
                "definition_id must identify one exact reusable function"
            )
        if not isinstance(self.arguments, Mapping):
            raise ValueError("function selection arguments must be an object")
        frozen = _freeze_json(self.arguments, "function selection arguments")
        if not isinstance(frozen, Mapping):
            raise AssertionError("function selection arguments changed shape")
        object.__setattr__(self, "arguments", frozen)

    def as_record(self) -> dict[str, Any]:
        return {
            "library": self.library,
            "function_id": self.function_id,
            "interface": self.interface,
            "definition_id": self.definition_id,
            "arguments": _thaw_json(self.arguments),
        }

    @classmethod
    def from_record(cls, value: object) -> "EpisodeFunctionSelectionSpec":
        record = _record(value, "Episode function selection")
        _keys(
            record,
            {
                "library",
                "function_id",
                "interface",
                "definition_id",
                "arguments",
            },
            "Episode function selection",
        )
        return cls(**record)


@dataclass(frozen=True)
class EpisodeNumericalControlSpec:
    """Exact rarefaction and continuation selections approved by the Duet."""

    rarefaction: EpisodeFunctionSelectionSpec
    continuation: EpisodeFunctionSelectionSpec

    def __post_init__(self) -> None:
        if not isinstance(self.rarefaction, EpisodeFunctionSelectionSpec):
            raise ValueError(
                "numeric_control.rarefaction must be a function selection"
            )
        if not isinstance(self.continuation, EpisodeFunctionSelectionSpec):
            raise ValueError(
                "numeric_control.continuation must be a function selection"
            )

    def as_record(self) -> dict[str, Any]:
        return {
            "rarefaction": self.rarefaction.as_record(),
            "continuation": self.continuation.as_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "EpisodeNumericalControlSpec":
        record = _record(value, "Episode numerical control")
        _keys(
            record,
            {"rarefaction", "continuation"},
            "Episode numerical control",
        )
        return cls(
            rarefaction=EpisodeFunctionSelectionSpec.from_record(
                record["rarefaction"]
            ),
            continuation=EpisodeFunctionSelectionSpec.from_record(
                record["continuation"]
            ),
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
class EpisodeCreationSpec:
    """Complete declarative contract for one Episode."""

    goal: str
    progress: str
    stopping: str
    numeric_control: EpisodeNumericalControlSpec
    execution_capability_names: tuple[str, ...] = ()
    unit: str = DEFAULT_EPISODE_UNIT
    result: str = DEFAULT_EPISODE_RESULT
    deliverable: EpisodeDeliverableContract = field(
        default_factory=EpisodeDeliverableContract.typed_status
    )
    capability_inheritance: CapabilityInheritance = CapabilityInheritance.PARENT
    epistemic: Optional[EpistemicContract] = None
    def __post_init__(self) -> None:
        with contract_field("goal"):
            object.__setattr__(
                self,
                "goal",
                _text(self.goal, "goal", max_chars=MAX_EPISODE_GOAL_CHARS),
            )
        with contract_field("progress"):
            object.__setattr__(
                self,
                "progress",
                _text(
                    self.progress,
                    "progress",
                    max_chars=MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
                ),
            )
        with contract_field("stopping"):
            object.__setattr__(
                self,
                "stopping",
                _text(
                    self.stopping,
                    "stopping",
                    max_chars=MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
                ),
            )
        with contract_field("numeric_control"):
            if not isinstance(self.numeric_control, EpisodeNumericalControlSpec):
                raise ValueError(
                    "numeric_control must be an EpisodeNumericalControlSpec"
                )
        with contract_field("execution_capability_names"):
            object.__setattr__(
                self,
                "execution_capability_names",
                _name_tuple(
                    self.execution_capability_names,
                    "execution_capability_names",
                ),
            )
        with contract_field("unit"):
            object.__setattr__(
                self,
                "unit",
                _text(
                    self.unit,
                    "unit",
                    max_chars=MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
                ),
            )
        with contract_field("result"):
            object.__setattr__(
                self,
                "result",
                _text(
                    self.result,
                    "result",
                    max_chars=MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
                ),
            )
        with contract_field("deliverable"):
            if not isinstance(self.deliverable, EpisodeDeliverableContract):
                raise ValueError(
                    "deliverable must be an EpisodeDeliverableContract"
                )
        if self.capability_inheritance is not CapabilityInheritance.PARENT:
            raise ValueError(
                "Episodes must inherit parent execution capabilities"
            )
        with contract_field("epistemic"):
            if self.epistemic is not None:
                if not isinstance(self.epistemic, EpistemicContract):
                    raise ValueError("epistemic must be an EpistemicContract")
                self.epistemic.validate_components()

    def as_record(self) -> dict[str, Any]:
        record = {
            "goal": self.goal,
            "unit": self.unit,
            "result": self.result,
            "progress": self.progress,
            "stopping": self.stopping,
            "numeric_control": self.numeric_control.as_record(),
            "execution_capability_names": list(
                self.execution_capability_names
            ),
            "deliverable": self.deliverable.as_record(),
            "capability_inheritance": self.capability_inheritance.value,
        }
        if self.epistemic is not None:
            record["epistemic"] = self.epistemic.as_record()
        return record

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
                "goal",
                "unit",
                "result",
                "progress",
                "stopping",
                "numeric_control",
                "execution_capability_names",
                "deliverable",
                "capability_inheritance",
            } | ({"epistemic"} if "epistemic" in record else set()),
            "Episode creation spec",
        )
        inheritance = _enum(
            CapabilityInheritance,
            record["capability_inheritance"],
            "capability inheritance",
        )
        capability_names = record["execution_capability_names"]
        with contract_field("execution_capability_names"):
            if not isinstance(capability_names, list):
                raise ValueError("execution_capability_names must be an array")
        with contract_field("deliverable"):
            deliverable = EpisodeDeliverableContract.from_record(
                record["deliverable"]
            )
        with contract_field("numeric_control"):
            numeric_control = EpisodeNumericalControlSpec.from_record(
                record["numeric_control"]
            )
        return cls(
            goal=record["goal"],
            unit=record["unit"],
            result=record["result"],
            progress=record["progress"],
            stopping=record["stopping"],
            numeric_control=numeric_control,
            execution_capability_names=tuple(capability_names),
            deliverable=deliverable,
            capability_inheritance=inheritance,
            epistemic=(EpistemicContract.from_record(record["epistemic"])
                       if "epistemic" in record else None),
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
    episode_reference: Optional[EpisodeReference] = None

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
        if self.episode_reference is not None and not isinstance(
            self.episode_reference, EpisodeReference
        ):
            raise ValueError(
                "episode_reference must be an EpisodeReference or None"
            )

    def as_record(self) -> dict[str, Any]:
        return {
            "local_id": self.local_id,
            "workflow_parent_local_id": self.workflow_parent_local_id,
            "contract": self.contract.as_record(),
            "episode_reference": (
                None
                if self.episode_reference is None
                else self.episode_reference.as_record()
            ),
        }

    @classmethod
    def from_record(cls, value: object) -> "EpisodeDesignSpec":
        record = _record(value, "Episode design spec")
        _keys(
            record,
            {
                "local_id",
                "workflow_parent_local_id",
                "contract",
                "episode_reference",
            },
            "Episode design spec",
        )
        return cls(
            local_id=record["local_id"],
            workflow_parent_local_id=record["workflow_parent_local_id"],
            contract=EpisodeCreationSpec.from_record(record["contract"]),
            episode_reference=(
                None
                if record["episode_reference"] is None
                else EpisodeReference.from_record(record["episode_reference"])
            ),
        )


@dataclass(frozen=True)
class EpisodeWorkflowSpec:
    """A complete flat declaration of a nested Episode workflow."""

    episodes: tuple[EpisodeDesignSpec, ...]
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
            {"episodes"},
            "Episode workflow spec",
        )
        episodes = record["episodes"]
        if not isinstance(episodes, list):
            raise ValueError("episodes must be an array")
        return cls(tuple(EpisodeDesignSpec.from_record(item) for item in episodes))

    @classmethod
    def from_json(cls, payload: str) -> "EpisodeWorkflowSpec":
        return cls.from_record(_load_json(payload, "Episode workflow spec"))


__all__ = [
    "DEFAULT_EPISODE_RESULT",
    "DEFAULT_EPISODE_UNIT",
    "MAX_EPISODE_BLUEPRINT_TEXT_CHARS",
    "MAX_EPISODE_GOAL_CHARS",
    "MAX_EPISODE_TOOL_NAME_CHARS",
    "CapabilityInheritance",
    "EpisodeContractError",
    "EpisodeDeliverableContract",
    "EpisodeDeliverableKind",
    "EpisodeCreationSpec",
    "EpisodeDesignSpec",
    "EpisodeFunctionSelectionSpec",
    "EpisodeNumericalControlSpec",
    "EpisodeWorkflowSpec",
    "OpaqueId",
    "Sha256Digest",
    "contract_field",
]
