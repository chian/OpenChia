"""Project exact recordings from the existing verified Run journal.

This is a view of committed evidence, not another replay log. Old hash-only
events and interrupted exchanges remain visible but cannot supply a response.
"""

from collections.abc import Mapping

from agent.duet_contracts import content_id, digest_record
from agent.episode_contracts import OpaqueId

from ..broker import (
    admit_model_request,
    admit_model_response,
    model_request_hash,
    model_response_hash,
)
from ..contracts import RunEventKind, RunEventOrigin
from ..http_contracts import (
    admit_http_request,
    admit_http_response,
    http_request_hash,
    http_response_hash,
)
from ..protocol import _thaw_json, episode_id_for_path
from ..store import RunStoreNotFound


_REQUESTS = {
    RunEventKind.MODEL_REQUESTED: ("model", "model_request_id"),
    RunEventKind.HTTP_REQUESTED: ("http", "http_request_id"),
    RunEventKind.LEARNING_REQUESTED: ("learning", "request_id"),
    RunEventKind.REFINEMENT_REQUESTED: ("refinement", "request_id"),
    RunEventKind.EXPERIMENT_REQUESTED: ("experiment", "request_id"),
}
_RESPONSES = {
    RunEventKind.MODEL_RESPONDED: ("model", "model_request_id"),
    RunEventKind.HTTP_RESPONDED: ("http", "http_request_id"),
    RunEventKind.LEARNING_RESPONDED: ("learning", "request_id"),
    RunEventKind.REFINEMENT_RESPONDED: ("refinement", "request_id"),
    RunEventKind.EXPERIMENT_RESPONDED: ("experiment", "request_id"),
}
HOST_EXCHANGE_CHANNELS = ("learning", "refinement", "experiment")


def _host_request_hash(value):
    if (
        not isinstance(value, Mapping)
        or set(value) != {"operation", "payload"}
        or not isinstance(value["operation"], str)
        or not value["operation"]
        or not isinstance(value["payload"], Mapping)
    ):
        raise ValueError("recorded host request must contain an operation and payload")
    return digest_record(value).value


def _host_response_hash(value):
    if not isinstance(value, Mapping):
        raise ValueError("recorded host response must be a typed object")
    return digest_record(value).value


_REQUEST_HASH = {
    "model": lambda value: model_request_hash(admit_model_request(value)).value,
    "http": lambda value: http_request_hash(admit_http_request(value)).value,
    **dict.fromkeys(HOST_EXCHANGE_CHANNELS, _host_request_hash),
}
_RESPONSE_HASH = {
    "model": lambda value: model_response_hash(admit_model_response(value)).value,
    "http": lambda value: http_response_hash(admit_http_response(value)).value,
    **dict.fromkeys(HOST_EXCHANGE_CHANNELS, _host_response_hash),
}
_TERMINAL = {
    RunEventKind.RUN_SUCCEEDED: "succeeded",
    RunEventKind.RUN_FAILED: "failed",
    RunEventKind.RUN_BLOCKED: "blocked",
    RunEventKind.RUN_INTERRUPTED: "interrupted",
    RunEventKind.RUN_CANCELLED: "cancelled",
    RunEventKind.RUN_INVALID: "invalid",
    RunEventKind.RUN_RESOURCE_LIMITED: "resource_limited",
}


def event_reference(event):
    return {
        "run_id": event.run_id.value,
        "event_id": event.event_id.value,
        "content_hash": event.event_hash.value,
    }


