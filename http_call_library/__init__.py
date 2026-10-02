"""Reusable, typed, host-brokered HTTP call mechanics for Episodes."""

from .calls import http_json, http_request
from .contracts import (
    HttpFailure,
    HttpFailureKind,
    HttpJsonResult,
    HttpResult,
)
from .definitions import HTTP_JSON, HTTP_REQUEST
from .transport import (
    HTTP_BODY_ENCODINGS,
    HTTP_OUTCOMES,
    HttpTransport,
    HttpTransportRequest,
    HttpTransportResponse,
    HttpTransportUnavailable,
    call_http_transport,
    http_transport_scope,
)


__all__ = [
    "HTTP_BODY_ENCODINGS",
    "HTTP_JSON",
    "HTTP_OUTCOMES",
    "HTTP_REQUEST",
    "HttpFailure",
    "HttpFailureKind",
    "HttpJsonResult",
    "HttpResult",
    "HttpTransport",
    "HttpTransportRequest",
    "HttpTransportResponse",
    "HttpTransportUnavailable",
    "call_http_transport",
    "http_json",
    "http_request",
    "http_transport_scope",
]
