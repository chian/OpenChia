"""Campaign projections in the existing Duet transaction, not a second database.

Immutable deltas are authoritative. Small indexes accelerate current-state reads;
they never duplicate the growing journal in a Run event. Public publication takes
an attempt, not worker-authored state, credit, or a claimed successful verdict.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent.duet_contracts import canonical_json, content_id, digest_record
from agent.duet_store import (
    DuetConflictError,
    DuetNotFoundError,
    DuetStore,
    DuetStoreError,
)
from agent.episode_contracts import OpaqueId

from .records import Ref, RefinementRecord

if TYPE_CHECKING:
    from .evidence import EvidenceReader


_INDEX_COLLECTIONS = (
    "assignment",
    "invocation",
    "check",
    "check_state",
    "evaluation",
    "observation",
    "research_source",
    "research_finding",
    "lesson",
    "conflict",
    "coordination",
    "unit",
    "report",
    "plan",
    "selection",
    "measure_proposal",
    "measure",
    "measure_control",
    "measure_need",
    "measure_definition",
    "measure_review",
    "evaluation_source",
    "evaluation_run",
)
_INDEX_SCHEMA = """CREATE TABLE IF NOT EXISTS refinement_index (
    campaign_id TEXT NOT NULL REFERENCES refinement_campaign_heads(campaign_id),
    collection TEXT NOT NULL CHECK (collection IN (%s)),
    item_key TEXT NOT NULL,
    record_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
    status TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    PRIMARY KEY (campaign_id, collection, item_key))""" % ", ".join(
    f"'{name}'" for name in _INDEX_COLLECTIONS
)
_COLLECTION_CHECK = re.compile(
    r"CHECK\s*\(\s*collection\s+IN\s*\(([^)]+)\)\s*\)", re.IGNORECASE
)

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS refinement_campaign_heads (
        campaign_id TEXT PRIMARY KEY,
        duet_id TEXT NOT NULL REFERENCES duets(duet_id),
        contract_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
        authority_head_id TEXT REFERENCES approvals(approval_id),
        initial_candidate_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
        candidate_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
        latest_commit_id TEXT REFERENCES artifacts(artifact_id),
        sequence INTEGER NOT NULL CHECK (sequence >= 0))""",
    """CREATE TABLE IF NOT EXISTS refinement_operations (
        campaign_id TEXT NOT NULL REFERENCES refinement_campaign_heads(campaign_id),
        operation_id TEXT NOT NULL,
        invocation_id TEXT NOT NULL,
        logical_unit_id TEXT NOT NULL,
        action TEXT NOT NULL,
        attempt_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
        commit_id TEXT REFERENCES artifacts(artifact_id),
        PRIMARY KEY (campaign_id, operation_id))""",
    _INDEX_SCHEMA,
    """CREATE TABLE IF NOT EXISTS refinement_fact_credits (
        campaign_id TEXT NOT NULL REFERENCES refinement_campaign_heads(campaign_id),
        judgment_lineage TEXT NOT NULL,
        semantic_fact_key TEXT NOT NULL,
        record_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
        receipt_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
        PRIMARY KEY (campaign_id, judgment_lineage, semantic_fact_key))""",
    """CREATE INDEX IF NOT EXISTS refinement_history_lookup
        ON refinement_index(campaign_id, collection, sequence)""",
    """CREATE INDEX IF NOT EXISTS refinement_unit_operations
        ON refinement_operations(campaign_id, invocation_id, logical_unit_id)""",
)


def _index_layout(sql: str) -> str:
    sql = _COLLECTION_CHECK.sub("CHECK (collection IN (collections))", sql)
    return (
        ""
        .join(sql.split())
        .casefold()
        .replace("ifnotexists", "")
        .replace('"refinement_index"', "refinement_index")
    )


