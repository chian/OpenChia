"""One transactional derived index per Run, owned and rebuilt by RunStore.

The journal commits first. Summary and compact event facts then advance together.
The index is not an evidence store: queries never authorize execution or credit.
"""

from contextlib import contextmanager
import json
import os
import sqlite3
import stat

from agent.duet_contracts import canonical_json

from .facts import EventFact, event_fact
from .runs import RunRecord, advance_record, attach_evidence, initial_record


_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS summary (singleton INTEGER PRIMARY KEY CHECK(singleton=1), record_json TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS facts (sequence INTEGER PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, episode_id TEXT, kind TEXT NOT NULL, ordinal INTEGER NOT NULL, record_json TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS facts_kind_sequence ON facts(kind, sequence)",
    "CREATE INDEX IF NOT EXISTS facts_episode_kind_sequence ON facts(episode_id, kind, sequence)",
)


class RunRecordIndex:
    def __init__(self, store):
        self.store = store

    def _path(self, run_id):
        return self.store._records / f"{self.store._run_name(run_id)}.sqlite3"

    @contextmanager
    def connection(self, run_id, *, write=False):
        from ..store import RunStoreCorruption, _fsync_directory

        path = self._path(run_id)
        new_file = not path.exists()
        if not write and new_file:
            yield None
            return
        # Retain the RunStore's private-file convention and reject links.
        descriptor = os.open(path, (os.O_RDWR | os.O_CREAT if write else os.O_RDONLY) | os.O_NOFOLLOW, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise RunStoreCorruption("Run record index must be a regular file")
        finally:
            os.close(descriptor)
        connection = sqlite3.connect(path.as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RunStoreCorruption("unsupported Run record index version")
            if write and version == 0:
                for statement in _SCHEMA:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version = 1")
            yield None if not write and version == 0 else connection
            connection.execute("COMMIT")
            if write and new_file:
                # SQLite owns subsequent transaction durability; only a new
                # index adds a directory entry owned by this store.
                _fsync_directory(path.parent)
        except sqlite3.DatabaseError as exc:
            raise RunStoreCorruption("Run record index is unreadable or inconsistent") from exc
        finally:
            # An unfinished transaction rolls back all its compact facts. No
            # authoritative event or terminal evidence is removed.
            connection.close()

    def _load(self, connection, run_id):
        from ..store import RunStoreCorruption

        row = None if connection is None else connection.execute("SELECT record_json FROM summary WHERE singleton=1").fetchone()
        if row is None:
            return None
        try:
            value = RunRecord.from_record(json.loads(row["record_json"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise RunStoreCorruption("Run record contract or identity is invalid") from exc
        if value.run_id != run_id.value:
            raise RunStoreCorruption("Run record path and identity disagree")
        return value

    @staticmethod
    def _replace(connection, value):
        connection.execute(
            "INSERT INTO summary VALUES (1, ?) ON CONFLICT(singleton) DO UPDATE SET record_json=excluded.record_json",
            (canonical_json(value.as_record()),),
        )

    @staticmethod
    def _insert_fact(connection, event, *, logical_run_id=None):
        episode_id = None if event.episode_id is None else event.episode_id.value
        prior = connection.execute(
            "SELECT ordinal FROM facts WHERE episode_id IS ? AND kind=? ORDER BY sequence DESC LIMIT 1",
            (episode_id, event.kind.value),
        ).fetchone()
        value = event_fact(event, 0 if prior is None else prior["ordinal"] + 1, logical_run_id=logical_run_id)
        connection.execute(
            "INSERT INTO facts VALUES (?, ?, ?, ?, ?, ?)",
            (event.sequence, event.event_id.value, episode_id, event.kind.value, value.ordinal, canonical_json(value.as_record())),
        )

    def initialize(self, registration):
        with self.connection(registration.run_id, write=True) as connection:
            if self._load(connection, registration.run_id) is not None:
                return
            if (self.store._event_directory(registration.run_id) / f"{0:020d}.json").exists():
                return  # Older Runs require an explicit verified backfill.
            self._replace(connection, initial_record(registration))

    def event_committed(self, event):
        from ..contracts import RunEventKind

        logical_run_id = self.store.read_registration(event.run_id).logical_run_id if event.kind is RunEventKind.EPISODE_STARTED else None
        with self.connection(event.run_id, write=True) as connection:
            prior = self._load(connection, event.run_id)
            if prior is None or prior.activity.events != event.sequence:
                return  # A query reports the gap; never silently skip an event.
            next_record = advance_record(prior, event)
            self._insert_fact(connection, event, logical_run_id=logical_run_id)
            self._replace(connection, next_record)

    def evidence_committed(self, evidence):
        with self.connection(evidence.run_id, write=True) as connection:
            prior = self._load(connection, evidence.run_id)
            if prior is None or prior.activity.events != evidence.event_count:
                return
            self._replace(connection, attach_evidence(prior, evidence))

    def inspect(self, run_id):
        registration = self.store.read_registration(run_id)
        with self.connection(run_id) as connection:
            return self.inspect_record(registration, self._load(connection, run_id))

    def inspect_record(self, registration, value):
        from ..store import RunStoreCorruption

        run_id = registration.run_id
        status = "unavailable"
        if value is not None:
            if value.registration_hash != registration.registration_hash.value:
                raise RunStoreCorruption("Run record belongs to another registration")
            next_event = self.store._event_directory(run_id) / f"{value.activity.events:020d}.json"
            status = "behind" if next_event.exists() else "current"
            if value.through_event is not None:
                last_event = self.store._event_directory(run_id) / f"{value.through_event.sequence:020d}.json"
                if not last_event.is_file():
                    raise RunStoreCorruption("Run record references a missing event")
            if value.terminal_status is not None and value.evidence_ref is None:
                status = "behind" if self.store._evidence_path(run_id).exists() else "publication_pending"
            if value.evidence_ref is not None and not self.store._evidence_path(run_id).is_file():
                raise RunStoreCorruption("Run record references missing terminal evidence")
        return {
            "schema_version": 1,
            "index_status": status,
            "record": None if value is None else value.as_record(),
            "required_action": "refresh_record" if status in {"behind", "unavailable"} else None,
            "limitations": [
                "This is a maintained view of committed facts, not process liveness or independent audit verification.",
                "Counts do not prove response compatibility or a coherent checkpoint; replay requires its own preview.",
            ],
        }

    def rebuild(self, registration, events, evidence):
        with self.connection(registration.run_id, write=True) as connection:
            connection.execute("DELETE FROM facts")
            value = initial_record(registration)
            for event in events:
                value = advance_record(value, event)
                self._insert_fact(connection, event, logical_run_id=registration.logical_run_id)
            if evidence is not None:
                value = attach_evidence(value, evidence)
            self._replace(connection, value)


def read_fact(row, registration):
    from ..store import RunStoreCorruption

    try:
        fact = EventFact.from_record(json.loads(row["record_json"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise RunStoreCorruption("indexed event fact has an invalid identity") from exc
    if (
        fact.run_id != registration.run_id.value
        or fact.registration_hash != registration.registration_hash.value
        or fact.event.sequence != row["sequence"] or fact.event.event_id != row["event_id"]
        or fact.episode_id != row["episode_id"] or fact.kind != row["kind"]
        or fact.ordinal != row["ordinal"]
    ):
        raise RunStoreCorruption("indexed event fact differs from its indexed identity")
    return fact
