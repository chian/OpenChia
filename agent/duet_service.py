"""Host-owned Duet protocol, admission gates, and atomic workflow launch."""

from __future__ import annotations

import json
import re
import threading
from typing import Any, Iterable, Mapping, Optional

from agent.duet_contracts import (
    AdmittedCreatorContract,
    ApprovalKind,
    ContractDeficit,
    CreatorActivityEnvelope,
    CreatorGuidance,
    CreatorProgressEnvelope,
    DuetApproval,
    DuetDecision,
    DuetDesignState,
    DuetIdentity,
    DuetMessageKind,
    DuetPolicy,
    DuetProvenance,
    FrozenDuetWorkflow,
    FrozenWorkflowDesign,
    WorkflowAdmissionAuthority,
    WorkflowCandidate,
    canonical_json,
    content_id,
)
from agent.duet_store import (
    DuetConflictError,
    DuetNotFoundError,
    DuetStore,
)
from agent.episode_blueprints import (
    workflow_spec_from_blueprint,
)
from agent.episode_contracts import (
    CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
    EpisodeContractError,
    EpisodeCreationSpec,
    EpisodeCreatorContext,
    EpisodeCreatorContextReference,
    EpisodeCreatorStatusField,
    EpisodeMeasuredOutcome,
    EpisodeWorkflowDesignProjection,
    EpisodeWorkflowDesignResult,
    EpisodeWorkflowSpec,
    OpaqueId,
    Sha256Digest,
    MAX_CREATOR_CONTEXT_ARTIFACT_BYTES,
    MAX_CREATOR_CONTEXT_TOTAL_BYTES,
)
from method_loop.identities import EpisodeRef


_CREATOR_CONTEXT_ARTIFACT_KIND = "creator_context"
EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND = "episode_workflow_draft"
_EPISODE_WORKFLOW_DRAFT_SCHEMA_VERSION = 1
_EPISODE_WORKFLOW_DRAFT_SOURCE_STAGES = frozenset(
    {"duet", "candidate", "human_edit", "frozen"}
)
_SECRET_CONTEXT_KEY = re.compile(
    r"(?:^|[_-])(?:password|passwd|secret|api[_-]?key|private[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|auth[_-]?token)$|"
    r"^(?:token|credential|authorization)$",
    re.IGNORECASE,
)
_RAW_SECRET_VALUE = re.compile(
    r"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{16,})"
)