def _upgrade_index_collections(connection: sqlite3.Connection) -> None:
    """Widen the development index constraint in the caller's Duet transaction.

    Artifacts, operations, campaign heads and credit are unchanged. Recognize only
    the same table with an older subset of collections; never downgrade an unknown
    schema or discard columns. SQLite cannot ALTER this CHECK constraint in place.
    """
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'refinement_index'"
    ).fetchone()
    sql = row[0]
    match = _COLLECTION_CHECK.search(sql)
    if match is None or _index_layout(sql) != _index_layout(_INDEX_SCHEMA):
        raise DuetStoreError("unrecognized refinement index layout; migration refused")
    values = re.findall(r"'([^']+)'", match[1])
    if (
        "".join(match[1].split()) != ",".join(f"'{value}'" for value in values)
        or len(values) != len(set(values))
        or not values
        or not set(values).issubset(_INDEX_COLLECTIONS)
    ):
        raise DuetStoreError(
            "unrecognized refinement index collections; migration refused"
        )
    if set(values) == set(_INDEX_COLLECTIONS):
        return
    objects = connection.execute(
        "SELECT type, name FROM sqlite_master WHERE tbl_name = 'refinement_index' "
        "AND type IN ('index', 'trigger') AND sql IS NOT NULL"
    ).fetchall()
    if any(tuple(item) != ("index", "refinement_history_lookup") for item in objects):
        raise DuetStoreError(
            "unrecognized refinement index extensions; migration refused"
        )
    # Copy before replacement; an error rolls back the entire existing write
    # transaction. Explicit columns retain every identity, status and sequence.
    connection.execute(
        _INDEX_SCHEMA.replace(
            "CREATE TABLE IF NOT EXISTS refinement_index",
            "CREATE TABLE refinement_index_upgrade",
            1,
        )
    )
    connection.execute(
        "INSERT INTO refinement_index_upgrade "
        "(campaign_id, collection, item_key, record_id, status, sequence) "
        "SELECT campaign_id, collection, item_key, record_id, status, sequence "
        "FROM refinement_index"
    )
    connection.execute("DROP TABLE refinement_index")
    connection.execute(
        "ALTER TABLE refinement_index_upgrade RENAME TO refinement_index"
    )
    connection.execute(
        "CREATE INDEX refinement_history_lookup "
        "ON refinement_index(campaign_id, collection, sequence)"
    )


@dataclass(frozen=True)
class IndexEntry:
    collection: str
    key: str
    record: RefinementRecord
    status: str
    sequence: int


class CampaignView:
    """One transaction-consistent read view supplied to host admission functions."""

    def __init__(self, connection: sqlite3.Connection, campaign_id: OpaqueId):
        self.connection = connection
        self.campaign_id = campaign_id
        head = connection.execute(
            "SELECT * FROM refinement_campaign_heads WHERE campaign_id = ?",
            (campaign_id.value,),
        ).fetchone()
        if head is None:
            raise DuetNotFoundError("unknown refinement campaign")
        self.head = dict(head)

    def read(self, reference: Ref | str, kind: str | None = None) -> RefinementRecord:
        identifier = (
            reference.artifact_id.value if isinstance(reference, Ref) else reference
        )
        row = self.connection.execute(
            "SELECT duet_id, content_hash, record_json FROM artifacts WHERE artifact_id = ?",
            (identifier,),
        ).fetchone()
        if row is None:
            raise DuetNotFoundError("missing campaign artifact")
        result = RefinementRecord.from_record(json.loads(row["record_json"]))
        if (
            result.campaign_id != self.campaign_id
            or row["duet_id"] != self.head["duet_id"]
            or row["content_hash"] != result.content_hash.value
            or (isinstance(reference, Ref) and result.ref != reference)
            or (kind is not None and result.kind != kind)
        ):
            raise ValueError("artifact lineage, kind, or identity does not match")
        return result

    def entries(self, collection: str) -> tuple[IndexEntry, ...]:
        rows = self.connection.execute(
            "SELECT * FROM refinement_index WHERE campaign_id = ? AND collection = ? "
            "ORDER BY sequence, item_key",
            (self.campaign_id.value, collection),
        ).fetchall()
        return tuple(
            IndexEntry(
                row["collection"],
                row["item_key"],
                self.read(row["record_id"]),
                row["status"],
                row["sequence"],
            )
            for row in rows
        )

    def data(self, reference: Ref):
        """Read exact campaign reference data inside this transaction."""
        row = self.connection.execute(
            "SELECT duet_id, content_hash, record_json FROM artifacts WHERE artifact_id = ?",
            (reference.artifact_id.value,),
        ).fetchone()
        if (
            row is None
            or row["duet_id"] != self.head["duet_id"]
            or row["content_hash"] != reference.content_hash.value
        ):
            raise ValueError("campaign data reference is missing or changed")
        value = json.loads(row["record_json"])
        if digest_record(value) != reference.content_hash:
            raise ValueError("campaign reference data hash differs")
        return value

    def entry(self, collection: str, key: str) -> IndexEntry:
        row = self.connection.execute(
            "SELECT * FROM refinement_index WHERE campaign_id = ? AND collection = ? AND item_key = ?",
            (self.campaign_id.value, collection, key),
        ).fetchone()
        if row is None:
            raise DuetNotFoundError(f"no admitted {collection} with that key")
        return IndexEntry(
            collection, key, self.read(row["record_id"]), row["status"], row["sequence"]
        )

    def credited(self, lineage: str) -> frozenset[str]:
        return frozenset(
            row[0]
            for row in self.connection.execute(
                "SELECT semantic_fact_key FROM refinement_fact_credits WHERE campaign_id = ? AND judgment_lineage = ?",
                (self.campaign_id.value, lineage),
            )
        )

    @property
    def candidate(self) -> RefinementRecord:
        return self.read(self.head["candidate_id"], "candidate")

    @property
    def contract(self) -> RefinementRecord:
        return self.read(self.head["contract_id"], "campaign")


