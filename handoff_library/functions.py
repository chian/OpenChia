"""Admission functions for closed Episode handoff records."""

from __future__ import annotations

from typing import Mapping

from .contracts import (
    ChildResult,
    DuetLaunchAddress,
    DuetLaunchRequest,
    HandoffPayloadContract,
    ParentRequest,
    ParentRequestAddress,
)


def _tuple(value: object, name: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be an array")
    return tuple(value)


def _payload_contract(value: object) -> HandoffPayloadContract:
    if isinstance(value, HandoffPayloadContract):
        return value
    return HandoffPayloadContract.from_record(value)


def admit_parent_request(
    value: object,
    expected: ParentRequestAddress,
    payload_contract: HandoffPayloadContract | Mapping[str, object],
) -> ParentRequest:
    """Admit exactly the request intended for one runtime child invocation."""

    if not isinstance(expected, ParentRequestAddress):
        raise TypeError("expected must be a ParentRequestAddress")
    if not isinstance(value, Mapping):
        raise ValueError("parent request must be an object")
    expected_fields = {
        "request_id",
        "parent_episode_id",
        "child_episode_id",
        "goal_id",
        "child_interface",
        "artifact_ids_by_role",
        "measurements",
        "states",
        "flags",
    }
    if set(value) != expected_fields:
        raise ValueError("parent request fields must match its closed contract")
    request = ParentRequest(
        request_id=value["request_id"],
        parent_episode_id=value["parent_episode_id"],
        child_episode_id=value["child_episode_id"],
        goal_id=value["goal_id"],
        child_interface=value["child_interface"],
        artifact_ids_by_role={
            role: _tuple(ids, f"artifact_ids_by_role.{role}")
            for role, ids in value["artifact_ids_by_role"].items()
        } if isinstance(value["artifact_ids_by_role"], Mapping) else value["artifact_ids_by_role"],
        measurements=value["measurements"],
        states=value["states"],
        flags=value["flags"],
    )
    for name in (
        "request_id",
        "parent_episode_id",
        "child_episode_id",
        "goal_id",
        "child_interface",
    ):
        if getattr(request, name) != getattr(expected, name):
            raise ValueError(f"parent request {name} does not match its invocation")
    _payload_contract(payload_contract).validate(
        artifact_ids_by_role=request.artifact_ids_by_role,
        measurements=request.measurements,
        states=request.states,
        flags=request.flags,
    )
    return request


def admit_child_result(
    value: object,
    request: ParentRequest,
    declared_channel_ids: tuple[str, ...],
    payload_contract: HandoffPayloadContract | Mapping[str, object],
) -> ChildResult:
    """Admit one result only for its exact request, interface, and channels."""

    if not isinstance(request, ParentRequest):
        raise TypeError("request must be an admitted ParentRequest")
    if not isinstance(declared_channel_ids, tuple) or any(
        not isinstance(channel_id, str) or not channel_id
        for channel_id in declared_channel_ids
    ):
        raise ValueError("declared_channel_ids must be a tuple of stable IDs")
    if len(set(declared_channel_ids)) != len(declared_channel_ids):
        raise ValueError("declared_channel_ids must be unique")
    if not isinstance(value, Mapping):
        raise ValueError("child result must be an object")
    expected = {
        "request_id",
        "child_episode_id",
        "child_interface",
        "logical_identity_ids_by_channel",
        "artifact_ids_by_role",
        "measurements",
        "states",
        "flags",
    }
    if set(value) != expected:
        raise ValueError("child result fields must match its closed contract")
    result = ChildResult(
        request_id=value["request_id"],
        child_episode_id=value["child_episode_id"],
        child_interface=value["child_interface"],
        logical_identity_ids_by_channel={
            channel: _tuple(ids, f"logical_identity_ids_by_channel.{channel}")
            for channel, ids in value["logical_identity_ids_by_channel"].items()
        } if isinstance(value["logical_identity_ids_by_channel"], Mapping) else value["logical_identity_ids_by_channel"],
        artifact_ids_by_role={
            role: _tuple(ids, f"artifact_ids_by_role.{role}")
            for role, ids in value["artifact_ids_by_role"].items()
        } if isinstance(value["artifact_ids_by_role"], Mapping) else value["artifact_ids_by_role"],
        measurements=value["measurements"],
        states=value["states"],
        flags=value["flags"],
    )
    if result.request_id != request.request_id:
        raise ValueError("child result request_id does not match its request")
    if result.child_episode_id != request.child_episode_id:
        raise ValueError("child result episode does not match its request")
    if result.child_interface != request.child_interface:
        raise ValueError("child result interface does not match its request")
    actual_channels = tuple(result.logical_identity_ids_by_channel)
    if set(actual_channels) != set(declared_channel_ids) or len(
        actual_channels
    ) != len(declared_channel_ids):
        raise ValueError(
            "child result must include every declared result channel exactly"
        )
    _payload_contract(payload_contract).validate(
        artifact_ids_by_role=result.artifact_ids_by_role,
        measurements=result.measurements,
        states=result.states,
        flags=result.flags,
    )
    return result


def admit_duet_launch_request(
    value: object,
    expected: DuetLaunchAddress,
    payload_contract: HandoffPayloadContract | Mapping[str, object],
) -> DuetLaunchRequest:
    if not isinstance(expected, DuetLaunchAddress):
        raise TypeError("expected must be a DuetLaunchAddress")
    if not isinstance(value, Mapping):
        raise ValueError("Duet launch request must be an object")
    expected_fields = {
        "request_id",
        "workflow_id",
        "goal_id",
        "artifact_ids_by_role",
        "measurements",
        "states",
        "flags",
    }
    if set(value) != expected_fields:
        raise ValueError("Duet launch request fields must match its closed contract")
    artifacts = value["artifact_ids_by_role"]
    request = DuetLaunchRequest(
        request_id=value["request_id"],
        workflow_id=value["workflow_id"],
        goal_id=value["goal_id"],
        artifact_ids_by_role={
            role: _tuple(ids, f"artifact_ids_by_role.{role}")
            for role, ids in artifacts.items()
        } if isinstance(artifacts, Mapping) else artifacts,
        measurements=value["measurements"],
        states=value["states"],
        flags=value["flags"],
    )
    for name in ("request_id", "workflow_id", "goal_id"):
        if getattr(request, name) != getattr(expected, name):
            raise ValueError(f"Duet launch {name} does not match its invocation")
    _payload_contract(payload_contract).validate(
        artifact_ids_by_role=request.artifact_ids_by_role,
        measurements=request.measurements,
        states=request.states,
        flags=request.flags,
    )
    return request


__all__ = [
    "admit_child_result",
    "admit_duet_launch_request",
    "admit_parent_request",
]