def read_recording(
    runs, run_id, *, episode_ids=None, through_event_ref=None, projection_version=2
):
    """Select exact invocations, without exposing unrelated child histories.

    An omitted selector explicitly requests the complete Run. A saved prefix
    requires both event identity and hash, so continuing a Run cannot silently
    change an already selected recording.
    """
    if type(projection_version) is not int or projection_version not in {1, 2}:
        raise ValueError("unsupported recording projection version")
    run_id = OpaqueId(run_id) if isinstance(run_id, str) else run_id
    registration = runs.read_registration(run_id)
    try:
        snapshot = runs.read_terminal_snapshot(run_id)
    except RunStoreNotFound:
        events = runs.read_committed_prefix(run_id)
        terminal_evidence_available = False
    else:
        events = snapshot.events
        terminal_evidence_available = True
    if through_event_ref is not None:
        match = next(
            (
                index
                for index, event in enumerate(events)
                if event_reference(event) == through_event_ref
            ),
            None,
        )
        if match is None:
            raise ValueError("recording boundary is absent or has a different hash")
        events = events[: match + 1]
    selected = (
        None
        if episode_ids is None
        else {OpaqueId(value).value for value in episode_ids}
    )
    available = {
        event.episode_id.value for event in events if event.episode_id is not None
    }
    if selected is not None and (not selected or not selected <= available):
        raise ValueError("recording selection must name existing Episode invocations")
    pending, exchanges, gaps, units, invocations = {}, [], [], [], []
    learning = []
    components = []
    seen_requests = set()
    terminal_status = None
    for event in events:
        terminal_status = _TERMINAL.get(event.kind, terminal_status)
        if selected is not None and (
            event.episode_id is None or event.episode_id.value not in selected
        ):
            continue
        if event.kind is RunEventKind.EPISODE_STARTED:
            invocations.append({
                **_thaw_json(event.payload),
                "episode_id": event.episode_id.value,
                "event_ref": event_reference(event),
            })
        elif event.kind is RunEventKind.UNIT_COMPLETED:
            units.append({
                **_thaw_json(event.payload),
                "episode_id": event.episode_id.value,
                "event_ref": event_reference(event),
            })
        elif event.kind is RunEventKind.COMPONENT_OBSERVED:
            components.append({
                **_thaw_json(event.payload),
                "episode_id": event.episode_id.value,
                "event_ref": event_reference(event),
            })
        elif event.kind in {
            RunEventKind.LEARNING_OPENED,
            RunEventKind.LEARNING_COMMITTED,
        }:
            if event.origin is not RunEventOrigin.HOST_LEARNING:
                raise ValueError(
                    "numerical learning evidence must originate from the host"
                )
            payload = _thaw_json(event.payload)
            # A numerical experiment reuses admitted observations, not raw
            # lessons or candidate claims, and never invokes admission again.
            projected = (
                payload
                if event.kind is RunEventKind.LEARNING_OPENED
                else {
                    "unit_id": payload["unit_id"],
                    "baseline_ids": payload["baseline_ids"],
                    "observation_ids": payload["observation_ids"],
                    "numeric_step": payload["receipt"]["numeric_step"],
                    "terminal_state": payload["receipt"]["terminal_state"],
                }
            )
            learning.append({
                "kind": event.kind.value,
                "episode_id": event.episode_id.value,
                "event_ref": event_reference(event),
                "payload": projected,
            })
        elif event.kind in _REQUESTS:
            kind, key = _REQUESTS[event.kind]
            if projection_version == 1 and kind in HOST_EXCHANGE_CHANNELS:
                continue
            identity = (kind, OpaqueId(event.payload[key]).value)
            if identity in seen_requests:
                raise ValueError("recording contains duplicate request identity")
            seen_requests.add(identity)
            pending[identity] = event
        elif event.kind in _RESPONSES:
            kind, key = _RESPONSES[event.kind]
            if projection_version == 1 and kind in HOST_EXCHANGE_CHANNELS:
                continue
            requested = pending.pop((kind, OpaqueId(event.payload[key]).value), None)
            if requested is None:
                raise ValueError("recorded response has no preceding request")
            exchange, gap = _exchange(
                registration, kind, requested, event, projection_version
            )
            if gap is not None:
                gaps.append(gap)
            else:
                exchanges.append(exchange)
    for requested in pending.values():
        gaps.append({
            "kind": "response_not_committed",
            **({"channel": _REQUESTS[requested.kind][0]} if projection_version == 2 else {}),
            "event_ref": event_reference(requested),
            "detail": "This request has no committed response; it cannot answer a replay.",
        })
    result = {
        "schema_version": projection_version,
        "registration_ref": {
            "run_id": run_id.value,
            "content_hash": registration.registration_hash.value,
        },
        "through_event_ref": event_reference(events[-1]) if events else None,
        "selected_episode_ids": sorted(available if selected is None else selected),
        "source_terminal_status": terminal_status,
        "terminal_evidence_available": terminal_evidence_available
        and terminal_status is not None,
        "exchanges": exchanges,
        "invocations": invocations,
        "units": units,
        "learning": learning,
        **({"components": components} if components else {}),
        "gaps": gaps,
    }
    # Terminal artifact publication can finish after this journal prefix was
    # saved. That changes availability, not the identity of the recorded facts.
    identity = {
        key: value
        for key, value in result.items()
        if key != "terminal_evidence_available"
    }
    return {"recording_id": content_id("run_recording", identity).value, **result}


