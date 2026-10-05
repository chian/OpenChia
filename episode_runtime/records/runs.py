"""Compact, versioned Run facts shared by live and replay inspection.

These are host projections, not acceptance evidence or executable checkpoints.
No prompts, responses, worker prose or growing unit histories belong here.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from agent.duet_contracts import digest_record
from episode_runtime.contracts import RunEventKind


class RecordModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class ContentRecord(RecordModel):
    def as_record(self):
        body = self.model_dump(mode="json")
        return {**body, "content_hash": digest_record(body).value}

    @classmethod
    def record_schema(cls):
        schema = cls.model_json_schema()
        schema["properties"]["content_hash"] = {
            "type": "string", "pattern": r"^sha256:[0-9a-f]{64}$",
        }
        schema.setdefault("required", []).append("content_hash")
        return schema

    @classmethod
    def from_record(cls, raw):
        body = dict(raw)
        expected = body.pop("content_hash")
        value = cls.model_validate(body)
        if value.as_record()["content_hash"] != expected:
            raise ValueError("record differs from its committed content hash")
        return value


class EvidenceReference(RecordModel):
    artifact_id: str = Field(min_length=1, pattern=r"\S")
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class EventPosition(RecordModel):
    sequence: int = Field(ge=0)
    event_id: str
    content_hash: str


class Activity(RecordModel):
    events: int = Field(default=0, ge=0)
    invocations_started: int = Field(default=0, ge=0)
    invocations_completed: int = Field(default=0, ge=0)
    units_completed: int = Field(default=0, ge=0)
    components_observed: int = Field(default=0, ge=0)
    model_requests: int = Field(default=0, ge=0)
    model_responses: int = Field(default=0, ge=0)
    http_requests: int = Field(default=0, ge=0)
    http_responses: int = Field(default=0, ge=0)
    experiment_requests: int = Field(default=0, ge=0)
    experiment_responses: int = Field(default=0, ge=0)
    learning_commits: int = Field(default=0, ge=0)
    reused_responses: int = Field(default=0, ge=0)


class RunRecord(ContentRecord):
    schema_version: Literal[1] = 1
    run_id: str
    duet_id: str
    registration_hash: str
    build_receipt_id: str
    workflow_id: str
    workflow_hash: str
    authority_head_approval_id: str
    execution_scope: dict[str, JsonValue] | None
    through_event: EventPosition | None = None
    activity: Activity = Field(default_factory=Activity)
    terminal_status: Literal[
        "succeeded", "failed", "cancelled", "blocked", "interrupted",
        "invalid", "resource_limited",
    ] | None = None
    evidence_ref: EvidenceReference | None = None

    @classmethod
    def from_record(cls, raw):
        value = super().from_record(raw)
        if value.activity.events != (
            0 if value.through_event is None else value.through_event.sequence + 1
        ):
            raise ValueError("Run record activity differs from its event position")
        if value.evidence_ref is not None and value.terminal_status is None:
            raise ValueError("Run record evidence requires a terminal event")
        return value


_COUNTERS = {
    RunEventKind.EPISODE_STARTED: "invocations_started",
    RunEventKind.EPISODE_COMPLETED: "invocations_completed",
    RunEventKind.UNIT_COMPLETED: "units_completed",
    RunEventKind.COMPONENT_OBSERVED: "components_observed",
    RunEventKind.MODEL_REQUESTED: "model_requests",
    RunEventKind.MODEL_RESPONDED: "model_responses",
    RunEventKind.HTTP_REQUESTED: "http_requests",
    RunEventKind.HTTP_RESPONDED: "http_responses",
    RunEventKind.EXPERIMENT_REQUESTED: "experiment_requests",
    RunEventKind.EXPERIMENT_RESPONDED: "experiment_responses",
    RunEventKind.LEARNING_COMMITTED: "learning_commits",
}


def initial_record(registration):
    return RunRecord(
        **{
            key: getattr(registration, key).value
            for key in (
                "run_id", "duet_id", "registration_hash", "build_receipt_id",
                "workflow_id", "workflow_hash", "authority_head_approval_id",
            )
        },
        execution_scope=None if registration.execution_scope is None else {
            "kind": registration.execution_scope.kind,
            "entry_local_id": registration.execution_scope.entry_local_id,
            "included_local_ids": list(registration.execution_scope.included_local_ids),
            "content_hash": digest_record(registration.execution_scope.as_record()).value,
        },
    )


def advance_record(prior, event):
    if (
        event.run_id.value != prior.run_id
        or event.registration_hash.value != prior.registration_hash
        or event.sequence != prior.activity.events
        or (None if event.previous_event_hash is None else event.previous_event_hash.value)
        != (None if prior.through_event is None else prior.through_event.content_hash)
        or prior.terminal_status is not None
    ):
        raise ValueError("Run record cannot skip or replace committed events")
    activity = prior.activity.model_dump()
    activity["events"] += 1
    counter = _COUNTERS.get(event.kind)
    if counter is not None:
        activity[counter] += 1
    if event.kind in {RunEventKind.MODEL_RESPONDED, RunEventKind.HTTP_RESPONDED}:
        activity["reused_responses"] += int(event.payload.get("reused_from") is not None)
    body = prior.model_dump(mode="json")
    body.update(
        activity=activity,
        through_event={
            "sequence": event.sequence, "event_id": event.event_id.value,
            "content_hash": event.event_hash.value,
        },
    )
    if event.terminal:
        body["terminal_status"] = event.payload["terminal_status"]
    return RunRecord.model_validate(body)


def attach_evidence(prior, evidence):
    if (
        evidence.run_id.value != prior.run_id
        or evidence.registration_hash.value != prior.registration_hash
        or evidence.event_count != prior.activity.events
        or prior.through_event is None
        or evidence.head_event_hash.value != prior.through_event.content_hash
        or evidence.terminal_status.value != prior.terminal_status
    ):
        raise ValueError("Run record evidence differs from its committed position")
    body = prior.model_dump(mode="json")
    body["evidence_ref"] = {
        "artifact_id": evidence.evidence_id.value,
        "content_hash": evidence.content_hash.value,
    }
    return RunRecord.model_validate(body)
