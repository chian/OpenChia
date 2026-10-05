"""Exact unit selection and evidence, sharing the ordinary method acquisition."""

from dataclasses import dataclass
from typing import Mapping

from function_library.epistemic_schemas import canonical
from function_library.models import _freeze_json, _thaw_json
from function_library.epistemic_contract import exact
from method_loop.identities import EpisodeRef, UnitRef

from .scoped import RunScope


@dataclass(frozen=True)
class UnitScope(RunScope):
    unit_ref: Mapping
    unit_label: str
    unit_event_ref: Mapping
    learning_baseline: Mapping | None = None

    def __post_init__(self):
        if self.kind != "unit":
            raise ValueError("unit selection requires kind=unit")
        invocation = RunScope(**{
            field: ("nested" if len(self.included_local_ids) > 1 else "episode")
            if field == "kind" else getattr(self, field)
            for field in RunScope.__dataclass_fields__
        })
        for field in RunScope.__dataclass_fields__:
            if field != "kind":
                object.__setattr__(self, field, getattr(invocation, field))
        unit = UnitRef.from_record(self.unit_ref)
        if unit.episode_id != EpisodeRef(self.boundary["source_run_id"], self.source_path).episode_id:
            raise ValueError("selected unit belongs to a different saved invocation")
        if unit.unit_index != 0 and self.learning_baseline is None:
            raise ValueError("later-unit execution requires coherent source/controller/shared-state restoration; no preceding units will be silently rerun")
        if self.learning_baseline is not None:
            if unit.unit_index == 0 or len(self.included_local_ids) != 1:
                raise ValueError("saved learning is only a later-unit, single-invocation starting state")
            baseline = exact(self.learning_baseline, {
                "schema_version", "source_registration_ref", "through_event_ref",
                "completed_units", "controller_state", "source_admission",
            }, "learning baseline")
            if baseline["schema_version"] != 1 or baseline["completed_units"] != unit.unit_index:
                raise ValueError("learning baseline differs from selected unit position")
            object.__setattr__(self, "learning_baseline", _freeze_json(baseline, "learning baseline"))
        if not isinstance(self.unit_label, str) or not self.unit_label:
            raise ValueError("selected unit needs its recorded label")
        for field in ("unit_ref", "unit_event_ref"):
            object.__setattr__(self, field, _freeze_json(getattr(self, field), field))

    def target_ref(self, run_id):
        return UnitRef(EpisodeRef(run_id, self.entry_path(run_id)).episode_id, self.unit_ref["unit_index"])

    def as_record(self):
        return {
            field: _thaw_json(getattr(self, field)) for field in self.__dataclass_fields__
            if field != "learning_baseline" or self.learning_baseline is not None
        }

    @classmethod
    def from_record(cls, value):
        fields = set(cls.__dataclass_fields__) - {"learning_baseline"}
        return cls(**exact(value, fields | ({"learning_baseline"} if "learning_baseline" in value else set()), "unit scope"))


def unit_projection(value):
    from .linker import _json_value

    return {
        "unit_label": value.unit_label,
        "unit_ref": value.unit_ref.as_record(),
        "epoch": value.epoch,
        "controller_input": _json_value(value.controller_input),
        "controller_step": _json_value(value.controller_step),
        "episode_update": _json_value(value.episode_update),
        "goal_result": _json_value(value.goal_result),
    }


def validate_unit_event(registration, events, kind, episode_id, payload):
    from .contracts import RunEventKind, TERMINAL_EVENT_KINDS

    scope = registration.execution_scope
    if not isinstance(scope, UnitScope):
        return
    target = scope.target_ref(registration.logical_run_id.value)
    prior = [event for event in events if event.kind is RunEventKind.UNIT_COMPLETED and event.episode_id.value == target.episode_id]
    if prior and kind not in TERMINAL_EVENT_KINDS:
        raise ValueError("the selected unit is already observed; further worker activity exceeds unit scope")
    if episode_id is None or episode_id.value != target.episode_id:
        return
    if kind is RunEventKind.EPISODE_COMPLETED:
        raise ValueError("unit execution cannot publish containing-Episode completion")
    if kind is RunEventKind.UNIT_COMPLETED and (
        payload.get("unit_label") != scope.unit_label
        or canonical(payload.get("unit_ref")) != canonical(target.as_record())
    ):
        raise ValueError("observed unit differs from its exact experimental selection")


def validate_unit_return(registration, events, typed_status):
    from .contracts import RunEventKind

    scope = registration.execution_scope
    target = scope.target_ref(registration.logical_run_id.value)
    owned = [event for event in events if event.episode_id is not None and event.episode_id.value == target.episode_id]
    units = [event for event in owned if event.kind is RunEventKind.UNIT_COMPLETED]
    if (
        len(units) != 1
        or sum(event.kind is RunEventKind.EPISODE_STARTED for event in owned) != 1
        or any(event.kind is RunEventKind.EPISODE_COMPLETED for event in owned)
        or typed_status is None or "completion" in typed_status or "workflow_result" in typed_status
    ):
        raise ValueError("unit return needs one observed unit, not an Episode-completion claim")
    event = units[0]
    validate_unit_event(registration, (), event.kind, event.episode_id, event.payload)
    if canonical(typed_status.get("unit_result")) != canonical(event.payload):
        raise ValueError("unit return differs from its committed observation")
    return event
