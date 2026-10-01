"""Host authority boundary for Duet-owned workflow design and launch."""

from __future__ import annotations

import json
import threading
from typing import Any, Iterable, Mapping, Optional

from agent.duet_contracts import (
    ApprovalKind,
    ContractDeficit,
    DuetApproval,
    DuetDesignState,
    DuetIdentity,
    DuetPolicy,
    DuetProvenance,
    FrozenDuetWorkflow,
    WorkflowAdmissionAuthority,
    canonical_json,
    content_id,
)
from agent.duet_store import (
    DuetConflictError,
    DuetNotFoundError,
    DuetStore,
)
from agent.episode_blueprints import workflow_spec_from_blueprint
from agent.episode_contracts import (
    EpisodeContractError,
    EpisodeWorkflowSpec,
    OpaqueId,
    Sha256Digest,
)


EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND = "episode_workflow_draft"


class DuetProtocolError(RuntimeError):
    """A Duet protocol operation violates its authority boundary."""


class StaleDuetApprovalError(DuetProtocolError):
    """A human approval no longer binds the current exact workflow."""


class WorkflowAdmissionError(DuetProtocolError):
    def __init__(self, deficits: Iterable[ContractDeficit]) -> None:
        self.deficits = tuple(deficits)
        super().__init__(
            "workflow admission failed: "
            + ", ".join(
                f"{item.field_path}:{item.code}" for item in self.deficits
            )
        )


