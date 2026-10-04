"""Immutable experimental intent; predictions are data, never acceptance rules."""

from dataclasses import dataclass
import json

from pydantic import ValidationError

from agent.duet_contracts import canonical_json, content_id, digest_record

from .schema import ExperimentInput


class ExperimentError(ValueError):
    """A request has an invalid shape or contradicts its own declared scope."""


@dataclass(frozen=True)
class ExperimentSpec:
    canonical_record: str

    def __post_init__(self):
        try:
            value = json.loads(self.canonical_record)
        except (TypeError, ValueError) as exc:
            raise ExperimentError("experiment must be a JSON object") from exc
        try:
            ExperimentInput.model_validate(value)
        except ValidationError as exc:
            error = exc.errors(include_input=False, include_url=False)[0]
            path = "/" + "/".join(str(part) for part in error["loc"])
            raise ExperimentError(
                f"invalid experiment at {path}: {error['type']}"
            ) from None
        _validate_selection(value)
        object.__setattr__(self, "canonical_record", canonical_json(value))

    @classmethod
    def from_record(cls, value):
        return cls(canonical_json(value))

    def as_record(self):
        return json.loads(self.canonical_record)

    @property
    def experiment_id(self):
        return content_id("experiment", self.as_record()).value

    @property
    def content_hash(self):
        return digest_record(self.as_record()).value


def _validate_selection(value):
    scope, start = value["scope"], value["start"]
    if type(value["schema_version"]) is not int:
        raise ExperimentError("schema_version must be an integer")
    if len(scope["included_local_ids"]) != len(set(scope["included_local_ids"])):
        raise ExperimentError("scope.included_local_ids must be unique")
    if scope["entry_local_id"] not in scope["included_local_ids"]:
        raise ExperimentError("scope.entry_local_id must be explicitly included")
    if (scope["kind"] == "component") != (value["boundary"]["children"] == "none"):
        raise ExperimentError("component scope requires children=none; other scopes declare execute or reuse")
    if (scope["kind"] == "component") != (scope["component_definition_id"] is not None):
        raise ExperimentError("only component scope names a component_definition_id")
    if (scope["kind"] == "unit") != (scope["unit_label"] is not None):
        raise ExperimentError("only unit scope names a unit_label")
    if (
        scope["kind"] in {"component", "episode"}
        and len(scope["included_local_ids"]) != 1
    ):
        raise ExperimentError("use nested scope when selecting multiple Episodes")
    if (start["kind"] == "fresh") != (start["artifact_ref"] is None):
        raise ExperimentError(
            "saved starts require an artifact; fresh starts cannot name one"
        )
    if start["kind"] != "fresh" and start["input_payload"]:
        raise ExperimentError(
            "saved inputs cannot be silently overlaid; fork a fresh experiment"
        )
    if value["mode"] == "live_fresh" and start["kind"] != "fresh":
        raise ExperimentError("live_fresh requires a fresh start")
    if value["mode"] == "live_saved" and start["kind"] == "fresh":
        raise ExperimentError("live_saved requires saved inputs or a checkpoint")
    requirements = [
        row["requirement_ref"]["artifact_id"] for row in value["requirements"]
    ]
    if len(requirements) != len(set(requirements)):
        raise ExperimentError("requirements must have unique identities")
