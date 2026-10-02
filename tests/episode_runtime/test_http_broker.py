"""The host HTTP broker applies the approved egress policy (chian/OpenChia#8).

Every case drives ``ScopedHttpBroker`` with a fake ``HostHttpTransport``; the
network is never touched.  Each returned record must already be canonical
(``admit_http_response`` is the identity on it), and the credential must reach
only the fake transport's outgoing headers.
"""
from __future__ import annotations

import asyncio
import base64
import os
from pathlib import Path

import pytest

from agent.episode_contracts import EpisodeEgressRule
from episode_runtime.http_broker import (
    HTTP_FRAME_OVERHEAD_BYTES,
    MAX_CREDENTIAL_FILE_BYTES,
    CredentialSpec,
    ResponseTooLarge,
    ScopedHttpBroker,
    load_egress_config,
)
from episode_runtime.http_contracts import (
    MAX_HTTP_TIMEOUT_SECONDS,
    HttpBrokerError,
    admit_http_response,
)

HOST = "www.bv-brc.org"
SECRET = "s3cr3t-token-value"


def _rule(name="query", **overrides) -> EpisodeEgressRule:
    record = {
        "name": name,
        "host": HOST,
        "path_prefix": "/ragstack/api/",
        "methods": ["GET", "HEAD", "POST"],
        "read_only": True,
        "max_requests": 10,
        "max_response_bytes": 4096,
        "credential": None,
    }
    record.update(overrides)
    return EpisodeEgressRule.from_record(record)


def _request(url=f"https://{HOST}/ragstack/api/v1/query?x=1", method="GET", **extra):
    record = {"method": method, "url": url, "headers": {}, "body": None, "timeout": None}
    record.update(extra)
    return record


class FakeTransport:
    def __init__(self, result=(200, {"Content-Type": "application/json"}, b'{"ok":1}')):
        self.result = result
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _broker(rules=None, *, transport=None, credentials=None, max_frame_bytes=1_048_576):
    return ScopedHttpBroker(
        policy={"fetcher": tuple(rules or (_rule(),))},
        credentials=credentials or {},
        transport=transport or FakeTransport(),
        max_frame_bytes=max_frame_bytes,
    )


def _call(broker, request=None, local_id="fetcher"):
    response = asyncio.run(broker(local_id=local_id, request=request or _request()))
    assert admit_http_response(response) == response
    return response


@pytest.mark.parametrize(
    ("prefix", "path", "admitted"),
    [
        ("/ragstack/api/", "/ragstack/api/v1", True),
        ("/ragstack/api/", "/ragstack/api", False),
        ("/ragstack/api", "/ragstack/api", True),
        ("/ragstack/api", "/ragstack/api/v1", True),
        ("/ragstack/api", "/ragstack/apix", False),
        ("/ragstack/api", "/ragstack/ap", False),
        ("/", "/anything/at/all", True),
    ],
)
def test_path_prefix_respects_the_segment_boundary(prefix, path, admitted):
    transport = FakeTransport()
    broker = _broker([_rule(path_prefix=prefix)], transport=transport)
    response = _call(broker, _request(url=f"https://{HOST}{path}?q=1"))
    assert (response["outcome"] == "ok") is admitted
    assert len(transport.calls) == int(admitted)


def test_unmatched_host_method_or_node_is_denied_without_dialing():
    transport = FakeTransport()
    broker = _broker([_rule(methods=["GET"])], transport=transport)
    other_host = _call(broker, _request(url="https://evil.example/ragstack/api/v1"))
    post = _call(broker, _request(method="POST", body="{}"))
    other_node = _call(broker, local_id="someone_else")
    for response in (other_host, post, other_node):
        assert response["outcome"] == "denied"
        assert response["rule"] is None
        assert response["status"] is None and response["headers"] == {}
        assert response["reason"].startswith("no egress rule admits ")
    assert post["reason"] == f"no egress rule admits POST {HOST}/ragstack/api/v1/query"
    assert transport.calls == []


