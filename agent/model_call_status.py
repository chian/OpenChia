"""Summarize the current refiner model call for ``/build status`` (#77).

Since #66 a ``/build`` does its work through the refiner Run, whose model calls
never pass the Builder's in-process wait tracker, so ``model_wait`` read null
even while a call had been silent for an hour. Every pinned call already writes
``model_launch_call`` events to the owning Duet's ledger; this reads the newest
call after the latest ``build_requested`` and reports its liveness.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

_TERMINAL = {"succeeded", "failed", "cancelled", "abandoned"}


def _age_seconds(recorded_at: str | None, now: datetime) -> float | None:
    if not recorded_at:
        return None
    try:
        then = datetime.fromisoformat(recorded_at)
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0.0, (now - then).total_seconds())


def model_wait_from_events(calls: Iterable[Mapping[str, Any]], *, now: datetime | None = None) -> dict | None:
    """Liveness of the newest model call among ``model_launch_call`` events (oldest first)."""
    now = now or datetime.now(timezone.utc)
    by_call: dict[str, list[Mapping[str, Any]]] = {}
    order: list[str] = []
    for event in calls:
        record = event.get("record") or {}
        call_id = record.get("call_id")
        if not call_id:
            continue
        if call_id not in by_call:
            by_call[call_id] = []
            order.append(call_id)
        by_call[call_id].append(record)
    if not order:
        return None
    current = by_call[order[-1]]
    first, last = current[0], current[-1]
    observed = [r for r in current if "idle_seconds" in r]
    activity = observed[-1] if observed else {}
    since_record = _age_seconds(activity.get("recorded_at"), now)
    idle = None
    if activity and since_record is not None:
        idle = round(float(activity.get("idle_seconds") or 0.0) + since_record, 1)
    terminal = last.get("state") in _TERMINAL
    age = _age_seconds(last.get("recorded_at"), now)
    return {
        "active": not terminal,
        "task": first.get("task"),
        "episode": first.get("episode_local_id"),
        "state": last.get("state"),
        "phase": activity.get("phase"),
        "idle_seconds": None if terminal else idle,
        # The status line renders elapsed_seconds as "wait …" / "reply … ago".
        "elapsed_seconds": None if terminal or idle is None else int(idle),
        "response_seen": any(r.get("phase") == "receiving_model_events" for r in observed),
        "physical_attempt": last.get("physical_attempt"),
        "endpoint": first.get("base_url"),
        "last_recorded_seconds_ago": None if age is None else round(age, 1),
    }


def refiner_model_wait(host) -> dict | None:
    """The newest model call of the current build, including its refiner Run's calls."""
    owner = host.identity.duet_id.value
    requested = [e["sequence"] for e in host.store.events(owner) if e["event_type"] == "build_requested"]
    if not requested:
        return None
    calls = [
        event for event in host.store.events_of_type("model_launch_call", after_sequence=requested[-1])
        if event.get("duet_id") == owner or (event.get("record") or {}).get("owner_duet_id") == owner
    ]
    return model_wait_from_events(calls)


__all__ = ["model_wait_from_events", "refiner_model_wait"]
