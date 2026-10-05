"""Durable, append-oriented storage for Duet design sessions."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Iterator, Mapping, Optional

from agent.duet_contracts import canonical_json, content_id


_ALLOWED_STATE_TRANSITIONS = {
    ("designing", "designing"),
    ("designing", "awaiting_workflow_approval"),
    ("awaiting_workflow_approval", "designing"),
    ("awaiting_workflow_approval", "awaiting_workflow_approval"),
    ("sealed", "refining"),
    ("refining", "refining"),
    ("refining", "awaiting_workflow_approval"),
    ("refining", "awaiting_refinement_approval"),
    ("awaiting_workflow_approval", "sealed"),
    ("awaiting_refinement_approval", "sealed"),
    ("refining", "sealed"),
}


def _require_state_transition(expected_state: str, state: str) -> None:
    if (expected_state, state) not in _ALLOWED_STATE_TRANSITIONS:
        raise ValueError(
            f"invalid Duet state transition: {expected_state} -> {state}"
        )


class DuetStoreError(RuntimeError):
    """Base class for durable Duet store failures."""


class DuetConflictError(DuetStoreError):
    """An immutable identity or optimistic revision conflicted."""


class DuetNotFoundError(DuetStoreError):
    """A required Duet record does not exist."""


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return json.loads(canonical_json(value))


class DuetStore:
    """SQLite repository for one or more Duet design sessions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            str(self.path),
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._transaction_depth = 0
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "DuetStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            depth = self._transaction_depth
            savepoint = f"duet_nested_{depth}"
            self._connection.execute(
                "BEGIN IMMEDIATE" if depth == 0 else f"SAVEPOINT {savepoint}"
            )
            self._transaction_depth += 1
            try:
                yield self._connection
            except BaseException:
                if depth == 0:
                    self._connection.execute("ROLLBACK")
                else:
                    self._connection.execute(f"ROLLBACK TO {savepoint}")
                    self._connection.execute(f"RELEASE {savepoint}")
                raise
            else:
                self._connection.execute(
                    "COMMIT" if depth == 0 else f"RELEASE {savepoint}"
                )
            finally:
                self._transaction_depth -= 1

    def _create_schema(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS duets (
                    duet_id TEXT PRIMARY KEY,
                    identity_json TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    authority_head_approval_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (authority_head_approval_id)
                        REFERENCES approvals(approval_id)
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    duet_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (duet_id) REFERENCES duets(duet_id)
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    duet_id TEXT NOT NULL,
                    human_authority_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    predecessor_approval_id TEXT,
                    record_json TEXT NOT NULL,
                    revoked_at REAL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (duet_id) REFERENCES duets(duet_id),
                    FOREIGN KEY (artifact_id) REFERENCES artifacts(artifact_id),
                    FOREIGN KEY (predecessor_approval_id)
                        REFERENCES approvals(approval_id)
                );

                CREATE INDEX IF NOT EXISTS artifact_history_page
                    ON artifacts(duet_id, kind, created_at DESC, artifact_id DESC);
                CREATE INDEX IF NOT EXISTS artifact_episode_history
                    ON artifacts(duet_id, kind,
                        json_extract(record_json, '$.episode_id'),
                        created_at DESC, artifact_id DESC);
                CREATE INDEX IF NOT EXISTS artifact_recording_history
                    ON artifacts(duet_id, kind,
                        json_extract(record_json, '$.registration_ref.run_id'),
                        created_at DESC, artifact_id DESC);
                CREATE INDEX IF NOT EXISTS artifact_experiment_history
                    ON artifacts(duet_id, kind,
                        json_extract(record_json, '$.experiment_id'),
                        created_at DESC, artifact_id DESC);

                CREATE TABLE IF NOT EXISTS refinement_cycles (
                    refinement_id TEXT PRIMARY KEY,
                    duet_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    baseline_artifact_id TEXT NOT NULL,
                    proposal_artifact_id TEXT NOT NULL,
                    baseline_authority_head_approval_id TEXT NOT NULL,
                    decision_artifact_id TEXT,
                    resulting_approval_id TEXT,
                    state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE (duet_id, ordinal),
                    FOREIGN KEY (duet_id) REFERENCES duets(duet_id),
                    FOREIGN KEY (baseline_artifact_id)
                        REFERENCES artifacts(artifact_id),
                    FOREIGN KEY (proposal_artifact_id)
                        REFERENCES artifacts(artifact_id),
                    FOREIGN KEY (baseline_authority_head_approval_id)
                        REFERENCES approvals(approval_id),
                    FOREIGN KEY (decision_artifact_id)
                        REFERENCES artifacts(artifact_id),
                    FOREIGN KEY (resulting_approval_id)
                        REFERENCES approvals(approval_id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS one_active_refinement_per_duet
                ON refinement_cycles(duet_id)
                WHERE state IN (
                    'refining',
                    'awaiting_workflow_approval',
                    'awaiting_refinement_approval'
                );

                CREATE TABLE IF NOT EXISTS duet_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    duet_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (duet_id) REFERENCES duets(duet_id)
                );
                """
            )

    @staticmethod
    def _decode(row: sqlite3.Row, column: str = "record_json") -> dict[str, Any]:
        value = json.loads(row[column])
        if not isinstance(value, dict):
            raise DuetStoreError("stored record has an invalid top-level type")
        return value

    def create_duet(
        self,
        *,
        duet_id: str,
        identity: Mapping[str, Any],
        policy: Mapping[str, Any],
        state: str,
    ) -> None:
        now = time.time()
        identity_json = canonical_json(_object(identity, "identity"))
        policy_json = canonical_json(_object(policy, "policy"))
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT identity_json, policy_json FROM duets WHERE duet_id = ?",
                (duet_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["identity_json"] != identity_json
                    or existing["policy_json"] != policy_json
                ):
                    raise DuetConflictError(
                        "duet_id already names different immutable content"
                    )
                return
            connection.execute(
                "INSERT INTO duets "
                "(duet_id, identity_json, policy_json, state, "
                "authority_head_approval_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, NULL, ?, ?)",
                (duet_id, identity_json, policy_json, state, now, now),
            )

    def get_duet(self, duet_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM duets WHERE duet_id = ?", (duet_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "duet_id": row["duet_id"],
            "identity": json.loads(row["identity_json"]),
            "policy": json.loads(row["policy_json"]),
            "state": row["state"],
            "authority_head_approval_id": row["authority_head_approval_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def transition_state(
        self,
        duet_id: str,
        *,
        expected_state: str,
        expected_authority_head_approval_id: Optional[str],
        state: str,
    ) -> None:
        _require_state_transition(expected_state, state)
        with self.transaction() as connection:
            changed = connection.execute(
                "UPDATE duets SET state = ?, updated_at = ? "
                "WHERE duet_id = ? AND state = ? "
                "AND authority_head_approval_id IS ?",
                (
                    state,
                    time.time(),
                    duet_id,
                    expected_state,
                    expected_authority_head_approval_id,
                ),
            ).rowcount
            if changed != 1:
                if connection.execute(
                    "SELECT 1 FROM duets WHERE duet_id = ?",
                    (duet_id,),
                ).fetchone() is None:
                    raise DuetNotFoundError("unknown duet_id")
                raise DuetConflictError(
                    "Duet state or authority head changed concurrently"
                )

    def put_artifact(
        self,
        *,
        artifact_id: str,
        duet_id: str,
        kind: str,
        revision: int,
        content_hash: str,
        record: Mapping[str, Any],
    ) -> None:
        payload = canonical_json(_object(record, "artifact"))
        with self.transaction() as connection:
            self._put_artifact(
                connection,
                artifact_id=artifact_id,
                duet_id=duet_id,
                kind=kind,
                revision=revision,
                content_hash=content_hash,
                payload=payload,
            )

    @staticmethod
    def _put_artifact(
        connection: sqlite3.Connection,
        *,
        artifact_id: str,
        duet_id: str,
        kind: str,
        revision: int,
        content_hash: str,
        payload: str,
    ) -> None:
        immutable = (duet_id, kind, revision, content_hash, payload)
        existing = connection.execute(
            "SELECT duet_id, kind, revision, content_hash, record_json "
            "FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        if existing is not None:
            actual = tuple(existing[key] for key in existing.keys())
            if actual != immutable:
                raise DuetConflictError(
                    "artifact_id already names different immutable content"
                )
            return
        connection.execute(
            "INSERT INTO artifacts "
            "(artifact_id, duet_id, kind, revision, content_hash, "
            "record_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                artifact_id,
                duet_id,
                kind,
                revision,
                content_hash,
                payload,
                time.time(),
            ),
        )

    def _artifact(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "artifact_id": row["artifact_id"],
            "duet_id": row["duet_id"],
            "kind": row["kind"],
            "revision": row["revision"],
            "content_hash": row["content_hash"],
            "record": self._decode(row),
        }

    def get_artifact(self, artifact_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        return None if row is None else self._artifact(row)

    def latest_artifact(self, *, duet_id: str, kind: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM artifacts WHERE duet_id = ? AND kind = ? "
                "ORDER BY revision DESC, created_at DESC, artifact_id DESC "
                "LIMIT 1",
                (duet_id, kind),
            ).fetchone()
        return None if row is None else self._artifact(row)

    @staticmethod
    def _require_latest_artifact(
        connection: sqlite3.Connection,
        *,
        duet_id: str,
        kind: str,
        expected_artifact_id: Optional[str],
        expected_content_hash: Optional[str],
        expected_revision: Optional[int],
    ) -> None:
        expected = (
            expected_artifact_id,
            expected_content_hash,
            expected_revision,
        )
        if any(value is None for value in expected) and not all(
            value is None for value in expected
        ):
            raise ValueError(
                "latest artifact identity, hash, and revision move together"
            )
        row = connection.execute(
            "SELECT artifact_id, content_hash, revision FROM artifacts "
            "WHERE duet_id = ? AND kind = ? "
            "ORDER BY revision DESC, created_at DESC, artifact_id DESC "
            "LIMIT 1",
            (duet_id, kind),
        ).fetchone()
        actual = (
            (None, None, None)
            if row is None
            else (
                row["artifact_id"],
                row["content_hash"],
                row["revision"],
            )
        )
        if actual != expected:
            raise DuetConflictError(
                f"latest {kind} artifact changed concurrently"
            )

    def artifact_page(
        self, *, duet_id: str, kinds: tuple[str, ...], limit: int = 20,
        after: str | None = None, episode_id: str | None = None,
        recording_run_id: str | None = None,
        experiment_id: str | None = None,
    ) -> dict[str, Any]:
        """Bounded indexed history; no journal scans or decoding unrelated rows."""
        if not kinds or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("artifact history needs kinds and a limit from 1 to 100")
        terms = ["duet_id = ?", "kind IN (" + ",".join("?" for _ in kinds) + ")"]
        values: list[Any] = [duet_id, *kinds]
        for path, selected in (
            ("$.episode_id", episode_id),
            ("$.registration_ref.run_id", recording_run_id),
            ("$.experiment_id", experiment_id),
        ):
            if selected is not None:
                terms.append(f"json_extract(record_json, '{path}') = ?")
                values.append(selected)
        with self._lock:
            if after is not None:
                cursor = self._connection.execute(
                    "SELECT created_at FROM artifacts WHERE " + " AND ".join(terms)
                    + " AND artifact_id = ?", (*values, after),
                ).fetchone()
                if cursor is None:
                    raise ValueError("history cursor is outside the selected owner or record kinds")
                terms.append("(created_at < ? OR (created_at = ? AND artifact_id < ?))")
                values.extend((cursor["created_at"], cursor["created_at"], after))
            rows = self._connection.execute(
                "SELECT * FROM artifacts WHERE " + " AND ".join(terms)
                + " ORDER BY created_at DESC, artifact_id DESC LIMIT ?",
                (*values, limit + 1),
            ).fetchall()
        return {
            "items": [self._artifact(row) for row in rows[:limit]],
            "next_cursor": rows[limit - 1]["artifact_id"] if len(rows) > limit else None,
        }

    def artifacts_by_kind(
        self,
        *,
        duet_id: str,
        kind: str,
    ) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM artifacts WHERE duet_id = ? AND kind = ? "
                "ORDER BY created_at, artifact_id",
                (duet_id, kind),
            ).fetchall()
        return tuple(self._artifact(row) for row in rows)

    def put_artifacts_with_transition(
        self,
        *,
        artifacts: tuple[Mapping[str, Any], ...],
        duet_id: str,
        expected_latest_artifact_kind: str,
        expected_latest_artifact_id: Optional[str],
        expected_latest_artifact_hash: Optional[str],
        expected_latest_artifact_revision: Optional[int],
        expected_state: str,
        expected_authority_head_approval_id: Optional[str],
        state: str,
        event_type: str,
        provenance: str,
        event_record: Mapping[str, Any],
    ) -> None:
        """Persist immutable artifacts with one exact Duet state transition."""

        _require_state_transition(expected_state, state)
        with self.transaction() as connection:
            self._require_latest_artifact(
                connection,
                duet_id=duet_id,
                kind=expected_latest_artifact_kind,
                expected_artifact_id=expected_latest_artifact_id,
                expected_content_hash=expected_latest_artifact_hash,
                expected_revision=expected_latest_artifact_revision,
            )
            for spec in artifacts:
                self._put_artifact_spec(connection, spec)
            changed = connection.execute(
                "UPDATE duets SET state = ?, updated_at = ? "
                "WHERE duet_id = ? AND state = ? "
                "AND authority_head_approval_id IS ?",
                (
                    state,
                    time.time(),
                    duet_id,
                    expected_state,
                    expected_authority_head_approval_id,
                ),
            ).rowcount
            if changed != 1:
                if connection.execute(
                    "SELECT 1 FROM duets WHERE duet_id = ?",
                    (duet_id,),
                ).fetchone() is None:
                    raise DuetNotFoundError("unknown duet_id")
                raise DuetConflictError(
                    "Duet state or authority head changed concurrently"
                )
            self._append_event(
                connection,
                duet_id=duet_id,
                event_type=event_type,
                provenance=provenance,
                record=event_record,
            )

    def put_artifacts_with_events(
        self,
        *,
        artifacts: tuple[Mapping[str, Any], ...],
        events: tuple[Mapping[str, Any], ...],
        idempotency_artifact_ids: tuple[str, ...],
        duet_id: str,
        expected_state: str,
        expected_authority_head_approval_id: Optional[str],
    ) -> bool:
        """Atomically persist immutable artifacts and their exact Duet events."""

        if not artifacts or not events:
            raise ValueError("an atomic Duet write requires artifacts and events")
        artifact_ids = tuple(
            spec.get("artifact_id") if isinstance(spec, Mapping) else None
            for spec in artifacts
        )
        if (
            not idempotency_artifact_ids
            or len(set(idempotency_artifact_ids))
            != len(idempotency_artifact_ids)
            or any(
                not isinstance(artifact_id, str)
                or not artifact_id
                or artifact_id not in artifact_ids
                for artifact_id in idempotency_artifact_ids
            )
        ):
            raise ValueError(
                "idempotency artifact IDs must uniquely name supplied artifacts"
            )
        if any(
            not isinstance(spec, Mapping) or spec.get("duet_id") != duet_id
            for spec in artifacts
        ):
            raise ValueError("atomic artifact belongs to another Duet")
        event_fields = {"event_type", "provenance", "record"}
        with self.transaction() as connection:
            placeholders = ", ".join("?" for _ in idempotency_artifact_ids)
            existing_markers = connection.execute(
                "SELECT artifact_id FROM artifacts WHERE artifact_id IN "
                f"({placeholders})",
                idempotency_artifact_ids,
            ).fetchall()
            if existing_markers:
                if len(existing_markers) != len(idempotency_artifact_ids):
                    raise DuetConflictError(
                        "atomic artifact submission is only partially present"
                    )
                existing_artifact_ids = {
                    row["artifact_id"]
                    for row in connection.execute(
                        "SELECT artifact_id FROM artifacts WHERE artifact_id IN "
                        f"({', '.join('?' for _ in artifact_ids)})",
                        artifact_ids,
                    ).fetchall()
                }
                if existing_artifact_ids != set(artifact_ids):
                    raise DuetConflictError(
                        "atomic artifact submission is incomplete"
                    )
                for spec in artifacts:
                    self._put_artifact_spec(connection, spec)
                return False
            duet = connection.execute(
                "SELECT state, authority_head_approval_id FROM duets "
                "WHERE duet_id = ?",
                (duet_id,),
            ).fetchone()
            if duet is None:
                raise DuetNotFoundError("unknown duet_id")
            if (
                duet["state"] != expected_state
                or duet["authority_head_approval_id"]
                != expected_authority_head_approval_id
            ):
                raise DuetConflictError(
                    "Duet state or authority head changed concurrently"
                )
            for spec in artifacts:
                self._put_artifact_spec(connection, spec)
            for event in events:
                if not isinstance(event, Mapping) or set(event) != event_fields:
                    raise ValueError("atomic event spec has an invalid shape")
                self._append_event(
                    connection,
                    duet_id=duet_id,
                    event_type=event["event_type"],
                    provenance=event["provenance"],
                    record=event["record"],
                )
            return True

    @staticmethod
    def _refinement_cycle(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "refinement_id": row["refinement_id"],
            "duet_id": row["duet_id"],
            "ordinal": row["ordinal"],
            "baseline_artifact_id": row["baseline_artifact_id"],
            "proposal_artifact_id": row["proposal_artifact_id"],
            "baseline_authority_head_approval_id": row[
                "baseline_authority_head_approval_id"
            ],
            "decision_artifact_id": row["decision_artifact_id"],
            "resulting_approval_id": row["resulting_approval_id"],
            "state": row["state"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_refinement_cycle(
        self,
        refinement_id: str,
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM refinement_cycles WHERE refinement_id = ?",
                (refinement_id,),
            ).fetchone()
        return None if row is None else self._refinement_cycle(row)

    def active_refinement_cycle(
        self,
        duet_id: str,
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM refinement_cycles WHERE duet_id = ? "
                "AND state IN ('refining', 'awaiting_workflow_approval', "
                "'awaiting_refinement_approval') "
                "ORDER BY ordinal DESC LIMIT 1",
                (duet_id,),
            ).fetchone()
        return None if row is None else self._refinement_cycle(row)

    def begin_refinement_cycle(
        self,
        *,
        duet_id: str,
        baseline_artifact_id: str,
        proposal_artifact_id: str,
        expected_authority_head_approval_id: str,
        event_type: str,
        provenance: str,
        event_record: Mapping[str, Any],
    ) -> dict[str, Any]:
        with self.transaction() as connection:
            artifacts = connection.execute(
                "SELECT artifact_id, duet_id FROM artifacts "
                "WHERE artifact_id IN (?, ?)",
                (baseline_artifact_id, proposal_artifact_id),
            ).fetchall()
            if len(artifacts) != 2 or any(
                row["duet_id"] != duet_id for row in artifacts
            ):
                raise DuetNotFoundError(
                    "refinement baseline or proposal artifact is missing"
                )
            ordinal_row = connection.execute(
                "SELECT COALESCE(MAX(ordinal), 0) + 1 AS next_ordinal "
                "FROM refinement_cycles WHERE duet_id = ?",
                (duet_id,),
            ).fetchone()
            ordinal = int(ordinal_row["next_ordinal"])
            refinement_id = content_id(
                "refinement_cycle",
                {
                    "duet_id": duet_id,
                    "ordinal": ordinal,
                    "baseline_artifact_id": baseline_artifact_id,
                    "proposal_artifact_id": proposal_artifact_id,
                    "baseline_authority_head_approval_id": (
                        expected_authority_head_approval_id
                    ),
                },
            ).value
            now = time.time()
            changed = connection.execute(
                "UPDATE duets SET state = 'refining', updated_at = ? "
                "WHERE duet_id = ? AND state = 'sealed' "
                "AND authority_head_approval_id = ?",
                (now, duet_id, expected_authority_head_approval_id),
            ).rowcount
            if changed != 1:
                raise DuetConflictError(
                    "sealed Duet authority changed before refinement began"
                )
            connection.execute(
                "INSERT INTO refinement_cycles "
                "(refinement_id, duet_id, ordinal, baseline_artifact_id, "
                "proposal_artifact_id, baseline_authority_head_approval_id, "
                "decision_artifact_id, resulting_approval_id, state, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 'refining', ?, ?)",
                (
                    refinement_id,
                    duet_id,
                    ordinal,
                    baseline_artifact_id,
                    proposal_artifact_id,
                    expected_authority_head_approval_id,
                    now,
                    now,
                ),
            )
            self._append_event(
                connection,
                duet_id=duet_id,
                event_type=event_type,
                provenance=provenance,
                record={
                    **_object(event_record, "event"),
                    "refinement_id": refinement_id,
                },
            )
            row = connection.execute(
                "SELECT * FROM refinement_cycles WHERE refinement_id = ?",
                (refinement_id,),
            ).fetchone()
            if row is None:
                raise DuetStoreError("refinement cycle was not durably stored")
            return self._refinement_cycle(row)

    def attach_refinement_decision(
        self,
        *,
        refinement_id: str,
        duet_id: str,
        decision_artifact_id: str,
        artifacts: tuple[Mapping[str, Any], ...],
        expected_latest_artifact_kind: str,
        expected_latest_artifact_id: Optional[str],
        expected_latest_artifact_hash: Optional[str],
        expected_latest_artifact_revision: Optional[int],
        expected_authority_head_approval_id: str,
        state: str,
        event_type: str,
        provenance: str,
        event_record: Mapping[str, Any],
    ) -> None:
        if state not in {
            "awaiting_workflow_approval",
            "awaiting_refinement_approval",
        }:
            raise ValueError("refinement decision state is invalid")
        _require_state_transition("refining", state)
        with self.transaction() as connection:
            self._require_latest_artifact(
                connection,
                duet_id=duet_id,
                kind=expected_latest_artifact_kind,
                expected_artifact_id=expected_latest_artifact_id,
                expected_content_hash=expected_latest_artifact_hash,
                expected_revision=expected_latest_artifact_revision,
            )
            cycle = connection.execute(
                "SELECT state, baseline_authority_head_approval_id, "
                "decision_artifact_id FROM refinement_cycles "
                "WHERE refinement_id = ? AND duet_id = ?",
                (refinement_id, duet_id),
            ).fetchone()
            if (
                cycle is None
                or cycle["state"] != "refining"
                or cycle["decision_artifact_id"] is not None
                or cycle["baseline_authority_head_approval_id"]
                != expected_authority_head_approval_id
            ):
                raise DuetConflictError(
                    "refinement cycle cannot accept this decision"
                )
            for spec in artifacts:
                self._put_artifact_spec(connection, spec)
            decision = connection.execute(
                "SELECT duet_id FROM artifacts WHERE artifact_id = ?",
                (decision_artifact_id,),
            ).fetchone()
            if decision is None or decision["duet_id"] != duet_id:
                raise DuetNotFoundError("refinement decision artifact is missing")
            now = time.time()
            connection.execute(
                "UPDATE refinement_cycles SET decision_artifact_id = ?, "
                "state = ?, updated_at = ? WHERE refinement_id = ?",
                (decision_artifact_id, state, now, refinement_id),
            )
            changed = connection.execute(
                "UPDATE duets SET state = ?, updated_at = ? "
                "WHERE duet_id = ? AND state = 'refining' "
                "AND authority_head_approval_id = ?",
                (
                    state,
                    now,
                    duet_id,
                    expected_authority_head_approval_id,
                ),
            ).rowcount
            if changed != 1:
                raise DuetConflictError(
                    "Duet authority changed before the decision was attached"
                )
            self._append_event(
                connection,
                duet_id=duet_id,
                event_type=event_type,
                provenance=provenance,
                record=event_record,
            )

    def close_refinement_cycle(
        self,
        *,
        refinement_id: str,
        duet_id: str,
        expected_authority_head_approval_id: str,
        terminal_state: str,
        event_type: str,
        provenance: str,
        event_record: Mapping[str, Any],
    ) -> None:
        if terminal_state not in {"rejected", "cancelled"}:
            raise ValueError("refinement terminal state must be rejected or cancelled")
        with self.transaction() as connection:
            cycle = connection.execute(
                "SELECT state, baseline_authority_head_approval_id "
                "FROM refinement_cycles WHERE refinement_id = ? AND duet_id = ?",
                (refinement_id, duet_id),
            ).fetchone()
            active_states = {
                "refining",
                "awaiting_workflow_approval",
                "awaiting_refinement_approval",
            }
            if (
                cycle is None
                or cycle["state"] not in active_states
                or cycle["baseline_authority_head_approval_id"]
                != expected_authority_head_approval_id
            ):
                raise DuetConflictError("refinement cycle is not active")
            now = time.time()
            connection.execute(
                "UPDATE refinement_cycles SET state = ?, updated_at = ? "
                "WHERE refinement_id = ?",
                (terminal_state, now, refinement_id),
            )
            changed = connection.execute(
                "UPDATE duets SET state = 'sealed', updated_at = ? "
                "WHERE duet_id = ? AND state = ? "
                "AND authority_head_approval_id = ?",
                (
                    now,
                    duet_id,
                    cycle["state"],
                    expected_authority_head_approval_id,
                ),
            ).rowcount
            if changed != 1:
                raise DuetConflictError(
                    "Duet authority changed before refinement closed"
                )
            self._append_event(
                connection,
                duet_id=duet_id,
                event_type=event_type,
                provenance=provenance,
                record=event_record,
            )

    @staticmethod
    def _put_approval(
        connection: sqlite3.Connection,
        record: Mapping[str, Any],
    ) -> None:
        payload = canonical_json(record)
        artifact = connection.execute(
            "SELECT duet_id, content_hash, revision FROM artifacts "
            "WHERE artifact_id = ?",
            (record["artifact_id"],),
        ).fetchone()
        if artifact is None:
            raise DuetNotFoundError("approval artifact does not exist")
        if (
            artifact["duet_id"] != record["duet_id"]
            or artifact["content_hash"] != record["content_hash"]
            or artifact["revision"] != record["revision"]
        ):
            raise DuetConflictError(
                "approval does not match the exact artifact revision"
            )
        existing = connection.execute(
            "SELECT record_json FROM approvals WHERE approval_id = ?",
            (record["approval_id"],),
        ).fetchone()
        if existing is not None:
            if existing["record_json"] != payload:
                raise DuetConflictError(
                    "approval_id already names different content"
                )
            return
        predecessor = record["predecessor_approval_id"]
        if predecessor is not None:
            predecessor_row = connection.execute(
                "SELECT duet_id FROM approvals WHERE approval_id = ?",
                (predecessor,),
            ).fetchone()
            if predecessor_row is None:
                raise DuetNotFoundError("predecessor approval does not exist")
            if predecessor_row["duet_id"] != record["duet_id"]:
                raise DuetConflictError(
                    "predecessor approval belongs to another Duet"
                )
        connection.execute(
            "INSERT INTO approvals "
            "(approval_id, duet_id, human_authority_id, kind, artifact_id, "
            "content_hash, revision, predecessor_approval_id, record_json, "
            "revoked_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
            (
                record["approval_id"],
                record["duet_id"],
                record["human_authority_id"],
                record["kind"],
                record["artifact_id"],
                record["content_hash"],
                record["revision"],
                predecessor,
                payload,
                time.time(),
            ),
        )

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        *,
        duet_id: str,
        event_type: str,
        provenance: str,
        record: Mapping[str, Any],
    ) -> int:
        cursor = connection.execute(
            "INSERT INTO duet_events "
            "(duet_id, event_type, provenance, record_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                duet_id,
                event_type,
                provenance,
                canonical_json(_object(record, "event")),
                time.time(),
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _put_artifact_spec(
        connection: sqlite3.Connection,
        spec: Mapping[str, Any],
    ) -> None:
        required = {
            "artifact_id",
            "duet_id",
            "kind",
            "revision",
            "content_hash",
            "record",
        }
        if not isinstance(spec, Mapping) or set(spec) != required:
            raise ValueError("artifact spec has an invalid shape")
        DuetStore._put_artifact(
            connection,
            artifact_id=spec["artifact_id"],
            duet_id=spec["duet_id"],
            kind=spec["kind"],
            revision=spec["revision"],
            content_hash=spec["content_hash"],
            payload=canonical_json(_object(spec["record"], "artifact")),
        )

    def commit_approval(
        self,
        *,
        approval: Mapping[str, Any],
        artifacts: tuple[Mapping[str, Any], ...],
        expected_latest_artifact_kind: str,
        expected_latest_artifact_id: str,
        expected_latest_artifact_hash: str,
        expected_latest_artifact_revision: int,
        expected_state: str,
        refinement_id: Optional[str],
        event_type: str,
        provenance: str,
        event_record: Mapping[str, Any],
    ) -> None:
        """Atomically persist approval artifacts and advance authority/state."""

        _require_state_transition(expected_state, "sealed")
        approval_record = _object(approval, "approval")
        with self.transaction() as connection:
            duet = connection.execute(
                "SELECT state, authority_head_approval_id FROM duets "
                "WHERE duet_id = ?",
                (approval_record["duet_id"],),
            ).fetchone()
            if duet is None:
                raise DuetNotFoundError("unknown duet_id")
            if duet["state"] != expected_state:
                raise DuetConflictError("Duet approval state changed concurrently")
            if (
                duet["authority_head_approval_id"]
                != approval_record["predecessor_approval_id"]
            ):
                raise DuetConflictError(
                    "approval predecessor is not the current authority head"
                )
            self._require_latest_artifact(
                connection,
                duet_id=approval_record["duet_id"],
                kind=expected_latest_artifact_kind,
                expected_artifact_id=expected_latest_artifact_id,
                expected_content_hash=expected_latest_artifact_hash,
                expected_revision=expected_latest_artifact_revision,
            )
            for spec in artifacts:
                self._put_artifact_spec(connection, spec)
            self._put_approval(connection, approval_record)
            if refinement_id is not None:
                cycle = connection.execute(
                    "SELECT state, decision_artifact_id FROM refinement_cycles "
                    "WHERE refinement_id = ? AND duet_id = ?",
                    (refinement_id, approval_record["duet_id"]),
                ).fetchone()
                if cycle is None or cycle["state"] != expected_state:
                    raise DuetConflictError(
                        "refinement cycle is not awaiting this approval"
                    )
                if cycle["decision_artifact_id"] is None:
                    raise DuetConflictError(
                        "refinement cycle has no exact decision to approve"
                    )
                connection.execute(
                    "UPDATE refinement_cycles SET state = 'approved', "
                    "resulting_approval_id = ?, updated_at = ? "
                    "WHERE refinement_id = ?",
                    (
                        approval_record["approval_id"],
                        time.time(),
                        refinement_id,
                    ),
                )
            changed = connection.execute(
                "UPDATE duets SET state = 'sealed', "
                "authority_head_approval_id = ?, updated_at = ? "
                "WHERE duet_id = ? AND state = ? "
                "AND authority_head_approval_id IS ?",
                (
                    approval_record["approval_id"],
                    time.time(),
                    approval_record["duet_id"],
                    expected_state,
                    approval_record["predecessor_approval_id"],
                ),
            ).rowcount
            if changed != 1:
                raise DuetConflictError(
                    "Duet state or authority head changed concurrently"
                )
            self._append_event(
                connection,
                duet_id=approval_record["duet_id"],
                event_type=event_type,
                provenance=provenance,
                record=event_record,
            )

    def get_approval(self, approval_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
        if row is None:
            return None
        record = self._decode(row)
        record["revoked"] = row["revoked_at"] is not None
        return record

    def latest_approval(self, *, duet_id: str, kind: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM approvals WHERE duet_id = ? AND kind = ? "
                "ORDER BY created_at DESC, approval_id DESC LIMIT 1",
                (duet_id, kind),
            ).fetchone()
        if row is None:
            return None
        record = self._decode(row)
        record["revoked"] = row["revoked_at"] is not None
        return record

    def append_event(
        self,
        *,
        duet_id: str,
        event_type: str,
        provenance: str,
        record: Mapping[str, Any],
    ) -> int:
        with self.transaction() as connection:
            return self._append_event(
                connection,
                duet_id=duet_id,
                event_type=event_type,
                provenance=provenance,
                record=record,
            )

    def events(self, duet_id: str) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM duet_events WHERE duet_id = ? ORDER BY sequence",
                (duet_id,),
            ).fetchall()
        return tuple(
            {
                "sequence": row["sequence"],
                "event_type": row["event_type"],
                "provenance": row["provenance"],
                "record": json.loads(row["record_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        )


__all__ = [
    "DuetConflictError",
    "DuetNotFoundError",
    "DuetStore",
    "DuetStoreError",
]