def test_first_matching_rule_wins_and_is_named():
    broker = _broker([_rule("narrow", path_prefix="/ragstack/api/v1/"), _rule("wide")])
    assert _call(broker)["rule"] == "narrow"
    assert broker.match_rule("fetcher", _request(url=f"https://{HOST}/ragstack/api/v2")).name == "wide"


def test_malformed_requests_raise_as_protocol_violations():
    with pytest.raises(HttpBrokerError):
        asyncio.run(_broker()(local_id="fetcher", request=_request(method="DELETE")))
    with pytest.raises(HttpBrokerError):
        asyncio.run(_broker()(local_id="fetcher", request=_request(headers={"authorization": "x"})))


def test_budget_is_per_rule_and_node_and_counts_failures():
    transport = FakeTransport(OSError("boom"))
    broker = _broker([_rule(max_requests=2)], transport=transport)
    outcomes = [_call(broker)["outcome"] for _ in range(3)]
    assert outcomes == ["transport_error", "transport_error", "denied"]
    assert broker.request_count("fetcher", "query") == 2
    assert len(transport.calls) == 2
    exhausted = _call(broker)
    assert exhausted["rule"] == "query" and "budget" in exhausted["reason"]
    assert broker.request_count("fetcher", "query") == 2


def test_oversize_from_the_transport_keeps_status_and_admitted_headers():
    transport = FakeTransport(
        ResponseTooLarge(200, {"Content-Type": "text/plain", "Set-Cookie": "a=b"})
    )
    response = _call(_broker(transport=transport))
    assert response["outcome"] == "oversize"
    assert response["status"] == 200
    assert response["headers"] == {"content-type": "text/plain"}
    assert response["body"] is None


def test_response_cap_is_bounded_by_the_frame():
    transport = FakeTransport((200, {}, b"x" * 5000))
    broker = _broker(
        [_rule(max_response_bytes=900_000)],
        transport=transport,
        max_frame_bytes=HTTP_FRAME_OVERHEAD_BYTES + 4096,
    )
    response = _call(broker)
    assert transport.calls[0]["max_response_bytes"] == 4096
    assert response["outcome"] == "oversize"


def test_base64_growth_past_the_frame_is_oversize_not_a_run_failure():
    payload = bytes([0xFF]) * 900_000
    broker = _broker(
        [_rule(max_response_bytes=900_000)],
        transport=FakeTransport((200, {}, payload)),
    )
    assert _call(broker)["outcome"] == "oversize"


def _credential(tmp_path, content=f"  {SECRET}\n", **overrides) -> CredentialSpec:
    path = tmp_path / "token"
    if content is not None:
        path.write_text(content)
    return CredentialSpec(name="patric", path=path, **overrides)


def test_credential_reaches_only_the_outgoing_request(tmp_path):
    transport = FakeTransport((200, {"X-Request-Id": "r1"}, f"echo {SECRET}".encode()[:4]))
    broker = _broker(
        [_rule(credential="patric")],
        transport=transport,
        credentials={"patric": _credential(tmp_path)},
    )
    response = _call(broker, _request(headers={"accept": "application/json"}))
    sent = dict(transport.calls[0]["headers"])
    assert sent == {"accept": "application/json", "authorization": f"Bearer {SECRET}"}
    assert response["outcome"] == "ok"
    assert SECRET not in repr(response)


def test_custom_header_and_empty_scheme_override_worker_headers(tmp_path):
    transport = FakeTransport()
    spec = _credential(tmp_path, header="X-Api-Key", scheme="")
    broker = _broker([_rule(credential="patric")], transport=transport, credentials={"patric": spec})
    _call(broker, _request(headers={"x-api-key": "worker-guess"}))
    assert transport.calls[0]["headers"]["x-api-key"] == SECRET


def test_transport_error_reason_never_echoes_the_token(tmp_path):
    transport = FakeTransport(RuntimeError(f"upstream rejected Bearer {SECRET}"))
    broker = _broker(
        [_rule(credential="patric")],
        transport=transport,
        credentials={"patric": _credential(tmp_path)},
    )
    response = _call(broker)
    assert response["outcome"] == "transport_error"
    assert response["reason"].startswith("RuntimeError: ")
    assert SECRET not in response["reason"]


