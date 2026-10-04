"""Match an interrupted worker's whole history using the shared Run journal.

Unlike recorded-response experiments, reconstruction preserves every logical
identity and checks ordering across children and host channels. This verifier
has no brokers, write access or live fallback. Exhaustion is a boundary to be
admitted by the host, never permission to perform the next action.
"""

from dataclasses import dataclass

from agent.duet_contracts import canonical_json, digest_record
from agent.episode_contracts import OpaqueId

from ..contracts import RunEventKind, RunEventOrigin, _freeze_json, _thaw_json
from .recordings import _REQUESTS, event_reference, read_recording


_BOUNDARIES = {
    RunEventKind.EPISODE_STARTED,
    RunEventKind.UNIT_COMPLETED,
    RunEventKind.EPISODE_COMPLETED,
}
_INTERRUPTIONS = {"interrupted", "cancelled", "resource_limited"}


class ReconstructionError(ValueError):
    """The saved execution cannot be reconstructed without changing its meaning."""


class ReconstructionBoundaryReached(ReconstructionError):
    """All saved frames matched; separate host admission is still required."""


@dataclass(frozen=True)
class RecordedReply:
    frame_type: str
    body: object
    event_ref: object


@dataclass(frozen=True)
class _ExpectedFrame:
    frame_type: str
    body: object
    event_ref: object
    reply: RecordedReply | None


def _worker_frame(event, exchanges):
    payload = _thaw_json(event.payload)
    if event.kind in _BOUNDARIES:
        return _ExpectedFrame(
            "run_event",
            _freeze_json({
                "episode_id": event.episode_id.value,
                "event_kind": event.kind.value,
                "payload": payload,
            }, "reconstructed event"),
            _freeze_json(event_reference(event), "event reference"), None,
        )
    channel, request_key = _REQUESTS[event.kind]
    exchange = exchanges.get(event.event_id.value)
    if exchange is None:
        from ..broker import admit_model_request, model_request_hash

        if event.kind in {RunEventKind.REFINEMENT_REQUESTED, RunEventKind.LEARNING_REQUESTED, RunEventKind.EXPERIMENT_REQUESTED}:
            if digest_record(payload["request"]).value != payload["request_hash"]:
                raise ReconstructionError("pending host request differs from its committed hash")
            return _ExpectedFrame(
                channel + "_request", _freeze_json({
                    "episode_id": event.episode_id.value,
                    "episode_path": payload["episode_path"],
                    request_key: payload[request_key], **payload["request"],
                }, "pending host request"),
                _freeze_json(event_reference(event), "event reference"), None,
            )
        if event.kind is not RunEventKind.MODEL_REQUESTED:
            raise ReconstructionError("an unanswered side-effecting operation requires receipt reconciliation")
        request = admit_model_request(payload["request"])
        if model_request_hash(request).value != payload["request_hash"]:
            raise ReconstructionError("pending model request differs from its committed hash")
        return _ExpectedFrame(
            "model_request",
            _freeze_json({
                "episode_id": event.episode_id.value,
                "episode_path": payload["episode_path"],
                request_key: payload[request_key],
                "request": payload["request"],
            }, "pending model request"),
            _freeze_json(event_reference(event), "event reference"), None,
        )
    body = {
        "episode_id": event.episode_id.value,
        "episode_path": exchange["episode_path"],
        request_key: payload[request_key],
    }
    if channel in {"model", "http"}:
        body["request"] = exchange["request"]
    else:
        body.update(exchange["request"])
    reply = RecordedReply(
        channel + "_response",
        _freeze_json({request_key: payload[request_key], "response": exchange["response"]}, "recorded reply"),
        _freeze_json(exchange["response_event_ref"], "response reference"),
    )
    return _ExpectedFrame(
        channel + "_request", _freeze_json(body, "reconstructed request"),
        _freeze_json(event_reference(event), "event reference"), reply,
    )


