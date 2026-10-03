"""Compact event projections for scope discovery, never executable audit copies."""

from collections.abc import Mapping
from typing import Literal

from pydantic import Field, JsonValue

from agent.duet_contracts import digest_record
from method_loop.identities import EpisodeRef, UnitRef

from .runs import ContentRecord, EventPosition


class EventFact(ContentRecord):
    schema_version: Literal[1] = 1
    run_id: str
    registration_hash: str
    event: EventPosition
    episode_id: str | None
    kind: str
    origin: str
    ordinal: int = Field(ge=0)
    detail: dict[str, JsonValue]


def _text(value):
    return value if isinstance(value, str) and len(value) <= 4096 else None


def _start(event, logical_run_id=None):
    payload = event.payload
    path = payload.get("episode_path")
    try:
        ref = EpisodeRef((logical_run_id or event.run_id).value, tuple((part["grain"], part["key"]) for part in path))
        if event.episode_id is None or ref.episode_id != event.episode_id.value:
            raise ValueError("invocation path differs from event owner")
    except (KeyError, TypeError, ValueError):
        path = None
    else:
        path = [{"grain": grain, "key": key} for grain, key in ref.path]
    state = _text(payload.get("goal_state_id"))
    initial = _text(payload.get("initial_goal_state_id"))
    return {
        "episode_path": path,
        "request_hash": digest_record(payload["request"]).value if isinstance(payload.get("request"), Mapping) else None,
        "goal_state_id": state, "initial_goal_state_id": initial,
        "has_goal_view": isinstance(payload.get("goal_view"), Mapping),
        "initial_state_reproducible": None if state is None or initial is None else state == initial,
    }


def _unit(event):
    try:
        ref = UnitRef.from_record(event.payload.get("unit_ref"))
        if event.episode_id is None or ref.episode_id != event.episode_id.value:
            raise ValueError("unit belongs to another invocation")
    except (TypeError, ValueError):
        ref = None
    return {
        "unit_ref": None if ref is None else ref.as_record(),
        "unit_label": _text(event.payload.get("unit_label")),
        "has_controller_input": event.payload.get("controller_input") is not None,
        "has_controller_step": event.payload.get("controller_step") is not None,
        "has_goal_result": event.payload.get("goal_result") is not None,
    }


def _completion(event):
    from method_loop.episode import EpisodeCompletion

    try:
        value = EpisodeCompletion(**{key: event.payload[key] for key in (
            "ended_by", "end_reason", "units_consumed",
        )})
    except (KeyError, TypeError, ValueError):
        return {"completion": None}
    return {"completion": value.as_record()}


def _response(event):
    return {
        "has_response_content": event.payload.get("response") is not None,
        "reused": event.payload.get("reused_from") is not None,
    }


_DETAIL = {
    "episode_started": _start,
    "unit_completed": _unit,
    "episode_completed": _completion,
    "model_responded": _response,
    "http_responded": _response,
}


def event_fact(event, ordinal, *, logical_run_id=None):
    project = _DETAIL.get(event.kind.value)
    return EventFact(
        run_id=event.run_id.value, registration_hash=event.registration_hash.value,
        event=EventPosition(sequence=event.sequence, event_id=event.event_id.value, content_hash=event.event_hash.value),
        episode_id=None if event.episode_id is None else event.episode_id.value,
        kind=event.kind.value, origin=event.origin.value, ordinal=ordinal,
        detail=_start(event, logical_run_id) if event.kind.value == "episode_started" else ({} if project is None else project(event)),
    )


def unit_prefix(current, *, invocation_start, previous_unit):
    """Locate history before selection, without calling it a restored state.

    Both indexed discovery and verified boundary capture use this projection.
    The selected unit's completed event is deliberately not its starting point.
    Physical attempts lacking the earlier boundary cannot invent inherited facts.
    """
    unit = current.detail.get("unit_ref")
    index = None if unit is None else unit["unit_index"]
    boundary = invocation_start if index == 0 else previous_unit
    reason = None
    if unit is None:
        reason = "unit_identity_missing"
    elif invocation_start is None:
        reason = "invocation_start_missing_in_attempt"
    elif invocation_start.ordinal != 0:
        reason = "invocation_identity_repeated"
    elif index != current.ordinal:
        reason = "preceding_units_missing_or_inconsistent"
    elif index > 0 and (
        previous_unit is None
        or previous_unit.detail.get("unit_ref") is None
        or previous_unit.detail["unit_ref"]["unit_index"] != index - 1
    ):
        reason = "preceding_unit_missing_or_inconsistent"
    elif boundary.event.sequence < invocation_start.event.sequence or any(
        item.run_id != current.run_id
        or item.registration_hash != current.registration_hash
        or item.episode_id != current.episode_id
        or item.origin != "worker"
        or item.event.sequence >= current.event.sequence
        for item in (invocation_start, boundary)
    ) or current.origin != "worker":
        reason = "boundary_context_mismatch"
    return {
        "status": "located" if reason is None else "unavailable",
        "kind": None if index is None else ("after_invocation_start" if index == 0 else "after_previous_unit"),
        "completed_units": index,
        "through_event_ref": None if reason is not None else {
            "run_id": boundary.run_id,
            "event_id": boundary.event.event_id,
            "content_hash": boundary.event.content_hash,
        },
        "gap": reason,
        "restoration_verified": False,
    }
