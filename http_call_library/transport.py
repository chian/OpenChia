"""Scoped transport boundary for reusable Episode HTTP calls.

Unlike the model transport there is no host fallback: an HTTP request leaves
generated Episode code only through a transport installed for the current
async context.  The isolated Run worker installs one that forwards the
request over its protocol pipe to the host-owned broker, so generated code
never receives network access, credentials, or a client object.

This module is staged into the isolated worker and must import only the
standard library.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import math
from types import MappingProxyType
from typing import Iterator, Mapping, Protocol, runtime_checkable


HTTP_OUTCOMES = ("denied", "ok", "oversize", "transport_error")
HTTP_BODY_ENCODINGS = ("base64", "utf-8")


class HttpTransportUnavailable(RuntimeError):
    """No HTTP transport is installed for the current execution context."""


def _headers(value: object, name: str) -> Mapping[str, str]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping or None")
    result: dict[str, str] = {}
    for key in sorted(value):
        item = value[key]
        if not isinstance(key, str) or not key:
            raise TypeError(f"{name} names must be non-empty text")
        if not isinstance(item, str):
            raise TypeError(f"{name} values must be text")
        result[key] = item
    return MappingProxyType(result)


def _optional_text(value: object, name: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{name} must be text or None")
    return value


@dataclass(frozen=True)
class HttpTransportRequest:
    """Provider-neutral request crossing the one HTTP transport boundary."""

    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: str | None = None
    timeout: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.method, str) or not self.method:
            raise TypeError("HTTP method must be non-empty text")
        if not isinstance(self.url, str) or not self.url:
            raise TypeError("HTTP url must be non-empty text")
        object.__setattr__(
            self, "headers", _headers(self.headers, "HTTP request headers")
        )
        _optional_text(self.body, "HTTP request body")
        if self.timeout is not None:
            if isinstance(self.timeout, bool) or not isinstance(
                self.timeout, (int, float)
            ):
                raise TypeError("HTTP timeout must be a number or None")
            if not math.isfinite(float(self.timeout)) or self.timeout <= 0:
                raise ValueError("HTTP timeout must be positive and finite")
            object.__setattr__(self, "timeout", float(self.timeout))


@dataclass(frozen=True)
class HttpTransportResponse:
    """The typed outcome of one brokered HTTP exchange."""

    outcome: str
    status: int | None
    headers: Mapping[str, str]
    body: str | None
    body_encoding: str | None
    reason: str | None
    rule: str | None

    def __post_init__(self) -> None:
        if self.outcome not in HTTP_OUTCOMES:
            raise ValueError("HTTP outcome is not admitted")
        if self.status is not None and (
            isinstance(self.status, bool) or not isinstance(self.status, int)
        ):
            raise TypeError("HTTP status must be an integer or None")
        object.__setattr__(
            self, "headers", _headers(self.headers, "HTTP response headers")
        )
        _optional_text(self.body, "HTTP response body")
        if self.body_encoding is not None and (
            self.body_encoding not in HTTP_BODY_ENCODINGS
        ):
            raise ValueError("HTTP body_encoding is not admitted")
        if (self.body is None) != (self.body_encoding is None):
            raise ValueError("HTTP body and body_encoding must be present together")
        _optional_text(self.reason, "HTTP reason")
        _optional_text(self.rule, "HTTP rule")


@runtime_checkable
class HttpTransport(Protocol):
    async def __call__(
        self,
        request: HttpTransportRequest,
    ) -> HttpTransportResponse: ...


_SCOPED_HTTP_TRANSPORT: ContextVar[HttpTransport | None] = ContextVar(
    "openchia_http_transport",
    default=None,
)


@contextmanager
def http_transport_scope(transport: HttpTransport) -> Iterator[None]:
    """Install one transport for the current async context and its children."""

    if not isinstance(transport, HttpTransport):
        raise TypeError("transport must implement HttpTransport")
    token = _SCOPED_HTTP_TRANSPORT.set(transport)
    try:
        yield
    finally:
        _SCOPED_HTTP_TRANSPORT.reset(token)


async def call_http_transport(
    request: HttpTransportRequest,
) -> HttpTransportResponse:
    """Route a request through the scoped transport; there is no fallback."""

    if not isinstance(request, HttpTransportRequest):
        raise TypeError("request must be an HttpTransportRequest")
    transport = _SCOPED_HTTP_TRANSPORT.get()
    if transport is None:
        raise HttpTransportUnavailable(
            "no HTTP transport is installed; HTTP calls run only inside an "
            "isolated Run whose approved Episode declares egress"
        )
    response = await transport(request)
    if not isinstance(response, HttpTransportResponse):
        raise TypeError("HTTP transport returned another type")
    return response


__all__ = [
    "HTTP_BODY_ENCODINGS",
    "HTTP_OUTCOMES",
    "HttpTransport",
    "HttpTransportRequest",
    "HttpTransportResponse",
    "HttpTransportUnavailable",
    "call_http_transport",
    "http_transport_scope",
]
