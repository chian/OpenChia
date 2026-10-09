"""A refusal of service returned as an ordinary reply fails the model call.

2026-10-09: with the Argo monthly quota exhausted, every refiner call through the
shared pinned transport "succeeded" in about one second with Argo's
"ACCESS REVOKED … Monthly limit exceeded" notice as its text, and that text
became refiner input.
"""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent.provider_notices import ProviderRefusedService, provider_notice

ARGO_NOTICE = (
    "\n\n⚠️ **IMPORTANT USAGE NOTICE FROM ARGO** ⚠️\n\n🚫 **ACCESS REVOKED** 🚫\n\nYour Argo usage limit has "
    "been exceeded. Reason: Monthly limit exceeded. Please contact your Directorate Operations Officer for "
    "assistance.\n\n ** END NOTICE FROM ARGO **"
)


def test_argo_notice_is_recognized() -> None:
    notice = provider_notice(ARGO_NOTICE)
    assert notice and "ACCESS REVOKED" in notice and "\n" not in notice


@pytest.mark.parametrize("text", [
    "The collection endpoint enforces a quota exceeded error when called too often.",  # one marker only
    "OK",
    "",
    None,
    ("Access revoked and monthly limit exceeded are discussed in this long design note. " * 100),  # too long
])
def test_ordinary_answers_are_not_notices(text) -> None:
    assert provider_notice(text) is None


@contextmanager
def _gateway(text):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):  # noqa: N802 - http.server API
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in (
                    {"id": "c", "object": "chat.completion.chunk", "model": "m",
                     "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]},
                    {"id": "c", "object": "chat.completion.chunk", "model": "m",
                     "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                ):
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                return
            payload = json.dumps({"id": "c", "object": "chat.completion", "model": "m", "choices": [
                {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _request():
    from llm_call_library.transport import ModelTransportRequest

    return ModelTransportRequest(
        task="notice_check", model_type="reasoning", messages=({"role": "user", "content": "hello"},),
        temperature=None, max_tokens=16, timeout=10, reasoning_config=None, main_runtime=None,
    )


def _call(endpoint, records, text_progress=None):
    from agent.episode_launch_transport import invoke_pinned_route

    route = {"provider": "custom", "model": "m", "base_url": endpoint, "api_mode": "chat_completions",
             "recovery": {"mode": "retry_on_healthy_probe", "max_replacements": 1}}
    return asyncio.run(invoke_pinned_route(
        route, None, _request(), threading.Event(), text_progress or (lambda: None),
        record_activity=records.append,
    ))


def test_shared_transport_fails_on_a_notice_without_retrying() -> None:
    records = []
    with _gateway(ARGO_NOTICE) as (endpoint, calls):
        with pytest.raises(ProviderRefusedService, match="Provider refused service"):
            _call(endpoint, records)
    assert len(calls) == 1  # a refusal is not a dropped connection: no replacement
    assert "physical_attempt_failed" in [r["state"] for r in records]


def test_shared_transport_returns_ordinary_answers() -> None:
    records = []
    with _gateway("OK") as (endpoint, calls):
        text, _model = _call(endpoint, records)
    assert text == "OK" and len(calls) == 1
