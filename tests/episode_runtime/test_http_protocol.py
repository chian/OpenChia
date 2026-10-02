"""HTTP request/response frames, record admission, and worker request matching."""

from __future__ import annotations

import asyncio
import io
import sys
from types import SimpleNamespace

import pytest

from agent.duet_contracts import content_id, digest_record
from agent.episode_contracts import OpaqueId, Sha256Digest
from episode_runtime import linker
from episode_runtime.http_contracts import (
    FORBIDDEN_REQUEST_HEADERS,
    MAX_HTTP_TIMEOUT_SECONDS,
    HttpBrokerError,
    admit_http_request,
    admit_http_response,
    http_request_hash,
    http_request_record,
    http_response_hash,
)
from episode_runtime.protocol import (
    FrameDecoder,
    FrameEncoder,
    FrameSender,
    HostFrameType,
    ProtocolBinding,
    ProtocolError,
    WorkerFrameType,
    episode_id_for_path,
)
from episode_runtime.worker import _ProtocolChannel, _WorkerHttpTransport
from http_call_library import HttpTransportRequest, HttpTransportResponse
from method_loop.identities import EpisodeRef


RUN_ID = OpaqueId.mint("run", "http-protocol-test")
BINDING = ProtocolBinding(
    run_id=RUN_ID,
    registration_hash=Sha256Digest.of_bytes(b"registration"),
    manifest_id=OpaqueId.mint("manifest", "http-protocol-test"),
)
PATH = [
    {"grain": "study", "key": RUN_ID.value},
    {"grain": "query", "key": "q-1"},
]
EPISODE_ID = OpaqueId(
    EpisodeRef(
        run_id=RUN_ID.value,
        path=tuple((item["grain"], item["key"]) for item in PATH),
    ).episode_id
)


def _request(**overrides):
    record = {
        "method": "GET",
        "url": "https://www.bv-brc.org/ragstack/asm-next/api/v1/query?x=1",
        "headers": {"accept": "application/json"},
        "body": None,
        "timeout": 60.0,
    }
    record.update(overrides)
    return record


def _response(**overrides):
    record = {
        "outcome": "ok",
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": '{"hits":[]}',
        "body_encoding": "utf-8",
        "reason": None,
        "rule": "ragstack_query",
    }
    record.update(overrides)
    return record


def _request_body(**overrides):
    body = {
        "http_request_id": content_id("http_request", {"n": 1}).value,
        "episode_id": EPISODE_ID.value,
        "episode_path": PATH,
        "request": _request(),
    }
    body.update(overrides)
    return body


def _round_trip(sender, frame_type, body):
    packet = FrameEncoder(sender=sender, binding=BINDING).encode(frame_type, body)
    return FrameDecoder(sender=sender, binding=BINDING).decode(packet)


def test_http_request_frame_round_trips_with_admitted_request():
    frame = _round_trip(
        FrameSender.WORKER, WorkerFrameType.HTTP_REQUEST.value, _request_body()
    )
    assert frame.frame_type == "http_request"
    assert set(frame.body) == {
        "http_request_id",
        "episode_id",
        "episode_path",
        "request",
    }
    assert [dict(item) for item in frame.body["episode_path"]] == PATH
    # The host re-admits the frozen frame record to the same canonical hash.
    assert http_request_hash(frame.body["request"]) == http_request_hash(_request())
    assert (
        episode_id_for_path(RUN_ID, frame.body["episode_path"]).value
        == frame.body["episode_id"]
    )


def test_http_response_frame_round_trips_with_admitted_response():
    body = {
        "http_request_id": content_id("http_request", {"n": 1}).value,
        "response": _response(),
    }
    frame = _round_trip(FrameSender.HOST, HostFrameType.HTTP_RESPONSE.value, body)
    assert set(frame.body) == {"http_request_id", "response"}
    assert admit_http_response(frame.body["response"]) == _response()
    assert http_response_hash(frame.body["response"]) == http_response_hash(
        _response()
    )


def test_http_frames_are_sender_bound():
    with pytest.raises(ProtocolError):
        _round_trip(
            FrameSender.HOST, WorkerFrameType.HTTP_REQUEST.value, _request_body()
        )
    with pytest.raises(ProtocolError):
        _round_trip(
            FrameSender.WORKER,
            HostFrameType.HTTP_RESPONSE.value,
            {"http_request_id": EPISODE_ID.value, "response": _response()},
        )


