"""Closed data records for communication between nested Episodes."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from method_loop import ClosedRecord


_STABLE_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}_[0-9a-f]{24,64}$")
_INTERFACE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_TOKEN = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")


def _stable_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not _STABLE_ID.fullmatch(value):
        raise ValueError(f"{name} must be a stable opaque ID")
    return value


def _interface(value: object) -> str:
    if not isinstance(value, str) or not _INTERFACE.fullmatch(value):
        raise ValueError("child_interface must be a lowercase dotted name")
    return value


def _ids(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be a tuple")
    result = tuple(_stable_id(item, name) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must contain unique IDs")
    return result


def _ids_by_role(value: object, name: str) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    result: dict[str, tuple[str, ...]] = {}
    for role, raw in value.items():
        if not isinstance(role, str) or not _TOKEN.fullmatch(role):
            raise ValueError(f"{name} keys must be closed lowercase tokens")
        result[role] = _ids(raw, f"{name}.{role}")
    return MappingProxyType(result)


def _identities_by_channel(value: object) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise ValueError("logical_identity_ids_by_channel must be an object")
    result: dict[str, tuple[str, ...]] = {}
    for channel_id, raw in value.items():
        key = _stable_id(channel_id, "result channel ID")
        result[key] = _ids(raw, f"logical identities in {key}")
    return MappingProxyType(result)


def _measurements(value: object) -> Mapping[str, float]:
    if not isinstance(value, Mapping):
        raise ValueError("measurements must be an object")
    result: dict[str, float] = {}
    for name, raw in value.items():
        if not isinstance(name, str) or not _TOKEN.fullmatch(name):
            raise ValueError("measurement names must be closed lowercase tokens")
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError("measurements must be numeric")
        number = float(raw)
        if not math.isfinite(number):
            raise ValueError("measurements must be finite")
        result[name] = number
    return MappingProxyType(result)


def _states(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("states must be an object")
    result: dict[str, str] = {}
    for name, raw in value.items():
        if not isinstance(name, str) or not _TOKEN.fullmatch(name):
            raise ValueError("state names must be closed lowercase tokens")
        if not isinstance(raw, str) or not _TOKEN.fullmatch(raw):
            raise ValueError("state values must be closed lowercase tokens")
        result[name] = raw
    return MappingProxyType(result)


def _flags(value: object) -> Mapping[str, bool]:
    if not isinstance(value, Mapping):
        raise ValueError("flags must be an object")
    result: dict[str, bool] = {}
    for name, raw in value.items():
        if not isinstance(name, str) or not _TOKEN.fullmatch(name):
            raise ValueError("flag names must be closed lowercase tokens")
        if not isinstance(raw, bool):
            raise ValueError("flag values must be boolean")
        result[name] = raw
    return MappingProxyType(result)


def _tokens(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be a tuple")
    if any(not isinstance(item, str) or not _TOKEN.fullmatch(item) for item in value):
        raise ValueError(f"{name} must contain closed lowercase tokens")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must contain unique tokens")
    return value


def _array(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    return tuple(value)


def _state_vocabulary(value: object) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise ValueError("state_values must be an object")
    result: dict[str, tuple[str, ...]] = {}
    for name, raw_values in value.items():
        if not isinstance(name, str) or not _TOKEN.fullmatch(name):
            raise ValueError("state names must be closed lowercase tokens")
        values = _tokens(raw_values, f"state_values.{name}")
        if not values:
            raise ValueError("each admitted state needs at least one value")
        result[name] = values
    return MappingProxyType(result)


@dataclass(frozen=True)
class HandoffPayloadContract:
    """The exact static vocabulary admitted on one Episode edge."""

    artifact_roles: tuple[str, ...] = ()
    required_artifact_roles: tuple[str, ...] = ()
    measurement_names: tuple[str, ...] = ()
    required_measurement_names: tuple[str, ...] = ()
    state_values: Mapping[str, tuple[str, ...]] = MappingProxyType({})
    required_state_names: tuple[str, ...] = ()
    flag_names: tuple[str, ...] = ()
    required_flag_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "artifact_roles",
            "required_artifact_roles",
            "measurement_names",
            "required_measurement_names",
            "required_state_names",
            "flag_names",
            "required_flag_names",
        ):
            object.__setattr__(
                self,
                field_name,
                _tokens(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "state_values",
            _state_vocabulary(self.state_values),
        )
        subset_pairs = (
            (self.required_artifact_roles, self.artifact_roles, "artifact roles"),
            (
                self.required_measurement_names,
                self.measurement_names,
                "measurement names",
            ),
            (
                self.required_state_names,
                tuple(self.state_values),
                "state names",
            ),
            (self.required_flag_names, self.flag_names, "flag names"),
        )
        for required, admitted, label in subset_pairs:
            if not set(required) <= set(admitted):
                raise ValueError(f"required {label} must be admitted {label}")

    def validate(
        self,
        *,
        artifact_ids_by_role: Mapping[str, tuple[str, ...]],
        measurements: Mapping[str, float],
        states: Mapping[str, str],
        flags: Mapping[str, bool],
    ) -> None:
        actual_artifacts = set(artifact_ids_by_role)
        actual_measurements = set(measurements)
        actual_states = set(states)
        actual_flags = set(flags)
        checks = (
            (
                actual_artifacts,
                set(self.artifact_roles),
                set(self.required_artifact_roles),
                "artifact roles",
            ),
            (
                actual_measurements,
                set(self.measurement_names),
                set(self.required_measurement_names),
                "measurement names",
            ),
            (
                actual_states,
                set(self.state_values),
                set(self.required_state_names),
                "state names",
            ),
            (
                actual_flags,
                set(self.flag_names),
                set(self.required_flag_names),
                "flag names",
            ),
        )
        for actual, admitted, required, label in checks:
            unknown = sorted(actual - admitted)
            missing = sorted(required - actual)
            if unknown or missing:
                raise ValueError(
                    f"handoff {label} mismatch: missing={missing!r}, "
                    f"unknown={unknown!r}"
                )
        empty_required = sorted(
            role
            for role in self.required_artifact_roles
            if not artifact_ids_by_role[role]
        )
        if empty_required:
            raise ValueError(
                f"required artifact roles must contain an ID: {empty_required!r}"
            )
        invalid_states = sorted(
            name
            for name, value in states.items()
            if value not in self.state_values[name]
        )
        if invalid_states:
            raise ValueError(
                f"handoff states contain undeclared values: {invalid_states!r}"
            )

    def as_record(self) -> dict[str, object]:
        return {
            "artifact_roles": list(self.artifact_roles),
            "required_artifact_roles": list(self.required_artifact_roles),
            "measurement_names": list(self.measurement_names),
            "required_measurement_names": list(self.required_measurement_names),
            "state_values": {
                name: list(values) for name, values in self.state_values.items()
            },
            "required_state_names": list(self.required_state_names),
            "flag_names": list(self.flag_names),
            "required_flag_names": list(self.required_flag_names),
        }

    @classmethod
    def from_record(cls, value: object) -> "HandoffPayloadContract":
        if not isinstance(value, Mapping):
            raise ValueError("handoff payload contract must be an object")
        expected = {
            "artifact_roles",
            "required_artifact_roles",
            "measurement_names",
            "required_measurement_names",
            "state_values",
            "required_state_names",
            "flag_names",
            "required_flag_names",
        }
        if set(value) != expected:
            raise ValueError("handoff payload contract fields must be exact")
        state_values = value["state_values"]
        return cls(
            artifact_roles=_array(value["artifact_roles"], "artifact_roles"),
            required_artifact_roles=_array(
                value["required_artifact_roles"],
                "required_artifact_roles",
            ),
            measurement_names=_array(
                value["measurement_names"],
                "measurement_names",
            ),
            required_measurement_names=_array(
                value["required_measurement_names"],
                "required_measurement_names",
            ),
            state_values={
                name: _array(values, f"state_values.{name}")
                for name, values in state_values.items()
            }
            if isinstance(state_values, Mapping)
            else state_values,
            required_state_names=_array(
                value["required_state_names"],
                "required_state_names",
            ),
            flag_names=_array(value["flag_names"], "flag_names"),
            required_flag_names=_array(
                value["required_flag_names"],
                "required_flag_names",
            ),
        )


@dataclass(frozen=True)
class ParentRequestAddress:
    """Runtime-owned correlation facts for one intended child invocation."""

    request_id: str
    parent_episode_id: str
    child_episode_id: str
    goal_id: str
    child_interface: str

    def __post_init__(self) -> None:
        for name in (
            "request_id",
            "parent_episode_id",
            "child_episode_id",
            "goal_id",
        ):
            object.__setattr__(self, name, _stable_id(getattr(self, name), name))
        object.__setattr__(self, "child_interface", _interface(self.child_interface))


@dataclass(frozen=True)
class DuetLaunchAddress:
    """Runtime-owned correlation facts for one approved root launch."""

    request_id: str
    workflow_id: str
    goal_id: str

    def __post_init__(self) -> None:
        for name in ("request_id", "workflow_id", "goal_id"):
            object.__setattr__(self, name, _stable_id(getattr(self, name), name))


@dataclass(frozen=True)
class ParentRequest(ClosedRecord):
    """The complete instruction-free record a parent sends to one child."""

    request_id: str
    parent_episode_id: str
    child_episode_id: str
    goal_id: str
    child_interface: str
    artifact_ids_by_role: Mapping[str, tuple[str, ...]] = MappingProxyType({})
    measurements: Mapping[str, float] = MappingProxyType({})
    states: Mapping[str, str] = MappingProxyType({})
    flags: Mapping[str, bool] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _stable_id(self.request_id, "request_id"))
        object.__setattr__(
            self,
            "parent_episode_id",
            _stable_id(self.parent_episode_id, "parent_episode_id"),
        )
        object.__setattr__(
            self,
            "child_episode_id",
            _stable_id(self.child_episode_id, "child_episode_id"),
        )
        object.__setattr__(self, "goal_id", _stable_id(self.goal_id, "goal_id"))
        object.__setattr__(self, "child_interface", _interface(self.child_interface))
        object.__setattr__(
            self,
            "artifact_ids_by_role",
            _ids_by_role(self.artifact_ids_by_role, "artifact_ids_by_role"),
        )
        object.__setattr__(self, "measurements", _measurements(self.measurements))
        object.__setattr__(self, "states", _states(self.states))
        object.__setattr__(self, "flags", _flags(self.flags))

    def as_record(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "parent_episode_id": self.parent_episode_id,
            "child_episode_id": self.child_episode_id,
            "goal_id": self.goal_id,
            "child_interface": self.child_interface,
            "artifact_ids_by_role": {
                role: list(ids) for role, ids in self.artifact_ids_by_role.items()
            },
            "measurements": dict(self.measurements),
            "states": dict(self.states),
            "flags": dict(self.flags),
        }


@dataclass(frozen=True)
class ChildResult(ClosedRecord):
    """The complete instruction-free record a child returns to its parent."""

    request_id: str
    child_episode_id: str
    child_interface: str
    logical_identity_ids_by_channel: Mapping[str, tuple[str, ...]] = MappingProxyType({})
    artifact_ids_by_role: Mapping[str, tuple[str, ...]] = MappingProxyType({})
    measurements: Mapping[str, float] = MappingProxyType({})
    states: Mapping[str, str] = MappingProxyType({})
    flags: Mapping[str, bool] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _stable_id(self.request_id, "request_id"))
        object.__setattr__(
            self,
            "child_episode_id",
            _stable_id(self.child_episode_id, "child_episode_id"),
        )
        object.__setattr__(self, "child_interface", _interface(self.child_interface))
        object.__setattr__(
            self,
            "logical_identity_ids_by_channel",
            _identities_by_channel(self.logical_identity_ids_by_channel),
        )
        object.__setattr__(
            self,
            "artifact_ids_by_role",
            _ids_by_role(self.artifact_ids_by_role, "artifact_ids_by_role"),
        )
        object.__setattr__(self, "measurements", _measurements(self.measurements))
        object.__setattr__(self, "states", _states(self.states))
        object.__setattr__(self, "flags", _flags(self.flags))

    def as_record(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "child_episode_id": self.child_episode_id,
            "child_interface": self.child_interface,
            "logical_identity_ids_by_channel": {
                channel: list(ids)
                for channel, ids in self.logical_identity_ids_by_channel.items()
            },
            "artifact_ids_by_role": {
                role: list(ids) for role, ids in self.artifact_ids_by_role.items()
            },
            "measurements": dict(self.measurements),
            "states": dict(self.states),
            "flags": dict(self.flags),
        }


@dataclass(frozen=True)
class DuetLaunchRequest(ClosedRecord):
    """Closed root-launch envelope; rich Duet specifications stay in artifacts."""

    request_id: str
    workflow_id: str
    goal_id: str
    artifact_ids_by_role: Mapping[str, tuple[str, ...]]
    measurements: Mapping[str, float] = MappingProxyType({})
    states: Mapping[str, str] = MappingProxyType({})
    flags: Mapping[str, bool] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _stable_id(self.request_id, "request_id"))
        object.__setattr__(self, "workflow_id", _stable_id(self.workflow_id, "workflow_id"))
        object.__setattr__(self, "goal_id", _stable_id(self.goal_id, "goal_id"))
        object.__setattr__(
            self,
            "artifact_ids_by_role",
            _ids_by_role(self.artifact_ids_by_role, "artifact_ids_by_role"),
        )
        object.__setattr__(self, "measurements", _measurements(self.measurements))
        object.__setattr__(self, "states", _states(self.states))
        object.__setattr__(self, "flags", _flags(self.flags))

    def as_record(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "workflow_id": self.workflow_id,
            "goal_id": self.goal_id,
            "artifact_ids_by_role": {
                role: list(ids) for role, ids in self.artifact_ids_by_role.items()
            },
            "measurements": dict(self.measurements),
            "states": dict(self.states),
            "flags": dict(self.flags),
        }


__all__ = [
    "ChildResult",
    "DuetLaunchAddress",
    "DuetLaunchRequest",
    "HandoffPayloadContract",
    "ParentRequest",
    "ParentRequestAddress",
]
