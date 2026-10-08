"""A physical model attempt that fails with a retryable transport error is replaced.

Observed on ANL Argo (2026-10-08): long streamed Refiner calls dropped mid-response
("peer closed connection without sending complete message body (incomplete chunked
read)"), classified retryable, yet the supervisor raised immediately because
ADR 0008 replacement covered only silent calls; the whole build stopped.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

import agent.model_call_recovery as recovery


def _route(mode="retry_on_healthy_probe", max_replacements=1):
    return {"recovery": {"mode": mode, "max_replacements": max_replacements, "recovery_grace_seconds": 0.01}}


def _run(route, outcomes):
    calls, records = [], []

    async def invoke(request, cancel, activity):
        calls.append(request)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def describe_failure(exc, request, activity):
        dropped = "chunked" in str(exc)
        status = getattr(exc, "status", None)
        return {"error_type": "APIError", "retryable": dropped or status == 503, "http_status": status,
                "failure_category": "timeout" if dropped else "server_error",
                "provider_error": {"type": "RemoteProtocolError" if dropped else type(exc).__name__}}

    async def main():
        return await recovery.supervise_model_call(
            route=route, request="req", cancel=threading.Event(), progress=lambda: None,
            record=records.append, invoke=invoke, describe_failure=describe_failure,
        )

    try:
        result = asyncio.run(main())
    except Exception as exc:  # surfaced to the caller as before
        result = exc
    return result, calls, [r["state"] for r in records], records


DROP = RuntimeError("peer closed connection without sending complete message body (incomplete chunked read)")


def test_dropped_stream_is_replaced_once_and_the_result_admitted() -> None:
    result, calls, states, records = _run(_route(), [DROP, "ok"])
    assert result == "ok" and len(calls) == 2
    assert states.count("physical_attempt_failed") == 1 and "physical_attempt_succeeded" in states
    proposed = [r for r in records if r["state"] == "recovery_replacement_proposed"]
    assert proposed and proposed[0]["basis"] == "retryable_transport_failure"


def test_replacement_budget_is_respected() -> None:
    result, calls, _, _ = _run(_route(max_replacements=1), [DROP, DROP, "never"])
    assert isinstance(result, RuntimeError) and len(calls) == 2


@pytest.mark.parametrize("mode", ["preserve", "disabled"])
def test_other_modes_keep_failing(mode) -> None:
    result, calls, _, _ = _run(_route(mode=mode), [DROP, "never"])
    assert isinstance(result, RuntimeError) and len(calls) == 1


def test_non_retryable_failures_are_not_replaced() -> None:
    result, calls, _, _ = _run(_route(), [ValueError("400 bad request"), "never"])
    assert isinstance(result, ValueError) and len(calls) == 1


class Overloaded(RuntimeError):
    status = 503


def test_provider_error_responses_are_not_retried() -> None:
    # A provider verdict (HTTP 503 "overloaded") stays a single-attempt failure,
    # as test_episode_model_failure_reporting requires.
    result, calls, _, _ = _run(_route(), [Overloaded("Server overloaded"), "never"])
    assert isinstance(result, Overloaded) and len(calls) == 1


def test_routes_without_a_recovery_record_keep_legacy_behaviour() -> None:
    result, calls, _, _ = _run({}, [DROP, "never"])
    assert isinstance(result, RuntimeError) and len(calls) == 1
