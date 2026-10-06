"""Dedicated read-only SQLite access. No host/store construction or migrations."""

from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sqlite3


class InspectionError(ValueError):
    pass


def canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return 'sha256:' + hashlib.sha256(raw.encode()).hexdigest()


def ref_id(value):
    return value.get('artifact_id') if isinstance(value, dict) else None


@dataclass(frozen=True)
class Artifact:
    ordinal: int
    identity: str
    kind: str
    created_at: float
    content_hash: str
    record: dict

    @property
    def body(self):
        return self.record.get('body', self.record)


class Archive:
    def __init__(self, home):
        self.home = Path(home).expanduser().resolve()
        self.root = self.home / 'openchia'
        self.path = self.root / 'authority.sqlite3'

    @contextmanager
    def connection(self):
        if not self.path.is_file():
            raise InspectionError(f'No recorded OpenChia authority store at {self.path}')
        connection = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=0.25)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            yield connection
        except sqlite3.DatabaseError as exc:
            raise InspectionError(f'Cannot read recorded state: {exc}') from exc
        finally:
            connection.close()

    def campaigns(self, duet=None):
        with self.connection() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'refinement_campaign_heads' not in tables:
                return []
            rows = db.execute(
                'SELECT h.*, a.created_at FROM refinement_campaign_heads h '
                'JOIN artifacts a ON a.artifact_id=h.contract_id '
                'WHERE (? IS NULL OR h.duet_id=?) ORDER BY a.rowid DESC', (duet, duet))
            return [dict(row) for row in rows]

    @lru_cache(maxsize=8192)
    def artifact(self, identity, duet, cutoff):
        with self.connection() as db:
            row = db.execute(
                'SELECT rowid AS ordinal,* FROM artifacts WHERE artifact_id=? '
                'AND duet_id=? AND rowid<=?', (identity, duet, cutoff)).fetchone()
        if row is None:
            raise InspectionError(f'Artifact {identity} is unavailable at this historical position')
        return self.decode(row)

    @staticmethod
    def decode(row):
        record = json.loads(row['record_json'])
        if not isinstance(record, dict):
            raise InspectionError('Recorded artifact is not an object')
        expected = canonical_hash(record)
        if record.get('schema_id', '').startswith('openchia.refinement.'):
            if record.get('schema_version') != 1:
                raise InspectionError(f'Unsupported refinement schema: {record.get("schema_version")}')
            # The envelope hashes its semantic record, before adding its own identity.
            semantic = {k: v for k, v in record.items() if k not in {'artifact_id', 'content_hash'}}
            # Experiment receipts can store the same typed envelope under a
            # separate outer receipt identity, hashing either the full record
            # or its semantic body. Preserve both recorded identities.
            if expected != row['content_hash']:
                expected = canonical_hash(semantic)
                if record.get('content_hash') != expected:
                    raise InspectionError(f'Artifact envelope hash mismatch: {row["artifact_id"]}')
        if expected != row['content_hash']:
            raise InspectionError(f'Artifact hash mismatch: {row["artifact_id"]}')
        return Artifact(row['ordinal'], row['artifact_id'], row['kind'],
                        row['created_at'], row['content_hash'], record)

    def records(self, duet, cutoff, kinds, *, contains=None):
        slots = ','.join('?' for _ in kinds)
        with self.connection() as db:
            rows = db.execute(
                f'SELECT rowid AS ordinal,* FROM artifacts WHERE duet_id=? AND rowid<=? '
                f'AND kind IN ({slots}) AND (? IS NULL OR instr(record_json,?)>0) ORDER BY rowid',
                (duet, cutoff, *kinds, contains, contains)).fetchall()
        return [self.decode(row) for row in rows]
