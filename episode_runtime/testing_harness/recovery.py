"""Recover stopped execution publication using the shared owner and Run records."""

import asyncio

from ..contracts import RunEventOrigin, RunTerminalStatus
from ..executor_lifecycle import verify_stopped_executor
from ..store import RunStoreNotFound


def execution_owner(artifacts, registration):
    rows = [
        event for event in artifacts.events(registration.duet_id.value)
        if event["event_type"] in {"run_execution_owned", "run_requested"}
        and event["record"].get("run_id") == registration.run_id.value
        and event["record"].get("owner") is not None
    ]
    return None if not rows else rows[-1]["record"]["owner"]


def execution_owner_status(artifacts, registration):
    from openchia_cli.active_sessions import _pid_liveness

    lifecycle = [
        event for event in artifacts.events(registration.duet_id.value)
        if event["event_type"] in {"run_execution_owned", "run_requested", "run_owner_released"}
        and event["record"].get("run_id") == registration.run_id.value
        and event["record"].get("owner") is not None
    ]
    owned = [event for event in lifecycle if event["event_type"] != "run_owner_released"]
    current = None if not owned else owned[-1]
    owner = None if current is None else current["record"]["owner"]
    if current is not None and any(
        event["sequence"] > current["sequence"]
        and event["event_type"] == "run_owner_released"
        and event["record"]["owner"] == owner
        and event["record"].get("lease_id") == current["record"].get("lease_id")
        for event in lifecycle
    ):
        return {"state": "released", "owner": owner}
    live = None if owner is None else _pid_liveness(owner["pid"], owner["process_start_time"])
    return {"state": {True: "live", False: "stopped", None: "unknown"}[live], "owner": owner}


def require_stopped_owner(artifacts, registration, *, legacy_terminal=False):
    status = execution_owner_status(artifacts, registration)
    owner = status["owner"]
    if owner is None and legacy_terminal:
        return {"state": "legacy_terminal", "owner": None}
    if status["state"] not in {"stopped", "released"}:
        raise ValueError("Run host owner is live or unverifiable; continuation cannot start another owner")
    return status


def release_execution_owner(artifacts, registration, lease):
    with artifacts.transaction():
        owned = [
            event for event in artifacts.events(registration.duet_id.value)
            if event["event_type"] == "run_execution_owned"
            and event["record"].get("run_id") == registration.run_id.value
        ]
        if not owned or any(owned[-1]["record"].get(key) != lease[key] for key in ("owner", "lease_id")):
            raise ValueError("execution ownership changed before release")
        artifacts.append_event(
            duet_id=registration.duet_id.value, event_type="run_owner_released",
            provenance="host_validation", record={
                "run_id": registration.run_id.value,
                "registration_hash": registration.registration_hash.value,
                **lease,
            },
        )


def claim_execution_owner(artifacts, registration):

    # The same transaction serializes competing restart commands. A dispatch
    # without a claim never authorized START and may resume that exact identity.
    with artifacts.transaction():
        require_stopped_owner(artifacts, registration)
        lease = new_execution_lease()
        artifacts.append_event(
            duet_id=registration.duet_id.value, event_type="run_execution_owned",
            provenance="host_validation", record={
                "run_id": registration.run_id.value,
                "registration_hash": registration.registration_hash.value,
                **lease,
            },
        )
    return lease


def new_execution_lease():
    from secrets import token_hex
    from agent.openchia_build_recovery import owner_record

    return {"owner": owner_record(), "lease_id": token_hex(32)}


def recover_stopped_run(*, runs, artifacts, executor, registration):
    """Return terminal evidence, or None for an unstarted, ownerless dispatch.

    A terminal event is recovered only after both the host owner and the exact
    confined worker are stopped. This is an interruption, never success inferred
    from a stopped process. Existing terminal status is preserved unchanged.
    """
    try:
        claim = runs.read_claim(registration.run_id)
    except RunStoreNotFound:
        require_stopped_owner(artifacts, registration)
        return None
    prefix = runs.read_committed_prefix(registration.run_id)
    terminal = bool(prefix and prefix[-1].terminal)
    ownership = require_stopped_owner(artifacts, registration, legacy_terminal=terminal)
    stopped = asyncio.run(verify_stopped_executor(executor, claim))
    if terminal:
        return runs.complete_terminal_publication(registration.run_id)
    sequence = max(
        (event.sender_sequence for event in prefix if event.origin is RunEventOrigin.HOST),
        default=-1,
    ) + 1
    return runs.finalize_run(
        run_id=registration.run_id, origin=RunEventOrigin.HOST,
        sender_sequence=sequence, terminal_status=RunTerminalStatus.INTERRUPTED,
        typed_status={
            "kind": "owner_process_stopped", "owner": ownership,
            "executor": stopped,
            "last_event_id": None if not prefix else prefix[-1].event_id.value,
            "detail": "Recovered after verified host and worker process death; completion was not observed.",
        },
    )
