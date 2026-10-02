"""Canonical HTTP request/response records shared by the worker and host.

Staged into the isolated worker: it imports only the standard library and
already-staged packages.  The host-owned broker (``http_broker.py``) applies
the approved egress policy; this module owns only the record shapes, their
exact-key admission, and their evidence hashes.  Credentials never appear in
either record: the host adds them after ``http_request_hash`` is computed.
"""

from __future__ import annotations

import base64
import binascii
import math
import re
from types import MappingProxyType
from typing import Mapping
from urllib.parse import unquote, urlsplit

from agent.duet_contracts import digest_record
from agent.episode_contracts import Sha256Digest
from http_call_library import (
    HTTP_BODY_ENCODINGS,
    HTTP_OUTCOMES,
    HttpTransportRequest,
    HttpTransportResponse,
)


ADMITTED_METHODS = frozenset({"GET", "HEAD", "POST"})
FORBIDDEN_REQUEST_HEADERS = frozenset(
    {
        "authorization",
        "content-length",
        "cookie",
        "host",
        "proxy-authorization",
        "transfer-encoding",
    }
)
ADMITTED_RESPONSE_HEADERS = frozenset(
    {
        "content-length",
        "content-type",
        "date",
        "location",
        "retry-after",
        "x-request-id",
    }
)
ADMITTED_HTTP_OUTCOMES = frozenset(HTTP_OUTCOMES)
MAX_HTTP_TIMEOUT_SECONDS = 120.0
MAX_HTTP_URL_CHARS = 8192
MAX_HTTP_HEADERS = 64
MAX_HTTP_HEADER_VALUE_CHARS = 8192
MAX_HTTP_REASON_CHARS = 2048

_REQUEST_FIELDS = frozenset({"method", "url", "headers", "body", "timeout"})
_RESPONSE_FIELDS = frozenset(
    {"outcome", "status", "headers", "body", "body_encoding", "reason", "rule"}
)
_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9a-z]+$")
_HOSTNAME = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
)
_CONTROL = re.compile(r"[\x00-\x20\x7f]")


class HttpBrokerError(ValueError):
    """An HTTP request or response record is outside the admitted shape."""