def _active_stack(events, run_id, entry_path=None):
    from ..protocol import episode_id_for_path

    stack, seen, returning = [], set(), None
    for event in events:
        if event.kind is RunEventKind.EPISODE_STARTED:
            path = _thaw_json(event.payload.get("episode_path"))
            if (
                episode_id_for_path(run_id, path) != event.episode_id
                or event.episode_id.value in seen
                or (stack and path[:-1] != stack[-1]["episode_path"])
                or (not stack and (seen or (
                    path != entry_path if entry_path is not None else len(path) != 1
                )))
            ):
                raise ReconstructionError("recording does not contain one serial nested Episode stack")
            required = {"request", "goal_view", "goal_state_id", "initial_goal_state_id"}
            if not required <= set(event.payload):
                raise ReconstructionError("Episode start lacks its saved request or goal-state boundary")
            seen.add(event.episode_id.value)
            stack.append({"episode_id": event.episode_id.value, "episode_path": path})
            returning = None
        elif event.kind in {RunEventKind.UNIT_COMPLETED, RunEventKind.EPISODE_COMPLETED}:
            if not stack or stack[-1]["episode_id"] != event.episode_id.value:
                raise ReconstructionError("worker boundary differs from the active nested Episode")
            if event.kind is RunEventKind.EPISODE_COMPLETED:
                returning = stack.pop()
            else:
                returning = None
        elif event.kind in _REQUESTS:
            if episode_id_for_path(run_id, _thaw_json(event.payload.get("episode_path"))) != event.episode_id:
                raise ReconstructionError("recorded request path differs from its logical Episode identity")
            # build_result runs after Context.leave(), with the just-completed
            # child's identity. Its typed return can still require a host call.
            active = stack and stack[-1]["episode_id"] == event.episode_id.value
            result = returning and returning["episode_id"] == event.episode_id.value
            if not (active or result):
                raise ReconstructionError("recorded request is not from the active nested Episode")
            if active:
                returning = None
    if not stack and returning is None:
        raise ReconstructionError("recording has no interrupted active Episode")
    return stack


