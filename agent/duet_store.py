"""Durable, append-oriented storage for Duet design sessions.

The store is intentionally ignorant of model prompts.  It persists canonical
typed records, exact content hashes, approvals, accepted evidence identities,
unit-boundary decisions, and atomically launched workflow nodes.
"""

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
        # sqlite3.executescript owns its transaction boundary even when the
        # connection uses manual isolation; wrapping it in transaction() would
        # leave no active transaction for that context manager to commit.
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

                CREATE TABLE IF NOT EXISTS drafts (
                    duet_id TEXT NOT NULL,
                    draft_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    ready INTEGER NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (duet_id, revision),
                    UNIQUE (draft_id, revision),
                    FOREIGN KEY (duet_id) REFERENCES duets(duet_id)
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    duet_id TEXT NOT NULL,
                    creator_episode_id TEXT,
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

                CREATE TABLE IF NOT EXISTS creators (
                    creator_episode_id TEXT PRIMARY KEY,
                    duet_id TEXT NOT NULL,
                    contract_artifact_id TEXT NOT NULL UNIQUE,
                    contract_hash TEXT NOT NULL,
                    approval_id TEXT NOT NULL,
                    parent_creator_episode_id TEXT,
                    design_artifact_id TEXT,
                    state TEXT NOT NULL,
                    units_consumed INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (duet_id) REFERENCES duets(duet_id),
                    FOREIGN KEY (contract_artifact_id) REFERENCES artifacts(artifact_id),
                    FOREIGN KEY (approval_id) REFERENCES approvals(approval_id)
                );

                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    duet_id TEXT NOT NULL,
                    creator_episode_id TEXT NOT NULL,
                    evidence_kind_id TEXT NOT NULL,
                    acceptance_source_id TEXT NOT NULL,
                    observation_json TEXT NOT NULL,
                    source_artifact_id TEXT,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (duet_id) REFERENCES duets(duet_id),
                    FOREIGN KEY (creator_episode_id) REFERENCES creators(creator_episode_id)
                );

                CREATE TABLE IF NOT EXISTS duet_inbox (
                    message_id TEXT PRIMARY KEY,
                    duet_id TEXT NOT NULL,
                    creator_episode_id TEXT NOT NULL,
                    expected_unit_index INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    applied_unit_index INTEGER,
                    created_at REAL NOT NULL,
                    applied_at REAL,
                    FOREIGN KEY (duet_id) REFERENCES duets(duet_id),
                    FOREIGN KEY (creator_episode_id) REFERENCES creators(creator_episode_id)
                );

                CREATE TABLE IF NOT EXISTS launches (
                    launch_id TEXT PRIMARY KEY,
                    duet_id TEXT NOT NULL,
                    workflow_artifact_id TEXT NOT NULL UNIQUE,
                    workflow_hash TEXT NOT NULL,
                    approval_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (duet_id) REFERENCES duets(duet_id),
                    FOREIGN KEY (workflow_artifact_id) REFERENCES artifacts(artifact_id),
                    FOREIGN KEY (approval_id) REFERENCES approvals(approval_id)
                );

                CREATE TABLE IF NOT EXISTS launched_episodes (
                    episode_id TEXT PRIMARY KEY,
                    launch_id TEXT NOT NULL,
                    duet_id TEXT NOT NULL,
                    designed_by_episode_id TEXT NOT NULL,
                    workflow_parent_episode_id TEXT,
                    local_id TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    contract_hash TEXT NOT NULL,
                    contract_json TEXT NOT NULL,
                    UNIQUE (launch_id, local_id),
                    FOREIGN KEY (launch_id) REFERENCES launches(launch_id),
                    FOREIGN KEY (duet_id) REFERENCES duets(duet_id)
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
            columns = {
                row["name"]
                for row in self._connection.execute(
                    "PRAGMA table_info(creators)"
                ).fetchall()
            }
            if "parent_creator_episode_id" not in columns:
                self._connection.execute(
                    "ALTER TABLE creators ADD COLUMN parent_creator_episode_id TEXT"
                )
            if "design_artifact_id" not in columns:
                self._connection.execute(
                    "ALTER TABLE creators ADD COLUMN design_artifact_id TEXT"
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
                    raise DuetConflictError("duet_id already names different immutable content")
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

    def set_state(self, duet_id: str, state: str) -> None:
        with self.transaction() as connection:
            changed = connection.execute(
                "UPDATE duets SET state = ?, updated_at = ? WHERE duet_id = ?",
                (state, time.time(), duet_id),
            ).rowcount
            if changed != 1:
                raise DuetNotFoundError("unknown duet_id")

    def put_draft(
        self,
        *,
        duet_id: str,
        draft_id: str,
        revision: int,
        content_hash: str,
        ready: bool,
        record: Mapping[str, Any],
        expected_previous_revision: Optional[int],
    ) -> None:
        payload = canonical_json(_object(record, "draft"))
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT revision FROM drafts WHERE duet_id = ? ORDER BY revision DESC LIMIT 1",
                (duet_id,),
            ).fetchone()
            actual = None if row is None else int(row["revision"])
            if actual != expected_previous_revision:
                raise DuetConflictError(
                    f"draft revision changed: expected {expected_previous_revision}, found {actual}"
                )
            if revision != (0 if actual is None else actual + 1):
                raise DuetConflictError("draft revisions must be contiguous")
            connection.execute(
                "INSERT INTO drafts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    duet_id,
                    draft_id,
                    revision,
                    content_hash,
                    int(ready),
                    payload,
                    time.time(),
                ),
            )

    def latest_draft(self, duet_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT record_json FROM drafts WHERE duet_id = ? ORDER BY revision DESC LIMIT 1",
                (duet_id,),
            ).fetchone()
        return None if row is None else self._decode(row)

    def put_artifact(
        self,
        *,
        artifact_id: str,
        duet_id: str,
        kind: str,
        revision: int,
        content_hash: str,
        record: Mapping[str, Any],
        creator_episode_id: Optional[str] = None,
    ) -> None:
        payload = canonical_json(_object(record, "artifact"))
        immutable = (duet_id, creator_episode_id, kind, revision, content_hash, payload)
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT duet_id, creator_episode_id, kind, revision, content_hash, record_json "
                "FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
            if existing is not None:
                actual = tuple(existing[key] for key in existing.keys())
                if actual != immutable:
                    raise DuetConflictError("artifact_id already names different immutable content")
                return
            connection.execute(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact_id,
                    duet_id,
                    creator_episode_id,
                    kind,
                    revision,
                    content_hash,
                    payload,
                    time.time(),
                ),
            )

    def get_artifact(self, artifact_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "artifact_id": row["artifact_id"],
            "duet_id": row["duet_id"],
            "creator_episode_id": row["creator_episode_id"],
            "kind": row["kind"],
            "revision": row["revision"],
            "content_hash": row["content_hash"],
            "record": self._decode(row),
        }

    def latest_artifact(
        self,
        *,
        duet_id: str,
        kind: str,
        creator_episode_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        clauses = ["duet_id = ?", "kind = ?"]
        parameters: list[Any] = [duet_id, kind]
        if creator_episode_id is not None:
            clauses.append("creator_episode_id = ?")
            parameters.append(creator_episode_id)
        query = (
            "SELECT * FROM artifacts WHERE "
            + " AND ".join(clauses)
            + " ORDER BY revision DESC, created_at DESC LIMIT 1"
        )
        with self._lock:
            row = self._connection.execute(query, parameters).fetchone()
        if row is None:
            return None
        return {
            "artifact_id": row["artifact_id"],
            "duet_id": row["duet_id"],
            "creator_episode_id": row["creator_episode_id"],
            "kind": row["kind"],
            "revision": row["revision"],
            "content_hash": row["content_hash"],
            "record": self._decode(row),
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
        return tuple(
            {
                "artifact_id": row["artifact_id"],
                "duet_id": row["duet_id"],
                "creator_episode_id": row["creator_episode_id"],
                "kind": row["kind"],
                "revision": row["revision"],
                "content_hash": row["content_hash"],
                "record": self._decode(row),
            }
            for row in rows
        )

    def put_approval(self, record: Mapping[str, Any]) -> None:
        record = _object(record, "approval")
        payload = canonical_json(record)
        with self.transaction() as connection:
            artifact = connection.execute(
                "SELECT duet_id, content_hash, revision FROM artifacts WHERE artifact_id = ?",
                (record["artifact_id"],),
            ).fetchone()
            if artifact is None:
                raise DuetNotFoundError("approval artifact does not exist")
            if (
                artifact["duet_id"] != record["duet_id"]
                or artifact["content_hash"] != record["content_hash"]
                or artifact["revision"] != record["revision"]
            ):
                raise DuetConflictError("approval does not match the exact artifact revision")
            existing = connection.execute(
                "SELECT record_json FROM approvals WHERE approval_id = ?",
                (record["approval_id"],),
            ).fetchone()
            if existing is not None:
                if existing["record_json"] != payload:
                    raise DuetConflictError("approval_id already names different content")
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

    def latest_approval(
        self,
        *,
        duet_id: str,
        kind: str,
    ) -> Optional[dict[str, Any]]:
        """Return the newest approval of one kind, including revocation state."""

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

    def admit_creator(
        self,
        *,
        creator_episode_id: str,
        duet_id: str,
        contract_artifact_id: str,
        contract_hash: str,
        approval_id: str,
        state: str,
        parent_creator_episode_id: Optional[str] = None,
        design_artifact_id: Optional[str] = None,
    ) -> bool:
        now = time.time()
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM creators WHERE contract_artifact_id = ?",
                (contract_artifact_id,),
            ).fetchone()
            if existing is not None:
                expected = (
                    creator_episode_id,
                    duet_id,
                    contract_hash,
                    approval_id,
                    parent_creator_episode_id,
                    design_artifact_id,
                )
                actual = (
                    existing["creator_episode_id"],
                    existing["duet_id"],
                    existing["contract_hash"],
                    existing["approval_id"],
                    existing["parent_creator_episode_id"],
                    existing["design_artifact_id"],
                )
                if actual != expected:
                    raise DuetConflictError("creator admission conflicts with persisted content")
                return False
            connection.execute(
                "INSERT INTO creators "
                "(creator_episode_id, duet_id, contract_artifact_id, "
                "contract_hash, approval_id, parent_creator_episode_id, "
                "design_artifact_id, state, units_consumed, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                (
                    creator_episode_id,
                    duet_id,
                    contract_artifact_id,
                    contract_hash,
                    approval_id,
                    parent_creator_episode_id,
                    design_artifact_id,
                    state,
                    now,
                    now,
                ),
            )
            return True

    def get_creator(self, creator_episode_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM creators WHERE creator_episode_id = ?",
                (creator_episode_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def latest_creator(self, duet_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM creators WHERE duet_id = ? "
                "AND parent_creator_episode_id IS NULL "
                "ORDER BY created_at DESC, creator_episode_id DESC LIMIT 1",
                (duet_id,),
            ).fetchone()
        return None if row is None else dict(row)

    def put_creator_progress(
        self,
        *,
        artifact_id: str,
        duet_id: str,
        creator_episode_id: str,
        sequence: int,
        state: str,
        content_hash: str,
        record: Mapping[str, Any],
        provenance: str,
    ) -> bool:
        """Atomically persist a closed progress envelope and advance status."""

        payload = canonical_json(_object(record, "Creator progress"))
        now = time.time()
        with self.transaction() as connection:
            creator = connection.execute(
                "SELECT duet_id, units_consumed, parent_creator_episode_id "
                "FROM creators "
                "WHERE creator_episode_id = ?",
                (creator_episode_id,),
            ).fetchone()
            if creator is None:
                raise DuetNotFoundError("unknown Creator Episode")
            if creator["duet_id"] != duet_id:
                raise DuetConflictError("Creator progress belongs to another Duet")
            if sequence < int(creator["units_consumed"]):
                raise DuetConflictError("Creator progress sequence moved backwards")
            existing = connection.execute(
                "SELECT duet_id, creator_episode_id, kind, revision, "
                "content_hash, record_json FROM artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
            immutable = (
                duet_id,
                creator_episode_id,
                "creator_progress",
                sequence,
                content_hash,
                payload,
            )
            if existing is not None:
                actual = tuple(existing[key] for key in existing.keys())
                if actual != immutable:
                    raise DuetConflictError(
                        "Creator progress artifact names different content"
                    )
                return False
            connection.execute(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    artifact_id,
                    duet_id,
                    creator_episode_id,
                    "creator_progress",
                    sequence,
                    content_hash,
                    payload,
                    now,
                ),
            )
            connection.execute(
                "UPDATE creators SET state = ?, units_consumed = ?, updated_at = ? "
                "WHERE creator_episode_id = ?",
                (state, sequence, now, creator_episode_id),
            )
            if creator["parent_creator_episode_id"] is None:
                connection.execute(
                    "UPDATE duets SET state = ?, updated_at = ? WHERE duet_id = ?",
                    (state, now, duet_id),
                )
            connection.execute(
                "INSERT INTO duet_events "
                "(duet_id, event_type, provenance, record_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (duet_id, "creator_progress", provenance, payload, now),
            )
            return True

    def register_evidence(
        self,
        *,
        evidence_id: str,
        duet_id: str,
        creator_episode_id: str,
        evidence_kind_id: str,
        acceptance_source_id: str,
        observation: Mapping[str, Any],
        source_artifact_id: Optional[str] = None,
    ) -> None:
        payload = canonical_json(_object(observation, "evidence observation"))
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
            ).fetchone()
            if existing is not None:
                immutable = (
                    duet_id,
                    creator_episode_id,
                    evidence_kind_id,
                    acceptance_source_id,
                    payload,
                    source_artifact_id,
                )
                actual = tuple(
                    existing[name]
                    for name in (
                        "duet_id",
                        "creator_episode_id",
                        "evidence_kind_id",
                        "acceptance_source_id",
                        "observation_json",
                        "source_artifact_id",
                    )
                )
                if actual != immutable:
                    raise DuetConflictError("evidence_id already names different content")
                return
            connection.execute(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evidence_id,
                    duet_id,
                    creator_episode_id,
                    evidence_kind_id,
                    acceptance_source_id,
                    payload,
                    source_artifact_id,
                    time.time(),
                ),
            )

    def get_evidence(self, evidence_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
            ).fetchone()
        return None if row is None else {
            **dict(row),
            "observation": json.loads(row["observation_json"]),
        }

    def queue_message(self, record: Mapping[str, Any]) -> bool:
        record = _object(record, "Duet message")
        payload = canonical_json(record)
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT record_json FROM duet_inbox WHERE message_id = ?",
                (record["message_id"],),
            ).fetchone()
            if existing is not None:
                if existing["record_json"] != payload:
                    raise DuetConflictError("message_id already names different content")
                return False
            connection.execute(
                "INSERT INTO duet_inbox VALUES (?, ?, ?, ?, ?, ?, NULL, ?, NULL)",
                (
                    record["message_id"],
                    record["duet_id"],
                    record["creator_episode_id"],
                    record["expected_unit_index"],
                    record["kind"],
                    payload,
                    time.time(),
                ),
            )
            return True

    def claim_messages_at_boundary(
        self,
        *,
        creator_episode_id: str,
        unit_index: int,
    ) -> tuple[dict[str, Any], ...]:
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT message_id, record_json FROM duet_inbox "
                "WHERE creator_episode_id = ? AND applied_at IS NULL "
                "AND expected_unit_index <= ? ORDER BY created_at, message_id",
                (creator_episode_id, unit_index),
            ).fetchall()
            now = time.time()
            for row in rows:
                connection.execute(
                    "UPDATE duet_inbox SET applied_unit_index = ?, applied_at = ? "
                    "WHERE message_id = ? AND applied_at IS NULL",
                    (unit_index, now, row["message_id"]),
                )
        return tuple(json.loads(row["record_json"]) for row in rows)

    def launch_workflow(
        self,
        *,
        launch_record: Mapping[str, Any],
        episode_records: tuple[Mapping[str, Any], ...],
    ) -> bool:
        launch = _object(launch_record, "launch record")
        episodes = tuple(_object(item, "launched Episode") for item in episode_records)
        with self.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM launches WHERE workflow_artifact_id = ?",
                (launch["workflow_artifact_id"],),
            ).fetchone()
            if existing is not None:
                if existing["launch_id"] != launch["launch_id"]:
                    raise DuetConflictError("workflow was already launched differently")
                return False
            connection.execute(
                "INSERT INTO launches VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    launch["launch_id"],
                    launch["duet_id"],
                    launch["workflow_artifact_id"],
                    launch["workflow_hash"],
                    launch["approval_id"],
                    launch["run_id"],
                    time.time(),
                ),
            )
            for item in episodes:
                connection.execute(
                    "INSERT INTO launched_episodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item["episode_id"],
                        launch["launch_id"],
                        launch["duet_id"],
                        item["designed_by_episode_id"],
                        item["workflow_parent_episode_id"],
                        item["local_id"],
                        item["depth"],
                        item["contract_hash"],
                        canonical_json(item["contract"]),
                    ),
                )
            connection.execute(
                "UPDATE duets SET state = ?, updated_at = ? WHERE duet_id = ?",
                ("launched", time.time(), launch["duet_id"]),
            )
            return True

    def launched_episodes(self, launch_id: str) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM launched_episodes WHERE launch_id = ? ORDER BY depth, local_id",
                (launch_id,),
            ).fetchall()
        return tuple(
            {**dict(row), "contract": json.loads(row["contract_json"])}
            for row in rows
        )

    def latest_launch(self, duet_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM launches WHERE duet_id = ? "
                "ORDER BY created_at DESC, launch_id DESC LIMIT 1",
                (duet_id,),
            ).fetchone()
        return None if row is None else dict(row)

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
                "INSERT INTO duet_events (duet_id, event_type, provenance, record_json, created_at) "
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
