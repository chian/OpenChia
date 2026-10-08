"""Observe a pinned model call and recover only under its frozen source policy.

A probe answers whether another request completed. It does not reveal the
original request's queue position, server-side state, or cancellation outcome.
Only the selected primary attempt may return text to the Episode broker.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import replace
from datetime import datetime, timezone
import threading
import time
import uuid

from agent.model_call_recovery_policy import frozen_recovery_policy


class ModelCallRecoveryExhausted(RuntimeError):
    """Operational recovery ended without an Episode result."""


#: A silent call records ``call_waiting`` at this interval, so the ledger (and
#: ``/build status``) can tell "still waiting" from "supervisor stopped" (#77).
WAITING_HEARTBEAT_SECONDS = 120.0
#: Consecutive health probes that fail to *connect* before the provider is
#: declared unreachable and the logical call ends (#77).
UNREACHABLE_PROBE_LIMIT = 3
#: Probe phases that mean the provider never answered at all (no response headers).
_NO_RESPONSE_PHASES = frozenset({"dispatching", "request_dispatched"})


class CallActivity:
    """Content-free observations shared with the attempt's provider thread."""

    def __init__(self, progress):
        self._lock = threading.Lock()
        self._progress = progress
        self._revision = 0
        self._last = time.monotonic()
        self._phase = "dispatching"
        self._at = datetime.now(timezone.utc).isoformat()
        self._request_id = None
        self.provider_finished = threading.Event()

    def observe(self, phase, *, request_id=None):
        with self._lock:
            self._revision += 1
            self._last = time.monotonic()
            self._phase = phase
            self._at = datetime.now(timezone.utc).isoformat()
            if request_id:
                self._request_id = str(request_id)[:200]

    def progress(self):
        self.observe("receiving_model_events")
        self._progress()

    def snapshot(self):
        with self._lock:
            return {
                "revision": self._revision,
                "last_activity_monotonic": self._last,
                "last_activity_at": self._at,
                "phase": self._phase,
                "provider_request_id": self._request_id,
            }

    def cancel_if_unchanged(self, revision, cancel):
        """Linearize abandonment against activity from the provider thread."""
        with self._lock:
            if self._revision != revision:
                return False
            cancel.set()
            return True


class _Attempt:
    def __init__(self, invoke, request, progress):
        self.request = request
        self.cancel = threading.Event()
        self.activity = CallActivity(progress)
        self.task = asyncio.create_task(invoke(request, self.cancel, self.activity))

    async def close(self):
        self.cancel.set()
        # The provider helper polls the event and closes its attempt-owned
        # client. Do not wait indefinitely on an SDK's connection cleanup.
        done, _ = await asyncio.wait({self.task}, timeout=5.0)
        if not done:
            self.task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await self.task
        return {
            "client_task_finished": bool(done),
            "provider_thread_finished": self.activity.provider_finished.is_set(),
        }


_DROPPED_TRANSPORT_TYPES = frozenset({
    "RemoteProtocolError", "ReadError", "WriteError", "ConnectError", "ReadTimeout",
    "APIConnectionError",
})


def _dropped_transport(failure):
    """The connection failed with no provider response status or error verdict."""
    if not failure.get("retryable") or failure.get("http_status") is not None:
        return False
    provider = failure.get("provider_error") or {}
    return (provider.get("type") in _DROPPED_TRANSPORT_TYPES
            or failure.get("error_type") in _DROPPED_TRANSPORT_TYPES)


