"""Host-owned HTTP broker: the only network path out of an Episode Run.

HOST-ONLY.  This module is never staged into the isolated worker (it is not
in ``identity._SELECTED_LOCAL_SOURCES``): it reads host credential files and
dials the network.  The worker sends an admitted request record over the
frame pipe; this broker applies the human-approved ``egress_policy`` of the
requesting Episode node, the per-rule budgets, and the response caps, adds the
operator-held credential to the outgoing request only, and returns a typed,
admitted response record.  Policy outcomes (``denied``, ``transport_error``,
``oversize``) are records, never exceptions; only a request outside the
admitted shape raises ``HttpBrokerError`` (a protocol violation).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from typing import Any, Mapping, Optional, Protocol, runtime_checkable
from urllib.parse import urlsplit

from agent.episode_contracts import (
    EpisodeEgressRule,
    validate_egress_host,
    validate_egress_name,
)

from .http_contracts import (
    ADMITTED_RESPONSE_HEADERS,
    MAX_HTTP_REASON_CHARS,
    MAX_HTTP_TIMEOUT_SECONDS,
    HttpBrokerError,
    admit_http_request,
    admit_http_response,
)


DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0
# D7: the response cap leaves this much of the frame for the envelope.
HTTP_FRAME_OVERHEAD_BYTES = 131_072
# The serialized response record must leave this much for the frame envelope
# (ids, hashes, sequence); base64 and JSON escaping can grow a body past its
# raw byte cap, so the encoded size is checked as well.
_FRAME_ENVELOPE_RESERVE_BYTES = 16_384
MAX_CREDENTIAL_FILE_BYTES = 65_536
CREDENTIAL_KINDS = frozenset({"bearer_token_file"})

_HEADER_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_SCHEME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]*$")
_CREDENTIAL_HEADER_FORBIDDEN = frozenset(
    {"host", "content-length", "transfer-encoding", "connection"}
)
_CREDENTIAL_FIELDS = frozenset({"kind", "path", "header", "scheme"})
_EGRESS_FIELDS = frozenset({"allowed_hosts", "credentials"})
_MAX_RESPONSE_HEADER_VALUE_CHARS = 8192


class ResponseTooLarge(Exception):
    """The upstream response body exceeded the broker's byte cap."""

    def __init__(
        self,
        status: Optional[int],
        headers: Mapping[str, str],
        message: str = "response body exceeds its byte cap",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.headers = dict(headers)


@dataclass(frozen=True, kw_only=True)
class CredentialSpec:
    """One operator-held credential a rule may name; the secret stays in a file."""

    name: str
    kind: str = "bearer_token_file"
    path: Path
    header: str = "Authorization"
    scheme: str = "Bearer"

    def __post_init__(self) -> None:
        validate_egress_name(self.name, "egress credential name")
        if self.kind not in CREDENTIAL_KINDS:
            raise ValueError(
                f"egress credential {self.name!r} kind {self.kind!r} is unknown; "
                f"allowed: {sorted(CREDENTIAL_KINDS)!r}"
            )
        if not isinstance(self.path, (str, Path)) or not str(self.path):
            raise ValueError(f"egress credential {self.name!r} needs a file path")
        path = Path(self.path).expanduser()
        if not path.is_absolute():
            raise ValueError(
                f"egress credential {self.name!r} path must be absolute or start with ~"
            )
        object.__setattr__(self, "path", path)
        if (
            not isinstance(self.header, str)
            or not _HEADER_NAME.fullmatch(self.header)
            or self.header.lower() in _CREDENTIAL_HEADER_FORBIDDEN
        ):
            raise ValueError(
                f"egress credential {self.name!r} header must be an HTTP header name"
            )
        if not isinstance(self.scheme, str) or not _SCHEME.fullmatch(self.scheme):
            raise ValueError(
                f"egress credential {self.name!r} scheme must be a token or empty"
            )


def load_egress_config(
    config: Mapping[str, Any] | None,
) -> tuple[tuple[str, ...], Mapping[str, CredentialSpec]]:
    """Parse the operator's ``openchia.egress`` block.

    Returns the sorted allowed hostnames and the credentials by name.  A
    missing block is the closed default: no hosts, no credentials.
    """

    if config is None:
        return (), MappingProxyType({})
    if not isinstance(config, Mapping):
        raise ValueError("config must be a mapping")
    openchia = config.get("openchia")
    if openchia is None:
        return (), MappingProxyType({})
    if not isinstance(openchia, Mapping):
        raise ValueError("openchia config must be a mapping")
    egress = openchia.get("egress")
    if egress is None:
        return (), MappingProxyType({})
    if not isinstance(egress, Mapping):
        raise ValueError("openchia.egress must be a mapping")
    unknown = set(egress) - _EGRESS_FIELDS
    if unknown:
        raise ValueError(f"openchia.egress has unknown keys {sorted(map(str, unknown))!r}")
    raw_hosts = egress.get("allowed_hosts") or ()
    if isinstance(raw_hosts, (str, bytes)) or not isinstance(raw_hosts, (list, tuple)):
        raise ValueError("openchia.egress.allowed_hosts must be a list of hostnames")
    hosts = tuple(
        sorted(
            {
                validate_egress_host(item, "openchia.egress.allowed_hosts entry")
                for item in raw_hosts
            }
        )
    )
    raw_credentials = egress.get("credentials") or {}
    if not isinstance(raw_credentials, Mapping):
        raise ValueError("openchia.egress.credentials must be a mapping")
    credentials: dict[str, CredentialSpec] = {}
    for name in sorted(raw_credentials, key=str):
        validate_egress_name(name, "openchia.egress credential name")
        entry = raw_credentials[name]
        if not isinstance(entry, Mapping):
            raise ValueError(f"openchia.egress.credentials.{name} must be a mapping")
        extra = set(entry) - _CREDENTIAL_FIELDS
        if extra:
            raise ValueError(
                f"openchia.egress.credentials.{name} has unknown keys "
                f"{sorted(map(str, extra))!r}"
            )
        if "path" not in entry:
            raise ValueError(f"openchia.egress.credentials.{name} needs a path")
        path = entry["path"]
        if not isinstance(path, str) or not path:
            raise ValueError(f"openchia.egress.credentials.{name}.path must be text")
        credentials[name] = CredentialSpec(
            name=name,
            kind=entry.get("kind", "bearer_token_file"),
            path=Path(path),
            header=entry.get("header", "Authorization"),
            scheme=entry.get("scheme", "Bearer"),
        )
    return hosts, MappingProxyType(credentials)


@runtime_checkable
class HostHttpTransport(Protocol):
    """One outgoing HTTPS exchange; tests inject a fake instead of the network.

    Returns ``(status, headers, body_bytes)`` and raises ``ResponseTooLarge``
    when the body would exceed ``max_response_bytes``.
    """

    async def __call__(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Optional[bytes],
        timeout: float,
        max_response_bytes: int,
    ) -> tuple[int, Mapping[str, str], bytes]: ...


def _admitted_headers(headers: object) -> dict[str, str]:
    """Project upstream headers onto the admitted, lowercase, single-line set."""

    result: dict[str, str] = {}
    if headers is None:
        return result
    items = headers.items() if hasattr(headers, "items") else headers
    for name, value in items:  # type: ignore[union-attr]
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        lowered = name.lower()
        if lowered not in ADMITTED_RESPONSE_HEADERS:
            continue
        if any(character in value for character in "\r\n\x00"):
            continue
        combined = value if lowered not in result else f"{result[lowered]}, {value}"
        if len(combined) > _MAX_RESPONSE_HEADER_VALUE_CHARS:
            continue
        result[lowered] = combined
    return result


@dataclass(frozen=True)
class HttpxHostTransport:
    """SSRF-safe httpx transport: no redirects, no env proxies or netrc, bounded body."""

    async def __call__(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: Optional[bytes],
        timeout: float,
        max_response_bytes: int,
    ) -> tuple[int, Mapping[str, str], bytes]:
        from tools.url_safety import create_ssrf_safe_async_client

        async with create_ssrf_safe_async_client(
            follow_redirects=False,
            timeout=timeout,
            trust_env=False,
        ) as client, client.stream(
            method,
            url,
            headers=dict(headers),
            content=body,
        ) as response:
            status = int(response.status_code)
            raw_headers = list(response.headers.multi_items())
            admitted = _admitted_headers(raw_headers)
            if response.headers.get("content-encoding"):
                # The streamed body is decoded; the wire length would mislead.
                admitted.pop("content-length", None)
            declared = response.headers.get("content-length")
            try:
                declared_size = int(declared) if declared else None
            except ValueError:
                declared_size = None
            if declared_size is not None and declared_size > max_response_bytes:
                raise ResponseTooLarge(status, admitted)
            if method == "HEAD":
                return status, admitted, b""
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_response_bytes:
                    raise ResponseTooLarge(status, admitted)
                chunks.append(chunk)
            return status, admitted, b"".join(chunks)


def _path_prefix_matches(prefix: str, path: str) -> bool:
    if prefix.endswith("/"):
        return path.startswith(prefix)
    if path == prefix:
        return True
    return path.startswith(prefix) and path[len(prefix)] in "/?"


def _reason(text: str, *, secret: Optional[str] = None) -> str:
    if secret:
        text = text.replace(secret, "[redacted]")
    cleaned = " ".join(text.replace("\x00", " ").split())
    if len(cleaned) > MAX_HTTP_REASON_CHARS:
        cleaned = cleaned[: MAX_HTTP_REASON_CHARS - 3] + "..."
    return cleaned or "HTTP request failed"


def _status(value: object) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 100 <= value <= 599 else None


def _record(
    outcome: str,
    *,
    rule: Optional[EpisodeEgressRule],
    reason: Optional[str] = None,
    status: Optional[int] = None,
    headers: Optional[Mapping[str, str]] = None,
    body: Optional[str] = None,
    body_encoding: Optional[str] = None,
) -> dict[str, object]:
    return admit_http_response(
        {
            "outcome": outcome,
            "status": status,
            "headers": dict(headers or {}),
            "body": body,
            "body_encoding": body_encoding,
            "reason": reason,
            "rule": None if rule is None else rule.name,
        }
    )


class _CredentialUnavailable(Exception):
    pass


def _read_credential(spec: CredentialSpec) -> str:
    """Read the token at call time; failures never reveal the file contents."""

    try:
        descriptor = os.open(spec.path, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError as exc:
        raise _CredentialUnavailable("its file does not exist") from exc
    except OSError as exc:
        raise _CredentialUnavailable("its file cannot be opened") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise _CredentialUnavailable("its file is not a regular file")
        if info.st_size > MAX_CREDENTIAL_FILE_BYTES:
            raise _CredentialUnavailable(
                f"its file exceeds {MAX_CREDENTIAL_FILE_BYTES} bytes"
            )
        chunks: list[bytes] = []
        size = 0
        while True:
            try:
                chunk = os.read(descriptor, 8192)
            except OSError as exc:
                raise _CredentialUnavailable("its file cannot be read") from exc
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_CREDENTIAL_FILE_BYTES:
                raise _CredentialUnavailable(
                    f"its file exceeds {MAX_CREDENTIAL_FILE_BYTES} bytes"
                )
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    try:
        token = b"".join(chunks).decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise _CredentialUnavailable("its file is not UTF-8 text") from exc
    if not token:
        raise _CredentialUnavailable("its file is empty")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in token):
        raise _CredentialUnavailable("its token is not a single header-safe line")
    return token


def _frozen_policy(
    policy: Mapping[str, tuple[EpisodeEgressRule, ...]],
) -> Mapping[str, tuple[EpisodeEgressRule, ...]]:
    if not isinstance(policy, Mapping):
        raise TypeError("policy must be a mapping of local_id to rules")
    frozen: dict[str, tuple[EpisodeEgressRule, ...]] = {}
    for local_id, rules in policy.items():
        if not isinstance(local_id, str) or not local_id:
            raise TypeError("policy keys must be Episode local_ids")
        rules = tuple(rules)
        if any(not isinstance(rule, EpisodeEgressRule) for rule in rules):
            raise TypeError("policy values must contain EpisodeEgressRule values")
        frozen[local_id] = rules
    return MappingProxyType(frozen)


class ScopedHttpBroker:
    """Apply one Run's approved egress policy to admitted worker requests.

    The credential token is read per call, placed on the outgoing headers
    only, and never enters the returned record, an exception, or a log.
    """

    def __init__(
        self,
        *,
        policy: Mapping[str, tuple[EpisodeEgressRule, ...]],
        credentials: Mapping[str, CredentialSpec],
        transport: HostHttpTransport,
        max_frame_bytes: int,
    ) -> None:
        self.policy = _frozen_policy(policy)
        if not isinstance(credentials, Mapping) or any(
            not isinstance(spec, CredentialSpec) or spec.name != name
            for name, spec in credentials.items()
        ):
            raise TypeError("credentials must map names to their CredentialSpec")
        self.credentials = MappingProxyType(dict(credentials))
        if not callable(transport):
            raise TypeError("transport must implement HostHttpTransport")
        self.transport = transport
        if (
            isinstance(max_frame_bytes, bool)
            or not isinstance(max_frame_bytes, int)
            or max_frame_bytes < 1024
        ):
            raise ValueError("max_frame_bytes must be an integer >= 1024")
        self.max_frame_bytes = max_frame_bytes
        self._counts: dict[tuple[str, str], int] = {}

    def request_count(self, local_id: str, rule_name: str) -> int:
        return self._counts.get((local_id, rule_name), 0)

    def _match(
        self,
        local_id: str,
        request: Mapping[str, object],
    ) -> Optional[EpisodeEgressRule]:
        parts = urlsplit(str(request["url"]))
        host = parts.hostname
        path = parts.path
        method = request["method"]
        for rule in self.policy.get(local_id, ()):
            if (
                rule.read_only is True
                and rule.host == host
                and _path_prefix_matches(rule.path_prefix, path)
                and method in rule.methods
            ):
                return rule
        return None

    def match_rule(
        self,
        local_id: str,
        request: object,
    ) -> Optional[EpisodeEgressRule]:
        """The first rule of ``local_id`` admitting ``request``, or ``None``."""

        return self._match(local_id, admit_http_request(request))

    def _response_cap(self, rule: EpisodeEgressRule) -> int:
        return max(
            0,
            min(
                rule.max_response_bytes,
                self.max_frame_bytes - HTTP_FRAME_OVERHEAD_BYTES,
            ),
        )

    def _fits_frame(self, record: Mapping[str, object]) -> bool:
        encoded = json.dumps(
            record,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return len(encoded) <= self.max_frame_bytes - _FRAME_ENVELOPE_RESERVE_BYTES

    async def __call__(
        self,
        *,
        local_id: str,
        request: object,
    ) -> dict[str, object]:
        record = admit_http_request(request)
        method = str(record["method"])
        parts = urlsplit(str(record["url"]))
        rule = self._match(local_id, record)
        if rule is None:
            return _record(
                "denied",
                rule=None,
                reason=_reason(
                    f"no egress rule admits {method} {parts.hostname}{parts.path}"
                ),
            )
        key = (local_id, rule.name)
        used = self._counts.get(key, 0)
        if used >= rule.max_requests:
            return _record(
                "denied",
                rule=rule,
                reason=(
                    f"egress rule {rule.name!r} exhausted its budget of "
                    f"{rule.max_requests} requests"
                ),
            )
        self._counts[key] = used + 1

        headers = dict(record["headers"])  # type: ignore[arg-type]
        token: Optional[str] = None
        if rule.credential is not None:
            spec = self.credentials.get(rule.credential)
            if spec is None:
                return _record(
                    "denied",
                    rule=rule,
                    reason=(
                        f"egress credential {rule.credential!r} is not configured "
                        "on this host"
                    ),
                )
            try:
                token = _read_credential(spec)
            except _CredentialUnavailable as exc:
                return _record(
                    "denied",
                    rule=rule,
                    reason=f"egress credential {spec.name!r} is unavailable: {exc}",
                )
            headers[spec.header.lower()] = (
                f"{spec.scheme} {token}" if spec.scheme else token
            )

        timeout_value = record["timeout"]
        timeout = (
            DEFAULT_HTTP_TIMEOUT_SECONDS
            if timeout_value is None
            else float(timeout_value)  # type: ignore[arg-type]
        )
        if not math.isfinite(timeout) or timeout <= 0.0:
            timeout = DEFAULT_HTTP_TIMEOUT_SECONDS
        timeout = min(timeout, MAX_HTTP_TIMEOUT_SECONDS)
        cap = self._response_cap(rule)
        body = record["body"]
        try:
            status_value, raw_headers, payload = await self.transport(
                method=method,
                url=str(record["url"]),
                headers=headers,
                body=None if body is None else str(body).encode("utf-8"),
                timeout=timeout,
                max_response_bytes=cap,
            )
        except ResponseTooLarge as exc:
            return _record(
                "oversize",
                rule=rule,
                status=_status(exc.status),
                headers=_admitted_headers(exc.headers),
                reason=f"response body exceeds the {cap}-byte cap",
            )
        except Exception as exc:
            return _record(
                "transport_error",
                rule=rule,
                reason=_reason(f"{type(exc).__name__}: {exc}", secret=token),
            )

        status = _status(status_value)
        if status is None:
            return _record(
                "transport_error",
                rule=rule,
                reason="upstream returned an invalid HTTP status",
            )
        admitted = _admitted_headers(raw_headers)
        if not isinstance(payload, (bytes, bytearray)):
            return _record(
                "transport_error",
                rule=rule,
                reason="host transport returned a non-bytes body",
            )
        if method == "HEAD" or 300 <= status < 400:
            return _record("ok", rule=rule, status=status, headers=admitted)
        if len(payload) > cap:
            return _record(
                "oversize",
                rule=rule,
                status=status,
                headers=admitted,
                reason=f"response body exceeds the {cap}-byte cap",
            )
        try:
            text = bytes(payload).decode("utf-8", errors="strict")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text = base64.b64encode(bytes(payload)).decode("ascii")
            encoding = "base64"
        response = _record(
            "ok",
            rule=rule,
            status=status,
            headers=admitted,
            body=text,
            body_encoding=encoding,
        )
        if not self._fits_frame(response):
            return _record(
                "oversize",
                rule=rule,
                status=status,
                headers=admitted,
                reason="encoded response exceeds the protocol frame bound",
            )
        return response


def http_response_bytes(response: Mapping[str, object]) -> int:
    """Byte length of a response record's body (decoded base64; 0 when null)."""

    body = response.get("body")
    if body is None:
        return 0
    if response.get("body_encoding") == "base64":
        return len(base64.b64decode(str(body).encode("ascii"), validate=True))
    return len(str(body).encode("utf-8"))


__all__ = [
    "CREDENTIAL_KINDS",
    "CredentialSpec",
    "DEFAULT_HTTP_TIMEOUT_SECONDS",
    "HTTP_FRAME_OVERHEAD_BYTES",
    "HostHttpTransport",
    "HttpBrokerError",
    "HttpxHostTransport",
    "MAX_CREDENTIAL_FILE_BYTES",
    "ResponseTooLarge",
    "ScopedHttpBroker",
    "http_response_bytes",
    "load_egress_config",
]
