"""Host authority boundary for Duet workflow design and refinement."""

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
    DuetProtocolError,
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
from agent.episode_blueprints import (
    INITIAL_WORKFLOW_SOURCE_STAGES,
    REFINEMENT_WORKFLOW_SOURCE_STAGES,
    WORKFLOW_DRAFT_FIELDS,
    creation_spec_from_blueprint,
    workflow_blueprint_from_spec,
    workflow_draft_record,
    workflow_spec_from_blueprint,
)
from agent.episode_contracts import (
    EpisodeContractError,
    EpisodeDeliverableKind,
    EpisodeWorkflowSpec,
    OpaqueId,
    Sha256Digest,
    validate_egress_host,
    validate_egress_name,
)
from iterative_episode_refiner.contracts import (
    CurrentBuildAuthorization,
    RefinementChangeKind,
    RefinementCycleState,
    RefinementDecision,
)
from iterative_episode_refiner.service import (
    IterativeEpisodeRefiner,
    REFINEMENT_DECISION_ARTIFACT_KIND,
)


EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND = "episode_workflow_draft"
DUET_WORKFLOW_ARTIFACT_KIND = "duet_workflow"
WORKFLOW_ADMISSION_AUTHORITY_ARTIFACT_KIND = "workflow_admission_authority"


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


def _egress_rule_invalid_detail(
    workflow_blueprint: Mapping[str, Any],
    exc: Exception,
) -> str:
    """Name the Episode whose egress_allowlist failed host validation."""

    episodes = workflow_blueprint.get("episodes")
    if isinstance(episodes, list):
        for node in episodes:
            if not isinstance(node, Mapping):
                continue
            try:
                creation_spec_from_blueprint(node.get("contract"))
            except EpisodeContractError as node_exc:
                if node_exc.field_path[:1] == ("egress_allowlist",):
                    local_id = node.get("local_id")
                    if isinstance(local_id, str):
                        return f"{local_id}: {node_exc}"
            except (TypeError, ValueError):
                continue
    return str(exc)


def _egress_ceiling_deficits(
    workflow: EpisodeWorkflowSpec,
    authority: WorkflowAdmissionAuthority,
) -> list[ContractDeficit]:
    """One deficit per exceeded ceiling, naming every offending Episode rule."""

    offenders: dict[str, list[str]] = {"host": [], "credential": []}
    for item in workflow.episodes:
        for rule in item.contract.egress_allowlist:
            for dimension in authority.egress_rule_violations(rule):
                value = rule.host if dimension == "host" else rule.credential
                offenders[dimension].append(
                    f"{item.local_id} rule {rule.name!r} {dimension} {value!r}"
                )
    deficits = []
    if offenders["host"]:
        deficits.append(
            ContractDeficit(
                "egress_host_not_allowed",
                "egress_allowlist.host",
                detail=(
                    "; ".join(offenders["host"])
                    + " is outside the operator's allowed egress hosts "
                    + repr(list(authority.egress_hosts))
                ),
            )
        )
    if offenders["credential"]:
        deficits.append(
            ContractDeficit(
                "egress_credential_unknown",
                "egress_allowlist.credential",
                detail=(
                    "; ".join(offenders["credential"])
                    + " names no operator-configured credential "
                    + repr(list(authority.egress_credential_names))
                ),
            )
        )
    return deficits


def _artifact_spec(
    *,
    artifact_id: OpaqueId,
    duet_id: OpaqueId,
    kind: str,
    revision: int,
    content_hash: Sha256Digest,
    record: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id.value,
        "duet_id": duet_id.value,
        "kind": kind,
        "revision": revision,
        "content_hash": content_hash.value,
        "record": dict(record),
    }


def _approval_identity_record(
    *,
    duet_id: OpaqueId,
    human_authority_id: OpaqueId,
    kind: ApprovalKind,
    artifact_id: OpaqueId,
    content_hash: Sha256Digest,
    revision: int,
    predecessor_approval_id: Optional[OpaqueId],
) -> dict[str, Any]:
    return {
        "duet_id": duet_id.value,
        "human_authority_id": human_authority_id.value,
        "kind": kind.value,
        "artifact_id": artifact_id.value,
        "content_hash": content_hash.value,
        "revision": revision,
        "predecessor_approval_id": (
            None
            if predecessor_approval_id is None
            else predecessor_approval_id.value
        ),
    }


def _frozen_identity_record(
    *,
    duet_id: OpaqueId,
    source_draft_artifact_id: OpaqueId,
    source_draft_hash: Sha256Digest,
    revision: int,
    workflow_hash: Sha256Digest,
    admission_authority_id: OpaqueId,
    admission_authority_hash: Sha256Digest,
    refinement_decision_id: Optional[OpaqueId],
    refinement_decision_hash: Optional[Sha256Digest],
) -> dict[str, Any]:
    return {
        "duet_id": duet_id.value,
        "source_draft_artifact_id": source_draft_artifact_id.value,
        "source_draft_hash": source_draft_hash.value,
        "revision": revision,
        "workflow_hash": workflow_hash.value,
        "admission_authority_id": admission_authority_id.value,
        "admission_authority_hash": admission_authority_hash.value,
        "refinement_decision_id": (
            None
            if refinement_decision_id is None
            else refinement_decision_id.value
        ),
        "refinement_decision_hash": (
            None
            if refinement_decision_hash is None
            else refinement_decision_hash.value
        ),
    }


