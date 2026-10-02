"""Typed outcomes for reusable Episode HTTP calls."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class HttpFailureKind(str, Enum):
    HTTP_DENIED = "http-denied"
    HTTP_TRANSPORT = "http-transport"
    HTTP_OVERSIZE = "http-oversize"
    HTTP_STATUS = "http-status"
    HTTP_DECODE = "http-decode"


def _frozen_headers(value: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError("headers must be a mapping")
    return MappingProxyType({str(key): str(value[key]) for key in sorted(value)})


def _content(body: str | None, body_encoding: str | None) -> bytes | None:
    if body is None:
        return None
    if body_encoding == "base64":
        try:
            return base64.b64decode(body.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise ValueError("HTTP body is not valid base64") from exc
    return body.encode("utf-8")


@dataclass(frozen=True)
class HttpFailure:
    """One typed non-success outcome; never a Run failure by itself."""

    kind: HttpFailureKind
    message: str
    status: int | None = None
    rule: str | None = None
    headers: Mapping[str, str] = MappingProxyType({})
    body: str | None = None
    body_encoding: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, HttpFailureKind):
            raise TypeError("kind must be an HttpFailureKind")
        object.__setattr__(self, "headers", _frozen_headers(self.headers))

    @property
    def succeeded(self) -> bool:
        return False


@dataclass(frozen=True)
class HttpResult:
    """A successful (2xx) brokered HTTP exchange."""

    status: int
    headers: Mapping[str, str]
    body: str | None
    body_encoding: str | None
    rule: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", _frozen_headers(self.headers))

    @property
    def succeeded(self) -> bool:
        return True

    @property
    def content(self) -> bytes | None:
        """The exact response bytes, or None when the response had no body."""

        return _content(self.body, self.body_encoding)

    @property
    def text(self) -> str | None:
        """The body as UTF-8 text; raises UnicodeDecodeError for binary bodies."""

        if self.body is None or self.body_encoding == "utf-8":
            return self.body
        content = self.content
        return None if content is None else content.decode("utf-8")


@dataclass(frozen=True)
class HttpJsonResult:
    """A successful (2xx) brokered exchange whose body parsed as JSON."""

    status: int
    headers: Mapping[str, str]
    value: object
    raw_body: str
    rule: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", _frozen_headers(self.headers))

    @property
    def succeeded(self) -> bool:
        return True


__all__ = [
    "HttpFailure",
    "HttpFailureKind",
    "HttpJsonResult",
    "HttpResult",
]
