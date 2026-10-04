"""Approved experiment access, independent of materializer-selected functions."""

from dataclasses import dataclass
import re
from typing import Mapping

from .epistemic_contract import exact, names
from .models import _freeze_json, _thaw_json


OPERATION_FIELDS = {
    "describe": ((),),
    "history": (("query",),),
    "inventory": (("source", "query"),),
    "preview": (("spec",),),
    "run": (("spec",),),
    "continue": (("experiment_id", "resume_from"),),
    "status": (("experiment_id",),),
    "results": (("experiment_id",),),
    "compare": (("before", "after"),),
    "recording": (("experiment_id",),),
    "boundary": (("experiment_id", "episode_id"), ("experiment_id", "unit_id")),
}
OPERATIONS = frozenset(OPERATION_FIELDS)
SCOPE_KINDS = frozenset({
    "component",
    "unit",
    "episode",
    "nested",
    "workflow",
    "refinement",
})
MODES = frozenset({"numerical", "recorded", "live_saved", "live_fresh"})
CAPABILITY = "episode_testing"


def validate_operation_payload(operation, payload):
    choices = OPERATION_FIELDS[operation]
    if isinstance(payload, Mapping):
        for fields in choices:
            if set(payload) == set(fields):
                return exact(payload, set(fields), f"experiment {operation}")
    raise ValueError(
        f"experiment {operation} requires exactly one field set: {choices}"
    )


def testing_contract_schema():
    reference = {
        "type": "object",
        "properties": {
            "artifact_id": {"type": "string", "minLength": 1},
            "content_hash": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
        },
        "required": ["artifact_id", "content_hash"],
        "additionalProperties": False,
    }
    optional = {**reference, "type": ["object", "null"]}
    target = {
        "candidate_ref": reference,
        "build_receipt_ref": reference,
        "environment_ref": reference,
        "launch_ref": optional,
        "campaign_ref": optional,
        "requirements": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {"requirement_ref": reference, "measure_ref": reference},
                "required": ["requirement_ref", "measure_ref"],
                "additionalProperties": False,
            },
        },
        "recording_refs": {"type": "array", "items": reference},
        "parent_context_refs": {"type": "array", "items": reference},
    }
    return {
        "type": "object",
        "description": "Optional human-approved test access. Requires the episode_testing capability. A selected library function cannot grant this authority.",
        "properties": {
            "targets": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {
                    "type": "object",
                    "properties": target,
                    "required": list(target),
                    "additionalProperties": False,
                },
            },
            "scope_kinds": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "enum": sorted(SCOPE_KINDS)},
            },
            "modes": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "enum": sorted(MODES)},
            },
        },
        "required": ["targets", "scope_kinds", "modes"],
        "additionalProperties": False,
    }


def _reference(value):
    value = exact(value, {"artifact_id", "content_hash"}, "experiment access reference")
    if not isinstance(value["artifact_id"], str) or not value["artifact_id"].strip():
        raise ValueError("experiment access needs an artifact identity")
    if not isinstance(value["content_hash"], str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", value["content_hash"]
    ):
        raise ValueError("experiment access needs an exact content hash")


@dataclass(frozen=True)
class TestingContract:
    targets: Mapping[str, object]
    scope_kinds: tuple[str, ...]
    modes: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.targets, Mapping) or not self.targets:
            raise ValueError("testing access requires explicitly named targets")
        for name, target in self.targets.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("testing target names must be nonempty text")
            exact(
                target,
                {
                    "candidate_ref",
                    "build_receipt_ref",
                    "environment_ref",
                    "launch_ref",
                    "campaign_ref",
                    "requirements",
                    "recording_refs",
                    "parent_context_refs",
                },
                "testing target",
            )
            for key in ("candidate_ref", "build_receipt_ref", "environment_ref"):
                _reference(target[key])
            for key in ("launch_ref", "campaign_ref"):
                if target[key] is not None:
                    _reference(target[key])
            for key in ("recording_refs", "parent_context_refs"):
                if not isinstance(target[key], (tuple, list)):
                    raise ValueError(f"testing {key} must be an array")
                for ref in target[key]:
                    _reference(ref)
            if (
                not isinstance(target["requirements"], (tuple, list))
                or not target["requirements"]
            ):
                raise ValueError(
                    "testing target needs assigned requirement/measure pairs"
                )
            for requirement in target["requirements"]:
                exact(
                    requirement,
                    {"requirement_ref", "measure_ref"},
                    "testing requirement",
                )
                for ref in requirement.values():
                    _reference(ref)
        for field, choices in (("scope_kinds", SCOPE_KINDS), ("modes", MODES)):
            values = names(getattr(self, field), field, nonempty=True)
            if not set(values) <= choices:
                raise ValueError(f"testing {field} contains an unknown choice")
            object.__setattr__(self, field, values)
        object.__setattr__(
            self, "targets", _freeze_json(self.targets, "testing targets")
        )

    def as_record(self):
        return {
            "targets": _thaw_json(self.targets),
            "scope_kinds": list(self.scope_kinds),
            "modes": list(self.modes),
        }

    @classmethod
    def from_record(cls, value):
        row = exact(value, {"targets", "scope_kinds", "modes"}, "testing contract")
        return cls(row["targets"], row["scope_kinds"], row["modes"])
