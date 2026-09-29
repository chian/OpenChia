"""Host-owned Duet protocol, admission gates, and atomic workflow launch."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Optional

from agent.duet_contracts import (
    ApprovalKind,
    ContractDeficit,
    ContractFieldRecord,
    CreatorContractDraft,
    CreatorGuidance,
    CreatorProgressEnvelope,
    DuetAnswer,
    DuetApproval,
    DuetDecision,
    DuetDesignState,
    DuetIdentity,
    DuetMessageKind,
    DuetPolicy,
    DuetProvenance,
    FieldImpact,
    FrozenCreatorContract,
    FrozenWorkflowDesign,
    InformationRequest,
    WorkflowApproval,
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
    creation_spec_from_blueprint,
    workflow_spec_from_blueprint,
)
from agent.episode_contracts import (
    EpisodeCreationSpec,
    EpisodeCreatorStatusField,
    EpisodeMeasuredOutcome,
    EpisodeWorkflowDesignProjection,
    EpisodeWorkflowDesignResult,
    EpisodeWorkflowSpec,
    OpaqueId,
    Sha256Digest,
)
from method_loop.identities import EpisodeRef


_REQUIRED_CREATOR_FIELDS = (
    "goal",
    "unit",
    "result",
    "progress",
    "stopping",
    "execution_capability_names",
    "creator_contract",
    "deliverable",
    "safety_bounds",
)


class DuetProtocolError(RuntimeError):
    """The requested operation violates the typed Duet protocol."""


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
    return DuetPolicy(
        policy_id=OpaqueId(record["policy_id"]),
        capability_allowlist=tuple(record["capability_allowlist"]),
        minimum_method_credit=record["minimum_method_credit"],
        creator_proposal_bound=record["creator_proposal_bound"],
        maximum_creator_depth=record["maximum_creator_depth"],
    )


def _field_from_record(record: Mapping[str, Any]) -> ContractFieldRecord:
    return ContractFieldRecord(
        field_path=record["field_path"],
        value=record["value"],
        provenance=DuetProvenance(record["provenance"]),
        source_ids=tuple(OpaqueId(item) for item in record["source_ids"]),
        validation_codes=tuple(record["validation_codes"]),
        approved=record["approved"],
        impact=FieldImpact(record["impact"]),
    )


def _deficit_from_record(record: Mapping[str, Any]) -> ContractDeficit:
    return ContractDeficit(
        code=record["code"],
        field_path=record["field_path"],
        blocking=record["blocking"],
    )


def _draft_from_record(record: Mapping[str, Any]) -> CreatorContractDraft:
    return CreatorContractDraft(
        draft_id=OpaqueId(record["draft_id"]),
        duet_id=OpaqueId(record["duet_id"]),
        revision=record["revision"],
        fields=tuple(_field_from_record(item) for item in record["fields"]),
        deficits=tuple(_deficit_from_record(item) for item in record["deficits"]),
    )


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


def _frozen_from_artifact(record: Mapping[str, Any]) -> FrozenCreatorContract:
    return FrozenCreatorContract(
        artifact_id=OpaqueId(record["artifact_id"]),
        duet_id=OpaqueId(record["duet_id"]),
        draft_id=OpaqueId(record["draft_id"]),
        revision=record["revision"],
        content_hash=Sha256Digest(record["content_hash"]),
        contract=EpisodeCreationSpec.from_record(record["contract"]),
    )


def _path_for_error(message: str) -> str:
    for path in _REQUIRED_CREATOR_FIELDS:
        if path in message:
            return path
    if "credit" in message or "evidence" in message or "return_contract" in message:
        return "creator_contract"
    if "capability" in message:
        return "execution_capability_names"
    return "goal"


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

    def open_duet(
        self,
        identity: DuetIdentity,
        policy: DuetPolicy,
        *,
        initial_fields: tuple[ContractFieldRecord, ...] = (),
    ) -> CreatorContractDraft:
        if identity.policy_id != policy.policy_id:
            raise ValueError("Duet identity and policy IDs differ")
        self.store.create_duet(
            duet_id=identity.duet_id.value,
            identity=identity.as_record(),
            policy=policy.as_record(),
            state=DuetDesignState.COLLECTING_CONTRACT.value,
        )
        existing = self.store.latest_draft(identity.duet_id.value)
        if existing is not None:
            return _draft_from_record(existing)
        return self._write_revision(
            identity.duet_id,
            prior=None,
            fields=initial_fields,
            provenance=DuetProvenance.HUMAN_INPUT,
        )

    def _duet_row(self, duet_id: OpaqueId) -> dict[str, Any]:
        row = self.store.get_duet(duet_id.value)
        if row is None:
            raise DuetNotFoundError("unknown Duet")
        return row

    def policy(self, duet_id: OpaqueId) -> DuetPolicy:
        return _policy_from_record(self._duet_row(duet_id)["policy"])

    def latest_draft(self, duet_id: OpaqueId) -> CreatorContractDraft:
        record = self.store.latest_draft(duet_id.value)
        if record is None:
            raise DuetNotFoundError("Duet has no Creator contract draft")
        return _draft_from_record(record)

    def _materialize_contract(
        self,
        fields: tuple[ContractFieldRecord, ...],
    ) -> tuple[Optional[EpisodeCreationSpec], tuple[ContractDeficit, ...]]:
        draft = CreatorContractDraft(
            draft_id=OpaqueId.mint("draft", "validation"),
            duet_id=OpaqueId.mint("duet", "validation"),
            revision=0,
            fields=fields,
        )
        try:
            record = draft.materialized()
        except ValueError:
            return None, (
                ContractDeficit("overlapping_paths", "goal"),
            )
        deficits = [
            ContractDeficit("required", field_path)
            for field_path in _REQUIRED_CREATOR_FIELDS
            if field_path not in record
        ]
        if deficits:
            return None, tuple(deficits)
        try:
            spec = creation_spec_from_blueprint(
                record,
                identity_namespace="duet-creator-contract",
            )
        except (TypeError, ValueError) as exc:
            return None, (
                ContractDeficit(
                    "invalid_contract",
                    _path_for_error(str(exc)),
                ),
            )
        task_caps = set(spec.execution_capability_names)
        assignable = set(spec.creator_contract.assignable_capability_names)
        unknown = (task_caps | assignable) - self.allowed_episode_capabilities
        if unknown:
            return None, (
                ContractDeficit("capability_not_allowed", "execution_capability_names"),
            )
        return spec, ()

    def _write_revision(
        self,
        duet_id: OpaqueId,
        *,
        prior: Optional[CreatorContractDraft],
        fields: tuple[ContractFieldRecord, ...],
        provenance: DuetProvenance,
    ) -> CreatorContractDraft:
        _, deficits = self._materialize_contract(fields)
        revision = 0 if prior is None else prior.revision + 1
        draft_id = (
            OpaqueId.mint("draft", f"{duet_id.value}:creator-contract")
            if prior is None
            else prior.draft_id
        )
        draft = CreatorContractDraft(
            draft_id=draft_id,
            duet_id=duet_id,
            revision=revision,
            fields=tuple(sorted(fields, key=lambda item: item.field_path)),
            deficits=deficits,
        )
        self.store.put_draft(
            duet_id=duet_id.value,
            draft_id=draft.draft_id.value,
            revision=draft.revision,
            content_hash=draft.content_hash.value,
            ready=draft.ready,
            record=draft.as_record(),
            expected_previous_revision=None if prior is None else prior.revision,
        )
        state = (
            DuetDesignState.CONTRACT_CANDIDATE
            if draft.ready
            else DuetDesignState.NEEDS_DUET_INPUT
        )
        self.store.set_state(duet_id.value, state.value)
        self.store.append_event(
            duet_id=duet_id.value,
            event_type="creator_contract_revision",
            provenance=provenance.value,
            record={
                "draft_id": draft.draft_id.value,
                "revision": draft.revision,
                "content_hash": draft.content_hash.value,
                "deficit_codes": [item.code for item in draft.deficits],
            },
        )
        return draft

    def patch_contract(
        self,
        duet_id: OpaqueId,
        *,
        expected_revision: int,
        patches: tuple[ContractFieldRecord, ...],
        actor: DuetProvenance,
    ) -> CreatorContractDraft:
        if actor not in {DuetProvenance.HUMAN_INPUT, DuetProvenance.LLM_PROPOSAL}:
            raise ValueError("only human input or LLM proposals may patch a draft")
        prior = self.latest_draft(duet_id)
        if prior.revision != expected_revision:
            raise DuetConflictError("Creator contract draft revision is stale")
        if any(item.provenance is not actor for item in patches):
            raise ValueError("patch provenance must match the authenticated actor")
        by_path = {item.field_path: item for item in prior.fields}
        for patch in patches:
            existing = by_path.get(patch.field_path)
            if (
                actor is DuetProvenance.LLM_PROPOSAL
                and existing is not None
                and existing.human_fixed
                and existing.value != patch.value
            ):
                raise DuetProtocolError(
                    f"LLM proposal cannot replace human-fixed field {patch.field_path}"
                )
            by_path[patch.field_path] = patch
        return self._write_revision(
            duet_id,
            prior=prior,
            fields=tuple(by_path.values()),
            provenance=actor,
        )

    def replace_contract(
        self,
        duet_id: OpaqueId,
        *,
        expected_revision: int,
        fields: tuple[ContractFieldRecord, ...],
    ) -> CreatorContractDraft:
        """Replace a mutable draft with one exact human-authored field set."""

        prior = self.latest_draft(duet_id)
        if prior.revision != expected_revision:
            raise DuetConflictError("Creator contract draft revision is stale")
        if any(item.provenance is not DuetProvenance.HUMAN_INPUT for item in fields):
            raise ValueError("direct draft replacement requires human provenance")
        return self._write_revision(
            duet_id,
            prior=prior,
            fields=fields,
            provenance=DuetProvenance.HUMAN_INPUT,
        )

    def information_requests(
        self, duet_id: OpaqueId
    ) -> tuple[InformationRequest, ...]:
        draft = self.latest_draft(duet_id)
        requests = []
        for deficit in draft.deficits:
            request_id = content_id(
                "request",
                {
                    "duet_id": duet_id.value,
                    "revision": draft.revision,
                    "field_path": deficit.field_path,
                    "code": deficit.code,
                },
            )
            requests.append(
                InformationRequest(
                    request_id=request_id,
                    duet_id=duet_id,
                    revision=draft.revision,
                    field_path=deficit.field_path,
                    reason_code=deficit.code,
                    answer_schema={"type": "object"},
                    blocking=deficit.blocking,
                )
            )
        return tuple(requests)

    def record_human_answer(
        self,
        identity: DuetIdentity,
        *,
        request_id: OpaqueId,
        value: Any,
    ) -> DuetAnswer:
        """Persist an answer from a trusted human UI without applying it yet."""

        if self._duet_row(identity.duet_id)["identity"] != identity.as_record():
            raise DuetProtocolError("human answer authority does not match the Duet")
        requests = {
            item.request_id: item for item in self.information_requests(identity.duet_id)
        }
        request = requests.get(request_id)
        if request is None:
            raise DuetNotFoundError("information request is stale or unknown")
        answer_id = content_id(
            "answer",
            {
                "request_id": request_id.value,
                "duet_id": identity.duet_id.value,
                "revision": request.revision,
                "field_path": request.field_path,
                "value": value,
                "human_authority_id": identity.human_authority_id.value,
            },
        )
        answer = DuetAnswer(
            answer_id=answer_id,
            request_id=request_id,
            duet_id=identity.duet_id,
            revision=request.revision,
            field_path=request.field_path,
            value=value,
            human_authority_id=identity.human_authority_id,
        )
        self.store.put_artifact(
            artifact_id=answer_id.value,
            duet_id=identity.duet_id.value,
            kind="duet_answer",
            revision=request.revision,
            content_hash=Sha256Digest.of_record(answer.as_record()).value,
            record=answer.as_record(),
        )
        return answer

    def submit_duet_answer(self, answer_artifact_id: OpaqueId) -> CreatorContractDraft:
        """Apply one exact host-recorded human answer; no answer prose is accepted."""

        artifact = self.store.get_artifact(answer_artifact_id.value)
        if artifact is None or artifact["kind"] != "duet_answer":
            raise DuetNotFoundError("human answer artifact not found")
        record = artifact["record"]
        answer = DuetAnswer(
            answer_id=OpaqueId(record["answer_id"]),
            request_id=OpaqueId(record["request_id"]),
            duet_id=OpaqueId(record["duet_id"]),
            revision=record["revision"],
            field_path=record["field_path"],
            value=record["value"],
            human_authority_id=OpaqueId(record["human_authority_id"]),
        )
        return self.patch_contract(
            answer.duet_id,
            expected_revision=answer.revision,
            patches=(
                ContractFieldRecord(
                    field_path=answer.field_path,
                    value=answer.value,
                    provenance=DuetProvenance.HUMAN_INPUT,
                    source_ids=(answer.answer_id,),
                    approved=True,
                ),
            ),
            actor=DuetProvenance.HUMAN_INPUT,
        )

    def freeze_creator_contract(
        self,
        duet_id: OpaqueId,
        *,
        expected_revision: int,
    ) -> FrozenCreatorContract:
        draft = self.latest_draft(duet_id)
        if draft.revision != expected_revision:
            raise DuetConflictError("cannot freeze a stale draft revision")
        spec, deficits = self._materialize_contract(draft.fields)
        if spec is None or deficits:
            raise DuetProtocolError("Creator contract is not complete and valid")
        artifact_id = content_id(
            "contract",
            {
                "duet_id": duet_id.value,
                "draft_id": draft.draft_id.value,
                "revision": draft.revision,
                "contract": spec.as_record(),
            },
        )
        frozen = FrozenCreatorContract(
            artifact_id=artifact_id,
            duet_id=duet_id,
            draft_id=draft.draft_id,
            revision=draft.revision,
            content_hash=spec.spec_hash,
            contract=spec,
        )
        self.store.put_artifact(
            artifact_id=artifact_id.value,
            duet_id=duet_id.value,
            kind=ApprovalKind.CREATOR_CONTRACT.value,
            revision=draft.revision,
            content_hash=frozen.content_hash.value,
            record=frozen.as_record(),
        )
        self.store.set_state(
            duet_id.value, DuetDesignState.AWAITING_CREATOR_APPROVAL.value
        )
        return frozen

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

    def submit_episode_creator(
        self,
        *,
        contract_artifact_id: OpaqueId,
        content_hash: Sha256Digest,
        human_approval_id: OpaqueId,
    ) -> OpaqueId:
        """The LLM's final call: identifiers only, followed by host reload."""

        artifact = self.store.get_artifact(contract_artifact_id.value)
        if artifact is None or artifact["kind"] != ApprovalKind.CREATOR_CONTRACT.value:
            raise DuetNotFoundError("frozen Creator contract artifact not found")
        frozen = _frozen_from_artifact(artifact["record"])
        if frozen.content_hash != content_hash:
            raise StaleDuetApprovalError("submitted Creator contract hash is stale")
        latest_draft = self.latest_draft(frozen.duet_id)
        if latest_draft.revision != frozen.revision:
            raise StaleDuetApprovalError(
                "Creator contract approval was invalidated by a later draft revision"
            )
        approval = self._require_exact_approval(
            approval_id=human_approval_id,
            kind=ApprovalKind.CREATOR_CONTRACT,
            artifact_id=frozen.artifact_id,
            content_hash=frozen.content_hash,
            revision=frozen.revision,
        )
        creator_episode_id = content_id(
            "episode",
            {
                "duet_id": frozen.duet_id.value,
                "contract_artifact_id": frozen.artifact_id.value,
                "contract_hash": frozen.content_hash.value,
            },
        )
        self.store.admit_creator(
            creator_episode_id=creator_episode_id.value,
            duet_id=frozen.duet_id.value,
            contract_artifact_id=frozen.artifact_id.value,
            contract_hash=frozen.content_hash.value,
            approval_id=approval.approval_id.value,
            state=DuetDesignState.CREATOR_ADMITTED.value,
        )
        self.store.set_state(
            frozen.duet_id.value, DuetDesignState.CREATOR_ADMITTED.value
        )
        return creator_episode_id

    def admit_nested_creator(
        self,
        *,
        parent_creator_episode_id: OpaqueId,
        workflow_design_artifact_id: OpaqueId,
        node_local_id: str,
    ) -> OpaqueId:
        """Admit one Creator node through its exact parent design authority."""

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
        nodes = {
            item.local_id: item
            for item in workflow.episodes
            if item.local_id == node_local_id
        }
        if len(nodes) != 1:
            raise DuetNotFoundError("nested Creator node is absent from the design")
        contract = nodes[node_local_id].contract
        if not contract.can_create_episodes or contract.creator_contract is None:
            raise DuetProtocolError("selected workflow node is not a Creator")
        contract_artifact_id = content_id(
            "contract",
            {
                "duet_id": parent["duet_id"],
                "parent_creator_episode_id": parent_creator_episode_id.value,
                "workflow_design_artifact_id": workflow_design_artifact_id.value,
                "node_local_id": node_local_id,
                "contract": contract.as_record(),
            },
        )
        frozen = FrozenCreatorContract(
            artifact_id=contract_artifact_id,
            duet_id=OpaqueId(parent["duet_id"]),
            draft_id=content_id(
                "draft",
                {
                    "workflow_design_artifact_id": workflow_design_artifact_id.value,
                    "node_local_id": node_local_id,
                },
            ),
            revision=artifact["revision"],
            content_hash=contract.spec_hash,
            contract=contract,
        )
        creator_episode_id = content_id(
            "episode",
            {
                "duet_id": parent["duet_id"],
                "parent_creator_episode_id": parent_creator_episode_id.value,
                "workflow_design_artifact_id": workflow_design_artifact_id.value,
                "node_local_id": node_local_id,
                "contract_hash": frozen.content_hash.value,
            },
        )
        self.store.put_artifact(
            artifact_id=frozen.artifact_id.value,
            duet_id=parent["duet_id"],
            creator_episode_id=creator_episode_id.value,
            kind="nested_creator_contract",
            revision=frozen.revision,
            content_hash=frozen.content_hash.value,
            record=frozen.as_record(),
        )
        self.store.admit_creator(
            creator_episode_id=creator_episode_id.value,
            duet_id=parent["duet_id"],
            contract_artifact_id=frozen.artifact_id.value,
            contract_hash=frozen.content_hash.value,
            approval_id=parent["approval_id"],
            parent_creator_episode_id=parent_creator_episode_id.value,
            design_artifact_id=workflow_design_artifact_id.value,
            state=DuetDesignState.CREATOR_ADMITTED.value,
        )
        self.store.append_event(
            duet_id=parent["duet_id"],
            event_type="nested_creator_admitted",
            provenance=DuetProvenance.HOST_VALIDATION.value,
            record={
                "creator_episode_id": creator_episode_id.value,
                "parent_creator_episode_id": parent_creator_episode_id.value,
                "workflow_design_artifact_id": workflow_design_artifact_id.value,
                "node_local_id": node_local_id,
                "contract_hash": frozen.content_hash.value,
            },
        )
        return creator_episode_id

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
    ) -> FrozenCreatorContract:
        creator = self.store.get_creator(creator_episode_id.value)
        if creator is None:
            raise DuetNotFoundError("unknown Creator Episode")
        artifact = self.store.get_artifact(creator["contract_artifact_id"])
        if artifact is None:
            raise DuetNotFoundError("Creator contract artifact is missing")
        return _frozen_from_artifact(artifact["record"])

    def creator_contract(
        self, creator_episode_id: OpaqueId
    ) -> FrozenCreatorContract:
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
        deficits: list[ContractDeficit] = []
        roots = [
            item for item in workflow.episodes
            if item.workflow_parent_local_id is None
        ]
        if len(roots) != 1:
            deficits.append(ContractDeficit("single_root_required", "goal"))
        allowed = set(creator.assignable_capability_names)
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
                if not creator.may_assign_creator_capability:
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
        policy = self.policy(frozen.duet_id)
        depths = self._workflow_depths(workflow)
        authority_depth = self._creator_authority_depth(creator_episode_id)
        creator_depth = max(
            (
                authority_depth + depths[item.local_id] + 1
                for item in workflow.episodes
                if item.contract.can_create_episodes
            ),
            default=authority_depth,
        )
        if creator_depth > policy.maximum_creator_depth:
            deficits.append(
                ContractDeficit("creator_depth_exceeded", "creator_contract")
            )
        max_depth = (
            None
            if frozen.contract.safety_bounds is None
            else frozen.contract.safety_bounds.max_depth
        )
        if max_depth is not None and depths and max(depths.values()) + 1 > max_depth:
            deficits.append(ContractDeficit("workflow_depth_exceeded", "safety_bounds"))
        unique = {
            (item.code, item.field_path, item.blocking): item for item in deficits
        }
        return tuple(unique[key] for key in sorted(unique))

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

    def freeze_workflow_design(
        self,
        *,
        creator_episode_id: OpaqueId,
        workflow_blueprint: Mapping[str, Any],
    ) -> FrozenWorkflowDesign:
        """Translate, admit, and freeze one design before its Run Episode."""

        frozen_creator = self._creator_frozen_contract(creator_episode_id)
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
            },
        )
        design = FrozenWorkflowDesign(
            artifact_id=artifact_id,
            duet_id=frozen_creator.duet_id,
            creator_episode_id=creator_episode_id,
            revision=revision,
            workflow_hash=workflow.workflow_hash,
            workflow=workflow,
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
        self.store.set_state(
            frozen.duet_id.value,
            DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value,
        )
        return candidate

    def approve_workflow(
        self,
        identity: DuetIdentity,
        candidate: WorkflowCandidate,
    ) -> WorkflowApproval:
        if candidate.duet_id != identity.duet_id:
            raise DuetProtocolError("workflow candidate belongs to another Duet")
        policy = self.policy(identity.duet_id)
        if candidate.projection.method_credit < policy.minimum_method_credit:
            raise WorkflowAdmissionError(
                (ContractDeficit("credit_below_threshold", "creator_contract"),)
            )
        approval = self.record_human_approval(
            identity,
            kind=ApprovalKind.WORKFLOW,
            artifact_id=candidate.artifact_id,
            content_hash=candidate.workflow_hash,
            revision=candidate.revision,
        )
        return WorkflowApproval(approval)

    @staticmethod
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

    @staticmethod
    def _workflow_from_artifact(record: Mapping[str, Any]) -> EpisodeWorkflowSpec:
        return EpisodeWorkflowSpec.from_record(record["workflow"])

    def launch_workflow(
        self,
        *,
        workflow_artifact_id: OpaqueId,
        workflow_hash: Sha256Digest,
        workflow_approval_id: OpaqueId,
        run_id: str,
    ) -> OpaqueId:
        artifact = self.store.get_artifact(workflow_artifact_id.value)
        if artifact is None or artifact["kind"] != ApprovalKind.WORKFLOW.value:
            raise DuetNotFoundError("approved workflow artifact not found")
        record = artifact["record"]
        workflow = self._workflow_from_artifact(record)
        if workflow.workflow_hash != workflow_hash:
            raise StaleDuetApprovalError("workflow content hash is stale")
        latest = self.store.latest_artifact(
            duet_id=record["duet_id"],
            kind=ApprovalKind.WORKFLOW.value,
            creator_episode_id=record["creator_episode_id"],
        )
        if latest is None or latest["artifact_id"] != workflow_artifact_id.value:
            raise StaleDuetApprovalError(
                "workflow approval was invalidated by a later candidate revision"
            )
        approval = self._require_exact_approval(
            approval_id=workflow_approval_id,
            kind=ApprovalKind.WORKFLOW,
            artifact_id=workflow_artifact_id,
            content_hash=workflow_hash,
            revision=record["revision"],
        )
        creator_episode_id = OpaqueId(record["creator_episode_id"])
        deficits = self.workflow_deficits(
            creator_episode_id=creator_episode_id,
            workflow=workflow,
        )
        if deficits:
            raise WorkflowAdmissionError(deficits)
        launch_id = content_id(
            "launch",
            {
                "workflow_artifact_id": workflow_artifact_id.value,
                "workflow_hash": workflow_hash.value,
                "approval_id": approval.approval_id.value,
                "run_id": run_id,
            },
        )
        by_id = {item.local_id: item for item in workflow.episodes}
        depths = self._workflow_depths(workflow)
        episode_ids: dict[str, OpaqueId] = {}
        ordered = sorted(workflow.episodes, key=lambda item: (depths[item.local_id], item.local_id))
        for item in ordered:
            parent = item.workflow_parent_local_id
            if parent is not None:
                # Reconstruct the structural path from local ancestry instead
                # of smuggling an authority root into Episode identity.
                ancestry = []
                cursor: Optional[str] = item.local_id
                while cursor is not None:
                    ancestry.append(cursor)
                    cursor = by_id[cursor].workflow_parent_local_id
                path = tuple(
                    (
                        "creator_episode"
                        if by_id[local_id].contract.can_create_episodes
                        else "task_episode",
                        local_id,
                    )
                    for local_id in reversed(ancestry)
                )
            else:
                path = (
                    (
                        "creator_episode"
                        if item.contract.can_create_episodes
                        else "task_episode",
                        item.local_id,
                    ),
                )
            episode_ids[item.local_id] = OpaqueId(
                EpisodeRef(run_id=run_id, path=path).episode_id
            )
        episode_records = tuple(
            {
                "episode_id": episode_ids[item.local_id].value,
                "designed_by_episode_id": creator_episode_id.value,
                "workflow_parent_episode_id": (
                    None
                    if item.workflow_parent_local_id is None
                    else episode_ids[item.workflow_parent_local_id].value
                ),
                "local_id": item.local_id,
                "depth": depths[item.local_id],
                "contract_hash": item.contract.spec_hash.value,
                "contract": item.contract.as_record(),
            }
            for item in ordered
        )
        self.store.launch_workflow(
            launch_record={
                "launch_id": launch_id.value,
                "duet_id": record["duet_id"],
                "workflow_artifact_id": workflow_artifact_id.value,
                "workflow_hash": workflow_hash.value,
                "approval_id": workflow_approval_id.value,
                "run_id": run_id,
            },
            episode_records=episode_records,
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
        """Closed, prose-free status projection suitable for the Duet LLM."""

        row = self._duet_row(duet_id)
        draft = self.latest_draft(duet_id)
        requests = self.information_requests(duet_id)
        creator = self.store.latest_creator(duet_id.value)
        progress = None
        if creator is not None:
            latest = self.store.latest_artifact(
                duet_id=duet_id.value,
                kind="creator_progress",
                creator_episode_id=creator["creator_episode_id"],
            )
            if latest is not None:
                progress = latest["record"]
        creator_approval = self.store.latest_approval(
            duet_id=duet_id.value,
            kind=ApprovalKind.CREATOR_CONTRACT.value,
        )
        workflow_approval = self.store.latest_approval(
            duet_id=duet_id.value,
            kind=ApprovalKind.WORKFLOW.value,
        )
        launch = self.store.latest_launch(duet_id.value)
        return {
            "duet_id": duet_id.value,
            "state": row["state"],
            "draft_id": draft.draft_id.value,
            "revision": draft.revision,
            "ready": draft.ready,
            "content_hash": draft.content_hash.value,
            "deficit_codes": [item.code for item in draft.deficits],
            "requested_field_ids": [item.field_path for item in requests],
            "creator_episode_id": (
                None if creator is None else creator["creator_episode_id"]
            ),
            "creator_progress": progress,
            "creator_contract_approval": creator_approval,
            "workflow_approval": workflow_approval,
            "launch": launch,
            "allowed_episode_capability_names": sorted(
                self.allowed_episode_capabilities
            ),
        }


__all__ = [
    "DuetProtocolError",
    "DuetService",
    "StaleDuetApprovalError",
    "WorkflowAdmissionError",
]
