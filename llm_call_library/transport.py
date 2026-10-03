"""Scoped transport boundary for reusable Episode model calls.

The default transport is the existing host auxiliary client.  An isolated Run
worker installs a process-local broker transport instead, so generated Episode
code can request a model call without receiving provider credentials, network
access, or a host runtime object.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Protocol, Sequence, runtime_checkable


def _messages(value: object) -> tuple[Mapping[str, str], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TypeError("messages must be a sequence")
    result: list[Mapping[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"role", "content"}:
            raise ValueError("each model message must contain role and content")
        role = item["role"]
        content = item["content"]
        if not isinstance(role, str) or not role:
            raise ValueError("model message role must be non-empty text")
        if not isinstance(content, str) or not content:
            raise ValueError("model message content must be non-empty text")
        result.append(MappingProxyType({"role": role, "content": content}))
    if not result:
        raise ValueError("model request requires at least one message")
    return tuple(result)


@dataclass(frozen=True)
class ModelTransportRequest:
    """Provider-neutral request crossing the one model transport boundary."""

    task: str
    messages: tuple[Mapping[str, str], ...]
    temperature: float | None
    max_tokens: int | None
    timeout: float | None
    reasoning_config: Mapping[str, object] | None
    main_runtime: Mapping[str, Any] | None
    episode_local_id: str | None = None
    call_role: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task, str) or not self.task.strip():
            raise ValueError("model transport task must be non-empty text")
        object.__setattr__(self, "messages", _messages(self.messages))
        if self.reasoning_config is not None:
            if not isinstance(self.reasoning_config, Mapping):
                raise TypeError("reasoning_config must be a mapping or None")
            object.__setattr__(
                self,
                "reasoning_config",
                MappingProxyType(dict(self.reasoning_config)),
            )
        if self.main_runtime is not None:
            if not isinstance(self.main_runtime, Mapping):
                raise TypeError("main_runtime must be a mapping or None")
            object.__setattr__(
                self,
                "main_runtime",
                MappingProxyType(dict(self.main_runtime)),
            )


@dataclass(frozen=True)
class ModelTransportResponse:
    """Text plus the concrete route receipt returned by a transport."""

    text: str
    route: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("model transport response text must be text")
        if not isinstance(self.route, Mapping):
            raise TypeError("model transport route must be a mapping")
        object.__setattr__(
            self,
            "route",
            MappingProxyType(
                {
                    str(name): str(value)
                    for name, value in self.route.items()
                    if value is not None
                }
            ),
        )


@runtime_checkable
class ModelTransport(Protocol):
    async def __call__(
        self,
        request: ModelTransportRequest,
    ) -> ModelTransportResponse: ...


_SCOPED_TRANSPORT: ContextVar[ModelTransport | None] = ContextVar(
    "openchia_model_transport",
    default=None,
)

_CALL_IDENTITY: ContextVar[tuple[str, str] | None] = ContextVar("episode_model_call_identity", default=None)


@contextmanager
def model_call_scope(episode_local_id: str, role: str) -> Iterator[None]:
    """Host-authored Builder call identity, independent of provider selection."""
    token = _CALL_IDENTITY.set((episode_local_id, role))
    try:
        yield
    finally:
        _CALL_IDENTITY.reset(token)


@contextmanager
def model_transport_scope(transport: ModelTransport) -> Iterator[None]:
    """Install one transport for the current async context and its children."""

    if not isinstance(transport, ModelTransport):
        raise TypeError("transport must implement ModelTransport")
    token = _SCOPED_TRANSPORT.set(transport)
    try:
        yield
    finally:
        _SCOPED_TRANSPORT.reset(token)


async def _host_transport(
    request: ModelTransportRequest,
) -> ModelTransportResponse:
    from agent.auxiliary_client import (
        async_call_llm,
        extract_content_or_reasoning,
    )

    route: dict[str, str] = {}
    response = await async_call_llm(
        task=request.task,
        messages=[dict(item) for item in request.messages],
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        timeout=request.timeout,
        main_runtime=(
            None
            if request.main_runtime is None
            else dict(request.main_runtime)
        ),
        reasoning_config=(
            None
            if request.reasoning_config is None
            else dict(request.reasoning_config)
        ),
        route_info=route,
    )
    return ModelTransportResponse(
        text=extract_content_or_reasoning(response) or "",
        route=route,
    )


async def call_model_transport(
    request: ModelTransportRequest,
) -> ModelTransportResponse:
    """Route a request through the scoped broker or the normal host client."""

    if not isinstance(request, ModelTransportRequest):
        raise TypeError("request must be a ModelTransportRequest")
    identity = _CALL_IDENTITY.get()
    if identity is not None:
        from dataclasses import replace
        request = replace(request, episode_local_id=identity[0], call_role=identity[1])
    transport = _SCOPED_TRANSPORT.get()
    return await (transport or _host_transport)(request)


__all__ = [
    "ModelTransport",
    "ModelTransportRequest",
    "ModelTransportResponse",
    "call_model_transport",
    "model_call_scope",
    "model_transport_scope",
]
