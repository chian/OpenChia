"""A watched launch call streams and re-aggregates, like the auxiliary client.

Regression for every Builder call failing through the launch transport on the
ANL Argo gateway with ``500 Streaming is required for operations that may take
longer than 10 minutes``: the transport sent a plain non-streaming
``chat.completions.create`` with no ``max_tokens``, which that gateway refuses
above ~16k output tokens, while the auxiliary client (which the Oct-2 builds
used) streams any call that reports progress."""

from __future__ import annotations

from types import SimpleNamespace

from agent import episode_launch_transport as transport

ROUTE = {"provider": "custom", "model": "Claude Opus 5",
         "base_url": "https://apps.inside.anl.gov/argoapi/v1", "api_mode": "chat_completions"}
REQUEST = SimpleNamespace(task="episode_structured_json_reasoning")


def _chunk(text: str | None, finish: str | None = None):
    delta = SimpleNamespace(content=text, reasoning=None, reasoning_content=None, tool_calls=None, role="assistant")
    return SimpleNamespace(id="chatcmpl-1", model="Claude Opus 5", usage=None,
                           choices=[SimpleNamespace(index=0, delta=delta, finish_reason=finish)])


class _Client:
    def __init__(self, rejects_stream: bool = False) -> None:
        self.calls: list[dict] = []
        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                if kwargs.get("stream"):
                    if rejects_stream:
                        raise RuntimeError("stream not supported here")
                    return iter([_chunk("hel"), _chunk("lo"), _chunk(None, "stop")])
                return SimpleNamespace(id="chatcmpl-1", model="Claude Opus 5", usage=None,
                                       choices=[SimpleNamespace(message=SimpleNamespace(content="plain"),
                                                                finish_reason="stop")])

        self.chat = SimpleNamespace(completions=_Completions())


def test_watched_call_streams_reaggregates_and_ticks_progress() -> None:
    client = _Client()
    ticks: list[int] = []
    response = transport._chat_completion(
        client, {"model": "Claude Opus 5", "messages": []}, REQUEST, ROUTE, lambda: ticks.append(1))
    assert client.calls[0]["stream"] is True
    assert client.calls[0]["stream_options"] == {"include_usage": True}
    assert response.choices[0].message.content == "hello"
    assert ticks, "progress must tick while chunks arrive"


def test_watched_call_falls_back_to_plain_when_streaming_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr("agent.auxiliary_client._provider_requires_stream", lambda provider, base_url: False)
    client = _Client(rejects_stream=True)
    response = transport._chat_completion(client, {"model": "Claude Opus 5", "messages": []}, REQUEST, ROUTE, lambda: None)
    assert [("stream" in call) for call in client.calls] == [True, False]
    assert response.choices[0].message.content == "plain"


def test_unwatched_call_stays_plain(monkeypatch) -> None:
    monkeypatch.setattr("agent.auxiliary_client._provider_requires_stream", lambda provider, base_url: False)
    client = _Client()
    response = transport._chat_completion(client, {"model": "Claude Opus 5", "messages": []}, REQUEST, ROUTE, None)
    assert "stream" not in client.calls[0]
    assert response.choices[0].message.content == "plain"


def test_stream_only_provider_streams_even_without_progress(monkeypatch) -> None:
    monkeypatch.setattr("agent.auxiliary_client._provider_requires_stream", lambda provider, base_url: True)
    client = _Client()
    transport._chat_completion(client, {"model": "Claude Opus 5", "messages": []}, REQUEST, ROUTE, None)
    assert client.calls[0]["stream"] is True
