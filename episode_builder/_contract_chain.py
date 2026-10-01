"""Correlated authority, plan, admission, and manifest contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Any, Mapping, Optional

from agent.duet_contracts import (
    ApprovalKind,
    DuetApproval,
    FrozenDuetWorkflow,
    WorkflowAdmissionAuthority,
    content_id,
)
from agent.episode_contracts import OpaqueId, Sha256Digest
from iterative_episode_refiner.contracts import (
    DuetWorkspaceNote,
    RefinementBaseline,
    RefinementChangeKind,
    RefinementDecision,
    RefinementProposal,
    RefinementTargetLayer,
    is_implementation_directive_target,
)

from ._contract_base import (
    _DEFINITION_ID,
    _DOTTED_NAME,
    _EPISODE_ID,
    BuildAttempt,
    BuildDeficit,
    BuildReceipt,
    _array,
    _local_id,
    _record,
    _text,
    _tuple_of_strings,
)
from ._contract_plan import EdgeMaterializationPlan, NodeMaterializationPlan


_NODE_DISPOSITIONS = frozenset({"full", "directive", "unchanged"})


def _approval_from_record(value: object) -> DuetApproval:
    if not isinstance(value, Mapping):
        raise ValueError("Duet approval must be an object")
    return DuetApproval.from_record(value)


def _approval_identity(approval: DuetApproval) -> OpaqueId:
    return content_id(
        "approval",
        {
            "duet_id": approval.duet_id.value,
            "human_authority_id": approval.human_authority_id.value,
            "kind": approval.kind.value,
            "artifact_id": approval.artifact_id.value,
            "content_hash": approval.content_hash.value,
            "revision": approval.revision,
            "predecessor_approval_id": (
                None
                if approval.predecessor_approval_id is None
                else approval.predecessor_approval_id.value
            ),
        },
    )


def _frozen_workflow_identity(frozen: FrozenDuetWorkflow) -> OpaqueId:
    return content_id(
        "workflow",
        {
            "duet_id": frozen.duet_id.value,
            "source_draft_artifact_id": frozen.source_draft_artifact_id.value,
            "source_draft_hash": frozen.source_draft_hash.value,
            "revision": frozen.revision,
            "workflow_hash": frozen.workflow_hash.value,
            "admission_authority_id": frozen.admission_authority_id.value,
            "admission_authority_hash": frozen.admission_authority_hash.value,
            "refinement_decision_id": (
                None
                if frozen.refinement_decision_id is None
                else frozen.refinement_decision_id.value
            ),
            "refinement_decision_hash": (
                None
                if frozen.refinement_decision_hash is None
                else frozen.refinement_decision_hash.value
            ),
        },
    )


def _record_hash(value: object) -> Sha256Digest:
    if not hasattr(value, "as_record"):
        raise TypeError("content-addressed value must provide as_record()")
    return Sha256Digest.of_record(value.as_record())


@dataclass(frozen=True)
class ApprovedBuildRequest:
    """The complete current authority chain for one successor build.

    Initial requests contain only the workflow authority records.  A successor
    request additionally carries the exact approved refinement decision, its
    baseline/proposal/human-note evidence, the predecessor receipt, and any
    correlated predecessor manifest.  This
    makes an implementation-preserving approval a different request even when
    the normalized workflow is byte-for-byte unchanged.
    """

    authority_approval: DuetApproval
    workflow_approval: DuetApproval
    frozen_workflow: FrozenDuetWorkflow
    admission_authority: WorkflowAdmissionAuthority
    request_nonce: str
    refinement_decision: Optional[RefinementDecision] = None
    refinement_baseline: Optional[RefinementBaseline] = None
    refinement_proposal: Optional[RefinementProposal] = None
    refinement_notes: tuple[DuetWorkspaceNote, ...] = ()
    predecessor_receipt: Optional["BuildReceipt"] = None
    predecessor_manifest: Optional["BuildManifest"] = None
    build_request_id: OpaqueId = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.authority_approval, DuetApproval):
            raise TypeError("authority_approval must be a DuetApproval")
        if not isinstance(self.workflow_approval, DuetApproval):
            raise TypeError("workflow_approval must be a DuetApproval")
        if not isinstance(self.frozen_workflow, FrozenDuetWorkflow):
            raise TypeError("frozen_workflow must be a FrozenDuetWorkflow")
        if not isinstance(self.admission_authority, WorkflowAdmissionAuthority):
            raise TypeError(
                "admission_authority must be a WorkflowAdmissionAuthority"
            )
        object.__setattr__(
            self,
            "request_nonce",
            _text(self.request_nonce, "build request nonce", maximum=256),
        )
        authority_approval = self.authority_approval
        workflow_approval = self.workflow_approval
        frozen = self.frozen_workflow
        authority = self.admission_authority
        if workflow_approval.kind is not ApprovalKind.WORKFLOW:
            raise ValueError("workflow_approval must authorize a workflow")
        if not (
            authority_approval.duet_id
            == workflow_approval.duet_id
            == frozen.duet_id
            == authority.duet_id
        ):
            raise ValueError("build request records must name the same Duet")
        if authority_approval.human_authority_id != workflow_approval.human_authority_id:
            raise ValueError("build request approvals have different human authority")
        if workflow_approval.artifact_id != frozen.artifact_id:
            raise ValueError("workflow approval does not name the frozen workflow")
        if workflow_approval.content_hash != frozen.workflow_hash:
            raise ValueError("workflow approval hash does not match the workflow")
        if workflow_approval.revision != frozen.revision:
            raise ValueError("workflow approval revision does not match the workflow")
        if frozen.admission_authority_id != authority.authority_id:
            raise ValueError("frozen workflow names a different admission authority")
        if frozen.admission_authority_hash != authority.content_hash:
            raise ValueError("frozen workflow authority hash is stale")
        if frozen.artifact_id != _frozen_workflow_identity(frozen):
            raise ValueError("frozen workflow artifact identity is stale")
        for approval in (authority_approval, workflow_approval):
            if approval.approval_id != _approval_identity(approval):
                raise ValueError("approval identity is stale")
        roots = tuple(
            episode
            for episode in frozen.workflow.episodes
            if episode.workflow_parent_local_id is None
        )
        if len(roots) != 1:
            raise ValueError("an approved build request must have one root Episode")
        allowed = set(authority.assignable_capability_names)
        episodes_by_id = {
            episode.local_id: episode
            for episode in frozen.workflow.episodes
        }
        for episode in frozen.workflow.episodes:
            requested = set(episode.contract.execution_capability_names)
            if not requested.issubset(allowed):
                raise ValueError(
                    f"Episode {episode.local_id!r} exceeds its capability authority"
                )
            parent_id = episode.workflow_parent_local_id
            if parent_id is not None and not requested.issubset(
                episodes_by_id[
                    parent_id
                ].contract.execution_capability_names
            ):
                raise ValueError(
                    f"Episode {episode.local_id!r} exceeds inherited parent "
                    "capabilities"
                )
            deliverable_tools = set(episode.contract.deliverable.tool_names)
            if not deliverable_tools.issubset(requested):
                raise ValueError(
                    f"Episode {episode.local_id!r} requires deliverable tools "
                    "outside its execution capabilities"
                )
        decision = self.refinement_decision
        related = (
            self.refinement_baseline,
            self.refinement_proposal,
            self.predecessor_receipt,
            self.predecessor_manifest,
        )
        if decision is None:
            if any(item is not None for item in related) or self.refinement_notes:
                raise ValueError("an initial request cannot carry refinement artifacts")
            if authority_approval != workflow_approval:
                raise ValueError("initial authority head must be the workflow approval")
            if frozen.refinement_decision_id is not None:
                raise ValueError("a refined workflow requires its approved decision")
        else:
            if not isinstance(decision, RefinementDecision):
                raise TypeError("refinement_decision must be a RefinementDecision")
            baseline = self.refinement_baseline
            proposal = self.refinement_proposal
            predecessor_receipt = self.predecessor_receipt
            predecessor = self.predecessor_manifest
            if not isinstance(baseline, RefinementBaseline):
                raise ValueError("a refinement request requires its baseline")
            if not isinstance(proposal, RefinementProposal):
                raise ValueError("a refinement request requires its proposal")
            if not isinstance(predecessor_receipt, BuildReceipt):
                raise ValueError("a refinement request requires its predecessor receipt")
            if decision.duet_id != frozen.duet_id or baseline.duet_id != frozen.duet_id:
                raise ValueError("refinement records belong to another Duet")
            if decision.baseline_id != baseline.baseline_id:
                raise ValueError("refinement decision names another baseline")
            if (
                decision.proposal_id != proposal.proposal_id
                or decision.proposal_hash != proposal.content_hash
                or proposal.baseline_id != baseline.baseline_id
                or proposal.duet_id != frozen.duet_id
            ):
                raise ValueError("refinement decision and proposal linkage is stale")
            if decision.implementation_directive_ids != tuple(
                item.directive_id for item in proposal.implementation_directives
            ):
                raise ValueError("decision does not name the proposal directives exactly")
            if not isinstance(self.refinement_notes, tuple) or any(
                not isinstance(item, DuetWorkspaceNote)
                for item in self.refinement_notes
            ):
                raise TypeError(
                    "refinement_notes must contain DuetWorkspaceNote values"
                )
            notes_by_id = {item.note_id: item for item in self.refinement_notes}
            if len(notes_by_id) != len(self.refinement_notes) or set(notes_by_id) != set(
                proposal.note_ids
            ):
                raise ValueError("refinement notes must exactly cover proposal note IDs")
            ordered_notes = tuple(notes_by_id[note_id] for note_id in proposal.note_ids)
            for note in ordered_notes:
                if note.duet_id != frozen.duet_id or note.baseline_id != baseline.baseline_id:
                    raise ValueError("refinement note belongs to another baseline")
                if note.human_authority_id != authority_approval.human_authority_id:
                    raise ValueError("refinement note belongs to another human authority")
            object.__setattr__(self, "refinement_notes", ordered_notes)
            if (
                predecessor_receipt.receipt_id != baseline.build_receipt_id
                or predecessor_receipt.content_hash != baseline.build_receipt_hash
                or predecessor_receipt.build_request_id != baseline.build_request_id
                or predecessor_receipt.build_attempt_id != baseline.build_attempt_id
            ):
                raise ValueError("predecessor receipt does not match the baseline")
            if (predecessor is None) != (baseline.build_manifest_id is None):
                raise ValueError(
                    "predecessor manifest evidence must match the baseline"
                )
            if predecessor is not None:
                if not isinstance(predecessor, BuildManifest):
                    raise TypeError("predecessor_manifest must be a BuildManifest")
                predecessor_hash = _record_hash(predecessor)
                if (
                    predecessor.manifest_id != baseline.build_manifest_id
                    or predecessor_hash != baseline.build_manifest_hash
                    or predecessor_receipt.manifest_id != predecessor.manifest_id
                    or predecessor.build_request_id != baseline.build_request_id
                    or predecessor.build_attempt_id != baseline.build_attempt_id
                    or predecessor_receipt.plan_id != predecessor.plan_id
                    or predecessor_receipt.admission_report_id
                    != predecessor.admission_report_id
                    or predecessor.workflow_hash != baseline.workflow_hash
                ):
                    raise ValueError("predecessor manifest does not match the baseline")
            if (
                baseline.workflow_hash != decision.baseline_workflow_hash
                or predecessor_receipt.receipt_id != baseline.build_receipt_id
            ):
                raise ValueError("refinement baseline hashes are stale")
            for directive in proposal.implementation_directives:
                target = directive.target
                if (
                    target.layer
                    is not RefinementTargetLayer.MATERIALIZATION_IMPLEMENTATION
                    or target.artifact_id
                    != baseline.materialized_specification_id
                    or target.artifact_hash
                    != baseline.materialized_specification_hash
                ):
                    raise ValueError(
                        "implementation directive target is not the predecessor "
                        "Materialized Specification"
                    )
                if not is_implementation_directive_target(target):
                    raise ValueError(
                        "implementation directive does not target an executable "
                        "Materialized Specification scope"
                    )
                if (
                    target.episode_local_id is not None
                    and target.episode_local_id not in episodes_by_id
                ):
                    raise ValueError(
                        "implementation directive names an unknown Episode"
                    )
            for note in ordered_notes:
                target = note.target
                if target.layer is RefinementTargetLayer.WORKFLOW_SEMANTICS:
                    if (
                        target.artifact_id != baseline.frozen_workflow_artifact_id
                        or target.artifact_hash != baseline.workflow_hash
                    ):
                        raise ValueError("workflow note target is not the baseline")
                elif (
                    target.artifact_id
                    != baseline.materialized_specification_id
                    or target.artifact_hash
                    != baseline.materialized_specification_hash
                ):
                    raise ValueError(
                        "implementation note target is not the predecessor "
                        "Materialized Specification"
                    )
            if decision.kind is RefinementChangeKind.DESIGN_SEMANTIC:
                if authority_approval != workflow_approval:
                    raise ValueError("semantic successor authority must be its workflow approval")
                if (
                    frozen.refinement_decision_id != decision.decision_id
                    or frozen.refinement_decision_hash != decision.content_hash
                    or decision.result_workflow_hash != frozen.workflow_hash
                    or baseline.authority_head_approval_id
                    != workflow_approval.predecessor_approval_id
                ):
                    raise ValueError("semantic successor authority linkage is stale")
            else:
                if authority_approval.kind is not ApprovalKind.REFINEMENT:
                    raise ValueError("implementation successor needs refinement authority")
                if (
                    authority_approval.artifact_id != decision.decision_id
                    or authority_approval.content_hash != decision.content_hash
                    or authority_approval.predecessor_approval_id
                    != baseline.authority_head_approval_id
                    or baseline.workflow_approval_id != workflow_approval.approval_id
                    or baseline.frozen_workflow_artifact_id != frozen.artifact_id
                    or baseline.workflow_hash != frozen.workflow_hash
                    or decision.result_workflow_hash != frozen.workflow_hash
                ):
                    raise ValueError("implementation successor authority linkage is stale")
        object.__setattr__(
            self,
            "build_request_id",
            content_id("build_request", self.semantic_record()),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "authority_approval": self.authority_approval.as_record(),
            "workflow_approval": self.workflow_approval.as_record(),
            "frozen_workflow": self.frozen_workflow.as_record(),
            "admission_authority": self.admission_authority.as_record(),
            "request_nonce": self.request_nonce,
            "refinement_decision": (
                None
                if self.refinement_decision is None
                else self.refinement_decision.as_record()
            ),
            "refinement_baseline": (
                None
                if self.refinement_baseline is None
                else self.refinement_baseline.as_record()
            ),
            "refinement_proposal": (
                None
                if self.refinement_proposal is None
                else self.refinement_proposal.as_record()
            ),
            "refinement_notes": [item.as_record() for item in self.refinement_notes],
            "predecessor_receipt": (
                None
                if self.predecessor_receipt is None
                else self.predecessor_receipt.as_record()
            ),
            "predecessor_manifest": (
                None
                if self.predecessor_manifest is None
                else self.predecessor_manifest.as_record()
            ),
        }

    def as_record(self) -> dict[str, Any]:
        return {
            "build_request_id": self.build_request_id.value,
            **self.semantic_record(),
        }

    @classmethod
    def from_record(cls, value: object) -> "ApprovedBuildRequest":
        record = _record(
            value,
            "approved build request",
            {
                "build_request_id",
                "authority_approval",
                "workflow_approval",
                "frozen_workflow",
                "admission_authority",
                "request_nonce",
                "refinement_decision",
                "refinement_baseline",
                "refinement_proposal",
                "refinement_notes",
                "predecessor_receipt",
                "predecessor_manifest",
            },
        )
        notes = _array(record["refinement_notes"], "refinement_notes")
        result = cls(
            authority_approval=_approval_from_record(record["authority_approval"]),
            workflow_approval=_approval_from_record(record["workflow_approval"]),
            frozen_workflow=FrozenDuetWorkflow.from_record(
                record["frozen_workflow"]
            ),
            admission_authority=WorkflowAdmissionAuthority.from_record(
                record["admission_authority"]
            ),
            request_nonce=record["request_nonce"],
            refinement_decision=(
                None
                if record["refinement_decision"] is None
                else RefinementDecision.from_record(record["refinement_decision"])
            ),
            refinement_baseline=(
                None
                if record["refinement_baseline"] is None
                else RefinementBaseline.from_record(record["refinement_baseline"])
            ),
            refinement_proposal=(
                None
                if record["refinement_proposal"] is None
                else RefinementProposal.from_record(record["refinement_proposal"])
            ),
            refinement_notes=tuple(
                DuetWorkspaceNote.from_record(item) for item in notes
            ),
            predecessor_receipt=(
                None
                if record["predecessor_receipt"] is None
                else BuildReceipt.from_record(record["predecessor_receipt"])
            ),
            predecessor_manifest=(
                None
                if record["predecessor_manifest"] is None
                else BuildManifest.from_record(record["predecessor_manifest"])
            ),
        )
        if result.build_request_id.value != record["build_request_id"]:
            raise ValueError("approved build request identity is stale")
        return result


def _node_disposition_map(
    value: object,
    name: str,
) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    result: dict[str, str] = {}
    for local_id in sorted(value):
        key = _local_id(local_id, f"{name} key")
        disposition = value[local_id]
        if disposition not in _NODE_DISPOSITIONS:
            raise ValueError(
                f"{name}.{key} must be one of {sorted(_NODE_DISPOSITIONS)!r}"
            )
        result[key] = disposition
    return MappingProxyType(result)


@dataclass(frozen=True)
class WorkflowMaterializationPlan:
    """A complete bottom-up implementation plan for one approved workflow."""

    build_request_id: OpaqueId
    build_attempt_id: OpaqueId
    workflow_hash: Sha256Digest
    root_local_id: str
    nodes: tuple[NodeMaterializationPlan, ...]
    edges: tuple[EdgeMaterializationPlan, ...]
    predecessor_plan_id: Optional[OpaqueId]
    node_dispositions: Mapping[str, str]
    deficits: tuple[BuildDeficit, ...] = ()
    plan_id: OpaqueId = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.build_request_id, OpaqueId):
            raise TypeError("build_request_id must be an OpaqueId")
        if not isinstance(self.build_attempt_id, OpaqueId):
            raise TypeError("build_attempt_id must be an OpaqueId")
        if self.predecessor_plan_id is not None and not isinstance(
            self.predecessor_plan_id,
            OpaqueId,
        ):
            raise TypeError("predecessor_plan_id must be an OpaqueId or None")
        if not isinstance(self.workflow_hash, Sha256Digest):
            object.__setattr__(
                self,
                "workflow_hash",
                Sha256Digest(self.workflow_hash),
            )
        object.__setattr__(
            self,
            "root_local_id",
            _local_id(self.root_local_id, "root_local_id"),
        )
        if not isinstance(self.nodes, tuple):
            raise ValueError("materialization plan nodes must be a tuple")
        if any(not isinstance(node, NodeMaterializationPlan) for node in self.nodes):
            raise TypeError("nodes must contain NodeMaterializationPlan values")
        if not isinstance(self.edges, tuple) or any(
            not isinstance(edge, EdgeMaterializationPlan) for edge in self.edges
        ):
            raise TypeError("edges must contain EdgeMaterializationPlan values")
        if not isinstance(self.deficits, tuple) or any(
            not isinstance(deficit, BuildDeficit) for deficit in self.deficits
        ):
            raise TypeError("deficits must contain BuildDeficit values")
        deficits = tuple(
            sorted(
                self.deficits,
                key=lambda item: (
                    item.episode_local_id or "",
                    item.field_path,
                    item.code,
                    item.detail,
                ),
            )
        )
        blocked = any(deficit.blocking for deficit in deficits)
        if not self.nodes and not blocked:
            raise ValueError("a ready materialization plan must contain nodes")
        nodes = tuple(sorted(self.nodes, key=lambda node: node.local_id))
        edges = tuple(
            sorted(
                self.edges,
                key=lambda edge: (
                    edge.parent_local_id,
                    edge.slot_name,
                    edge.child_local_id,
                ),
            )
        )
        node_by_id = {node.local_id: node for node in nodes}
        if len(node_by_id) != len(nodes):
            raise ValueError("materialization node local IDs must be unique")
        if self.root_local_id in node_by_id and node_by_id[
            self.root_local_id
        ].parent_local_id is not None:
            raise ValueError("the root materialization node cannot have a parent")
        if not blocked and self.root_local_id not in node_by_id:
            raise ValueError("root_local_id does not name a materialization node")
        if not blocked and sum(node.parent_local_id is None for node in nodes) != 1:
            raise ValueError("materialization plan must contain exactly one root")
        if not blocked and len(edges) != len(nodes) - 1:
            raise ValueError("materialization plan must contain one edge per non-root node")
        child_ids: set[str] = set()
        used_slots: set[tuple[str, str]] = set()
        slots_by_parent: dict[str, set[str]] = {}
        for edge in edges:
            parent = node_by_id.get(edge.parent_local_id)
            child = node_by_id.get(edge.child_local_id)
            if parent is None or child is None:
                raise ValueError("materialization edge names an unknown node")
            if child.parent_local_id != parent.local_id:
                raise ValueError("materialization edge differs from child parent linkage")
            if edge.child_interface != child.interface:
                raise ValueError("materialization edge child interface differs from its node")
            if edge.slot_name not in parent.child_slot_names:
                raise ValueError("materialization edge uses an undeclared parent slot")
            if edge.request_payload_contract != child.request_payload_contract:
                raise ValueError("edge request payload differs from the child admission contract")
            if edge.result_payload_contract != child.result_payload_contract:
                raise ValueError("edge result payload differs from the child result contract")
            if edge.child_local_id in child_ids:
                raise ValueError("a child materialization node must have one parent edge")
            slot_key = (edge.parent_local_id, edge.slot_name)
            if slot_key in used_slots:
                raise ValueError("a parent child slot may be materialized only once")
            child_ids.add(edge.child_local_id)
            used_slots.add(slot_key)
            slots_by_parent.setdefault(edge.parent_local_id, set()).add(edge.slot_name)
        expected_children = set(node_by_id) - {self.root_local_id}
        if not blocked and child_ids != expected_children:
            raise ValueError("every non-root materialization node needs one edge")
        for node in nodes:
            if not blocked and set(node.child_slot_names) != slots_by_parent.get(
                node.local_id,
                set(),
            ):
                raise ValueError("node child slots must exactly match its materialized edges")
        dispositions = _node_disposition_map(
            self.node_dispositions,
            "node_dispositions",
        )
        if not set(dispositions).issubset(node_by_id):
            raise ValueError("node dispositions contain an unplanned Episode")
        if not blocked and set(dispositions) != set(node_by_id):
            raise ValueError("a ready plan must classify every Episode node")
        if self.predecessor_plan_id is None:
            if any(value != "full" for value in dispositions.values()):
                raise ValueError("a full plan can only contain full dispositions")
        else:
            if any(value == "full" for value in dispositions.values()):
                raise ValueError("a successor plan cannot contain full dispositions")
            if not blocked and "directive" not in dispositions.values():
                raise ValueError("a successor plan must apply an approved directive")
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)
        object.__setattr__(self, "node_dispositions", dispositions)
        object.__setattr__(
            self,
            "deficits",
            deficits,
        )
        object.__setattr__(
            self,
            "plan_id",
            content_id("materialization_plan", self.semantic_record()),
        )

    @property
    def ready(self) -> bool:
        return not any(deficit.blocking for deficit in self.deficits)

    def semantic_record(self) -> dict[str, Any]:
        return {
            "build_request_id": self.build_request_id.value,
            "build_attempt_id": self.build_attempt_id.value,
            "workflow_hash": self.workflow_hash.value,
            "root_local_id": self.root_local_id,
            "nodes": [node.as_record() for node in self.nodes],
            "edges": [edge.as_record() for edge in self.edges],
            "predecessor_plan_id": (
                None
                if self.predecessor_plan_id is None
                else self.predecessor_plan_id.value
            ),
            "node_dispositions": dict(self.node_dispositions),
            "deficits": [deficit.as_record() for deficit in self.deficits],
        }

    def as_record(self) -> dict[str, Any]:
        return {"plan_id": self.plan_id.value, **self.semantic_record()}

    def validate_against(
        self,
        build_request: ApprovedBuildRequest,
        build_attempt: BuildAttempt,
    ) -> None:
        if not isinstance(build_request, ApprovedBuildRequest):
            raise TypeError("build_request must be an ApprovedBuildRequest")
        if not isinstance(build_attempt, BuildAttempt):
            raise TypeError("build_attempt must be a BuildAttempt")
        if (
            self.build_request_id != build_request.build_request_id
            or self.build_attempt_id != build_attempt.build_attempt_id
            or build_attempt.build_request_id != build_request.build_request_id
        ):
            raise ValueError("materialization plan names another request or attempt")
        workflow = build_request.frozen_workflow.workflow
        if self.workflow_hash != workflow.workflow_hash:
            raise ValueError("materialization plan names a different workflow hash")
        preserving = bool(
            build_request.refinement_decision is not None
            and build_request.refinement_decision.kind
            is RefinementChangeKind.IMPLEMENTATION_PRESERVING
        )
        expected_predecessor = (
            build_request.predecessor_manifest.plan_id
            if preserving and build_request.predecessor_manifest is not None
            else None
        )
        if self.predecessor_plan_id != expected_predecessor:
            raise ValueError("materialization plan predecessor linkage is stale")
        expected_roots = tuple(
            episode.local_id
            for episode in workflow.episodes
            if episode.workflow_parent_local_id is None
        )
        if expected_roots != (self.root_local_id,):
            raise ValueError("materialization plan changes the frozen root")
        designs = {episode.local_id: episode for episode in workflow.episodes}
        plans = {node.local_id: node for node in self.nodes}
        if not set(plans).issubset(designs):
            raise ValueError("materialization plan contains an unknown Duet Episode")
        if self.ready and set(designs) != set(plans):
            raise ValueError("a ready plan must cover every Duet Episode exactly")
        for local_id, node in plans.items():
            design = designs[local_id]
            if node.parent_local_id != design.workflow_parent_local_id:
                raise ValueError(f"node {local_id!r} changes the Duet topology")
            if node.contract_hash != design.contract.spec_hash:
                raise ValueError(f"node {local_id!r} changes the Duet contract")
            reference_id = (
                None
                if design.episode_reference is None
                else design.episode_reference.episode_id
            )
            if node.reference_episode_id != reference_id:
                raise ValueError(f"node {local_id!r} changes the Episode reference")
            if node.capability_names != design.contract.execution_capability_names:
                raise ValueError(f"node {local_id!r} changes assigned capabilities")
            bindings = {
                str(binding["role"]): binding
                for binding in node.as_record()["selected_function_bindings"]
            }
            numeric_selections = (
                (
                    "controller.rarefaction",
                    design.contract.numeric_control.rarefaction,
                ),
                (
                    "controller.continuation",
                    design.contract.numeric_control.continuation,
                ),
            )
            for role, selection in numeric_selections:
                binding = bindings.get(role)
                expected = {
                    "source": "library",
                    **selection.as_record(),
                }
                if binding is None or {
                    key: binding[key]
                    for key in expected
                } != expected:
                    raise ValueError(
                        f"node {local_id!r} changes the Architecture-owned "
                        f"{role} function or arguments"
                    )

    @classmethod
    def from_record(cls, value: object) -> "WorkflowMaterializationPlan":
        record = _record(
            value,
            "workflow materialization plan",
            {
                "plan_id",
                "build_request_id",
                "build_attempt_id",
                "workflow_hash",
                "root_local_id",
                "nodes",
                "edges",
                "predecessor_plan_id",
                "node_dispositions",
                "deficits",
            },
        )
        if not all(
            isinstance(record[name], list) for name in ("nodes", "edges", "deficits")
        ):
            raise ValueError("materialization plan collections must be arrays")
        result = cls(
            build_request_id=OpaqueId(record["build_request_id"]),
            build_attempt_id=OpaqueId(record["build_attempt_id"]),
            workflow_hash=Sha256Digest(record["workflow_hash"]),
            root_local_id=record["root_local_id"],
            nodes=tuple(NodeMaterializationPlan.from_record(item) for item in record["nodes"]),
            edges=tuple(EdgeMaterializationPlan.from_record(item) for item in record["edges"]),
            predecessor_plan_id=(
                None
                if record["predecessor_plan_id"] is None
                else OpaqueId(record["predecessor_plan_id"])
            ),
            node_dispositions=record["node_dispositions"],
            deficits=tuple(BuildDeficit.from_record(item) for item in record["deficits"]),
        )
        if result.plan_id.value != record["plan_id"]:
            raise ValueError("workflow materialization plan identity is stale")
        return result


@dataclass(frozen=True)
class BuildAdmissionReport:
    """Deterministic module-admission findings for one materialization plan."""

    build_request_id: OpaqueId
    build_attempt_id: OpaqueId
    plan_id: OpaqueId
    workflow_hash: Sha256Digest
    module_source_hashes: Mapping[str, Sha256Digest]
    deficits: tuple[BuildDeficit, ...]
    report_id: OpaqueId = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.build_request_id, OpaqueId):
            raise TypeError("build_request_id must be an OpaqueId")
        if not isinstance(self.build_attempt_id, OpaqueId):
            raise TypeError("build_attempt_id must be an OpaqueId")
        if not isinstance(self.plan_id, OpaqueId):
            raise TypeError("plan_id must be an OpaqueId")
        if not isinstance(self.workflow_hash, Sha256Digest):
            object.__setattr__(
                self,
                "workflow_hash",
                Sha256Digest(self.workflow_hash),
            )
        object.__setattr__(
            self,
            "module_source_hashes",
            _digest_map(
                self.module_source_hashes,
                "module_source_hashes",
                allow_empty=True,
            ),
        )
        if not isinstance(self.deficits, tuple) or any(
            not isinstance(deficit, BuildDeficit) for deficit in self.deficits
        ):
            raise TypeError("deficits must contain BuildDeficit values")
        object.__setattr__(
            self,
            "deficits",
            tuple(
                sorted(
                    self.deficits,
                    key=lambda item: (
                        item.episode_local_id or "",
                        item.field_path,
                        item.code,
                        item.detail,
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "report_id",
            content_id("admission_report", self.semantic_record()),
        )

    @property
    def admitted(self) -> bool:
        return not any(deficit.blocking for deficit in self.deficits)

    def semantic_record(self) -> dict[str, Any]:
        return {
            "build_request_id": self.build_request_id.value,
            "build_attempt_id": self.build_attempt_id.value,
            "plan_id": self.plan_id.value,
            "workflow_hash": self.workflow_hash.value,
            "module_source_hashes": {
                local_id: digest.value
                for local_id, digest in self.module_source_hashes.items()
            },
            "deficits": [deficit.as_record() for deficit in self.deficits],
        }

    def as_record(self) -> dict[str, Any]:
        return {"report_id": self.report_id.value, **self.semantic_record()}

    def validate_against(self, plan: WorkflowMaterializationPlan) -> None:
        if not isinstance(plan, WorkflowMaterializationPlan):
            raise TypeError("plan must be a WorkflowMaterializationPlan")
        if (
            self.build_request_id != plan.build_request_id
            or self.build_attempt_id != plan.build_attempt_id
            or self.plan_id != plan.plan_id
            or self.workflow_hash != plan.workflow_hash
        ):
            raise ValueError("admission report does not belong to its plan")
        planned_ids = {node.local_id for node in plan.nodes}
        if not set(self.module_source_hashes).issubset(planned_ids):
            raise ValueError("admission report contains an unplanned module")
        if self.admitted:
            if not plan.ready:
                raise ValueError("a blocked plan cannot have an admitted report")
            if set(self.module_source_hashes) != planned_ids:
                raise ValueError("an admitted report must cover every planned module")

    @classmethod
    def from_record(cls, value: object) -> "BuildAdmissionReport":
        record = _record(
            value,
            "build admission report",
            {
                "report_id",
                "build_request_id",
                "build_attempt_id",
                "plan_id",
                "workflow_hash",
                "module_source_hashes",
                "deficits",
            },
        )
        if not isinstance(record["deficits"], list):
            raise ValueError("build admission report deficits must be an array")
        result = cls(
            build_request_id=OpaqueId(record["build_request_id"]),
            build_attempt_id=OpaqueId(record["build_attempt_id"]),
            plan_id=OpaqueId(record["plan_id"]),
            workflow_hash=Sha256Digest(record["workflow_hash"]),
            module_source_hashes=record["module_source_hashes"],
            deficits=tuple(
                BuildDeficit.from_record(item) for item in record["deficits"]
            ),
        )
        if result.report_id.value != record["report_id"]:
            raise ValueError("build admission report identity is stale")
        return result


def _id_map(
    value: object,
    name: str,
    value_pattern: re.Pattern[str],
) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{name} must be a non-empty mapping")
    result: dict[str, str] = {}
    for local_id in sorted(value):
        key = _local_id(local_id, f"{name} key")
        item = _text(value[local_id], f"{name}.{local_id}", maximum=128)
        if value_pattern.fullmatch(item) is None:
            raise ValueError(f"{name}.{local_id} has an invalid identity")
        result[key] = item
    return MappingProxyType(result)


def _digest_map(
    value: object,
    name: str,
    *,
    allow_empty: bool = False,
) -> Mapping[str, Sha256Digest]:
    if not isinstance(value, Mapping) or (not value and not allow_empty):
        qualifier = "a mapping" if allow_empty else "a non-empty mapping"
        raise ValueError(f"{name} must be {qualifier}")
    result: dict[str, Sha256Digest] = {}
    for local_id in sorted(value):
        key = _local_id(local_id, f"{name} key")
        raw = value[local_id]
        result[key] = raw if isinstance(raw, Sha256Digest) else Sha256Digest(raw)
    return MappingProxyType(result)


@dataclass(frozen=True)
class BuildManifest:
    """The exact statically admitted source objects produced from one plan."""

    build_request_id: OpaqueId
    build_attempt_id: OpaqueId
    plan_id: OpaqueId
    admission_report_id: OpaqueId
    predecessor_manifest_id: Optional[OpaqueId]
    workflow_hash: Sha256Digest
    root_local_id: str
    root_module: str
    episode_ids_by_local_id: Mapping[str, str]
    module_hashes_by_local_id: Mapping[str, Sha256Digest]
    module_dispositions_by_local_id: Mapping[str, str]
    function_definition_ids: tuple[str, ...]
    manifest_id: OpaqueId = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.build_request_id, OpaqueId):
            raise TypeError("build_request_id must be an OpaqueId")
        if not isinstance(self.build_attempt_id, OpaqueId):
            raise TypeError("build_attempt_id must be an OpaqueId")
        if not isinstance(self.plan_id, OpaqueId):
            raise TypeError("plan_id must be an OpaqueId")
        if not isinstance(self.admission_report_id, OpaqueId):
            raise TypeError("admission_report_id must be an OpaqueId")
        if self.predecessor_manifest_id is not None and not isinstance(
            self.predecessor_manifest_id,
            OpaqueId,
        ):
            raise TypeError("predecessor_manifest_id must be an OpaqueId or None")
        if not isinstance(self.workflow_hash, Sha256Digest):
            raise TypeError("workflow_hash must be a Sha256Digest")
        object.__setattr__(
            self,
            "root_local_id",
            _local_id(self.root_local_id, "root_local_id"),
        )
        module = _text(self.root_module, "root_module", maximum=512)
        if _DOTTED_NAME.fullmatch(module) is None:
            raise ValueError("root_module must be a dotted Python module name")
        object.__setattr__(self, "root_module", module)
        object.__setattr__(
            self,
            "episode_ids_by_local_id",
            _id_map(
                self.episode_ids_by_local_id,
                "episode_ids_by_local_id",
                _EPISODE_ID,
            ),
        )
        object.__setattr__(
            self,
            "module_hashes_by_local_id",
            _digest_map(
                self.module_hashes_by_local_id,
                "module_hashes_by_local_id",
            ),
        )
        if set(self.episode_ids_by_local_id) != set(self.module_hashes_by_local_id):
            raise ValueError("Episode IDs and module hashes must cover the same nodes")
        dispositions = _node_disposition_map(
            self.module_dispositions_by_local_id,
            "module_dispositions_by_local_id",
        )
        if set(dispositions) != set(self.module_hashes_by_local_id):
            raise ValueError("module dispositions must cover every module exactly")
        object.__setattr__(self, "module_dispositions_by_local_id", dispositions)
        definition_ids = _tuple_of_strings(
            self.function_definition_ids,
            "function_definition_ids",
            pattern=_DEFINITION_ID,
        )
        object.__setattr__(self, "function_definition_ids", definition_ids)
        object.__setattr__(
            self,
            "manifest_id",
            content_id("build_manifest", self.semantic_record()),
        )

    def semantic_record(self) -> dict[str, Any]:
        return {
            "build_request_id": self.build_request_id.value,
            "build_attempt_id": self.build_attempt_id.value,
            "plan_id": self.plan_id.value,
            "admission_report_id": self.admission_report_id.value,
            "predecessor_manifest_id": (
                None
                if self.predecessor_manifest_id is None
                else self.predecessor_manifest_id.value
            ),
            "workflow_hash": self.workflow_hash.value,
            "root_local_id": self.root_local_id,
            "root_module": self.root_module,
            "episode_ids_by_local_id": dict(self.episode_ids_by_local_id),
            "module_hashes_by_local_id": {
                local_id: digest.value
                for local_id, digest in self.module_hashes_by_local_id.items()
            },
            "module_dispositions_by_local_id": dict(
                self.module_dispositions_by_local_id
            ),
            "function_definition_ids": list(self.function_definition_ids),
        }

    def as_record(self) -> dict[str, Any]:
        return {"manifest_id": self.manifest_id.value, **self.semantic_record()}

    def validate_against(
        self,
        plan: WorkflowMaterializationPlan,
        admission_report: BuildAdmissionReport,
    ) -> None:
        if not isinstance(plan, WorkflowMaterializationPlan):
            raise TypeError("plan must be a WorkflowMaterializationPlan")
        if not isinstance(admission_report, BuildAdmissionReport):
            raise TypeError("admission_report must be a BuildAdmissionReport")
        if not plan.ready:
            raise ValueError("a plan with blocking deficits cannot produce a manifest")
        if (
            self.build_request_id != plan.build_request_id
            or self.build_attempt_id != plan.build_attempt_id
            or self.plan_id != plan.plan_id
        ):
            raise ValueError("manifest does not belong to its materialization plan")
        if plan.predecessor_plan_id is not None and self.predecessor_manifest_id is None:
            raise ValueError("successor plan requires predecessor manifest linkage")
        if self.workflow_hash != plan.workflow_hash:
            raise ValueError("manifest workflow hash differs from its plan")
        if self.root_local_id != plan.root_local_id:
            raise ValueError("manifest root differs from its plan")
        nodes = {node.local_id: node for node in plan.nodes}
        if set(self.episode_ids_by_local_id) != set(nodes):
            raise ValueError("manifest must contain every planned Episode module")
        if self.root_module != nodes[self.root_local_id].module_name:
            raise ValueError("manifest root module differs from the root node plan")
        admission_report.validate_against(plan)
        if not admission_report.admitted:
            raise ValueError("manifest requires an admitted module report")
        if self.admission_report_id != admission_report.report_id:
            raise ValueError("manifest names a different admission report")
        if self.module_hashes_by_local_id != admission_report.module_source_hashes:
            raise ValueError("manifest module hashes differ from the admission report")
        if self.module_dispositions_by_local_id != plan.node_dispositions:
            raise ValueError("manifest module dispositions differ from the plan")
        known_library_definitions = {
            str(binding["definition_id"])
            for node in plan.nodes
            for binding in node.selected_function_bindings
            if binding["source"] == "library"
        }
        if not known_library_definitions.issubset(self.function_definition_ids):
            raise ValueError(
                "manifest drops a selected executable library definition"
            )

    @classmethod
    def from_record(cls, value: object) -> "BuildManifest":
        record = _record(
            value,
            "build manifest",
            {
                "manifest_id",
                "build_request_id",
                "build_attempt_id",
                "plan_id",
                "admission_report_id",
                "predecessor_manifest_id",
                "workflow_hash",
                "root_local_id",
                "root_module",
                "episode_ids_by_local_id",
                "module_hashes_by_local_id",
                "module_dispositions_by_local_id",
                "function_definition_ids",
            },
        )
        result = cls(
            build_request_id=OpaqueId(record["build_request_id"]),
            build_attempt_id=OpaqueId(record["build_attempt_id"]),
            plan_id=OpaqueId(record["plan_id"]),
            admission_report_id=OpaqueId(record["admission_report_id"]),
            predecessor_manifest_id=(
                None
                if record["predecessor_manifest_id"] is None
                else OpaqueId(record["predecessor_manifest_id"])
            ),
            workflow_hash=Sha256Digest(record["workflow_hash"]),
            root_local_id=record["root_local_id"],
            root_module=record["root_module"],
            episode_ids_by_local_id=record["episode_ids_by_local_id"],
            module_hashes_by_local_id=record["module_hashes_by_local_id"],
            module_dispositions_by_local_id=record[
                "module_dispositions_by_local_id"
            ],
            function_definition_ids=tuple(
                _array(
                    record["function_definition_ids"],
                    "function_definition_ids",
                )
            ),
        )
        if result.manifest_id.value != record["manifest_id"]:
            raise ValueError("build manifest identity is stale")
        return result
