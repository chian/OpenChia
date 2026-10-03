"""Host-owned, narrowly scoped model transport for isolated Run workers."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from types import MappingProxyType
from typing import Mapping

from agent.episode_contracts import Sha256Digest
from llm_call_library import (
    ModelTransport,
    ModelTransportRequest,
    ModelTransportResponse,
)


ADMITTED_MODEL_TASKS = frozenset(
    {
        "episode_structured_json_reasoning",
        "episode_structured_json_fast",
        "episode_probability_reasoning",
        "episode_probability_fast",
    }
)
_FAST_REASONING_CONFIG = {"enabled": False, "effort": "none"}


class ModelBrokerError(RuntimeError):
    """The worker requested authority outside the scoped model boundary."""


def _mapping(value: object, name: str, fields: set[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ModelBrokerError(f"{name} fields must be exact")
    return value


def model_request_record(request: ModelTransportRequest) -> dict[str, object]:
    if not isinstance(request, ModelTransportRequest):
        raise TypeError("request must be a ModelTransportRequest")
    return {
        "task": request.task,
        "model_type": request.model_type,
        "messages": [dict(item) for item in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "timeout": request.timeout,
        "reasoning_config": (
            None
            if request.reasoning_config is None
            else dict(request.reasoning_config)
        ),
        "main_runtime": (
            None if request.main_runtime is None else dict(request.main_runtime)
        ),
    }


def admit_model_request(value: object) -> ModelTransportRequest:
    record = _mapping(
        value,
        "model request",
        {
            "task",
            "model_type",
            "messages",
            "temperature",
            "max_tokens",
            "timeout",
            "reasoning_config",
            "main_runtime",
        },
    )
    task = record["task"]
    if task not in ADMITTED_MODEL_TASKS:
        raise ModelBrokerError("worker requested an unscoped model task")
    messages = record["messages"]
    if not isinstance(messages, list) or len(messages) != 2:
        raise ModelBrokerError("model request needs one system and one user message")
    normalized_messages: list[Mapping[str, str]] = []
    for index, item in enumerate(messages):
        message = _mapping(item, "model message", {"role", "content"})
        expected_role = "system" if index == 0 else "user"
        if message["role"] != expected_role:
            raise ModelBrokerError("model message roles must be system then user")
        content = message["content"]
        if not isinstance(content, str) or not content or "\x00" in content:
            raise ModelBrokerError("model message content must be non-empty text")
        normalized_messages.append(
            MappingProxyType({"role": expected_role, "content": content})
        )
    temperature = record["temperature"]
    if temperature is not None and (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not math.isfinite(float(temperature))
        or not 0.0 <= float(temperature) <= 2.0
    ):
        raise ModelBrokerError("model temperature is outside the scoped range")
    max_tokens = record["max_tokens"]
    if max_tokens is not None and (
        isinstance(max_tokens, bool)
        or not isinstance(max_tokens, int)
        or max_tokens < 1
    ):
        raise ModelBrokerError("model max_tokens must be positive or absent")
    timeout = record["timeout"]
    if timeout is not None and (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(float(timeout))
        or float(timeout) <= 0.0
    ):
        raise ModelBrokerError("model transport timeout must be positive or absent")
    reasoning = record["reasoning_config"]
    if reasoning is not None and reasoning != _FAST_REASONING_CONFIG:
        raise ModelBrokerError("worker requested an unscoped reasoning configuration")
    if record["main_runtime"] is not None:
        raise ModelBrokerError("worker cannot supply host runtime routing state")
    return ModelTransportRequest(
        task=task,
        model_type=record["model_type"],
        messages=tuple(normalized_messages),
        temperature=(None if temperature is None else float(temperature)),
        max_tokens=max_tokens,
        timeout=(None if timeout is None else float(timeout)),
        reasoning_config=reasoning,
        main_runtime=None,
    )


def model_response_record(response: ModelTransportResponse) -> dict[str, object]:
    if not isinstance(response, ModelTransportResponse):
        raise TypeError("response must be a ModelTransportResponse")
    return {"text": response.text, "route": dict(response.route)}


def admit_model_response(value: object) -> ModelTransportResponse:
    record = _mapping(value, "model response", {"text", "route"})
    text = record["text"]
    route = record["route"]
    if not isinstance(text, str) or "\x00" in text:
        raise ModelBrokerError("model response text is invalid")
    if not isinstance(route, Mapping) or any(
        not isinstance(name, str)
        or not name
        or not isinstance(item, str)
        or "\x00" in item
        for name, item in route.items()
    ):
        raise ModelBrokerError("model response route must contain text fields")
    return ModelTransportResponse(text=text, route=route)


def model_request_hash(request: ModelTransportRequest) -> Sha256Digest:
    from agent.duet_contracts import digest_record

    return digest_record(model_request_record(request))


def model_response_hash(response: ModelTransportResponse) -> Sha256Digest:
    from agent.duet_contracts import digest_record

    return digest_record(model_response_record(response))


@dataclass(frozen=True)
class ScopedModelBroker:
    """Invoke exactly one configured host transport for admitted requests."""

    transport: ModelTransport
    episode_paths: Mapping[tuple[str, ...], str]

    def __post_init__(self) -> None:
        if not isinstance(self.transport, ModelTransport):
            raise TypeError("transport must implement ModelTransport")
        object.__setattr__(self, "episode_paths", MappingProxyType(dict(self.episode_paths)))

    async def __call__(self, value: object, *, episode_path: object) -> ModelTransportResponse:
        from .protocol import ProtocolError, _episode_path

        request = admit_model_request(value)
        try:
            grains = tuple(part["grain"] for part in _episode_path(episode_path))
        except ProtocolError as exc:
            raise ModelBrokerError(str(exc)) from exc
        local_id = self.episode_paths.get(grains)
        if local_id is None:
            raise ModelBrokerError("model call path is outside the admitted workflow")
        request = replace(request, episode_local_id=local_id, call_role="run")
        response = await self.transport(request)
        if not isinstance(response, ModelTransportResponse):
            raise ModelBrokerError("host model transport returned another type")
        return admit_model_response(model_response_record(response))


__all__ = [
    "ADMITTED_MODEL_TASKS",
    "ModelBrokerError",
    "ScopedModelBroker",
    "admit_model_request",
    "admit_model_response",
    "model_request_hash",
    "model_request_record",
    "model_response_hash",
    "model_response_record",
]