def _exchange(registration, kind, requested, responded, projection_version):
    before, after = _thaw_json(requested.payload), _thaw_json(responded.payload)
    if (
        requested.origin is not RunEventOrigin.WORKER
        or responded.origin is not RunEventOrigin.HOST
    ):
        raise ValueError("recording exchange has an invalid origin")
    if requested.episode_id != responded.episode_id:
        raise ValueError("response differs from its recorded request context")
    request = before.get("request")
    path = before.get("episode_path")
    response = (
        {"text": after.get("response_text"), "route": after.get("route")}
        if kind == "model"
        else after.get("response")
    )
    missing = [
        name for name, value in (
            ("request", request),
            ("episode_path", path),
            ("response", response),
            ("request_hash", before.get("request_hash")),
            ("response_request_hash", after.get("request_hash")),
            ("response_hash", after.get("response_hash")),
        ) if value is None
    ]
    if kind == "model":
        missing.extend(name for name in ("response_text", "route") if after.get(name) is None)
    if missing:
        return None, {
            "kind": "recording_content_missing",
            **({"channel": kind, "missing_fields": missing} if projection_version == 2 else {}),
            "event_ref": event_reference(requested),
            "detail": "Legacy hash-only evidence cannot reconstruct an exact external exchange."
            if projection_version == 1
            else "The committed exchange lacks content or hashes; it cannot supply an exact recorded response.",
        }
    if before["request_hash"] != after["request_hash"]:
        raise ValueError("response differs from its recorded request context")
    if episode_id_for_path(registration.logical_run_id, path) != requested.episode_id:
        raise ValueError("recording path differs from its Episode identity")
    if kind in HOST_EXCHANGE_CHANNELS and request != {
        "operation": before.get("operation"), "payload": before.get("payload")
    }:
        raise ValueError("recorded host request differs from its operation envelope")
    if (
        _REQUEST_HASH[kind](request) != before["request_hash"]
        or _RESPONSE_HASH[kind](response) != after["response_hash"]
    ):
        raise ValueError("recording content differs from its committed digest")
    return {
        "kind": kind,
        "episode_id": requested.episode_id.value,
        "episode_path": path,
        "request": request,
        "request_hash": before["request_hash"],
        "response": response,
        "response_hash": after["response_hash"],
        "request_event_ref": event_reference(requested),
        "response_event_ref": event_reference(responded),
        "request_sequence": requested.sequence,
        **({"response_sequence": responded.sequence} if projection_version == 2 else {}),
        **(
            {"session_state": after["session_state"]}
            if projection_version == 2 and "session_state" in after else {}
        ),
        "reused_from": after.get("reused_from"),
    }, None