class DuetService:
    """Validate, persist, freeze, approve, and launch Duet workflows."""

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

    def open_duet(self, identity: DuetIdentity, policy: DuetPolicy) -> None:
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
        return DuetPolicy.from_record(self._duet_row(duet_id)["policy"])

    def record_human_approval(
        self,
        identity: DuetIdentity,
        *,
        kind: ApprovalKind,
        artifact_id: OpaqueId,
        content_hash: Sha256Digest,
        revision: int,
    ) -> DuetApproval:
        if self._duet_row(identity.duet_id)["identity"] != identity.as_record():
            raise DuetProtocolError(
                "human approval authority does not match the Duet"
            )
        approval = DuetApproval(
            approval_id=content_id(
                "approval",
                {
                    "duet_id": identity.duet_id.value,
                    "human_authority_id": identity.human_authority_id.value,
                    "kind": kind.value,
                    "artifact_id": artifact_id.value,
                    "content_hash": content_hash.value,
                    "revision": revision,
                },
            ),
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

    def workflow_admission_authority(
        self,
        duet_id: OpaqueId,
    ) -> WorkflowAdmissionAuthority:
        self._duet_row(duet_id)
        return WorkflowAdmissionAuthority(
            duet_id=duet_id,
            assignable_capability_names=tuple(
                sorted(self.allowed_episode_capabilities)
            ),
        )

    def validate_duet_workflow(
        self,
        duet_id: OpaqueId,
        workflow_blueprint: Mapping[str, Any],
    ) -> tuple[Optional[EpisodeWorkflowSpec], tuple[ContractDeficit, ...]]:
        if not isinstance(workflow_blueprint, Mapping):
            return None, (
                ContractDeficit(
                    "invalid_workflow",
                    "goal",
                    detail="Episode workflow must be a JSON object",
                ),
            )
        try:
            workflow = workflow_spec_from_blueprint(workflow_blueprint)
        except (EpisodeContractError, TypeError, ValueError) as exc:
            field_path = (
                ".".join(exc.field_path)
                if isinstance(exc, EpisodeContractError) and exc.field_path
                else "goal"
            )
            return None, (
                ContractDeficit(
                    "invalid_workflow",
                    field_path,
                    detail=str(exc),
                ),
            )
        deficits: list[ContractDeficit] = []
        roots = [
            item
            for item in workflow.episodes
            if item.workflow_parent_local_id is None
        ]
        if len(roots) != 1:
            deficits.append(ContractDeficit("single_root_required", "goal"))
        allowed = set(
            self.workflow_admission_authority(duet_id).assignable_capability_names
        )
        for item in workflow.episodes:
            if not set(item.contract.execution_capability_names).issubset(allowed):
                deficits.append(
                    ContractDeficit(
                        "capability_escalation",
                        "execution_capability_names",
                    )
                )
            if item.episode_reference is not None:
                try:
                    from episode_library import episode_library

                    episode_library.resolve_optional(item.episode_reference)
                except (TypeError, ValueError) as exc:
                    deficits.append(
                        ContractDeficit(
                            "unknown_episode_reference",
                            "episode_reference",
                            detail=f"{item.local_id}: {exc}",
                        )
                    )
        unique = {
            (item.code, item.field_path, item.blocking): item for item in deficits
        }
        return workflow, tuple(unique[key] for key in sorted(unique))

    def read_episode_workflow_draft(
        self,
        duet_id: OpaqueId,
        artifact_id: OpaqueId,
    ) -> dict[str, Any]:
        artifact = self.store.get_artifact(artifact_id.value)
        if (
            artifact is None
            or artifact["duet_id"] != duet_id.value
            or artifact["kind"] != EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND
        ):
            raise DuetNotFoundError(
                "Episode workflow draft not found for this Duet"
            )
        blueprint = artifact["record"].get("workflow_blueprint")
        if not isinstance(blueprint, Mapping):
            raise DuetProtocolError("Episode workflow draft body is malformed")
        if Sha256Digest.of_record(blueprint).value != artifact["content_hash"]:
            raise DuetProtocolError(
                "Episode workflow draft hash verification failed"
            )
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
        duet = self._duet_row(duet_id)
        if duet["state"] == DuetDesignState.SEALED.value:
            raise DuetProtocolError(
                "the approved Episode workflow is frozen and cannot be revised"
            )
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
            )
            actual_hash = None if prior is None else prior["content_hash"]
            if expected_workflow_hash != actual_hash:
                raise DuetConflictError(
                    "Episode workflow changed while it was being edited"
                )
            if prior is not None and prior["content_hash"] == blueprint_hash.value:
                return prior
            workflow, deficits = self.validate_duet_workflow(duet_id, blueprint)
            revision = 1 if prior is None else int(prior["revision"]) + 1
            record = {
                "duet_id": duet_id.value,
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
            raise DuetProtocolError(
                "Episode workflow draft was not durably stored"
            )
        return artifact

    def freeze_duet_workflow(
        self,
        *,
        duet_id: OpaqueId,
        source_draft_artifact_id: OpaqueId,
        source_draft_hash: Sha256Digest,
    ) -> FrozenDuetWorkflow:
        source = self.store.get_artifact(source_draft_artifact_id.value)
        latest = self.store.latest_artifact(
            duet_id=duet_id.value,
            kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
        )
        if (
            source is None
            or source["duet_id"] != duet_id.value
            or source["kind"] != EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND
            or source["content_hash"] != source_draft_hash.value
            or latest is None
            or latest["artifact_id"] != source["artifact_id"]
        ):
            raise StaleDuetApprovalError(
                "Episode workflow draft changed before it could be frozen"
            )
        workflow, deficits = self.validate_duet_workflow(
            duet_id,
            source["record"].get("workflow_blueprint"),
        )
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
        frozen = FrozenDuetWorkflow(
            artifact_id=content_id("workflow", identity_record),
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
            artifact_id=frozen.artifact_id.value,
            duet_id=duet_id.value,
            kind="duet_workflow",
            revision=frozen.revision,
            content_hash=frozen.workflow_hash.value,
            record=frozen.as_record(),
        )
        self.store.set_state(duet_id.value, DuetDesignState.SEALED.value)
        return frozen

    def duet_status(self, duet_id: OpaqueId) -> dict[str, Any]:
        row = self._duet_row(duet_id)
        draft = self.store.latest_artifact(
            duet_id=duet_id.value,
            kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
        )
        workflow_draft = None
        if draft is not None:
            workflow, deficits = self.validate_duet_workflow(
                duet_id,
                draft["record"].get("workflow_blueprint"),
            )
            workflow_draft = {
                "artifact_id": draft["artifact_id"],
                "revision": draft["revision"],
                "content_hash": draft["content_hash"],
                "source_stage": draft["record"]["source_stage"],
                "workflow_hash": (
                    None if workflow is None else workflow.workflow_hash.value
                ),
                "ready": not deficits,
                "validation_deficits": [item.as_record() for item in deficits],
            }
        approval = self.store.latest_approval(
            duet_id=duet_id.value,
            kind=ApprovalKind.WORKFLOW.value,
        )
        if approval is not None:
            approved = self.store.get_artifact(approval["artifact_id"])
            source_id = (
                None
                if approved is None
                else approved["record"].get("source_draft_artifact_id")
            )
            if (
                draft is None
                or source_id != draft["artifact_id"]
                or approval.get("revoked")
            ):
                approval = None
        return {
            "duet_id": duet_id.value,
            "state": row["state"],
            "ready": bool(workflow_draft and workflow_draft["ready"]),
            "episode_workflow_draft": workflow_draft,
            "workflow_approval": approval,
            "allowed_episode_capability_names": sorted(
                self.allowed_episode_capabilities
            ),
        }


__all__ = [
    "DuetProtocolError",
    "DuetService",
    "EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND",
    "StaleDuetApprovalError",
    "WorkflowAdmissionError",
]
