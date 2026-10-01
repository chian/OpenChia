"""Generic declarations for composing reusable Episode bindings.

Every Episode remains a loop. ``BRANCH`` and ``LEAF`` describe only whether
that loop may pull child Episodes as units in the declared tree.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
import math
from types import MappingProxyType
from typing import Any, Mapping


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]*$")
_INTERFACE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_DEFINITION_ID = re.compile(r"^function_[0-9a-f]{64}$")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be non-empty text")
    return value


def _freeze_json(value: object, name: str) -> object:
    """Freeze JSON-shaped binding arguments without hiding executable objects."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} numbers must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        keys = tuple(value)
        if any(not isinstance(key, str) or not key for key in keys):
            raise ValueError(f"{name} keys must be non-empty strings")
        for key in sorted(keys):
            frozen[key] = _freeze_json(value[key], f"{name}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
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


class EpisodeTopologyRole(str, Enum):
    """Whether an Episode loop exposes child-Episode attachment points."""

    BRANCH = "branch"
    LEAF = "leaf"


@dataclass(frozen=True)
class EpisodeFunctionBinding:
    """One explicitly selected reusable function in an Episode design.

    ``name`` is the function's local role in this Episode. ``library`` and
    ``function_id`` identify the reusable implementation. ``interface`` names
    the typed call boundary the Episode expects, and ``arguments`` records the
    complete Episode-owned configuration supplied to that function.
    """

    name: str
    library: str
    function_id: str
    interface: str
    definition_id: str
    arguments: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(_text(self.name, "function binding name")):
            raise ValueError("function binding name must be a lowercase identifier")
        for value, label in (
            (self.library, "function library"),
            (self.function_id, "function ID"),
            (self.interface, "function interface"),
        ):
            if not _INTERFACE.fullmatch(_text(value, label)):
                raise ValueError(f"{label} must be a lowercase dotted name")
        if not isinstance(self.definition_id, str) or not _DEFINITION_ID.fullmatch(
            self.definition_id
        ):
            raise ValueError("function definition ID must identify exact semantics")
        if not isinstance(self.arguments, Mapping):
            raise ValueError("function arguments must be an object")
        object.__setattr__(
            self,
            "arguments",
            _freeze_json(self.arguments, f"{self.name} arguments"),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "library": self.library,
            "function_id": self.function_id,
            "interface": self.interface,
            "definition_id": self.definition_id,
            "arguments": _thaw_json(self.arguments),
        }


@dataclass(frozen=True)
class EpisodeControllerBinding:
    """The complete numerical controller selected by one Episode.

    The fields are roles, not a second workflow language.  An Episode-local
    source factory still owns the readable acquisition dataflow; this record
    makes the controller's schema boundary and four selected functions
    mechanically available to the builder without a name-based lookup.
    """

    schema: EpisodeFunctionBinding
    composer: EpisodeFunctionBinding
    credit: EpisodeFunctionBinding
    rarefaction: EpisodeFunctionBinding
    continuation: EpisodeFunctionBinding

    def __post_init__(self) -> None:
        selections = (
            self.schema,
            self.composer,
            self.credit,
            self.rarefaction,
            self.continuation,
        )
        if any(
            not isinstance(selection, EpisodeFunctionBinding)
            for selection in selections
        ):
            raise TypeError(
                "controller selections must be EpisodeFunctionBinding values"
            )
        names = [selection.name for selection in selections]
        if len(set(names)) != len(names):
            raise ValueError("controller binding names must be unique")

    def as_record(self) -> dict[str, Any]:
        return {
            "schema": self.schema.as_record(),
            "composer": self.composer.as_record(),
            "credit": self.credit.as_record(),
            "rarefaction": self.rarefaction.as_record(),
            "continuation": self.continuation.as_record(),
        }

    def selections(self) -> tuple[EpisodeFunctionBinding, ...]:
        return (
            self.schema,
            self.composer,
            self.credit,
            self.rarefaction,
            self.continuation,
        )


@dataclass(frozen=True)
class EpisodeChildSlot:
    """One parent-owned child edge, builder, and message projections."""

    name: str
    accepted_interfaces: tuple[str, ...]
    build_child: EpisodeFunctionBinding
    prepare_request: EpisodeFunctionBinding
    receive_result: EpisodeFunctionBinding

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(_text(self.name, "child slot name")):
            raise ValueError("child slot name must be a lowercase identifier")
        if not isinstance(self.accepted_interfaces, tuple) or not self.accepted_interfaces:
            raise ValueError("a child slot must accept at least one interface")
        if any(
            not isinstance(value, str) or not _INTERFACE.fullmatch(value)
            for value in self.accepted_interfaces
        ):
            raise ValueError("accepted interfaces must be lowercase dotted names")
        if len(set(self.accepted_interfaces)) != len(self.accepted_interfaces):
            raise ValueError("accepted interfaces must be unique")
        if not isinstance(self.build_child, EpisodeFunctionBinding):
            raise TypeError("build_child must be an EpisodeFunctionBinding")
        if not isinstance(self.prepare_request, EpisodeFunctionBinding):
            raise TypeError("prepare_request must be an EpisodeFunctionBinding")
        if not isinstance(self.receive_result, EpisodeFunctionBinding):
            raise TypeError("receive_result must be an EpisodeFunctionBinding")
        boundary_names = (
            self.build_child.name,
            self.prepare_request.name,
            self.receive_result.name,
        )
        if len(set(boundary_names)) != len(boundary_names):
            raise ValueError("child-edge function binding names must be distinct")

    def as_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "accepted_interfaces": list(self.accepted_interfaces),
            "build_child": self.build_child.as_record(),
            "prepare_request": self.prepare_request.as_record(),
            "receive_result": self.receive_result.as_record(),
        }