def save_recording(
    artifacts, runs, run_id, *, episode_ids=None, through_event_ref=None
):
    """Persist a selector into the original journal, not a duplicate response log."""
    from ..records.experiments import put_data

    value = read_recording(
        runs, run_id, episode_ids=episode_ids, through_event_ref=through_event_ref
    )
    registration = runs.read_registration(OpaqueId(run_id))
    if artifacts.get_duet(registration.duet_id.value) is None:
        raise ValueError("recording requires its source Run's owning Duet")
    selector = {
        key: value[key]
        for key in (
            "recording_id",
            "registration_ref",
            "through_event_ref",
            "selected_episode_ids",
        )
    }
    selector["projection_version"] = value["schema_version"]
    if selector["through_event_ref"] is None:
        raise ValueError("an empty audit has no immutable recording boundary")
    return put_data(artifacts, registration.duet_id.value, "recording", selector)


def load_recording(artifacts, runs, reference, duet_id):
    from ..records.experiments import read_reference

    row = read_reference(artifacts, reference, duet_id)
    if row["kind"] != "experiment.recording.v1":
        raise ValueError("recording_ref must name a saved Run recording selector")
    selector = row["record"]
    fields = {
        "recording_id",
        "registration_ref",
        "through_event_ref",
        "selected_episode_ids",
    }
    if set(selector) not in (fields, fields | {"projection_version"}):
        raise ValueError("recording selector fields differ from the registered format")
    # Four-field selectors predate all-channel projection. Keep their exact
    # external-only identity; discovery labels the omitted host evidence.
    version = selector.get("projection_version", 1)
    registration = runs.read_registration(
        OpaqueId(selector["registration_ref"]["run_id"])
    )
    if (
        registration.duet_id.value != duet_id
        or registration.registration_hash.value
        != selector["registration_ref"]["content_hash"]
    ):
        raise ValueError("recording Run identity or owner differs from its reference")
    value = read_recording(
        runs,
        registration.run_id,
        episode_ids=selector["selected_episode_ids"] or None,
        through_event_ref=selector["through_event_ref"],
        projection_version=version,
    )
    if value["recording_id"] != selector["recording_id"]:
        raise ValueError("recording content differs from its saved exact boundary")
    return registration, value


def recording_summary(recording):
    """Default discovery excludes prompt text, response bodies and sibling traces."""
    return {
        key: recording[key]
        for key in (
            "recording_id",
            "registration_ref",
            "through_event_ref",
            "selected_episode_ids",
            "source_terminal_status",
            "terminal_evidence_available",
            "gaps",
        )
    } | {
        "projection_version": recording["schema_version"],
        "exchange_counts": {
            kind: sum(row["kind"] == kind for row in recording["exchanges"])
            for kind in ("model", "http", *HOST_EXCHANGE_CHANNELS)
        },
        "host_state_exchange_count": sum(
            row.get("session_state") is not None for row in recording["exchanges"]
        ),
        "unit_count": len(recording["units"]),
        "invocations": [
            {
                "episode_id": row["episode_id"],
                "episode_path": row["episode_path"],
                "boundary_available": all(
                    key in row
                    for key in (
                        "request",
                        "goal_view",
                        "goal_state_id",
                        "initial_goal_state_id",
                    )
                ),
            }
            for row in recording["invocations"]
        ],
        "learning_event_count": len(recording["learning"]),
        "components": [
            {
                "episode_id": row["episode_id"],
                "episode_path": row["episode_path"],
                "definition_id": row["execution_scope"]["binding"]["definition_id"],
                "binding_role": row["execution_scope"]["binding"]["role"],
                "status": row["component_result"]["status"],
                "event_ref": row["event_ref"],
            }
            for row in recording.get("components", ())
        ],
        "limitations": [
            "A recording is evidence, not permission to replay an experiment.",
            "Unit controller inputs alone are not a coherent nested checkpoint.",
            "Ordinary recorded execution reuses model/HTTP responses; host learning, refinement and experiment operations are not replayed from these records.",
            *(
                ["Legacy projection v1 omits host exchanges; reselect the original Run prefix for all-channel inspection."]
                if recording["schema_version"] == 1 else []
            ),
        ],
    }
