"""Closed child-to-parent Episode update records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from agent.episode_contract_models import (
    CHILD_EPISODE_UPDATE_SCHEMA_VERSION,
    PARENT_UPDATE_PROJECTION_SCHEMA_VERSION,
    _LEGACY_CHILD_EPISODE_UPDATE_SCHEMA_VERSION,
    ChildEpisodePhase,
    ChildEpisodeStopReason,
    EpisodeWorkflowDesignProjection,
    OpaqueId,
    Sha256Digest,
    _dump_json,
    _enum,
    _keys,
    _load_json,
    _non_negative_int,
    _number,
    _record,
)


_PHASE_REASONS: dict[ChildEpisodePhase, frozenset[ChildEpisodeStopReason]] = {
    ChildEpisodePhase.RUNNING: frozenset({ChildEpisodeStopReason.NONE}),
    ChildEpisodePhase.SUCCEEDED: frozenset({ChildEpisodeStopReason.TARGET_REACHED}),
    ChildEpisodePhase.STOPPED: frozenset(
        {
            ChildEpisodeStopReason.NO_PROGRESS,
            ChildEpisodeStopReason.DELIVERABLE_MISSING,
            ChildEpisodeStopReason.SOURCE_EXHAUSTED,
        }
    ),
    ChildEpisodePhase.BOUND_HIT: frozenset({ChildEpisodeStopReason.SAFETY_BOUND}),
    ChildEpisodePhase.FAILED: frozenset({ChildEpisodeStopReason.ERROR}),
    ChildEpisodePhase.CANCELLED: frozenset({ChildEpisodeStopReason.CANCELLED}),
}


@dataclass(frozen=True)
class ChildEpisodeUpdate:
    """Prompt-injection-free controller update built by the Episode host.

    Accepted result IDs address separately validated host artifacts; they do
    not carry the artifacts' content.  ``checkpoint_hash`` authenticates the
    persisted state from which the host projected this update.
    """

    child_episode_id: OpaqueId
    parent_episode_id: OpaqueId
    sequence: int
    phase: ChildEpisodePhase
    stop_reason: ChildEpisodeStopReason
    progress_value: float
    progress_delta: float
    observations: int
    units_consumed: int
    requests_transition: bool
    spec_hash: Sha256Digest
    checkpoint_hash: Sha256Digest
    accepted_result_ids: tuple[OpaqueId, ...] = ()
    schema_version: int = field(
        default=CHILD_EPISODE_UPDATE_SCHEMA_VERSION, init=False
    )

    def __post_init__(self) -> None:
        if not isinstance(self.child_episode_id, OpaqueId):
            raise ValueError("child_episode_id must be an OpaqueId")
        if not isinstance(self.parent_episode_id, OpaqueId):
            raise ValueError("parent_episode_id must be an OpaqueId")
        object.__setattr__(self, "sequence", _non_negative_int(self.sequence, "sequence"))
        if not isinstance(self.phase, ChildEpisodePhase):
            raise ValueError("phase must be a ChildEpisodePhase")
        if not isinstance(self.stop_reason, ChildEpisodeStopReason):
            raise ValueError("stop_reason must be a ChildEpisodeStopReason")
        if self.stop_reason not in _PHASE_REASONS[self.phase]:
            raise ValueError("stop_reason is inconsistent with child Episode phase")
        object.__setattr__(
            self, "progress_value", _number(self.progress_value, "progress_value")
        )
        object.__setattr__(
            self, "progress_delta", _number(self.progress_delta, "progress_delta")
        )
        object.__setattr__(
            self, "observations", _non_negative_int(self.observations, "observations")
        )
        object.__setattr__(
            self, "units_consumed", _non_negative_int(self.units_consumed, "units_consumed")
        )
        if not isinstance(self.requests_transition, bool):
            raise ValueError("requests_transition must be a boolean")
        expected_transition = self.phase not in {
            ChildEpisodePhase.RUNNING,
            ChildEpisodePhase.SUCCEEDED,
        }
        if self.requests_transition is not expected_transition:
            raise ValueError(
                "requests_transition is inconsistent with child Episode phase"
            )
        if not isinstance(self.spec_hash, Sha256Digest):
            raise ValueError("spec_hash must be a Sha256Digest")
        if not isinstance(self.checkpoint_hash, Sha256Digest):
            raise ValueError("checkpoint_hash must be a Sha256Digest")
        if not isinstance(self.accepted_result_ids, tuple) or any(
            not isinstance(result_id, OpaqueId)
            for result_id in self.accepted_result_ids
        ):
            raise ValueError("accepted_result_ids must be a tuple of OpaqueIds")
        if len(set(self.accepted_result_ids)) != len(self.accepted_result_ids):
            raise ValueError("accepted_result_ids must be unique")
        if self.phase is ChildEpisodePhase.SUCCEEDED:
            if len(self.accepted_result_ids) != 1:
                raise ValueError(
                    "a succeeded child Episode must carry exactly one accepted result ID"
                )
        elif self.accepted_result_ids:
            raise ValueError(
                "only a succeeded child Episode may carry an accepted result ID"
            )

    @property
    def terminal(self) -> bool:
        return self.phase is not ChildEpisodePhase.RUNNING

    @property
    def goal_reached(self) -> bool:
        return self.phase is ChildEpisodePhase.SUCCEEDED

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "child_episode_id": self.child_episode_id.value,
            "parent_episode_id": self.parent_episode_id.value,
            "sequence": self.sequence,
            "phase": self.phase.value,
            "stop_reason": self.stop_reason.value,
            "progress_value": self.progress_value,
            "progress_delta": self.progress_delta,
            "observations": self.observations,
            "units_consumed": self.units_consumed,
            "requests_transition": self.requests_transition,
            "terminal": self.terminal,
            "goal_reached": self.goal_reached,
            "spec_hash": self.spec_hash.value,
            "checkpoint_hash": self.checkpoint_hash.value,
            "accepted_result_ids": [
                result_id.value for result_id in self.accepted_result_ids
            ],
        }

    def to_json(self) -> str:
        return _dump_json(self.as_record())

    def as_parent_record(
        self,
        *,
        designed_by_episode_id: Optional[OpaqueId],
        workflow_parent_episode_id: Optional[OpaqueId],
        workflow_design: Optional[EpisodeWorkflowDesignProjection] = None,
    ) -> dict[str, Any]:
        """Return the closed projection shown to the containing Episode."""

        if designed_by_episode_id is not None and not isinstance(
            designed_by_episode_id, OpaqueId
        ):
            raise ValueError("designed_by_episode_id must be an OpaqueId or None")
        if workflow_parent_episode_id is not None and not isinstance(
            workflow_parent_episode_id, OpaqueId
        ):
            raise ValueError(
                "workflow_parent_episode_id must be an OpaqueId or None"
            )
        if workflow_design is not None and not isinstance(
            workflow_design,
            EpisodeWorkflowDesignProjection,
        ):
            raise ValueError(
                "workflow_design must be EpisodeWorkflowDesignProjection or None"
            )
        return {
            "schema_version": PARENT_UPDATE_PROJECTION_SCHEMA_VERSION,
            "episode_id": self.child_episode_id.value,
            "designed_by_episode_id": (
                None
                if designed_by_episode_id is None
                else designed_by_episode_id.value
            ),
            "workflow_parent_episode_id": (
                None
                if workflow_parent_episode_id is None
                else workflow_parent_episode_id.value
            ),
            "sequence": self.sequence,
            "phase": self.phase.value,
            "stop_reason": self.stop_reason.value,
            "progress_value": self.progress_value,
            "progress_delta": self.progress_delta,
            "observations": self.observations,
            "units_consumed": self.units_consumed,
            "requests_transition": self.requests_transition,
            "terminal": self.terminal,
            "goal_reached": self.goal_reached,
            "spec_hash": self.spec_hash.value,
            "checkpoint_hash": self.checkpoint_hash.value,
            "accepted_result_ids": [
                result_id.value for result_id in self.accepted_result_ids
            ],
            "workflow_design": (
                None if workflow_design is None else workflow_design.as_record()
            ),
        }

    def to_parent_json(
        self,
        *,
        designed_by_episode_id: Optional[OpaqueId],
        workflow_parent_episode_id: Optional[OpaqueId],
        workflow_design: Optional[EpisodeWorkflowDesignProjection] = None,
    ) -> str:
        return _dump_json(
            self.as_parent_record(
                designed_by_episode_id=designed_by_episode_id,
                workflow_parent_episode_id=workflow_parent_episode_id,
                workflow_design=workflow_design,
            )
        )

    @classmethod
    def from_record(cls, value: object) -> "ChildEpisodeUpdate":
        record = _record(value, "child Episode update")
        _keys(
            record,
            {
                "schema_version",
                "child_episode_id",
                "parent_episode_id",
                "sequence",
                "phase",
                "stop_reason",
                "progress_value",
                "progress_delta",
                "observations",
                "units_consumed",
                "requests_transition",
                "terminal",
                "goal_reached",
                "spec_hash",
                "checkpoint_hash",
                "accepted_result_ids",
            },
            "child Episode update",
        )
        schema_version = record["schema_version"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version
            not in {
                _LEGACY_CHILD_EPISODE_UPDATE_SCHEMA_VERSION,
                CHILD_EPISODE_UPDATE_SCHEMA_VERSION,
            }
        ):
            raise ValueError("unsupported child Episode update schema version")
        result_ids = record["accepted_result_ids"]
        if not isinstance(result_ids, list):
            raise ValueError("accepted_result_ids must be an array")
        phase = _enum(ChildEpisodePhase, record["phase"], "child Episode phase")
        requests_transition = record["requests_transition"]
        if not isinstance(requests_transition, bool):
            raise ValueError("requests_transition must be a boolean")
        if schema_version == _LEGACY_CHILD_EPISODE_UPDATE_SCHEMA_VERSION:
            requests_transition = phase not in {
                ChildEpisodePhase.RUNNING,
                ChildEpisodePhase.SUCCEEDED,
            }
        update = cls(
            child_episode_id=OpaqueId(record["child_episode_id"]),
            parent_episode_id=OpaqueId(record["parent_episode_id"]),
            sequence=record["sequence"],
            phase=phase,
            stop_reason=_enum(
                ChildEpisodeStopReason,
                record["stop_reason"],
                "child Episode stop reason",
            ),
            progress_value=record["progress_value"],
            progress_delta=record["progress_delta"],
            observations=record["observations"],
            units_consumed=record["units_consumed"],
            requests_transition=requests_transition,
            spec_hash=Sha256Digest(record["spec_hash"]),
            checkpoint_hash=Sha256Digest(record["checkpoint_hash"]),
            accepted_result_ids=tuple(OpaqueId(value) for value in result_ids),
        )
        if record["terminal"] is not update.terminal:
            raise ValueError("terminal flag does not match child Episode phase")
        if record["goal_reached"] is not update.goal_reached:
            raise ValueError("goal_reached flag does not match child Episode phase")
        return update

    @classmethod
    def from_json(cls, payload: str) -> "ChildEpisodeUpdate":
        return cls.from_record(_load_json(payload, "child Episode update"))


__all__ = ["ChildEpisodeUpdate"]
