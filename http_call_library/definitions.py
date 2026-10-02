"""Importable function objects used directly by Episode design modules."""

from __future__ import annotations

from types import MappingProxyType

from function_library import FunctionImplementation, LibraryFunction


_BOUNDARY = "episode_runtime.http_broker.ScopedHttpBroker"
_TIMEOUT_SCHEMA = {"type": "number", "exclusiveMinimum": 0, "maximum": 120}


HTTP_REQUEST = LibraryFunction(
    library="http_call_library",
    function_id="http_request",
    interface="http.request",
    description=(
        "Send one HTTP request to an endpoint the approved Episode's egress "
        "allowlist admits and return its typed status, headers, and body."
    ),
    implementation=FunctionImplementation(
        module="http_call_library.calls",
        symbol="http_request",
        is_async=True,
    ),
    input_type=(
        "method: str, url: str, *, headers: Mapping[str, str] | None, "
        "body: str | None, timeout: float | None"
    ),
    output_type="http_call_library.HttpResult | http_call_library.HttpFailure",
    effect=(
        "One read-only HTTPS exchange brokered by the host against the "
        "human-approved egress allowlist; the worker holds no network access "
        "or credential."
    ),
    failure_contract=(
        "Returns a typed HttpFailure for denied, oversize, transport-error, "
        "and non-2xx outcomes (redirects are never followed); raises "
        "HttpTransportUnavailable outside an isolated Run, and cancellation "
        "and invalid caller types still raise."
    ),
    provenance=MappingProxyType(
        {
            "implementation_owner": "http_call_library.calls.http_request",
            "client_boundary": _BOUNDARY,
            "endpoint_owner": "binding Episode egress_allowlist",
            "response_semantics_owner": "binding Episode",
            "parameter_schema": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["GET", "HEAD", "POST"],
                    },
                    "timeout": _TIMEOUT_SCHEMA,
                },
                "required": [],
                "additionalProperties": False,
            },
        }
    ),
)


HTTP_JSON = LibraryFunction(
    library="http_call_library",
    function_id="http_json",
    interface="http.json",
    description=(
        "Send one HTTP request with an optional JSON body to an endpoint the "
        "approved Episode's egress allowlist admits and parse the 2xx response "
        "body as JSON."
    ),
    implementation=FunctionImplementation(
        module="http_call_library.calls",
        symbol="http_json",
        is_async=True,
    ),
    input_type=(
        "method: str, url: str, *, headers: Mapping[str, str] | None, "
        "json_body: object, timeout: float | None"
    ),
    output_type=(
        "http_call_library.HttpJsonResult | http_call_library.HttpFailure"
    ),
    effect=(
        "One read-only HTTPS exchange brokered by the host against the "
        "human-approved egress allowlist; the worker holds no network access "
        "or credential."
    ),
    failure_contract=(
        "Returns a typed HttpFailure for denied, oversize, transport-error, "
        "non-2xx, and undecodable-JSON outcomes; raises "
        "HttpTransportUnavailable outside an isolated Run, and cancellation "
        "and invalid caller types still raise."
    ),
    provenance=MappingProxyType(
        {
            "implementation_owner": "http_call_library.calls.http_json",
            "client_boundary": _BOUNDARY,
            "endpoint_owner": "binding Episode egress_allowlist",
            "response_semantics_owner": "binding Episode",
            "parameter_schema": {
                "type": "object",
                "properties": {
                    "method": {"type": "string", "enum": ["GET", "POST"]},
                    "timeout": _TIMEOUT_SCHEMA,
                },
                "required": [],
                "additionalProperties": False,
            },
        }
    ),
)


__all__ = ["HTTP_JSON", "HTTP_REQUEST"]
