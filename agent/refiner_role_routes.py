"""Per-role model and reasoning for the refiner's calls on the owning Duet's binding.

By default every refiner call uses the owning Duet's route (model, provider,
reasoning). Roles differ in what they need: the Designer and the module emitter
benefit from deep reasoning in a single call, while a coding loop pays for that
reasoning on every step. ``openchia.refiner_roles`` in the Hermes config lets an
operator override, per role, the custom provider, the model and the reasoning:

    openchia:
      refiner_roles:
        designer:    {reasoning: default}      # omit reasoning_effort: the server default
        emitter:     {reasoning: default}
        coder:       {custom_provider: Mango Coder, model: Qwen3-Coder-Next}
        implementer: {reasoning: low}

Role keys are the refiner's Episode local IDs (``launch``/``designer``,
``materialization_implementer``, ``implementer``, ``measure``, ``verify``,
``question``, ``support``, ``*_parts``) plus two call kinds: ``emitter`` (the
Builder emitter transcribing missing modules, #81) and ``coder`` (the Implementer's
coding session). ``designer`` also covers the root ``launch`` Episode.

Overrides are resolved when the Duet binding is frozen and stored in it without
secrets, so they are pinned, audited and preserved by ``/build continue``.
Credentials are resolved at call time from the provider's ``key_env``.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Mapping

OVERRIDE_FIELDS = frozenset({"custom_provider", "model", "reasoning"})
REASONING_LEVELS = frozenset({"minimal", "low", "medium", "high", "xhigh"})

_SCOPED_ROLE: ContextVar[str | None] = ContextVar("openchia_refiner_role", default=None)


@contextmanager
def role_scope(role: str) -> Iterator[None]:
    """Attribute model calls made in this context to *role* (e.g. ``emitter``)."""
    token = _SCOPED_ROLE.set(role)
    try:
        yield
    finally:
        _SCOPED_ROLE.reset(token)


def scoped_role() -> str | None:
    return _SCOPED_ROLE.get()


def _reasoning(value: Any) -> dict | None:
    """``default`` omits the field (server default); ``none`` disables; a level enables."""
    text = str(value).strip().lower()
    if text in {"default", "server", "omit"}:
        return None
    if value is False or text in {"none", "false", "disabled"}:
        return {"enabled": False}
    if text in REASONING_LEVELS:
        return {"enabled": True, "effort": text}
    raise ValueError(f"refiner role reasoning must be default, none or one of {sorted(REASONING_LEVELS)}, not {value!r}")


def resolve_role_routes(spec: Mapping[str, Any] | None, duet_route: Mapping[str, Any],
                        custom_providers: list[Mapping[str, Any]] | None) -> dict[str, dict]:
    """Concrete, secret-free routes for each configured role, derived from the Duet's route."""
    from agent.model_call_recovery_policy import resolve_recovery_policy

    if not spec:
        return {}
    if not isinstance(spec, Mapping):
        raise ValueError("openchia.refiner_roles must be a mapping of role -> override")
    providers = {str(item.get("name")): item for item in (custom_providers or []) if isinstance(item, Mapping)}
    routes: dict[str, dict] = {}
    for role, override in spec.items():
        if not isinstance(override, Mapping) or not override:
            raise ValueError(f"refiner role {role!r} needs a mapping with {sorted(OVERRIDE_FIELDS)}")
        unknown = set(override) - OVERRIDE_FIELDS
        if unknown:
            raise ValueError(f"refiner role {role!r} has unknown fields {sorted(unknown)}")
        route = {key: value for key, value in duet_route.items() if key != "recovery"}
        if "custom_provider" in override:
            name = str(override["custom_provider"])
            provider = providers.get(name)
            if provider is None:
                raise ValueError(f"refiner role {role!r} names unknown custom provider {name!r}")
            route.update(provider="custom", base_url=str(provider["base_url"]).rstrip("/"),
                         api_mode="chat_completions", model=str(provider.get("model") or route["model"]),
                         key_env=provider.get("key_env"))
            route.pop("reasoning", None)  # a different server: inherit no Duet reasoning setting
        if "model" in override:
            route["model"] = str(override["model"])
        if "reasoning" in override:
            route["reasoning"] = _reasoning(override["reasoning"])
        route["recovery"] = resolve_recovery_policy(route)
        routes[str(role)] = route
    return routes


def role_candidates(episode_local_id: str | None) -> list[str]:
    """Override keys to try for one call, most specific first."""
    candidates = []
    scoped = scoped_role()
    if scoped:
        candidates.append(scoped)
    if episode_local_id:
        candidates.append(episode_local_id)
        if episode_local_id == "launch":
            candidates.append("designer")
    return candidates


def select_route(role_routes: Mapping[str, dict], duet_route: dict, episode_local_id: str | None) -> tuple[str | None, dict]:
    for role in role_candidates(episode_local_id):
        if role in role_routes:
            return role, role_routes[role]
    return None, duet_route


def route_key(route: Mapping[str, Any], duet_key: str | None) -> str | None:
    """The credential for *route*: its provider's ``key_env``, or the Duet's own key."""
    if "key_env" in route:
        name = route["key_env"]
        return os.environ.get(name) if name else None
    return duet_key


def configured_role_spec() -> tuple[Mapping | None, list]:
    from openchia_cli.config import load_config_readonly

    config = load_config_readonly() or {}
    return (config.get("openchia") or {}).get("refiner_roles"), list(config.get("custom_providers") or [])


__all__ = [
    "configured_role_spec", "resolve_role_routes", "role_candidates", "role_scope",
    "route_key", "scoped_role", "select_route",
]