@pytest.mark.parametrize(
    "body",
    [
        {key: value for key, value in _request_body().items() if key != "episode_path"},
        {**_request_body(), "extra": 1},
        _request_body(episode_path=[]),
        _request_body(episode_path=[{"grain": "study"}]),
        _request_body(episode_path=[{"grain": "study", "key": ""}]),
        _request_body(episode_path=[{"grain": 1, "key": "k"}]),
        _request_body(episode_path="study/k"),
        # A path that does not hash to the claimed episode_id.
        _request_body(episode_path=PATH[:1]),
        _request_body(request=_request(url="http://www.bv-brc.org/x")),
        _request_body(request=_request(headers={"authorization": "Bearer x"})),
    ],
)
def test_http_request_frame_rejects_malformed_bodies(body):
    with pytest.raises((ProtocolError, ValueError)):
        _round_trip(FrameSender.WORKER, WorkerFrameType.HTTP_REQUEST.value, body)


@pytest.mark.parametrize(
    "response",
    [
        _response(outcome="oversize", status=200, body="x", reason="too big"),
        _response(outcome="maybe"),
        _response(headers={"set-cookie": "a=b"}),
        {key: value for key, value in _response().items() if key != "rule"},
    ],
)
def test_http_response_frame_rejects_malformed_responses(response):
    with pytest.raises(ProtocolError):
        _round_trip(
            FrameSender.HOST,
            HostFrameType.HTTP_RESPONSE.value,
            {"http_request_id": EPISODE_ID.value, "response": response},
        )


def test_admit_http_request_normalizes_and_accepts_the_canonical_shape():
    admitted = admit_http_request(
        _request(
            method="POST",
            body='{"q":"x"}',
            timeout=5,
            headers={"content-type": "application/json", "accept": "*/*"},
        )
    )
    assert admitted["timeout"] == 5.0 and isinstance(admitted["timeout"], float)
    assert list(admitted["headers"]) == ["accept", "content-type"]
    assert admit_http_request(admitted) == admitted


@pytest.mark.parametrize(
    "overrides",
    [
        {"method": "PUT"},
        {"method": "get"},
        {"url": "http://www.bv-brc.org/api"},
        {"url": "https:///api"},
        {"url": "https://WWW.bv-brc.org/api"},
        {"url": "https://www.bv-brc.org:8443/api"},
        {"url": "https://user:pw@www.bv-brc.org/api"},
        {"url": "https://www.bv-brc.org"},
        {"url": "https://www.bv-brc.org/api/../secret"},
        {"url": "https://www.bv-brc.org/api/%2e%2e/secret"},
        {"url": "https://www.bv-brc.org/api#frag"},
        {"url": "https://www.bv-brc.org/a b"},
        {"headers": {"Accept": "x"}},
        {"headers": {"accept": "a\r\nx-injected: 1"}},
        {"body": "text"},
        {"method": "POST", "body": b"bytes"},
        {"timeout": 0},
        {"timeout": MAX_HTTP_TIMEOUT_SECONDS + 1},
        {"timeout": True},
        {"timeout": float("nan")},
    ],
)
def test_admit_http_request_rejects_out_of_contract_records(overrides):
    with pytest.raises(HttpBrokerError):
        admit_http_request(_request(**overrides))


@pytest.mark.parametrize("name", sorted(FORBIDDEN_REQUEST_HEADERS))
def test_admit_http_request_rejects_every_host_owned_header(name):
    with pytest.raises(HttpBrokerError):
        admit_http_request(_request(headers={name: "x"}))


def test_admit_http_request_requires_exact_keys():
    with pytest.raises(HttpBrokerError):
        admit_http_request({**_request(), "follow_redirects": True})
    record = _request()
    del record["timeout"]
    with pytest.raises(HttpBrokerError):
        admit_http_request(record)


@pytest.mark.parametrize(
    "record",
    [
        _response(),
        _response(body=None, body_encoding=None),
        _response(body="AAEC", body_encoding="base64"),
        _response(status=302, headers={"location": "https://x.org/"}, body=None, body_encoding=None),
        _response(outcome="denied", status=None, headers={}, body=None, body_encoding=None, reason="no rule", rule=None),
        _response(outcome="transport_error", status=None, headers={}, body=None, body_encoding=None, reason="timeout"),
        _response(outcome="oversize", status=200, body=None, body_encoding=None, reason="over 262144 bytes"),
    ],
)
def test_admit_http_response_accepts_each_outcome_shape(record):
    assert admit_http_response(record) == record


