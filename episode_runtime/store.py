"""Append-only filesystem persistence for admitted Episode Runs."""

from __future__ import annotations

from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Any, Iterator, Mapping, Optional

from agent.duet_contracts import canonical_json
from agent.episode_contracts import OpaqueId, Sha256Digest

from .audit_contracts import RunAuditChunk, RunAuditLog, RunEvidence
from .contracts import (
    InspectedExecutorAttestation,
    RunEvent,
    RunEventKind,
    RunEventOrigin,
    RunRegistration,
    RunTerminalStatus,
)


_EVENT_FILE = re.compile(r"^[0-9]{20}\.json$")
_MAX_RECORD_BYTES = 64 * 1024 * 1024
_TARGET_AUDIT_CHUNK_BYTES = 8 * 1024 * 1024
_TERMINAL_KIND = {
    RunTerminalStatus.SUCCEEDED: RunEventKind.RUN_SUCCEEDED,
    RunTerminalStatus.FAILED: RunEventKind.RUN_FAILED,
    RunTerminalStatus.CANCELLED: RunEventKind.RUN_CANCELLED,
    RunTerminalStatus.BLOCKED: RunEventKind.RUN_BLOCKED,
    RunTerminalStatus.INTERRUPTED: RunEventKind.RUN_INTERRUPTED,
    RunTerminalStatus.INVALID: RunEventKind.RUN_INVALID,
    RunTerminalStatus.RESOURCE_LIMITED: RunEventKind.RUN_RESOURCE_LIMITED,
}


class RunStoreError(RuntimeError):
    """The append-only Run store rejected an operation."""


class RunStoreConflict(RunStoreError):
    """An immutable record already exists or an expected head changed."""


class RunStoreNotFound(RunStoreError):
    """A required immutable predecessor record is absent."""


