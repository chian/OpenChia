"""Build ownership recovery and packaging of the shipped Refiner program."""

import os
from dataclasses import replace

from agent.duet_contracts import content_id
from agent.episode_contracts import OpaqueId
from episode_builder.service import _materializer_identity
from episode_runtime.records.experiments import artifact_fields, read_record


def owner_record():
    from openchia_cli.active_sessions import _own_start_time

    started = _own_start_time()
    if started is None:
        raise ValueError("Build ownership requires a verifiable process identity.")
    return {"pid": os.getpid(), "process_start_time": started}


def requested_jobs(host):
    state = host.store.get_duet(host.identity.duet_id.value)
    return [
        event["record"] for event in host.store.events(host.identity.duet_id.value)
        if event["event_type"] == "build_requested"
        and event["record"]["authority_head_approval_id"] == state["authority_head_approval_id"]
    ]


def builder_owner_status(host, job):
    from openchia_cli.active_sessions import _pid_liveness

    events = host.store.events(host.identity.duet_id.value)
    starts = [event for event in events
              if event["event_type"] in {"build_requested", "build_continue_requested"}
              and event["record"]["build_request_id"] == job["build_request_id"]]
    latest = starts[-1] if starts else None
    finished = [
        event for event in events
        if event["event_type"] in {"build_finished", "build_host_failure"}
        and event["record"]["build_request_id"] == job["build_request_id"]
        and (latest is None or event["sequence"] > latest["sequence"])
    ]
    if finished:
        final = finished[-1]
        return {
            "state": "finished",
            "build_state": final["record"].get("state", "host_error"),
            "error": final["record"].get("error"),
            "event_sequence": final["sequence"],
        }
    owner = job.get("owner") if latest is None else latest["record"].get("owner")
    live = None if owner is None else _pid_liveness(owner["pid"], owner["process_start_time"])
    return {"state": {True: "live", False: "stopped", None: "unknown"}[live]}


def require_owner_stopped(host, job):
    if builder_owner_status(host, job)["state"] not in {"finished", "stopped"}:
        raise ValueError("Previous build owner is live or unverifiable; it cannot be restarted.")


def unfinished_builder_status(host, current):
    """Recover construction/refinement status before any admitted receipt exists."""
    jobs = requested_jobs(host)
    if not jobs or jobs[-1]["build_request_id"] == current.get("build_request_id"):
        return current
    job = jobs[-1]
    request_id = job["build_request_id"]
    refinement = read_record(host.store, "build_job", build_request_id=request_id)
    start = read_record(host.store, "construction_start", build_request_id=request_id)
    attempts = host.build_store.attempts_for_build_request(request_id)
    receipts = host.build_store.receipts_for_build_request(request_id)
    progress = [
        {key: value for key, value in event["record"].items() if key != "build_request_id"}
        for event in host.store.events(host.identity.duet_id.value)
        if event["event_type"] == "build_progress"
        and event["record"]["build_request_id"] == request_id
    ]
    ownership = builder_owner_status(host, job)
    state = ownership.get("build_state") or {
        "stopped": "interrupted", "live": "refining", "unknown": "ownership_unknown",
    }[ownership["state"]]
    return {
        **current, "state": state, "build_request_id": request_id,
        "build_attempt_id": None if not attempts else attempts[0].build_attempt_id.value,
        "build_receipt_id": None if not receipts else receipts[0].receipt_id.value,
        "materialized_specification_id": None if start is None else start["record"]["handoff"]["materialized_specification"]["specification_id"],
        "refinement_baseline_id": None,
        "progress": host._empty_progress(state) if not progress else progress[-1],
        "refinement": None if refinement is None else {
            key: refinement["record"][key] for key in ("campaign_ref", "experiment_id")
        }, "error": ownership.get("error"),
        "ownership": ownership,
        "continuation": {
            "command": "/build continue", "stage": "construction" if refinement is None else "refining", "owner_verification_required": True,
            "owner_check_passed": ownership["state"] in {"finished", "stopped"},
        },
    }


def continued_materialization_request(host, request, builder):
    """Find/restart the shipped deterministic materializer using normal attempts.

    No model response is fabricated or source identity loosened. Its inert
    adapters are reproducible; a consumed partial nonce gets a linked successor,
    while a completed receipt is returned without another Builder invocation.
    """
    # Fresh authorization has no stored request yet. The claim lookup below
    # requires it, before EpisodeBuilder.build would normally publish it.
    host.build_store.put_build_request(request)
    identity = _materializer_identity(builder.planner.call_options, builder.emitter.call_options)
    seen = set()
    while request.build_request_id.value not in seen:
        seen.add(request.build_request_id.value)
        link = read_record(host.store, "build_continuation", predecessor_build_request_id=request.build_request_id.value)
        if link is not None:
            successor = host.build_store.read_build_request(link["record"]["build_request_id"])
            if replace(successor, request_nonce=request.request_nonce) != request:
                raise ValueError("materializer continuation changes its approved request")
            request = successor
            continue
        receipts = host.build_store.receipts_for_build_request(request.build_request_id)
        if receipts:
            if len(receipts) != 1:
                raise ValueError("materializer has ambiguous completed receipts")
            if not any(item.code == "build_cancelled" for item in receipts[0].deficits):
                return request, receipts[0]
        attempts = host.build_store.attempts_for_build_request(request.build_request_id)
        if not attempts and not host.build_store.build_request_consumed(request.build_request_id):
            return request, None
        if any(attempt.materializer != identity for attempt in attempts):
            raise ValueError("materializer source changed; the partial attempt cannot be continued")
        successor = replace(request, request_nonce=content_id(
            "build_continue", {"predecessor": request.build_request_id.value}
        ).value)
        host.build_store.put_build_request(successor)
        link = {"predecessor_build_request_id": request.build_request_id.value,
                "build_request_id": successor.build_request_id.value}
        fields = (
            artifact_fields("build_continuation", duet_id=request.frozen_workflow.duet_id.value,
                            predecessor_build_request_id=request.build_request_id.value, record=link),
            artifact_fields("build_parent", duet_id=request.frozen_workflow.duet_id.value,
                            build_request_id=successor.build_request_id.value, record=link),
        )
        with host.store.transaction():
            for item in fields:
                host.store.put_artifact(**item)
        request = successor
    raise ValueError("materializer continuation lineage contains a cycle")
