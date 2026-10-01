"""Durable, append-oriented storage for Duet design sessions."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Iterator, Mapping, Optional

from agent.duet_contracts import canonical_json


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
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            else:
                self._connection.execute("COMMIT")

    def _create_schema(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS duets (
                    duet_id TEXT PRIMARY KEY,
                    identity_json TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
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
                    record_json TEXT NOT NULL,
                    revoked_at REAL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (duet_id) REFERENCES duets(duet_id),
                    FOREIGN KEY (artifact_id) REFERENCES artifacts(artifact_id)
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
                "INSERT INTO duets VALUES (?, ?, ?, ?, ?, ?)",
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
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def rebind_duet_policy(
        self,
        *,
        duet_id: str,
        identity: Mapping[str, Any],
        policy: Mapping[str, Any],
    ) -> None:
        new_identity = _object(identity, "identity")
        old = self.get_duet(duet_id)
        if old is None:
            raise DuetNotFoundError("unknown duet_id")
        for name in ("duet_id", "human_authority_id", "conversation_id"):
            if old["identity"].get(name) != new_identity.get(name):
                raise DuetConflictError(
                    "duet_id already names different immutable authority"
                )
        with self.transaction() as connection:
            connection.execute(
                "UPDATE duets SET identity_json = ?, policy_json = ?, updated_at = ? "
                "WHERE duet_id = ?",
                (
                    canonical_json(new_identity),
                    canonical_json(_object(policy, "policy")),
                    time.time(),
                    duet_id,
                ),
            )

    def set_state(self, duet_id: str, state: str) -> None:
        with self.transaction() as connection:
            changed = connection.execute(
                "UPDATE duets SET state = ?, updated_at = ? WHERE duet_id = ?",
                (state, time.time(), duet_id),
            ).rowcount
            if changed != 1:
                raise DuetNotFoundError("unknown duet_id")

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
        immutable = (duet_id, kind, revision, content_hash, payload)
        with self.transaction() as connection:
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
                "(artifact_id, duet_id, kind, revision, content_hash, record_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
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
                "ORDER BY revision DESC, created_at DESC LIMIT 1",
                (duet_id, kind),
            ).fetchone()
        return None if row is None else self._artifact(row)

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

    def put_approval(self, record: Mapping[str, Any]) -> None:
        record = _object(record, "approval")
        payload = canonical_json(record)
        with self.transaction() as connection:
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
            connection.execute(
                "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                (
                    record["approval_id"],
                    record["duet_id"],
                    record["human_authority_id"],
                    record["kind"],
                    record["artifact_id"],
                    record["content_hash"],
                    record["revision"],
                    payload,
                    time.time(),
                ),
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