class DuetService:
    """Validate, persist, approve, and resolve Duet-owned Architecture."""

    def __init__(
        self,
        store: DuetStore,
        *,
        allowed_episode_capabilities: Iterable[str],
        allowed_egress_hosts: Iterable[str] = (),
        egress_credential_names: Iterable[str] = (),
    ) -> None:
        if not isinstance(store, DuetStore):
            raise TypeError("DuetService requires a DuetStore")
        capabilities = tuple(sorted(set(allowed_episode_capabilities)))
        if any(not isinstance(item, str) or not item for item in capabilities):
            raise ValueError("allowed Episode capabilities must be names")
        egress_hosts = frozenset(
            validate_egress_host(item, "allowed egress host")
            for item in allowed_egress_hosts
        )
        credential_names = frozenset(
            validate_egress_name(item, "egress credential name")
            for item in egress_credential_names
        )
        self.store = store
        self.allowed_episode_capabilities = frozenset(capabilities)
        self.allowed_egress_hosts = egress_hosts
        self.egress_credential_names = credential_names
        self._workflow_draft_lock = threading.RLock()
        self.refiner = IterativeEpisodeRefiner(store, self)

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
            raise DuetConflictError(
                "duet_id already names another immutable identity or policy"
            )

    def _duet_row(self, duet_id: OpaqueId) -> dict[str, Any]:
        row = self.store.get_duet(duet_id.value)
        if row is None:
            raise DuetNotFoundError("unknown Duet")
        return row

    def _assert_identity(self, identity: DuetIdentity) -> dict[str, Any]:
        row = self._duet_row(identity.duet_id)
        if row["identity"] != identity.as_record():
            raise DuetProtocolError(
                "human approval authority does not match the Duet"
            )
        return row

    def policy(self, duet_id: OpaqueId) -> DuetPolicy:
        return DuetPolicy.from_record(self._duet_row(duet_id)["policy"])

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
            egress_hosts=tuple(sorted(self.allowed_egress_hosts)),
            egress_credential_names=tuple(
                sorted(self.egress_credential_names)
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
            if field_path.split(".")[0] == "egress_allowlist":
                return None, (
                    ContractDeficit(
                        "egress_rule_invalid",
                        field_path,
                        detail=_egress_rule_invalid_detail(
                            workflow_blueprint, exc
                        ),
                    ),
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
        authority = self.workflow_admission_authority(duet_id)
        allowed = set(authority.assignable_capability_names)
        deficits.extend(_egress_ceiling_deficits(workflow, authority))
        episodes_by_id = {item.local_id: item for item in workflow.episodes}
        for item in workflow.episodes:
            capabilities = set(item.contract.execution_capability_names)
            if not capabilities.issubset(allowed):
                deficits.append(
                    ContractDeficit(
                        "capability_escalation",
                        "execution_capability_names",
                    )
                )
            if (
                item.contract.deliverable.kind
                is not EpisodeDeliverableKind.TYPED_STATUS
            ):
                deficits.append(
                    ContractDeficit(
                        "deliverable_not_runnable",
                        "deliverable",
                        detail=(
                            f"{item.local_id}: the current isolated runtime "
                            "materializes terminal typed status"
                        ),
                    )
                )
            parent_id = item.workflow_parent_local_id
            if parent_id is not None:
                parent_capabilities = set(
                    episodes_by_id[parent_id].contract.execution_capability_names
                )
                if not capabilities.issubset(parent_capabilities):
                    deficits.append(
                        ContractDeficit(
                            "capability_inheritance_violation",
                            "execution_capability_names",
                            detail=(
                                f"{item.local_id}: child capabilities must be "
                                f"inherited from {parent_id}"
                            ),
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

    def _stored_approval(self, approval_id: OpaqueId) -> DuetApproval:
        stored = self.store.get_approval(approval_id.value)
        if stored is None:
            raise DuetNotFoundError("approval not found")
        required = {
            "approval_id",
            "duet_id",
            "human_authority_id",
            "kind",
            "artifact_id",
            "content_hash",
            "revision",
            "predecessor_approval_id",
            "revoked",
        }
        if set(stored) != required or not isinstance(stored["revoked"], bool):
            raise DuetProtocolError("stored approval is malformed")
        if stored["revoked"]:
            raise DuetProtocolError("approval has been revoked")
        try:
            approval = DuetApproval.from_record(
                {key: value for key, value in stored.items() if key != "revoked"}
            )
        except (TypeError, ValueError) as exc:
            raise DuetProtocolError("stored approval is malformed") from exc
        expected = content_id(
            "approval",
            _approval_identity_record(
                duet_id=approval.duet_id,
                human_authority_id=approval.human_authority_id,
                kind=approval.kind,
                artifact_id=approval.artifact_id,
                content_hash=approval.content_hash,
                revision=approval.revision,
                predecessor_approval_id=approval.predecessor_approval_id,
            ),
        )
        if approval.approval_id != approval_id or approval.approval_id != expected:
            raise DuetProtocolError("approval identity is stale")
        return approval

    def _artifact_of_kind(
        self,
        artifact_id: OpaqueId,
        *,
        duet_id: OpaqueId,
        kind: str,
    ) -> dict[str, Any]:
        artifact = self.store.get_artifact(artifact_id.value)
        if (
            artifact is None
            or artifact["duet_id"] != duet_id.value
            or artifact["kind"] != kind
        ):
            raise DuetNotFoundError(f"{kind} artifact not found for this Duet")
        return artifact

    def verify_workflow_approval(
        self,
        approval_id: OpaqueId,
    ) -> tuple[DuetApproval, FrozenDuetWorkflow, WorkflowAdmissionAuthority]:
        """Verify one historical workflow approval without requiring it current."""

        if not isinstance(approval_id, OpaqueId):
            raise TypeError("approval_id must be an OpaqueId")
        approval = self._stored_approval(approval_id)
        if approval.kind is not ApprovalKind.WORKFLOW:
            raise DuetProtocolError("approval does not authorize a workflow")
        duet = self._duet_row(approval.duet_id)
        try:
            identity = DuetIdentity.from_record(duet["identity"])
        except (TypeError, ValueError) as exc:
            raise DuetProtocolError("stored Duet identity is malformed") from exc
        if identity.human_authority_id != approval.human_authority_id:
            raise DuetProtocolError(
                "workflow approval does not carry the Duet human authority"
            )
        artifact = self.store.get_artifact(approval.artifact_id.value)
        if artifact is None:
            raise DuetNotFoundError("approved frozen workflow is missing")
        if (
            artifact["duet_id"] != approval.duet_id.value
            or artifact["kind"] != DUET_WORKFLOW_ARTIFACT_KIND
            or artifact["revision"] != approval.revision
            or artifact["content_hash"] != approval.content_hash.value
        ):
            raise DuetProtocolError(
                "workflow approval does not match its frozen artifact"
            )
        try:
            frozen = FrozenDuetWorkflow.from_record(artifact["record"])
        except (TypeError, ValueError) as exc:
            raise DuetProtocolError("frozen workflow artifact is malformed") from exc
        expected_frozen_id = content_id(
            "workflow",
            _frozen_identity_record(
                duet_id=frozen.duet_id,
                source_draft_artifact_id=frozen.source_draft_artifact_id,
                source_draft_hash=frozen.source_draft_hash,
                revision=frozen.revision,
                workflow_hash=frozen.workflow_hash,
                admission_authority_id=frozen.admission_authority_id,
                admission_authority_hash=frozen.admission_authority_hash,
                refinement_decision_id=frozen.refinement_decision_id,
                refinement_decision_hash=frozen.refinement_decision_hash,
            ),
        )
        if (
            frozen.artifact_id != approval.artifact_id
            or frozen.duet_id != approval.duet_id
            or frozen.revision != approval.revision
            or frozen.workflow_hash != approval.content_hash
            or frozen.artifact_id != expected_frozen_id
        ):
            raise DuetProtocolError("frozen workflow identity is stale")
        source = self.store.get_artifact(frozen.source_draft_artifact_id.value)
        if (
            source is None
            or source["duet_id"] != frozen.duet_id.value
            or source["kind"] != EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND
            or source["revision"] != frozen.revision
            or source["content_hash"] != frozen.source_draft_hash.value
        ):
            raise DuetProtocolError("frozen workflow source linkage is stale")
        source_record = source["record"]
        if (
            not isinstance(source_record, Mapping)
            or set(source_record) != WORKFLOW_DRAFT_FIELDS
        ):
            raise DuetProtocolError("workflow source draft is malformed")
        blueprint = source_record["workflow_blueprint"]
        if (
            source_record["duet_id"] != frozen.duet_id.value
            or source_record["revision"] != frozen.revision
            or source_record["source_stage"]
            not in (
                INITIAL_WORKFLOW_SOURCE_STAGES
                | REFINEMENT_WORKFLOW_SOURCE_STAGES
            )
            or source_record["workflow_blueprint_hash"]
            != frozen.source_draft_hash.value
            or source_record["workflow_hash"] != frozen.workflow_hash.value
            or source_record["validation_deficits"] != []
            or source_record["ready"] is not True
            or not isinstance(blueprint, Mapping)
            or Sha256Digest.of_record(blueprint) != frozen.source_draft_hash
        ):
            raise DuetProtocolError(
                "workflow source draft does not match the frozen workflow"
            )
        try:
            source_workflow = workflow_spec_from_blueprint(blueprint)
        except (EpisodeContractError, TypeError, ValueError) as exc:
            raise DuetProtocolError(
                "workflow source draft cannot be reconstructed"
            ) from exc
        if source_workflow.as_record() != frozen.workflow.as_record():
            raise DuetProtocolError(
                "workflow source draft content differs from the frozen workflow"
            )
        if frozen.refinement_decision_id is None:
            if any(
                source_record[name] is not None
                for name in ("refinement_id", "baseline_id", "proposal_id")
            ):
                raise DuetProtocolError(
                    "initial workflow draft carries successor lineage"
                )
            if approval.predecessor_approval_id is not None:
                raise DuetProtocolError(
                    "successor workflow approval has no refinement decision"
                )
        else:
            self.refiner.verify_semantic_successor(
                approval=approval,
                frozen=frozen,
                source_record=source_record,
            )
        authority_artifact = self.store.get_artifact(
            frozen.admission_authority_id.value
        )
        if (
            authority_artifact is None
            or authority_artifact["duet_id"] != frozen.duet_id.value
            or authority_artifact["kind"]
            != WORKFLOW_ADMISSION_AUTHORITY_ARTIFACT_KIND
            or authority_artifact["revision"] != 0
            or authority_artifact["content_hash"]
            != frozen.admission_authority_hash.value
        ):
            raise DuetProtocolError(
                "frozen workflow admission authority linkage is stale"
            )
        try:
            authority = WorkflowAdmissionAuthority.from_record(
                authority_artifact["record"]
            )
        except (TypeError, ValueError) as exc:
            raise DuetProtocolError(
                "workflow admission authority is malformed"
            ) from exc
        if (
            authority.duet_id != frozen.duet_id
            or authority.authority_id != frozen.admission_authority_id
            or authority.content_hash != frozen.admission_authority_hash
        ):
            raise DuetProtocolError(
                "workflow admission authority does not match its artifact"
            )
        authority_capabilities = set(authority.assignable_capability_names)
        frozen_by_id = {
            episode.local_id: episode for episode in frozen.workflow.episodes
        }
        for episode in frozen.workflow.episodes:
            capabilities = set(episode.contract.execution_capability_names)
            if not capabilities.issubset(authority_capabilities):
                raise DuetProtocolError(
                    "frozen workflow exceeds its admission authority"
                )
            parent_id = episode.workflow_parent_local_id
            if parent_id is not None and not capabilities.issubset(
                frozen_by_id[parent_id].contract.execution_capability_names
            ):
                raise DuetProtocolError(
                    "frozen workflow violates capability inheritance"
                )
            if any(
                authority.egress_rule_violations(rule)
                for rule in episode.contract.egress_allowlist
            ):
                raise DuetProtocolError(
                    "frozen workflow egress exceeds its admission authority"
                )
        return approval, frozen, authority

    def resolve_current_build_authorization(
        self,
        duet_id: OpaqueId,
    ) -> CurrentBuildAuthorization:
        row = self._duet_row(duet_id)
        if row["state"] != DuetDesignState.SEALED.value:
            raise DuetProtocolError("current Duet workflow is not sealed")
        head_value = row["authority_head_approval_id"]
        if not isinstance(head_value, str):
            raise DuetProtocolError("sealed Duet has no authority head")
        head = self._stored_approval(OpaqueId(head_value))
        decision: Optional[RefinementDecision] = None
        if head.kind is ApprovalKind.WORKFLOW:
            workflow_approval, frozen, authority = (
                self.verify_workflow_approval(head.approval_id)
            )
            if frozen.refinement_decision_id is not None:
                decision = self.refiner.load_decision(
                    frozen.refinement_decision_id
                )
        else:
            decision = self.refiner.load_decision(head.artifact_id)
            if (
                decision.kind
                is not RefinementChangeKind.IMPLEMENTATION_PRESERVING
                or decision.content_hash != head.content_hash
            ):
                raise DuetProtocolError(
                    "refinement approval does not authorize its exact decision"
                )
            baseline = self.refiner.load_baseline(decision.baseline_id)
            if baseline.authority_head_approval_id != head.predecessor_approval_id:
                raise DuetProtocolError(
                    "refinement approval does not extend its baseline authority"
                )
            workflow_approval, frozen, authority = (
                self.verify_workflow_approval(baseline.workflow_approval_id)
            )
            if (
                baseline.workflow_hash != frozen.workflow_hash
                or baseline.frozen_workflow_artifact_id != frozen.artifact_id
            ):
                raise DuetProtocolError(
                    "refinement baseline does not match its workflow approval"
                )
        if head.duet_id != duet_id:
            raise DuetProtocolError("authority head belongs to another Duet")
        if not set(authority.assignable_capability_names).issubset(
            self.allowed_episode_capabilities
        ):
            raise DuetProtocolError(
                "workflow authority exceeds current host capabilities"
            )
        if not set(authority.egress_hosts).issubset(
            self.allowed_egress_hosts
        ) or not set(authority.egress_credential_names).issubset(
            self.egress_credential_names
        ):
            raise DuetProtocolError(
                "workflow authority exceeds current host egress ceiling"
            )
        return CurrentBuildAuthorization(
            authority_approval=head,
            workflow_approval=workflow_approval,
            frozen_workflow=frozen,
            admission_authority=authority,
            refinement_decision=decision,
        )

    def read_episode_workflow_draft(
        self,
        duet_id: OpaqueId,
        artifact_id: OpaqueId,
    ) -> dict[str, Any]:
        artifact = self._artifact_of_kind(
            artifact_id,
            duet_id=duet_id,
            kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
        )
        record = artifact["record"]
        if (
            not isinstance(record, Mapping)
            or set(record) != WORKFLOW_DRAFT_FIELDS
        ):
            raise DuetProtocolError("Episode workflow draft is malformed")
        blueprint = record["workflow_blueprint"]
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
            "source_stage": record["source_stage"],
            "workflow_hash": record["workflow_hash"],
            "refinement_id": record["refinement_id"],
            "baseline_id": record["baseline_id"],
            "proposal_id": record["proposal_id"],
            "human_note_ids": list(record["human_note_ids"]),
            "workflow": json.loads(canonical_json(blueprint)),
        }

    def record_initial_workflow_draft(
        self,
        *,
        duet_id: OpaqueId,
        workflow_blueprint: Mapping[str, Any],
        expected_draft_artifact_id: Optional[str],
        expected_draft_hash: Optional[str],
        expected_draft_revision: Optional[int],
        source_stage: str,
        human_note_ids: tuple[OpaqueId, ...] = (),
    ) -> dict[str, Any]:
        """Record one still-mutable initial Duet Architecture draft."""

        if source_stage not in INITIAL_WORKFLOW_SOURCE_STAGES:
            raise ValueError("Duet workflow source must be duet or human_edit")
        if not isinstance(workflow_blueprint, Mapping):
            raise ValueError("Episode workflow draft must be an object")
        if not isinstance(human_note_ids, tuple) or any(
            not isinstance(item, OpaqueId) for item in human_note_ids
        ):
            raise TypeError("human_note_ids must be a tuple of OpaqueIds")
        if len({item.value for item in human_note_ids}) != len(human_note_ids):
            raise ValueError("human_note_ids must be unique")
        with self._workflow_draft_lock:
            row = self._duet_row(duet_id)
            if self.store.active_refinement_cycle(duet_id.value) is not None:
                raise DuetProtocolError(
                    "an immutable refinement decision already awaits approval; "
                    "approve or close it before editing again"
                )
            if row["state"] not in {
                DuetDesignState.DESIGNING.value,
                DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value,
            }:
                raise DuetProtocolError(
                    "Duet state does not accept an initial workflow revision"
                )
            return self._record_initial_draft(
                duet_id=duet_id,
                workflow_blueprint=workflow_blueprint,
                expected_draft_artifact_id=expected_draft_artifact_id,
                expected_draft_hash=expected_draft_hash,
                expected_draft_revision=expected_draft_revision,
                source_stage=source_stage,
                duet_row=row,
                human_note_ids=human_note_ids,
            )

    def _record_initial_draft(
        self,
        *,
        duet_id: OpaqueId,
        workflow_blueprint: Mapping[str, Any],
        expected_draft_artifact_id: Optional[str],
        expected_draft_hash: Optional[str],
        expected_draft_revision: Optional[int],
        source_stage: str,
        duet_row: Mapping[str, Any],
        human_note_ids: tuple[OpaqueId, ...],
    ) -> dict[str, Any]:
        for note_id in human_note_ids:
            note = self.refiner.load_note(note_id)
            if note.duet_id != duet_id or note.baseline_id is not None:
                raise DuetProtocolError(
                    "initial Architecture note belongs to another workspace"
                )
        prior = self.store.latest_artifact(
            duet_id=duet_id.value,
            kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
        )
        expected = (
            expected_draft_artifact_id,
            expected_draft_hash,
            expected_draft_revision,
        )
        if any(value is None for value in expected) and not all(
            value is None for value in expected
        ):
            raise ValueError(
                "draft artifact identity, hash, and revision move together"
            )
        actual = (
            (None, None, None)
            if prior is None
            else (
                prior["artifact_id"],
                prior["content_hash"],
                prior["revision"],
            )
        )
        if actual != expected:
            raise DuetConflictError(
                "Episode workflow changed while it was being edited"
            )
        raw_blueprint = json.loads(canonical_json(workflow_blueprint))
        workflow, deficits = self.validate_duet_workflow(duet_id, raw_blueprint)
        blueprint = (
            raw_blueprint
            if workflow is None or deficits
            else workflow_blueprint_from_spec(workflow)
        )
        blueprint_hash = Sha256Digest.of_record(blueprint)
        submitted_note_ids = [item.value for item in human_note_ids]
        if (
            prior is not None
            and prior["content_hash"] == blueprint_hash.value
            and prior["record"].get("human_note_ids") == submitted_note_ids
        ):
            return prior
        revision = 1 if prior is None else int(prior["revision"]) + 1
        record, blueprint_hash, artifact_id = workflow_draft_record(
            duet_id=duet_id,
            revision=revision,
            source_stage=source_stage,
            blueprint=blueprint,
            workflow=workflow,
            deficits=deficits,
            refinement_id=None,
            baseline_id=None,
            proposal_id=None,
            human_note_ids=human_note_ids,
        )
        next_state = (
            DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value
            if not deficits
            else DuetDesignState.DESIGNING.value
        )
        self.store.put_artifacts_with_transition(
            artifacts=(
                _artifact_spec(
                    artifact_id=artifact_id,
                    duet_id=duet_id,
                    kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
                    revision=revision,
                    content_hash=blueprint_hash,
                    record=record,
                ),
            ),
            duet_id=duet_id.value,
            expected_latest_artifact_kind=(
                EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND
            ),
            expected_latest_artifact_id=(
                None if prior is None else prior["artifact_id"]
            ),
            expected_latest_artifact_hash=(
                None if prior is None else prior["content_hash"]
            ),
            expected_latest_artifact_revision=(
                None if prior is None else prior["revision"]
            ),
            expected_state=duet_row["state"],
            expected_authority_head_approval_id=duet_row[
                "authority_head_approval_id"
            ],
            state=next_state,
            event_type="episode_workflow_revision",
            provenance=(
                DuetProvenance.HUMAN_INPUT.value
                if source_stage == "human_edit"
                else DuetProvenance.LLM_PROPOSAL.value
            ),
            event_record={
                "artifact_id": artifact_id.value,
                "revision": revision,
                "content_hash": blueprint_hash.value,
                "deficit_codes": [item.code for item in deficits],
            },
        )
        artifact = self.store.get_artifact(artifact_id.value)
        if artifact is None:
            raise DuetProtocolError("workflow draft was not durably stored")
        return artifact

    def _approval(
        self,
        *,
        identity: DuetIdentity,
        kind: ApprovalKind,
        artifact_id: OpaqueId,
        content_hash: Sha256Digest,
        revision: int,
        predecessor_approval_id: Optional[OpaqueId],
    ) -> DuetApproval:
        identity_record = _approval_identity_record(
            duet_id=identity.duet_id,
            human_authority_id=identity.human_authority_id,
            kind=kind,
            artifact_id=artifact_id,
            content_hash=content_hash,
            revision=revision,
            predecessor_approval_id=predecessor_approval_id,
        )
        return DuetApproval(
            approval_id=content_id("approval", identity_record),
            duet_id=identity.duet_id,
            human_authority_id=identity.human_authority_id,
            kind=kind,
            artifact_id=artifact_id,
            content_hash=content_hash,
            revision=revision,
            predecessor_approval_id=predecessor_approval_id,
        )

    def approve_current_workflow(
        self,
        identity: DuetIdentity,
        *,
        source_draft_artifact_id: OpaqueId,
        source_draft_hash: Sha256Digest,
    ) -> CurrentBuildAuthorization:
        row = self._assert_identity(identity)
        if row["state"] != DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value:
            raise DuetProtocolError("Duet is not awaiting workflow approval")
        source = self.store.get_artifact(source_draft_artifact_id.value)
        latest = self.store.latest_artifact(
            duet_id=identity.duet_id.value,
            kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
        )
        if (
            source is None
            or latest is None
            or source["artifact_id"] != latest["artifact_id"]
            or source["duet_id"] != identity.duet_id.value
            or source["kind"] != EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND
            or source["content_hash"] != source_draft_hash.value
        ):
            raise StaleDuetApprovalError(
                "Episode workflow draft changed before approval"
            )
        workflow, deficits = self.validate_duet_workflow(
            identity.duet_id,
            source["record"].get("workflow_blueprint"),
        )
        if workflow is None or deficits:
            raise WorkflowAdmissionError(deficits)
        cycle = self.store.active_refinement_cycle(identity.duet_id.value)
        decision: Optional[RefinementDecision] = None
        refinement_id: Optional[str] = None
        if cycle is None:
            if row["authority_head_approval_id"] is not None:
                raise DuetProtocolError(
                    "successor workflow approval requires a refinement cycle"
                )
        else:
            if (
                cycle["state"]
                != RefinementCycleState.AWAITING_WORKFLOW_APPROVAL.value
                or cycle["decision_artifact_id"] is None
            ):
                raise DuetProtocolError(
                    "refinement cycle is not awaiting workflow approval"
                )
            decision = self.refiner.load_decision(
                OpaqueId(cycle["decision_artifact_id"])
            )
            if (
                decision.kind is not RefinementChangeKind.DESIGN_SEMANTIC
                or decision.successor_draft_artifact_id
                != source_draft_artifact_id
                or decision.successor_draft_hash != source_draft_hash
            ):
                raise DuetProtocolError(
                    "workflow draft is not the semantic refinement successor"
                )
            refinement_id = cycle["refinement_id"]
        authority = self.workflow_admission_authority(identity.duet_id)
        frozen_identity = _frozen_identity_record(
            duet_id=identity.duet_id,
            source_draft_artifact_id=source_draft_artifact_id,
            source_draft_hash=source_draft_hash,
            revision=int(source["revision"]),
            workflow_hash=workflow.workflow_hash,
            admission_authority_id=authority.authority_id,
            admission_authority_hash=authority.content_hash,
            refinement_decision_id=(
                None if decision is None else decision.decision_id
            ),
            refinement_decision_hash=(
                None if decision is None else decision.content_hash
            ),
        )
        frozen = FrozenDuetWorkflow(
            artifact_id=content_id("workflow", frozen_identity),
            duet_id=identity.duet_id,
            revision=int(source["revision"]),
            workflow_hash=workflow.workflow_hash,
            workflow=workflow,
            admission_authority_id=authority.authority_id,
            admission_authority_hash=authority.content_hash,
            source_draft_artifact_id=source_draft_artifact_id,
            source_draft_hash=source_draft_hash,
            refinement_decision_id=(
                None if decision is None else decision.decision_id
            ),
            refinement_decision_hash=(
                None if decision is None else decision.content_hash
            ),
        )
        predecessor = (
            None
            if row["authority_head_approval_id"] is None
            else OpaqueId(row["authority_head_approval_id"])
        )
        approval = self._approval(
            identity=identity,
            kind=ApprovalKind.WORKFLOW,
            artifact_id=frozen.artifact_id,
            content_hash=frozen.workflow_hash,
            revision=frozen.revision,
            predecessor_approval_id=predecessor,
        )
        self.store.commit_approval(
            approval=approval.as_record(),
            artifacts=(
                _artifact_spec(
                    artifact_id=authority.authority_id,
                    duet_id=identity.duet_id,
                    kind=WORKFLOW_ADMISSION_AUTHORITY_ARTIFACT_KIND,
                    revision=0,
                    content_hash=authority.content_hash,
                    record=authority.as_record(),
                ),
                _artifact_spec(
                    artifact_id=frozen.artifact_id,
                    duet_id=identity.duet_id,
                    kind=DUET_WORKFLOW_ARTIFACT_KIND,
                    revision=frozen.revision,
                    content_hash=frozen.workflow_hash,
                    record=frozen.as_record(),
                ),
            ),
            expected_latest_artifact_kind=(
                EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND
            ),
            expected_latest_artifact_id=source["artifact_id"],
            expected_latest_artifact_hash=source["content_hash"],
            expected_latest_artifact_revision=source["revision"],
            expected_state=DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value,
            refinement_id=refinement_id,
            event_type="workflow_approved",
            provenance=DuetProvenance.HUMAN_APPROVAL.value,
            event_record={
                "approval_id": approval.approval_id.value,
                "artifact_id": frozen.artifact_id.value,
                "predecessor_approval_id": (
                    None if predecessor is None else predecessor.value
                ),
                "refinement_decision_id": (
                    None if decision is None else decision.decision_id.value
                ),
            },
        )
        return CurrentBuildAuthorization(
            authority_approval=approval,
            workflow_approval=approval,
            frozen_workflow=frozen,
            admission_authority=authority,
            refinement_decision=decision,
        )

    def approve_current_implementation_refinement(
        self,
        identity: DuetIdentity,
        *,
        decision_id: OpaqueId,
    ) -> DuetApproval:
        if not isinstance(decision_id, OpaqueId):
            raise TypeError("decision_id must be an OpaqueId")
        row = self._assert_identity(identity)
        if row["state"] != DuetDesignState.AWAITING_REFINEMENT_APPROVAL.value:
            raise DuetProtocolError(
                "Duet is not awaiting implementation refinement approval"
            )
        cycle = self.store.active_refinement_cycle(identity.duet_id.value)
        if (
            cycle is None
            or cycle["state"]
            != RefinementCycleState.AWAITING_REFINEMENT_APPROVAL.value
            or cycle["decision_artifact_id"] != decision_id.value
        ):
            raise DuetProtocolError(
                "refinement cycle is not awaiting implementation approval"
            )
        decision = self.refiner.load_decision(decision_id)
        if decision.kind is not RefinementChangeKind.IMPLEMENTATION_PRESERVING:
            raise DuetProtocolError("refinement decision changes workflow semantics")
        predecessor_value = row["authority_head_approval_id"]
        if predecessor_value != cycle["baseline_authority_head_approval_id"]:
            raise DuetProtocolError("refinement authority baseline is stale")
        if not isinstance(predecessor_value, str):
            raise DuetProtocolError("refinement baseline has no authority head")
        approval = self._approval(
            identity=identity,
            kind=ApprovalKind.REFINEMENT,
            artifact_id=decision.decision_id,
            content_hash=decision.content_hash,
            revision=int(cycle["ordinal"]),
            predecessor_approval_id=OpaqueId(predecessor_value),
        )
        self.store.commit_approval(
            approval=approval.as_record(),
            artifacts=(),
            expected_latest_artifact_kind=(
                REFINEMENT_DECISION_ARTIFACT_KIND
            ),
            expected_latest_artifact_id=decision.decision_id.value,
            expected_latest_artifact_hash=decision.content_hash.value,
            expected_latest_artifact_revision=int(cycle["ordinal"]),
            expected_state=DuetDesignState.AWAITING_REFINEMENT_APPROVAL.value,
            refinement_id=cycle["refinement_id"],
            event_type="refinement_approved",
            provenance=DuetProvenance.HUMAN_APPROVAL.value,
            event_record={
                "approval_id": approval.approval_id.value,
                "decision_id": decision.decision_id.value,
                "predecessor_approval_id": predecessor_value,
            },
        )
        return approval

    def duet_status(self, duet_id: OpaqueId) -> dict[str, Any]:
        row = self._duet_row(duet_id)
        active = self.store.active_refinement_cycle(duet_id.value)
        draft = None
        if row["state"] == DuetDesignState.SEALED.value and row[
            "authority_head_approval_id"
        ] is not None:
            authorization = self.resolve_current_build_authorization(duet_id)
            draft = self.store.get_artifact(
                authorization.frozen_workflow.source_draft_artifact_id.value
            )
        elif active is not None:
            baseline = self.refiner.load_baseline(
                OpaqueId(active["baseline_artifact_id"])
            )
            _, frozen, _ = self.verify_workflow_approval(
                baseline.workflow_approval_id
            )
            if (
                active["state"]
                == RefinementCycleState.AWAITING_WORKFLOW_APPROVAL.value
                and active["decision_artifact_id"] is not None
            ):
                decision = self.refiner.load_decision(
                    OpaqueId(active["decision_artifact_id"])
                )
                if decision.successor_draft_artifact_id is not None:
                    draft = self.store.get_artifact(
                        decision.successor_draft_artifact_id.value
                    )
            elif active["state"] == RefinementCycleState.REFINING.value:
                cycle_drafts = tuple(
                    item
                    for item in self.store.artifacts_by_kind(
                        duet_id=duet_id.value,
                        kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
                    )
                    if item["record"].get("refinement_id")
                    == active["refinement_id"]
                )
                if cycle_drafts:
                    draft = cycle_drafts[-1]
            if draft is None:
                draft = self.store.get_artifact(
                    frozen.source_draft_artifact_id.value
                )
        else:
            draft = self.store.latest_artifact(
                duet_id=duet_id.value,
                kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
            )
        workflow_draft = None
        if draft is not None:
            record = draft["record"]
            if (
                not isinstance(record, Mapping)
                or set(record) != WORKFLOW_DRAFT_FIELDS
            ):
                raise DuetProtocolError("stored workflow draft is malformed")
            workflow, deficits = self.validate_duet_workflow(
                duet_id,
                record["workflow_blueprint"],
            )
            workflow_draft = {
                "artifact_id": draft["artifact_id"],
                "revision": draft["revision"],
                "content_hash": draft["content_hash"],
                "source_stage": record["source_stage"],
                "workflow_hash": (
                    None if workflow is None else workflow.workflow_hash.value
                ),
                "ready": not deficits,
                "validation_deficits": [item.as_record() for item in deficits],
                "refinement_id": record["refinement_id"],
                "baseline_id": record["baseline_id"],
                "proposal_id": record["proposal_id"],
                "human_note_ids": list(record["human_note_ids"]),
            }
        head = None
        workflow_approval = None
        if row["authority_head_approval_id"] is not None:
            head = self.store.get_approval(row["authority_head_approval_id"])
            if head is not None:
                parsed_head = self._stored_approval(
                    OpaqueId(row["authority_head_approval_id"])
                )
                if parsed_head.kind is ApprovalKind.WORKFLOW:
                    workflow_approval = head
                else:
                    decision = self.refiner.load_decision(
                        parsed_head.artifact_id
                    )
                    baseline = self.refiner.load_baseline(
                        decision.baseline_id
                    )
                    workflow_approval = self.store.get_approval(
                        baseline.workflow_approval_id.value
                    )
        return {
            "duet_id": duet_id.value,
            "state": row["state"],
            "ready": row["state"]
            in {
                DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value,
                DuetDesignState.AWAITING_REFINEMENT_APPROVAL.value,
            },
            "episode_workflow_draft": workflow_draft,
            "authority_head_approval": head,
            "workflow_approval": workflow_approval,
            "active_refinement": active,
            "allowed_episode_capability_names": sorted(
                self.allowed_episode_capabilities
            ),
            "allowed_egress_hosts": sorted(self.allowed_egress_hosts),
            "egress_credential_names": sorted(self.egress_credential_names),
        }


__all__ = [
    "DUET_WORKFLOW_ARTIFACT_KIND",
    "DuetService",
    "EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND",
    "StaleDuetApprovalError",
    "WORKFLOW_ADMISSION_AUTHORITY_ARTIFACT_KIND",
    "WorkflowAdmissionError",
]
