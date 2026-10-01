"""Workspace projection and navigation for iterative Episode refinement.

The Duet store and EpisodeBuilder own persisted facts.  This module turns
those already-validated facts into the two UI projections and an exact target
index.  It delegates source-package verification to BuildStore and never
executes a workflow or independently interprets generated source.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Mapping, Optional, Protocol

from agent.duet_contracts import (
    DuetApproval,
    DuetDesignState,
    DuetIdentity,
    DuetProtocolError,
    FrozenDuetWorkflow,
    WorkflowAdmissionAuthority,
    canonical_json,
)
from agent.duet_store import DuetConflictError, DuetNotFoundError, DuetStore
from agent.episode_blueprints import workflow_blueprint_from_spec
from agent.episode_contracts import OpaqueId, Sha256Digest
from episode_builder import (
    BuildManifest,
    BuildReceipt,
    BuildStore,
    MaterializedSpecification,
)
from episode_runtime import RunEvidence, RunStore

from .contracts import (
    CurrentBuildAuthorization,
    DuetWorkspaceNote,
    RefinementBaseline,
    RefinementDecision,
    RefinementProposal,
    RefinementTarget,
    RefinementTargetLayer,
)
from .service import (
    EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
    MATERIALIZED_SPECIFICATION_ARTIFACT_KIND,
    REFINEMENT_BASELINE_ARTIFACT_KIND,
    RUN_EVIDENCE_ARTIFACT_KIND,
    IterativeEpisodeRefiner,
)


_INITIAL_EDITABLE_STATES = frozenset(
    {
        DuetDesignState.DESIGNING.value,
        DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value,
    }
)
_MISSING = object()


class WorkspaceAuthorityReader(Protocol):
    def duet_status(self, duet_id: OpaqueId) -> dict[str, Any]: ...

    def read_episode_workflow_draft(
        self,
        duet_id: OpaqueId,
        artifact_id: OpaqueId,
    ) -> dict[str, Any]: ...

    def verify_workflow_approval(
        self,
        approval_id: OpaqueId,
    ) -> tuple[
        DuetApproval,
        FrozenDuetWorkflow,
        WorkflowAdmissionAuthority,
    ]: ...

    def resolve_current_build_authorization(
        self,
        duet_id: OpaqueId,
    ) -> CurrentBuildAuthorization: ...


class RefinementWorkspaceError(RuntimeError):
    """The persisted workspace cannot be projected without losing identity."""


def _json_copy(value: object) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_copy(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_json_copy(item) for item in value]
    return value


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _summary(value: object) -> str:
    text = json.dumps(
        _json_copy(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(text) <= 480:
        return text
    return text[:477] + "..."


def _label(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def _target(
    *,
    layer: RefinementTargetLayer,
    artifact_id: str,
    artifact_hash: str,
    json_pointer: str,
    episode_local_id: Optional[str],
) -> dict[str, Any]:
    return RefinementTarget(
        layer=layer,
        artifact_id=OpaqueId(artifact_id),
        artifact_hash=Sha256Digest(artifact_hash),
        json_pointer=json_pointer,
        episode_local_id=episode_local_id,
    ).as_record()


def architecture_target_index(
    snapshot: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Index every target emitted by ``WorkflowArchitectureViewModel``."""

    artifact_id = snapshot["source_artifact_id"]
    artifact_hash = snapshot["content_hash"]
    configuration = _mapping(snapshot["configuration"], "Architecture")
    episodes = configuration.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("Architecture episodes must be an array")
    evidence = {
        "source_artifact_id": artifact_id,
        "content_hash": artifact_hash,
        "workflow_hash": snapshot["workflow_hash"],
        "revision": snapshot["revision"],
        "validation_deficits": _json_copy(snapshot["validation_deficits"]),
    }
    index: dict[str, dict[str, Any]] = {}

    def add(
        *,
        pointer: str,
        local_id: Optional[str],
        selected: object,
    ) -> None:
        target = _target(
            layer=RefinementTargetLayer.WORKFLOW_SEMANTICS,
            artifact_id=artifact_id,
            artifact_hash=artifact_hash,
            json_pointer=pointer,
            episode_local_id=local_id,
        )
        index[target["target_id"]] = {
            "part_kind": "architecture",
            "selected_part": _json_copy(selected),
            "target_metadata": target,
            "evidence": _json_copy(evidence),
        }

    add(pointer="", local_id=None, selected=configuration)
    for raw_value in episodes:
        raw = _mapping(raw_value, "Architecture Episode")
        local_id = raw.get("local_id")
        if not isinstance(local_id, str) or not local_id:
            raise ValueError("Architecture Episode has no local_id")
        episode_pointer = f"/episodes/{_pointer_token(local_id)}"
        add(pointer=episode_pointer, local_id=local_id, selected=raw)
        for field in (
            "local_id",
            "workflow_parent_local_id",
            "episode_reference",
        ):
            add(
                pointer=f"{episode_pointer}/{field}",
                local_id=local_id,
                selected={field: raw.get(field)},
            )
        contract = _mapping(raw.get("contract"), "Architecture contract")
        for field in (
            "goal",
            "result",
            "unit",
            "progress",
            "stopping",
            "numeric_control",
            "execution_capability_names",
            "deliverable",
        ):
            add(
                pointer=f"{episode_pointer}/contract/{field}",
                local_id=local_id,
                selected={field: contract[field]},
            )
    return index


def _projected_part(
    *,
    specification: MaterializedSpecification,
    key: str,
    name: str,
    value: object,
    part_hash: Sha256Digest,
    stable_target: str,
    episode_local_id: Optional[str],
    evidence: object,
    code: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": _label(name),
        "description": (
            "Deterministic EpisodeBuilder projection of this exact build part."
        ),
        "summary": _summary(value),
        "declaration": _json_copy(value),
        "evidence": _json_copy(evidence),
        "part_hash": part_hash.value,
        "target": _target(
            layer=RefinementTargetLayer.MATERIALIZATION_IMPLEMENTATION,
            artifact_id=specification.specification_id.value,
            artifact_hash=specification.content_hash.value,
            json_pointer=stable_target,
            episode_local_id=episode_local_id,
        ),
        "code": code,
    }