class ReconstructionCursor:
    """A read-only verifier, not a continuation authorization or another journal."""

    def __init__(self, runs, run_id, *, artifacts=None):
        from ..continuation import execution_lineage

        run_id = OpaqueId(run_id) if isinstance(run_id, str) else run_id
        registration = runs.read_registration(run_id)
        recordings, events, semantic = [], [], []
        pending = None
        receipts = []
        for attempt in execution_lineage(runs, registration):
            recording = read_recording(runs, attempt.run_id)
            if not recording["terminal_evidence_available"] or recording["source_terminal_status"] not in _INTERRUPTIONS:
                raise ReconstructionError("reconstruction requires terminal interruption evidence")
            attempt_events = runs.read_audit_log(attempt.run_id)
            fresh = [event for event in attempt_events if event.kind in _BOUNDARIES or event.kind in _REQUESTS]
            gaps = recording["gaps"]
            trailing = None
            if gaps:
                if (
                    len(gaps) != 1 or not fresh
                    or gaps[0]["kind"] != "response_not_committed"
                    or gaps[0].get("channel") not in {"model", "refinement", "learning", "experiment"}
                    or fresh[-1].kind not in _REQUESTS
                    or gaps[0]["event_ref"] != event_reference(fresh[-1])
                ):
                    raise ReconstructionError("unfinished external operations need durable receipt reconciliation")
                trailing = fresh[-1]
                if trailing.kind is RunEventKind.REFINEMENT_REQUESTED and artifacts is not None:
                    from ..records.host_operations import read_receipt

                    receipt = read_receipt(artifacts, attempt, trailing)
                    if receipt is not None:
                        before = _thaw_json(trailing.payload)
                        recording["exchanges"].append({
                            "kind": "refinement", "episode_path": before["episode_path"],
                            "request": before["request"], "response": receipt["response"],
                            "request_event_ref": event_reference(trailing),
                            "response_event_ref": {"run_id": attempt.run_id.value, **receipt["receipt_ref"]},
                            "response_sequence": trailing.sequence,
                            "session_state": receipt["session_state"],
                        })
                        receipts.append(receipt["receipt_ref"])
                        trailing = None
            if attempt.resume_from is not None:
                activation = [event for event in attempt_events if event.kind is RunEventKind.RUN_RECONSTRUCTED]
                if len(activation) > 1 or (fresh and (
                    not activation or activation[0].origin is not RunEventOrigin.HOST_RECONSTRUCTION
                    or activation[0].sequence >= fresh[0].sequence
                    or activation[0].payload.get("resume_from") != attempt.resume_from.as_record()
                )):
                    raise ReconstructionError("continued execution lacks its prior host reconstruction admission")
                if pending is not None and fresh:
                    if (
                        activation[0].payload.get("reconstruction", {}).get(
                            "pending_model_request_ref" if pending.kind is RunEventKind.MODEL_REQUESTED else "pending_host_request_ref"
                        ) != event_reference(pending)
                        or canonical_json(_worker_frame(pending, {}).body)
                        != canonical_json(_worker_frame(fresh[0], {}).body)
                    ):
                        raise ReconstructionError("continued model request differs from the interrupted request")
                    semantic.pop()
                    pending = None
            recordings.append(recording)
            events.extend(attempt_events)
            semantic.extend(fresh)
            if trailing is not None:
                pending = trailing
        semantic = tuple(semantic)
        if any(event.origin is not RunEventOrigin.WORKER for event in semantic):
            raise ReconstructionError("worker history contains an invalid event origin")
        if any(event.kind is RunEventKind.COMPONENT_OBSERVED for event in events):
            raise ReconstructionError("component-only execution is not a resumable nested Episode")
        exchanges = {row["request_event_ref"]["event_id"]: row for recording in recordings for row in recording["exchanges"]}
        # Serial reconstruction cannot publish a response before another worker
        # action that originally preceded it. Do not silently serialize concurrency.
        for current, following in zip(semantic, semantic[1:]):
            exchange = exchanges.get(current.event_id.value)
            if exchange is not None and current.run_id == following.run_id and exchange["response_sequence"] > following.sequence:
                raise ReconstructionError("overlapping exchanges require a different reconstruction contract")
        self._frames = tuple(_worker_frame(event, exchanges) for event in semantic)
        entry_path = None if registration.execution_scope is None else [
            {"grain": grain, "key": key}
            for grain, key in registration.execution_scope.entry_path(registration.logical_run_id.value)
        ]
        self._stack = _freeze_json(
            _active_stack(semantic, registration.logical_run_id, entry_path) if semantic else [],
            "active stack",
        )
        self._registration_ref = _freeze_json(recordings[-1]["registration_ref"], "registration reference")
        self._boundary_ref = _freeze_json(recordings[-1]["through_event_ref"], "recording boundary")
        self._recording_id = recordings[-1]["recording_id"]
        self._lineage = tuple(recording["registration_ref"] for recording in recordings)
        self._position = 0
        self._divergence = None
        self._pending_ref = None if pending is None else event_reference(pending)
        self._pending_kind = None if pending is None else pending.kind
        self._receipts = receipts
        states = [row for recording in recordings for row in recording["exchanges"] if row["kind"] == "refinement"]
        self._host_unstarted = not states and not any(
            event.kind is RunEventKind.REFINEMENT_REQUESTED for event in semantic
        )
        self._host_state = None if not states else _freeze_json({
            "event_ref": states[-1]["response_event_ref"],
            "state": states[-1].get("session_state"),
        }, "host continuation state")
        if pending is not None and pending.kind is RunEventKind.REFINEMENT_REQUESTED:
            before = pending.payload.get("session_state_before")
            if before is not None:
                self._host_state = _freeze_json({
                    "event_ref": event_reference(pending), "state": before,
                }, "host continuation state")

    @property
    def host_state(self):
        """Provenance-bound host metadata, never included in a worker reply."""
        return _thaw_json(self._host_state)

    @property
    def host_unstarted(self):
        return self._host_unstarted

    @property
    def prefix_verified(self):
        return self._divergence is None and self._position == len(self._frames)

    @property
    def retry_pending_request(self):
        return self.prefix_verified and self._pending_ref is not None

    def accept(self, frame):
        if self._divergence is not None:
            raise ReconstructionError(canonical_json(self._divergence))
        if self.prefix_verified:
            raise ReconstructionBoundaryReached("saved prefix matched; live work has not been authorized")
        expected = self._frames[self._position]
        if frame.frame_type != expected.frame_type or canonical_json(frame.body) != canonical_json(expected.body):
            self._divergence = {
                "kind": "reconstruction_diverged",
                "expected_event_ref": expected.event_ref,
                "expected_frame_type": expected.frame_type,
                "observed_frame_type": frame.frame_type,
                "expected_body_hash": digest_record(expected.body).value,
                "observed_body_hash": digest_record(frame.body).value,
            }
            raise ReconstructionError(canonical_json(self._divergence))
        self._position += 1
        return expected.reply

    def report(self):
        return {
            "recording_id": self._recording_id,
            "registration_ref": _thaw_json(self._registration_ref),
            "through_event_ref": _thaw_json(self._boundary_ref),
            "execution_lineage": list(self._lineage),
            "matched_worker_frames": self._position,
            "remaining_worker_frames": len(self._frames) - self._position,
            "expected_active_stack": _thaw_json(self._stack),
            "status": "diverged" if self._divergence else ("prefix_verified" if self.prefix_verified else "reconstructing"),
            "divergence": _thaw_json(self._divergence),
            "live_work_authorized": False,
            "pending_model_request_ref": self._pending_ref if self._pending_kind is RunEventKind.MODEL_REQUESTED else None,
            "pending_host_request_ref": self._pending_ref if self._pending_kind is not RunEventKind.MODEL_REQUESTED else None,
            "host_operation_receipts": self._receipts,
        }