def _reject_raw_context_secrets(value: object, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if _SECRET_CONTEXT_KEY.search(str(key)):
                raise ValueError(
                    f"Creator context cannot contain a secret-shaped key at {path}.{key}"
                )
            _reject_raw_context_secrets(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_raw_context_secrets(child, f"{path}[{index}]")
    elif isinstance(value, str) and _RAW_SECRET_VALUE.search(value):
        raise ValueError(f"Creator context cannot contain a raw secret at {path}")


class DuetProtocolError(RuntimeError):
    """The requested operation violates the typed Duet protocol."""


class CreatorContextValidationError(DuetProtocolError):
    """A context reference failed a mechanical ownership or integrity gate."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class StaleDuetApprovalError(DuetProtocolError):
    """An approval does not bind the exact current artifact revision and hash."""


class WorkflowAdmissionError(DuetProtocolError):
    """A workflow candidate failed deterministic admission."""

    def __init__(self, deficits: Iterable[ContractDeficit]) -> None:
        self.deficits = tuple(deficits)
        super().__init__(
            "workflow admission failed: "
            + ", ".join(f"{item.field_path}:{item.code}" for item in self.deficits)
        )


def _policy_from_record(record: Mapping[str, Any]) -> DuetPolicy:
    return DuetPolicy.from_record(record)


def _approval_from_record(record: Mapping[str, Any]) -> DuetApproval:
    return DuetApproval(
        approval_id=OpaqueId(record["approval_id"]),
        duet_id=OpaqueId(record["duet_id"]),
        human_authority_id=OpaqueId(record["human_authority_id"]),
        kind=ApprovalKind(record["kind"]),
        artifact_id=OpaqueId(record["artifact_id"]),
        content_hash=Sha256Digest(record["content_hash"]),
        revision=record["revision"],
    )


def _admitted_creator_from_artifact(
    record: Mapping[str, Any],
) -> AdmittedCreatorContract:
    return AdmittedCreatorContract.from_record(record)


class DuetService:
    """The one authority boundary used by UI, Duet tools, and Creator runtime."""

    def __init__(
        self,
        store: DuetStore,
        *,
        allowed_episode_capabilities: Iterable[str],
    ) -> None:
        if not isinstance(store, DuetStore):
            raise TypeError("DuetService requires a DuetStore")
        capabilities = tuple(sorted(set(allowed_episode_capabilities)))
        if any(not isinstance(item, str) or not item for item in capabilities):
            raise ValueError("allowed Episode capabilities must be names")
        self.store = store
        self.allowed_episode_capabilities = frozenset(capabilities)
        self._workflow_draft_lock = threading.RLock()

    def open_duet(
        self,
        identity: DuetIdentity,
        policy: DuetPolicy,
    ) -> None:
        if identity.policy_id != policy.policy_id:
            raise ValueError("Duet identity and policy IDs differ")
        existing = self.store.get_duet(identity.duet_id.value)
        if existing is None:
            self.store.create_duet(
                duet_id=identity.duet_id.value,
                identity=identity.as_record(),
                policy=policy.as_record(),
                state=DuetDesignState.DESIGNING.value,
            )
            return
        if (
            existing["identity"] != identity.as_record()
            or existing["policy"] != policy.as_record()
        ):
            self.store.rebind_duet_policy(
                duet_id=identity.duet_id.value,
                identity=identity.as_record(),
                policy=policy.as_record(),
            )

    def _duet_row(self, duet_id: OpaqueId) -> dict[str, Any]:
        row = self.store.get_duet(duet_id.value)
        if row is None:
            raise DuetNotFoundError("unknown Duet")
        return row

    def policy(self, duet_id: OpaqueId) -> DuetPolicy:
        return _policy_from_record(self._duet_row(duet_id)["policy"])

    def register_creator_context_artifact(
        self,
        duet_id: OpaqueId,
        *,
        artifact_kind: str,
        schema_version: int,
        purpose: str,
        required: bool,
        content: Mapping[str, Any],
        producer_creator_episode_id: Optional[OpaqueId] = None,
        provenance: DuetProvenance = DuetProvenance.LLM_PROPOSAL,
    ) -> EpisodeCreatorContextReference:
        """Persist one exact structured document and return its immutable reference."""

        self._duet_row(duet_id)
        if not isinstance(provenance, DuetProvenance):
            raise TypeError("Creator context provenance must be a DuetProvenance")
        if not isinstance(content, Mapping):
            raise ValueError("Creator context artifact content must be an object")
        normalized = json.loads(canonical_json(content))
        _reject_raw_context_secrets(normalized)
        producer_id = (
            None
            if producer_creator_episode_id is None
            else producer_creator_episode_id.value
        )
        if producer_id is not None:
            producer = self.store.get_creator(producer_id)
            if producer is None or producer["duet_id"] != duet_id.value:
                raise DuetProtocolError(
                    "Creator context producer is outside the active Duet"
                )
        record = {
            "artifact_kind": artifact_kind,
            "schema_version": schema_version,
            "purpose": purpose,
            "required": required,
            "content": normalized,
        }
        encoded = canonical_json(record).encode("utf-8")
        if len(encoded) > MAX_CREATOR_CONTEXT_ARTIFACT_BYTES:
            raise ValueError(
                "Creator context artifact exceeds the per-artifact byte budget"
            )
        digest = Sha256Digest.of_bytes(encoded)
        artifact_id = content_id(
            "context",
            {
                "duet_id": duet_id.value,
                "producer_creator_episode_id": producer_id,
                "content_hash": digest.value,
            },
        )
        reference = EpisodeCreatorContextReference(
            artifact_id=artifact_id,
            content_hash=digest,
            artifact_kind=artifact_kind,
            schema_version=schema_version,
            purpose=purpose,
            required=required,
        )
        self.store.put_artifact(
            artifact_id=artifact_id.value,
            duet_id=duet_id.value,
            creator_episode_id=producer_id,
            kind=_CREATOR_CONTEXT_ARTIFACT_KIND,
            revision=0,
            content_hash=digest.value,
            record=record,
        )
        self.store.append_event(
            duet_id=duet_id.value,
            event_type="creator_context_artifact_registered",
            provenance=provenance.value,
            record={
                "artifact_id": artifact_id.value,
                "content_hash": digest.value,
                "artifact_kind": reference.artifact_kind,
                "schema_version": reference.schema_version,
                "purpose": reference.purpose,
                "required": reference.required,
                "producer_creator_episode_id": producer_id,
            },
        )
        return reference

    def read_creator_context_artifact(
        self,
        duet_id: OpaqueId,
        artifact_id: OpaqueId,
    ) -> dict[str, Any]:
        """Return one whole context artifact after verifying its immutable digest."""

        self._duet_row(duet_id)
        artifact = self.store.get_artifact(artifact_id.value)
        if (
            artifact is None
            or artifact["duet_id"] != duet_id.value
            or artifact["kind"] != _CREATOR_CONTEXT_ARTIFACT_KIND
        ):
            raise DuetNotFoundError("unknown Creator context artifact")
        record = artifact["record"]
        if set(record) != {
            "artifact_kind",
            "schema_version",
            "purpose",
            "required",
            "content",
        }:
            raise CreatorContextValidationError(
                "context_artifact_malformed",
                "Creator context artifact contains unknown or missing fields",
            )
        encoded = canonical_json(record).encode("utf-8")
        digest = Sha256Digest.of_bytes(encoded)
        if digest.value != artifact["content_hash"]:
            raise CreatorContextValidationError(
                "context_artifact_hash_mismatch",
                "Creator context artifact no longer matches its stored digest",
            )
        return {
            "artifact_id": artifact_id.value,
            "content_hash": digest.value,
            "artifact_kind": record["artifact_kind"],
            "schema_version": record["schema_version"],
            "purpose": record["purpose"],
            "required": record["required"],
            "producer_creator_episode_id": artifact["creator_episode_id"],
            "content": record["content"],
        }

    def list_creator_context_artifacts(
        self,
        duet_id: OpaqueId,
    ) -> tuple[dict[str, Any], ...]:
        """Project resumable artifact metadata without repeating full content."""

        self._duet_row(duet_id)
        return tuple(
            {
                "artifact_id": artifact["artifact_id"],
                "content_hash": artifact["content_hash"],
                "artifact_kind": artifact["record"]["artifact_kind"],
                "schema_version": artifact["record"]["schema_version"],
                "purpose": artifact["record"]["purpose"],
                "required": artifact["record"]["required"],
                "producer_creator_episode_id": artifact["creator_episode_id"],
            }
            for artifact in self.store.artifacts_by_kind(
                duet_id=duet_id.value,
                kind=_CREATOR_CONTEXT_ARTIFACT_KIND,
            )
        )

    def _creator_lineage_ids(self, creator_episode_id: OpaqueId) -> set[str]:
        lineage: set[str] = set()
        cursor: Optional[str] = creator_episode_id.value
        duet_id: Optional[str] = None
        while cursor is not None:
            if cursor in lineage:
                raise DuetProtocolError("Creator authority lineage contains a cycle")
            row = self.store.get_creator(cursor)
            if row is None:
                raise DuetNotFoundError("Creator authority lineage is incomplete")
            if duet_id is None:
                duet_id = row["duet_id"]
            elif row["duet_id"] != duet_id:
                raise DuetProtocolError("Creator authority lineage crosses Duets")
            lineage.add(cursor)
            cursor = row.get("parent_creator_episode_id")
        return lineage

    def resolve_creator_context(
        self,
        duet_id: OpaqueId,
        context: EpisodeCreatorContext,
        *,
        consumer_creator_episode_id: Optional[OpaqueId] = None,
    ) -> dict[str, dict[str, Any]]:
        """Resolve and verify a manifest without rewriting or summarizing content."""

        if not isinstance(context, EpisodeCreatorContext):
            raise TypeError("context must be an EpisodeCreatorContext")
        self._duet_row(duet_id)
        allowed_owners = (
            set()
            if consumer_creator_episode_id is None
            else self._creator_lineage_ids(consumer_creator_episode_id)
        )
        resolved: dict[str, dict[str, Any]] = {}
        total_bytes = 0
        for reference in context.artifact_references:
            artifact = self.store.get_artifact(reference.artifact_id.value)
            if artifact is None:
                raise CreatorContextValidationError(
                    "context_artifact_missing",
                    f"missing Creator context artifact {reference.artifact_id.value}",
                )
            if artifact["duet_id"] != duet_id.value:
                raise CreatorContextValidationError(
                    "context_artifact_scope_violation",
                    "Creator context artifact is outside the contract's Duet",
                )
            if artifact["kind"] != _CREATOR_CONTEXT_ARTIFACT_KIND:
                raise CreatorContextValidationError(
                    "context_artifact_kind_mismatch",
                    "Only an artifact committed through creator_context_artifact "
                    "may appear in creator_contract.design_context; workflow, "
                    "approval, and prior contract artifacts are not context receipts",
                )
            owner = artifact["creator_episode_id"]
            if owner is not None and owner not in allowed_owners:
                raise CreatorContextValidationError(
                    "context_artifact_scope_violation",
                    "Creator context artifact is outside the consumer authority lineage",
                )
            record = artifact["record"]
            if set(record) != {
                "artifact_kind",
                "schema_version",
                "purpose",
                "required",
                "content",
            }:
                raise CreatorContextValidationError(
                    "context_artifact_malformed",
                    "Creator context artifact contains unknown or missing fields",
                )
            encoded = canonical_json(record).encode("utf-8")
            total_bytes += len(encoded)
            if len(encoded) > MAX_CREATOR_CONTEXT_ARTIFACT_BYTES:
                raise CreatorContextValidationError(
                    "context_artifact_too_large",
                    "Creator context artifact exceeds its byte budget",
                )
            digest = Sha256Digest.of_bytes(encoded)
            if (
                digest != reference.content_hash
                or artifact["content_hash"] != reference.content_hash.value
            ):
                raise CreatorContextValidationError(
                    "context_artifact_hash_mismatch",
                    "Creator context artifact hash does not match its reference",
                )
            if (
                record["artifact_kind"] != reference.artifact_kind
                or record["schema_version"] != reference.schema_version
                or record["purpose"] != reference.purpose
                or record["required"] != reference.required
            ):
                raise CreatorContextValidationError(
                    "context_artifact_metadata_mismatch",
                    "Creator context artifact metadata does not match its reference",
                )
            resolved[reference.artifact_id.value] = {
                "reference": reference.as_record(),
                "content": record["content"],
            }
        if total_bytes > MAX_CREATOR_CONTEXT_TOTAL_BYTES:
            raise CreatorContextValidationError(
                "context_budget_exceeded",
                "Creator context manifest exceeds the aggregate exact-delivery budget",
            )
        return resolved

    def creator_context_artifacts(
        self,
        creator_episode_id: OpaqueId,
    ) -> dict[str, dict[str, Any]]:
        frozen = self.creator_contract(creator_episode_id)
        contract = frozen.contract.creator_contract
        if contract is None:
            return {}
        return self.resolve_creator_context(
            frozen.duet_id,
            contract.design_context,
            consumer_creator_episode_id=creator_episode_id,
        )

    def record_human_approval(
        self,
        identity: DuetIdentity,
        *,
        kind: ApprovalKind,
        artifact_id: OpaqueId,
        content_hash: Sha256Digest,
        revision: int,
    ) -> DuetApproval:
        """Trusted UI/CLI operation; this is never exposed as a model tool."""

        if self._duet_row(identity.duet_id)["identity"] != identity.as_record():
            raise DuetProtocolError("human approval authority does not match the Duet")
        approval_id = content_id(
            "approval",
            {
                "duet_id": identity.duet_id.value,
                "human_authority_id": identity.human_authority_id.value,
                "kind": kind.value,
                "artifact_id": artifact_id.value,
                "content_hash": content_hash.value,
                "revision": revision,
            },
        )
        approval = DuetApproval(
            approval_id=approval_id,
            duet_id=identity.duet_id,
            human_authority_id=identity.human_authority_id,
            kind=kind,
            artifact_id=artifact_id,
            content_hash=content_hash,
            revision=revision,
        )
        self.store.put_approval(approval.as_record())
        self.store.append_event(
            duet_id=identity.duet_id.value,
            event_type=f"{kind.value}_approved",
            provenance=DuetProvenance.HUMAN_APPROVAL.value,
            record=approval.as_record(),
        )
        return approval

    def _require_exact_approval(
        self,
        *,
        approval_id: OpaqueId,
        kind: ApprovalKind,
        artifact_id: OpaqueId,
        content_hash: Sha256Digest,
        revision: int,
    ) -> DuetApproval:
        record = self.store.get_approval(approval_id.value)
        if record is None or record.pop("revoked", False):
            raise StaleDuetApprovalError("approval is missing or revoked")
        approval = _approval_from_record(record)
        if (
            approval.kind is not kind
            or approval.artifact_id != artifact_id
            or approval.content_hash != content_hash
            or approval.revision != revision
        ):
            raise StaleDuetApprovalError(
                "approval does not bind this exact artifact revision and hash"
            )
        return approval

    def _admit_creator_node(
        self,
        *,
        duet_id: OpaqueId,
        source_design_artifact_id: OpaqueId,
        source_design_hash: Sha256Digest,
        workflow_approval_id: OpaqueId,
        node_local_id: str,
        contract: EpisodeCreationSpec,
        source_revision: int,
        parent_creator_episode_id: Optional[OpaqueId] = None,
    ) -> OpaqueId:
        if not contract.can_create_episodes or contract.creator_contract is None:
            raise DuetProtocolError("selected workflow node is not a Creator Episode")
        creator_episode_id = content_id(
            "creator",
            {
                "duet_id": duet_id.value,
                "source_design_artifact_id": source_design_artifact_id.value,
                "source_design_hash": source_design_hash.value,
                "node_local_id": node_local_id,
                "contract_hash": contract.spec_hash.value,
                "parent_creator_episode_id": (
                    None
                    if parent_creator_episode_id is None
                    else parent_creator_episode_id.value
                ),
            },
        )
        contract_artifact_id = content_id(
            "creator_contract",
            {
                "creator_episode_id": creator_episode_id.value,
                "source_design_artifact_id": source_design_artifact_id.value,
                "node_local_id": node_local_id,
                "contract_hash": contract.spec_hash.value,
            },
        )
        admitted = AdmittedCreatorContract(
            artifact_id=contract_artifact_id,
            duet_id=duet_id,
            source_design_artifact_id=source_design_artifact_id,
            source_design_hash=source_design_hash,
            workflow_approval_id=workflow_approval_id,
            node_local_id=node_local_id,
            content_hash=contract.spec_hash,
            contract=contract,
        )
        self.store.put_artifact(
            artifact_id=contract_artifact_id.value,
            duet_id=duet_id.value,
            creator_episode_id=creator_episode_id.value,
            kind="admitted_creator_contract",
            revision=source_revision,
            content_hash=contract.spec_hash.value,
            record=admitted.as_record(),
        )
        self.store.admit_creator(
            creator_episode_id=creator_episode_id.value,
            duet_id=duet_id.value,
            contract_artifact_id=contract_artifact_id.value,
            contract_hash=contract.spec_hash.value,
            approval_id=workflow_approval_id.value,
            parent_creator_episode_id=(
                None
                if parent_creator_episode_id is None
                else parent_creator_episode_id.value
            ),
            design_artifact_id=source_design_artifact_id.value,
            node_local_id=node_local_id,
            state=DuetDesignState.DESIGNING.value,
        )
        self.store.append_event(
            duet_id=duet_id.value,
            event_type="creator_episode_admitted",
            provenance=DuetProvenance.HOST_VALIDATION.value,
            record={
                "creator_episode_id": creator_episode_id.value,
                "parent_creator_episode_id": (
                    None
                    if parent_creator_episode_id is None
                    else parent_creator_episode_id.value
                ),
                "source_design_artifact_id": source_design_artifact_id.value,
                "node_local_id": node_local_id,
                "contract_hash": contract.spec_hash.value,
            },
        )
        return creator_episode_id

    def admit_workflow_creator(
        self,
        *,
        frozen_workflow: FrozenDuetWorkflow,
        workflow_approval_id: OpaqueId,
        node_local_id: str,
    ) -> OpaqueId:
        """Admit a Creator node explicitly present in an approved Duet workflow."""

        artifact = self.store.get_artifact(frozen_workflow.artifact_id.value)
        if (
            artifact is None
            or artifact["kind"] != "duet_workflow"
            or artifact["record"] != frozen_workflow.as_record()
        ):
            raise DuetNotFoundError("frozen Duet workflow artifact not found")
        self._require_exact_approval(
            approval_id=workflow_approval_id,
            kind=ApprovalKind.WORKFLOW,
            artifact_id=frozen_workflow.artifact_id,
            content_hash=frozen_workflow.workflow_hash,
            revision=frozen_workflow.revision,
        )
        node = next(
            (
                item
                for item in frozen_workflow.workflow.episodes
                if item.local_id == node_local_id
            ),
            None,
        )
        if node is None:
            raise DuetNotFoundError("Creator node is absent from the approved workflow")
        return self._admit_creator_node(
            duet_id=frozen_workflow.duet_id,
            source_design_artifact_id=frozen_workflow.artifact_id,
            source_design_hash=frozen_workflow.workflow_hash,
            workflow_approval_id=workflow_approval_id,
            node_local_id=node_local_id,
            contract=node.contract,
            source_revision=frozen_workflow.revision,
        )

    def admit_nested_creator(
        self,
        *,
        parent_creator_episode_id: OpaqueId,
        workflow_design_artifact_id: OpaqueId,
        node_local_id: str,
    ) -> OpaqueId:
        """Admit one Creator node through its parent's frozen design authority."""

        parent = self.store.get_creator(parent_creator_episode_id.value)
        if parent is None:
            raise DuetNotFoundError("parent Creator Episode does not exist")
        artifact = self.store.get_artifact(workflow_design_artifact_id.value)
        if (
            artifact is None
            or artifact["kind"] != "workflow_design"
            or artifact["creator_episode_id"] != parent_creator_episode_id.value
            or artifact["duet_id"] != parent["duet_id"]
        ):
            raise DuetProtocolError(
                "nested Creator must come from the parent's frozen workflow design"
            )
        latest = self.store.latest_artifact(
            duet_id=parent["duet_id"],
            kind="workflow_design",
            creator_episode_id=parent_creator_episode_id.value,
        )
        if latest is None or latest["artifact_id"] != artifact["artifact_id"]:
            raise StaleDuetApprovalError(
                "nested Creator design was superseded before execution"
            )
        workflow = EpisodeWorkflowSpec.from_record(artifact["record"]["workflow"])
        deficits = self.workflow_deficits(
            creator_episode_id=parent_creator_episode_id,
            workflow=workflow,
        )
        if deficits:
            raise WorkflowAdmissionError(deficits)
        node = next(
            (item for item in workflow.episodes if item.local_id == node_local_id),
            None,
        )
        if node is None:
            raise DuetNotFoundError("nested Creator node is absent from the design")
        return self._admit_creator_node(
            duet_id=OpaqueId(parent["duet_id"]),
            source_design_artifact_id=workflow_design_artifact_id,
            source_design_hash=Sha256Digest(artifact["content_hash"]),
            workflow_approval_id=OpaqueId(parent["approval_id"]),
            node_local_id=node_local_id,
            contract=node.contract,
            source_revision=int(artifact["revision"]),
            parent_creator_episode_id=parent_creator_episode_id,
        )

    def register_evidence(
        self,
        *,
        duet_id: OpaqueId,
        creator_episode_id: OpaqueId,
        evidence_kind_id: str,
        acceptance_source_id: str,
        observation: Mapping[str, Any],
        source_artifact_id: Optional[OpaqueId] = None,
    ) -> OpaqueId:
        evidence_id = content_id(
            "evidence",
            {
                "duet_id": duet_id.value,
                "creator_episode_id": creator_episode_id.value,
                "evidence_kind_id": evidence_kind_id,
                "acceptance_source_id": acceptance_source_id,
                "observation": observation,
                "source_artifact_id": (
                    None if source_artifact_id is None else source_artifact_id.value
                ),
            },
        )
        self.store.register_evidence(
            evidence_id=evidence_id.value,
            duet_id=duet_id.value,
            creator_episode_id=creator_episode_id.value,
            evidence_kind_id=evidence_kind_id,
            acceptance_source_id=acceptance_source_id,
            observation=observation,
            source_artifact_id=(
                None if source_artifact_id is None else source_artifact_id.value
            ),
        )
        return evidence_id

    def _creator_frozen_contract(
        self, creator_episode_id: OpaqueId
    ) -> AdmittedCreatorContract:
        creator = self.store.get_creator(creator_episode_id.value)
        if creator is None:
            raise DuetNotFoundError("unknown Creator Episode")
        artifact = self.store.get_artifact(creator["contract_artifact_id"])
        if artifact is None:
            raise DuetNotFoundError("Creator contract artifact is missing")
        return _admitted_creator_from_artifact(artifact["record"])

    def creator_contract(
        self, creator_episode_id: OpaqueId
    ) -> AdmittedCreatorContract:
        """Return the exact admitted contract for a Creator runtime."""

        return self._creator_frozen_contract(creator_episode_id)

    def publish_creator_progress(
        self,
        envelope: CreatorProgressEnvelope,
    ) -> OpaqueId:
        """Persist one prose-free Creator status projection atomically."""

        if not isinstance(envelope, CreatorProgressEnvelope):
            raise TypeError("Creator progress must be a CreatorProgressEnvelope")
        creator = self.store.get_creator(envelope.creator_episode_id.value)
        if creator is None:
            raise DuetNotFoundError("unknown Creator Episode")
        artifact_id = content_id(
            "progress",
            {
                "duet_id": creator["duet_id"],
                "envelope": envelope.as_record(),
            },
        )
        content_hash = Sha256Digest.of_record(envelope.as_record())
        self.store.put_creator_progress(
            artifact_id=artifact_id.value,
            duet_id=creator["duet_id"],
            creator_episode_id=envelope.creator_episode_id.value,
            sequence=envelope.sequence,
            state=envelope.state.value,
            content_hash=content_hash.value,
            record=envelope.as_record(),
            provenance=DuetProvenance.HOST_VALIDATION.value,
        )
        return artifact_id

    def publish_creator_activity(
        self,
        envelope: CreatorActivityEnvelope,
    ) -> OpaqueId:
        """Append one host-observed Creator activity event."""

        if not isinstance(envelope, CreatorActivityEnvelope):
            raise TypeError("Creator activity must be a CreatorActivityEnvelope")
        creator = self.store.get_creator(envelope.creator_episode_id.value)
        if creator is None:
            raise DuetNotFoundError("unknown Creator Episode")
        record = envelope.as_record()
        artifact_id = content_id(
            "activity",
            {
                "duet_id": creator["duet_id"],
                "envelope": record,
            },
        )
        latest = self.store.latest_artifact(
            duet_id=creator["duet_id"],
            kind="creator_activity",
            creator_episode_id=envelope.creator_episode_id.value,
        )
        if latest is not None:
            if latest["artifact_id"] == artifact_id.value:
                return artifact_id
            latest_record = latest["record"]
            if envelope.attempt < int(latest_record["attempt"]):
                raise DuetConflictError("Creator activity attempt moved backwards")
            if envelope.event_index <= int(latest_record["event_index"]):
                raise DuetConflictError(
                    "Creator activity event index did not increase"
                )
        self.store.put_artifact(
            artifact_id=artifact_id.value,
            duet_id=creator["duet_id"],
            creator_episode_id=envelope.creator_episode_id.value,
            kind="creator_activity",
            revision=envelope.event_index,
            content_hash=Sha256Digest.of_record(record).value,
            record=record,
        )
        self.store.append_event(
            duet_id=creator["duet_id"],
            event_type="creator_activity",
            provenance=DuetProvenance.HOST_VALIDATION.value,
            record=record,
        )
        return artifact_id

    @staticmethod
    def _workflow_depths(workflow: EpisodeWorkflowSpec) -> dict[str, int]:
        by_id = {item.local_id: item for item in workflow.episodes}
        depths: dict[str, int] = {}
        for local_id in by_id:
            depth = 0
            cursor = local_id
            while by_id[cursor].workflow_parent_local_id is not None:
                depth += 1
                cursor = by_id[cursor].workflow_parent_local_id
            depths[local_id] = depth
        return depths

    def _creator_authority_depth(self, creator_episode_id: OpaqueId) -> int:
        """Count the root Creator and each explicitly admitted Creator ancestor."""

        depth = 0
        cursor: Optional[str] = creator_episode_id.value
        seen: set[str] = set()
        while cursor is not None:
            if cursor in seen:
                raise DuetProtocolError("Creator authority lineage contains a cycle")
            seen.add(cursor)
            row = self.store.get_creator(cursor)
            if row is None:
                raise DuetNotFoundError("Creator authority lineage is incomplete")
            depth += 1
            cursor = row.get("parent_creator_episode_id")
        return depth

    def workflow_deficits(
        self,
        *,
        creator_episode_id: OpaqueId,
        workflow: EpisodeWorkflowSpec,
    ) -> tuple[ContractDeficit, ...]:
        frozen = self._creator_frozen_contract(creator_episode_id)
        creator = frozen.contract.creator_contract
        if creator is None:
            raise DuetProtocolError("Creator Episode lacks its Creator contract")
        return self._workflow_deficits_for_authority(
            duet_id=frozen.duet_id,
            workflow=workflow,
            authority_depth=self._creator_authority_depth(creator_episode_id),
            consumer_creator_episode_id=creator_episode_id,
            assignable_capability_names=creator.assignable_capability_names,
            may_assign_creator_capability=creator.may_assign_creator_capability,
            maximum_creator_depth=self.policy(
                frozen.duet_id
            ).maximum_creator_depth,
            maximum_workflow_depth=(
                None
                if frozen.contract.safety_bounds is None
                else frozen.contract.safety_bounds.max_depth
            ),
        )

    def workflow_admission_authority(
        self,
        duet_id: OpaqueId,
    ) -> WorkflowAdmissionAuthority:
        """Return the host-owned, model-free admission ceiling."""

        self._duet_row(duet_id)
        return WorkflowAdmissionAuthority(
            duet_id=duet_id,
            assignable_capability_names=tuple(
                sorted(self.allowed_episode_capabilities)
            ),
            maximum_creator_depth=self.policy(duet_id).maximum_creator_depth,
        )

    def _workflow_deficits_for_authority(
        self,
        *,
        duet_id: OpaqueId,
        workflow: EpisodeWorkflowSpec,
        authority_depth: int,
        consumer_creator_episode_id: Optional[OpaqueId],
        assignable_capability_names: tuple[str, ...],
        may_assign_creator_capability: bool,
        maximum_creator_depth: int,
        maximum_workflow_depth: Optional[int],
    ) -> tuple[ContractDeficit, ...]:
        """Validate one work graph under an exact authority-tree parent."""

        deficits: list[ContractDeficit] = []
        roots = [
            item for item in workflow.episodes
            if item.workflow_parent_local_id is None
        ]
        if len(roots) != 1:
            deficits.append(ContractDeficit("single_root_required", "goal"))
        allowed = set(assignable_capability_names)
        by_local_id = {item.local_id: item for item in workflow.episodes}
        for item in workflow.episodes:
            if not set(item.contract.execution_capability_names).issubset(allowed):
                deficits.append(
                    ContractDeficit(
                        "capability_escalation",
                        "execution_capability_names",
                    )
                )
            if item.contract.can_create_episodes:
                if not may_assign_creator_capability:
                    deficits.append(
                        ContractDeficit(
                            "recursive_creator_not_authorized",
                            "creator_contract",
                        )
                    )
                elif item.contract.creator_contract is None:
                    deficits.append(
                        ContractDeficit(
                            "recursive_creator_contract_required",
                            "creator_contract",
                        )
                    )
                elif not set(
                    item.contract.creator_contract.assignable_capability_names
                ).issubset(allowed):
                    deficits.append(
                        ContractDeficit(
                            "recursive_creator_capability_escalation",
                            "creator_contract",
                        )
                    )
                else:
                    try:
                        self.resolve_creator_context(
                            duet_id,
                            item.contract.creator_contract.design_context,
                            consumer_creator_episode_id=consumer_creator_episode_id,
                        )
                    except CreatorContextValidationError as exc:
                        deficits.append(
                            ContractDeficit(
                                exc.code,
                                "creator_contract.design_context",
                                detail=str(exc),
                            )
                        )
            parent_id = item.workflow_parent_local_id
            if (
                parent_id is not None
                and by_local_id[parent_id].contract.can_create_episodes
            ):
                deficits.append(
                    ContractDeficit(
                        "creator_node_must_be_leaf",
                        "creator_contract",
                    )
                )
        depths = self._workflow_depths(workflow)
        creator_depth = authority_depth + (
            1 if any(item.contract.can_create_episodes for item in workflow.episodes) else 0
        )
        if creator_depth > maximum_creator_depth:
            deficits.append(
                ContractDeficit("creator_depth_exceeded", "creator_contract")
            )
        if (
            maximum_workflow_depth is not None
            and depths
            and max(depths.values()) + 1 > maximum_workflow_depth
        ):
            deficits.append(ContractDeficit("workflow_depth_exceeded", "safety_bounds"))
        unique = {
            (item.code, item.field_path, item.blocking): item for item in deficits
        }
        return tuple(unique[key] for key in sorted(unique))

    def validate_duet_workflow(
        self,
        duet_id: OpaqueId,
        workflow_blueprint: Mapping[str, Any],
    ) -> tuple[Optional[EpisodeWorkflowSpec], tuple[ContractDeficit, ...]]:
        """Run deterministic validation for a Duet-authored workflow draft."""

        if not isinstance(workflow_blueprint, Mapping):
            return None, (
                ContractDeficit(
                    "invalid_workflow",
                    "goal",
                    detail="Episode workflow must be a JSON object",
                ),
            )
        try:
            workflow = workflow_spec_from_blueprint(
                workflow_blueprint,
                identity_namespace=f"{duet_id.value}:duet-workflow",
            )
        except (EpisodeContractError, TypeError, ValueError) as exc:
            return None, (
                ContractDeficit(
                    "invalid_workflow",
                    "goal",
                    detail=str(exc),
                ),
            )
        authority = self.workflow_admission_authority(duet_id)
        return workflow, self._workflow_deficits_for_authority(
            duet_id=duet_id,
            workflow=workflow,
            authority_depth=0,
            consumer_creator_episode_id=None,
            assignable_capability_names=authority.assignable_capability_names,
            may_assign_creator_capability=True,
            maximum_creator_depth=authority.maximum_creator_depth,
            maximum_workflow_depth=None,
        )

    def _validate_registered_evidence(
        self,
        *,
        creator_episode_id: OpaqueId,
        measured_outcomes: tuple[EpisodeMeasuredOutcome, ...],
    ) -> None:
        frozen = self._creator_frozen_contract(creator_episode_id)
        requirements = {
            item.requirement_id: item
            for item in frozen.contract.creator_contract.evidence_requirements
        }
        for outcome in measured_outcomes:
            for measurement in outcome.evidence:
                requirement = requirements.get(measurement.requirement_id)
                if requirement is None:
                    raise WorkflowAdmissionError(
                        (ContractDeficit("undeclared_evidence", "creator_contract"),)
                    )
                for evidence_id in measurement.accepted_evidence_ids:
                    stored = self.store.get_evidence(evidence_id.value)
                    if (
                        stored is None
                        or stored["creator_episode_id"] != creator_episode_id.value
                        or stored["evidence_kind_id"] != requirement.evidence_kind_id
                        or stored["acceptance_source_id"]
                        != requirement.acceptance_source_id
                    ):
                        raise WorkflowAdmissionError(
                            (
                                ContractDeficit(
                                    "unregistered_evidence",
                                    "creator_contract",
                                ),
                            )
                        )

    def read_episode_workflow_draft(
        self,
        duet_id: OpaqueId,
        artifact_id: OpaqueId,
    ) -> dict[str, Any]:
        """Return one exact workflow body after proving Duet ownership."""

        artifact = self.store.get_artifact(artifact_id.value)
        if (
            artifact is None
            or artifact["duet_id"] != duet_id.value
            or artifact["kind"] != EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND
        ):
            raise DuetNotFoundError("Episode workflow draft not found for this Duet")
        blueprint = artifact["record"].get("workflow_blueprint")
        if not isinstance(blueprint, Mapping):
            raise DuetProtocolError("Episode workflow draft body is malformed")
        if Sha256Digest.of_record(blueprint).value != artifact["content_hash"]:
            raise DuetProtocolError("Episode workflow draft hash verification failed")
        return {
            "artifact_id": artifact["artifact_id"],
            "revision": artifact["revision"],
            "content_hash": artifact["content_hash"],
            "source_stage": artifact["record"]["source_stage"],
            "workflow_hash": artifact["record"].get("workflow_hash"),
            "workflow": json.loads(canonical_json(blueprint)),
        }

    def record_duet_workflow_draft(
        self,
        *,
        duet_id: OpaqueId,
        workflow_blueprint: Mapping[str, Any],
        expected_workflow_hash: Optional[str],
        source_stage: str,
    ) -> dict[str, Any]:
        """Append a Duet-owned workflow revision without running any model.

        Persistence precedes semantic readiness so a human can repair a
        structurally valid but authority-incomplete design. The returned
        deficits come exclusively from deterministic host validators.
        """

        self._duet_row(duet_id)
        if source_stage not in {"duet", "human_edit"}:
            raise ValueError("Duet workflow source must be duet or human_edit")
        if not isinstance(workflow_blueprint, Mapping):
            raise ValueError("Episode workflow draft must be an object")
        blueprint = json.loads(canonical_json(workflow_blueprint))
        blueprint_hash = Sha256Digest.of_record(blueprint)
        with self._workflow_draft_lock:
            prior = self.store.latest_artifact(
                duet_id=duet_id.value,
                kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
                unowned_only=True,
            )
            actual_hash = None if prior is None else prior["content_hash"]
            if expected_workflow_hash != actual_hash:
                raise DuetConflictError(
                    "Episode workflow changed while it was being edited"
                )
            if prior is not None and prior["content_hash"] == blueprint_hash.value:
                return prior
            workflow, deficits = self.validate_duet_workflow(
                duet_id,
                blueprint,
            )
            revision = 1 if prior is None else int(prior["revision"]) + 1
            record = {
                "schema_version": _EPISODE_WORKFLOW_DRAFT_SCHEMA_VERSION,
                "duet_id": duet_id.value,
                "creator_episode_id": None,
                "revision": revision,
                "source_stage": source_stage,
                "workflow_blueprint_hash": blueprint_hash.value,
                "workflow_blueprint": blueprint,
                "workflow_hash": (
                    None if workflow is None else workflow.workflow_hash.value
                ),
                "validation_deficits": [item.as_record() for item in deficits],
                "ready": not deficits,
            }
            artifact_id = content_id("episode_workflow_draft", record)
            self.store.put_artifact(
                artifact_id=artifact_id.value,
                duet_id=duet_id.value,
                kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
                revision=revision,
                content_hash=blueprint_hash.value,
                record=record,
            )
            self.store.set_state(
                duet_id.value,
                (
                    DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value
                    if not deficits
                    else DuetDesignState.DESIGNING.value
                ),
            )
            self.store.append_event(
                duet_id=duet_id.value,
                event_type="episode_workflow_revision",
                provenance=(
                    DuetProvenance.HUMAN_INPUT.value
                    if source_stage == "human_edit"
                    else DuetProvenance.LLM_PROPOSAL.value
                ),
                record={
                    "artifact_id": artifact_id.value,
                    "revision": revision,
                    "content_hash": blueprint_hash.value,
                    "deficit_codes": [item.code for item in deficits],
                },
            )
        artifact = self.store.get_artifact(artifact_id.value)
        if artifact is None:
            raise DuetProtocolError("Episode workflow draft was not durably stored")
        return artifact

    def freeze_duet_workflow(
        self,
        *,
        duet_id: OpaqueId,
        source_draft_artifact_id: OpaqueId,
        source_draft_hash: Sha256Digest,
    ) -> FrozenDuetWorkflow:
        """Freeze the exact Duet-owned workflow under host admission authority."""

        source = self.store.get_artifact(source_draft_artifact_id.value)
        latest = self.store.latest_artifact(
            duet_id=duet_id.value,
            kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
            unowned_only=True,
        )
        if (
            source is None
            or source["duet_id"] != duet_id.value
            or source["kind"] != EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND
            or source["creator_episode_id"] is not None
            or source["content_hash"] != source_draft_hash.value
            or latest is None
            or latest["artifact_id"] != source["artifact_id"]
        ):
            raise StaleDuetApprovalError(
                "Episode workflow draft changed before it could be frozen"
            )
        blueprint = source["record"].get("workflow_blueprint")
        workflow, deficits = self.validate_duet_workflow(duet_id, blueprint)
        if workflow is None or deficits:
            raise WorkflowAdmissionError(deficits)
        authority = self.workflow_admission_authority(duet_id)
        self.store.put_artifact(
            artifact_id=authority.authority_id.value,
            duet_id=duet_id.value,
            kind="workflow_admission_authority",
            revision=0,
            content_hash=authority.content_hash.value,
            record=authority.as_record(),
        )
        identity_record = {
            "duet_id": duet_id.value,
            "source_draft_artifact_id": source_draft_artifact_id.value,
            "source_draft_hash": source_draft_hash.value,
            "revision": int(source["revision"]),
            "workflow_hash": workflow.workflow_hash.value,
            "admission_authority_id": authority.authority_id.value,
            "admission_authority_hash": authority.content_hash.value,
        }
        artifact_id = content_id("workflow", identity_record)
        frozen = FrozenDuetWorkflow(
            artifact_id=artifact_id,
            duet_id=duet_id,
            revision=int(source["revision"]),
            workflow_hash=workflow.workflow_hash,
            workflow=workflow,
            admission_authority_id=authority.authority_id,
            admission_authority_hash=authority.content_hash,
            source_draft_artifact_id=source_draft_artifact_id,
            source_draft_hash=source_draft_hash,
        )
        self.store.put_artifact(
            artifact_id=artifact_id.value,
            duet_id=duet_id.value,
            kind="duet_workflow",
            revision=frozen.revision,
            content_hash=frozen.workflow_hash.value,
            record=frozen.as_record(),
        )
        return frozen

    def record_episode_workflow_draft(
        self,
        *,
        creator_episode_id: OpaqueId,
        workflow_blueprint: Mapping[str, Any],
        source_stage: str,
        consumed_context_artifact_ids: tuple[str, ...] = (),
        workflow_hash: Optional[Sha256Digest] = None,
        workflow_design_artifact_id: Optional[OpaqueId] = None,
    ) -> dict[str, Any]:
        """Append the exact user-facing Episode workflow before validation.

        The Episode workflow is the durable design object.  Review, admission,
        and execution records may refer to it, but none of those internal
        records is allowed to be its only surviving representation.
        """

        frozen_creator = self._creator_frozen_contract(creator_episode_id)
        if source_stage not in _EPISODE_WORKFLOW_DRAFT_SOURCE_STAGES:
            raise ValueError(f"unknown Episode workflow draft source: {source_stage}")
        if not isinstance(workflow_blueprint, Mapping):
            raise ValueError("Episode workflow draft must be an object")
        if (
            not isinstance(consumed_context_artifact_ids, tuple)
            or any(
                not isinstance(item, str) or not item
                for item in consumed_context_artifact_ids
            )
            or len(set(consumed_context_artifact_ids))
            != len(consumed_context_artifact_ids)
        ):
            raise ValueError(
                "consumed_context_artifact_ids must be unique non-empty string IDs"
            )
        blueprint = json.loads(canonical_json(workflow_blueprint))
        blueprint_hash = Sha256Digest.of_record(blueprint)
        normalized_hash = None if workflow_hash is None else workflow_hash.value
        design_artifact_id = (
            None
            if workflow_design_artifact_id is None
            else workflow_design_artifact_id.value
        )
        with self._workflow_draft_lock:
            prior = self.store.latest_artifact(
                duet_id=frozen_creator.duet_id.value,
                kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
                creator_episode_id=creator_episode_id.value,
            )
            if prior is not None and all(
                (
                    prior["record"].get("source_stage") == source_stage,
                    prior["record"].get("workflow_blueprint_hash")
                    == blueprint_hash.value,
                    prior["record"].get("consumed_context_artifact_ids")
                    == list(consumed_context_artifact_ids),
                    prior["record"].get("workflow_hash") == normalized_hash,
                    prior["record"].get("workflow_design_artifact_id")
                    == design_artifact_id,
                )
            ):
                return prior
            revision = 1 if prior is None else int(prior["revision"]) + 1
            record = {
                "schema_version": _EPISODE_WORKFLOW_DRAFT_SCHEMA_VERSION,
                "duet_id": frozen_creator.duet_id.value,
                "creator_episode_id": creator_episode_id.value,
                "revision": revision,
                "source_stage": source_stage,
                "workflow_blueprint_hash": blueprint_hash.value,
                "workflow_blueprint": blueprint,
                "consumed_context_artifact_ids": list(
                    consumed_context_artifact_ids
                ),
                "workflow_hash": normalized_hash,
                "workflow_design_artifact_id": design_artifact_id,
            }
            artifact_id = content_id("episode_workflow_draft", record)
            self.store.put_artifact(
                artifact_id=artifact_id.value,
                duet_id=frozen_creator.duet_id.value,
                creator_episode_id=creator_episode_id.value,
                kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
                revision=revision,
                content_hash=blueprint_hash.value,
                record=record,
            )
        artifact = self.store.get_artifact(artifact_id.value)
        if artifact is None:
            raise DuetProtocolError("Episode workflow draft was not durably stored")
        return artifact

    def freeze_workflow_design(
        self,
        *,
        creator_episode_id: OpaqueId,
        workflow_blueprint: Mapping[str, Any],
        consumed_context_artifact_ids: tuple[str, ...] = (),
        source_stage: str = "candidate",
        identity_namespace: Optional[str] = None,
    ) -> FrozenWorkflowDesign:
        """Translate, admit, and freeze one design before its Run Episode."""

        frozen_creator = self._creator_frozen_contract(creator_episode_id)
        self.record_episode_workflow_draft(
            creator_episode_id=creator_episode_id,
            workflow_blueprint=workflow_blueprint,
            source_stage=source_stage,
            consumed_context_artifact_ids=consumed_context_artifact_ids,
        )
        if (
            not isinstance(consumed_context_artifact_ids, tuple)
            or any(
                not isinstance(item, str) for item in consumed_context_artifact_ids
            )
            or len(set(consumed_context_artifact_ids))
            != len(consumed_context_artifact_ids)
        ):
            raise ValueError(
                "consumed_context_artifact_ids must be unique string IDs"
            )
        creator_contract = frozen_creator.contract.creator_contract
        if creator_contract is None:
            raise DuetProtocolError("Creator Episode lacks its Creator contract")
        references = creator_contract.design_context.artifact_references
        by_artifact_id = {
            item.artifact_id.value: item for item in references
        }
        consumed = set(consumed_context_artifact_ids)
        unknown_consumed = consumed - set(by_artifact_id)
        if unknown_consumed:
            raise WorkflowAdmissionError(
                (
                    ContractDeficit(
                        "undeclared_context_receipt",
                        "creator_contract.design_context",
                    ),
                )
            )
        required = {
            item.artifact_id.value for item in references if item.required
        }
        if not required.issubset(consumed):
            raise WorkflowAdmissionError(
                (
                    ContractDeficit(
                        "required_context_unread",
                        "creator_contract.design_context",
                    ),
                )
            )
        context_receipts = tuple(
            item for item in references if item.artifact_id.value in consumed
        )
        prior = self.store.latest_artifact(
            duet_id=frozen_creator.duet_id.value,
            kind="workflow_design",
            creator_episode_id=creator_episode_id.value,
        )
        revision = 1 if prior is None else int(prior["revision"]) + 1
        workflow = workflow_spec_from_blueprint(
            workflow_blueprint,
            identity_namespace=(
                f"{creator_episode_id.value}:candidate:{revision}"
                if identity_namespace is None
                else identity_namespace
            ),
        )
        deficits = self.workflow_deficits(
            creator_episode_id=creator_episode_id,
            workflow=workflow,
        )
        if deficits:
            raise WorkflowAdmissionError(deficits)
        artifact_id = content_id(
            "design",
            {
                "duet_id": frozen_creator.duet_id.value,
                "creator_episode_id": creator_episode_id.value,
                "revision": revision,
                "workflow": workflow.as_record(),
                "context_receipts": [
                    item.as_record() for item in context_receipts
                ],
            },
        )
        design = FrozenWorkflowDesign(
            artifact_id=artifact_id,
            duet_id=frozen_creator.duet_id,
            creator_episode_id=creator_episode_id,
            revision=revision,
            workflow_hash=workflow.workflow_hash,
            workflow=workflow,
            context_receipts=context_receipts,
        )
        self.store.put_artifact(
            artifact_id=design.artifact_id.value,
            duet_id=design.duet_id.value,
            creator_episode_id=creator_episode_id.value,
            kind="workflow_design",
            revision=design.revision,
            content_hash=design.workflow_hash.value,
            record=design.as_record(),
        )
        self.record_episode_workflow_draft(
            creator_episode_id=creator_episode_id,
            workflow_blueprint=workflow_blueprint,
            source_stage="frozen",
            consumed_context_artifact_ids=consumed_context_artifact_ids,
            workflow_hash=design.workflow_hash,
            workflow_design_artifact_id=design.artifact_id,
        )
        return design

    def submit_workflow_candidate(
        self,
        *,
        creator_episode_id: OpaqueId,
        revision: int,
        workflow: EpisodeWorkflowSpec,
        measured_outcomes: tuple[EpisodeMeasuredOutcome, ...],
    ) -> WorkflowCandidate:
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("workflow candidate revision must be a positive integer")
        frozen = self._creator_frozen_contract(creator_episode_id)
        prior = self.store.latest_artifact(
            duet_id=frozen.duet_id.value,
            kind=ApprovalKind.WORKFLOW.value,
            creator_episode_id=creator_episode_id.value,
        )
        if prior is not None and revision <= prior["revision"]:
            raise DuetConflictError(
                "workflow candidate revisions must increase monotonically"
            )
        deficits = self.workflow_deficits(
            creator_episode_id=creator_episode_id,
            workflow=workflow,
        )
        if deficits:
            raise WorkflowAdmissionError(deficits)
        self._validate_registered_evidence(
            creator_episode_id=creator_episode_id,
            measured_outcomes=measured_outcomes,
        )
        result = EpisodeWorkflowDesignResult.host_computed(
            workflow=workflow,
            creator_contract=frozen.contract.creator_contract,
            measured_outcomes=measured_outcomes,
        )
        artifact_id = content_id(
            "workflow",
            {
                "duet_id": frozen.duet_id.value,
                "creator_episode_id": creator_episode_id.value,
                "revision": revision,
                "result": result.as_record(),
            },
        )
        projection = EpisodeWorkflowDesignProjection.from_result(
            artifact_id=artifact_id,
            result=result,
            return_contract=frozen.contract.creator_contract.return_contract,
        )
        candidate = WorkflowCandidate(
            artifact_id=artifact_id,
            duet_id=frozen.duet_id,
            creator_episode_id=creator_episode_id,
            revision=revision,
            workflow_hash=workflow.workflow_hash,
            workflow=workflow,
            projection=projection,
        )
        self.store.put_artifact(
            artifact_id=artifact_id.value,
            duet_id=frozen.duet_id.value,
            creator_episode_id=creator_episode_id.value,
            kind=ApprovalKind.WORKFLOW.value,
            revision=revision,
            content_hash=workflow.workflow_hash.value,
            record=candidate.as_record(),
        )
        return candidate

    def _candidate_from_artifact(record: Mapping[str, Any]) -> WorkflowCandidate:
        return WorkflowCandidate(
            artifact_id=OpaqueId(record["artifact_id"]),
            duet_id=OpaqueId(record["duet_id"]),
            creator_episode_id=OpaqueId(record["creator_episode_id"]),
            revision=record["revision"],
            workflow_hash=Sha256Digest(record["workflow_hash"]),
            workflow=EpisodeWorkflowSpec.from_record(record["workflow"]),
            projection=EpisodeWorkflowDesignProjection.from_record(
                record["projection"]
            ),
        )

    def latest_workflow_candidate(
        self,
        creator_episode_id: OpaqueId,
    ) -> WorkflowCandidate:
        """Reload the newest immutable candidate for a Creator Episode."""

        frozen = self._creator_frozen_contract(creator_episode_id)
        artifact = self.store.latest_artifact(
            duet_id=frozen.duet_id.value,
            kind=ApprovalKind.WORKFLOW.value,
            creator_episode_id=creator_episode_id.value,
        )
        if artifact is None:
            raise DuetNotFoundError("Creator Episode has no measured workflow candidate")
        return self._candidate_from_artifact(artifact["record"])

    def _launched_episode_records(
        self,
        *,
        workflow: EpisodeWorkflowSpec,
        run_id: str,
        design_artifact_id: OpaqueId,
    ) -> tuple[dict[str, Any], ...]:
        """Materialize stable Episode identities for one admitted workflow."""

        by_id = {item.local_id: item for item in workflow.episodes}
        depths = self._workflow_depths(workflow)
        episode_ids: dict[str, OpaqueId] = {}
        ordered = sorted(
            workflow.episodes,
            key=lambda item: (depths[item.local_id], item.local_id),
        )
        run_key = f"approved-{design_artifact_id.value[-12:]}"
        for item in ordered:
            ancestry = []
            cursor: Optional[str] = item.local_id
            while cursor is not None:
                ancestry.append(cursor)
                cursor = by_id[cursor].workflow_parent_local_id
            path = (("run_episode", run_key),) + tuple(
                (
                    "creator_episode"
                    if by_id[local_id].contract.can_create_episodes
                    else "task_episode",
                    f"{design_artifact_id.value}:{local_id}",
                )
                for local_id in reversed(ancestry)
            )
            episode_ids[item.local_id] = OpaqueId(
                EpisodeRef(run_id=run_id, path=path).episode_id
            )
        return tuple(
            {
                "episode_id": episode_ids[item.local_id].value,
                "design_artifact_id": design_artifact_id.value,
                "workflow_parent_episode_id": (
                    None
                    if item.workflow_parent_local_id is None
                    else episode_ids[item.workflow_parent_local_id].value
                ),
                "local_id": item.local_id,
                "runtime_key": f"{design_artifact_id.value}:{item.local_id}",
                "depth": depths[item.local_id],
                "contract_hash": item.contract.spec_hash.value,
                "contract": item.contract.as_record(),
            }
            for item in ordered
        )

    def launch_duet_workflow(
        self,
        *,
        frozen: FrozenDuetWorkflow,
        workflow_approval_id: OpaqueId,
        run_id: str,
    ) -> OpaqueId:
        """Launch one approved Duet workflow without minting a fake Creator."""

        artifact = self.store.get_artifact(frozen.artifact_id.value)
        if (
            artifact is None
            or artifact["kind"] != "duet_workflow"
            or artifact["creator_episode_id"] is not None
            or artifact["record"] != frozen.as_record()
        ):
            raise DuetNotFoundError("frozen Duet workflow artifact not found")
        latest_draft = self.store.latest_artifact(
            duet_id=frozen.duet_id.value,
            kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
            unowned_only=True,
        )
        if (
            latest_draft is None
            or latest_draft["artifact_id"]
            != frozen.source_draft_artifact_id.value
            or latest_draft["content_hash"] != frozen.source_draft_hash.value
        ):
            raise StaleDuetApprovalError(
                "workflow approval was invalidated by a later Duet revision"
            )
        current_authority = self.workflow_admission_authority(frozen.duet_id)
        if (
            current_authority.authority_id != frozen.admission_authority_id
            or current_authority.content_hash != frozen.admission_authority_hash
        ):
            raise StaleDuetApprovalError(
                "host admission authority changed after workflow validation"
            )
        workflow, deficits = self.validate_duet_workflow(
            frozen.duet_id,
            latest_draft["record"]["workflow_blueprint"],
        )
        if workflow is None or deficits or workflow != frozen.workflow:
            raise WorkflowAdmissionError(deficits or (
                ContractDeficit("workflow_changed", "goal"),
            ))
        approval = self._require_exact_approval(
            approval_id=workflow_approval_id,
            kind=ApprovalKind.WORKFLOW,
            artifact_id=frozen.artifact_id,
            content_hash=frozen.workflow_hash,
            revision=frozen.revision,
        )
        attempt = self.store.launch_count(
            duet_id=frozen.duet_id.value,
            workflow_artifact_id=frozen.artifact_id.value,
        ) + 1
        launch_id = content_id(
            "launch",
            {
                "workflow_artifact_id": frozen.artifact_id.value,
                "workflow_hash": frozen.workflow_hash.value,
                "approval_id": approval.approval_id.value,
                "run_id": run_id,
                "attempt": attempt,
            },
        )
        self.store.launch_workflow(
            launch_record={
                "launch_id": launch_id.value,
                "duet_id": frozen.duet_id.value,
                "workflow_artifact_id": frozen.artifact_id.value,
                "workflow_hash": frozen.workflow_hash.value,
                "approval_id": workflow_approval_id.value,
                "run_id": run_id,
                "attempt": attempt,
            },
            episode_records=self._launched_episode_records(
                workflow=frozen.workflow,
                run_id=run_id,
                design_artifact_id=frozen.artifact_id,
            ),
        )
        return launch_id

    def queue_decision(self, decision: DuetDecision) -> bool:
        if self.store.get_creator(decision.creator_episode_id.value) is None:
            raise DuetNotFoundError("unknown Creator Episode")
        return self.store.queue_message(decision.as_record())

    def record_creator_guidance(
        self,
        identity: DuetIdentity,
        *,
        creator_episode_id: OpaqueId,
        expected_unit_index: int,
        instruction: str,
    ) -> CreatorGuidance:
        """Trusted human operation for downward Creator steering."""

        creator = self.store.get_creator(creator_episode_id.value)
        if creator is None or creator["duet_id"] != identity.duet_id.value:
            raise DuetProtocolError("Creator Episode does not belong to this Duet")
        guidance_id = content_id(
            "guidance",
            {
                "duet_id": identity.duet_id.value,
                "creator_episode_id": creator_episode_id.value,
                "expected_unit_index": expected_unit_index,
                "instruction": instruction,
                "human_authority_id": identity.human_authority_id.value,
            },
        )
        guidance = CreatorGuidance(
            guidance_id=guidance_id,
            duet_id=identity.duet_id,
            creator_episode_id=creator_episode_id,
            expected_unit_index=expected_unit_index,
            instruction=instruction,
            human_authority_id=identity.human_authority_id,
        )
        self.store.put_artifact(
            artifact_id=guidance.guidance_id.value,
            duet_id=identity.duet_id.value,
            creator_episode_id=creator_episode_id.value,
            kind="creator_guidance",
            revision=expected_unit_index,
            content_hash=Sha256Digest.of_record(guidance.as_record()).value,
            record=guidance.as_record(),
        )
        return guidance

    def record_human_decision(
        self,
        identity: DuetIdentity,
        *,
        creator_episode_id: OpaqueId,
        kind: DuetMessageKind,
        expected_unit_index: int,
        code: str,
        field_ids: tuple[str, ...] = (),
        guidance_artifact_ids: tuple[OpaqueId, ...] = (),
    ) -> DuetDecision:
        """Trusted human operation; persist before a model may submit the ID."""

        creator = self.store.get_creator(creator_episode_id.value)
        if creator is None or creator["duet_id"] != identity.duet_id.value:
            raise DuetProtocolError("Creator Episode does not belong to this Duet")
        for artifact_id in guidance_artifact_ids:
            artifact = self.store.get_artifact(artifact_id.value)
            if (
                artifact is None
                or artifact["kind"] != "creator_guidance"
                or artifact["duet_id"] != identity.duet_id.value
                or artifact["creator_episode_id"] != creator_episode_id.value
                or artifact["revision"] != expected_unit_index
            ):
                raise DuetProtocolError(
                    "Creator guidance does not belong to this decision boundary"
                )
        message_id = content_id(
            "decision",
            {
                "duet_id": identity.duet_id.value,
                "creator_episode_id": creator_episode_id.value,
                "kind": kind.value,
                "expected_unit_index": expected_unit_index,
                "code": code,
                "field_ids": list(field_ids),
                "guidance_artifact_ids": [
                    item.value for item in guidance_artifact_ids
                ],
                "human_authority_id": identity.human_authority_id.value,
            },
        )
        decision = DuetDecision(
            message_id=message_id,
            duet_id=identity.duet_id,
            creator_episode_id=creator_episode_id,
            kind=kind,
            expected_unit_index=expected_unit_index,
            code=code,
            field_ids=field_ids,
            guidance_artifact_ids=guidance_artifact_ids,
        )
        self.store.put_artifact(
            artifact_id=message_id.value,
            duet_id=identity.duet_id.value,
            creator_episode_id=creator_episode_id.value,
            kind="duet_decision",
            revision=expected_unit_index,
            content_hash=Sha256Digest.of_record(decision.as_record()).value,
            record=decision.as_record(),
        )
        return decision

    def submit_duet_decision(self, decision_artifact_id: OpaqueId) -> bool:
        artifact = self.store.get_artifact(decision_artifact_id.value)
        if artifact is None or artifact["kind"] != "duet_decision":
            raise DuetNotFoundError("human decision artifact not found")
        record = artifact["record"]
        decision = DuetDecision(
            message_id=OpaqueId(record["message_id"]),
            duet_id=OpaqueId(record["duet_id"]),
            creator_episode_id=OpaqueId(record["creator_episode_id"]),
            kind=DuetMessageKind(record["kind"]),
            expected_unit_index=record["expected_unit_index"],
            code=record["code"],
            field_ids=tuple(record["field_ids"]),
            guidance_artifact_ids=tuple(
                OpaqueId(item) for item in record["guidance_artifact_ids"]
            ),
        )
        return self.queue_decision(decision)

    def claim_boundary_messages(
        self,
        creator_episode_id: OpaqueId,
        *,
        unit_index: int,
    ) -> tuple[DuetDecision, ...]:
        records = self.store.claim_messages_at_boundary(
            creator_episode_id=creator_episode_id.value,
            unit_index=unit_index,
        )
        return tuple(
            DuetDecision(
                message_id=OpaqueId(record["message_id"]),
                duet_id=OpaqueId(record["duet_id"]),
                creator_episode_id=OpaqueId(record["creator_episode_id"]),
                kind=DuetMessageKind(record["kind"]),
                expected_unit_index=record["expected_unit_index"],
                code=record["code"],
                field_ids=tuple(record["field_ids"]),
                guidance_artifact_ids=tuple(
                    OpaqueId(item) for item in record["guidance_artifact_ids"]
                ),
            )
            for record in records
        )

    def creator_boundary_records(
        self,
        messages: tuple[DuetDecision, ...],
    ) -> tuple[dict[str, Any], ...]:
        """Resolve trusted human guidance for already-claimed boundary messages."""

        resolved = []
        for message in messages:
            guidance = []
            for artifact_id in message.guidance_artifact_ids:
                artifact = self.store.get_artifact(artifact_id.value)
                if (
                    artifact is None
                    or artifact["kind"] != "creator_guidance"
                    or artifact["duet_id"] != message.duet_id.value
                    or artifact["creator_episode_id"]
                    != message.creator_episode_id.value
                ):
                    raise DuetProtocolError(
                        "claimed Creator guidance failed authority validation"
                    )
                guidance.append(artifact["record"])
            resolved.append(
                {
                    "decision": message.as_record(),
                    "trusted_human_guidance": guidance,
                }
            )
        return tuple(resolved)

    def duet_status(self, duet_id: OpaqueId) -> dict[str, Any]:
        """Closed status for workflow design, execution, and real Creator nodes."""

        row = self._duet_row(duet_id)
        draft_artifact = self.store.latest_artifact(
            duet_id=duet_id.value,
            kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
            unowned_only=True,
        )
        workflow_draft = None
        if draft_artifact is not None:
            draft_record = draft_artifact["record"]
            workflow_draft = {
                "artifact_id": draft_artifact["artifact_id"],
                "revision": draft_artifact["revision"],
                "content_hash": draft_artifact["content_hash"],
                "source_stage": draft_record["source_stage"],
                "workflow_hash": draft_record.get("workflow_hash"),
                "ready": bool(draft_record.get("ready")),
                "validation_deficits": list(
                    draft_record.get("validation_deficits") or ()
                ),
            }

        approval = self.store.latest_approval(
            duet_id=duet_id.value,
            kind=ApprovalKind.WORKFLOW.value,
        )
        superseded_approval = None
        if approval is not None:
            approved_artifact = self.store.get_artifact(approval["artifact_id"])
            source_id = (
                None
                if approved_artifact is None
                else approved_artifact["record"].get("source_draft_artifact_id")
            )
            if (
                draft_artifact is None
                or source_id != draft_artifact["artifact_id"]
                or approval.get("revoked")
            ):
                superseded_approval = approval
                approval = None

        review = None
        if draft_artifact is not None:
            review_artifact = self.store.latest_artifact(
                duet_id=duet_id.value,
                kind="workflow_shadow_review",
                unowned_only=True,
            )
            authority = self.workflow_admission_authority(duet_id)
            if (
                review_artifact is not None
                and review_artifact["record"].get("workflow_blueprint_hash")
                == draft_artifact["content_hash"]
                and review_artifact["record"].get("admission_authority_hash")
                == authority.content_hash.value
            ):
                review_record = review_artifact["record"]
                review = {
                    "review_artifact_id": review_artifact["artifact_id"],
                    "workflow_blueprint_hash": review_record["workflow_blueprint_hash"],
                    "lenses": [
                        {
                            "lens": lens,
                            "verdict": result.get("verdict", "unknown"),
                            "finding_codes": [
                                finding.get("code")
                                for finding in result.get("findings") or ()
                                if isinstance(finding, Mapping)
                                and isinstance(finding.get("code"), str)
                            ],
                        }
                        for lens, result in sorted(
                            (review_record.get("lenses") or {}).items()
                        )
                    ],
                }

        creator_statuses = []
        for creator in self.store.creators(duet_id.value):
            creator_id = creator["creator_episode_id"]
            progress_artifact = self.store.latest_artifact(
                duet_id=duet_id.value,
                kind="creator_progress",
                creator_episode_id=creator_id,
            )
            activity_artifacts = self.store.recent_artifacts_by_kind(
                duet_id=duet_id.value,
                kind="creator_activity",
                creator_episode_id=creator_id,
                limit=8,
            )
            failure_artifact = self.store.latest_artifact(
                duet_id=duet_id.value,
                kind="creator_execution_error",
                creator_episode_id=creator_id,
            )
            creator_statuses.append(
                {
                    "creator_episode_id": creator_id,
                    "node_local_id": creator["node_local_id"],
                    "parent_creator_episode_id": creator["parent_creator_episode_id"],
                    "source_design_artifact_id": creator["design_artifact_id"],
                    "state": creator["state"],
                    "progress": (
                        None if progress_artifact is None else progress_artifact["record"]
                    ),
                    "activity": (
                        None
                        if not activity_artifacts
                        else activity_artifacts[-1]["record"]
                    ),
                    "activity_history": [
                        item["record"] for item in activity_artifacts
                    ],
                    "failure": (
                        None
                        if failure_artifact is None
                        else {
                            "error_artifact_id": failure_artifact["artifact_id"],
                            **failure_artifact["record"],
                        }
                    ),
                }
            )

        return {
            "duet_id": duet_id.value,
            "state": row["state"],
            "ready": bool(workflow_draft and workflow_draft["ready"]),
            "episode_workflow_draft": workflow_draft,
            "workflow_review": review,
            "workflow_approval": approval,
            "superseded_workflow_approval": superseded_approval,
            "launch": self.store.latest_launch(duet_id.value),
            "creator_episodes": creator_statuses,
            "creator_context_artifacts": list(
                self.list_creator_context_artifacts(duet_id)
            ),
            "creator_context_policy": {
                "required_for": "explicit_creator_episode_nodes_only",
                "ordinary_task_workflows_require_context_artifacts": False,
                "creation_tool": "creator_context_artifact",
                "read_tool": "creator_context_read",
                "accepted_artifact_kind": _CREATOR_CONTEXT_ARTIFACT_KIND,
                "prior_workflow_approval_or_contract_is_context": False,
            },
            "allowed_episode_capability_names": sorted(
                self.allowed_episode_capabilities
            ),
            "creator_progress_adapter": {
                "adapter_id": CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
                "host_owned": True,
                "measurement_boundary": "root_episode_progress",
                "applies_to": "explicit_creator_episode_nodes_only",
            },
        }



__all__ = [
    "CreatorContextValidationError",
    "DuetProtocolError",
    "DuetService",
    "StaleDuetApprovalError",
    "WorkflowAdmissionError",
]
