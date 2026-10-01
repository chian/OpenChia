"""The empty-index FTS realignment must survive its own savepoint (startup regression).

A store whose ``messages_fts`` still reads raw ``messages`` (FTS_STORAGE_VERSION < 3)
but holds **no messages** is realigned in place under ``SAVEPOINT fts_align_empty``.
The alignment DDL used to run through ``executescript``, whose implicit COMMIT ended
the transaction and discarded the savepoint, so ``RELEASE SAVEPOINT`` raised
``no such savepoint: fts_align_empty``; the rollback handler then raised the same
error again, masking the real outcome, and SessionDB initialisation was abandoned
("session will NOT be indexed for search") although the index had in fact been
rebuilt. Observed on a live ~/.hermes/state.db on 2026-09-30.
"""

import sqlite3

import pytest

from hermes_state import SessionDB
from hermes_state_common import FTS_STORAGE_VERSION


def _rewind_to_raw_messages_index(path):
    """Put an opened store back on the pre-v3 shape with an empty messages table."""
    first = SessionDB(db_path=path)
    if not first._fts_enabled:
        first.close()
        pytest.skip("SQLite FTS5 unavailable")
    first._conn.execute("DROP TABLE messages_fts")
    first._conn.execute(
        "CREATE VIRTUAL TABLE messages_fts USING fts5("
        "content, tool_name, tool_calls, content='messages', content_rowid='id')"
    )
    first._conn.execute(
        "INSERT INTO state_meta(key, value) VALUES('fts_storage_version', '2') "
        "ON CONFLICT(key) DO UPDATE SET value = '2'"
    )
    first._conn.commit()
    first.close()


def test_empty_store_realigns_on_open_without_savepoint_error(tmp_path):
    path = tmp_path / "state.db"
    _rewind_to_raw_messages_index(path)

    # Pre-fix this raised sqlite3.OperationalError("no such savepoint: fts_align_empty").
    migrated = SessionDB(db_path=path)
    try:
        assert migrated._fts_enabled
        assert migrated.get_meta("fts_storage_version") == str(FTS_STORAGE_VERSION)
        index_sql = migrated._conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'messages_fts'"
        ).fetchone()[0]
        assert "messages_fts_src" in index_sql
        # The realigned, empty index is live: a first message is indexed and found.
        migrated.create_session("session", source="cli")
        migrated.append_message("session", role="user", content="needle in the haystack")
        assert migrated.search_messages("needle")
    finally:
        migrated.close()


def test_alignment_failure_surfaces_the_original_error(tmp_path, monkeypatch):
    """When the alignment itself fails, the caller sees that error — never the
    savepoint bookkeeping's."""
    path = tmp_path / "state.db"
    _rewind_to_raw_messages_index(path)

    def boom(self, cursor, table_name, ddl, **kwargs):
        raise sqlite3.OperationalError("simulated DDL failure inside alignment")

    # Patch on the concrete class: the method lives on the FTS mixin, which sits
    # before the schema mixin in SessionDB's MRO.
    monkeypatch.setattr(SessionDB, "_ensure_fts_schema", boom)
    with pytest.raises(Exception) as excinfo:
        SessionDB(db_path=path)
    assert "simulated DDL failure" in str(excinfo.value)
    assert "no such savepoint" not in str(excinfo.value)
