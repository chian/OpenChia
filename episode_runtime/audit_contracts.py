"""Chunked terminal audit and evidence contracts for one admitted Run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from agent.duet_contracts import content_id, digest_record
from agent.episode_contracts import OpaqueId, Sha256Digest

from .contracts import (
    InspectedExecutorAttestation,
    RunEvent,
    RunRegistration,
    RunTerminalStatus,
    _array,
    _integer,
    _json_mapping,
    _record,
    _thaw_json,
)


@dataclass(frozen=True)
class RunAuditChunk:
    """One bounded, content-addressed segment of the durable event chain."""

    run_id: OpaqueId
    registration_hash: Sha256Digest
    manifest_id: OpaqueId
    attestation_id: OpaqueId
    attestation_hash: Sha256Digest
    chunk_index: int
    first_sequence: int
    previous_chunk_id: Optional[OpaqueId]
    previous_chunk_hash: Optional[Sha256Digest]
    events: tuple[RunEvent, ...]
    chunk_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        for name in ("run_id", "manifest_id", "attestation_id"):
            if not isinstance(getattr(self, name), OpaqueId):
                raise TypeError(f"{name} must be an OpaqueId")
        for name in ("registration_hash", "attestation_hash"):
            if not isinstance(getattr(self, name), Sha256Digest):
                raise TypeError(f"{name} must be a Sha256Digest")
        _integer(self.chunk_index, "chunk_index")
        _integer(self.first_sequence, "first_sequence")
        if (self.previous_chunk_id is None) != (self.previous_chunk_hash is None):
            raise ValueError("audit chunk predecessor identity and hash must align")
        if (self.chunk_index == 0) != (self.previous_chunk_id is None):
            raise ValueError("only the first audit chunk can omit its predecessor")
        if self.previous_chunk_id is not None and not isinstance(
            self.previous_chunk_id, OpaqueId
        ):
            raise TypeError("previous_chunk_id must be an OpaqueId or None")
        if self.previous_chunk_hash is not None and not isinstance(
            self.previous_chunk_hash, Sha256Digest
        ):
            raise TypeError("previous_chunk_hash must be a Sha256Digest or None")
        if not isinstance(self.events, tuple) or not self.events:
            raise ValueError("Run audit chunk requires a non-empty event tuple")
        previous_event = self.events[0].previous_event_hash
        for offset, event in enumerate(self.events):
            if not isinstance(event, RunEvent):
                raise TypeError("Run audit chunks contain only RunEvent values")
            if (
                event.sequence != self.first_sequence + offset
                or event.previous_event_hash != previous_event
                or event.run_id != self.run_id
                or event.registration_hash != self.registration_hash
                or event.manifest_id != self.manifest_id
                or event.attestation_id != self.attestation_id
                or event.attestation_hash != self.attestation_hash
            ):
                raise ValueError("Run audit chunk event linkage is invalid")
            if event.terminal and offset != len(self.events) - 1:
                raise ValueError("terminal Run event must end its audit chunk")
            previous_event = event.event_hash
        chunk_id = content_id("run_audit_chunk", self.semantic_record())
        object.__setattr__(self, "chunk_id", chunk_id)
        object.__setattr__(
            self,
            "content_hash",
            digest_record({"chunk_id": chunk_id.value, **self.semantic_record()}),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id.value,
            "registration_hash": self.registration_hash.value,
            "manifest_id": self.manifest_id.value,
            "attestation_id": self.attestation_id.value,
            "attestation_hash": self.attestation_hash.value,
            "chunk_index": self.chunk_index,
            "first_sequence": self.first_sequence,
            "previous_chunk_id": (
                None
                if self.previous_chunk_id is None
                else self.previous_chunk_id.value
            ),
            "previous_chunk_hash": (
                None
                if self.previous_chunk_hash is None
                else self.previous_chunk_hash.value
            ),
            "events": [event.as_record() for event in self.events],
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id.value,
            "content_hash": self.content_hash.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "RunAuditChunk":
        record = _record(
            value,
            "Run audit chunk",
            {
                "chunk_id",
                "content_hash",
                "run_id",
                "registration_hash",
                "manifest_id",
                "attestation_id",
                "attestation_hash",
                "chunk_index",
                "first_sequence",
                "previous_chunk_id",
                "previous_chunk_hash",
                "events",
            },
        )
        result = cls(
            run_id=OpaqueId(record["run_id"]),
            registration_hash=Sha256Digest(record["registration_hash"]),
            manifest_id=OpaqueId(record["manifest_id"]),
            attestation_id=OpaqueId(record["attestation_id"]),
            attestation_hash=Sha256Digest(record["attestation_hash"]),
            chunk_index=record["chunk_index"],
            first_sequence=record["first_sequence"],
            previous_chunk_id=(
                None
                if record["previous_chunk_id"] is None
                else OpaqueId(record["previous_chunk_id"])
            ),
            previous_chunk_hash=(
                None
                if record["previous_chunk_hash"] is None
                else Sha256Digest(record["previous_chunk_hash"])
            ),
            events=tuple(
                RunEvent.from_record(item)
                for item in _array(record["events"], "Run audit chunk events")
            ),
        )
        if (
            result.chunk_id.value != record["chunk_id"]
            or result.content_hash.value != record["content_hash"]
        ):
            raise ValueError("Run audit chunk identity is stale")
        return result


@dataclass(frozen=True)
class RunAuditLog:
    """Terminal manifest committing an ordered chain of bounded audit chunks."""

    run_id: OpaqueId
    registration_hash: Sha256Digest
    manifest_id: OpaqueId
    attestation_id: OpaqueId
    attestation_hash: Sha256Digest
    event_count: int
    terminal_event_id: OpaqueId
    head_event_hash: Sha256Digest
    chunk_count: int
    head_chunk_id: OpaqueId
    head_chunk_hash: Sha256Digest
    audit_log_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "manifest_id",
            "attestation_id",
            "terminal_event_id",
            "head_chunk_id",
        ):
            if not isinstance(getattr(self, name), OpaqueId):
                raise TypeError(f"{name} must be an OpaqueId")
        for name in (
            "registration_hash",
            "attestation_hash",
            "head_event_hash",
            "head_chunk_hash",
        ):
            if not isinstance(getattr(self, name), Sha256Digest):
                raise TypeError(f"{name} must be a Sha256Digest")
        _integer(self.event_count, "event_count", minimum=1)
        _integer(self.chunk_count, "chunk_count", minimum=1)
        audit_log_id = content_id("run_audit_log", self.semantic_record())
        object.__setattr__(self, "audit_log_id", audit_log_id)
        object.__setattr__(
            self,
            "content_hash",
            digest_record({"audit_log_id": audit_log_id.value, **self.semantic_record()}),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id.value,
            "registration_hash": self.registration_hash.value,
            "manifest_id": self.manifest_id.value,
            "attestation_id": self.attestation_id.value,
            "attestation_hash": self.attestation_hash.value,
            "event_count": self.event_count,
            "terminal_event_id": self.terminal_event_id.value,
            "head_event_hash": self.head_event_hash.value,
            "chunk_count": self.chunk_count,
            "head_chunk_id": self.head_chunk_id.value,
            "head_chunk_hash": self.head_chunk_hash.value,
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "audit_log_id": self.audit_log_id.value,
            "content_hash": self.content_hash.value,
            **self.semantic_record(),
        }

    def validate_chunks(self, chunks: tuple[RunAuditChunk, ...]) -> tuple[RunEvent, ...]:
        if not isinstance(chunks, tuple) or len(chunks) != self.chunk_count:
            raise ValueError("audit chunks do not cover the terminal manifest")
        events: list[RunEvent] = []
        previous_chunk_id: Optional[OpaqueId] = None
        previous_chunk_hash: Optional[Sha256Digest] = None
        previous_event_hash: Optional[Sha256Digest] = None
        for index, chunk in enumerate(chunks):
            if (
                not isinstance(chunk, RunAuditChunk)
                or chunk.chunk_index != index
                or chunk.previous_chunk_id != previous_chunk_id
                or chunk.previous_chunk_hash != previous_chunk_hash
                or chunk.first_sequence != len(events)
                or chunk.run_id != self.run_id
                or chunk.registration_hash != self.registration_hash
                or chunk.manifest_id != self.manifest_id
                or chunk.attestation_id != self.attestation_id
                or chunk.attestation_hash != self.attestation_hash
            ):
                raise ValueError("audit chunk chain differs from its terminal manifest")
            for event in chunk.events:
                if event.previous_event_hash != previous_event_hash:
                    raise ValueError(
                        "audit chunk event chain has a broken cross-chunk link"
                    )
                previous_event_hash = event.event_hash
            events.extend(chunk.events)
            previous_chunk_id = chunk.chunk_id
            previous_chunk_hash = chunk.content_hash
        if len(events) != self.event_count:
            raise ValueError("audit chunk event count differs from its manifest")
        terminal = events[-1]
        if any(event.terminal for event in events[:-1]):
            raise ValueError("terminal Run event appears before the audit head")
        if (
            not terminal.terminal
            or terminal.event_id != self.terminal_event_id
            or terminal.event_hash != self.head_event_hash
        ):
            raise ValueError("audit chunk chain has another terminal head")
        if (
            chunks[-1].chunk_id != self.head_chunk_id
            or chunks[-1].content_hash != self.head_chunk_hash
        ):
            raise ValueError("audit manifest names another head chunk")
        return tuple(events)

    @classmethod
    def from_record(cls, value: object) -> "RunAuditLog":
        record = _record(
            value,
            "Run audit log",
            {
                "audit_log_id",
                "content_hash",
                "run_id",
                "registration_hash",
                "manifest_id",
                "attestation_id",
                "attestation_hash",
                "event_count",
                "terminal_event_id",
                "head_event_hash",
                "chunk_count",
                "head_chunk_id",
                "head_chunk_hash",
            },
        )
        result = cls(
            run_id=OpaqueId(record["run_id"]),
            registration_hash=Sha256Digest(record["registration_hash"]),
            manifest_id=OpaqueId(record["manifest_id"]),
            attestation_id=OpaqueId(record["attestation_id"]),
            attestation_hash=Sha256Digest(record["attestation_hash"]),
            event_count=record["event_count"],
            terminal_event_id=OpaqueId(record["terminal_event_id"]),
            head_event_hash=Sha256Digest(record["head_event_hash"]),
            chunk_count=record["chunk_count"],
            head_chunk_id=OpaqueId(record["head_chunk_id"]),
            head_chunk_hash=Sha256Digest(record["head_chunk_hash"]),
        )
        if (
            result.audit_log_id.value != record["audit_log_id"]
            or result.content_hash.value != record["content_hash"]
        ):
            raise ValueError("Run audit log identity is stale")
        return result


@dataclass(frozen=True)
class RunEvidence:
    """Exactly one immutable terminal evidence record for a claimed Run."""

    run_id: OpaqueId
    registration_hash: Sha256Digest
    manifest_id: OpaqueId
    attestation_id: OpaqueId
    attestation_hash: Sha256Digest
    audit_log_id: OpaqueId
    audit_log_hash: Sha256Digest
    event_count: int
    terminal_event_id: OpaqueId
    head_event_hash: Sha256Digest
    terminal_status: RunTerminalStatus
    typed_status: Mapping[str, object]
    effect_receipt_ids: tuple[OpaqueId, ...] = ()
    effect_receipt_hashes: tuple[Sha256Digest, ...] = ()
    evidence_id: OpaqueId = field(init=False)
    content_hash: Sha256Digest = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "manifest_id",
            "attestation_id",
            "terminal_event_id",
            "audit_log_id",
        ):
            if not isinstance(getattr(self, name), OpaqueId):
                raise TypeError(f"{name} must be an OpaqueId")
        for name in (
            "registration_hash",
            "attestation_hash",
            "head_event_hash",
            "audit_log_hash",
        ):
            if not isinstance(getattr(self, name), Sha256Digest):
                raise TypeError(f"{name} must be a Sha256Digest")
        _integer(self.event_count, "event_count", minimum=1)
        if not isinstance(self.terminal_status, RunTerminalStatus):
            raise TypeError("terminal_status must be a RunTerminalStatus")
        object.__setattr__(
            self,
            "typed_status",
            _json_mapping(self.typed_status, "typed_status"),
        )
        if not isinstance(self.effect_receipt_ids, tuple) or not isinstance(
            self.effect_receipt_hashes,
            tuple,
        ):
            raise TypeError("effect receipt identities and hashes must be tuples")
        if self.effect_receipt_ids or self.effect_receipt_hashes:
            raise ValueError("the initial runtime cannot admit effect receipts")
        evidence_id = content_id("run_evidence", self.semantic_record())
        object.__setattr__(self, "evidence_id", evidence_id)
        object.__setattr__(
            self,
            "content_hash",
            digest_record(
                {"evidence_id": evidence_id.value, **self.semantic_record()}
            ),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id.value,
            "registration_hash": self.registration_hash.value,
            "manifest_id": self.manifest_id.value,
            "attestation_id": self.attestation_id.value,
            "attestation_hash": self.attestation_hash.value,
            "audit_log_id": self.audit_log_id.value,
            "audit_log_hash": self.audit_log_hash.value,
            "event_count": self.event_count,
            "terminal_event_id": self.terminal_event_id.value,
            "head_event_hash": self.head_event_hash.value,
            "terminal_status": self.terminal_status.value,
            "typed_status": _thaw_json(self.typed_status),
            "effect_receipt_ids": [
                item.value for item in self.effect_receipt_ids
            ],
            "effect_receipt_hashes": [
                item.value for item in self.effect_receipt_hashes
            ],
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id.value,
            "content_hash": self.content_hash.value,
            **self.semantic_record(),
        }

    def validate_against(
        self,
        registration: RunRegistration,
        attestation: InspectedExecutorAttestation,
        audit_log: RunAuditLog,
        chunks: tuple[RunAuditChunk, ...],
    ) -> None:
        if not isinstance(registration, RunRegistration):
            raise TypeError("registration must be a RunRegistration")
        if not isinstance(attestation, InspectedExecutorAttestation):
            raise TypeError("attestation must be an InspectedExecutorAttestation")
        attestation.validate_against(registration)
        if (
            self.run_id != registration.run_id
            or self.registration_hash != registration.registration_hash
            or self.manifest_id != registration.manifest_id
            or self.attestation_id != attestation.attestation_id
            or self.attestation_hash != attestation.content_hash
        ):
            raise ValueError("Run evidence belongs to another registration")
        if not isinstance(audit_log, RunAuditLog):
            raise TypeError("audit_log must be a RunAuditLog")
        if (
            audit_log.run_id != self.run_id
            or audit_log.registration_hash != self.registration_hash
            or audit_log.manifest_id != self.manifest_id
            or audit_log.attestation_id != self.attestation_id
            or audit_log.attestation_hash != self.attestation_hash
        ):
            raise ValueError("Run audit log belongs to another evidence record")
        events = audit_log.validate_chunks(chunks)
        terminal = events[-1]
        if not terminal.terminal:
            raise ValueError("Run evidence requires a terminal head event")
        terminal_status = RunTerminalStatus(
            terminal.payload["terminal_status"]
        )
        terminal_typed_status = _json_mapping(
            terminal.payload["typed_status"],
            "terminal typed_status",
        )
        if (
            self.audit_log_id != audit_log.audit_log_id
            or self.audit_log_hash != audit_log.content_hash
            or self.event_count != len(events)
            or self.terminal_event_id != terminal.event_id
            or self.head_event_hash != terminal.event_hash
            or self.terminal_status is not terminal_status
            or self.typed_status != terminal_typed_status
        ):
            raise ValueError("Run evidence differs from its terminal event chain")

    @classmethod
    def from_record(cls, value: object) -> "RunEvidence":
        record = _record(
            value,
            "Run evidence",
            {
                "evidence_id",
                "content_hash",
                "run_id",
                "registration_hash",
                "manifest_id",
                "attestation_id",
                "attestation_hash",
                "audit_log_id",
                "audit_log_hash",
                "event_count",
                "terminal_event_id",
                "head_event_hash",
                "terminal_status",
                "typed_status",
                "effect_receipt_ids",
                "effect_receipt_hashes",
            },
        )
        try:
            terminal_status = RunTerminalStatus(record["terminal_status"])
        except (TypeError, ValueError) as exc:
            raise ValueError("Run evidence terminal status is invalid") from exc
        result = cls(
            run_id=OpaqueId(record["run_id"]),
            registration_hash=Sha256Digest(record["registration_hash"]),
            manifest_id=OpaqueId(record["manifest_id"]),
            attestation_id=OpaqueId(record["attestation_id"]),
            attestation_hash=Sha256Digest(record["attestation_hash"]),
            audit_log_id=OpaqueId(record["audit_log_id"]),
            audit_log_hash=Sha256Digest(record["audit_log_hash"]),
            event_count=record["event_count"],
            terminal_event_id=OpaqueId(record["terminal_event_id"]),
            head_event_hash=Sha256Digest(record["head_event_hash"]),
            terminal_status=terminal_status,
            typed_status=record["typed_status"],
            effect_receipt_ids=tuple(
                OpaqueId(item)
                for item in _array(
                    record["effect_receipt_ids"],
                    "effect_receipt_ids",
                )
            ),
            effect_receipt_hashes=tuple(
                Sha256Digest(item)
                for item in _array(
                    record["effect_receipt_hashes"],
                    "effect_receipt_hashes",
                )
            ),
        )
        if (
            result.evidence_id.value != record["evidence_id"]
            or result.content_hash.value != record["content_hash"]
        ):
            raise ValueError("Run evidence identity is stale")
        return result

__all__ = ["RunAuditChunk", "RunAuditLog", "RunEvidence"]
