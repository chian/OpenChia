"""Durable control-plane state for generic nested Creator instances.

The schema is additive to a Duet database and deliberately uses separate
tables.  Existing Episode, approval, and evidence records are never rewritten.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any, Iterator, Mapping, Optional

from agent.duet_contracts import canonical_json
from agent.episode_contracts import OpaqueId, Sha256Digest
from agent.generic_creator_models import (
    CreatorFaultRecord,
    CreatorRepairRequest,
    EvidenceGateManifest,
    FaultStatus,
    GenericCreatorInstanceSpec,
    GenericCreatorStatus,
    RepairStatus,
)


GENERIC_CREATOR_STORE_SCHEMA_VERSION = 1


class GenericCreatorStoreError(RuntimeError):
    """Base error for generic Creator persistence."""


class GenericCreatorConflictError(GenericCreatorStoreError):
    """An immutable record or optimistic namespace revision conflicted."""


class GenericCreatorNotFoundError(GenericCreatorStoreError):
    """A required control-plane record does not exist."""


_SECRET_KEY = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|private[_-]?key|credential|authorization)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{16,})"
)


def _json_object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    parsed = json.loads(canonical_json(value))
    if not isinstance(parsed, dict):
        raise ValueError(f"{name} must be an object")
    return parsed


def _reject_secrets(value: object, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _SECRET_KEY.search(str(key)):
                raise ValueError(f"shared state cannot contain secret-shaped key {path}.{key}")
            _reject_secrets(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_secrets(child, f"{path}[{index}]")
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise ValueError(f"shared state cannot contain a raw secret at {path}")


class GenericCreatorStore:
    """SQLite store for authority, work, evidence, and artifact graphs."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            str(self.path), timeout=30, isolation_level=None, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "GenericCreatorStore":
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
                CREATE TABLE IF NOT EXISTS generic_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS generic_creator_instances (
                    instance_id TEXT PRIMARY KEY,
                    parent_instance_id TEXT,
                    root_instance_id TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    spec_hash TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    runtime_identity TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    closed_at REAL,
                    FOREIGN KEY(parent_instance_id) REFERENCES generic_creator_instances(instance_id)
                );
                CREATE TABLE IF NOT EXISTS generic_creator_budgets (
                    instance_id TEXT PRIMARY KEY,
                    iterations_allocated INTEGER NOT NULL,
                    iterations_remaining INTEGER NOT NULL,
                    child_slots_allocated INTEGER NOT NULL,
                    child_slots_remaining INTEGER NOT NULL,
                    elapsed_allocated REAL NOT NULL,
                    elapsed_remaining REAL NOT NULL,
                    returned INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(instance_id) REFERENCES generic_creator_instances(instance_id)
                );
                CREATE TABLE IF NOT EXISTS generic_creator_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    producer_instance_id TEXT NOT NULL,
                    producing_episode_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    artifact_key TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    supersedes_artifact_id TEXT,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(producer_instance_id) REFERENCES generic_creator_instances(instance_id)
                );
                CREATE TABLE IF NOT EXISTS generic_namespace_heads (
                    namespace TEXT NOT NULL,
                    artifact_key TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    artifact_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    PRIMARY KEY(namespace, artifact_key),
                    FOREIGN KEY(artifact_id) REFERENCES generic_creator_artifacts(artifact_id)
                );
                CREATE TABLE IF NOT EXISTS generic_gate_manifests (
                    manifest_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    instance_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    success_criteria_hash TEXT NOT NULL,
                    approved INTEGER NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(manifest_id, revision),
                    FOREIGN KEY(instance_id) REFERENCES generic_creator_instances(instance_id)
                );
                CREATE TABLE IF NOT EXISTS generic_gate_evidence (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    evidence_id TEXT NOT NULL,
                    manifest_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    gate_id TEXT NOT NULL,
                    evidence_kind TEXT NOT NULL,
                    acceptance_source TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    accepted_by_host INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(evidence_id, manifest_id, revision, gate_id)
                );
                CREATE TABLE IF NOT EXISTS generic_work_items (
                    instance_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL,
                    last_evidence_sequence INTEGER NOT NULL,
                    artifact_id TEXT,
                    required_checks_json TEXT NOT NULL,
                    accepted_checks_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(instance_id, item_id),
                    FOREIGN KEY(instance_id) REFERENCES generic_creator_instances(instance_id)
                );
                CREATE TABLE IF NOT EXISTS generic_integration_edges (
                    instance_id TEXT NOT NULL,
                    edge_id TEXT NOT NULL,
                    owner_instance_id TEXT,
                    status TEXT NOT NULL,
                    artifact_ids_json TEXT NOT NULL,
                    evidence_ids_json TEXT NOT NULL,
                    retest_required INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(instance_id, edge_id)
                );
                CREATE TABLE IF NOT EXISTS generic_faults (
                    fault_id TEXT PRIMARY KEY,
                    reporting_instance_id TEXT NOT NULL,
                    owning_instance_id TEXT,
                    status TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS generic_repairs (
                    repair_id TEXT PRIMARY KEY,
                    fault_id TEXT NOT NULL,
                    owning_instance_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    FOREIGN KEY(fault_id) REFERENCES generic_faults(fault_id)
                );
                CREATE TABLE IF NOT EXISTS generic_audit_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    instance_id TEXT,
                    event_type TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )
            self._connection.execute(
                "INSERT OR IGNORE INTO generic_schema_migrations(version, applied_at) VALUES (?, ?)",
                (GENERIC_CREATOR_STORE_SCHEMA_VERSION, time.time()),
            )

    @staticmethod
    def _decode(row: sqlite3.Row, column: str) -> dict[str, Any]:
        value = json.loads(row[column])
        if not isinstance(value, dict):
            raise GenericCreatorStoreError("stored JSON record is not an object")
        return value

    def audit(self, instance_id: Optional[str], event_type: str, record: Mapping[str, Any]) -> None:
        payload = canonical_json(_json_object(record, "audit record"))
        with self.transaction() as connection:
            connection.execute(
                "INSERT INTO generic_audit_events(instance_id, event_type, record_json, created_at) VALUES (?, ?, ?, ?)",
                (instance_id, event_type, payload, time.time()),
            )

    def create_instance(
        self,
        spec: GenericCreatorInstanceSpec,
        *,
        root_instance_id: str,
        depth: int,
        runtime_identity: Sha256Digest,
    ) -> None:
        now = time.time()
        try:
            with self.transaction() as connection:
                connection.execute(
                    """INSERT INTO generic_creator_instances(
                        instance_id, parent_instance_id, root_instance_id, depth, status,
                        spec_hash, spec_json, runtime_identity, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        spec.instance_id, spec.parent_instance_id, root_instance_id, depth,
                        GenericCreatorStatus.ADMITTED.value, spec.content_hash.value,
                        canonical_json(spec.as_record()), runtime_identity.value, now, now,
                    ),
                )
                connection.execute(
                    """INSERT INTO generic_creator_budgets(
                        instance_id, iterations_allocated, iterations_remaining,
                        child_slots_allocated, child_slots_remaining,
                        elapsed_allocated, elapsed_remaining
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        spec.instance_id, spec.maximum_iterations, spec.maximum_iterations,
                        spec.maximum_child_episodes, spec.maximum_child_episodes,
                        spec.maximum_elapsed_time, spec.maximum_elapsed_time,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise GenericCreatorConflictError(f"Creator instance {spec.instance_id!r} already exists") from exc

    def create_child_instance(
        self,
        spec: GenericCreatorInstanceSpec,
        *,
        root_instance_id: str,
        depth: int,
        runtime_identity: Sha256Digest,
    ) -> None:
        """Atomically reserve the parent budget and persist its child."""

        if spec.parent_instance_id is None:
            raise ValueError("child instance requires a parent")
        now = time.time()
        try:
            with self.transaction() as connection:
                budget = connection.execute(
                    "SELECT * FROM generic_creator_budgets WHERE instance_id = ?",
                    (spec.parent_instance_id,),
                ).fetchone()
                if budget is None:
                    raise GenericCreatorNotFoundError(
                        f"unknown parent budget {spec.parent_instance_id!r}"
                    )
                requested_children = spec.maximum_child_episodes + 1
                if (
                    budget["iterations_remaining"] < spec.maximum_iterations
                    or budget["child_slots_remaining"] < requested_children
                    or budget["elapsed_remaining"] < spec.maximum_elapsed_time
                ):
                    raise GenericCreatorConflictError(
                        "child budget exceeds the parent's remaining reservation"
                    )
                connection.execute(
                    """UPDATE generic_creator_budgets SET
                        iterations_remaining = iterations_remaining - ?,
                        child_slots_remaining = child_slots_remaining - ?,
                        elapsed_remaining = elapsed_remaining - ? WHERE instance_id = ?""",
                    (
                        spec.maximum_iterations, requested_children,
                        spec.maximum_elapsed_time, spec.parent_instance_id,
                    ),
                )
                connection.execute(
                    """INSERT INTO generic_creator_instances(
                        instance_id, parent_instance_id, root_instance_id, depth, status,
                        spec_hash, spec_json, runtime_identity, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        spec.instance_id, spec.parent_instance_id, root_instance_id, depth,
                        GenericCreatorStatus.ADMITTED.value, spec.content_hash.value,
                        canonical_json(spec.as_record()), runtime_identity.value, now, now,
                    ),
                )
                connection.execute(
                    """INSERT INTO generic_creator_budgets(
                        instance_id, iterations_allocated, iterations_remaining,
                        child_slots_allocated, child_slots_remaining,
                        elapsed_allocated, elapsed_remaining
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        spec.instance_id, spec.maximum_iterations, spec.maximum_iterations,
                        spec.maximum_child_episodes, spec.maximum_child_episodes,
                        spec.maximum_elapsed_time, spec.maximum_elapsed_time,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise GenericCreatorConflictError(
                f"Creator instance {spec.instance_id!r} already exists"
            ) from exc

    def instance(self, instance_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM generic_creator_instances WHERE instance_id = ?", (instance_id,)
            ).fetchone()
        if row is None:
            raise GenericCreatorNotFoundError(f"unknown Creator instance {instance_id!r}")
        return {
            "spec": GenericCreatorInstanceSpec.from_record(self._decode(row, "spec_json")),
            "root_instance_id": row["root_instance_id"],
            "depth": row["depth"],
            "status": GenericCreatorStatus(row["status"]),
            "runtime_identity": Sha256Digest(row["runtime_identity"]),
            "closed_at": row["closed_at"],
        }

    def budget(self, instance_id: str) -> dict[str, int | float | bool]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM generic_creator_budgets WHERE instance_id = ?", (instance_id,)
            ).fetchone()
        if row is None:
            raise GenericCreatorNotFoundError(f"unknown Creator budget {instance_id!r}")
        return {
            "iterations_allocated": row["iterations_allocated"],
            "iterations_remaining": row["iterations_remaining"],
            "child_slots_allocated": row["child_slots_allocated"],
            "child_slots_remaining": row["child_slots_remaining"],
            "elapsed_allocated": row["elapsed_allocated"],
            "elapsed_remaining": row["elapsed_remaining"],
            "returned": bool(row["returned"]),
        }

    def descendants(self, instance_id: str) -> tuple[str, ...]:
        with self._lock:
            rows = self._connection.execute(
                """WITH RECURSIVE tree(id) AS (
                    SELECT instance_id FROM generic_creator_instances WHERE parent_instance_id = ?
                    UNION ALL
                    SELECT child.instance_id FROM generic_creator_instances child
                    JOIN tree ON child.parent_instance_id = tree.id
                ) SELECT id FROM tree ORDER BY id""",
                (instance_id,),
            ).fetchall()
        return tuple(row["id"] for row in rows)

    def reserve_from_parent(self, parent_id: str, child_spec: GenericCreatorInstanceSpec) -> None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM generic_creator_budgets WHERE instance_id = ?", (parent_id,)
            ).fetchone()
            if row is None:
                raise GenericCreatorNotFoundError(f"unknown parent budget {parent_id!r}")
            requested_children = child_spec.maximum_child_episodes + 1
            if (
                row["iterations_remaining"] < child_spec.maximum_iterations
                or row["child_slots_remaining"] < requested_children
                or row["elapsed_remaining"] < child_spec.maximum_elapsed_time
            ):
                raise GenericCreatorConflictError("child budget exceeds the parent's remaining reservation")
            connection.execute(
                """UPDATE generic_creator_budgets SET
                    iterations_remaining = iterations_remaining - ?,
                    child_slots_remaining = child_slots_remaining - ?,
                    elapsed_remaining = elapsed_remaining - ?
                WHERE instance_id = ?""",
                (
                    child_spec.maximum_iterations, requested_children,
                    child_spec.maximum_elapsed_time, parent_id,
                ),
            )

    def release_reservation(self, parent_id: str, child_spec: GenericCreatorInstanceSpec) -> None:
        with self.transaction() as connection:
            connection.execute(
                """UPDATE generic_creator_budgets SET
                    iterations_remaining = iterations_remaining + ?,
                    child_slots_remaining = child_slots_remaining + ?,
                    elapsed_remaining = elapsed_remaining + ?
                WHERE instance_id = ?""",
                (
                    child_spec.maximum_iterations, child_spec.maximum_child_episodes + 1,
                    child_spec.maximum_elapsed_time, parent_id,
                ),
            )

    def consume(self, instance_id: str, *, iterations: int = 0, elapsed: float = 0.0) -> bool:
        if isinstance(iterations, bool) or iterations < 0 or elapsed < 0:
            raise ValueError("consumption values must be non-negative")
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM generic_creator_budgets WHERE instance_id = ?", (instance_id,)
            ).fetchone()
            if row is None:
                raise GenericCreatorNotFoundError(f"unknown Creator budget {instance_id!r}")
            if row["iterations_remaining"] < iterations or row["elapsed_remaining"] < elapsed:
                return False
            connection.execute(
                """UPDATE generic_creator_budgets SET
                    iterations_remaining = iterations_remaining - ?,
                    elapsed_remaining = elapsed_remaining - ? WHERE instance_id = ?""",
                (iterations, elapsed, instance_id),
            )
            return True

    def set_status(self, instance_id: str, status: GenericCreatorStatus) -> None:
        terminal = status in {
            GenericCreatorStatus.SUCCEEDED, GenericCreatorStatus.FAILED,
            GenericCreatorStatus.CANCELLED, GenericCreatorStatus.INVALIDATED,
        }
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE generic_creator_instances SET status = ?, updated_at = ?, closed_at = CASE WHEN ? THEN COALESCE(closed_at, ?) ELSE closed_at END WHERE instance_id = ?",
                (status.value, time.time(), int(terminal), time.time(), instance_id),
            )
            if cursor.rowcount != 1:
                raise GenericCreatorNotFoundError(f"unknown Creator instance {instance_id!r}")

    def return_unused_budget(self, instance_id: str) -> None:
        child = self.instance(instance_id)
        parent_id = child["spec"].parent_instance_id
        if parent_id is None:
            return
        with self.transaction() as connection:
            budget = connection.execute(
                "SELECT * FROM generic_creator_budgets WHERE instance_id = ?", (instance_id,)
            ).fetchone()
            if budget is None or budget["returned"]:
                return
            connection.execute(
                """UPDATE generic_creator_budgets SET
                    iterations_remaining = iterations_remaining + ?,
                    child_slots_remaining = child_slots_remaining + ?,
                    elapsed_remaining = elapsed_remaining + ? WHERE instance_id = ?""",
                (
                    budget["iterations_remaining"], budget["child_slots_remaining"],
                    budget["elapsed_remaining"], parent_id,
                ),
            )
            connection.execute(
                "UPDATE generic_creator_budgets SET returned = 1 WHERE instance_id = ?",
                (instance_id,),
            )

    def put_artifact(
        self,
        *,
        producer_instance_id: str,
        producing_episode_id: str,
        namespace: str,
        artifact_key: str,
        kind: str,
        record: Mapping[str, Any],
        expected_revision: Optional[int],
    ) -> tuple[OpaqueId, Sha256Digest, int]:
        payload = _json_object(record, "artifact record")
        _reject_secrets(payload)
        encoded = canonical_json(payload)
        digest = Sha256Digest.of_bytes(encoded.encode())
        artifact_id = OpaqueId.mint(
            "artifact", f"{producer_instance_id}:{producing_episode_id}:{namespace}:{artifact_key}:{digest.value}"
        )
        now = time.time()
        with self.transaction() as connection:
            owner = connection.execute(
                "SELECT spec_json FROM generic_creator_instances WHERE instance_id = ?",
                (producer_instance_id,),
            ).fetchone()
            if owner is None:
                raise GenericCreatorNotFoundError(f"unknown producer {producer_instance_id!r}")
            spec = GenericCreatorInstanceSpec.from_record(self._decode(owner, "spec_json"))
            if namespace != spec.shared_state_namespace:
                raise GenericCreatorConflictError("artifact namespace is outside producer ownership")
            head = connection.execute(
                "SELECT * FROM generic_namespace_heads WHERE namespace = ? AND artifact_key = ?",
                (namespace, artifact_key),
            ).fetchone()
            actual_revision = 0 if head is None else int(head["revision"])
            if expected_revision is None:
                if head is not None:
                    raise GenericCreatorConflictError("namespace key already exists; expected_revision is required")
            elif expected_revision != actual_revision:
                raise GenericCreatorConflictError(
                    f"stale namespace write: expected revision {expected_revision}, current {actual_revision}"
                )
            revision = actual_revision + 1
            supersedes = None if head is None else head["artifact_id"]
            connection.execute(
                """INSERT OR IGNORE INTO generic_creator_artifacts(
                    artifact_id, content_hash, producer_instance_id, producing_episode_id,
                    namespace, artifact_key, kind, record_json, supersedes_artifact_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    artifact_id.value, digest.value, producer_instance_id, producing_episode_id,
                    namespace, artifact_key, kind, encoded, supersedes, now,
                ),
            )
            connection.execute(
                """INSERT INTO generic_namespace_heads(namespace, artifact_key, revision, artifact_id, content_hash)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(namespace, artifact_key) DO UPDATE SET
                       revision=excluded.revision, artifact_id=excluded.artifact_id,
                       content_hash=excluded.content_hash""",
                (namespace, artifact_key, revision, artifact_id.value, digest.value),
            )
        return artifact_id, digest, revision

    def artifact(self, artifact_id: OpaqueId, *, verify: bool = True) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM generic_creator_artifacts WHERE artifact_id = ?", (artifact_id.value,)
            ).fetchone()
        if row is None:
            raise GenericCreatorNotFoundError(f"unknown artifact {artifact_id.value!r}")
        record = self._decode(row, "record_json")
        if verify and Sha256Digest.of_bytes(canonical_json(record).encode()).value != row["content_hash"]:
            raise GenericCreatorConflictError("artifact content hash verification failed")
        return {
            "artifact_id": row["artifact_id"], "content_hash": row["content_hash"],
            "producer_instance_id": row["producer_instance_id"],
            "producing_episode_id": row["producing_episode_id"], "namespace": row["namespace"],
            "artifact_key": row["artifact_key"], "kind": row["kind"], "record": record,
        }

    def put_manifest(
        self, instance_id: str, manifest: EvidenceGateManifest, *, approved: bool
    ) -> None:
        if any(gate.accepted_evidence_ids for gate in manifest.gates):
            raise GenericCreatorConflictError(
                "gate manifests cannot self-assert accepted evidence"
            )
        with self.transaction() as connection:
            instance = connection.execute(
                "SELECT spec_json FROM generic_creator_instances WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
            if instance is None:
                raise GenericCreatorNotFoundError(f"unknown Creator instance {instance_id!r}")
            spec = GenericCreatorInstanceSpec.from_record(self._decode(instance, "spec_json"))
            if manifest.manifest_id != spec.progress_measurement.gate_manifest_id:
                raise GenericCreatorConflictError(
                    "gate manifest ID does not match the instance progress contract"
                )
            prior = connection.execute(
                "SELECT * FROM generic_gate_manifests WHERE manifest_id = ? ORDER BY revision DESC LIMIT 1",
                (manifest.manifest_id,),
            ).fetchone()
            if prior is not None:
                if prior["instance_id"] != instance_id:
                    raise GenericCreatorConflictError(
                        "a gate manifest cannot move between Creator instances"
                    )
                if manifest.revision != prior["revision"] + 1:
                    raise GenericCreatorConflictError("manifest revisions must be consecutive")
                if manifest.success_criteria_hash.value != prior["success_criteria_hash"] and not approved:
                    raise GenericCreatorConflictError("success-criteria revision requires new approval")
                old = EvidenceGateManifest.from_record(self._decode(prior, "record_json"))
                old_required = {
                    gate.gate_id: gate for gate in old.gates
                    if gate.requirement.value == "required"
                }
                new_required = {
                    gate.gate_id: gate for gate in manifest.gates
                    if gate.requirement.value == "required"
                }
                weakened = not set(old_required).issubset(new_required)
                for gate_id, old_gate in old_required.items():
                    new_gate = new_required.get(gate_id)
                    if new_gate is None:
                        continue
                    old_definition = old_gate.as_record()
                    new_definition = new_gate.as_record()
                    for record in (old_definition, new_definition):
                        record.pop("current_acceptance_state")
                        record.pop("accepted_evidence_ids")
                    if old_definition != new_definition:
                        weakened = True
                if weakened and not approved:
                    raise GenericCreatorConflictError(
                        "changing or weakening required gates requires new approval"
                    )
            elif manifest.revision != 1:
                raise GenericCreatorConflictError("a new manifest must begin at revision 1")
            connection.execute(
                """INSERT INTO generic_gate_manifests(
                    manifest_id, revision, instance_id, content_hash,
                    success_criteria_hash, approved, record_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    manifest.manifest_id, manifest.revision, instance_id,
                    manifest.content_hash.value, manifest.success_criteria_hash.value,
                    int(approved), canonical_json(manifest.as_record()), time.time(),
                ),
            )

    def latest_manifest(self, manifest_id: str) -> EvidenceGateManifest:
        with self._lock:
            row = self._connection.execute(
                "SELECT record_json FROM generic_gate_manifests WHERE manifest_id = ? ORDER BY revision DESC LIMIT 1",
                (manifest_id,),
            ).fetchone()
        if row is None:
            raise GenericCreatorNotFoundError(f"unknown gate manifest {manifest_id!r}")
        return EvidenceGateManifest.from_record(self._decode(row, "record_json"))

    def accept_gate_evidence(
        self,
        *,
        manifest: EvidenceGateManifest,
        gate_id: str,
        evidence_id: OpaqueId,
        evidence_kind: str,
        acceptance_source: str,
        evidence_hash: Sha256Digest,
        host_accepted: bool,
    ) -> None:
        gate = next((item for item in manifest.gates if item.gate_id == gate_id), None)
        if gate is None:
            raise GenericCreatorNotFoundError(f"unknown gate {gate_id!r}")
        if not host_accepted:
            raise GenericCreatorConflictError("model assertions cannot accept gate evidence")
        if evidence_kind != gate.required_evidence_kind or acceptance_source != gate.accepted_evidence_source:
            raise GenericCreatorConflictError("evidence kind or acceptance source does not match the gate")
        with self.transaction() as connection:
            persisted = connection.execute(
                """SELECT content_hash FROM generic_gate_manifests
                   WHERE manifest_id = ? AND revision = ?""",
                (manifest.manifest_id, manifest.revision),
            ).fetchone()
            if persisted is None or persisted["content_hash"] != manifest.content_hash.value:
                raise GenericCreatorConflictError(
                    "evidence must reference the exact persisted gate manifest"
                )
            prior = connection.execute(
                """SELECT evidence_kind, acceptance_source, evidence_hash
                   FROM generic_gate_evidence WHERE evidence_id = ? LIMIT 1""",
                (evidence_id.value,),
            ).fetchone()
            if prior is not None and (
                prior["evidence_kind"] != evidence_kind
                or prior["acceptance_source"] != acceptance_source
                or prior["evidence_hash"] != evidence_hash.value
            ):
                raise GenericCreatorConflictError(
                    "accepted evidence identity is already bound to different content"
                )
            connection.execute(
                """INSERT OR IGNORE INTO generic_gate_evidence(
                    evidence_id, manifest_id, revision, gate_id, evidence_kind,
                    acceptance_source, evidence_hash, accepted_by_host, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    evidence_id.value, manifest.manifest_id, manifest.revision, gate_id,
                    evidence_kind, acceptance_source, evidence_hash.value, time.time(),
                ),
            )

    def accepted_evidence(self, manifest: EvidenceGateManifest) -> dict[str, tuple[OpaqueId, ...]]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT gate_id, evidence_id FROM generic_gate_evidence
                   WHERE manifest_id = ? AND revision = ? AND accepted_by_host = 1
                   ORDER BY sequence""",
                (manifest.manifest_id, manifest.revision),
            ).fetchall()
        result: dict[str, list[OpaqueId]] = {}
        for row in rows:
            result.setdefault(row["gate_id"], []).append(OpaqueId(row["evidence_id"]))
        return {key: tuple(value) for key, value in result.items()}

    def is_host_accepted_evidence(self, evidence_id: OpaqueId) -> bool:
        with self._lock:
            row = self._connection.execute(
                """SELECT 1 FROM generic_gate_evidence
                   WHERE evidence_id = ? AND accepted_by_host = 1 LIMIT 1""",
                (evidence_id.value,),
            ).fetchone()
        return row is not None

    def evidence_belongs_to_manifest(self, evidence_id: OpaqueId, manifest_id: str) -> bool:
        with self._lock:
            row = self._connection.execute(
                """SELECT 1 FROM generic_gate_evidence
                   WHERE evidence_id = ? AND manifest_id = ? AND accepted_by_host = 1 LIMIT 1""",
                (evidence_id.value, manifest_id),
            ).fetchone()
        return row is not None

    def evidence_instance_ids(self, evidence_id: OpaqueId) -> tuple[str, ...]:
        with self._lock:
            rows = self._connection.execute(
                """SELECT DISTINCT manifest.instance_id
                   FROM generic_gate_evidence evidence
                   JOIN generic_gate_manifests manifest
                     ON manifest.manifest_id = evidence.manifest_id
                    AND manifest.revision = evidence.revision
                   WHERE evidence.evidence_id = ? AND evidence.accepted_by_host = 1
                   ORDER BY manifest.instance_id""",
                (evidence_id.value,),
            ).fetchall()
        return tuple(row["instance_id"] for row in rows)

    def initialize_worklist(self, instance_id: str, items: list[object], checks: list[str]) -> None:
        now = time.time()
        with self.transaction() as connection:
            for ordinal, item in enumerate(items):
                item_id = item if isinstance(item, str) else str(item.get("item_id", "")) if isinstance(item, Mapping) else ""
                if not item_id:
                    raise ValueError("each worklist item must have a non-empty item_id")
                connection.execute(
                    """INSERT OR IGNORE INTO generic_work_items(
                        instance_id, item_id, ordinal, status, attempt_count,
                        last_evidence_sequence, required_checks_json, accepted_checks_json, updated_at
                    ) VALUES (?, ?, ?, 'pending', 0, 0, ?, '{}', ?)""",
                    (instance_id, item_id, ordinal, canonical_json(checks), now),
                )

    def work_items(self, instance_id: str) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM generic_work_items WHERE instance_id = ? ORDER BY ordinal",
                (instance_id,),
            ).fetchall()
        return tuple(
            {
                "item_id": row["item_id"], "status": row["status"],
                "attempt_count": row["attempt_count"], "artifact_id": row["artifact_id"],
                "required_checks": json.loads(row["required_checks_json"]),
                "accepted_checks": json.loads(row["accepted_checks_json"]),
                "last_evidence_sequence": row["last_evidence_sequence"],
            }
            for row in rows
        )

    def update_work_item(
        self,
        instance_id: str,
        item_id: str,
        *,
        status: str,
        artifact_id: Optional[OpaqueId] = None,
        accepted_checks: Optional[Mapping[str, OpaqueId]] = None,
        evidence_sequence: int = 0,
        increment_attempt: bool = False,
    ) -> None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM generic_work_items WHERE instance_id = ? AND item_id = ?",
                (instance_id, item_id),
            ).fetchone()
            if row is None:
                raise GenericCreatorNotFoundError(f"unknown work item {item_id!r}")
            if status == "accepted":
                required = set(json.loads(row["required_checks_json"]))
                check_ids = set(accepted_checks or {})
                if artifact_id is None or not required.issubset(check_ids):
                    raise GenericCreatorConflictError("work item requires an artifact and every independent check")
            connection.execute(
                """UPDATE generic_work_items SET status = ?, artifact_id = COALESCE(?, artifact_id),
                    accepted_checks_json = ?, last_evidence_sequence = ?,
                    attempt_count = attempt_count + ?, updated_at = ?
                   WHERE instance_id = ? AND item_id = ?""",
                (
                    status, None if artifact_id is None else artifact_id.value,
                    canonical_json(
                        {
                            key: value.value
                            for key, value in (accepted_checks or {}).items()
                        }
                    ),
                    evidence_sequence, int(increment_attempt), time.time(), instance_id, item_id,
                ),
            )

    def put_integration_edge(
        self,
        instance_id: str,
        edge_id: str,
        *,
        owner_instance_id: Optional[str],
        artifact_ids: tuple[str, ...],
        status: str = "pending",
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO generic_integration_edges(
                    instance_id, edge_id, owner_instance_id, status, artifact_ids_json,
                    evidence_ids_json, retest_required, updated_at
                ) VALUES (?, ?, ?, ?, ?, '[]', 0, ?)""",
                (instance_id, edge_id, owner_instance_id, status, canonical_json(list(artifact_ids)), time.time()),
            )

    def set_integration_edge(
        self, instance_id: str, edge_id: str, *, status: str,
        evidence_ids: tuple[OpaqueId, ...], retest_required: bool
    ) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE generic_integration_edges SET status = ?, evidence_ids_json = ?,
                    retest_required = ?, updated_at = ? WHERE instance_id = ? AND edge_id = ?""",
                (
                    status, canonical_json([item.value for item in evidence_ids]),
                    int(retest_required), time.time(), instance_id, edge_id,
                ),
            )
            if cursor.rowcount != 1:
                raise GenericCreatorNotFoundError(f"unknown integration edge {edge_id!r}")

    def integration_edges(self, instance_id: str) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM generic_integration_edges WHERE instance_id = ? ORDER BY edge_id",
                (instance_id,),
            ).fetchall()
        return tuple(
            {
                "edge_id": row["edge_id"], "owner_instance_id": row["owner_instance_id"],
                "status": row["status"], "artifact_ids": json.loads(row["artifact_ids_json"]),
                "evidence_ids": json.loads(row["evidence_ids_json"]),
                "retest_required": bool(row["retest_required"]),
            }
            for row in rows
        )

    def put_fault(self, fault: CreatorFaultRecord) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO generic_faults(
                    fault_id, reporting_instance_id, owning_instance_id, status,
                    record_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    fault.fault_id.value, fault.reporting_instance_id, fault.owning_instance_id,
                    fault.status.value, canonical_json(fault.as_record()), time.time(), time.time(),
                ),
            )

    def fault(self, fault_id: OpaqueId) -> CreatorFaultRecord:
        with self._lock:
            row = self._connection.execute(
                "SELECT record_json FROM generic_faults WHERE fault_id = ?", (fault_id.value,)
            ).fetchone()
        if row is None:
            raise GenericCreatorNotFoundError(f"unknown fault {fault_id.value!r}")
        return CreatorFaultRecord.from_record(self._decode(row, "record_json"))

    def put_repair(self, repair: CreatorRepairRequest) -> None:
        with self.transaction() as connection:
            fault_row = connection.execute(
                "SELECT record_json FROM generic_faults WHERE fault_id = ?",
                (repair.fault_id.value,),
            ).fetchone()
            if fault_row is None:
                raise GenericCreatorNotFoundError(f"unknown fault {repair.fault_id.value!r}")
            fault = CreatorFaultRecord.from_record(self._decode(fault_row, "record_json"))
            if fault.status is not FaultStatus.OPEN:
                raise GenericCreatorConflictError("fault already has a repair transition")
            updated_fault = replace(fault, status=FaultStatus.REPAIR_REQUESTED)
            connection.execute(
                """INSERT INTO generic_repairs(
                    repair_id, fault_id, owning_instance_id, status,
                    record_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    repair.repair_id.value, repair.fault_id.value, repair.owning_instance_id,
                    repair.status.value, canonical_json(repair.as_record()), time.time(), time.time(),
                ),
            )
            connection.execute(
                """UPDATE generic_faults SET status = ?, record_json = ?, updated_at = ?
                   WHERE fault_id = ?""",
                (
                    updated_fault.status.value, canonical_json(updated_fault.as_record()),
                    time.time(), fault.fault_id.value,
                ),
            )
            connection.execute(
                """INSERT INTO generic_audit_events(
                    instance_id, event_type, record_json, created_at
                ) VALUES (?, 'repair_requested', ?, ?)""",
                (
                    repair.owning_instance_id,
                    canonical_json(
                        {"fault_id": repair.fault_id.value, "repair_id": repair.repair_id.value}
                    ),
                    time.time(),
                ),
            )

    def repair(self, repair_id: OpaqueId) -> CreatorRepairRequest:
        with self._lock:
            row = self._connection.execute(
                "SELECT record_json FROM generic_repairs WHERE repair_id = ?",
                (repair_id.value,),
            ).fetchone()
        if row is None:
            raise GenericCreatorNotFoundError(f"unknown repair {repair_id.value!r}")
        return CreatorRepairRequest.from_record(self._decode(row, "record_json"))

    def update_repair_status(
        self, repair_id: OpaqueId, *, repair_status: RepairStatus, fault_status: FaultStatus
    ) -> None:
        with self.transaction() as connection:
            repair_row = connection.execute(
                "SELECT record_json FROM generic_repairs WHERE repair_id = ?",
                (repair_id.value,),
            ).fetchone()
            if repair_row is None:
                raise GenericCreatorNotFoundError(f"unknown repair {repair_id.value!r}")
            repair = CreatorRepairRequest.from_record(self._decode(repair_row, "record_json"))
            fault_row = connection.execute(
                "SELECT record_json FROM generic_faults WHERE fault_id = ?",
                (repair.fault_id.value,),
            ).fetchone()
            if fault_row is None:
                raise GenericCreatorNotFoundError(f"unknown fault {repair.fault_id.value!r}")
            fault = CreatorFaultRecord.from_record(self._decode(fault_row, "record_json"))
            updated_repair = replace(repair, status=repair_status)
            updated_fault = replace(fault, status=fault_status)
            now = time.time()
            connection.execute(
                "UPDATE generic_repairs SET status = ?, record_json = ?, updated_at = ? WHERE repair_id = ?",
                (
                    repair_status.value, canonical_json(updated_repair.as_record()),
                    now, repair_id.value,
                ),
            )
            connection.execute(
                "UPDATE generic_faults SET status = ?, record_json = ?, updated_at = ? WHERE fault_id = ?",
                (
                    fault_status.value, canonical_json(updated_fault.as_record()),
                    now, fault.fault_id.value,
                ),
            )
            connection.execute(
                """INSERT INTO generic_audit_events(
                    instance_id, event_type, record_json, created_at
                ) VALUES (?, 'repair_status_changed', ?, ?)""",
                (
                    repair.owning_instance_id,
                    canonical_json(
                        {
                            "fault_id": fault.fault_id.value,
                            "fault_status": fault_status.value,
                            "repair_id": repair_id.value,
                            "repair_status": repair_status.value,
                        }
                    ),
                    now,
                ),
            )

    def audit_events(self, instance_id: Optional[str] = None) -> tuple[dict[str, Any], ...]:
        sql = "SELECT * FROM generic_audit_events"
        args: tuple[object, ...] = ()
        if instance_id is not None:
            sql += " WHERE instance_id = ?"
            args = (instance_id,)
        sql += " ORDER BY sequence"
        with self._lock:
            rows = self._connection.execute(sql, args).fetchall()
        return tuple(
            {
                "sequence": row["sequence"], "instance_id": row["instance_id"],
                "event_type": row["event_type"], "record": self._decode(row, "record_json"),
            }
            for row in rows
        )


__all__ = [
    "GENERIC_CREATOR_STORE_SCHEMA_VERSION",
    "GenericCreatorConflictError",
    "GenericCreatorNotFoundError",
    "GenericCreatorStore",
    "GenericCreatorStoreError",
]