@pytest.mark.parametrize(
    "case", ["unconfigured", "missing", "directory", "empty", "oversize", "multiline"]
)
def test_unusable_credentials_are_denied_without_revealing_contents(tmp_path, case):
    credentials = {}
    if case != "unconfigured":
        content = {
            "missing": None,
            "directory": None,
            "empty": "  \n",
            "oversize": "a" * (MAX_CREDENTIAL_FILE_BYTES + 1),
            "multiline": f"{SECRET}\nsecond-line",
        }[case]
        spec = _credential(tmp_path, content=content)
        if case == "directory":
            spec.path.mkdir()
        credentials = {"patric": spec}
    transport = FakeTransport()
    broker = _broker([_rule(credential="patric")], transport=transport, credentials=credentials)
    response = _call(broker)
    assert response["outcome"] == "denied"
    assert response["rule"] == "query"
    assert "patric" in response["reason"]
    assert SECRET not in response["reason"] and str(tmp_path) not in response["reason"]
    assert transport.calls == []


def test_text_and_binary_bodies_are_encoded_canonically():
    text = _call(_broker(transport=FakeTransport((200, {}, "héllo".encode()))))
    assert (text["body"], text["body_encoding"]) == ("héllo", "utf-8")
    raw = b"\xff\x00\x10"
    binary = _call(_broker(transport=FakeTransport((200, {}, raw))))
    assert binary["body_encoding"] == "base64"
    assert base64.b64decode(binary["body"]) == raw


def test_head_and_redirect_bodies_are_dropped():
    head = _call(_broker(transport=FakeTransport((200, {}, b"ignored"))), _request(method="HEAD"))
    assert head["outcome"] == "ok" and head["body"] is None
    redirect = _call(
        _broker(transport=FakeTransport((302, {"Location": "https://elsewhere/"}, b"moved")))
    )
    assert redirect["status"] == 302 and redirect["body"] is None
    assert redirect["headers"] == {"location": "https://elsewhere/"}


def test_timeout_defaults_and_is_clamped():
    transport = FakeTransport()
    broker = _broker(transport=transport)
    _call(broker)
    _call(broker, _request(timeout=MAX_HTTP_TIMEOUT_SECONDS))
    assert [call["timeout"] for call in transport.calls] == [30.0, MAX_HTTP_TIMEOUT_SECONDS]


def test_invalid_upstream_status_is_a_transport_error():
    assert _call(_broker(transport=FakeTransport((700, {}, b""))))["outcome"] == "transport_error"


def test_load_egress_config_parses_the_operator_block(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    hosts, credentials = load_egress_config(
        {
            "openchia": {
                "egress": {
                    "allowed_hosts": ["www.bv-brc.org", "api.example.org", "www.bv-brc.org"],
                    "credentials": {"patric": {"kind": "bearer_token_file", "path": "~/.patric_token"}},
                }
            }
        }
    )
    assert hosts == ("api.example.org", "www.bv-brc.org")
    spec = credentials["patric"]
    assert spec.path == Path(os.path.expanduser("~/.patric_token"))
    assert (spec.header, spec.scheme) == ("Authorization", "Bearer")
    assert load_egress_config({}) == ((), {})


@pytest.mark.parametrize(
    "egress",
    [
        {"allowed_hosts": ["https://www.bv-brc.org"]},
        {"allowed_hosts": ["WWW.BV-BRC.ORG"]},
        {"allowed_hosts": "www.bv-brc.org"},
        {"credentials": {"patric": {"kind": "oauth", "path": "/x"}}},
        {"credentials": {"patric": {"path": "relative/token"}}},
        {"credentials": {"patric": {"kind": "bearer_token_file"}}},
        {"credentials": {"Bad Name": {"path": "/x"}}},
        {"credentials": {"patric": {"path": "/x", "token": "inline"}}},
        {"proxy": "http://x"},
    ],
)
def test_load_egress_config_rejects_malformed_blocks(egress):
    with pytest.raises(ValueError):
        load_egress_config({"openchia": {"egress": egress}})
