from __future__ import annotations

import sqlite3

import pytest

from agent.episode_contracts import OpaqueId, Sha256Digest
from agent.generic_creator_models import EvidenceGate, EvidenceGateManifest, GateRequirement
from agent.generic_creator_store import GenericCreatorConflictError, GenericCreatorStore
from tests.agent.generic_creator_fixtures import RUNTIME_IDENTITY, creator_spec


def _store(tmp_path) -> GenericCreatorStore:
    return GenericCreatorStore(tmp_path / "duet.sqlite3")


def test_additive_migration_and_interrupted_resume(tmp_path) -> None:
    path = tmp_path / "duet.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE existing_production_state(value TEXT)")
    connection.execute("INSERT INTO existing_production_state VALUES ('untouched')")
    connection.commit()
    connection.close()
    with GenericCreatorStore(path) as store:
        store.create_instance(creator_spec(), root_instance_id="root", depth=0, runtime_identity=RUNTIME_IDENTITY)
    with GenericCreatorStore(path) as reopened:
        assert reopened.instance("root")["spec"].instance_id == "root"
        row = reopened._connection.execute("SELECT value FROM existing_production_state").fetchone()
        assert row[0] == "untouched"


def test_namespace_cas_prevents_silent_branch_overwrite(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.create_instance(creator_spec(), root_instance_id="root", depth=0, runtime_identity=RUNTIME_IDENTITY)
        first, _, revision = store.put_artifact(
            producer_instance_id="root", producing_episode_id="episode_a", namespace="root",
            artifact_key="result", kind="result", record={"value": 1}, expected_revision=None,
        )
        assert revision == 1
        with pytest.raises(GenericCreatorConflictError, match="stale namespace write"):
            store.put_artifact(
                producer_instance_id="root", producing_episode_id="episode_b", namespace="root",
                artifact_key="result", kind="result", record={"value": 2}, expected_revision=0,
            )
        assert store.artifact(first)["record"] == {"value": 1}


def test_parent_cannot_write_a_descendant_namespace(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.create_instance(
            creator_spec(), root_instance_id="root", depth=0,
            runtime_identity=RUNTIME_IDENTITY,
        )
        with pytest.raises(GenericCreatorConflictError, match="producer ownership"):
            store.put_artifact(
                producer_instance_id="root", producing_episode_id="episode",
                namespace="root/child", artifact_key="result", kind="result",
                record={"value": 1}, expected_revision=None,
            )


def test_artifact_hash_verification_detects_tampering(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.create_instance(creator_spec(), root_instance_id="root", depth=0, runtime_identity=RUNTIME_IDENTITY)
        artifact_id, _, _ = store.put_artifact(
            producer_instance_id="root", producing_episode_id="episode", namespace="root",
            artifact_key="result", kind="result", record={"value": 1}, expected_revision=None,
        )
        store._connection.execute(
            "UPDATE generic_creator_artifacts SET record_json = ? WHERE artifact_id = ?",
            ('{"value":2}', artifact_id.value),
        )
        with pytest.raises(GenericCreatorConflictError, match="hash verification"):
            store.artifact(artifact_id)


@pytest.mark.parametrize(
    "record",
    [
        {"api_key": "redacted"},
        {"nested": {"value": "sk_abcdefghijklmnopqrstuvwxyz"}},
    ],
)
def test_shared_state_rejects_secret_shaped_content(tmp_path, record) -> None:
    with _store(tmp_path) as store:
        store.create_instance(creator_spec(), root_instance_id="root", depth=0, runtime_identity=RUNTIME_IDENTITY)
        with pytest.raises(ValueError, match="secret"):
            store.put_artifact(
                producer_instance_id="root", producing_episode_id="episode", namespace="root",
                artifact_key="result", kind="result", record=record, expected_revision=None,
            )


def _manifest(revision: int, criteria: bytes = b"criteria", include_gate: bool = True) -> EvidenceGateManifest:
    gates = (
        EvidenceGate("gate_a", "Gate A", 1, "test_result", "host_test", 1, (), GateRequirement.REQUIRED),
    )
    if not include_gate:
        gates = (
            EvidenceGate("gate_b", "Gate B", 1, "test_result", "host_test", 1, (), GateRequirement.REQUIRED),
        )
    return EvidenceGateManifest("manifest_root", revision, Sha256Digest.of_bytes(criteria), gates)


def test_manifest_revisions_cannot_weaken_without_approval(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.create_instance(creator_spec(), root_instance_id="root", depth=0, runtime_identity=RUNTIME_IDENTITY)
        store.put_manifest("root", _manifest(1), approved=True)
        with pytest.raises(GenericCreatorConflictError, match="approval"):
            store.put_manifest("root", _manifest(2, b"changed", include_gate=False), approved=False)
        store.put_manifest("root", _manifest(2, b"changed", include_gate=False), approved=True)
        assert store.latest_manifest("manifest_root").revision == 2


def test_only_host_accepted_matching_evidence_enters_ledger(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.create_instance(creator_spec(), root_instance_id="root", depth=0, runtime_identity=RUNTIME_IDENTITY)
        manifest = _manifest(1)
        store.put_manifest("root", manifest, approved=True)
        evidence_id = OpaqueId.mint("evidence", "test")
        with pytest.raises(GenericCreatorConflictError, match="model assertions"):
            store.accept_gate_evidence(
                manifest=manifest, gate_id="gate_a", evidence_id=evidence_id,
                evidence_kind="test_result", acceptance_source="host_test",
                evidence_hash=Sha256Digest.of_bytes(b"result"), host_accepted=False,
            )
        store.accept_gate_evidence(
            manifest=manifest, gate_id="gate_a", evidence_id=evidence_id,
            evidence_kind="test_result", acceptance_source="host_test",
            evidence_hash=Sha256Digest.of_bytes(b"result"), host_accepted=True,
        )
        # Repetition is idempotent and receives no additional count.
        store.accept_gate_evidence(
            manifest=manifest, gate_id="gate_a", evidence_id=evidence_id,
            evidence_kind="test_result", acceptance_source="host_test",
            evidence_hash=Sha256Digest.of_bytes(b"result"), host_accepted=True,
        )
        assert store.accepted_evidence(manifest) == {"gate_a": (evidence_id,)}


def test_unpersisted_manifest_cannot_accept_evidence(tmp_path) -> None:
    with _store(tmp_path) as store:
        store.create_instance(
            creator_spec(), root_instance_id="root", depth=0,
            runtime_identity=RUNTIME_IDENTITY,
        )
        manifest = _manifest(1)
        with pytest.raises(GenericCreatorConflictError, match="exact persisted"):
            store.accept_gate_evidence(
                manifest=manifest, gate_id="gate_a",
                evidence_id=OpaqueId.mint("evidence", "unpersisted"),
                evidence_kind="test_result", acceptance_source="host_test",
                evidence_hash=Sha256Digest.of_bytes(b"result"), host_accepted=True,
            )
