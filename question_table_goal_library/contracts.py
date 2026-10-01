"""Neutral contracts for one run-global question-table Goal.

The mutable table state exists once per workflow.  An Episode receives a
read-only scoped view of that state; it never receives a second table store or
a capability to commit directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from numeric_control_library.credit_assignment import ResultColumnSchema


_STABLE_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}_[0-9a-f]{24,64}$")
_TOKEN = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")


def _stable_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not _STABLE_ID.fullmatch(value):
        raise ValueError(f"{name} must be a stable opaque ID")
    return value


def _stable_ids(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{name} must be a tuple")
    result = tuple(_stable_id(item, name) for item in value)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must contain unique IDs")
    return result


class TableEvaluationStatus(str, Enum):
    OBSERVED = "observed"
    FAILED = "failed"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class QuestionTableContractRef:
    contract_id: str
    result_channel_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "contract_id",
            _stable_id(self.contract_id, "contract_id"),
        )
        object.__setattr__(
            self,
            "result_channel_ids",
            _stable_ids(self.result_channel_ids, "result_channel_ids"),
        )
        if not self.result_channel_ids:
            raise ValueError("a question-table contract needs result channels")

    def as_record(self) -> dict[str, object]:
        return {
            "contract_id": self.contract_id,
            "result_channel_ids": list(self.result_channel_ids),
        }


def result_column_schema(
    contract: QuestionTableContractRef,
) -> ResultColumnSchema:
    """Project the declared channels to credit's positional zero reference."""

    if not isinstance(contract, QuestionTableContractRef):
        raise TypeError("result-column schema requires QuestionTableContractRef")
    return ResultColumnSchema(
        columns=contract.result_channel_ids,
        reference_point=tuple(0.0 for _ in contract.result_channel_ids),
    )


@dataclass(frozen=True)
class ScopedQuestionTableGoalView:
    """Serializable identity for a read-only view over the global store."""

    state_id: str
    scope_goal_id: str
    parent_goal_id: str
    contract_id: str
    projection_artifact_id: str

    def __post_init__(self) -> None:
        for name in (
            "state_id",
            "scope_goal_id",
            "contract_id",
            "projection_artifact_id",
        ):
            object.__setattr__(self, name, _stable_id(getattr(self, name), name))
        if self.parent_goal_id:
            object.__setattr__(
                self,
                "parent_goal_id",
                _stable_id(self.parent_goal_id, "parent_goal_id"),
            )

    def as_record(self) -> dict[str, str]:
        return {
            "state_id": self.state_id,
            "scope_goal_id": self.scope_goal_id,
            "parent_goal_id": self.parent_goal_id,
            "contract_id": self.contract_id,
            "projection_artifact_id": self.projection_artifact_id,
        }


@dataclass(frozen=True)
class TableResultProposal:
    """Artifact-only proposal presented to the global Goal transaction."""

    scope_goal_id: str
    record_artifact_ids: tuple[str, ...]
    evidence_commit_id: str
    evaluation_status: TableEvaluationStatus
    evaluation_code: str
    attribution_artifact_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scope_goal_id",
            _stable_id(self.scope_goal_id, "scope_goal_id"),
        )
        object.__setattr__(
            self,
            "record_artifact_ids",
            _stable_ids(self.record_artifact_ids, "record_artifact_ids"),
        )
        if self.evidence_commit_id:
            object.__setattr__(
                self,
                "evidence_commit_id",
                _stable_id(self.evidence_commit_id, "evidence_commit_id"),
            )
        if not isinstance(self.evaluation_status, TableEvaluationStatus):
            raise TypeError("evaluation_status must be a TableEvaluationStatus")
        if not isinstance(self.evaluation_code, str) or not _TOKEN.fullmatch(
            self.evaluation_code
        ):
            raise ValueError("evaluation_code must be a closed lowercase token")
        object.__setattr__(
            self,
            "attribution_artifact_ids",
            _stable_ids(
                self.attribution_artifact_ids,
                "attribution_artifact_ids",
            ),
        )

    def as_record(self) -> dict[str, object]:
        return {
            "scope_goal_id": self.scope_goal_id,
            "record_artifact_ids": list(self.record_artifact_ids),
            "evidence_commit_id": self.evidence_commit_id,
            "evaluation_status": self.evaluation_status.value,
            "evaluation_code": self.evaluation_code,
            "attribution_artifact_ids": list(self.attribution_artifact_ids),
        }