class RunStoreCorruption(RunStoreError):
    """Stored bytes fail their canonical contract or content identity."""


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RunStoreCorruption(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise RunStoreCorruption(f"non-finite JSON number {value!r} is prohibited")


def _canonical_bytes(record: Mapping[str, object]) -> bytes:
    return canonical_json(record).encode("utf-8")


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError(errno.EIO, "short write to immutable Run record")
        offset += written


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class RunStore:
    """One append-only store with terminal audit reads, never event replay."""

    def __init__(self, root: Path | str) -> None:
        supplied = Path(root)
        if supplied == Path(supplied.anchor):
            raise ValueError("filesystem root cannot be a Run store")
        if supplied.is_symlink():
            raise ValueError("Run store root cannot be a symlink")
        supplied.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root = supplied.resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Run store root must be a directory")
        self._registrations = self.root / "registrations"
        self._claims = self.root / "claims"
        self._events = self.root / "events"
        self._evidence = self.root / "evidence"
        self._audit_logs = self.root / "audit_logs"
        self._audit_chunks = self.root / "audit_chunks"
        self._records = self.root / "records"
        self.runtime_sources_root = self.root / "runtime_sources"
        for directory in (
            self._registrations,
            self._claims,
            self._events,
            self._evidence,
            self._audit_logs,
            self._audit_chunks,
            self._records,
            self.runtime_sources_root,
        ):
            directory.mkdir(mode=0o700, exist_ok=True)
            if directory.is_symlink() or not directory.is_dir():
                raise ValueError("Run store directories must be real directories")

    @staticmethod
    def _run_name(run_id: OpaqueId) -> str:
        if not isinstance(run_id, OpaqueId):
            raise TypeError("run_id must be an OpaqueId")
        return run_id.value

    def _registration_path(self, run_id: OpaqueId) -> Path:
        return self._registrations / f"{self._run_name(run_id)}.json"

    def _claim_path(self, run_id: OpaqueId) -> Path:
        return self._claims / f"{self._run_name(run_id)}.json"

    def _event_directory(self, run_id: OpaqueId) -> Path:
        return self._events / self._run_name(run_id)

    def _evidence_path(self, run_id: OpaqueId) -> Path:
        return self._evidence / f"{self._run_name(run_id)}.json"

    def _audit_log_path(self, audit_log_id: OpaqueId) -> Path:
        if not isinstance(audit_log_id, OpaqueId):
            raise TypeError("audit_log_id must be an OpaqueId")
        return self._audit_logs / f"{audit_log_id.value}.json"

    def _audit_chunk_path(self, chunk_id: OpaqueId) -> Path:
        if not isinstance(chunk_id, OpaqueId):
            raise TypeError("chunk_id must be an OpaqueId")
        return self._audit_chunks / f"{chunk_id.value}.json"

    @staticmethod
    def _read_record(path: Path, name: str) -> Mapping[str, Any]:
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError as exc:
            raise RunStoreNotFound(f"{name} does not exist") from exc
        except OSError as exc:
            raise RunStoreCorruption(
                f"{name} cannot be opened as an exact regular file"
            ) from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise RunStoreCorruption(f"{name} is not a regular file")
            if info.st_size <= 0 or info.st_size > _MAX_RECORD_BYTES:
                raise RunStoreCorruption(f"{name} has an invalid byte length")
            chunks: list[bytes] = []
            remaining = info.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    raise RunStoreCorruption(f"{name} ended before its stated size")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise RunStoreCorruption(f"{name} grew while being read")
        finally:
            os.close(descriptor)
        payload = b"".join(chunks)
        try:
            decoded = payload.decode("utf-8", errors="strict")
            value = json.loads(
                decoded,
                object_pairs_hook=_pairs,
                parse_constant=_reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RunStoreCorruption(f"{name} is not strict UTF-8 JSON") from exc
        if not isinstance(value, Mapping):
            raise RunStoreCorruption(f"{name} must contain a JSON object")
        if _canonical_bytes(value) != payload:
            raise RunStoreCorruption(f"{name} is not canonically encoded")
        return value

    @staticmethod
    def _publish_atomic_exclusive(
        path: Path,
        record: Mapping[str, object],
        name: str,
    ) -> None:
        payload = _canonical_bytes(record)
        if not payload or len(payload) > _MAX_RECORD_BYTES:
            raise RunStoreError(f"{name} has an invalid byte length")
        if path.exists():
            existing = RunStore._read_record(path, name)
            if _canonical_bytes(existing) != payload:
                raise RunStoreConflict(f"{name} already contains different bytes")
            _fsync_directory(path.parent)
            return
        temporary = path.parent / (
            f".{path.name}.{secrets.token_hex(16)}.pending"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        try:
            descriptor = os.open(temporary, flags, 0o600)
        except FileExistsError as exc:
            raise RunStoreConflict(f"temporary publication collision for {name}") from exc
        try:
            try:
                _write_all(descriptor, payload)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError:
                existing = RunStore._read_record(path, name)
                if _canonical_bytes(existing) != payload:
                    raise RunStoreConflict(
                        f"{name} already contains different bytes"
                    )
            temporary.unlink()
            _fsync_directory(path.parent)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _publish_claim_exclusive(
        path: Path,
        record: Mapping[str, object],
    ) -> None:
        """Atomically publish the one-shot claim from an O_EXCL temp file."""

        try:
            RunStore._publish_atomic_exclusive(
                path,
                record,
                "Run claim",
            )
        except RunStoreConflict as exc:
            raise RunStoreConflict(
                "Run has already been claimed by another executor"
            ) from exc

    def publish_registration(self, registration: RunRegistration) -> None:
        if not isinstance(registration, RunRegistration):
            raise TypeError("registration must be a RunRegistration")
        from .records.index import RunRecordIndex
        from .continuation import validate_resume_registration

        validate_resume_registration(self, registration)

        # A derived-index setup failure must not publish an unclaimed Run with
        # no terminal event channel. Inspection still requires the registration.
        RunRecordIndex(self).initialize(registration)
        self._publish_atomic_exclusive(
            self._registration_path(registration.run_id),
            registration.as_record(),
            "Run registration",
        )

    def read_registration(self, run_id: OpaqueId) -> RunRegistration:
        record = self._read_record(
            self._registration_path(run_id),
            "Run registration",
        )
        try:
            registration = RunRegistration.from_record(record)
        except (TypeError, ValueError) as exc:
            raise RunStoreCorruption("Run registration contract is invalid") from exc
        if registration.run_id != run_id:
            raise RunStoreCorruption("Run registration path and identity disagree")
        return registration

    def claim_run(self, attestation: InspectedExecutorAttestation) -> None:
        if not isinstance(attestation, InspectedExecutorAttestation):
            raise TypeError(
                "attestation must be an InspectedExecutorAttestation"
            )
        registration = self.read_registration(attestation.run_id)
        attestation.validate_against(registration)
        self._publish_claim_exclusive(
            self._claim_path(attestation.run_id),
            attestation.as_record(),
        )
        event_directory = self._event_directory(attestation.run_id)
        try:
            event_directory.mkdir(mode=0o700)
        except FileExistsError:
            if event_directory.is_symlink() or not event_directory.is_dir():
                raise RunStoreCorruption(
                    "claimed Run event path is not a real directory"
                )
        _fsync_directory(self._events)

    def read_claim(self, run_id: OpaqueId) -> InspectedExecutorAttestation:
        registration = self.read_registration(run_id)
        record = self._read_record(self._claim_path(run_id), "Run claim")
        try:
            attestation = InspectedExecutorAttestation.from_record(record)
            attestation.validate_against(registration)
        except (TypeError, ValueError) as exc:
            raise RunStoreCorruption("Run claim contract is invalid") from exc
        if attestation.run_id != run_id:
            raise RunStoreCorruption("Run claim path and identity disagree")
        return attestation

    @contextmanager
    def _claim_lock(self, run_id: OpaqueId) -> Iterator[None]:
        try:
            import fcntl
        except ImportError as exc:
            raise RunStoreError(
                "Run claims require a Linux/Unix advisory lock implementation"
            ) from exc
        try:
            descriptor = os.open(
                self._claim_path(run_id),
                os.O_RDONLY | os.O_NOFOLLOW,
            )
        except FileNotFoundError as exc:
            raise RunStoreNotFound("Run must be claimed before events") from exc
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _load_event_chain_locked(
        self,
        registration: RunRegistration,
        attestation: InspectedExecutorAttestation,
    ) -> tuple[RunEvent, ...]:
        directory = self._event_directory(registration.run_id)
        if directory.is_symlink() or not directory.is_dir():
            raise RunStoreCorruption("claimed Run event directory is missing")
        entries = sorted(directory.iterdir(), key=lambda item: item.name)
        if any(
            not entry.is_file()
            or entry.is_symlink()
            or _EVENT_FILE.fullmatch(entry.name) is None
            for entry in entries
        ):
            raise RunStoreCorruption("Run event directory contains an unknown entry")
        events: list[RunEvent] = []
        previous: Optional[Sha256Digest] = None
        for sequence, entry in enumerate(entries):
            if entry.name != f"{sequence:020d}.json":
                raise RunStoreCorruption("Run event file sequence is not contiguous")
            record = self._read_record(entry, f"Run event {sequence}")
            try:
                event = RunEvent.from_record(record)
            except (TypeError, ValueError) as exc:
                raise RunStoreCorruption(
                    f"Run event {sequence} contract is invalid"
                ) from exc
            if (
                event.sequence != sequence
                or event.previous_event_hash != previous
                or event.run_id != registration.run_id
                or event.registration_hash != registration.registration_hash
                or event.manifest_id != registration.manifest_id
                or event.attestation_id != attestation.attestation_id
                or event.attestation_hash != attestation.content_hash
            ):
                raise RunStoreCorruption("Run event chain linkage is invalid")
            if event.terminal and sequence != len(entries) - 1:
                raise RunStoreCorruption("terminal Run event is not the chain head")
            events.append(event)
            previous = event.event_hash
        return tuple(events)

    @staticmethod
    def _validate_sender_position(
        events: tuple[RunEvent, ...],
        origin: RunEventOrigin,
        sender_sequence: int,
    ) -> None:
        if isinstance(sender_sequence, bool) or not isinstance(
            sender_sequence,
            int,
        ) or sender_sequence < 0:
            raise ValueError("sender_sequence must be a non-negative integer")
        prior = tuple(
            event.sender_sequence for event in events if event.origin is origin
        )
        if prior and sender_sequence <= prior[-1]:
            raise RunStoreConflict(
                "persisted sender_sequence must be strictly increasing"
            )

    def _new_event(
        self,
        *,
        registration: RunRegistration,
        attestation: InspectedExecutorAttestation,
        events: tuple[RunEvent, ...],
        origin: RunEventOrigin,
        sender_sequence: int,
        kind: RunEventKind,
        episode_id: Optional[OpaqueId],
        payload: Mapping[str, object],
    ) -> RunEvent:
        if not isinstance(origin, RunEventOrigin):
            raise TypeError("origin must be a RunEventOrigin")
        if not isinstance(kind, RunEventKind):
            raise TypeError("kind must be a RunEventKind")
        self._validate_sender_position(events, origin, sender_sequence)
        from .components import validate_component_event
        if origin is RunEventOrigin.WORKER:
            validate_component_event(registration, kind, episode_id, payload)
            from .units import validate_unit_event
            validate_unit_event(registration, events, kind, episode_id, payload)
        if kind is RunEventKind.LEARNING_COMMITTED:
            from .learning_integrity import validate_learning_commit
            from .learning_baseline import load_learning_baseline
            validate_learning_commit(
                events=(*self.read_execution_ancestors(registration), *events),
                origin=origin, episode_id=episode_id, payload=payload,
                baseline=load_learning_baseline(self, registration, episode_id),
            )
        return RunEvent(
            run_id=registration.run_id,
            registration_hash=registration.registration_hash,
            manifest_id=registration.manifest_id,
            attestation_id=attestation.attestation_id,
            attestation_hash=attestation.content_hash,
            sequence=len(events),
            origin=origin,
            sender_sequence=sender_sequence,
            kind=kind,
            episode_id=episode_id,
            payload=payload,
            previous_event_hash=(
                None if not events else events[-1].event_hash
            ),
        )

    def _publish_event(self, event: RunEvent) -> None:
        path = self._event_directory(event.run_id) / f"{event.sequence:020d}.json"
        self._publish_atomic_exclusive(path, event.as_record(), "Run event")
        from .records.index import RunRecordIndex

        RunRecordIndex(self).event_committed(event)

    @staticmethod
    def _build_audit_chunks(
        events: tuple[RunEvent, ...],
    ) -> tuple[RunAuditChunk, ...]:
        if not events or not events[-1].terminal:
            raise ValueError("audit chunks require a terminal event chain")
        first = events[0]
        chunks: list[RunAuditChunk] = []
        pending: list[RunEvent] = []
        previous_chunk_id: Optional[OpaqueId] = None
        previous_chunk_hash: Optional[Sha256Digest] = None

        def materialize(items: tuple[RunEvent, ...]) -> RunAuditChunk:
            return RunAuditChunk(
                run_id=first.run_id,
                registration_hash=first.registration_hash,
                manifest_id=first.manifest_id,
                attestation_id=first.attestation_id,
                attestation_hash=first.attestation_hash,
                chunk_index=len(chunks),
                first_sequence=items[0].sequence,
                previous_chunk_id=previous_chunk_id,
                previous_chunk_hash=previous_chunk_hash,
                events=items,
            )

        for event in events:
            candidate_items = (*pending, event)
            candidate = materialize(candidate_items)
            if (
                pending
                and len(_canonical_bytes(candidate.as_record()))
                > _TARGET_AUDIT_CHUNK_BYTES
            ):
                completed = materialize(tuple(pending))
                chunks.append(completed)
                previous_chunk_id = completed.chunk_id
                previous_chunk_hash = completed.content_hash
                pending = [event]
            else:
                pending.append(event)
        if pending:
            chunks.append(materialize(tuple(pending)))
        for chunk in chunks:
            if len(_canonical_bytes(chunk.as_record())) > _MAX_RECORD_BYTES:
                raise RunStoreError(
                    "one Run event is too large for a bounded audit chunk"
                )
        return tuple(chunks)

    def _publish_terminal_artifacts_locked(
        self,
        *,
        registration: RunRegistration,
        attestation: InspectedExecutorAttestation,
        events: tuple[RunEvent, ...],
    ) -> RunEvidence:
        if not events or not events[-1].terminal:
            raise RunStoreConflict("Run event chain has no terminal head")
        terminal = events[-1]
        chunks = self._build_audit_chunks(events)
        for chunk in chunks:
            self._publish_atomic_exclusive(
                self._audit_chunk_path(chunk.chunk_id),
                chunk.as_record(),
                "Run audit chunk",
            )
        audit_log = RunAuditLog(
            run_id=registration.run_id,
            registration_hash=registration.registration_hash,
            manifest_id=registration.manifest_id,
            attestation_id=attestation.attestation_id,
            attestation_hash=attestation.content_hash,
            event_count=len(events),
            terminal_event_id=terminal.event_id,
            head_event_hash=terminal.event_hash,
            chunk_count=len(chunks),
            head_chunk_id=chunks[-1].chunk_id,
            head_chunk_hash=chunks[-1].content_hash,
        )
        self._publish_atomic_exclusive(
            self._audit_log_path(audit_log.audit_log_id),
            audit_log.as_record(),
            "terminal Run audit log manifest",
        )
        terminal_status = RunTerminalStatus(
            terminal.payload["terminal_status"]
        )
        typed_status = terminal.payload["typed_status"]
        if not isinstance(typed_status, Mapping):
            raise RunStoreCorruption("terminal typed_status is not an object")
        evidence = RunEvidence(
            run_id=registration.run_id,
            registration_hash=registration.registration_hash,
            manifest_id=registration.manifest_id,
            attestation_id=attestation.attestation_id,
            attestation_hash=attestation.content_hash,
            audit_log_id=audit_log.audit_log_id,
            audit_log_hash=audit_log.content_hash,
            event_count=len(events),
            terminal_event_id=terminal.event_id,
            head_event_hash=terminal.event_hash,
            terminal_status=terminal_status,
            typed_status=typed_status,
        )
        evidence.validate_against(
            registration,
            attestation,
            audit_log,
            chunks,
        )
        self._publish_atomic_exclusive(
            self._evidence_path(registration.run_id),
            evidence.as_record(),
            "terminal Run evidence",
        )
        from .records.index import RunRecordIndex

        RunRecordIndex(self).evidence_committed(evidence)
        return evidence

    def append_event(
        self,
        *,
        run_id: OpaqueId,
        origin: RunEventOrigin,
        sender_sequence: int,
        kind: RunEventKind,
        episode_id: Optional[OpaqueId],
        payload: Mapping[str, object],
    ) -> RunEvent:
        if kind in _TERMINAL_KIND.values():
            raise ValueError("terminal events must be published with finalize_run")
        registration = self.read_registration(run_id)
        attestation = self.read_claim(run_id)
        with self._claim_lock(run_id):
            if self._evidence_path(run_id).exists():
                raise RunStoreConflict("terminal Run evidence already exists")
            events = self._load_event_chain_locked(registration, attestation)
            if events and events[-1].terminal:
                raise RunStoreConflict("Run event chain is already terminal")
            event = self._new_event(
                registration=registration,
                attestation=attestation,
                events=events,
                origin=origin,
                sender_sequence=sender_sequence,
                kind=kind,
                episode_id=episode_id,
                payload=payload,
            )
            self._publish_event(event)
            return event

    def finalize_run(
        self,
        *,
        run_id: OpaqueId,
        origin: RunEventOrigin,
        sender_sequence: int,
        terminal_status: RunTerminalStatus,
        typed_status: Mapping[str, object],
    ) -> RunEvidence:
        if not isinstance(terminal_status, RunTerminalStatus):
            raise TypeError("terminal_status must be a RunTerminalStatus")
        registration = self.read_registration(run_id)
        attestation = self.read_claim(run_id)
        with self._claim_lock(run_id):
            events = self._load_event_chain_locked(registration, attestation)
            if events and events[-1].terminal:
                terminal = events[-1]
                if (
                    terminal.origin is not origin
                    or terminal.sender_sequence != sender_sequence
                    or terminal.kind is not _TERMINAL_KIND[terminal_status]
                    or terminal.payload
                    != {
                        "terminal_status": terminal_status.value,
                        "typed_status": typed_status,
                    }
                ):
                    raise RunStoreConflict(
                        "terminal Run head differs from repeated finalization"
                    )
                complete_events = events
            else:
                terminal = self._new_event(
                    registration=registration,
                    attestation=attestation,
                    events=events,
                    origin=origin,
                    sender_sequence=sender_sequence,
                    kind=_TERMINAL_KIND[terminal_status],
                    episode_id=None,
                    payload={
                        "terminal_status": terminal_status.value,
                        "typed_status": typed_status,
                    },
                )
                self._publish_event(terminal)
                complete_events = (*events, terminal)
            return self._publish_terminal_artifacts_locked(
                registration=registration,
                attestation=attestation,
                events=complete_events,
            )

    def complete_terminal_publication(self, run_id: OpaqueId) -> RunEvidence:
        """Idempotently finish artifacts after a persisted terminal head."""

        try:
            return self.read_evidence(run_id)
        except RunStoreNotFound:
            pass
        registration = self.read_registration(run_id)
        attestation = self.read_claim(run_id)
        with self._claim_lock(run_id):
            events = self._load_event_chain_locked(registration, attestation)
            return self._publish_terminal_artifacts_locked(
                registration=registration,
                attestation=attestation,
                events=events,
            )

    def _read_audit_log_locked(
        self,
        evidence: RunEvidence,
    ) -> tuple[RunAuditLog, tuple[RunAuditChunk, ...]]:
        try:
            record = self._read_record(
                self._audit_log_path(evidence.audit_log_id),
                "terminal Run audit log",
            )
        except RunStoreNotFound as exc:
            raise RunStoreCorruption(
                "terminal evidence references a missing audit manifest"
            ) from exc
        try:
            audit_log = RunAuditLog.from_record(record)
        except (TypeError, ValueError) as exc:
            raise RunStoreCorruption(
                "terminal Run audit log contract is invalid"
            ) from exc
        if (
            audit_log.audit_log_id != evidence.audit_log_id
            or audit_log.content_hash != evidence.audit_log_hash
        ):
            raise RunStoreCorruption(
                "terminal Run audit log differs from evidence or event chain"
            )
        reverse_chunks: list[RunAuditChunk] = []
        next_id: Optional[OpaqueId] = audit_log.head_chunk_id
        next_hash: Optional[Sha256Digest] = audit_log.head_chunk_hash
        seen: set[OpaqueId] = set()
        while next_id is not None:
            if next_id in seen or len(reverse_chunks) >= audit_log.chunk_count:
                raise RunStoreCorruption("Run audit chunk chain contains a cycle")
            seen.add(next_id)
            try:
                chunk_record = self._read_record(
                    self._audit_chunk_path(next_id),
                    f"Run audit chunk {next_id.value}",
                )
            except RunStoreNotFound as exc:
                raise RunStoreCorruption(
                    "Run audit manifest references a missing chunk"
                ) from exc
            try:
                chunk = RunAuditChunk.from_record(chunk_record)
            except (TypeError, ValueError) as exc:
                raise RunStoreCorruption(
                    "Run audit chunk contract is invalid"
                ) from exc
            if chunk.chunk_id != next_id or chunk.content_hash != next_hash:
                raise RunStoreCorruption(
                    "Run audit chunk differs from its successor link"
                )
            reverse_chunks.append(chunk)
            next_id = chunk.previous_chunk_id
            next_hash = chunk.previous_chunk_hash
        if len(reverse_chunks) != audit_log.chunk_count:
            raise RunStoreCorruption(
                "Run audit chunk chain length differs from its manifest"
            )
        chunks = tuple(reversed(reverse_chunks))
        try:
            audit_log.validate_chunks(chunks)
        except (TypeError, ValueError) as exc:
            raise RunStoreCorruption(
                "terminal Run audit chunks differ from their manifest"
            ) from exc
        return audit_log, chunks

    def read_run_record(self, run_id: OpaqueId) -> dict[str, Any]:
        """Inspect maintained high-level facts without loading the audit chain."""
        from .records.index import RunRecordIndex

        return RunRecordIndex(self).inspect(run_id)

    def read_inventory(self, run_id: OpaqueId, query: Mapping[str, object], **selection) -> dict[str, Any]:
        """Inspect indexed invocation/unit facts without reconstructing the audit."""
        from .records.inventory import inventory

        return inventory(self, run_id, query, **selection)

    def refresh_run_record(self, run_id: OpaqueId) -> dict[str, Any]:
        """Explicitly rebuild the same view from verified evidence; never replay."""
        from .records.index import RunRecordIndex

        registration = self.read_registration(run_id)
        attestation = self.read_claim(run_id)
        try:
            evidence = self.verify_terminal_snapshot(run_id).evidence
        except RunStoreNotFound:
            evidence = None
        with self._claim_lock(run_id):
            events = self._load_event_chain_locked(registration, attestation)
            RunRecordIndex(self).rebuild(registration, events, evidence)
        return self.read_run_record(run_id)

    def read_evidence(self, run_id: OpaqueId) -> RunEvidence:
        return self.read_terminal_snapshot(run_id).evidence

    def terminal_snapshot_scope(self, run_ids):
        """Reuse named terminal histories until this host operation finishes."""
        from .store_terminal import terminal_snapshot_scope

        return terminal_snapshot_scope(self, run_ids)

    def read_terminal_snapshot(self, run_id: OpaqueId):
        """Verify terminal evidence/events together, or reuse a scoped snapshot."""
        from .store_terminal import read_terminal_snapshot

        return read_terminal_snapshot(self, run_id)

    def verify_terminal_snapshot(self, run_id: OpaqueId):
        """Independently reread all terminal artifacts, even inside a read scope."""
        from .store_terminal import read_terminal_snapshot

        return read_terminal_snapshot(self, run_id, verify=True)

    def read_committed_prefix(self, run_id: OpaqueId) -> tuple[RunEvent, ...]:
        """Inspect a verified journal prefix without claiming terminal evidence.

        Experiment recording/status uses this for active or interrupted Runs.
        Acceptance consumers must still use read_evidence/read_audit_log; those
        require the independently published terminal evidence and audit chunks.
        """
        registration = self.read_registration(run_id)
        attestation = self.read_claim(run_id)
        with self._claim_lock(run_id):
            return self._load_event_chain_locked(registration, attestation)

    def read_execution_ancestors(
        self, registration: RunRegistration,
    ) -> tuple[RunEvent, ...]:
        """Read validated terminal ancestors without locking this physical Run.

        Safe inside its claim transaction: only immutable predecessor attempts
        are read. The linkage is verified, never supplied as a ledger snapshot.
        """
        from .continuation import execution_lineage

        return tuple(
            event for ancestor in execution_lineage(self, registration)[:-1]
            for event in self.read_audit_log(ancestor.run_id)
        )

    def read_execution_prefix(self, run_id: OpaqueId) -> tuple[RunEvent, ...]:
        """Read exact continuation ancestors and this attempt's committed prefix.

        Events keep their original physical Run, hash and sequence. This does
        not republish evidence or credit and does not imply successful completion.
        Unrelated Runs, even of the same workflow, are never included.
        """
        previous = self.read_execution_ancestors(self.read_registration(run_id))
        return (*previous, *self.read_committed_prefix(run_id))

    def read_audit_log(self, run_id: OpaqueId) -> tuple[RunEvent, ...]:
        """Return only the validated terminal log; active prefixes are hidden."""
        return self.read_terminal_snapshot(run_id).events

    def audit_log_location(self, run_id: OpaqueId) -> Path:
        """Return the exact immutable terminal audit-manifest path."""

        evidence = self.read_evidence(run_id)
        path = self._audit_log_path(evidence.audit_log_id).resolve(strict=True)
        if path.parent != self._audit_logs.resolve(strict=True):
            raise RunStoreCorruption("terminal Run audit log escaped its store")
        return path


__all__ = [
    "RunStore",
    "RunStoreConflict",
    "RunStoreCorruption",
    "RunStoreError",
    "RunStoreNotFound",
]