class _CallSupervisor:
    def __init__(self, route, request, cancel, progress, record, invoke, describe_failure):
        self.route = route
        self.request = request
        self.cancel = cancel
        self.progress = progress
        self.record = record
        self.invoke = invoke
        self.describe_failure = describe_failure
        self.policy = frozen_recovery_policy(route)
        self.started = time.monotonic()
        self.primary = None
        self.probe = None
        self.retired_probe = None
        self.probe_id = None
        self.probe_started = 0.0
        self.probe_revision = None
        self.grace_deadline = None
        self.probe_round = 0
        self.physical_attempt = 0
        self.last_reported = 0.0
        self.reported_revision = -1
        self.next_probe_at = 0.0
        self.last_heartbeat = time.monotonic()
        self.unreachable_probes = 0

    def emit(self, state, **details):
        self.record({
            "state": state,
            "physical_attempt": self.physical_attempt,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": time.monotonic() - self.started,
            **details,
        })

    def start_primary(self):
        self.physical_attempt += 1
        self.primary = _Attempt(self.invoke, self.request, self.progress)
        self.grace_deadline = None
        self.probe_revision = None
        self.probe_round = 0
        self.next_probe_at = time.monotonic() + self.policy.idle_seconds
        self.reported_revision = -1
        self.emit("physical_attempt_started", recovery_policy=self.policy.to_dict())

    def activity_record(self):
        snapshot = self.primary.activity.snapshot()
        idle = time.monotonic() - snapshot.pop("last_activity_monotonic")
        return {**snapshot, "idle_seconds": idle}

    def start_probe(self, snapshot):
        self.probe_id = uuid.uuid4().hex
        self.probe_revision = snapshot["revision"]
        self.probe_started = time.monotonic()
        self.probe_round += 1
        request = replace(
            self.request,
            task="model_source_health_probe",
            messages=({"role": "user", "content": "Reply with exactly OK."},),
            temperature=None,
            max_tokens=16,
            timeout=self.policy.probe_timeout_seconds,
            main_runtime=None,
            call_role="health_probe",
        )
        self.probe = _Attempt(self.invoke, request, lambda: None)
        self.emit(
            "probe_started", probe_id=self.probe_id, original_activity=snapshot,
            probe_timeout_seconds=self.policy.probe_timeout_seconds,
            probe_max_tokens=request.max_tokens,
            scope="same_provider_endpoint_model_and_credential",
            original_server_state="unknown",
        )

    async def close_probe(self, reason):
        if self.probe is None:
            return
        closed = await self.probe.close()
        if not closed["provider_thread_finished"]:
            self.retired_probe = self.probe
        self.probe = None
        self.emit("probe_cancelled", probe_id=self.probe_id, reason=reason, **closed)

    async def inspect_probe(self, snapshot):
        if snapshot["revision"] != self.probe_revision:
            await self.close_probe("original_activity_resumed")
            self.grace_deadline = None
            self.probe_revision = None
            self.next_probe_at = time.monotonic() + self.policy.idle_seconds
            self.probe_round = 0
            self.emit("original_preserved", reason="original_activity_resumed", original_activity=snapshot)
            return
        if self.probe is None:
            return
        if not self.probe.task.done():
            if time.monotonic() - self.probe_started >= self.policy.probe_timeout_seconds:
                await self.close_probe("probe_deadline")
                self.probe_revision = None
                self.emit("original_preserved", reason="probe_outcome_unknown")
                self.schedule_probe()
            return
        try:
            text, actual_model = self.probe.task.result()
        except asyncio.CancelledError:
            self.emit("probe_cancelled", probe_id=self.probe_id, reason="provider_attempt_cancelled")
            healthy = False
        except Exception as exc:
            failure = self.describe_failure(exc, self.probe.request, self.probe.activity)
            self.emit("probe_failed", probe_id=self.probe_id, **failure)
            healthy = False
            # A probe asks for 16 tokens. Failing to connect, or timing out before
            # any response headers arrived, means the provider did not answer at
            # all; a slow provider still sends headers (#77: dropped VPN, every
            # probe "Request timed out." in phase request_dispatched).
            phase = self.probe.activity.snapshot()["phase"]
            no_answer = _dropped_transport(failure) or (
                failure.get("failure_category") == "timeout" and phase in _NO_RESPONSE_PHASES
            )
            if no_answer:
                self.unreachable_probes += 1
                if self.unreachable_probes >= UNREACHABLE_PROBE_LIMIT:
                    self.emit("provider_unreachable", probe_id=self.probe_id,
                              consecutive_failed_probes=self.unreachable_probes,
                              probe_phase=phase, original_activity=self.activity_record())
                    raise ModelCallRecoveryExhausted(
                        "Model provider unreachable: "
                        f"{self.unreachable_probes} consecutive health probes got no response; "
                        "no result was admitted"
                    )
            else:
                self.unreachable_probes = 0
        else:
            healthy = bool(text.strip())
            self.unreachable_probes = 0
            self.emit(
                "probe_succeeded", probe_id=self.probe_id,
                response_model=actual_model, response_nonempty=healthy,
                probe_elapsed_seconds=time.monotonic() - self.probe_started,
                original_server_state="unknown",
            )
        self.probe = None
        if healthy and self.policy.mode == "retry_on_healthy_probe":
            self.grace_deadline = time.monotonic() + self.policy.recovery_grace_seconds
            self.emit(
                "recovery_grace_started", probe_id=self.probe_id,
                grace_seconds=self.policy.recovery_grace_seconds,
                basis="healthy_side_call_with_original_still_silent",
                duplicate_server_work_possible=True,
            )
        else:
            self.probe_revision = None
            self.emit("original_preserved", reason="source_policy" if healthy else "probe_not_healthy")
            self.schedule_probe()

    def schedule_probe(self):
        # Repeated inconclusive/observational probes provide diminishing
        # information; space them out rather than hammering a queued server.
        self.next_probe_at = time.monotonic() + self.policy.probe_interval_seconds * min(2 ** min(self.probe_round - 1, 4), 16)

    async def replace_failed_primary(self, failure):
        """Resubmit after the transport dropped a physical attempt mid-response.

        A stream the connection lost ("incomplete chunked read", connection
        reset) produced no result and no provider verdict, so there is nothing
        to preserve; under ``retry_on_healthy_probe`` it uses the same bounded
        ``max_replacements`` budget as a silent-call replacement. Provider error
        responses (any HTTP status, or an error event in the stream) still fail
        the call without a retry, as do other modes and an exhausted budget.
        """
        if (
            self.policy.mode != "retry_on_healthy_probe"
            or not _dropped_transport(failure)
            or self.physical_attempt > self.policy.max_replacements
            or self.cancel.is_set()
        ):
            return False
        self.emit(
            "recovery_replacement_proposed", probe_id=None,
            original_server_state="failed", basis="retryable_transport_failure",
            failure_category=failure.get("failure_category"),
            duplicate_server_work_possible=True,
        )
        await self.primary.close()
        await asyncio.sleep(min(self.policy.recovery_grace_seconds, 5.0 * self.physical_attempt))
        if self.cancel.is_set():
            raise asyncio.CancelledError
        self.start_primary()
        return True

    async def replace_primary(self, snapshot):
        self.emit(
            "recovery_replacement_proposed", probe_id=self.probe_id,
            original_activity=snapshot, original_server_state="unknown",
            basis="healthy_side_call_and_no_activity_through_grace",
            duplicate_server_work_possible=True,
        )
        # Durable receipt publication can block. Prefer an original response
        # or renewed activity that arrived while that receipt was written.
        await asyncio.sleep(0)
        if self.primary.task.done() or not self.primary.activity.cancel_if_unchanged(snapshot["revision"], self.primary.cancel):
            self.grace_deadline = None
            self.probe_revision = None
            self.next_probe_at = time.monotonic() + self.policy.idle_seconds
            return
        if self.physical_attempt > self.policy.max_replacements:
            self.emit("recovery_exhausted", original_activity=snapshot, original_server_state="unknown")
            raise ModelCallRecoveryExhausted("Model recovery replacement limit reached; no result was admitted")
        finished = await self.primary.close()
        self.emit("physical_attempt_abandoned", **finished, server_cancellation_confirmed=False)
        if self.cancel.is_set():
            raise asyncio.CancelledError
        self.start_primary()

    async def run(self):
        if self.cancel.is_set():
            raise asyncio.CancelledError
        try:
            self.start_primary()
            while True:
                if self.cancel.is_set():
                    raise asyncio.CancelledError
                if self.primary.task.done():
                    try:
                        result = self.primary.task.result()
                    except Exception as exc:
                        failure = self.describe_failure(exc, self.primary.request, self.primary.activity)
                        self.emit("physical_attempt_failed", **failure)
                        if not await self.replace_failed_primary(failure):
                            raise
                        continue
                    self.emit("physical_attempt_succeeded")
                    return result
                snapshot = self.activity_record()
                now = time.monotonic()
                if snapshot["revision"] != self.reported_revision and now - self.last_reported >= 30:
                    self.emit("call_activity", **snapshot)
                    self.reported_revision = snapshot["revision"]
                    self.last_reported = now
                    self.last_heartbeat = now
                elif now - self.last_heartbeat >= WAITING_HEARTBEAT_SECONDS:
                    self.emit("call_waiting", **snapshot,
                              probe_active=self.probe is not None,
                              next_probe_in_seconds=max(0.0, self.next_probe_at - now))
                    self.last_heartbeat = now
                if self.probe_revision is not None:
                    await self.inspect_probe(snapshot)
                if self.grace_deadline is not None and time.monotonic() >= self.grace_deadline:
                    # Re-read after awaits: activity during cleanup or receipt
                    # persistence must still prevent abandonment.
                    current = self.activity_record()
                    if current["revision"] == self.probe_revision and not self.primary.task.done():
                        await self.replace_primary(current)
                elif self.can_probe(now, snapshot):
                    self.start_probe(snapshot)
                pending = {self.primary.task}
                if self.probe is not None:
                    pending.add(self.probe.task)
                await asyncio.wait(pending, timeout=0.5, return_when=asyncio.FIRST_COMPLETED)
        finally:
            try:
                await self.close_probe("logical_call_ended")
            finally:
                if self.primary is not None:
                    await self.primary.close()

    def can_probe(self, now, snapshot):
        if self.retired_probe is not None:
            if not self.retired_probe.activity.provider_finished.is_set():
                return False
            self.retired_probe = None
        return (
            self.policy.mode != "disabled"
            and self.probe is None
            and self.grace_deadline is None
            and now >= self.next_probe_at
            and snapshot["idle_seconds"] >= self.policy.idle_seconds
        )


async def supervise_model_call(*, route, request, cancel, progress, record, invoke, describe_failure):
    """One logical call, bounded replacement attempts, and one accepted result."""
    return await _CallSupervisor(route, request, cancel, progress, record, invoke, describe_failure).run()
