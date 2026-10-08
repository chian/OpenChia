"""Model-call liveness (#77): keepalive, waiting heartbeat, unreachable provider, status.

Observed 2026-10-08: the host left the ANL VPN mid-request. The provider socket
became half-open, the client had no read timeout, every health probe timed out
before any response, ADR 0008 preserved the original indefinitely, and
``/build status`` showed ``model_wait: null`` for the refining build.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from datetime import datetime, timedelta, timezone

import agent.model_call_recovery as recovery
from agent.model_call_status import model_wait_from_events
from agent.provider_http import CONNECT_TIMEOUT_SECONDS, keepalive_socket_options, provider_http_client


# ---------------------------------------------------------------- transport


def test_keepalive_options_enable_and_tune_tcp_keepalive() -> None:
    options = keepalive_socket_options()
    assert (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1) in options
    assert any(level == socket.IPPROTO_TCP for level, _, _ in options)


def test_provider_client_bounds_connect_but_not_reads() -> None:
    client = provider_http_client(trust_env=False)
    try:
        assert client.timeout.connect == CONNECT_TIMEOUT_SECONDS
        assert client.timeout.read is None  # long silent generations stay legal
    finally:
        client.close()


# ---------------------------------------------------------------- supervisor


def _route():
    return {"recovery": {
        "mode": "retry_on_healthy_probe", "idle_seconds": 0.05, "probe_timeout_seconds": 0.05,
        "probe_interval_seconds": 0.01, "recovery_grace_seconds": 0.05, "max_replacements": 1,
    }}


def _supervise(invoke, describe_failure, records, *, timeout=10.0):
    async def main():
        return await asyncio.wait_for(recovery.supervise_model_call(
            route=_route(), request=_Request(), cancel=threading.Event(), progress=lambda: None,
            record=records.append, invoke=invoke, describe_failure=describe_failure,
        ), timeout)

    try:
        return asyncio.run(main())
    except Exception as exc:
        return exc


class _Request:
    """Minimal stand-in accepted by dataclasses.replace in start_probe."""

    def __init__(self, **values):
        self.__dict__.update(values)


def _patch_replace(monkeypatch):
    monkeypatch.setattr(recovery, "replace", lambda request, **changes: _Request(**{**request.__dict__, **changes}))


def test_unanswered_probes_end_the_call_as_provider_unreachable(monkeypatch) -> None:
    _patch_replace(monkeypatch)
    records = []

    async def invoke(request, cancel, activity):
        activity.observe("request_dispatched")
        if getattr(request, "call_role", None) == "health_probe":
            raise TimeoutError("Request timed out.")
        while not cancel.is_set():  # the original: silent forever on a dead connection
            await asyncio.sleep(0.01)
        raise asyncio.CancelledError

    def describe_failure(exc, request, activity):
        return {"error_type": "APITimeoutError", "failure_category": "timeout", "retryable": True,
                "http_status": None, "provider_error": {"type": None}}

    result = _supervise(invoke, describe_failure, records)
    assert isinstance(result, recovery.ModelCallRecoveryExhausted)
    assert "unreachable" in str(result)
    states = [r["state"] for r in records]
    assert states.count("probe_failed") == recovery.UNREACHABLE_PROBE_LIMIT
    assert "provider_unreachable" in states


def test_probe_that_got_headers_does_not_count_as_unreachable(monkeypatch) -> None:
    # A slow provider that answers headers but times out is not "unreachable".
    _patch_replace(monkeypatch)
    records, probes = [], []

    async def invoke(request, cancel, activity):
        if getattr(request, "call_role", None) == "health_probe":
            probes.append(1)
            activity.observe("response_headers_received")
            raise TimeoutError("Request timed out.")
        if len(probes) >= 4:
            return ("done", "m")
        while not cancel.is_set() and len(probes) < 4:
            await asyncio.sleep(0.01)
        return ("done", "m")

    def describe_failure(exc, request, activity):
        return {"failure_category": "timeout", "retryable": True, "http_status": None,
                "provider_error": {"type": None}}

    result = _supervise(invoke, describe_failure, records)
    assert result == ("done", "m")
    assert "provider_unreachable" not in [r["state"] for r in records]


def test_silent_call_records_waiting_heartbeats(monkeypatch) -> None:
    monkeypatch.setattr(recovery, "WAITING_HEARTBEAT_SECONDS", 0.05)
    records = []

    async def invoke(request, cancel, activity):
        await asyncio.sleep(1.6)  # the supervisor loop ticks every 0.5 s
        return ("ok", "m")

    async def main():
        return await recovery.supervise_model_call(
            route={"recovery": {"mode": "preserve", "idle_seconds": 100.0}}, request=_Request(),
            cancel=threading.Event(), progress=lambda: None, record=records.append,
            invoke=invoke, describe_failure=lambda *a: {},
        )

    result = asyncio.run(main())
    assert result == ("ok", "m")
    waiting = [r for r in records if r["state"] == "call_waiting"]
    assert waiting and all("idle_seconds" in r and "phase" in r for r in waiting)


# ---------------------------------------------------------------- status


def _event(state, *, call="c1", at, **extra):
    return {"event_type": "model_launch_call", "record": {
        "call_id": call, "state": state, "recorded_at": at.isoformat(),
        "task": "episode_structured_json_reasoning", "episode_local_id": "launch",
        "base_url": "https://gw.test/v1", **extra}}


def test_status_reports_a_long_silent_refiner_call() -> None:
    t0 = datetime(2026, 10, 8, 19, 45, 5, tzinfo=timezone.utc)
    events = [
        _event("started", at=t0),
        _event("physical_attempt_started", at=t0, physical_attempt=1),
        _event("call_activity", at=t0 + timedelta(seconds=30), physical_attempt=1,
               idle_seconds=30.0, phase="request_dispatched"),
    ]
    wait = model_wait_from_events(events, now=t0 + timedelta(hours=1))
    assert wait["active"] and wait["episode"] == "launch" and wait["phase"] == "request_dispatched"
    assert 3599 <= wait["idle_seconds"] <= 3601 and wait["elapsed_seconds"] == int(wait["idle_seconds"])
    assert wait["response_seen"] is False and wait["endpoint"] == "https://gw.test/v1"


def test_status_follows_the_newest_call_and_marks_finished_calls_inactive() -> None:
    t0 = datetime(2026, 10, 8, 19, 0, 0, tzinfo=timezone.utc)
    events = [
        _event("started", call="old", at=t0),
        _event("succeeded", call="old", at=t0 + timedelta(seconds=5)),
        _event("started", call="new", at=t0 + timedelta(seconds=6)),
        _event("succeeded", call="new", at=t0 + timedelta(seconds=9)),
    ]
    wait = model_wait_from_events(events, now=t0 + timedelta(seconds=20))
    assert wait["state"] == "succeeded" and wait["active"] is False and wait["idle_seconds"] is None


def test_duet_store_reads_one_event_type_across_duets(tmp_path) -> None:
    from agent.duet_store import DuetStore

    with DuetStore(tmp_path / "authority.sqlite3") as store:
        for duet in ("owner", "refiner"):
            store.create_duet(duet_id=duet, identity={}, policy={}, state="designing")
        store.append_event(duet_id="owner", event_type="build_requested", provenance="host", record={})
        store.append_event(duet_id="refiner", event_type="model_launch_call", provenance="host",
                           record={"call_id": "x", "owner_duet_id": "owner", "state": "started"})
        calls = store.events_of_type("model_launch_call")
        assert [c["duet_id"] for c in calls] == ["refiner"]
        assert json.loads(json.dumps(calls[0]["record"]))["owner_duet_id"] == "owner"