def _exact(value: object, name: str, fields: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise HttpBrokerError(f"{name} must contain exactly {sorted(fields)!r}")
    return value


def _header_value(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_HTTP_HEADER_VALUE_CHARS
        or any(character in value for character in "\r\n\x00")
    ):
        raise HttpBrokerError(f"{name} must be single-line text")
    return value


def _url(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_HTTP_URL_CHARS
        or _CONTROL.search(value)
        or "\\" in value
    ):
        raise HttpBrokerError("HTTP url must be bounded text without whitespace")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as exc:
        raise HttpBrokerError("HTTP url is malformed") from exc
    if parts.scheme != "https":
        raise HttpBrokerError("HTTP url must use https")
    hostname = parts.hostname
    if (
        not hostname
        or parts.netloc != hostname
        or port is not None
        or parts.username is not None
        or parts.password is not None
        or not _HOSTNAME.fullmatch(hostname)
    ):
        raise HttpBrokerError(
            "HTTP url must name one lowercase hostname without port or userinfo"
        )
    if parts.fragment or "#" in value:
        raise HttpBrokerError("HTTP url must not carry a fragment")
    if not parts.path.startswith("/"):
        raise HttpBrokerError("HTTP url path must be absolute")
    segments = parts.path.split("/")[1:]
    if any(unquote(segment) in {".", ".."} for segment in segments):
        raise HttpBrokerError("HTTP url path must be normalized")
    if any("/" in unquote(segment) or "\\" in unquote(segment) for segment in segments):
        raise HttpBrokerError("HTTP url path must not encode separators")
    return value


def _request_headers(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or len(value) > MAX_HTTP_HEADERS:
        raise HttpBrokerError("HTTP request headers must be a bounded object")
    result: dict[str, str] = {}
    for name in sorted(value, key=str):
        if not isinstance(name, str) or not _HEADER_NAME.fullmatch(name):
            raise HttpBrokerError("HTTP request header names must be lowercase tokens")
        if name in FORBIDDEN_REQUEST_HEADERS:
            raise HttpBrokerError(f"HTTP request header {name!r} is host-owned")
        result[name] = _header_value(value[name], f"HTTP request header {name!r}")
    return result


def _timeout(value: object) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0.0 < float(value) <= MAX_HTTP_TIMEOUT_SECONDS
    ):
        raise HttpBrokerError(
            f"HTTP timeout must be absent or in (0, {MAX_HTTP_TIMEOUT_SECONDS}]"
        )
    return float(value)


def admit_http_request(value: object) -> dict[str, object]:
    """Admit one worker request record and return its canonical form."""

    record = _exact(value, "HTTP request", _REQUEST_FIELDS)
    method = record["method"]
    if method not in ADMITTED_METHODS:
        raise HttpBrokerError("HTTP method must be GET, HEAD, or POST")
    body = record["body"]
    if body is not None:
        if method != "POST":
            raise HttpBrokerError("only POST requests may carry a body")
        if not isinstance(body, str):
            raise HttpBrokerError("HTTP request body must be text")
        try:
            body.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise HttpBrokerError("HTTP request body must be UTF-8 text") from exc
    return {
        "method": method,
        "url": _url(record["url"]),
        "headers": _request_headers(record["headers"]),
        "body": body,
        "timeout": _timeout(record["timeout"]),
    }


def http_request_record(request: HttpTransportRequest) -> dict[str, object]:
    """Project one library request onto its admitted canonical record."""

    if not isinstance(request, HttpTransportRequest):
        raise TypeError("request must be an HttpTransportRequest")
    return admit_http_request(
        {
            "method": request.method,
            "url": request.url,
            "headers": dict(request.headers),
            "body": request.body,
            "timeout": request.timeout,
        }
    )


def _optional_token(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or _CONTROL.search(value):
        raise HttpBrokerError(f"{name} must be a non-empty token or null")
    return value


def _response_headers(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise HttpBrokerError("HTTP response headers must be an object")
    result: dict[str, str] = {}
    for name in sorted(value, key=str):
        if name not in ADMITTED_RESPONSE_HEADERS:
            raise HttpBrokerError(f"HTTP response header {name!r} is not admitted")
        result[name] = _header_value(value[name], f"HTTP response header {name!r}")
    return result


def admit_http_response(value: object) -> dict[str, object]:
    """Admit one host response record and return its canonical form.

    ``ok`` carries a status and optionally a body; ``oversize`` may carry the
    status and headers of the refused response but never a body; ``denied``
    and ``transport_error`` carry neither status, headers, nor body.  Every
    non-ok outcome carries a reason.
    """

    record = _exact(value, "HTTP response", _RESPONSE_FIELDS)
    outcome = record["outcome"]
    if outcome not in ADMITTED_HTTP_OUTCOMES:
        raise HttpBrokerError("HTTP response outcome is unknown")
    status = record["status"]
    if status is not None and (
        isinstance(status, bool)
        or not isinstance(status, int)
        or not 100 <= status <= 599
    ):
        raise HttpBrokerError("HTTP response status must be 100..599 or null")
    headers = _response_headers(record["headers"])
    body = record["body"]
    body_encoding = record["body_encoding"]
    reason = record["reason"]
    rule = _optional_token(record["rule"], "HTTP response rule")
    if (body is None) != (body_encoding is None):
        raise HttpBrokerError("HTTP body and body_encoding must be present together")
    if body is not None:
        if not isinstance(body, str) or body_encoding not in HTTP_BODY_ENCODINGS:
            raise HttpBrokerError("HTTP response body must be text with an encoding")
        if body_encoding == "base64":
            try:
                decoded = base64.b64decode(body.encode("ascii"), validate=True)
            except (UnicodeEncodeError, binascii.Error) as exc:
                raise HttpBrokerError("HTTP response body is not base64") from exc
            if base64.b64encode(decoded).decode("ascii") != body:
                raise HttpBrokerError("HTTP response base64 body is not canonical")
    if outcome == "ok":
        if status is None:
            raise HttpBrokerError("an ok HTTP response must carry a status")
        if reason is not None:
            raise HttpBrokerError("an ok HTTP response carries no reason")
        if 300 <= status < 400 and body is not None:
            raise HttpBrokerError("a redirect response carries no body")
    else:
        if body is not None:
            raise HttpBrokerError(f"an {outcome} HTTP response carries no body")
        if (
            not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > MAX_HTTP_REASON_CHARS
            or "\x00" in reason
        ):
            raise HttpBrokerError("a non-ok HTTP response must carry a bounded reason")
        if outcome != "oversize" and (status is not None or headers):
            raise HttpBrokerError(
                f"an {outcome} HTTP response carries no status or headers"
            )
    return {
        "outcome": outcome,
        "status": status,
        "headers": headers,
        "body": body,
        "body_encoding": body_encoding,
        "reason": reason,
        "rule": rule,
    }


def http_response_record(response: HttpTransportResponse) -> dict[str, object]:
    """Project one library response onto its admitted canonical record."""

    if not isinstance(response, HttpTransportResponse):
        raise TypeError("response must be an HttpTransportResponse")
    return admit_http_response(
        {
            "outcome": response.outcome,
            "status": response.status,
            "headers": dict(response.headers),
            "body": response.body,
            "body_encoding": response.body_encoding,
            "reason": response.reason,
            "rule": response.rule,
        }
    )


def http_transport_response(value: object) -> HttpTransportResponse:
    """Admit one response record and return the library's typed view of it."""

    record = admit_http_response(value)
    return HttpTransportResponse(
        outcome=record["outcome"],
        status=record["status"],
        headers=MappingProxyType(record["headers"]),
        body=record["body"],
        body_encoding=record["body_encoding"],
        reason=record["reason"],
        rule=record["rule"],
    )


def http_request_hash(value: object) -> Sha256Digest:
    """Hash the admitted worker request record (never the credential)."""

    if isinstance(value, HttpTransportRequest):
        return digest_record(http_request_record(value))
    return digest_record(admit_http_request(value))


def http_response_hash(value: object) -> Sha256Digest:
    """Hash the admitted response record exactly as returned to the worker."""

    if isinstance(value, HttpTransportResponse):
        return digest_record(http_response_record(value))
    return digest_record(admit_http_response(value))


__all__ = [
    "ADMITTED_HTTP_OUTCOMES",
    "ADMITTED_METHODS",
    "ADMITTED_RESPONSE_HEADERS",
    "FORBIDDEN_REQUEST_HEADERS",
    "HttpBrokerError",
    "MAX_HTTP_TIMEOUT_SECONDS",
    "admit_http_request",
    "admit_http_response",
    "http_request_hash",
    "http_request_record",
    "http_response_hash",
    "http_response_record",
    "http_transport_response",
]
