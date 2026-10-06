"""Dedicated read-only SQLite access. No host/store construction or migrations."""

from contextlib import contextmanager
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import RLock


class InspectionError(ValueError):
    pass


@contextmanager
def record_context(label):
    """Malformed stored structures are observation failures, with their source."""
    try:
        yield
    except InspectionError:
        raise
    except (KeyError, TypeError, AttributeError, IndexError, ValueError, RecursionError, OverflowError) as exc:
        raise InspectionError(f'Cannot inspect {label}: invalid recorded data ({exc})') from exc


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
        body = self.record.get('body', self.record)
        if not isinstance(body, dict):
            raise InspectionError(f'Artifact {self.identity} body must be an object')
        return body


class Archive:
    def __init__(self, home):
        self.home = Path(home).expanduser().resolve()
        self.root = self.home / 'openchia'
        self.path = self.root / 'authority.sqlite3'
        self._artifacts = OrderedDict()
        self._queries = OrderedDict()
        self._lock = RLock()

    @contextmanager
    def connection(self):
        if not self.path.is_file():
            raise InspectionError(f'No recorded OpenChia authority store at {self.path}')
        connection = None
        try:
            connection = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=0.25)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            yield connection
        except sqlite3.Error as exc:
            raise InspectionError(f'Cannot read authority store {self.path}: {exc}') from exc
        finally:
            if connection is not None:
                connection.close()

    def _cached(self, cache, key):
        with self._lock:
            value = cache.get(key)
            if value is not None:
                cache.move_to_end(key)
            return value

    def _remember(self, cache, key, value, limit):
        with self._lock:
            cache[key] = value
            cache.move_to_end(key)
            while len(cache) > limit:
                cache.popitem(last=False)

    def progress(self, campaign, duet=None):
        with self.connection() as db:
            row = db.execute(
                'SELECT h.latest_commit_id,h.sequence, '
                '(SELECT coalesce(max(rowid),0) FROM artifacts WHERE duet_id=h.duet_id) '
                'FROM refinement_campaign_heads h WHERE campaign_id=? AND (? IS NULL OR duet_id=?)',
                (campaign, duet, duet)).fetchone()
        if row is None:
            raise InspectionError('Campaign unavailable in the selected profile/Duet')
        return tuple(row)

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

    def artifact(self, identity, duet, cutoff):
        cached = self._cached(self._artifacts, (duet, identity))
        if cached is not None:
            if cached.ordinal > cutoff:
                raise InspectionError(f'Artifact {identity} is unavailable at this historical position')
            return cached
        with self.connection() as db:
            row = db.execute(
                'SELECT rowid AS ordinal,* FROM artifacts WHERE artifact_id=? '
                'AND duet_id=? AND rowid<=?', (identity, duet, cutoff)).fetchone()
        if row is None:
            raise InspectionError(f'Artifact {identity} is unavailable at this historical position')
        return self.decode(row)

    def decode(self, row):
        key = row['duet_id'], row['artifact_id']
        cached = self._cached(self._artifacts, key)
        if cached is not None and (cached.ordinal, cached.content_hash) == (row['ordinal'], row['content_hash']):
            return cached
        with record_context(f'artifact {row["artifact_id"]}'):
            item = self._decode(row)
        self._remember(self._artifacts, key, item, 8192)
        return item

    @staticmethod
    def _decode(row):
        record = json.loads(row['record_json'])
        if not isinstance(record, dict):
            raise InspectionError('Recorded artifact is not an object')
        expected = canonical_hash(record)
        schema = record.get('schema_id', '')
        if not isinstance(schema, str):
            raise InspectionError(f'Artifact {row["artifact_id"]} schema_id must be text')
        if schema.startswith('openchia.refinement.'):
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

    def records(self, duet, cutoff, kinds, *, campaign=None, related=None):
        if not kinds:
            return []
        key = duet, tuple(kinds), campaign, related
        through, records = self._cached(self._queries, key) or (0, ())
        if cutoff <= through:
            return [item for item in records if item.ordinal <= cutoff]
        slots = ','.join('?' for _ in kinds)
        filters, args = '', [duet, through, cutoff, *kinds]
        if campaign is not None:
            filters += " AND json_extract(record_json,'$.campaign_id')=?"
            args.append(campaign)
        if related is not None:
            invocation, assignment = related
            filters += (" AND (json_extract(record_json,'$.invocation_id')=?"
                        " OR json_extract(record_json,'$.body.invocation_id')=?"
                        " OR json_extract(record_json,'$.body.assignment_ref.artifact_id')=?"
                        " OR json_extract(record_json,'$.assignment_ref.artifact_id')=?)")
            args.extend((invocation, invocation, assignment, assignment))
        with self.connection() as db:
            rows = db.execute(
                f'SELECT rowid AS ordinal,* FROM artifacts WHERE duet_id=? AND rowid>? AND rowid<=? '
                f'AND kind IN ({slots}){filters} ORDER BY rowid', args).fetchall()
        records = (*records, *(self.decode(row) for row in rows))
        self._remember(self._queries, key, (cutoff, records), 128)
        return list(records)