@pytest.mark.parametrize(
    "record",
    [
        _response(outcome="oversize", reason="too big"),
        _response(outcome="denied", status=None, headers={}, body=None, body_encoding=None, reason=None),
        _response(outcome="denied", status=403, body=None, body_encoding=None, reason="no"),
        _response(status=None),
        _response(status=700),
        _response(status=True),
        _response(reason="unexpected"),
        _response(body_encoding=None),
        _response(body=None),
        _response(body_encoding="latin-1"),
        _response(body="not base64!", body_encoding="base64"),
        _response(status=301, body="moved"),
        _response(headers={"Content-Type": "x"}),
        _response(headers={"x-secret": "x"}),
        _response(rule=""),
    ],
)
def test_admit_http_response_rejects_inconsistent_shapes(record):
    with pytest.raises(HttpBrokerError):
        admit_http_response(record)


def test_hashes_are_deterministic_and_record_sensitive():
    assert http_request_hash(_request()) == http_request_hash(dict(_request()))
    assert http_request_hash(_request()) != http_request_hash(_request(timeout=None))
    assert http_response_hash(_response()) != http_response_hash(_response(status=201))
    library_request = HttpTransportRequest(
        method="GET",
        url=_request()["url"],
        headers={"accept": "application/json"},
        timeout=60,
    )
    assert http_request_record(library_request) == _request()
    assert http_request_hash(library_request) == http_request_hash(_request())


def _channel(monkeypatch):
    output = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=output))
    reader = asyncio.StreamReader()
    return _ProtocolChannel(binding=BINDING, reader=reader), reader, output


def test_worker_http_transport_round_trip_matches_pending_request(monkeypatch):
    async def scenario():
        channel, reader, output = _channel(monkeypatch)
        host_decoder = FrameDecoder(sender=FrameSender.WORKER, binding=BINDING)
        host_encoder = FrameEncoder(sender=FrameSender.HOST, binding=BINDING)
        transport = _WorkerHttpTransport(channel)
        id_token = linker._CURRENT_RUNTIME_EPISODE_ID.set(EPISODE_ID)
        path_token = linker._CURRENT_RUNTIME_EPISODE_PATH.set(
            tuple((item["grain"], item["key"]) for item in PATH)
        )
        try:
            call = asyncio.create_task(
                transport(
                    HttpTransportRequest(
                        method="GET",
                        url=_request()["url"],
                        headers={"accept": "application/json"},
                        timeout=60.0,
                    )
                )
            )
            receiver = asyncio.create_task(channel.receive_loop())
            while not output.getvalue():
                await asyncio.sleep(0)
        finally:
            linker._CURRENT_RUNTIME_EPISODE_PATH.reset(path_token)
            linker._CURRENT_RUNTIME_EPISODE_ID.reset(id_token)

        frame = host_decoder.decode(output.getvalue())
        assert frame.frame_type == WorkerFrameType.HTTP_REQUEST.value
        assert frame.body["episode_id"] == EPISODE_ID.value
        assert (
            episode_id_for_path(RUN_ID, frame.body["episode_path"]) == EPISODE_ID
        )
        expected_id = content_id(
            "http_request",
            {
                "run_id": RUN_ID.value,
                "registration_hash": BINDING.registration_hash.value,
                "episode_id": EPISODE_ID.value,
                "ordinal": 0,
                "request_hash": digest_record(_request()).value,
            },
        )
        assert frame.body["http_request_id"] == expected_id.value

        reader.feed_data(
            host_encoder.encode(
                HostFrameType.HTTP_RESPONSE.value,
                {"http_request_id": expected_id.value, "response": _response()},
            )
        )
        response = await call
        assert isinstance(response, HttpTransportResponse)
        assert response.status == 200 and response.rule == "ragstack_query"
        assert channel._pending_http == {}

        # A second response for the settled id is a protocol violation.
        reader.feed_data(
            host_encoder.encode(
                HostFrameType.HTTP_RESPONSE.value,
                {"http_request_id": expected_id.value, "response": _response()},
            )
        )
        with pytest.raises(ProtocolError):
            await receiver

    asyncio.run(scenario())


def test_worker_http_transport_requires_an_episode_context(monkeypatch):
    async def scenario():
        channel, _, output = _channel(monkeypatch)
        with pytest.raises(linker.RuntimeLinkError):
            await _WorkerHttpTransport(channel)(
                HttpTransportRequest(method="GET", url=_request()["url"])
            )
        assert output.getvalue() == b""

    asyncio.run(scenario())
