"""Exact repeatable-call authority, separate from the concrete workflow tree.

These records authorize calls to existing templates, never creation of another
Episode design. Scope and invocation admission remain registered operations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .episode_contract_models import (
    EpisodeFunctionSelectionSpec,
    _EPISODE_LOCAL_ID,
    _keys,
    _record,
)


CALL_FUNCTION_FIELDS = (
    "prepare_request",
    "receive_result",
    "synthesize_report",
    "request_schema",
    "invocation_admission",
    "authority_attenuation",
)


@dataclass(frozen=True)
class EpisodeRepeatableCallSpec:
    caller_local_id: str
    slot_name: str
    callee_template_local_id: str
    prepare_request: EpisodeFunctionSelectionSpec
    receive_result: EpisodeFunctionSelectionSpec
    synthesize_report: EpisodeFunctionSelectionSpec
    request_schema: EpisodeFunctionSelectionSpec
    invocation_admission: EpisodeFunctionSelectionSpec
    authority_attenuation: EpisodeFunctionSelectionSpec

    def __post_init__(self):
        for name in ("caller_local_id", "slot_name", "callee_template_local_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _EPISODE_LOCAL_ID.fullmatch(value):
                raise ValueError(f"repeatable call {name} must be a local identifier")
        for name in CALL_FUNCTION_FIELDS:
            if not isinstance(getattr(self, name), EpisodeFunctionSelectionSpec):
                raise TypeError(
                    f"repeatable call {name} must select an exact registered function"
                )

    def as_record(self):
        return {
            "caller_local_id": self.caller_local_id,
            "slot_name": self.slot_name,
            "callee_template_local_id": self.callee_template_local_id,
            **{name: getattr(self, name).as_record() for name in CALL_FUNCTION_FIELDS},
        }

    @classmethod
    def from_record(cls, value):
        record = _record(value, "repeatable call")
        _keys(
            record,
            {
                "caller_local_id",
                "slot_name",
                "callee_template_local_id",
                *CALL_FUNCTION_FIELDS,
            },
            "repeatable call",
        )
        return cls(
            caller_local_id=record["caller_local_id"],
            slot_name=record["slot_name"],
            callee_template_local_id=record["callee_template_local_id"],
            **{
                name: EpisodeFunctionSelectionSpec.from_record(record[name])
                for name in CALL_FUNCTION_FIELDS
            },
        )


def validate_calls(calls, episode_ids):
    if not isinstance(calls, tuple) or any(
        not isinstance(call, EpisodeRepeatableCallSpec) for call in calls
    ):
        raise TypeError("repeatable_calls must contain typed call bindings")
    seen = set()
    for call in calls:
        if (
            call.caller_local_id not in episode_ids
            or call.callee_template_local_id not in episode_ids
        ):
            raise ValueError(
                "repeatable call names a template outside the approved workflow"
            )
        key = (call.caller_local_id, call.slot_name)
        if key in seen:
            raise ValueError("repeatable call slots must be unique for their caller")
        seen.add(key)


def calls_record(calls):
    """Omit the extension entirely for legacy content hashes and receipts."""
    if not calls:
        return {}
    return {
        "repeatable_calls": {
            "version": 1,
            "bindings": [call.as_record() for call in calls],
        }
    }


def calls_from_record(record: Mapping):
    if "repeatable_calls" not in record:
        return ()
    value = _record(record["repeatable_calls"], "repeatable calls v1")
    _keys(value, {"version", "bindings"}, "repeatable calls v1")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("unsupported repeatable-call version")
    if not isinstance(value["bindings"], list) or not value["bindings"]:
        raise ValueError("repeatable-call extension requires a non-empty binding array")
    return tuple(
        EpisodeRepeatableCallSpec.from_record(item) for item in value["bindings"]
    )
