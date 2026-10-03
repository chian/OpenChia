"""Explicit, host-owned configuration for one Builder or Episode Run launch.

Configuration contains references to credentials, never credentials themselves.
Resolution reads only named sources and freezes values before the first call.
The returned public record is sufficient to repeat routing while obtaining a
current credential from the same reference.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit

from agent.duet_contracts import canonical_json
from agent.episode_contracts import Sha256Digest
from agent.secret_scope import load_env_file


class LaunchConfigurationError(ValueError):
    """A launch needs an explicit, resolvable model assignment."""


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise LaunchConfigurationError(f"{name} must be non-empty text")
    return value


def _fields(value: object, required: set[str], optional: set[str], name: str) -> dict:
    if not isinstance(value, Mapping):
        raise LaunchConfigurationError(f"{name} must be an object")
    missing = required - value.keys()
    unexpected = value.keys() - required - optional
    if missing or unexpected:
        raise LaunchConfigurationError(f"{name}: missing fields {sorted(missing)}; unexpected fields {sorted(unexpected)}")
    return dict(value)


def _endpoint(value: object) -> str:
    text = _text(value, "base_url")
    parsed = urlsplit(text)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise LaunchConfigurationError("base_url must be an HTTP(S) endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LaunchConfigurationError("base_url must keep credentials and query parameters out of the URL")
    return text.rstrip("/")


def read_launch_spec(path: str | Path) -> dict[str, Any]:
    """Read a selected launch file; relative project paths belong to that file."""
    source = Path(path).expanduser().resolve(strict=True)
    value = json.loads(source.read_text(encoding="utf-8-sig"))
    spec = validate_launch_spec(value)
    root = Path(spec["project_root"]).expanduser()
    spec["project_root"] = str((source.parent / root).resolve(strict=True))
    spec["source_file"] = str(source)
    return spec


def validate_launch_spec(value: object) -> dict[str, Any]:
    spec = _fields(value, {"project", "project_root", "env_files", "inherit_env", "routes", "bindings"}, {"source_file"}, "launch")
    for name in ("project", "project_root"):
        _text(spec[name], name)
    if "source_file" in spec:
        _text(spec["source_file"], "source_file")
    for name in ("env_files", "inherit_env"):
        if not isinstance(spec[name], list) or any(not isinstance(x, str) or not x for x in spec[name]):
            raise LaunchConfigurationError(f"{name} must be a list of names")
        if len(spec[name]) != len(set(spec[name])):
            raise LaunchConfigurationError(f"{name} contains duplicate entries")
    routes = spec["routes"]
    if not isinstance(routes, dict) or not routes:
        raise LaunchConfigurationError("routes must name at least one model configuration")
    for name, raw in routes.items():
        _text(name, "route name")
        route = _fields(raw, {"provider", "model", "base_url", "api_mode", "auth"}, {"reasoning", "fallbacks"}, f"route {name}")
        for key in ("provider", "model", "base_url", "api_mode"):
            val = route[key]
            if isinstance(val, Mapping):
                ref = _fields(val, {"env"}, set(), key)
                _text(ref["env"], key)
            else:
                _text(val, key)
        auth = _fields(route["auth"], {"kind"}, {"env", "account"}, "auth")
        if auth["kind"] not in {"env", "codex_login", "session", "none"}:
            raise LaunchConfigurationError("auth.kind must be env, codex_login, session, or none")
        expected = {"kind"} if auth["kind"] == "none" else {"kind", "account"}
        if auth["kind"] in {"env", "codex_login"}:
            expected.add("env")
        if set(auth) != expected:
            raise LaunchConfigurationError(f"{auth['kind']} auth requires {sorted(expected)}")
        for key in expected - {"kind"}:
            _text(auth[key], f"auth.{key}")
        reasoning = route.get("reasoning")
        if reasoning is not None:
            reasoning = _fields(reasoning, {"enabled", "effort"}, set(), "reasoning")
            if not isinstance(reasoning["enabled"], bool):
                raise LaunchConfigurationError("reasoning.enabled must be boolean")
            _text(reasoning["effort"], "reasoning.effort")
        fallbacks = route.get("fallbacks", [])
        if not isinstance(fallbacks, list) or any(not isinstance(x, str) or x not in routes or x == name for x in fallbacks):
            raise LaunchConfigurationError(f"route {name} has invalid fallbacks")
        if len(fallbacks) != len(set(fallbacks)):
            raise LaunchConfigurationError("fallbacks must name distinct routes in attempt order")
    bindings = _fields(spec["bindings"], {"default"}, {"roles", "episodes"}, "bindings")
    refs = [bindings["default"]]
    for group in ("roles", "episodes"):
        overrides = bindings.get(group, {})
        if not isinstance(overrides, dict):
            raise LaunchConfigurationError(f"bindings.{group} must be an object")
        for name, ref in overrides.items():
            _text(name, f"bindings.{group} name")
            if group == "roles" and name not in {
                "builder.planning", "builder.emission", "run",
                "episode_structured_json_reasoning", "episode_structured_json_fast",
                "episode_probability_reasoning", "episode_probability_fast",
            }:
                raise LaunchConfigurationError(f"unknown model call role {name}")
            refs.append(ref)
    if any(not isinstance(ref, str) or ref not in routes for ref in refs):
        raise LaunchConfigurationError("every binding must name a declared route")
    return json.loads(canonical_json(spec))


@dataclass(frozen=True)
class ResolvedLaunch:
    """Secret-bearing object stays in host memory; public_record is safe to store."""

    public_json: str
    credentials: Mapping[str, str | None] = field(repr=False, compare=False)
    configuration_hash: str = field(init=False)
    _bindings: Mapping = field(init=False, repr=False, compare=False)
    _route_chains: Mapping = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "credentials", MappingProxyType(dict(self.credentials)))
        object.__setattr__(self, "configuration_hash", Sha256Digest.of_bytes(self.public_json.encode()).value)
        spec = self.record["resolved_spec"]
        object.__setattr__(self, "_bindings", MappingProxyType({
            "default": spec["bindings"]["default"],
            "roles": MappingProxyType(spec["bindings"].get("roles", {})),
            "episodes": MappingProxyType(spec["bindings"].get("episodes", {})),
        }))
        object.__setattr__(self, "_route_chains", MappingProxyType({
            name: (name, *route.get("fallbacks", [])) for name, route in spec["routes"].items()
        }))

    @property
    def record(self) -> dict[str, Any]:
        return json.loads(self.public_json)

    def route_names(self, episode_local_id: str | None, role: str, task: str) -> tuple[str, ...]:
        bindings = self._bindings
        roles = bindings.get("roles", {})
        name = roles.get(role, roles.get(task, bindings["default"]))
        if role == "run":
            name = bindings.get("episodes", {}).get(episode_local_id, name)
        return self._route_chains[name]


def _codex_login_token(path: Path) -> str:
    """Read the operator-selected Codex login; Codex alone owns token rotation."""
    from openchia_cli.auth_codex import _codex_access_token_is_expiring

    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise LaunchConfigurationError(f"Cannot read Codex login file {path} ({type(exc).__name__})") from None
    if not isinstance(record, dict) or record.get("auth_mode") != "chatgpt":
        raise LaunchConfigurationError(f"Codex login file {path} must use ChatGPT authentication")
    tokens = record.get("tokens")
    token = tokens.get("access_token") if isinstance(tokens, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise LaunchConfigurationError(f"Codex login file {path} has no access token")
    if _codex_access_token_is_expiring(token, 0):
        raise LaunchConfigurationError(
            f"Codex access token in {path} has expired. Refresh that login in Codex, then start a new launch."
        )
    return token.strip()


def resolve_launch(spec: Mapping[str, Any], *, session_runtime: Mapping[str, Any] | None = None) -> ResolvedLaunch:
    """Snapshot explicit file/env inputs. No provider discovery or network calls."""
    spec = validate_launch_spec(spec)
    root = Path(spec["project_root"]).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise LaunchConfigurationError("project_root must be a directory")
    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    for name in spec["inherit_env"]:
        if name in os.environ:
            values[name] = os.environ[name]
            sources[name] = f"process_env:{name}"
    paths = []
    for raw in spec["env_files"]:
        path = (root / Path(raw).expanduser()).resolve(strict=True)
        # Fail on an unreadable declared source rather than treating it as an empty overlay.
        with path.open("rb"):
            pass
        for name, value in load_env_file(path).items():
            values[name] = value
            sources[name] = f"env_file:{path}:{name}"
        paths.append(str(path))
    resolved = json.loads(canonical_json(spec))
    resolved["project_root"] = str(root)
    resolved["env_files"] = paths
    provenance: dict[str, str] = {}
    credentials: dict[str, str | None] = {}
    codex_tokens: dict[Path, str] = {}
    for name, route in resolved["routes"].items():
        for key in ("provider", "model", "base_url", "api_mode"):
            val = route[key]
            if isinstance(val, dict):
                variable = val["env"]
                if variable not in values or not values[variable]:
                    raise LaunchConfigurationError(f"route {name}.{key}: explicit variable {variable} is unavailable")
                route[key] = values[variable]
                provenance[f"routes.{name}.{key}"] = sources[variable]
            else:
                provenance[f"routes.{name}.{key}"] = spec.get("source_file", "selected_launch")
        route["base_url"] = _endpoint(route["base_url"])
        if route["provider"] == "auto":
            raise LaunchConfigurationError("launch routes require a concrete provider")
        if route["api_mode"] not in {"chat_completions", "codex_responses", "anthropic_messages"}:
            raise LaunchConfigurationError(f"route {name}: unsupported explicit api_mode")
        auth = route["auth"]
        key = None
        source = "no_auth"
        if auth["kind"] == "env":
            variable = auth["env"]
            key = values.get(variable)
            if not key:
                raise LaunchConfigurationError(f"route {name}: credential reference {variable} is unavailable")
            source = sources[variable]
        elif auth["kind"] == "codex_login":
            from agent.codex_headers import is_official_codex_base_url

            if (route["provider"] != "openai-codex" or route["api_mode"] != "codex_responses"
                    or not is_official_codex_base_url(route["base_url"])):
                raise LaunchConfigurationError("codex_login requires the official Codex Responses endpoint")
            variable = auth["env"]
            if not values.get(variable) or not sources.get(variable, "").startswith("env_file:"):
                raise LaunchConfigurationError(
                    f"route {name}: {variable} must name a Codex login file in the workflow's explicit .env file"
                )
            path = (root / Path(values[variable]).expanduser()).resolve()
            if path not in codex_tokens:
                codex_tokens[path] = _codex_login_token(path)
            key = codex_tokens[path]
            source = f"{sources[variable]} -> codex_login:{path}"
        elif auth["kind"] == "session":
            runtime = session_runtime or {}
            for setting in ("provider", "base_url", "api_mode"):
                actual = runtime.get(setting)
                if setting == "base_url" and actual:
                    actual = _endpoint(actual)
                if actual != route[setting]:
                    raise LaunchConfigurationError(f"route {name}: session {setting} differs from selected route")
            key = runtime.get("api_key")
            if not isinstance(key, str) or not key:
                raise LaunchConfigurationError(f"route {name}: current session has no concrete credential")
            source = f"explicit_session_credential:{runtime.get('parent_session_id') or runtime.get('session_id') or 'unspecified'}"
        credentials[name] = key
        provenance[f"routes.{name}.auth"] = source
        provenance[f"routes.{name}.reasoning"] = (
            spec.get("source_file", "selected_launch") if "reasoning" in route else "episode_call_options"
        )
    # Values used as credentials cannot accidentally become public model/endpoint fields.
    public = {"requested_spec": spec, "resolved_spec": resolved, "sources": provenance}
    encoded = canonical_json(public)
    if any(secret and secret in encoded for secret in credentials.values()):
        raise LaunchConfigurationError("a credential value also appears in public launch settings")
    return ResolvedLaunch(encoded, credentials)