@dataclass(frozen=True)
class AcceptedIdentityChannels:
    """Table-owned accepted identities before numerical credit assignment."""

    declared_channel_ids: tuple[str, ...]
    observed_result_ids: tuple[str, ...]
    newly_committed_result_ids: tuple[str, ...]
    by_channel: Mapping[str, tuple[str, ...]]
    evaluation_status: TableEvaluationStatus
    evaluation_code: str
    attribution_artifact_ids: tuple[str, ...] = ()
    row_diagnostic_artifact_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        channels = _stable_ids(self.declared_channel_ids, "declared_channel_ids")
        if not channels:
            raise ValueError("accepted identities need declared channels")
        if not isinstance(self.by_channel, Mapping):
            raise TypeError("by_channel must be an object")
        projected = {
            _stable_id(channel, "result channel ID"): _stable_ids(
                identities,
                f"identities for {channel}",
            )
            for channel, identities in self.by_channel.items()
        }
        if set(projected) != set(channels):
            raise ValueError("by_channel must include every declared channel exactly")
        observed = _stable_ids(self.observed_result_ids, "observed_result_ids")
        projected_identities = [
            identity
            for identities in projected.values()
            for identity in identities
        ]
        members = set(projected_identities)
        if len(members) != len(projected_identities):
            raise ValueError(
                "one accepted logical identity cannot occupy multiple result channels"
            )
        if set(observed) != members:
            raise ValueError(
                "observed_result_ids must equal the union of channel identities"
            )
        newly_committed = _stable_ids(
            self.newly_committed_result_ids,
            "newly_committed_result_ids",
        )
        if not set(newly_committed) <= set(observed):
            raise ValueError("newly committed identities must be observed identities")
        if not isinstance(self.evaluation_status, TableEvaluationStatus):
            raise TypeError("evaluation_status must be a TableEvaluationStatus")
        if not isinstance(self.evaluation_code, str) or not _TOKEN.fullmatch(
            self.evaluation_code
        ):
            raise ValueError("evaluation_code must be a closed lowercase token")
        object.__setattr__(self, "declared_channel_ids", channels)
        object.__setattr__(self, "observed_result_ids", observed)
        object.__setattr__(self, "newly_committed_result_ids", newly_committed)
        object.__setattr__(self, "by_channel", MappingProxyType(projected))
        object.__setattr__(
            self,
            "attribution_artifact_ids",
            _stable_ids(self.attribution_artifact_ids, "attribution_artifact_ids"),
        )
        object.__setattr__(
            self,
            "row_diagnostic_artifact_ids",
            _stable_ids(
                self.row_diagnostic_artifact_ids,
                "row_diagnostic_artifact_ids",
            ),
        )

    def as_record(self) -> dict[str, object]:
        return {
            "declared_channel_ids": list(self.declared_channel_ids),
            "observed_result_ids": list(self.observed_result_ids),
            "newly_committed_result_ids": list(self.newly_committed_result_ids),
            "by_channel": {
                channel: list(identities)
                for channel, identities in self.by_channel.items()
            },
            "evaluation_status": self.evaluation_status.value,
            "evaluation_code": self.evaluation_code,
            "attribution_artifact_ids": list(self.attribution_artifact_ids),
            "row_diagnostic_artifact_ids": list(self.row_diagnostic_artifact_ids),
        }


__all__ = [
    "AcceptedIdentityChannels",
    "QuestionTableContractRef",
    "ScopedQuestionTableGoalView",
    "TableEvaluationStatus",
    "TableResultProposal",
    "result_column_schema",
]