class CampaignStore:
    def __init__(self, duet_store: DuetStore, evidence: EvidenceReader):
        self.duet_store = duet_store
        self.evidence = evidence
        # Additive and transactional; old refinement_cycles retain their meaning.
        with duet_store.transaction() as connection:
            for statement in _SCHEMA:
                connection.execute(statement)
            _upgrade_index_collections(connection)

    @staticmethod
    def data_reference(duet_id: str, kind: str, value: dict) -> Ref:
        return Ref(
            content_id("refinement_data", {"duet_id": duet_id, "kind": kind, "value": value}),
            digest_record(value),
        )

    def put_data(self, duet_id: str, kind: str, value: dict) -> Ref:
        """Store reference data; this does not admit it or grant it authority."""
        ref = self.data_reference(duet_id, kind, value)
        self.duet_store.put_artifact(
            artifact_id=ref.artifact_id.value,
            duet_id=duet_id,
            kind=f"refinement.{kind}.v1",
            revision=1,
            content_hash=ref.content_hash.value,
            record=value,
        )
        return ref

    def _put(self, connection, duet_id: str, value: RefinementRecord) -> None:
        self.duet_store._put_artifact(
            connection,
            artifact_id=value.artifact_id.value,
            duet_id=duet_id,
            kind=f"refinement.{value.kind}.v1",
            revision=1,
            content_hash=value.content_hash.value,
            payload=canonical_json(value.as_record()),
        )

    def start(self, contract: RefinementRecord, initial: RefinementRecord) -> None:
        """Install an already host-authorized contract; no executable authority is minted.

        The explicit entry point verifies the target/refiner approvals. This layer
        independently verifies stored references, lineage and the authority CAS.
        """
        if contract.kind != "campaign" or initial.kind != "candidate":
            raise ValueError("campaign start requires campaign and candidate records")
        if (
            contract.campaign_id != initial.campaign_id
            or initial.body["parent_candidate_ref"] is not None
        ):
            raise ValueError("initial candidate must be the campaign's root revision")
        if initial.body["target_approval_ref"] != contract.body["target_approval_ref"]:
            raise ValueError("candidate names a different target approval")
        self.evidence.validate_candidate(initial)
        handoff = self.evidence.validate_contract(contract)
        from .instrument_builds import initial_sources

        expected_files = {
            **handoff["candidate"]["files"],
            **initial_sources(self.evidence, contract),
        }
        if dict(initial.body["files"]) != expected_files:
            raise ValueError("initial candidate must retain the exact handoff source")
        duet_id = contract.body["duet_id"]
        authority = Ref.from_record(
            contract.body["target_approval_ref"]
        ).artifact_id.value
        with self.duet_store.transaction() as connection:
            existing = connection.execute(
                "SELECT contract_id, initial_candidate_id FROM refinement_campaign_heads WHERE campaign_id = ?",
                (contract.campaign_id.value,),
            ).fetchone()
            if existing is not None:
                if existing[0] != contract.artifact_id.value:
                    raise DuetConflictError(
                        "campaign identity already has another contract"
                    )
                if existing["initial_candidate_id"] != initial.artifact_id.value:
                    raise DuetConflictError(
                        "campaign identity already has another initial candidate"
                    )
                return
            self._authority(connection, duet_id, authority)
            self._put(connection, duet_id, contract)
            self._put(connection, duet_id, initial)
            connection.execute(
                "INSERT INTO refinement_campaign_heads VALUES (?, ?, ?, ?, ?, ?, NULL, 0)",
                (
                    contract.campaign_id.value,
                    duet_id,
                    contract.artifact_id.value,
                    authority,
                    initial.artifact_id.value,
                    initial.artifact_id.value,
                ),
            )
            self.duet_store._append_event(
                connection,
                duet_id=duet_id,
                event_type="refinement_campaign_started",
                provenance="host_validation",
                record={
                    "contract": contract.ref.as_record(),
                    "initial_candidate": initial.ref.as_record(),
                },
            )

    @staticmethod
    def _authority(connection, duet_id: str, authority: str) -> None:
        row = connection.execute(
            "SELECT authority_head_approval_id FROM duets WHERE duet_id = ?",
            (duet_id,),
        ).fetchone()
        if row is None or row[0] != authority:
            raise DuetConflictError("campaign target authority is no longer current")
        approval = connection.execute(
            "SELECT revoked_at FROM approvals WHERE approval_id = ? AND duet_id = ?",
            (authority, duet_id),
        ).fetchone()
        if approval is None or approval[0] is not None:
            raise DuetConflictError("campaign authority is absent or revoked")

    def record_attempt(self, attempt: RefinementRecord) -> RefinementRecord:
        """Audit first, including rejected proposals; retry cannot replace the payload."""
        if attempt.kind != "attempt":
            raise ValueError("expected a typed attempt")
        OpaqueId(attempt.body["operation_id"])
        with self.duet_store.transaction() as connection:
            view = CampaignView(connection, attempt.campaign_id)
            existing = connection.execute(
                "SELECT attempt_id FROM refinement_operations WHERE campaign_id = ? AND operation_id = ?",
                (attempt.campaign_id.value, attempt.body["operation_id"]),
            ).fetchone()
            if existing is not None:
                if existing[0] != attempt.artifact_id.value:
                    raise DuetConflictError(
                        "an audited operation cannot be replaced on retry"
                    )
                return view.read(existing[0], "attempt")
            self._authority(
                connection, view.head["duet_id"], view.head["authority_head_id"]
            )
            self._put(connection, view.head["duet_id"], attempt)
            connection.execute(
                "INSERT INTO refinement_operations VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (
                    attempt.campaign_id.value,
                    attempt.body["operation_id"],
                    attempt.body["invocation_id"],
                    attempt.body["logical_unit_id"],
                    attempt.body["action"],
                    attempt.artifact_id.value,
                ),
            )
        return attempt

    def commit_attempt(self, attempt: RefinementRecord) -> RefinementRecord:
        from .state_machine import admit_attempt

        self.record_attempt(attempt)
        with self.duet_store.transaction() as connection:
            row = connection.execute(
                "SELECT commit_id FROM refinement_operations WHERE campaign_id = ? AND operation_id = ?",
                (attempt.campaign_id.value, attempt.body["operation_id"]),
            ).fetchone()
            if row[0] is not None:
                return CampaignView(connection, attempt.campaign_id).read(
                    row[0], "commit"
                )
        # Resolve evidence outside the writer transaction. The referenced stores
        # are immutable; admission below still checks request/candidate bindings.
        resolved = self.evidence.resolve_attempt(attempt)
        with self.duet_store.transaction() as connection:
            view = CampaignView(connection, attempt.campaign_id)
            operation = connection.execute(
                "SELECT * FROM refinement_operations WHERE campaign_id = ? AND operation_id = ?",
                (attempt.campaign_id.value, attempt.body["operation_id"]),
            ).fetchone()
            if operation["commit_id"] is not None:
                return view.read(operation["commit_id"], "commit")
            self._authority(
                connection, view.head["duet_id"], view.head["authority_head_id"]
            )
            records, deltas = admit_attempt(view, attempt, resolved)
            for record in records:
                self._put(connection, view.head["duet_id"], record)
            predecessor = (
                view.read(view.head["latest_commit_id"]).ref
                if view.head["latest_commit_id"]
                else None
            )
            commit = RefinementRecord(
                "commit",
                attempt.campaign_id,
                {
                    "previous_commit_ref": predecessor.as_record()
                    if predecessor
                    else None,
                    "sequence": view.head["sequence"] + 1,
                    "attempt_ref": attempt.ref.as_record(),
                    "deltas": deltas,
                },
                view.contract.producer_ref,
                predecessor_refs=(predecessor,) if predecessor else (),
            )
            self._put(connection, view.head["duet_id"], commit)
            self._apply(connection, view, commit)
            connection.execute(
                "UPDATE refinement_operations SET commit_id = ? WHERE campaign_id = ? AND operation_id = ?",
                (
                    commit.artifact_id.value,
                    attempt.campaign_id.value,
                    attempt.body["operation_id"],
                ),
            )
            self.duet_store._append_event(
                connection,
                duet_id=view.head["duet_id"],
                event_type="refinement_committed",
                provenance="host_validation",
                record={"commit": commit.ref.as_record()},
            )
            return commit

    @staticmethod
    def _apply(connection, view: CampaignView, commit: RefinementRecord) -> None:
        """Apply only independently re-derived, closed host deltas."""
        from .integrity import validate_commit

        validate_commit(view, commit)
        candidate_id = view.head["candidate_id"]
        for delta in commit.body["deltas"]:
            kind = delta["kind"]
            if kind == "head":
                if delta["before"] != candidate_id:
                    raise DuetConflictError("candidate compare-and-swap failed")
                candidate_id = delta["after"]
            elif kind == "index":
                connection.execute(
                    "INSERT INTO refinement_index VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(campaign_id, collection, item_key) DO UPDATE SET "
                    "record_id=excluded.record_id, status=excluded.status, sequence=excluded.sequence",
                    (
                        view.campaign_id.value,
                        delta["collection"],
                        delta["key"],
                        delta["record_id"],
                        delta["status"],
                        commit.body["sequence"],
                    ),
                )
            elif kind == "credit":
                connection.execute(
                    "INSERT INTO refinement_fact_credits VALUES (?, ?, ?, ?, ?)",
                    (
                        view.campaign_id.value,
                        delta["lineage"],
                        delta["key"],
                        delta["record_id"],
                        delta["receipt_id"],
                    ),
                )
            else:
                raise ValueError("unregistered campaign delta")
        updated = connection.execute(
            "UPDATE refinement_campaign_heads SET candidate_id = ?, latest_commit_id = ?, sequence = ? "
            "WHERE campaign_id = ? AND sequence = ? AND candidate_id = ?",
            (
                candidate_id,
                commit.artifact_id.value,
                commit.body["sequence"],
                view.campaign_id.value,
                view.head["sequence"],
                view.head["candidate_id"],
            ),
        ).rowcount
        if updated != 1:
            raise DuetConflictError("campaign state changed concurrently")

    def read(self, campaign_id: OpaqueId, reference: Ref) -> RefinementRecord:
        with self.duet_store.transaction() as connection:
            return CampaignView(connection, campaign_id).read(reference)

    def project(
        self, campaign_id: OpaqueId, invocation_id: OpaqueId
    ) -> RefinementRecord:
        from .reports import parent_report

        with self.duet_store.transaction() as connection:
            return parent_report(CampaignView(connection, campaign_id), invocation_id)

    def context(
        self, campaign_id: OpaqueId, invocation_id: OpaqueId
    ) -> RefinementRecord:
        from .context import local_context

        with self.duet_store.transaction() as connection:
            return local_context(CampaignView(connection, campaign_id), invocation_id)
