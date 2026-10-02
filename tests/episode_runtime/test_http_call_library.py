"""The staged worker-side HTTP library: scope, call shapes, and definitions."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from function_library import LibraryFunction
from http_call_library import (
    HTTP_JSON,
    HTTP_REQUEST,
    HttpFailure,
    HttpFailureKind,
    HttpJsonResult,
    HttpResult,
    HttpTransport,
    HttpTransportRequest,
    HttpTransportResponse,
    HttpTransportUnavailable,
    call_http_transport,
    http_json,
    http_request,
    http_transport_scope,
)
from episode_runtime.http_contracts import http_request_record, http_response_record


URL = "https://www.bv-brc.org/ragstack/asm-next/api/v1/query"


def _response(**overrides) -> HttpTransportResponse:
    values = {
        "outcome": "ok",
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": '{"hits": [1, 2]}',
        "body_encoding": "utf-8",
        "reason": None,
        "rule": "ragstack_query",
    }
    values.update(overrides)
    return HttpTransportResponse(**values)


class _FakeTransport:
    """Admits like the worker transport, then answers with a fixed response."""

    def __init__(self, response=None, error=None):
        self.response = response if response is not None else _response()
        self.error = error
        self.requests: list[dict[str, object]] = []

    async def __call__(self, request: HttpTransportRequest) -> HttpTransportResponse:
        self.requests.append(http_request_record(request))
        if self.error is not None:
            raise self.error
        # The response crosses the same admission the worker applies.
        http_response_record(self.response)
        return self.response


def _run(coroutine_factory, transport):
    async def scenario():
        with http_transport_scope(transport):
            return await coroutine_factory()

    return asyncio.run(scenario())


def test_call_without_a_scope_raises_unavailable_and_never_falls_back():
    request = HttpTransportRequest(method="GET", url=URL)
    with pytest.raises(HttpTransportUnavailable):
        asyncio.run(call_http_transport(request))
    with pytest.raises(HttpTransportUnavailable):
        asyncio.run(http_request("GET", URL))
    with pytest.raises(HttpTransportUnavailable):
        asyncio.run(http_json("GET", URL))


def test_scope_installs_and_restores_the_transport():
    transport = _FakeTransport()
    assert isinstance(transport, HttpTransport)

    async def scenario():
        with http_transport_scope(transport):
            inner = await asyncio.create_task(
                call_http_transport(HttpTransportRequest(method="GET", url=URL))
            )
        with pytest.raises(HttpTransportUnavailable):
            await call_http_transport(HttpTransportRequest(method="GET", url=URL))
        return inner

    assert asyncio.run(scenario()) == transport.response
    with pytest.raises(TypeError):
        with http_transport_scope(object()):
            pass


def test_http_request_returns_a_typed_result_for_2xx():
    transport = _FakeTransport(
        _response(body=base64.b64encode(b"\x00\x01").decode(), body_encoding="base64")
    )
    result = _run(
        lambda: http_request("GET", URL, headers={"accept": "*/*"}, timeout=5),
        transport,
    )
    assert isinstance(result, HttpResult) and result.succeeded
    assert result.status == 200 and result.rule == "ragstack_query"
    assert result.content == b"\x00\x01"
    assert transport.requests == [
        {
            "method": "GET",
            "url": URL,
            "headers": {"accept": "*/*"},
            "body": None,
            "timeout": 5.0,
        }
    ]


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (
            _response(outcome="denied", status=None, headers={}, body=None, body_encoding=None, reason="budget exhausted"),
            HttpFailureKind.HTTP_DENIED,
        ),
        (
            _response(outcome="transport_error", status=None, headers={}, body=None, body_encoding=None, reason="timed out", rule=None),
            HttpFailureKind.HTTP_TRANSPORT,
        ),
        (
            _response(outcome="oversize", body=None, body_encoding=None, reason="over cap"),
            HttpFailureKind.HTTP_OVERSIZE,
        ),
        (_response(status=404, body="missing"), HttpFailureKind.HTTP_STATUS),
        (
            _response(status=302, headers={"location": "https://x.org/"}, body=None, body_encoding=None),
            HttpFailureKind.HTTP_STATUS,
        ),
    ],
)
def test_http_request_maps_outcomes_to_typed_failures(response, kind):
    for call in (lambda: http_request("GET", URL), lambda: http_json("GET", URL)):
        failure = _run(call, _FakeTransport(response))
        assert isinstance(failure, HttpFailure) and not failure.succeeded
        assert failure.kind is kind
        assert failure.status == response.status
        assert failure.rule == response.rule
        assert dict(failure.headers) == dict(response.headers)
        assert failure.message


def test_boundary_rejection_is_denied_and_transport_errors_are_transport():
    denied = _run(
        lambda: http_request("GET", "http://www.bv-brc.org/x"), _FakeTransport()
    )
    assert isinstance(denied, HttpFailure)
    assert denied.kind is HttpFailureKind.HTTP_DENIED
    with_body = _run(lambda: http_json("GET", URL, json_body={"q": 1}), _FakeTransport())
    assert with_body.kind is HttpFailureKind.HTTP_DENIED
    broken = _run(
        lambda: http_request("GET", URL), _FakeTransport(error=OSError("pipe closed"))
    )
    assert broken.kind is HttpFailureKind.HTTP_TRANSPORT


def test_http_json_sends_json_and_parses_the_body():
    transport = _FakeTransport()
    result = _run(
        lambda: http_json("POST", URL, json_body={"query": "dnaA", "k": 3}),
        transport,
    )
    assert isinstance(result, HttpJsonResult) and result.succeeded
    assert result.value == {"hits": [1, 2]}
    sent = transport.requests[0]
    assert json.loads(sent["body"]) == {"query": "dnaA", "k": 3}
    assert sent["headers"] == {
        "accept": "application/json",
        "content-type": "application/json",
    }


@pytest.mark.parametrize(
    "response",
    [
        _response(body="not json"),
        _response(body=None, body_encoding=None),
        _response(body=base64.b64encode(b"\xff\xfe").decode(), body_encoding="base64"),
    ],
)
def test_http_json_reports_undecodable_bodies(response):
    failure = _run(lambda: http_json("GET", URL), _FakeTransport(response))
    assert isinstance(failure, HttpFailure)
    assert failure.kind is HttpFailureKind.HTTP_DECODE
    assert failure.status == 200


def test_cancellation_propagates():
    class _Cancelled:
        async def __call__(self, request):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        _run(lambda: http_request("GET", URL), _Cancelled())


@pytest.mark.parametrize("function", [HTTP_REQUEST, HTTP_JSON])
def test_definitions_load_and_admit_their_binding_arguments(function):
    assert isinstance(function, LibraryFunction)
    assert function.library == "http_call_library"
    assert function.implementation.is_async
    loaded = function.load()
    assert loaded is (http_request if function is HTTP_REQUEST else http_json)
    assert function.provenance["client_boundary"]
    assert function.admit_arguments({}) == {}
    assert dict(function.admit_arguments({"method": "GET", "timeout": 30})) == {
        "method": "GET",
        "timeout": 30,
    }
    for arguments in ({"method": "DELETE"}, {"timeout": 0}, {"timeout": 121}, {"url": URL}):
        with pytest.raises(ValueError):
            function.admit_arguments(arguments)
    binding = function.bind("lookup", arguments={"method": "POST"})
    assert binding.definition_id == function.definition_id


def test_definitions_are_in_the_materializer_catalog():
    from episode_builder.planner import materializer_function_catalog

    catalog_ids = {item["definition_id"] for item in materializer_function_catalog()}
    assert {HTTP_REQUEST.definition_id, HTTP_JSON.definition_id} <= catalog_ids