@dataclass(frozen=True)
class EpisodeBindingDeclaration:
    """The method-level contract exposed by one reusable Episode binding."""

    grain_name: str
    interface: str
    topology_role: EpisodeTopologyRole
    goal: str
    unit: str
    result: str
    progress: str
    stopping: str
    admit_request: EpisodeFunctionBinding
    open_source: EpisodeFunctionBinding
    controller: EpisodeControllerBinding
    build_result: EpisodeFunctionBinding
    components: tuple[EpisodeFunctionBinding, ...]
    child_slots: tuple[EpisodeChildSlot, ...] = ()

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(_text(self.grain_name, "grain name")):
            raise ValueError("grain name must be a lowercase identifier")
        if not _INTERFACE.fullmatch(_text(self.interface, "Episode interface")):
            raise ValueError("Episode interface must be a lowercase dotted name")
        if not isinstance(self.topology_role, EpisodeTopologyRole):
            raise ValueError("topology_role must be an EpisodeTopologyRole")
        for name in ("goal", "unit", "result", "progress", "stopping"):
            _text(getattr(self, name), name)
        if not isinstance(self.admit_request, EpisodeFunctionBinding):
            raise TypeError("admit_request must be an EpisodeFunctionBinding")
        if not isinstance(self.open_source, EpisodeFunctionBinding):
            raise TypeError("open_source must be an EpisodeFunctionBinding")
        if not isinstance(self.controller, EpisodeControllerBinding):
            raise TypeError("controller must be an EpisodeControllerBinding")
        if not isinstance(self.build_result, EpisodeFunctionBinding):
            raise TypeError("build_result must be an EpisodeFunctionBinding")
        if not isinstance(self.components, tuple):
            raise ValueError("Episode components must be a tuple")
        if any(
            not isinstance(component, EpisodeFunctionBinding)
            for component in self.components
        ):
            raise ValueError(
                "components must contain EpisodeFunctionBinding values"
            )
        if not isinstance(self.child_slots, tuple) or any(
            not isinstance(slot, EpisodeChildSlot) for slot in self.child_slots
        ):
            raise ValueError("child_slots must contain EpisodeChildSlot values")
        function_names = [
            self.admit_request.name,
            self.open_source.name,
            self.build_result.name,
            *(selection.name for selection in self.controller.selections()),
            *(component.name for component in self.components),
            *(
                boundary.name
                for slot in self.child_slots
                for boundary in (
                    slot.build_child,
                    slot.prepare_request,
                    slot.receive_result,
                )
            ),
        ]
        if len(set(function_names)) != len(function_names):
            raise ValueError(
                "all function and handoff binding names must be unique within an Episode"
            )
        names = [slot.name for slot in self.child_slots]
        if len(set(names)) != len(names):
            raise ValueError("child slot names must be unique")
        if self.topology_role is EpisodeTopologyRole.LEAF and self.child_slots:
            raise ValueError("a leaf Episode cannot expose child Episode slots")
        if self.topology_role is EpisodeTopologyRole.BRANCH and not self.child_slots:
            raise ValueError("a branch Episode must expose a child Episode slot")

    def child_slot(self, name: str) -> EpisodeChildSlot:
        slot = next((item for item in self.child_slots if item.name == name), None)
        if slot is None:
            raise ValueError(
                f"Episode interface {self.interface!r} has no child slot {name!r}"
            )
        return slot

    def accepts(self, slot_name: str, child: "EpisodeBindingDeclaration") -> bool:
        if not isinstance(child, EpisodeBindingDeclaration):
            raise TypeError("child must be an EpisodeBindingDeclaration")
        return child.interface in self.child_slot(slot_name).accepted_interfaces

    def function_bindings(self) -> tuple[EpisodeFunctionBinding, ...]:
        """Return every exact function selection in structural role order."""

        return (
            self.admit_request,
            self.open_source,
            *self.controller.selections(),
            self.build_result,
            *self.components,
            *(
                boundary
                for slot in self.child_slots
                for boundary in (
                    slot.build_child,
                    slot.prepare_request,
                    slot.receive_result,
                )
            ),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "grain_name": self.grain_name,
            "interface": self.interface,
            "topology_role": self.topology_role.value,
            "goal": self.goal,
            "unit": self.unit,
            "result": self.result,
            "progress": self.progress,
            "stopping": self.stopping,
            "admit_request": self.admit_request.as_record(),
            "open_source": self.open_source.as_record(),
            "controller": self.controller.as_record(),
            "build_result": self.build_result.as_record(),
            "components": [
                component.as_record() for component in self.components
            ],
            "child_slots": [slot.as_record() for slot in self.child_slots],
        }


__all__ = [
    "EpisodeBindingDeclaration",
    "EpisodeChildSlot",
    "EpisodeControllerBinding",
    "EpisodeFunctionBinding",
    "EpisodeTopologyRole",
]
