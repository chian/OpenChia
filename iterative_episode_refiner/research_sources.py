"""Read-only instruments for Question and Support's evidence-gathering loops.

The host supplies the owning Duet's profile; the model supplies only a typed
query, URL, or library source handle. Results are untrusted data for the host
to persist and the leaf to synthesize, never new instructions or executable
callbacks. No arbitrary file reader or Target Workflow write capability is
exposed here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import contextmanager
import hashlib
import ipaddress
import json
from pathlib import Path
import socket
from urllib.parse import unquote, urlsplit


_LIBRARY_ROOTS = (
    "docs/openchia", "docs/adr", "episode_library", "function_library",
    "numeric_control_library", "llm_call_library", "handoff_library",
    "http_call_library", "method_loop",
)
_ARGUMENTS = {
    "web_search": "query",
    "read_url": "url",
    "library_search": "query",
    "read_library": "source_id",
}


@contextmanager
def _owner_scope(profile_home: Path):
    from agent.secret_scope import (
        build_profile_secret_scope, reset_secret_scope, set_secret_scope,
    )
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    if not profile_home.is_absolute():
        raise ValueError("research requires the owning Duet's absolute profile home")
    home_token = set_hermes_home_override(profile_home)
    try:
        secrets = build_profile_secret_scope(profile_home)
        secret_token = set_secret_scope(secrets, profile_home=str(profile_home))
        try:
            yield secrets
        finally:
            reset_secret_scope(secret_token)
    finally:
        reset_hermes_home_override(home_token)


def _secret_values(secrets):
    return tuple(
        value for key, value in secrets.items()
        if isinstance(value, str) and len(value) >= 8
        and any(token in key.upper() for token in ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH", "CREDENTIAL"))
    )


def _outbound_text(value, secrets):
    """Refuse credential-bearing requests before a third party receives them."""
    from agent.redact import redact_for_egress

    decoded = unquote(value)
    if any(
        redact_for_egress(text) != text
        or any(secret in text for secret in _secret_values(secrets))
        for text in (value, decoded)
    ):
        raise ValueError("research request contains credential material")
    return value


def _clean_text(value, secrets, *, source_code=False):
    from agent.redact import redact_sensitive_text

    text = value if isinstance(value, str) else ""
    for secret in _secret_values(secrets):
        text = text.replace(secret, "[redacted credential]")
    return redact_sensitive_text(text, force=True, code_file=source_code)


def _source(*, kind, title, content, secrets, url=None, path=None):
    clean = _clean_text(content, secrets, source_code=kind == "library")
    identity = f"library:{path}" if path else "web:" + hashlib.sha256(url.encode("utf-8")).hexdigest()
    return {
        "source_id": identity,
        "kind": kind,
        "title": _clean_text(title or path or url, secrets),
        "url": _clean_text(url, secrets) if url else None,
        "path": path,
        "content": clean,
        "content_hash": hashlib.sha256(clean.encode("utf-8")).hexdigest(),
        "truncated": "[TRUNCATED]" in clean,
        "redacted": clean != content,
    }


def _library_paths():
    """Build handles from declared library roots, excluding hidden/symlink paths."""
    root = Path(__file__).resolve().parent.parent
    result = {}
    for name in _LIBRARY_ROOTS:
        directory = root / name
        if not directory.is_dir() or directory.is_symlink():
            continue
        for path in sorted(directory.rglob("*")):
            relative = path.relative_to(root)
            if path.suffix not in {".py", ".md"} or not path.is_file():
                continue
            if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
                continue
            # A symlink anywhere in the relative path is a file-read escape,
            # even if the final component itself is an ordinary file.
            if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root):
                continue
            if path.resolve().is_relative_to(directory.resolve()):
                result[f"library:{relative.as_posix()}"] = path
    return result


async def _library_search(query, secrets):
    terms = set(query.casefold().replace("_", " ").replace(".", " ").split())
    rows = []
    for source_id, path in _library_paths().items():
        content = path.read_text(encoding="utf-8-sig")
        searchable = (source_id + "\n" + content).casefold()
        score = sum(term in searchable for term in terms)
        if score:
            name_score = sum(term in source_id.casefold() for term in terms)
            rows.append((name_score, score, source_id, content))
    rows.sort(key=lambda item: (-item[0], -item[1], item[2]))
    sources = []
    for name_score, score, source_id, content in rows[:20]:
        first_match = next(
            (line.strip() for line in content.splitlines() if any(term in line.casefold() for term in terms)),
            "",
        )
        source = _source(
            kind="library", title=source_id.removeprefix("library:"),
            content=first_match[:500], path=source_id.removeprefix("library:"), secrets=secrets,
        )
        source.update({"search_excerpt": True, "truncated": True, "matched_terms": score})
        sources.append(source)
    return {"success": True, "sources": sources, "total_matches": len(rows), "error": None}


async def _read_library(source_id, secrets):
    path = _library_paths().get(source_id)
    if path is None:
        raise ValueError("read_library requires a source_id from the declared library catalog")
    content = path.read_text(encoding="utf-8-sig")
    source = _source(
        kind="library", title=source_id.removeprefix("library:"), content=content,
        path=source_id.removeprefix("library:"), secrets=secrets,
    )
    return {"success": True, "sources": [source], "error": None}


async def _web_search(query, secrets):
    from tools.web_tools import web_search_tool

    result = json.loads(await asyncio.to_thread(web_search_tool, _outbound_text(query, secrets)))
    sources = [
        _source(
            kind="web_search", title=item.get("title", ""),
            content=item.get("description", ""), url=item["url"], secrets=secrets,
        )
        for item in result.get("data", {}).get("web", ())
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    ]
    return {
        "success": bool(result.get("success")), "sources": sources,
        "error": _clean_text(result.get("error"), secrets) or None,
    }


async def _read_url(url, secrets):
    from tools.web_tools import web_extract_tool

    _outbound_text(url, secrets)
    parsed = urlsplit(url)
    # The general web tool permits operator-approved intranet browsing. These
    # external-evidence leaves have a narrower public-network capability.
    addresses = await asyncio.to_thread(
        socket.getaddrinfo, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80),
        type=socket.SOCK_STREAM,
    )
    if not addresses or any(
        not ipaddress.ip_address(address[4][0].split("%")[0]).is_global
        for address in addresses
    ):
        raise ValueError("research URL resolves to a non-public network address")
    # The shared extractor owns SSRF, website policy, provider resolution and
    # retrieval caching; this leaf receives only the result, not a file tool.
    result = json.loads(await web_extract_tool([url], format="markdown"))
    sources = []
    failures = []
    for item in result.get("results", ()):
        if item.get("error"):
            failures.append(_clean_text(item["error"], secrets))
        elif item.get("content"):
            sources.append(_source(
                kind="web_page", title=item.get("title", ""),
                content=item["content"], url=item.get("url") or url, secrets=secrets,
            ))
    return {
        "success": bool(sources), "sources": sources,
        "error": "; ".join(failures) or _clean_text(result.get("error"), secrets) or None,
    }


_OPERATIONS = {
    "web_search": _web_search, "read_url": _read_url,
    "library_search": _library_search, "read_library": _read_library,
}


def validate_request(operation: str, arguments: Mapping) -> None:
    """Admit the exact read-only request before the host records or executes it."""
    if operation == "read_candidate":
        if not isinstance(arguments, Mapping) or set(arguments) != {"local_id", "section"}:
            raise ValueError("read_candidate requires exactly local_id and section")
        local_id = arguments["local_id"]
        if not isinstance(local_id, str) or not local_id.strip() or "\x00" in local_id:
            raise ValueError("local_id must name an approved Target Workflow Episode")
        if arguments["section"] not in ("architecture", "materialization", "source"):
            raise ValueError("read_candidate section must be architecture, materialization or source")
        return
    if not isinstance(operation, str) or operation not in _OPERATIONS:
        raise ValueError("unknown research operation")
    field = _ARGUMENTS[operation]
    if not isinstance(arguments, Mapping) or set(arguments) != {field}:
        raise ValueError(f"{operation} requires exactly {field}")
    value = arguments[field]
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{field} must be nonempty text")
    if operation in {"web_search", "read_url"}:
        _outbound_text(value, {})
    if operation == "read_url":
        from tools.url_safety import sensitive_query_param_name

        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("read_url requires a public HTTP(S) URL")
        if parsed.username or parsed.password or sensitive_query_param_name(value):
            raise ValueError("read_url accepts public URLs without embedded credentials")


async def retrieve(operation: str, arguments: Mapping, *, profile_home: Path) -> dict:
    """Perform one leaf instrument call; the caller owns evidence persistence."""
    validate_request(operation, arguments)
    value = arguments[_ARGUMENTS[operation]]
    with _owner_scope(Path(profile_home)) as secrets:
        try:
            result = await _OPERATIONS[operation](value, secrets)
        except Exception as exc:
            # Instrument failure is evidence for the Episode's next choice;
            # cancellation remains a control signal (BaseException).
            result = {
                "success": False, "sources": [], "error_type": type(exc).__name__,
                "error": _clean_text(str(exc), secrets),
            }
    return {"operation": operation, **result}
