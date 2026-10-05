"""Provider diagnostics survive real SDK transport and durable receipt storage.

The loopback server supplies HTTP/SSE errors, not reasoning answers. These
checks establish reporting and redaction, not live workflow acceptance.
"""

import asyncio
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import httpx
from openai import APIError
import pytest

from agent.duet_episode_transport import DuetEpisodeBinding
from agent.duet_store import DuetStore
from agent.episode_launch import resolve_launch
from agent.episode_launch_transport import LaunchModelTransport, provider_failure
from llm_call_library.transport import ModelCallFailed, ModelTransportRequest


@contextmanager
def error_server(wire, message, *, respond=None):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            text = None if respond is None else respond(calls[-1], len(calls))
            if text is not None:
                payload = json.dumps({
                    "id": "fixture-response", "object": "chat.completion", "created": 0,
                    "model": calls[-1]["model"],
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            error = {"message": message, "code": "capacity_exceeded", "type": "capacity_error", "param": "model"}
            body = {"error": error, "debug": "unfiltered-body-must-not-be-recorded"}
            payload = ("data: " + json.dumps(body) + "\n\n").encode() if wire == "codex_responses" else json.dumps(body).encode()
            self.send_response(200 if wire == "codex_responses" else 503)
            self.send_header("Content-Type", "text/event-stream" if wire == "codex_responses" else "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("X-Request-ID", "provider-request-42")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("wire", ["chat_completions", "codex_responses"])
@pytest.mark.parametrize("owner", ["target", "refiner"])
def test_failure_receipt_preserves_provider_evidence_without_secrets(tmp_path, wire, owner):
    secret = "opaque-test-credential-without-a-vendor-prefix"
    prompt = "Private workflow input not intended for diagnostic copies."
    message = f"Server overloaded; rejected credential {secret}; supplied input {prompt}"
    request = ModelTransportRequest(
        task="reporting_check", model_type="reasoning",
        messages=({"role": "user", "content": prompt},), temperature=None,
        max_tokens=16, timeout=10, reasoning_config=None, main_runtime=None,
    )
    database = tmp_path / "authority.sqlite3"
    with error_server(wire, message) as (endpoint, calls), DuetStore(database) as store:
        store.create_duet(duet_id="owner", identity={}, policy={}, state="designing")

        def record(value):
            store.append_event(duet_id="owner", event_type="model_launch_call", provenance="host", record=value)

        route = {"provider": "custom", "model": "test-model", "base_url": endpoint, "api_mode": wire}
        if owner == "refiner":
            transport = DuetEpisodeBinding(
                "owner", {"artifact_id": "test-binding"},
                {"route": route, "model_types": ["reasoning"], "session_id": "reporting"}, secret,
            ).transport(record_attempt=record)
        else:
            (tmp_path / "credentials.env").write_text(f"PROJECT_KEY={secret}\n", encoding="utf-8")
            launch = resolve_launch({
                "project": "reporting", "project_root": str(tmp_path), "env_files": ["credentials.env"],
                "routes": {
                    "test": {**route, "auth": {"kind": "env", "env": "PROJECT_KEY", "account": "reporting"}, "fallbacks": ["backup"]},
                    "backup": {**route, "auth": {"kind": "env", "env": "PROJECT_KEY", "account": "reporting"}},
                },
                "model_slots": {"reasoning": "test"},
                "builder_slots": {"planning": "reasoning", "emission": "reasoning"},
            })
            transport = LaunchModelTransport(launch, launch_id="test-launch", record_attempt=record)
        with pytest.raises(ModelCallFailed):
            asyncio.run(transport(request))
        assert len(calls) == 1  # Reporting must not introduce a retry.

    with DuetStore(database) as reopened:
        receipts = [row["record"] for row in reopened.events("owner")]
    failure = next(row for row in receipts if row["state"] == "failed")
    physical = next(row for row in receipts if row["state"] == "physical_attempt_failed")
    assert failure["failure_category"] == "overloaded"
    assert failure["retryable"] is True
    details = failure["provider_error"]
    assert details["code"] == "capacity_exceeded"
    assert details["type"] == "capacity_error"
    assert details["param"] == "model"
    assert "Server overloaded" in details["message"]
    assert "message" in details["redacted_fields"]
    assert physical["provider_error"]["request_id"] == "provider-request-42"
    assert physical["http_status"] == (None if wire == "codex_responses" else 503)
    serialized = json.dumps(receipts)
    assert all(value not in serialized for value in (secret, prompt, "unfiltered-body-must-not-be-recorded"))


def test_diagnostic_redaction_precedes_truncation_and_fails_closed(monkeypatch):
    secret = "opaque-diagnostic-secret"
    message = "Server overloaded " + "x" * 2018 + secret + "tail" * 500
    error = APIError(message, request=httpx.Request("POST", "http://localhost/v1"), body={"message": message, "code": "capacity_exceeded"})
    route = {"provider": "custom", "model": "test-model", "base_url": "http://localhost/v1"}
    result = provider_failure(error, route, credential=secret)
    details = result["provider_error"]
    assert len(details["message"]) <= 2048
    assert "message" in details["truncated_fields"]
    assert "message" in details["redacted_fields"]
    assert secret[:10] not in details["message"]

    def unavailable(*args, **kwargs):
        raise RuntimeError("redactor unavailable")

    monkeypatch.setattr("agent.redact.redact_sensitive_text", unavailable)
    safe = provider_failure(error, route, credential=secret)
    assert safe["provider_error"]["message"] == "[redaction-unavailable]"
    assert safe["failure_category"] == result["failure_category"]