def materialized_workspace_projection(
    specification: MaterializedSpecification,
    receipt: BuildReceipt,
    manifest: Optional[BuildManifest],
) -> dict[str, Any]:
    """Project one exact Materialized Specification for the UI.

    The Builder already performed source parsing while constructing the typed
    specification.  This function only formats its typed parts and exact AST
    symbol index; it performs no second interpretation of generated source.
    """

    if not isinstance(specification, MaterializedSpecification):
        raise TypeError("specification must be a MaterializedSpecification")
    if not isinstance(receipt, BuildReceipt):
        raise TypeError("receipt must be a BuildReceipt")
    if specification.receipt_id != receipt.receipt_id:
        raise ValueError("Materialized Specification names another receipt")
    if specification.build_request_id != receipt.build_request_id or (
        specification.build_attempt_id != receipt.build_attempt_id
    ):
        raise ValueError("Materialized Specification names another build")
    if (manifest is None) != (receipt.manifest_id is None):
        raise ValueError("manifest presence differs from the build receipt")
    if manifest is not None and manifest.manifest_id != receipt.manifest_id:
        raise ValueError("manifest differs from the build receipt")

    manifest_hash = (
        None
        if manifest is None
        else Sha256Digest.of_record(manifest.as_record()).value
    )
    overview = {
        "specification_id": specification.specification_id.value,
        "content_hash": specification.content_hash.value,
        "build_request_id": specification.build_request_id.value,
        "build_attempt_id": specification.build_attempt_id.value,
        "plan_id": specification.plan_id.value,
        "workflow_hash": specification.workflow_hash.value,
        "status": specification.status,
        "deficits": [item.as_record() for item in specification.deficits],
    }
    global_parts = [
        _projected_part(
            specification=specification,
            key="workflow_overview",
            name="workflow_overview",
            value=overview,
            part_hash=Sha256Digest.of_record(overview),
            stable_target="/workflow_global",
            episode_local_id=None,
            evidence={
                "build_receipt": receipt.as_record(),
                "build_manifest": (
                    None if manifest is None else manifest.as_record()
                ),
            },
        )
    ]
    for part in specification.workflow_global:
        global_parts.append(
            _projected_part(
                specification=specification,
                key=part.name,
                name=part.name,
                value=part.value,
                part_hash=part.content_hash,
                stable_target=part.stable_target,
                episode_local_id=None,
                evidence=part.as_record(),
            )
        )

    episodes = []
    for episode in specification.episodes:
        frozen_part = next(
            (part for part in episode.parts if part.name == "frozen_contract"),
            None,
        )
        frozen = (
            {}
            if frozen_part is None
            else _mapping(frozen_part.value, "frozen Episode declaration")
        )
        parent = frozen.get("workflow_parent_local_id")
        if parent is not None and not isinstance(parent, str):
            raise ValueError("frozen Episode parent identity is malformed")
        contract = frozen.get("contract")
        goal = contract.get("goal") if isinstance(contract, Mapping) else None
        name = episode.local_id
        if isinstance(goal, str) and goal.strip():
            compact = " ".join(goal.split())
            name = compact if len(compact) <= 46 else compact[:43].rstrip() + "..."
        emitted_source = None
        for part in episode.parts:
            if part.name != "emitted_module" or not isinstance(part.value, Mapping):
                continue
            source = part.value.get("module_source")
            if isinstance(source, str):
                emitted_source = source
        parts = []
        for part in episode.parts:
            code = emitted_source if part.name == "emitted_module" else None
            parts.append(
                _projected_part(
                    specification=specification,
                    key=part.name,
                    name=part.name,
                    value=part.value,
                    part_hash=part.content_hash,
                    stable_target=part.stable_target,
                    episode_local_id=episode.local_id,
                    evidence=part.as_record(),
                    code=code,
                )
            )
        for symbol in episode.source_symbols:
            record = symbol.as_record()
            parts.append(
                _projected_part(
                    specification=specification,
                    key=f"source_symbol:{symbol.symbol_path}",
                    name=f"source symbol {symbol.symbol_path}",
                    value=record,
                    part_hash=Sha256Digest.of_record(record),
                    stable_target=symbol.stable_target,
                    episode_local_id=episode.local_id,
                    evidence=record,
                )
            )
        episodes.append(
            {
                "local_id": episode.local_id,
                "name": name,
                "parent_local_id": parent,
                "declaration": episode.as_record(),
                "target": _target(
                    layer=(
                        RefinementTargetLayer.MATERIALIZATION_IMPLEMENTATION
                    ),
                    artifact_id=specification.specification_id.value,
                    artifact_hash=specification.content_hash.value,
                    json_pointer=episode.stable_target,
                    episode_local_id=episode.local_id,
                ),
                "parts": parts,
            }
        )

    return {
        "anchor_artifact_id": specification.specification_id.value,
        "anchor_hash": specification.content_hash.value,
        "workflow_hash": specification.workflow_hash.value,
        "status": specification.status,
        "global_parts": global_parts,
        "episodes": episodes,
        "build_chain": {
            "build_receipt_id": receipt.receipt_id.value,
            "build_receipt_hash": receipt.content_hash.value,
            "build_manifest_id": (
                None if manifest is None else manifest.manifest_id.value
            ),
            "build_manifest_hash": manifest_hash,
        },
        "crosswalk": dict(specification.local_id_to_episode_id),
    }


