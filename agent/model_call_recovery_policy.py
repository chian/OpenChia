"""Frozen operational recovery settings for an explicitly resolved model source.

These settings never select a model, credential, or Episode completion rule.
An old route without a recovery record keeps its original unbounded wait.
"""

from dataclasses import asdict, dataclass, fields
import math
from collections.abc import Mapping
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ModelCallRecoveryPolicy:
    mode: str = "retry_on_healthy_probe"
    idle_seconds: float = 900.0
    probe_timeout_seconds: float = 60.0
    probe_interval_seconds: float = 300.0
    recovery_grace_seconds: float = 60.0
    max_replacements: int = 1

    def __post_init__(self):
        if self.mode not in {"disabled", "preserve", "retry_on_healthy_probe"}:
            raise ValueError("Model recovery mode must be disabled, preserve, or retry_on_healthy_probe")
        for name in ("idle_seconds", "probe_timeout_seconds", "probe_interval_seconds", "recovery_grace_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"Model recovery {name} must be a finite positive number")
        if type(self.max_replacements) is not int or not 0 <= self.max_replacements <= 10:
            raise ValueError("Model recovery max_replacements must be an integer from 0 to 10")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value, *, base=None):
        if not isinstance(value, Mapping):
            raise ValueError("Model recovery policy must be an object")
        unknown = set(value) - {item.name for item in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown model recovery fields: {sorted(unknown)}")
        return cls(**{**(base.to_dict() if base else {}), **value})


def _source_url(value):
    if not isinstance(value, str):
        raise ValueError("Model recovery source base_url must be text")
    url = urlsplit(value)
    if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("Model recovery source must be an explicit HTTP(S) URL without credentials")
    return value.rstrip("/")


def resolve_recovery_policy(route, *, config=None):
    """Resolve once at launch/binding creation, not while a request is in flight.

    Source matches are literal provider + endpoint, optionally narrowed to one
    model. A route's explicit policy wins. Every source gets the same default;
    neither vendor knowledge nor request-status capabilities are required.
    """
    policy = ModelCallRecoveryPolicy()
    if config is None:
        from openchia_cli.config import load_config_readonly

        config = load_config_readonly()
    section = config.get("model_call_recovery", {})
    if not isinstance(section, Mapping) or set(section) - {"sources"}:
        raise ValueError("model_call_recovery must contain only sources")
    sources = section.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError("model_call_recovery.sources must be a list")
    seen = set()
    matches = []
    for source in sources:
        if not isinstance(source, Mapping) or not {"provider", "base_url", "policy"} <= source.keys() or source.keys() - {"provider", "base_url", "model", "policy"}:
            raise ValueError("Each recovery source requires provider, base_url, policy and optional model")
        for name in ("provider", "model"):
            if name in source and (not isinstance(source[name], str) or not source[name].strip()):
                raise ValueError(f"Recovery source {name} must be nonempty text")
        key = (source["provider"], _source_url(source["base_url"]), source.get("model"))
        if key in seen:
            raise ValueError("Duplicate model recovery source")
        seen.add(key)
        ModelCallRecoveryPolicy.from_dict(source["policy"])
        if key[:2] == (route["provider"], _source_url(route["base_url"])) and key[2] in (None, route["model"]):
            matches.append(source)
    for source in sorted(matches, key=lambda item: "model" in item):
        policy = ModelCallRecoveryPolicy.from_dict(source["policy"], base=policy)
    return ModelCallRecoveryPolicy.from_dict(route.get("recovery", {}), base=policy).to_dict()


def frozen_recovery_policy(route):
    """Absence is the declared legacy behavior, never permission to add retries."""
    if "recovery" not in route:
        return ModelCallRecoveryPolicy(mode="disabled")
    return ModelCallRecoveryPolicy.from_dict(route["recovery"])
