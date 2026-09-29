"""Trusted orchestration semantics for declarative nested Creator instances."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Callable, Iterable, Mapping, Optional

from agent.duet_contracts import canonical_json
from agent.episode_contracts import (
    EVIDENCE_GATE_SCORE_PROGRESS_ADAPTER,
    OpaqueId,
    Sha256Digest,
)
from agent.generic_creator_models import (
    ArtifactReference,
    CreatorFaultRecord,
    CreatorRepairRequest,
    EvidenceGateManifest,
    FaultStatus,
    GateRequirement,
    GenericCreatorInstanceSpec,
    GenericCreatorStatus,
    GenericCreatorType,
    PlatformPatchProposal,
    RepairStatus,
)
from agent.generic_creator_store import (
    GenericCreatorConflictError,
    GenericCreatorNotFoundError,
    GenericCreatorStore,
)
from agent.generic_creator_templates import (
    select_rarefaction_candidate,
    validate_template_result,
    validate_template_spec,
)


_EFFECTFUL_CAPABILITIES = frozenset(
    {"write_file", "patch", "terminal", "execute_code", "process_manage"}
)
_TERMINAL_STATUSES = frozenset(
    {
        GenericCreatorStatus.SUCCEEDED,
        GenericCreatorStatus.FAILED,
        GenericCreatorStatus.CANCELLED,
        GenericCreatorStatus.INVALIDATED,
    }
)


@dataclass(frozen=True)
class IsolatedExecutorAttestation:
    """A host-issued claim about mechanical execution boundaries."""

    executor_id: str
    filesystem_namespace_isolated: bool
    process_namespace_isolated: bool
    process_ownership_enforced: bool
    host_runtime_read_only: bool

    @property
    def permits_effectful_recursion(self) -> bool:
        return all(
            (
                self.filesystem_namespace_isolated,
                self.process_namespace_isolated,
                self.process_ownership_enforced,
                self.host_runtime_read_only,
            )
        )


@dataclass(frozen=True)
class GenericCreatorHostPolicy:
    allowed_capabilities: frozenset[str]
    recursive_creators_enabled: bool = False
    maximum_depth: int = 1
    maximum_descendants: int = 0
    isolated_executor: Optional[IsolatedExecutorAttestation] = None

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_capabilities, frozenset):
            raise ValueError("allowed_capabilities must be a frozenset")
        if self.maximum_depth < 1 or self.maximum_descendants < 0:
            raise ValueError("host depth and descendant limits are invalid")


def compute_runtime_identity(source_root: str | Path) -> Sha256Digest:
    """Hash the executable plus the loaded generic Creator control plane."""

    root = Path(source_root).resolve()
    paths = (
        Path(sys.executable).resolve(),
        root / "agent" / "duet_service.py",
        root / "agent" / "duet_store.py",
        root / "agent" / "episode_contract_models.py",
        root / "agent" / "episode_progress_adapters.py",
        root / "agent" / "openchia_agents.py",
        root / "agent" / "openchia_host.py",
        root / "agent" / "tool_executor.py",
        root / "agent" / "generic_creator_models.py",
        root / "agent" / "generic_creator_templates.py",
        root / "agent" / "generic_creator_store.py",
        root / "agent" / "generic_creator_runtime.py",
        root / "agent" / "openchia_execution_boundary.py",
    )
    material = bytearray()
    for path in paths:
        material.extend(str(path).encode())
        material.extend(b"\0")
        try:
            material.extend(path.read_bytes())
        except OSError as exc:
            raise RuntimeError(f"cannot establish runtime identity for {path}") from exc
        material.extend(b"\0")
    return Sha256Digest.of_bytes(bytes(material))


def evidence_gate_score(
    manifest: EvidenceGateManifest,
    accepted_evidence: Mapping[str, tuple[OpaqueId, ...]],
) -> float:
    """Compute required-gate credit from host-accepted evidence only."""

    by_id = {gate.gate_id: gate for gate in manifest.gates}
    accepted: set[str] = set()
    changed = True
    while changed:
        changed = False
        for gate in manifest.gates:
            evidence = set(accepted_evidence.get(gate.gate_id, ()))
            if (
                gate.gate_id not in accepted
                and len(evidence) >= gate.minimum_evidence_count
                and set(gate.dependencies).issubset(accepted)
            ):
                accepted.add(gate.gate_id)
                changed = True
    required = [gate for gate in by_id.values() if gate.requirement is GateRequirement.REQUIRED]
    total = sum(gate.weight for gate in required)
    if total <= 0:
        raise ValueError("evidence-gate manifests need positive required-gate weight")
    score = sum(gate.weight for gate in required if gate.gate_id in accepted)
    return score / total


class GenericCreatorEngine:
    """Host-owned authority tree and work-graph controller."""

    def __init__(
        self,
        *,
        store: GenericCreatorStore,
        policy: GenericCreatorHostPolicy,
        source_root: str | Path,
        runtime_identity_provider: Optional[Callable[[], Sha256Digest]] = None,
    ) -> None:
        self.store = store
        self.policy = policy
        self.source_root = Path(source_root).resolve()
        self._runtime_identity_provider = runtime_identity_provider or (
            lambda: compute_runtime_identity(self.source_root)
        )

    def _identity(self) -> Sha256Digest:
        identity = self._runtime_identity_provider()
        if not isinstance(identity, Sha256Digest):
            raise TypeError("runtime identity provider must return Sha256Digest")
        return identity

    def execution_boundary(
        self,
        *,
        workspace_roots: Iterable[str | Path],
        additional_protected_roots: Iterable[str | Path] = (),
        owned_process_sessions: Iterable[str] = (),
    ):
        """Build the boundary that protects this engine and its authority DB."""

        from agent.openchia_execution_boundary import OpenChiaExecutionBoundary

        database_paths = (
            self.store.path,
            Path(f"{self.store.path}-wal"),
            Path(f"{self.store.path}-shm"),
        )
        return OpenChiaExecutionBoundary(
            workspace_roots=tuple(Path(item) for item in workspace_roots),
            protected_roots=(
                self.source_root,
                *database_paths,
                *(Path(item) for item in additional_protected_roots),
            ),
            isolated_executor=self.policy.isolated_executor,
            owned_process_sessions=frozenset(owned_process_sessions),
        )

    def _validate_capabilities(self, spec: GenericCreatorInstanceSpec) -> None:
        if spec.progress_measurement.adapter_id != EVIDENCE_GATE_SCORE_PROGRESS_ADAPTER:
            raise GenericCreatorConflictError(
                "generic Creators require the host-only evidence_gate_score_v1 adapter"
            )
        requested = set(spec.assignable_capabilities)
        if not requested.issubset(self.policy.allowed_capabilities):
            raise GenericCreatorConflictError("Creator requests capabilities outside host policy")
        if requested & _EFFECTFUL_CAPABILITIES:
            attestation = self.policy.isolated_executor
            if attestation is None or not attestation.permits_effectful_recursion:
                raise GenericCreatorConflictError(
                    "effectful recursive capabilities require an attested isolated executor"
                )

    def _verify_artifacts(self, spec: GenericCreatorInstanceSpec) -> None:
        for reference in spec.input_artifacts:
            artifact = self.store.artifact(reference.artifact_id)
            if artifact["content_hash"] != reference.content_hash.value:
                raise GenericCreatorConflictError("input artifact hash does not match durable content")

    def admit_root(self, spec: GenericCreatorInstanceSpec) -> None:
        if spec.parent_instance_id is not None:
            raise GenericCreatorConflictError("root Creator must not name a parent")
        validate_template_spec(spec)
        self._validate_capabilities(spec)
        if spec.maximum_depth > self.policy.maximum_depth:
            raise GenericCreatorConflictError("Creator depth exceeds host policy")
        if spec.maximum_child_episodes > self.policy.maximum_descendants:
            raise GenericCreatorConflictError("Creator child budget exceeds host policy")
        self._verify_artifacts(spec)
        identity = self._identity()
        self.store.create_instance(
            spec, root_instance_id=spec.instance_id, depth=0, runtime_identity=identity
        )
        self._initialize_template(spec)
        self.store.audit(spec.instance_id, "root_admitted", {"runtime_identity": identity.value})

    def admit_child(self, spec: GenericCreatorInstanceSpec) -> None:
        if spec.parent_instance_id is None:
            raise GenericCreatorConflictError("nested Creator must name one owning parent")
        validate_template_spec(spec)
        parent = self.store.instance(spec.parent_instance_id)
        self.verify_runtime_identity(spec.parent_instance_id)
        parent_spec: GenericCreatorInstanceSpec = parent["spec"]
        if parent["status"] in _TERMINAL_STATUSES:
            raise GenericCreatorConflictError("a terminal parent cannot admit descendants")
        if not self.policy.recursive_creators_enabled or not parent_spec.may_create_child_creators:
            raise GenericCreatorConflictError("recursive Creator assignment is not permitted")
        if not set(spec.assignable_capabilities).issubset(parent_spec.assignable_capabilities):
            raise GenericCreatorConflictError("child capabilities must be a subset of the parent grant")
        if not parent_spec.immutable_parent_success_criteria_refs:
            raise GenericCreatorConflictError(
                "recursive parent must declare immutable success-criteria references"
            )
        if (
            spec.immutable_parent_success_criteria_refs
            != parent_spec.immutable_parent_success_criteria_refs
        ):
            raise GenericCreatorConflictError(
                "child must preserve the parent's exact immutable success-criteria references"
            )
        self._validate_capabilities(spec)
        depth = int(parent["depth"]) + 1
        root = self.store.instance(parent["root_instance_id"])
        root_spec: GenericCreatorInstanceSpec = root["spec"]
        if depth > min(self.policy.maximum_depth, parent_spec.maximum_depth, root_spec.maximum_depth):
            raise GenericCreatorConflictError("recursive depth limit exceeded")
        if len(self.store.descendants(parent["root_instance_id"])) >= self.policy.maximum_descendants:
            raise GenericCreatorConflictError("aggregate descendant limit exceeded")
        if not spec.shared_state_namespace.startswith(f"{parent_spec.shared_state_namespace}/"):
            raise GenericCreatorConflictError("child namespace must be owned beneath the parent namespace")
        self._verify_artifacts(spec)
        self.store.create_child_instance(
            spec,
            root_instance_id=parent["root_instance_id"],
            depth=depth,
            runtime_identity=self._identity(),
        )
        self._initialize_template(spec)
        self.store.audit(spec.instance_id, "child_admitted", {"parent_instance_id": parent_spec.instance_id})

    def _initialize_template(self, spec: GenericCreatorInstanceSpec) -> None:
        if spec.creator_type is GenericCreatorType.WORKLIST_FACTORY_CREATOR:
            gates = spec.work_definition["per_item_acceptance_gates"]
            check_ids = [
                item if isinstance(item, str) else str(item.get("gate_id", ""))
                for item in gates
            ]
            if any(not item for item in check_ids):
                raise ValueError("worklist acceptance gates need gate_id values")
            self.store.initialize_worklist(
                spec.instance_id, list(spec.work_definition["items"]), check_ids
            )
        elif spec.creator_type is GenericCreatorType.INTEGRATION_HANDOFF_CREATOR:
            owners = spec.work_definition["gate_ownership"]
            for edge in spec.work_definition["dependency_edges"]:
                if not isinstance(edge, Mapping) or not isinstance(edge.get("edge_id"), str):
                    raise ValueError("integration dependency edges need edge_id values")
                artifacts = tuple(str(item) for item in edge.get("artifact_ids", ()))
                self.store.put_integration_edge(
                    spec.instance_id,
                    edge["edge_id"],
                    owner_instance_id=owners.get(edge["edge_id"]),
                    artifact_ids=artifacts,
                )

    def verify_runtime_identity(self, instance_id: str) -> None:
        admitted = self.store.instance(instance_id)["runtime_identity"]
        current = self._identity()
        if current != admitted:
            self.store.set_status(instance_id, GenericCreatorStatus.INVALIDATED)
            self.cancel(instance_id, invalidated=True)
            raise GenericCreatorConflictError("executing host identity changed during the run")

    def start(self, instance_id: str) -> None:
        self.verify_runtime_identity(instance_id)
        current = self.store.instance(instance_id)["status"]
        if current not in {GenericCreatorStatus.ADMITTED, GenericCreatorStatus.WAITING, GenericCreatorStatus.REPAIRING}:
            raise GenericCreatorConflictError(f"cannot start Creator in {current.value} status")
        self.store.set_status(instance_id, GenericCreatorStatus.RUNNING)

    def consume_iteration(self, instance_id: str, *, elapsed: float = 0.0) -> None:
        self.verify_runtime_identity(instance_id)
        if not self.store.consume(instance_id, iterations=1, elapsed=elapsed):
            self.store.set_status(instance_id, GenericCreatorStatus.BLOCKED)
            self.store.audit(instance_id, "resource_cap_reached", {"elapsed_requested": elapsed})
            raise GenericCreatorConflictError("Creator resource cap reached; cap exhaustion is not success")

    def cancel(self, instance_id: str, *, invalidated: bool = False) -> None:
        descendants = self.store.descendants(instance_id)
        status = GenericCreatorStatus.INVALIDATED if invalidated else GenericCreatorStatus.CANCELLED
        for child_id in reversed(descendants):
            if self.store.instance(child_id)["status"] not in _TERMINAL_STATUSES:
                self.store.set_status(child_id, status)
            self.store.return_unused_budget(child_id)
        if self.store.instance(instance_id)["status"] not in _TERMINAL_STATUSES or invalidated:
            self.store.set_status(instance_id, status)
        self.store.return_unused_budget(instance_id)

    def complete(self, instance_id: str, manifest_id: str) -> float:
        self.verify_runtime_identity(instance_id)
        spec: GenericCreatorInstanceSpec = self.store.instance(instance_id)["spec"]
        if manifest_id != spec.progress_measurement.gate_manifest_id:
            raise GenericCreatorConflictError(
                "completion manifest does not belong to this Creator instance"
            )
        manifest = self.store.latest_manifest(manifest_id)
        score = evidence_gate_score(manifest, self.store.accepted_evidence(manifest))
        if score < spec.target:
            raise GenericCreatorConflictError("required host-accepted gate score has not reached target")
        descendants = self.store.descendants(instance_id)
        if any(self.store.instance(child)["status"] not in _TERMINAL_STATUSES for child in descendants):
            raise GenericCreatorConflictError("cannot complete while descendants remain active")
        self.store.set_status(instance_id, GenericCreatorStatus.SUCCEEDED)
        self.store.return_unused_budget(instance_id)
        self.store.audit(instance_id, "completed", {"normalized_score": score})
        return score

    def current_score(self, manifest_id: str) -> float:
        manifest = self.store.latest_manifest(manifest_id)
        return evidence_gate_score(manifest, self.store.accepted_evidence(manifest))

    def register_gate_manifest(
        self, instance_id: str, manifest: EvidenceGateManifest, *, approved: bool
    ) -> None:
        self.verify_runtime_identity(instance_id)
        self.store.put_manifest(instance_id, manifest, approved=approved)

    def accept_gate_evidence(
        self,
        instance_id: str,
        *,
        manifest: EvidenceGateManifest,
        gate_id: str,
        evidence_id: OpaqueId,
        evidence_kind: str,
        acceptance_source: str,
        evidence_hash: Sha256Digest,
    ) -> None:
        """Host-only acceptance API; there is no model-settable acceptance flag."""

        self.verify_runtime_identity(instance_id)
        spec: GenericCreatorInstanceSpec = self.store.instance(instance_id)["spec"]
        if manifest.manifest_id != spec.progress_measurement.gate_manifest_id:
            raise GenericCreatorConflictError("evidence manifest does not belong to the instance")
        self.store.accept_gate_evidence(
            manifest=manifest,
            gate_id=gate_id,
            evidence_id=evidence_id,
            evidence_kind=evidence_kind,
            acceptance_source=acceptance_source,
            evidence_hash=evidence_hash,
            host_accepted=True,
        )

    def retry_work_item(self, instance_id: str, item_id: str, *, evidence_sequence: int) -> None:
        self.verify_runtime_identity(instance_id)
        spec: GenericCreatorInstanceSpec = self.store.instance(instance_id)["spec"]
        item = next(
            (item for item in self.store.work_items(instance_id) if item["item_id"] == item_id),
            None,
        )
        if item is None:
            raise GenericCreatorConflictError("unknown work item")
        if item["status"] not in {"blocked", "failed"}:
            raise GenericCreatorConflictError("only a blocked or failed work item can be retried")
        if item["attempt_count"] >= spec.retry_behavior.maximum_attempts:
            raise GenericCreatorConflictError("work item retry limit reached")
        if spec.retry_behavior.require_new_evidence and evidence_sequence <= item["last_evidence_sequence"]:
            raise GenericCreatorConflictError("retry requires new evidence or a bounded repair request")
        self.store.update_work_item(
            instance_id, item_id, status="active", evidence_sequence=evidence_sequence,
            increment_attempt=True,
        )

    def start_work_item(self, instance_id: str, item_id: str) -> None:
        self.verify_runtime_identity(instance_id)
        item = next(
            (item for item in self.store.work_items(instance_id) if item["item_id"] == item_id),
            None,
        )
        if item is None or item["status"] != "pending":
            raise GenericCreatorConflictError("only a pending work item can start")
        self.store.update_work_item(
            instance_id, item_id, status="active", increment_attempt=True
        )

    def fail_work_item(
        self, instance_id: str, item_id: str, *, evidence_sequence: int, blocked: bool = False
    ) -> None:
        self.verify_runtime_identity(instance_id)
        item = next(
            (item for item in self.store.work_items(instance_id) if item["item_id"] == item_id),
            None,
        )
        if item is None or item["status"] != "active":
            raise GenericCreatorConflictError("only an active work item can fail or block")
        if evidence_sequence <= item["last_evidence_sequence"]:
            raise GenericCreatorConflictError("failure transition requires new evidence")
        self.store.update_work_item(
            instance_id, item_id, status="blocked" if blocked else "failed",
            evidence_sequence=evidence_sequence,
        )

    def accept_work_item(
        self,
        instance_id: str,
        item_id: str,
        *,
        artifact_id: OpaqueId,
        independently_accepted_checks: Mapping[str, OpaqueId],
        evidence_sequence: int,
    ) -> None:
        self.verify_runtime_identity(instance_id)
        item = next(
            (item for item in self.store.work_items(instance_id) if item["item_id"] == item_id),
            None,
        )
        if item is None or item["status"] != "active":
            raise GenericCreatorConflictError("only an active work item can be accepted")
        spec: GenericCreatorInstanceSpec = self.store.instance(instance_id)["spec"]
        if any(
            not self.store.evidence_belongs_to_manifest(
                evidence_id, spec.progress_measurement.gate_manifest_id
            )
            for evidence_id in independently_accepted_checks.values()
        ):
            raise GenericCreatorConflictError(
                "work item checks must reference host-accepted evidence"
            )
        used_elsewhere = {
            evidence_id
            for other in self.store.work_items(instance_id)
            if other["item_id"] != item_id and isinstance(other["accepted_checks"], dict)
            for evidence_id in other["accepted_checks"].values()
        }
        if any(item.value in used_elsewhere for item in independently_accepted_checks.values()):
            raise GenericCreatorConflictError(
                "per-item acceptance evidence cannot be reused by another work item"
            )
        self.store.artifact(artifact_id)
        self.store.update_work_item(
            instance_id,
            item_id,
            status="accepted",
            artifact_id=artifact_id,
            accepted_checks=independently_accepted_checks,
            evidence_sequence=evidence_sequence,
        )

    def report_fault(self, fault: CreatorFaultRecord) -> None:
        self.verify_runtime_identity(fault.reporting_instance_id)
        reporter = self.store.instance(fault.reporting_instance_id)
        if fault.owning_instance_id is not None:
            owner = self.store.instance(fault.owning_instance_id)
            if owner["root_instance_id"] != reporter["root_instance_id"]:
                raise GenericCreatorConflictError("fault owner is outside the reporting authority tree")
        for reference in fault.artifact_references + (fault.reproducible_test_reference,):
            artifact = self.store.artifact(reference.artifact_id)
            if artifact["content_hash"] != reference.content_hash.value:
                raise GenericCreatorConflictError("fault references an artifact with the wrong hash")
        for evidence_id in fault.accepted_evidence_ids:
            evidence_owners = self.store.evidence_instance_ids(evidence_id)
            if not evidence_owners or any(
                self.store.instance(owner)["root_instance_id"] != reporter["root_instance_id"]
                for owner in evidence_owners
            ):
                raise GenericCreatorConflictError(
                    "fault evidence must be host-accepted within the same authority tree"
                )
        self.store.put_fault(fault)
        self.store.audit(fault.reporting_instance_id, "fault_reported", fault.as_record())

    def request_repair(self, repair: CreatorRepairRequest) -> None:
        fault = self.store.fault(repair.fault_id)
        self.verify_runtime_identity(fault.reporting_instance_id)
        if not fault.retryable or fault.status is not FaultStatus.OPEN:
            raise GenericCreatorConflictError("fault is not open and retryable")
        if fault.owning_instance_id != repair.owning_instance_id:
            raise GenericCreatorConflictError("repair must reopen the recorded owner")
        if not set(repair.allowed_scope).issubset(fault.suggested_repair_scope):
            raise GenericCreatorConflictError("repair request expands beyond the fault scope")
        if repair.repair_budget > fault.remaining_repair_budget:
            raise GenericCreatorConflictError("repair budget exceeds the fault's remaining budget")
        if not set(fault.accepted_evidence_ids).issubset(repair.preserved_evidence_ids):
            raise GenericCreatorConflictError("repair must preserve accepted evidence")
        edges: list[tuple[str, str]] = []
        for edge_id in repair.integration_edge_ids_to_retest:
            reporting = fault.reporting_instance_id
            edge = next(
                (item for item in self.store.integration_edges(reporting) if item["edge_id"] == edge_id),
                None,
            )
            if edge is None:
                raise GenericCreatorConflictError("repair names an unknown integration edge")
            edges.append((reporting, edge_id))
        self.store.put_repair(repair)
        self.store.set_status(repair.owning_instance_id, GenericCreatorStatus.REPAIRING)
        for reporting, edge_id in edges:
            self.store.set_integration_edge(
                reporting, edge_id, status="pending", evidence_ids=(), retest_required=True
            )

    def verify_repair(self, repair_id: OpaqueId) -> None:
        """Close a repair only after every declared integration retest passes."""

        repair = self.store.repair(repair_id)
        fault = self.store.fault(repair.fault_id)
        self.verify_runtime_identity(fault.reporting_instance_id)
        for edge_id in repair.integration_edge_ids_to_retest:
            edge = next(
                (
                    item for item in self.store.integration_edges(fault.reporting_instance_id)
                    if item["edge_id"] == edge_id
                ),
                None,
            )
            if edge is None or edge["status"] != "accepted" or edge["retest_required"]:
                raise GenericCreatorConflictError(
                    "repair cannot verify before affected integration edges are retested"
                )
        self.store.update_repair_status(
            repair_id,
            repair_status=RepairStatus.VERIFIED,
            fault_status=FaultStatus.VERIFIED,
        )
        self.store.set_status(repair.owning_instance_id, GenericCreatorStatus.WAITING)

    def select_next_work(self, instance_id: str) -> dict[str, object]:
        self.verify_runtime_identity(instance_id)
        spec: GenericCreatorInstanceSpec = self.store.instance(instance_id)["spec"]
        if spec.creator_type is not GenericCreatorType.RAREFACTION_PORTFOLIO_CREATOR:
            raise GenericCreatorConflictError("instance is not a rarefaction portfolio Creator")
        return select_rarefaction_candidate(spec.work_definition)

    def admit_orchestrator_children(
        self,
        instance_id: str,
        child_specs: tuple[GenericCreatorInstanceSpec, ...],
    ) -> None:
        """Admit the orchestrator's declared children with resume-safe identity."""

        self.verify_runtime_identity(instance_id)
        orchestrator: GenericCreatorInstanceSpec = self.store.instance(instance_id)["spec"]
        if orchestrator.creator_type is not GenericCreatorType.GENERIC_ORCHESTRATOR_CREATOR:
            raise GenericCreatorConflictError("instance is not a generic orchestrator")
        expected = set(orchestrator.work_definition["template_instance_ids"])
        supplied = {item.instance_id for item in child_specs}
        if supplied != expected or len(supplied) != len(child_specs):
            raise GenericCreatorConflictError(
                "orchestrator child specs must exactly match declared template instance IDs"
            )
        by_id = {item.instance_id: item for item in child_specs}
        expected_roles = {
            orchestrator.work_definition["rarefaction_instance_id"]:
                GenericCreatorType.RAREFACTION_PORTFOLIO_CREATOR,
            orchestrator.work_definition["integration_instance_id"]:
                GenericCreatorType.INTEGRATION_HANDOFF_CREATOR,
            orchestrator.work_definition["qualification_instance_id"]:
                GenericCreatorType.QUALIFICATION_RELEASE_CREATOR,
        }
        for child_id, creator_type in expected_roles.items():
            if by_id[child_id].creator_type is not creator_type:
                raise GenericCreatorConflictError(
                    f"orchestrator child {child_id!r} must use {creator_type.value}"
                )
        for child_spec in child_specs:
            if child_spec.parent_instance_id != instance_id:
                raise GenericCreatorConflictError(
                    "orchestrator child must name the orchestrator as authority parent"
                )
            try:
                existing = self.store.instance(child_spec.instance_id)["spec"]
            except GenericCreatorNotFoundError:
                self.admit_child(child_spec)
            else:
                if existing.content_hash != child_spec.content_hash:
                    raise GenericCreatorConflictError(
                        "resumed orchestrator child identity conflicts with durable state"
                    )

    def orchestrator_next_action(self, instance_id: str) -> dict[str, object]:
        """Return a deterministic host decision over declared child state."""

        self.verify_runtime_identity(instance_id)
        spec: GenericCreatorInstanceSpec = self.store.instance(instance_id)["spec"]
        if spec.creator_type is not GenericCreatorType.GENERIC_ORCHESTRATOR_CREATOR:
            raise GenericCreatorConflictError("instance is not a generic orchestrator")
        statuses: dict[str, str] = {}
        for child_id in spec.work_definition["template_instance_ids"]:
            try:
                statuses[child_id] = self.store.instance(child_id)["status"].value
            except GenericCreatorNotFoundError:
                return {
                    "decision": "admit_declared_child",
                    "instance_id": child_id,
                    "instance_statuses": statuses,
                }
        for child_id in spec.work_definition["template_instance_ids"]:
            status = GenericCreatorStatus(statuses[child_id])
            if status in {GenericCreatorStatus.FAILED, GenericCreatorStatus.INVALIDATED}:
                return {
                    "decision": "route_fault",
                    "instance_id": child_id,
                    "instance_statuses": statuses,
                }
            if status not in {GenericCreatorStatus.SUCCEEDED, GenericCreatorStatus.CANCELLED}:
                return {
                    "decision": "run_instance",
                    "instance_id": child_id,
                    "instance_statuses": statuses,
                }
        return {
            "decision": "qualify_or_complete",
            "instance_id": spec.work_definition["qualification_instance_id"],
            "instance_statuses": statuses,
        }

    def materialize_template_result(
        self,
        instance_id: str,
        producing_episode_id: str,
        result: Mapping[str, object],
        *,
        expected_revision: Optional[int] = None,
    ) -> ArtifactReference:
        """Validate and content-address one task-independent template result."""

        self.verify_runtime_identity(instance_id)
        spec: GenericCreatorInstanceSpec = self.store.instance(instance_id)["spec"]
        validate_template_result(spec, result)
        artifact_id, digest, _ = self.store.put_artifact(
            producer_instance_id=instance_id,
            producing_episode_id=producing_episode_id,
            namespace=spec.shared_state_namespace,
            artifact_key="template_result",
            kind=f"{spec.creator_type.value}_result",
            record=result,
            expected_revision=expected_revision,
        )
        return ArtifactReference(artifact_id, digest)

    def accept_integration_edge(
        self,
        instance_id: str,
        edge_id: str,
        *,
        evidence_ids: tuple[OpaqueId, ...],
    ) -> None:
        self.verify_runtime_identity(instance_id)
        spec: GenericCreatorInstanceSpec = self.store.instance(instance_id)["spec"]
        if spec.creator_type is not GenericCreatorType.INTEGRATION_HANDOFF_CREATOR:
            raise GenericCreatorConflictError("only an integration Creator can accept an edge")
        if not evidence_ids:
            raise GenericCreatorConflictError("an integration edge needs independent accepted evidence")
        if any(
            not self.store.evidence_belongs_to_manifest(
                item, spec.progress_measurement.gate_manifest_id
            )
            for item in evidence_ids
        ):
            raise GenericCreatorConflictError(
                "integration evidence must be accepted by the host evidence ledger"
            )
        edge = next(
            (item for item in self.store.integration_edges(instance_id) if item["edge_id"] == edge_id),
            None,
        )
        if edge is None:
            raise GenericCreatorConflictError("unknown integration edge")
        for artifact_id in edge["artifact_ids"]:
            self.store.artifact(OpaqueId(artifact_id))
        self.store.set_integration_edge(
            instance_id, edge_id, status="accepted",
            evidence_ids=evidence_ids, retest_required=False,
        )

    def qualify_release(
        self,
        instance_id: str,
        *,
        manifest_id: str,
        integrated_artifacts: tuple[ArtifactReference, ...],
        integration_instance_ids: tuple[str, ...],
        reproducible_test_reference: ArtifactReference,
        producing_episode_id: str,
    ) -> ArtifactReference:
        """Independently qualify hashes, required gates, and integration edges."""

        self.verify_runtime_identity(instance_id)
        spec: GenericCreatorInstanceSpec = self.store.instance(instance_id)["spec"]
        if spec.creator_type is not GenericCreatorType.QUALIFICATION_RELEASE_CREATOR:
            raise GenericCreatorConflictError("instance is not a qualification Creator")
        problems: list[tuple[str, Optional[str], dict[str, object], dict[str, object]]] = []
        try:
            test_artifact = self.store.artifact(reproducible_test_reference.artifact_id)
            if test_artifact["content_hash"] != reproducible_test_reference.content_hash.value:
                raise GenericCreatorConflictError("qualification test reference hash mismatch")
        except Exception as exc:
            raise GenericCreatorConflictError(
                "qualification requires a verified reproducible test artifact"
            ) from exc
        verified_artifacts: list[ArtifactReference] = []
        for reference in integrated_artifacts:
            try:
                stored = self.store.artifact(reference.artifact_id)
                if stored["content_hash"] != reference.content_hash.value:
                    raise GenericCreatorConflictError("content hash mismatch")
                verified_artifacts.append(reference)
            except Exception as exc:
                problems.append(
                    ("artifact_hash", None, {"error": type(exc).__name__}, {"verified": True})
                )
        manifest = self.store.latest_manifest(manifest_id)
        accepted = self.store.accepted_evidence(manifest)
        score = evidence_gate_score(manifest, accepted)
        declared_required = set(spec.work_definition["required_gates"])
        manifest_required = {
            gate.gate_id for gate in manifest.gates
            if gate.requirement is GateRequirement.REQUIRED
        }
        if not declared_required.issubset(manifest_required):
            problems.append(
                (
                    "required_gate_manifest", None,
                    {"missing_gate_ids": sorted(declared_required - manifest_required)},
                    {"all_declared_gates_present": True},
                )
            )
        if score < 1:
            problems.append(
                ("required_gates", None, {"normalized_score": score}, {"normalized_score": 1.0})
            )
        verified_edges: list[str] = []
        qualification_root = self.store.instance(instance_id)["root_instance_id"]
        for integration_id in integration_instance_ids:
            integration_instance = self.store.instance(integration_id)
            if integration_instance["root_instance_id"] != qualification_root:
                raise GenericCreatorConflictError(
                    "qualification cannot consume integration state from another authority tree"
                )
            for edge in self.store.integration_edges(integration_id):
                if edge["status"] != "accepted" or edge["retest_required"]:
                    problems.append(
                        (
                            edge["edge_id"], edge["owner_instance_id"],
                            {"status": edge["status"], "retest_required": edge["retest_required"]},
                            {"status": "accepted", "retest_required": False},
                        )
                    )
                else:
                    verified_edges.append(edge["edge_id"])
        expected_artifacts = set(
            spec.work_definition["integrated_artifact_graph"].get("artifact_ids", ())
        )
        provided_artifacts = {item.artifact_id.value for item in verified_artifacts}
        if not expected_artifacts.issubset(provided_artifacts):
            problems.append(
                (
                    "artifact_graph", None,
                    {"missing_artifact_ids": sorted(expected_artifacts - provided_artifacts)},
                    {"all_declared_artifacts_verified": True},
                )
            )
        if problems:
            evidence_ids = tuple(
                evidence_id for ids in accepted.values() for evidence_id in ids
            )
            fault_ids: list[str] = []
            for index, (failed, owner, observed, expected) in enumerate(problems):
                fault = CreatorFaultRecord(
                    fault_id=OpaqueId.mint(
                        "fault", f"qualification:{instance_id}:{failed}:{index}:{canonical_json(observed)}"
                    ),
                    reporting_instance_id=instance_id,
                    owning_instance_id=owner,
                    failed_gate_or_interface_edge=failed,
                    artifact_references=tuple(verified_artifacts),
                    observed_result=observed,
                    expected_result=expected,
                    accepted_evidence_ids=evidence_ids,
                    reproducible_test_reference=reproducible_test_reference,
                    severity="release_blocking",
                    retryable=owner is not None,
                    suggested_repair_scope=(failed,),
                    remaining_repair_budget=max(0, spec.retry_behavior.maximum_attempts),
                )
                self.report_fault(fault)
                fault_ids.append(fault.fault_id.value)
            raise GenericCreatorConflictError(
                f"qualification emitted release-blocking faults: {fault_ids}"
            )
        result = {
            "qualified": True,
            "package_artifact_id": None,
            "verified_gate_ids": sorted(accepted),
            "verified_edge_ids": sorted(verified_edges),
            "fault_ids": [],
        }
        # Package identity is the content-addressed result itself; a null field
        # avoids a recursive self-hash while preserving the typed envelope.
        return self.materialize_template_result(
            instance_id, producing_episode_id, result
        )

    def propose_platform_patch(
        self,
        instance_id: str,
        producing_episode_id: str,
        proposal: PlatformPatchProposal,
        *,
        expected_revision: Optional[int] = None,
    ) -> ArtifactReference:
        self.verify_runtime_identity(instance_id)
        spec: GenericCreatorInstanceSpec = self.store.instance(instance_id)["spec"]
        artifact_id, digest, _ = self.store.put_artifact(
            producer_instance_id=instance_id,
            producing_episode_id=producing_episode_id,
            namespace=spec.shared_state_namespace,
            artifact_key=f"platform_patch_{proposal.content_hash.value.removeprefix('sha256:')[:16]}",
            kind="platform_patch_proposal",
            record=proposal.as_record(),
            expected_revision=expected_revision,
        )
        self.store.audit(
            instance_id,
            "platform_patch_proposed_not_applied",
            {"artifact_id": artifact_id.value, "content_hash": digest.value},
        )
        return ArtifactReference(artifact_id, digest)


__all__ = [
    "EVIDENCE_GATE_SCORE_PROGRESS_ADAPTER",
    "GenericCreatorEngine",
    "GenericCreatorHostPolicy",
    "IsolatedExecutorAttestation",
    "compute_runtime_identity",
    "evidence_gate_score",
]
