"""Reusable brokered HTTP call mechanics with no Episode-specific content."""

from __future__ import annotations

import json
from typing import Mapping

from .contracts import (
    HttpFailure,
    HttpFailureKind,
    HttpJsonResult,
    HttpResult,
    _content,
)
from .transport import (
    HttpTransportRequest,
    HttpTransportResponse,
    HttpTransportUnavailable,
    call_http_transport,
)


_OUTCOME_FAILURES = {
    "denied": HttpFailureKind.HTTP_DENIED,
    "transport_error": HttpFailureKind.HTTP_TRANSPORT,
    "oversize": HttpFailureKind.HTTP_OVERSIZE,
}


def _failure(
    kind: HttpFailureKind,
    message: str,
    response: HttpTransportResponse | None = None,
) -> HttpFailure:
    if response is None:
        return HttpFailure(kind=kind, message=message)
    return HttpFailure(
        kind=kind,
        message=message,
        status=response.status,
        rule=response.rule,
        headers=response.headers,
        body=response.body,
        body_encoding=response.body_encoding,
    )


async def _exchange(
    request: HttpTransportRequest,
) -> HttpTransportResponse | HttpFailure:
    try:
        response = await call_http_transport(request)
    except HttpTransportUnavailable:
        raise
    except (TypeError, ValueError) as exc:
        # The boundary refused to forward the request (scheme, header, method,
        # body, timeout, or frame-size admission).
        return _failure(HttpFailureKind.HTTP_DENIED, f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        return _failure(
            HttpFailureKind.HTTP_TRANSPORT, f"{type(exc).__name__}: {exc}"
        )
    kind = _OUTCOME_FAILURES.get(response.outcome)
    if kind is not None:
        return _failure(
            kind,
            response.reason or f"HTTP request outcome {response.outcome}",
            response,
        )
    if response.status is None or not 200 <= response.status < 300:
        return _failure(
            HttpFailureKind.HTTP_STATUS,
            f"HTTP status {response.status}",
            response,
        )
    return response


async def http_request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    body: str | None = None,
    timeout: float | None = None,
) -> HttpResult | HttpFailure:
    """Send one brokered HTTP request and return its typed outcome.

    Only a 2xx response is an ``HttpResult``; every other outcome, including a
    non-2xx status (redirects are never followed), is an ``HttpFailure``
    carrying the admitted status, headers, and body.
    """

    request = HttpTransportRequest(
        method=method,
        url=url,
        headers={} if headers is None else headers,
        body=body,
        timeout=timeout,
    )
    outcome = await _exchange(request)
    if isinstance(outcome, HttpFailure):
        return outcome
    return HttpResult(
        status=outcome.status,
        headers=outcome.headers,
        body=outcome.body,
        body_encoding=outcome.body_encoding,
        rule=outcome.rule,
    )


async def http_json(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    json_body: object = None,
    timeout: float | None = None,
) -> HttpJsonResult | HttpFailure:
    """Send one brokered request and parse its 2xx response body as JSON."""

    request_headers = {} if headers is None else dict(headers)
    request_headers.setdefault("accept", "application/json")
    body: str | None = None
    if json_body is not None:
        body = json.dumps(
            json_body,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        request_headers.setdefault("content-type", "application/json")
    request = HttpTransportRequest(
        method=method,
        url=url,
        headers=request_headers,
        body=body,
        timeout=timeout,
    )
    outcome = await _exchange(request)
    if isinstance(outcome, HttpFailure):
        return outcome
    try:
        content = _content(outcome.body, outcome.body_encoding)
        if content is None:
            raise ValueError("HTTP response has no body")
        raw_body = content.decode("utf-8")
        value = json.loads(raw_body)
    except (UnicodeDecodeError, ValueError) as exc:
        return _failure(
            HttpFailureKind.HTTP_DECODE,
            f"{type(exc).__name__}: {exc}",
            outcome,
        )
    return HttpJsonResult(
        status=outcome.status,
        headers=outcome.headers,
        value=value,
        raw_body=raw_body,
        rule=outcome.rule,
    )


__all__ = ["http_json", "http_request"]