def materialized_target_index(
    snapshot: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Index exact target records from a host-created materialized snapshot."""

    index: dict[str, dict[str, Any]] = {}

    def add(selected: object, target_value: object, evidence: object) -> None:
        target = _mapping(target_value, "Materialized target")
        target_id = target.get("target_id")
        if not isinstance(target_id, str) or not target_id:
            raise ValueError("Materialized target identity is missing")
        if target_id in index:
            raise ValueError("Materialized target identity is duplicated")
        index[target_id] = {
            "part_kind": "materialized",
            "selected_part": _json_copy(selected),
            "target_metadata": _json_copy(target),
            "evidence": _json_copy(evidence),
        }

    global_parts = snapshot.get("global_parts")
    episodes = snapshot.get("episodes")
    if not isinstance(global_parts, list) or not isinstance(episodes, list):
        raise ValueError("Materialized workspace projection is malformed")
    for part in global_parts:
        record = _mapping(part, "Materialized global part")
        add(record, record.get("target"), record.get("evidence"))
    for episode in episodes:
        record = _mapping(episode, "Materialized Episode")
        add(record, record.get("target"), record.get("declaration"))
        parts = record.get("parts")
        if not isinstance(parts, list):
            raise ValueError("Materialized Episode parts must be an array")
        for part in parts:
            part_record = _mapping(part, "Materialized Episode part")
            add(
                part_record,
                part_record.get("target"),
                part_record.get("evidence"),
            )
    return index


def _materialized_diff_document(
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Project stable implementation content without per-build identities."""

    def target_record(value: object) -> dict[str, Any]:
        target = value if isinstance(value, Mapping) else {}
        return {
            "json_pointer": target.get("json_pointer"),
            "episode_local_id": target.get("episode_local_id"),
        }

    def part_record(value: object) -> dict[str, Any]:
        part = value if isinstance(value, Mapping) else {}
        key = part.get("key")
        result = {
            "key": key,
            "part_hash": part.get("part_hash"),
            "target": target_record(part.get("target")),
        }
        if key == "workflow_overview":
            declaration = part.get("declaration")
            stable_declaration = (
                dict(declaration) if isinstance(declaration, Mapping) else {}
            )
            for volatile in (
                "specification_id",
                "content_hash",
                "build_request_id",
                "build_attempt_id",
                "plan_id",
            ):
                stable_declaration.pop(volatile, None)
            result.pop("part_hash", None)
            result["declaration"] = stable_declaration
        return result

    global_parts = snapshot.get("global_parts")
    episodes = snapshot.get("episodes")
    return {
        "workflow_hash": snapshot.get("workflow_hash"),
        "status": snapshot.get("status"),
        "global_parts": [
            part_record(value)
            for value in (
                global_parts if isinstance(global_parts, list) else []
            )
        ],
        "episodes": [
            {
                "local_id": episode.get("local_id"),
                "name": episode.get("name"),
                "parent_local_id": episode.get("parent_local_id"),
                "target": target_record(episode.get("target")),
                "parts": [
                    part_record(value)
                    for value in (
                        episode.get("parts")
                        if isinstance(episode.get("parts"), list)
                        else []
                    )
                ],
            }
            for episode in (
                episodes if isinstance(episodes, list) else []
            )
            if isinstance(episode, Mapping)
        ],
    }


def _projection_changes(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Return stable identity-addressed changes between two projections."""

    changes: list[dict[str, Any]] = []

    def stable_list_map(value: list[Any]) -> Optional[dict[str, Any]]:
        for identity_field in ("local_id", "key"):
            if not all(
                isinstance(item, Mapping)
                and isinstance(item.get(identity_field), str)
                for item in value
            ):
                continue
            result = {str(item[identity_field]): item for item in value}
            if len(result) == len(value):
                return result
        return None

    def visit(path: str, old: object, new: object) -> None:
        if isinstance(old, Mapping) and isinstance(new, Mapping):
            for key in sorted(set(old) | set(new)):
                child_path = path + "/" + _pointer_token(str(key))
                visit(
                    child_path,
                    old.get(key, _MISSING),
                    new.get(key, _MISSING),
                )
            return
        if isinstance(old, list) and isinstance(new, list):
            old_items = stable_list_map(old)
            new_items = stable_list_map(new)
            if old_items is not None and new_items is not None:
                visit(path, old_items, new_items)
                return
            for index in range(max(len(old), len(new))):
                child_path = path + "/" + str(index)
                visit(
                    child_path,
                    old[index] if index < len(old) else _MISSING,
                    new[index] if index < len(new) else _MISSING,
                )
            return
        if old is not _MISSING and new is not _MISSING and old == new:
            return
        if old is _MISSING:
            kind = "added"
        elif new is _MISSING:
            kind = "removed"
        else:
            kind = "changed"
        change: dict[str, Any] = {"path": path or "/", "kind": kind}
        if old is not _MISSING:
            change["before"] = _json_copy(old)
        if new is not _MISSING:
            change["after"] = _json_copy(new)
        changes.append(change)

    visit("", before, after)
    return tuple(changes)


def architecture_projection_changes(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Return exact changes between two persisted Architecture documents."""

    return _projection_changes(before, after)


def materialized_projection_changes(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Return stable part-addressed changes between two materializations."""

    return _projection_changes(
        _materialized_diff_document(before),
        _materialized_diff_document(after),
    )


class RefinementWorkspace:
    """Exact Architecture/Materialized views over one captured authority head."""

    def __init__(
        self,
        *,
        identity: DuetIdentity,
        authority: WorkspaceAuthorityReader,
        refiner: IterativeEpisodeRefiner,
        store: DuetStore,
        build_store: BuildStore,
        run_store: RunStore,
    ) -> None:
        self.identity = identity
        self.authority = authority
        self.refiner = refiner
        self.store = store
        self.build_store = build_store
        self.run_store = run_store
        self._note_lock = threading.RLock()

    def _pending_refinement_evidence(
        self,
        status: Mapping[str, Any],
    ) -> Optional[dict[str, Any]]:
        active = status.get("active_refinement")
        if not isinstance(active, Mapping) or not isinstance(
            active.get("decision_artifact_id"),
            str,
        ):
            return None
        decision_artifact = self.refiner.read_artifact(
            self.identity.duet_id,
            OpaqueId(active["decision_artifact_id"]),
        )
        decision = RefinementDecision.from_record(decision_artifact["record"])
        if (
            active.get("refinement_id") != decision.refinement_id.value
            or active.get("proposal_artifact_id")
            != decision.proposal_id.value
        ):
            raise RefinementWorkspaceError(
                "pending refinement decision lineage is stale"
            )
        proposal_artifact = self.refiner.read_artifact(
            self.identity.duet_id,
            decision.proposal_id,
        )
        proposal = RefinementProposal.from_record(proposal_artifact["record"])
        if proposal.content_hash != decision.proposal_hash:
            raise RefinementWorkspaceError(
                "pending refinement proposal hash is stale"
            )
        candidate = None
        if decision.successor_draft_artifact_id is not None:
            successor_hash = decision.successor_draft_hash
            if successor_hash is None:
                raise RefinementWorkspaceError(
                    "pending successor Architecture has no content hash"
                )
            draft = self.authority.read_episode_workflow_draft(
                self.identity.duet_id,
                decision.successor_draft_artifact_id,
            )
            if draft["content_hash"] != successor_hash.value:
                raise RefinementWorkspaceError(
                    "pending successor Architecture hash is stale"
                )
            candidate = {
                "source_artifact_id": draft["artifact_id"],
                "content_hash": draft["content_hash"],
                "workflow_hash": draft["workflow_hash"],
                "revision": draft["revision"],
                "configuration": draft["workflow"],
            }
        return {
            "refinement_id": decision.refinement_id.value,
            "state": active["state"],
            "decision_id": decision.decision_id.value,
            "decision_hash": decision.content_hash.value,
            "proposal_id": proposal.proposal_id.value,
            "proposal_hash": proposal.content_hash.value,
            "change_kind": decision.kind.value,
            "note_ids": [value.value for value in proposal.note_ids],
            "changed_workflow_paths": list(decision.changed_workflow_paths),
            "implementation_directives": [
                value.as_record()
                for value in proposal.implementation_directives
            ],
            "candidate_architecture": candidate,
        }

    def _architecture_snapshot(
        self,
        status: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        if status is None:
            status = self.authority.duet_status(self.identity.duet_id)
        draft_metadata = status.get("episode_workflow_draft")
        if not isinstance(draft_metadata, Mapping):
            raise DuetProtocolError(
                "no Episode Architecture exists yet; ask the Duet to submit one"
            )
        state = status["state"]
        authority_head = status.get("authority_head_approval")
        pending_refinement = self._pending_refinement_evidence(status)
        if authority_head is None:
            draft = self.authority.read_episode_workflow_draft(
                self.identity.duet_id,
                OpaqueId(draft_metadata["artifact_id"]),
            )
            return {
                "source_artifact_id": draft["artifact_id"],
                "content_hash": draft["content_hash"],
                "workflow_hash": draft["workflow_hash"],
                "revision": draft["revision"],
                "configuration": draft["workflow"],
                "validation_deficits": list(
                    draft_metadata.get("validation_deficits") or ()
                ),
                "editable": bool(
                    authority_head is None and state in _INITIAL_EDITABLE_STATES
                ),
                "pending_refinement": pending_refinement,
            }
        workflow_approval = status.get("workflow_approval")
        if not isinstance(workflow_approval, Mapping) or not isinstance(
            workflow_approval.get("approval_id"),
            str,
        ):
            raise RefinementWorkspaceError(
                "approved Architecture has no workflow authority record"
            )
        _approval, frozen, _authority = (
            self.authority.verify_workflow_approval(
                OpaqueId(workflow_approval["approval_id"])
            )
        )
        return {
            "source_artifact_id": frozen.artifact_id.value,
            "content_hash": frozen.workflow_hash.value,
            "workflow_hash": frozen.workflow_hash.value,
            "revision": frozen.revision,
            "configuration": workflow_blueprint_from_spec(frozen.workflow),
            "validation_deficits": [],
            "editable": False,
            "pending_refinement": pending_refinement,
        }

    @staticmethod
    def _frozen_architecture(frozen: FrozenDuetWorkflow) -> dict[str, Any]:
        return {
            "source_artifact_id": frozen.artifact_id.value,
            "content_hash": frozen.workflow_hash.value,
            "workflow_hash": frozen.workflow_hash.value,
            "revision": frozen.revision,
            "configuration": workflow_blueprint_from_spec(frozen.workflow),
        }

    def _previous_initial_architecture(
        self,
        current: Mapping[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Resolve the immutable initial draft immediately before ``current``."""

        current_revision = current.get("revision")
        if not isinstance(current_revision, int):
            raise RefinementWorkspaceError(
                "current Architecture revision is malformed"
            )
        candidates: list[Mapping[str, Any]] = []
        for artifact in self.store.artifacts_by_kind(
            duet_id=self.identity.duet_id.value,
            kind=EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND,
        ):
            record = artifact.get("record")
            if not isinstance(record, Mapping):
                raise RefinementWorkspaceError(
                    "stored Architecture draft is malformed"
                )
            revision = record.get("revision")
            if (
                record.get("refinement_id") is None
                and isinstance(revision, int)
                and revision < current_revision
            ):
                candidates.append(artifact)
        if not candidates:
            return None
        prior_revision = max(
            int(_mapping(item["record"], "Architecture draft")["revision"])
            for item in candidates
        )
        nearest = [
            item
            for item in candidates
            if _mapping(item["record"], "Architecture draft").get("revision")
            == prior_revision
        ]
        if len(nearest) != 1:
            raise RefinementWorkspaceError(
                "previous Architecture revision is ambiguous"
            )
        artifact_id = nearest[0].get("artifact_id")
        if not isinstance(artifact_id, str):
            raise RefinementWorkspaceError(
                "previous Architecture identity is malformed"
            )
        draft = self.authority.read_episode_workflow_draft(
            self.identity.duet_id,
            OpaqueId(artifact_id),
        )
        if (
            draft.get("artifact_id") != artifact_id
            or draft.get("content_hash") != nearest[0].get("content_hash")
            or draft.get("revision") != prior_revision
        ):
            raise RefinementWorkspaceError(
                "previous Architecture draft differs from its artifact"
            )
        return {
            "source_artifact_id": draft["artifact_id"],
            "content_hash": draft["content_hash"],
            "workflow_hash": draft["workflow_hash"],
            "revision": draft["revision"],
            "configuration": draft["workflow"],
        }

    def _architecture_comparison(
        self,
        *,
        architecture: Mapping[str, Any],
        baseline: Optional[RefinementBaseline],
        predecessor_baseline: Optional[RefinementBaseline],
        authority_head_approval_id: Optional[str],
    ) -> tuple[
        str,
        str,
        tuple[dict[str, Any], ...],
    ]:
        """Compare the latest Architecture with its persisted predecessor."""

        before: Optional[dict[str, Any]] = None
        after: Mapping[str, Any] = architecture
        pending = architecture.get("pending_refinement")
        candidate = (
            pending.get("candidate_architecture")
            if isinstance(pending, Mapping)
            else None
        )
        if authority_head_approval_id is None:
            before = self._previous_initial_architecture(architecture)
        elif isinstance(candidate, Mapping):
            if baseline is None:
                raise RefinementWorkspaceError(
                    "pending Architecture refinement has no predecessor baseline"
                )
            _approval, frozen, _authority = (
                self.authority.verify_workflow_approval(
                    baseline.workflow_approval_id
                )
            )
            if (
                frozen.artifact_id != baseline.frozen_workflow_artifact_id
                or frozen.workflow_hash != baseline.workflow_hash
            ):
                raise RefinementWorkspaceError(
                    "pending Architecture predecessor is stale"
                )
            before = self._frozen_architecture(frozen)
            after = candidate
        elif predecessor_baseline is not None:
            _approval, frozen, _authority = (
                self.authority.verify_workflow_approval(
                    predecessor_baseline.workflow_approval_id
                )
            )
            if (
                frozen.artifact_id
                != predecessor_baseline.frozen_workflow_artifact_id
                or frozen.workflow_hash != predecessor_baseline.workflow_hash
            ):
                raise RefinementWorkspaceError(
                    "refinement predecessor workflow is stale"
                )
            before = self._frozen_architecture(frozen)
        if before is None:
            revision = architecture.get("revision")
            return f"r{revision}", f"r{revision}", ()
        before_configuration = _mapping(
            before.get("configuration"),
            "previous Architecture",
        )
        after_configuration = _mapping(
            after.get("configuration"),
            "latest Architecture",
        )
        return (
            f"r{before.get('revision')}",
            f"r{after.get('revision')}",
            architecture_projection_changes(
                before_configuration,
                after_configuration,
            ),
        )

    def architecture_snapshot(self) -> dict[str, Any]:
        return json.loads(canonical_json(self._architecture_snapshot()))

    def baseline_for_authority_head(
        self,
        authority_head_approval_id: Optional[str],
    ) -> Optional[RefinementBaseline]:
        if authority_head_approval_id is None:
            return None
        artifacts = self.store.artifacts_by_kind(
            duet_id=self.identity.duet_id.value,
            kind=REFINEMENT_BASELINE_ARTIFACT_KIND,
        )
        for artifact in reversed(artifacts):
            try:
                baseline = RefinementBaseline.from_record(artifact["record"])
            except (TypeError, ValueError) as exc:
                raise RefinementWorkspaceError(
                    "stored refinement baseline is malformed"
                ) from exc
            if (
                baseline.authority_head_approval_id.value
                == authority_head_approval_id
            ):
                if (
                    baseline.baseline_id.value != artifact["artifact_id"]
                    or baseline.content_hash.value != artifact["content_hash"]
                ):
                    raise RefinementWorkspaceError(
                        "stored refinement baseline identity is stale"
                    )
                return baseline
        return None

    def current_baseline(self) -> Optional[RefinementBaseline]:
        duet = self.store.get_duet(self.identity.duet_id.value)
        if duet is None:
            raise RefinementWorkspaceError("active Duet record is missing")
        head = duet.get("authority_head_approval_id")
        return self.baseline_for_authority_head(
            head if isinstance(head, str) else None
        )

    def _carried_baseline(
        self,
        *,
        status: Mapping[str, Any],
        authority_head_approval_id: Optional[str],
    ) -> Optional[RefinementBaseline]:
        """Resolve the prior build carried while its successor is unbuilt."""

        if (
            authority_head_approval_id is None
            or status.get("state") != DuetDesignState.SEALED.value
        ):
            return None
        authorization = self.authority.resolve_current_build_authorization(
            self.identity.duet_id
        )
        if (
            authorization.authority_approval.approval_id.value
            != authority_head_approval_id
        ):
            raise RefinementWorkspaceError(
                "current build authorization differs from the workspace authority head"
            )
        decision = authorization.refinement_decision
        if decision is None:
            return None
        baseline, _proposal, _notes = self.refiner.approved_chain(decision)
        if (
            baseline.duet_id != self.identity.duet_id
            or decision.baseline_id != baseline.baseline_id
            or decision.baseline_workflow_hash != baseline.workflow_hash
            or authorization.authority_approval.predecessor_approval_id
            != baseline.authority_head_approval_id
        ):
            raise RefinementWorkspaceError(
                "refinement predecessor differs from the current authority chain"
            )
        return baseline

    def _baseline_predecessor(
        self,
        baseline: RefinementBaseline,
    ) -> Optional[RefinementBaseline]:
        """Resolve the build immediately before one materialized baseline."""

        request = self.build_store.read_build_request(
            baseline.build_request_id
        )
        if (
            request.frozen_workflow.duet_id != self.identity.duet_id
            or request.authority_approval.approval_id
            != baseline.authority_head_approval_id
            or request.workflow_approval.approval_id
            != baseline.workflow_approval_id
            or request.frozen_workflow.artifact_id
            != baseline.frozen_workflow_artifact_id
            or request.frozen_workflow.workflow_hash != baseline.workflow_hash
        ):
            raise RefinementWorkspaceError(
                "materialized baseline differs from its approved build request"
            )
        predecessor = request.refinement_baseline
        if predecessor is None:
            return None
        stored = self.refiner.load_baseline(predecessor.baseline_id)
        if stored.as_record() != predecessor.as_record():
            raise RefinementWorkspaceError(
                "materialized predecessor differs from its persisted baseline"
            )
        return stored

    def evidence_from_baseline(
        self,
        baseline: RefinementBaseline,
    ) -> Optional[RunEvidence]:
        evidence_id = baseline.run_evidence_artifact_id
        if evidence_id is None:
            return None
        artifact = self.store.get_artifact(evidence_id.value)
        if (
            artifact is None
            or artifact["duet_id"] != self.identity.duet_id.value
            or artifact["kind"] != RUN_EVIDENCE_ARTIFACT_KIND
            or artifact["content_hash"] != baseline.run_evidence_hash.value
        ):
            raise RefinementWorkspaceError(
                "current Run evidence artifact is missing or stale"
            )
        evidence = RunEvidence.from_record(artifact["record"])
        validated = self.run_store.read_evidence(evidence.run_id)
        if validated.as_record() != evidence.as_record():
            raise RefinementWorkspaceError(
                "current Run evidence differs from its validated audit log"
            )
        return evidence

    def run_reference_data(
        self,
        baseline: Optional[RefinementBaseline],
    ) -> Optional[dict[str, Any]]:
        """Project one validated terminal Run as untrusted refinement evidence."""

        if baseline is None or baseline.run_evidence_artifact_id is None:
            return None
        evidence = self.evidence_from_baseline(baseline)
        if evidence is None:
            raise RefinementWorkspaceError(
                "refinement baseline names absent Run evidence"
            )
        events = self.run_store.read_audit_log(evidence.run_id)
        location = self.run_store.audit_log_location(evidence.run_id)
        return {
            "classification": "UNTRUSTED_RUN_AUDIT_DATA",
            "log_location": str(location),
            "evidence": evidence.as_record(),
            "audit_log": {
                "audit_log_id": evidence.audit_log_id.value,
                "audit_log_hash": evidence.audit_log_hash.value,
                "events": [event.as_record() for event in events],
            },
        }

    def materialized_context(
        self,
        baseline: RefinementBaseline,
    ) -> tuple[MaterializedSpecification, BuildReceipt, Optional[BuildManifest]]:
        artifact = self.store.get_artifact(
            baseline.materialized_specification_id.value
        )
        if (
            artifact is None
            or artifact["duet_id"] != self.identity.duet_id.value
            or artifact["kind"] != MATERIALIZED_SPECIFICATION_ARTIFACT_KIND
            or artifact["content_hash"]
            != baseline.materialized_specification_hash.value
        ):
            raise RefinementWorkspaceError(
                "current Materialized Specification artifact is missing"
            )
        specification = MaterializedSpecification.from_record(artifact["record"])
        if specification.specification_id != baseline.materialized_specification_id:
            raise RefinementWorkspaceError(
                "current Materialized Specification identity is stale"
            )
        receipt = self.build_store.read_receipt(baseline.build_receipt_id)
        if receipt.content_hash != baseline.build_receipt_hash:
            raise RefinementWorkspaceError("current build receipt hash is stale")
        projected = self.build_store.project_receipt(
            receipt.receipt_id,
            verify_source_package=receipt.manifest_id is not None,
        )
        if projected.as_record() != specification.as_record():
            raise RefinementWorkspaceError(
                "persisted Materialized Specification differs from its build chain"
            )
        manifest = (
            None
            if baseline.build_manifest_id is None
            else self.build_store.read_manifest(baseline.build_manifest_id)
        )
        if manifest is not None and Sha256Digest.of_record(
            manifest.as_record()
        ) != baseline.build_manifest_hash:
            raise RefinementWorkspaceError("current build manifest hash is stale")
        return specification, receipt, manifest

    def context(
        self,
    ) -> tuple[dict[str, Any], Optional[RefinementBaseline]]:
        """Capture both views and their one exact baseline object."""

        status = self.authority.duet_status(self.identity.duet_id)
        head_record = status.get("authority_head_approval")
        if head_record is None:
            authority_head_approval_id = None
        elif isinstance(head_record, Mapping) and isinstance(
            head_record.get("approval_id"),
            str,
        ):
            authority_head_approval_id = head_record["approval_id"]
        else:
            raise RefinementWorkspaceError(
                "Duet authority head record is malformed"
            )
        architecture = self._architecture_snapshot(status)
        baseline = self.baseline_for_authority_head(
            authority_head_approval_id
        )
        carried_baseline = (
            None
            if baseline is not None
            else self._carried_baseline(
                status=status,
                authority_head_approval_id=authority_head_approval_id,
            )
        )
        display_baseline = baseline or carried_baseline
        predecessor_baseline = (
            None
            if baseline is None
            else self._baseline_predecessor(baseline)
        )
        (
            architecture_change_from,
            architecture_change_to,
            architecture_changes,
        ) = self._architecture_comparison(
            architecture=architecture,
            baseline=baseline,
            predecessor_baseline=(
                carried_baseline or predecessor_baseline
            ),
            authority_head_approval_id=authority_head_approval_id,
        )
        architecture_changed_paths = tuple(
            change["path"] for change in architecture_changes
        )
        materialized = None
        materialized_changes: tuple[dict[str, Any], ...] = ()
        materialized_from_id: Optional[str] = None
        materialized_to_id: Optional[str] = None
        if display_baseline is not None:
            specification, receipt, manifest = self.materialized_context(
                display_baseline
            )
            materialized = materialized_workspace_projection(
                specification,
                receipt,
                manifest,
            )
            materialized_from_id = specification.specification_id.value
            materialized_to_id = specification.specification_id.value
            if (
                display_baseline is not None
                and predecessor_baseline is not None
                and predecessor_baseline.baseline_id
                != display_baseline.baseline_id
            ):
                previous_specification, previous_receipt, previous_manifest = (
                    self.materialized_context(predecessor_baseline)
                )
                previous_materialized = materialized_workspace_projection(
                    previous_specification,
                    previous_receipt,
                    previous_manifest,
                )
                materialized_changes = materialized_projection_changes(
                    previous_materialized,
                    materialized,
                )
                materialized_from_id = (
                    previous_specification.specification_id.value
                )
        if baseline is not None:
            notes = self.refiner.list_workspace_notes(
                self.identity.duet_id,
                baseline.baseline_id,
            )
        else:
            duet = self.store.get_duet(self.identity.duet_id.value)
            if duet is None:
                raise RefinementWorkspaceError("active Duet record is missing")
            notes = (
                self.refiner.list_workspace_notes(self.identity.duet_id, None)
                if duet["authority_head_approval_id"] is None
                else ()
            )
        snapshot = {
            "architecture_snapshot": json.loads(canonical_json(architecture)),
            "materialized_snapshot": (
                None
                if materialized is None
                else json.loads(canonical_json(materialized))
            ),
            "notes": [note.as_record() for note in notes],
            "changed_paths": list(architecture_changed_paths),
            "architecture_changes": [
                _json_copy(change) for change in architecture_changes
            ],
            "architecture_change_from": architecture_change_from,
            "architecture_change_to": architecture_change_to,
            "materialized_changed_paths": [
                change["path"] for change in materialized_changes
            ],
            "materialized_changes": [
                _json_copy(change) for change in materialized_changes
            ],
            "materialized_change_from": materialized_from_id,
            "materialized_change_to": materialized_to_id,
            "notes_enabled": (
                baseline is not None or authority_head_approval_id is None
            ),
            "baseline_id": (
                None if baseline is None else baseline.baseline_id.value
            ),
        }
        baseline_after = self.baseline_for_authority_head(
            authority_head_approval_id
        )
        status_after = self.authority.duet_status(self.identity.duet_id)
        if (
            canonical_json(status_after) != canonical_json(status)
            or (
                None if baseline_after is None else baseline_after.baseline_id
            )
            != (None if baseline is None else baseline.baseline_id)
        ):
            raise DuetConflictError(
                "workspace authority changed while its snapshot was captured"
            )
        return snapshot, baseline

    def snapshot(self) -> dict[str, Any]:
        snapshot, _baseline = self.context()
        return snapshot

    @staticmethod
    def _target_index(
        snapshot: Mapping[str, Any],
    ) -> dict[str, dict[str, Any]]:
        index = architecture_target_index(snapshot["architecture_snapshot"])
        materialized = snapshot["materialized_snapshot"]
        if materialized is not None and snapshot.get("baseline_id") is not None:
            for target_id, selection in materialized_target_index(
                materialized
            ).items():
                if target_id in index:
                    raise RefinementWorkspaceError(
                        "workspace target identity is duplicated across views"
                    )
                index[target_id] = selection
        return index

    def _selection_for_saved_note(
        self,
        note: DuetWorkspaceNote,
    ) -> dict[str, Any]:
        target = note.target
        if target.layer is RefinementTargetLayer.WORKFLOW_SEMANTICS:
            if note.baseline_id is None:
                draft = self.authority.read_episode_workflow_draft(
                    self.identity.duet_id,
                    target.artifact_id,
                )
                artifact = self.store.get_artifact(target.artifact_id.value)
                if (
                    artifact is None
                    or artifact["duet_id"] != self.identity.duet_id.value
                    or artifact["kind"]
                    != EPISODE_WORKFLOW_DRAFT_ARTIFACT_KIND
                    or artifact["content_hash"] != target.artifact_hash.value
                ):
                    raise DuetProtocolError(
                        "saved note Architecture artifact is absent or stale"
                    )
                architecture = {
                    "source_artifact_id": draft["artifact_id"],
                    "content_hash": draft["content_hash"],
                    "workflow_hash": draft["workflow_hash"],
                    "revision": draft["revision"],
                    "configuration": draft["workflow"],
                    "validation_deficits": list(
                        artifact["record"].get("validation_deficits") or ()
                    ),
                    "editable": False,
                    "pending_refinement": None,
                }
            else:
                baseline = self.refiner.load_baseline(note.baseline_id)
                _approval, frozen, _authority = (
                    self.authority.verify_workflow_approval(
                        baseline.workflow_approval_id
                    )
                )
                if (
                    target.artifact_id != frozen.artifact_id
                    or target.artifact_hash != frozen.workflow_hash
                ):
                    raise DuetProtocolError(
                        "saved note Architecture target differs from its baseline"
                    )
                architecture = {
                    "source_artifact_id": frozen.artifact_id.value,
                    "content_hash": frozen.workflow_hash.value,
                    "workflow_hash": frozen.workflow_hash.value,
                    "revision": frozen.revision,
                    "configuration": workflow_blueprint_from_spec(
                        frozen.workflow
                    ),
                    "validation_deficits": [],
                    "editable": False,
                    "pending_refinement": None,
                }
            selection = architecture_target_index(architecture).get(
                target.target_id.value
            )
        else:
            if note.baseline_id is None:
                raise DuetProtocolError(
                    "saved materialization note has no refinement baseline"
                )
            baseline = self.refiner.load_baseline(note.baseline_id)
            specification, receipt, manifest = self.materialized_context(
                baseline
            )
            materialized = materialized_workspace_projection(
                specification,
                receipt,
                manifest,
            )
            selection = materialized_target_index(materialized).get(
                target.target_id.value
            )
        if (
            selection is None
            or selection["target_metadata"] != target.as_record()
        ):
            raise DuetProtocolError(
                "saved note target is absent from its exact persisted artifact"
            )
        return selection

    @staticmethod
    def _selection_response(
        *,
        baseline_id: Optional[str],
        selection: Mapping[str, Any],
        notes: list[dict[str, str]],
        run_reference: Optional[Mapping[str, Any]],
    ) -> dict[str, Any]:
        return {
            "baseline_id": baseline_id,
            "part_kind": selection["part_kind"],
            "selected_part": selection["selected_part"],
            "target_metadata": selection["target_metadata"],
            "human_notes": notes,
            "evidence": {
                "selected_part_evidence": selection["evidence"],
                "run_audit": (
                    None if run_reference is None else dict(run_reference)
                ),
            },
        }

    def read_target(self, *, target_id: str) -> dict[str, Any]:
        if not isinstance(target_id, str) or not target_id.strip():
            raise ValueError("target_id must be non-empty text")
        snapshot, baseline = self.context()
        selection = self._target_index(snapshot).get(target_id)
        if selection is None:
            raise DuetProtocolError("workspace target is absent or stale")
        notes = [
            {
                "note_id": note["note_id"],
                "target_id": note["target"]["target_id"],
                "body": note["body"],
            }
            for note in snapshot["notes"]
            if note["target"]["target_id"] == target_id
        ]
        return self._selection_response(
            baseline_id=snapshot["baseline_id"],
            selection=selection,
            notes=notes,
            run_reference=self.run_reference_data(baseline),
        )

    def read_note(self, *, note_id: str) -> dict[str, Any]:
        if not isinstance(note_id, str) or not note_id.strip():
            raise ValueError("note_id must be non-empty text")
        try:
            note = self.refiner.load_note(OpaqueId(note_id))
        except DuetNotFoundError as exc:
            raise DuetProtocolError(
                "saved workspace note is absent or stale"
            ) from exc
        if note.human_authority_id != self.identity.human_authority_id:
            raise DuetProtocolError(
                "saved workspace note belongs to another human authority"
            )
        selection = self._selection_for_saved_note(note)
        baseline = (
            None
            if note.baseline_id is None
            else self.refiner.load_baseline(note.baseline_id)
        )
        return self._selection_response(
            baseline_id=(
                None if note.baseline_id is None else note.baseline_id.value
            ),
            selection=selection,
            notes=[
                {
                    "note_id": note.note_id.value,
                    "target_id": note.target.target_id.value,
                    "body": note.body,
                }
            ],
            run_reference=self.run_reference_data(baseline),
        )

    def read(
        self,
        *,
        target_id: Optional[str] = None,
        note_id: Optional[str] = None,
    ) -> dict[str, Any]:
        if (target_id is None) == (note_id is None):
            raise ValueError("provide exactly one of target_id or note_id")
        if target_id is not None:
            return self.read_target(target_id=target_id)
        return self.read_note(note_id=note_id or "")

    @staticmethod
    def _validate_idempotency_key(idempotency_key: str) -> None:
        if (
            not isinstance(idempotency_key, str)
            or not idempotency_key.strip()
            or "\x00" in idempotency_key
            or len(idempotency_key) > 256
        ):
            raise ValueError("idempotency_key must be bounded non-empty text")

    def record_note(
        self,
        target_record: Mapping[str, Any],
        body: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._validate_idempotency_key(idempotency_key)
        target = RefinementTarget.from_record(target_record)
        with self._note_lock:
            snapshot, baseline = self.context()
            if not bool(snapshot.get("notes_enabled")):
                raise DuetProtocolError(
                    "notes become available after the latest Architecture is materialized"
                )
            selection = self._target_index(snapshot).get(target.target_id.value)
            if (
                selection is None
                or selection["target_metadata"] != target.as_record()
            ):
                raise DuetProtocolError(
                    "workspace note target is absent or stale"
                )
            notes = self.refiner.record_workspace_notes(
                self.identity,
                baseline_id=(None if baseline is None else baseline.baseline_id),
                body=body,
                targets=(target,),
                idempotency_keys=(idempotency_key,),
            )
            if len(notes) != 1:
                raise RefinementWorkspaceError(
                    "workspace note persistence returned wrong arity"
                )
            return notes[0].as_record()

    def record_global_instruction(
        self,
        body: str,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], ...]:
        """Atomically anchor one human prompt to both exact workspace layers."""

        self._validate_idempotency_key(idempotency_key)
        status = self.authority.duet_status(self.identity.duet_id)
        if status["state"] != DuetDesignState.SEALED.value:
            return ()
        snapshot, baseline = self.context()
        if baseline is None or snapshot["materialized_snapshot"] is None:
            return ()
        if snapshot["baseline_id"] != baseline.baseline_id.value:
            return ()
        selections = self._target_index(snapshot)
        architecture_roots = tuple(
            selection
            for selection in selections.values()
            if selection["target_metadata"]["layer"]
            == RefinementTargetLayer.WORKFLOW_SEMANTICS.value
            and selection["target_metadata"]["json_pointer"] == ""
            and selection["target_metadata"]["episode_local_id"] is None
            and selection["target_metadata"]["artifact_id"]
            == baseline.frozen_workflow_artifact_id.value
            and selection["target_metadata"]["artifact_hash"]
            == baseline.workflow_hash.value
        )
        materialized_roots = tuple(
            selection
            for selection in selections.values()
            if selection["part_kind"] == "materialized"
            and selection["selected_part"].get("key") == "workflow_overview"
            and selection["target_metadata"]["layer"]
            == RefinementTargetLayer.MATERIALIZATION_IMPLEMENTATION.value
            and selection["target_metadata"]["json_pointer"]
            == "/workflow_global"
            and selection["target_metadata"]["episode_local_id"] is None
            and selection["target_metadata"]["artifact_id"]
            == baseline.materialized_specification_id.value
            and selection["target_metadata"]["artifact_hash"]
            == baseline.materialized_specification_hash.value
        )
        if len(architecture_roots) != 1 or len(materialized_roots) != 1:
            raise RefinementWorkspaceError(
                "stable workspace has no single exact target per layer"
            )
        targets = (
            RefinementTarget.from_record(
                architecture_roots[0]["target_metadata"]
            ),
            RefinementTarget.from_record(
                materialized_roots[0]["target_metadata"]
            ),
        )
        with self._note_lock:
            notes = self.refiner.record_workspace_notes(
                self.identity,
                baseline_id=baseline.baseline_id,
                body=body,
                targets=targets,
                idempotency_keys=tuple(
                    f"{idempotency_key}:{target.layer.value}"
                    for target in targets
                ),
            )
        return tuple(note.as_record() for note in notes)


__all__ = [
    "RefinementWorkspace",
    "RefinementWorkspaceError",
    "WorkspaceAuthorityReader",
    "architecture_target_index",
    "materialized_target_index",
    "materialized_projection_changes",
    "materialized_workspace_projection",
]
