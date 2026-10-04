"""Frozen qualitative-result policy, using ordinary function definition identities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .models import _freeze_json, _thaw_json, _text


COMPONENT_ROLES = (
    "result_schema",
    "state_projector",
    "admission",
    "yield_function",
    "result_projection",
)
INQUIRY_ACTIONS = (
    "discover",
    "clarify",
    "support",
    "counterevidence",
    "prior_art",
    "falsify",
    "answer_criterion",
    "resolve_uncertainty",
    "merge",
    "retire",
)


def exact(value: object, fields: set[str], name: str) -> Mapping:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} must contain exactly {sorted(fields)}")
    return value


def names(value: object, name: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ValueError(f"{name} must be an array")
    result = tuple(_text(item, name) for item in value)
    if len(set(result)) != len(result) or (nonempty and not result):
        raise ValueError(
            f"{name} must contain unique {'nonempty ' if nonempty else ''}names"
        )
    return result


@dataclass(frozen=True)
class EpistemicContract:
    goal_class: str
    domain: str
    allowed_actions: tuple[str, ...]
    environment: Mapping[str, object]
    assumptions: tuple[str, ...]
    required_fields: tuple[str, ...]
    required_evidence: tuple[str, ...]
    components: Mapping[str, object]
    scope_tier: str = "episode"
    policy_strength: str = "advisory"
    evidence: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        for name in ("goal_class", "domain"):
            _text(getattr(self, name), name)
        for name in (
            "allowed_actions",
            "assumptions",
            "required_fields",
            "required_evidence",
        ):
            object.__setattr__(
                self,
                name,
                names(getattr(self, name), name, nonempty=name != "assumptions"),
            )
        if self.scope_tier not in {"episode", "workflow"}:
            raise ValueError(
                "domain/global promotion requires a separate human approval workflow"
            )
        if self.policy_strength not in {"advisory", "enforceable"}:
            raise ValueError("unknown learning policy strength")
        if not isinstance(self.environment, Mapping) or not self.environment:
            raise ValueError("learning requires explicit environmental conditions")
        object.__setattr__(
            self, "environment", _freeze_json(self.environment, "environment")
        )
        exact(self.components, set(COMPONENT_ROLES), "epistemic components")
        for role, selection in self.components.items():
            exact(
                selection,
                {"library", "function_id", "interface", "definition_id", "arguments"},
                role,
            )
        object.__setattr__(
            self, "components", _freeze_json(self.components, "components")
        )
        if not isinstance(self.evidence, (tuple, list)):
            raise ValueError("evidence must be an array")
        for item in self.evidence:
            exact(item, {"kind", "text", "observation"}, "approved evidence")
            _text(item["kind"], "evidence kind")
            _text(item["text"], "evidence text")
            if not isinstance(item["observation"], Mapping):
                raise ValueError("evidence observation must be an object")
        object.__setattr__(self, "evidence", _freeze_json(self.evidence, "evidence"))

    def validate_components(self) -> None:
        from .epistemic import resolve_component

        for role, selection in self.components.items():
            resolve_component(role, selection)

    def as_record(self) -> dict[str, object]:
        return {
            "goal_class": self.goal_class,
            "domain": self.domain,
            "allowed_actions": list(self.allowed_actions),
            "environment": _thaw_json(self.environment),
            "assumptions": list(self.assumptions),
            "required_fields": list(self.required_fields),
            "required_evidence": list(self.required_evidence),
            "components": _thaw_json(self.components),
            "scope_tier": self.scope_tier,
            "policy_strength": self.policy_strength,
            "evidence": _thaw_json(self.evidence),
        }

    @classmethod
    def from_record(cls, value: object) -> "EpistemicContract":
        record = exact(value, set(cls.__dataclass_fields__), "epistemic contract")
        return cls(**record)


def inquiry_contract(
    *, goal_class, domain, environment, evidence=(), scope_tier="episode"
):
    """Construct a problem-discovery policy without registering an Episode."""
    from .epistemic import default_components

    return EpistemicContract(
        goal_class=goal_class,
        domain=domain,
        allowed_actions=INQUIRY_ACTIONS,
        environment=environment,
        assumptions=(),
        required_fields=(
            "statement",
            "defined_terms",
            "scope",
            "boundary_conditions",
            "claimed_unknown",
            "why_it_matters",
            "prior_art_separation",
        ),
        required_evidence=("support", "counterevidence", "prior_art"),
        components=default_components(),
        scope_tier=scope_tier,
        evidence=evidence,
    )
