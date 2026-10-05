"""Real SQLite transaction boundaries used by host state and reply receipts."""

import asyncio

import pytest

from agent.duet_store import DuetStore
from episode_runtime.records.experiments import put_data


def test_outer_cancellation_rolls_back_successful_nested_writes(tmp_path):
    database = tmp_path / "duet.sqlite3"
    with DuetStore(database) as store:
        store.create_duet(duet_id="owner", identity={}, policy={}, state="designing")
        with pytest.raises(asyncio.CancelledError):
            with store.transaction():
                state = put_data(store, "owner", "state", {"revision": 1})
                with store.transaction():
                    receipt = put_data(store, "owner", "receipt", {"state_ref": state})
                assert store.get_artifact(receipt["artifact_id"]) is not None
                raise asyncio.CancelledError
        assert store.get_artifact(state["artifact_id"]) is None
        assert store.get_artifact(receipt["artifact_id"]) is None
        # Rollback must also leave the connection usable for the next operation.
        retained = put_data(store, "owner", "state", {"revision": 2})
    with DuetStore(database) as reopened:
        assert reopened.get_artifact(state["artifact_id"]) is None
        assert reopened.get_artifact(receipt["artifact_id"]) is None
        assert reopened.get_artifact(retained["artifact_id"])["record"] == {"revision": 2}


def test_caught_inner_failure_rolls_back_only_its_savepoint(tmp_path):
    database = tmp_path / "duet.sqlite3"
    with DuetStore(database) as store:
        store.create_duet(duet_id="owner", identity={}, policy={}, state="designing")
        with store.transaction():
            before = put_data(store, "owner", "state", {"revision": 1})
            with pytest.raises(ValueError, match="reject nested effect"):
                with store.transaction():
                    rejected = put_data(store, "owner", "state", {"revision": 2})
                    raise ValueError("reject nested effect")
            after = put_data(store, "owner", "receipt", {"state_ref": before})
            assert store.get_artifact(rejected["artifact_id"]) is None
    with DuetStore(database) as reopened:
        assert reopened.get_artifact(before["artifact_id"])["record"] == {"revision": 1}
        assert reopened.get_artifact(rejected["artifact_id"]) is None
        assert reopened.get_artifact(after["artifact_id"])["record"] == {"state_ref": before}
