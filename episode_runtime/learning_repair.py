"""Audit-linked representation repair within one frozen reasoning unit."""

from function_library.models import _thaw_json

from .contracts import RunEventKind
from .store import RunStoreConflict


def replay_repair(events, episode_id, request_hash):
    return next(
        (
            _thaw_json(e.payload)
            for e in events
            if e.kind is RunEventKind.LEARNING_REPAIR_REQUESTED
            and e.episode_id == episode_id
            and e.payload["request_hash"] == request_hash
        ),
        None,
    )


def audit_submission(
    *,
    events,
    publish,
    episode_id,
    unit_id,
    request_hash,
    producer_call_id,
    result,
    repair_of,
):
    attempts = [
        e
        for e in events
        if e.kind is RunEventKind.LEARNING_ATTEMPT
        and e.episode_id == episode_id
        and e.payload["unit_id"] == unit_id
    ]
    repairs = [
        e
        for e in events
        if e.kind is RunEventKind.LEARNING_REPAIR_REQUESTED
        and e.episode_id == episode_id
        and e.payload["unit_id"] == unit_id
    ]
    expected = repairs[-1].payload["repair_id"] if repairs else None
    if repair_of != expected:
        raise RunStoreConflict(
            "submission must follow the current unit's host repair request"
        )
    prior = next((e for e in attempts if e.payload.get("repair_of") == repair_of), None)
    if prior is not None:
        if prior.payload["request_hash"] != request_hash:
            raise RunStoreConflict("audited submission cannot change on retry")
        return prior
    return publish(
        RunEventKind.LEARNING_ATTEMPT,
        episode_id,
        {
            "unit_id": unit_id,
            "request_hash": request_hash,
            "producer_call_id": producer_call_id,
            "raw_result": result,
            **({"repair_of": repair_of} if repair_of is not None else {}),
        },
    )


def pending_submission(events, episode_id, unit_id, ordinal):
    audit = next(
        (
            e
            for e in reversed(events)
            if e.kind is RunEventKind.LEARNING_ATTEMPT
            and e.episode_id == episode_id
            and e.payload["unit_id"] == unit_id
        ),
        None,
    )
    if audit is None:
        return None
    payload = audit.payload
    return {
        "ordinal": ordinal,
        "result": _thaw_json(payload["raw_result"]),
        "producer_call_id": payload["producer_call_id"],
        **({"repair_of": payload["repair_of"]} if "repair_of" in payload else {}),
    }
