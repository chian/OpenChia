"""Strict declarative records for task-independent generic Creator instances.

These records are control-plane inputs.  They contain no executable callbacks,
credentials, or model-authored authority.  Every record rejects unknown keys
and hashes its canonical JSON representation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Optional, TypeVar

from agent.duet_contracts import canonical_json
from agent.episode_contracts import OpaqueId, Sha256Digest


GENERIC_CREATOR_INSTANCE_SCHEMA_VERSION = 1
EVIDENCE_GATE_MANIFEST_SCHEMA_VERSION = 1
CREATOR_FAULT_SCHEMA_VERSION = 1
CREATOR_REPAIR_SCHEMA_VERSION = 1
PLATFORM_PATCH_SCHEMA_VERSION = 1

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_NAMESPACE = re.compile(r"^[a-z][a-z0-9_.:/-]{0,255}$")


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _keys(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"malformed {name}: missing={sorted(expected - actual)!r}, "
            f"unknown={sorted(actual - expected)!r}"
        )


def _text(value: object, name: str, *, maximum: int = 8192) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be non-empty text without NUL")
    if len(value) > maximum:
        raise ValueError(f"{name} must be at most {maximum} characters")
    return value


def _identifier(value: object, name: str) -> str:
    result = _text(value, name, maximum=128)
    if _IDENTIFIER.fullmatch(result) is None:
        raise ValueError(f"{name} must be a lowercase identifier")
    return result


def _namespace(value: object, name: str) -> str:
    result = _text(value, name, maximum=256)
    if _NAMESPACE.fullmatch(result) is None or ".." in result.split("/"):
        raise ValueError(f"{name} has an invalid namespace shape")
    return result


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return result


def _non_negative_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def _string_tuple(value: object, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be a tuple")
    result = tuple(_identifier(item, name) for item in value)
    if not allow_empty and not result:
        raise ValueError(f"{name} must not be empty")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must contain unique values")
    return result


def _json_object(value: object, name: str) -> Mapping[str, Any]:
    record = _mapping(value, name)
    # canonical_json performs the recursive JSON/finite-number validation.
    import json

    return MappingProxyType(json.loads(canonical_json(record)))


_EnumT = TypeVar("_EnumT", bound=Enum)


def _enum(enum_type: type[_EnumT], value: object, name: str) -> _EnumT:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"unsupported {name}: {value!r}") from exc


class GenericCreatorType(str, Enum):
    PLAN_CONTEXT_CREATOR = "plan_context_creator"
    WORKLIST_FACTORY_CREATOR = "worklist_factory_creator"
    AGENT_LOOP_DESIGNER_CREATOR = "agent_loop_designer_creator"
    INTEGRATION_HANDOFF_CREATOR = "integration_handoff_creator"
    RAREFACTION_PORTFOLIO_CREATOR = "rarefaction_portfolio_creator"
    QUALIFICATION_RELEASE_CREATOR = "qualification_release_creator"
    GENERIC_ORCHESTRATOR_CREATOR = "generic_orchestrator_creator"


class GenericCreatorStatus(str, Enum):
    PENDING = "pending"
    ADMITTED = "admitted"
    RUNNING = "running"
    WAITING = "waiting"
    BLOCKED = "blocked"
    REPAIRING = "repairing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INVALIDATED = "invalidated"


class CancellationBehavior(str, Enum):
    CASCADE_IMMEDIATELY = "cascade_immediately"
    CASCADE_AT_BOUNDARY = "cascade_at_boundary"


class WorkItemStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    FAILED = "failed"
    SKIPPED = "skipped"


class FaultStatus(str, Enum):
    OPEN = "open"
    REPAIR_REQUESTED = "repair_requested"
    REPAIRED = "repaired"
    VERIFIED = "verified"
    CLOSED = "closed"


class RepairStatus(str, Enum):
    REQUESTED = "requested"
    ACTIVE = "active"
    SUBMITTED = "submitted"
    VERIFIED = "verified"
    REJECTED = "rejected"


class GateRequirement(str, Enum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class GateAcceptanceState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ArtifactReference:
    artifact_id: OpaqueId
    content_hash: Sha256Digest

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, OpaqueId):
            raise ValueError("artifact_id must be an OpaqueId")
        if not isinstance(self.content_hash, Sha256Digest):
            raise ValueError("content_hash must be a Sha256Digest")

    def as_record(self) -> dict[str, str]:
        return {
            "artifact_id": self.artifact_id.value,
            "content_hash": self.content_hash.value,
        }

    @classmethod
    def from_record(cls, value: object) -> "ArtifactReference":
        record = _mapping(value, "artifact reference")
        _keys(record, {"artifact_id", "content_hash"}, "artifact reference")
        return cls(OpaqueId(record["artifact_id"]), Sha256Digest(record["content_hash"]))


@dataclass(frozen=True)
class GenericEvidenceRequirement:
    requirement_id: str
    evidence_kind_id: str
    acceptance_source_id: str
    minimum_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "requirement_id", _identifier(self.requirement_id, "requirement_id"))
        object.__setattr__(self, "evidence_kind_id", _identifier(self.evidence_kind_id, "evidence_kind_id"))
        object.__setattr__(self, "acceptance_source_id", _identifier(self.acceptance_source_id, "acceptance_source_id"))
        object.__setattr__(self, "minimum_count", _positive_int(self.minimum_count, "minimum_count"))

    def as_record(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "evidence_kind_id": self.evidence_kind_id,
            "acceptance_source_id": self.acceptance_source_id,
            "minimum_count": self.minimum_count,
        }

    @classmethod
    def from_record(cls, value: object) -> "GenericEvidenceRequirement":
        record = _mapping(value, "generic evidence requirement")
        _keys(record, {"requirement_id", "evidence_kind_id", "acceptance_source_id", "minimum_count"}, "generic evidence requirement")
        return cls(**record)


@dataclass(frozen=True)
class GenericProgressMeasurement:
    adapter_id: str
    gate_manifest_id: str
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter_id", _identifier(self.adapter_id, "adapter_id"))
        object.__setattr__(self, "gate_manifest_id", _identifier(self.gate_manifest_id, "gate_manifest_id"))
        object.__setattr__(self, "description", _text(self.description, "progress description", maximum=1024))

    def as_record(self) -> dict[str, str]:
        return {
            "adapter_id": self.adapter_id,
            "gate_manifest_id": self.gate_manifest_id,
            "description": self.description,
        }

    @classmethod
    def from_record(cls, value: object) -> "GenericProgressMeasurement":
        record = _mapping(value, "generic progress measurement")
        _keys(record, {"adapter_id", "gate_manifest_id", "description"}, "generic progress measurement")
        return cls(**record)


@dataclass(frozen=True)
class GenericRetryPolicy:
    maximum_attempts: int
    require_new_evidence: bool
    reopen_with_delta_only: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "maximum_attempts", _positive_int(self.maximum_attempts, "maximum_attempts"))
        if not isinstance(self.require_new_evidence, bool) or not isinstance(self.reopen_with_delta_only, bool):
            raise ValueError("retry policy flags must be booleans")

    def as_record(self) -> dict[str, Any]:
        return {
            "maximum_attempts": self.maximum_attempts,
            "require_new_evidence": self.require_new_evidence,
            "reopen_with_delta_only": self.reopen_with_delta_only,
        }

    @classmethod
    def from_record(cls, value: object) -> "GenericRetryPolicy":
        record = _mapping(value, "generic retry policy")
        _keys(record, {"maximum_attempts", "require_new_evidence", "reopen_with_delta_only"}, "generic retry policy")
        return cls(**record)


@dataclass(frozen=True)
class GenericCreatorInstanceSpec:
    """One node in the authority tree plus its work-graph declarations."""

    instance_id: str
    creator_type: GenericCreatorType
    parent_instance_id: Optional[str]
    local_goal: str
    immutable_parent_success_criteria_refs: tuple[str, ...]
    input_artifacts: tuple[ArtifactReference, ...]
    work_definition: Mapping[str, Any]
    result_schema: Mapping[str, Any]
    dependency_ids: tuple[str, ...]
    interface_contracts: tuple[Mapping[str, Any], ...]
    progress_measurement: GenericProgressMeasurement
    target: float
    minimum_delta: float
    stagnation_window: int
    evidence_requirements: tuple[GenericEvidenceRequirement, ...]
    assignable_capabilities: tuple[str, ...]
    shared_state_namespace: str
    maximum_iterations: int
    maximum_child_episodes: int
    maximum_depth: int
    maximum_elapsed_time: float
    fault_ownership: Mapping[str, Any]
    parent_gates_may_satisfy: tuple[str, ...]
    cancellation_behavior: CancellationBehavior
    retry_behavior: GenericRetryPolicy
    status: GenericCreatorStatus = GenericCreatorStatus.PENDING
    may_create_child_creators: bool = False
    schema_version: int = field(default=GENERIC_CREATOR_INSTANCE_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "instance_id", _identifier(self.instance_id, "instance_id"))
        if not isinstance(self.creator_type, GenericCreatorType):
            raise ValueError("creator_type must be a GenericCreatorType")
        if self.parent_instance_id is not None:
            object.__setattr__(self, "parent_instance_id", _identifier(self.parent_instance_id, "parent_instance_id"))
            if self.parent_instance_id == self.instance_id:
                raise ValueError("a Creator instance cannot parent itself")
        object.__setattr__(self, "local_goal", _text(self.local_goal, "local_goal", maximum=4096))
        object.__setattr__(self, "immutable_parent_success_criteria_refs", _string_tuple(self.immutable_parent_success_criteria_refs, "immutable_parent_success_criteria_refs", allow_empty=self.parent_instance_id is None))
        if not isinstance(self.input_artifacts, tuple) or any(not isinstance(item, ArtifactReference) for item in self.input_artifacts):
            raise ValueError("input_artifacts must be a tuple of ArtifactReference values")
        if len({item.artifact_id for item in self.input_artifacts}) != len(self.input_artifacts):
            raise ValueError("input_artifacts must be unique")
        object.__setattr__(self, "work_definition", _json_object(self.work_definition, "work_definition"))
        object.__setattr__(self, "result_schema", _json_object(self.result_schema, "result_schema"))
        object.__setattr__(self, "dependency_ids", _string_tuple(self.dependency_ids, "dependency_ids"))
        if self.instance_id in self.dependency_ids:
            raise ValueError("a Creator instance cannot depend on itself")
        if not isinstance(self.interface_contracts, tuple):
            raise ValueError("interface_contracts must be a tuple")
        object.__setattr__(self, "interface_contracts", tuple(_json_object(item, "interface_contract") for item in self.interface_contracts))
        if not isinstance(self.progress_measurement, GenericProgressMeasurement):
            raise ValueError("progress_measurement must be GenericProgressMeasurement")
        object.__setattr__(self, "target", _positive_number(self.target, "target"))
        object.__setattr__(self, "minimum_delta", _positive_number(self.minimum_delta, "minimum_delta"))
        if self.target > 1 or self.minimum_delta > 1:
            raise ValueError("generic normalized target and minimum_delta must lie in (0, 1]")
        object.__setattr__(self, "stagnation_window", _positive_int(self.stagnation_window, "stagnation_window"))
        if self.stagnation_window < 2:
            raise ValueError("stagnation_window must be at least two")
        if not isinstance(self.evidence_requirements, tuple) or not self.evidence_requirements or any(not isinstance(item, GenericEvidenceRequirement) for item in self.evidence_requirements):
            raise ValueError("evidence_requirements must be a non-empty tuple")
        if len({item.requirement_id for item in self.evidence_requirements}) != len(self.evidence_requirements):
            raise ValueError("evidence requirement IDs must be unique")
        object.__setattr__(self, "assignable_capabilities", _string_tuple(self.assignable_capabilities, "assignable_capabilities"))
        object.__setattr__(self, "shared_state_namespace", _namespace(self.shared_state_namespace, "shared_state_namespace"))
        for name in ("maximum_iterations", "maximum_depth"):
            object.__setattr__(self, name, _positive_int(getattr(self, name), name))
        object.__setattr__(
            self,
            "maximum_child_episodes",
            _non_negative_int(self.maximum_child_episodes, "maximum_child_episodes"),
        )
        object.__setattr__(self, "maximum_elapsed_time", _positive_number(self.maximum_elapsed_time, "maximum_elapsed_time"))
        object.__setattr__(self, "fault_ownership", _json_object(self.fault_ownership, "fault_ownership"))
        object.__setattr__(self, "parent_gates_may_satisfy", _string_tuple(self.parent_gates_may_satisfy, "parent_gates_may_satisfy"))
        if not isinstance(self.cancellation_behavior, CancellationBehavior):
            raise ValueError("cancellation_behavior must be CancellationBehavior")
        if not isinstance(self.retry_behavior, GenericRetryPolicy):
            raise ValueError("retry_behavior must be GenericRetryPolicy")
        if not isinstance(self.status, GenericCreatorStatus):
            raise ValueError("status must be GenericCreatorStatus")
        if self.status is not GenericCreatorStatus.PENDING:
            raise ValueError("a declarative instance must enter admission in pending status")
        if not isinstance(self.may_create_child_creators, bool):
            raise ValueError("may_create_child_creators must be boolean")

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "instance_id": self.instance_id,
            "creator_type": self.creator_type.value,
            "parent_instance_id": self.parent_instance_id,
            "local_goal": self.local_goal,
            "immutable_parent_success_criteria_refs": list(self.immutable_parent_success_criteria_refs),
            "input_artifacts": [item.as_record() for item in self.input_artifacts],
            "work_definition": dict(self.work_definition),
            "result_schema": dict(self.result_schema),
            "dependency_ids": list(self.dependency_ids),
            "interface_contracts": [dict(item) for item in self.interface_contracts],
            "progress_measurement": self.progress_measurement.as_record(),
            "target": self.target,
            "minimum_delta": self.minimum_delta,
            "stagnation_window": self.stagnation_window,
            "evidence_requirements": [item.as_record() for item in self.evidence_requirements],
            "assignable_capabilities": list(self.assignable_capabilities),
            "shared_state_namespace": self.shared_state_namespace,
            "maximum_iterations": self.maximum_iterations,
            "maximum_child_episodes": self.maximum_child_episodes,
            "maximum_depth": self.maximum_depth,
            "maximum_elapsed_time": self.maximum_elapsed_time,
            "fault_ownership": dict(self.fault_ownership),
            "parent_gates_may_satisfy": list(self.parent_gates_may_satisfy),
            "cancellation_behavior": self.cancellation_behavior.value,
            "retry_behavior": self.retry_behavior.as_record(),
            "status": self.status.value,
            "may_create_child_creators": self.may_create_child_creators,
        }

    @property
    def content_hash(self) -> Sha256Digest:
        return Sha256Digest.of_bytes(canonical_json(self.as_record()).encode())

    @classmethod
    def from_record(cls, value: object) -> "GenericCreatorInstanceSpec":
        record = _mapping(value, "generic Creator instance")
        expected = {
            "schema_version", "instance_id", "creator_type", "parent_instance_id", "local_goal",
            "immutable_parent_success_criteria_refs", "input_artifacts", "work_definition", "result_schema",
            "dependency_ids", "interface_contracts", "progress_measurement", "target", "minimum_delta",
            "stagnation_window", "evidence_requirements", "assignable_capabilities", "shared_state_namespace",
            "maximum_iterations", "maximum_child_episodes", "maximum_depth", "maximum_elapsed_time",
            "fault_ownership", "parent_gates_may_satisfy", "cancellation_behavior", "retry_behavior",
            "status", "may_create_child_creators",
        }
        _keys(record, expected, "generic Creator instance")
        if record["schema_version"] != GENERIC_CREATOR_INSTANCE_SCHEMA_VERSION:
            raise ValueError("unsupported generic Creator instance schema version")
        tuple_fields = (
            "immutable_parent_success_criteria_refs", "input_artifacts", "dependency_ids", "interface_contracts",
            "evidence_requirements", "assignable_capabilities", "parent_gates_may_satisfy",
        )
        if any(not isinstance(record[name], list) for name in tuple_fields):
            raise ValueError("generic Creator collection fields must be arrays")
        return cls(
            instance_id=record["instance_id"],
            creator_type=_enum(GenericCreatorType, record["creator_type"], "creator_type"),
            parent_instance_id=record["parent_instance_id"],
            local_goal=record["local_goal"],
            immutable_parent_success_criteria_refs=tuple(record["immutable_parent_success_criteria_refs"]),
            input_artifacts=tuple(ArtifactReference.from_record(item) for item in record["input_artifacts"]),
            work_definition=record["work_definition"],
            result_schema=record["result_schema"],
            dependency_ids=tuple(record["dependency_ids"]),
            interface_contracts=tuple(record["interface_contracts"]),
            progress_measurement=GenericProgressMeasurement.from_record(record["progress_measurement"]),
            target=record["target"],
            minimum_delta=record["minimum_delta"],
            stagnation_window=record["stagnation_window"],
            evidence_requirements=tuple(GenericEvidenceRequirement.from_record(item) for item in record["evidence_requirements"]),
            assignable_capabilities=tuple(record["assignable_capabilities"]),
            shared_state_namespace=record["shared_state_namespace"],
            maximum_iterations=record["maximum_iterations"],
            maximum_child_episodes=record["maximum_child_episodes"],
            maximum_depth=record["maximum_depth"],
            maximum_elapsed_time=record["maximum_elapsed_time"],
            fault_ownership=record["fault_ownership"],
            parent_gates_may_satisfy=tuple(record["parent_gates_may_satisfy"]),
            cancellation_behavior=_enum(CancellationBehavior, record["cancellation_behavior"], "cancellation_behavior"),
            retry_behavior=GenericRetryPolicy.from_record(record["retry_behavior"]),
            status=_enum(GenericCreatorStatus, record["status"], "status"),
            may_create_child_creators=record["may_create_child_creators"],
        )


@dataclass(frozen=True)
class EvidenceGate:
    gate_id: str
    description: str
    weight: float
    required_evidence_kind: str
    accepted_evidence_source: str
    minimum_evidence_count: int
    dependencies: tuple[str, ...]
    requirement: GateRequirement
    acceptance_state: GateAcceptanceState = GateAcceptanceState.PENDING
    accepted_evidence_ids: tuple[OpaqueId, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate_id", _identifier(self.gate_id, "gate_id"))
        object.__setattr__(self, "description", _text(self.description, "gate description", maximum=1024))
        object.__setattr__(self, "weight", _positive_number(self.weight, "gate weight"))
        object.__setattr__(self, "required_evidence_kind", _identifier(self.required_evidence_kind, "required_evidence_kind"))
        object.__setattr__(self, "accepted_evidence_source", _identifier(self.accepted_evidence_source, "accepted_evidence_source"))
        object.__setattr__(self, "minimum_evidence_count", _positive_int(self.minimum_evidence_count, "minimum_evidence_count"))
        object.__setattr__(self, "dependencies", _string_tuple(self.dependencies, "gate dependencies"))
        if self.gate_id in self.dependencies:
            raise ValueError("a gate cannot depend on itself")
        if not isinstance(self.requirement, GateRequirement) or not isinstance(self.acceptance_state, GateAcceptanceState):
            raise ValueError("gate requirement and acceptance_state must be enums")
        if not isinstance(self.accepted_evidence_ids, tuple) or any(not isinstance(item, OpaqueId) for item in self.accepted_evidence_ids):
            raise ValueError("accepted_evidence_ids must be a tuple of OpaqueIds")
        if len(set(self.accepted_evidence_ids)) != len(self.accepted_evidence_ids):
            raise ValueError("accepted_evidence_ids must be unique")
        enough = len(self.accepted_evidence_ids) >= self.minimum_evidence_count
        if (self.acceptance_state is GateAcceptanceState.ACCEPTED) != enough:
            raise ValueError("accepted gate state must match its minimum accepted evidence count")

    def as_record(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "description": self.description,
            "weight": self.weight,
            "required_evidence_kind": self.required_evidence_kind,
            "accepted_evidence_source": self.accepted_evidence_source,
            "minimum_evidence_count": self.minimum_evidence_count,
            "dependencies": list(self.dependencies),
            "required_or_optional_status": self.requirement.value,
            "current_acceptance_state": self.acceptance_state.value,
            "accepted_evidence_ids": [item.value for item in self.accepted_evidence_ids],
        }

    @classmethod
    def from_record(cls, value: object) -> "EvidenceGate":
        record = _mapping(value, "evidence gate")
        _keys(record, {"gate_id", "description", "weight", "required_evidence_kind", "accepted_evidence_source", "minimum_evidence_count", "dependencies", "required_or_optional_status", "current_acceptance_state", "accepted_evidence_ids"}, "evidence gate")
        if not all(isinstance(record[name], list) for name in ("dependencies", "accepted_evidence_ids")):
            raise ValueError("gate dependencies and accepted_evidence_ids must be arrays")
        return cls(
            gate_id=record["gate_id"], description=record["description"], weight=record["weight"],
            required_evidence_kind=record["required_evidence_kind"], accepted_evidence_source=record["accepted_evidence_source"],
            minimum_evidence_count=record["minimum_evidence_count"], dependencies=tuple(record["dependencies"]),
            requirement=_enum(GateRequirement, record["required_or_optional_status"], "gate requirement"),
            acceptance_state=_enum(GateAcceptanceState, record["current_acceptance_state"], "gate acceptance state"),
            accepted_evidence_ids=tuple(OpaqueId(item) for item in record["accepted_evidence_ids"]),
        )


@dataclass(frozen=True)
class EvidenceGateManifest:
    manifest_id: str
    revision: int
    success_criteria_hash: Sha256Digest
    gates: tuple[EvidenceGate, ...]
    schema_version: int = field(default=EVIDENCE_GATE_MANIFEST_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest_id", _identifier(self.manifest_id, "manifest_id"))
        object.__setattr__(self, "revision", _positive_int(self.revision, "manifest revision"))
        if not isinstance(self.success_criteria_hash, Sha256Digest):
            raise ValueError("success_criteria_hash must be a Sha256Digest")
        if not isinstance(self.gates, tuple) or not self.gates or any(not isinstance(item, EvidenceGate) for item in self.gates):
            raise ValueError("gates must be a non-empty tuple")
        by_id = {item.gate_id: item for item in self.gates}
        if len(by_id) != len(self.gates):
            raise ValueError("gate IDs must be unique")
        for gate in self.gates:
            if not set(gate.dependencies).issubset(by_id):
                raise ValueError("gate dependencies must name gates in the same manifest")
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(gate_id: str) -> None:
            if gate_id in visiting:
                raise ValueError("gate dependencies must be acyclic")
            if gate_id in visited:
                return
            visiting.add(gate_id)
            for dependency in by_id[gate_id].dependencies:
                visit(dependency)
            visiting.remove(gate_id)
            visited.add(gate_id)

        for gate_id in by_id:
            visit(gate_id)

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "revision": self.revision,
            "success_criteria_hash": self.success_criteria_hash.value,
            "gates": [item.as_record() for item in self.gates],
        }

    @property
    def content_hash(self) -> Sha256Digest:
        return Sha256Digest.of_bytes(canonical_json(self.as_record()).encode())

    @classmethod
    def from_record(cls, value: object) -> "EvidenceGateManifest":
        record = _mapping(value, "evidence gate manifest")
        _keys(record, {"schema_version", "manifest_id", "revision", "success_criteria_hash", "gates"}, "evidence gate manifest")
        if record["schema_version"] != EVIDENCE_GATE_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported evidence gate manifest schema version")
        if not isinstance(record["gates"], list):
            raise ValueError("manifest gates must be an array")
        return cls(record["manifest_id"], record["revision"], Sha256Digest(record["success_criteria_hash"]), tuple(EvidenceGate.from_record(item) for item in record["gates"]))


@dataclass(frozen=True)
class CreatorFaultRecord:
    fault_id: OpaqueId
    reporting_instance_id: str
    owning_instance_id: Optional[str]
    failed_gate_or_interface_edge: str
    artifact_references: tuple[ArtifactReference, ...]
    observed_result: Mapping[str, Any]
    expected_result: Mapping[str, Any]
    accepted_evidence_ids: tuple[OpaqueId, ...]
    reproducible_test_reference: ArtifactReference
    severity: str
    retryable: bool
    suggested_repair_scope: tuple[str, ...]
    remaining_repair_budget: int
    status: FaultStatus = FaultStatus.OPEN
    schema_version: int = field(default=CREATOR_FAULT_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.fault_id, OpaqueId):
            raise ValueError("fault_id must be an OpaqueId")
        object.__setattr__(self, "reporting_instance_id", _identifier(self.reporting_instance_id, "reporting_instance_id"))
        if self.owning_instance_id is not None:
            object.__setattr__(self, "owning_instance_id", _identifier(self.owning_instance_id, "owning_instance_id"))
        object.__setattr__(self, "failed_gate_or_interface_edge", _identifier(self.failed_gate_or_interface_edge, "failed_gate_or_interface_edge"))
        if not isinstance(self.artifact_references, tuple) or any(not isinstance(item, ArtifactReference) for item in self.artifact_references):
            raise ValueError("artifact_references must contain ArtifactReference values")
        object.__setattr__(self, "observed_result", _json_object(self.observed_result, "observed_result"))
        object.__setattr__(self, "expected_result", _json_object(self.expected_result, "expected_result"))
        if not isinstance(self.accepted_evidence_ids, tuple) or any(not isinstance(item, OpaqueId) for item in self.accepted_evidence_ids):
            raise ValueError("accepted_evidence_ids must contain OpaqueIds")
        if len(set(self.accepted_evidence_ids)) != len(self.accepted_evidence_ids):
            raise ValueError("accepted_evidence_ids must be unique")
        if not isinstance(self.reproducible_test_reference, ArtifactReference):
            raise ValueError("reproducible_test_reference must be an ArtifactReference")
        object.__setattr__(self, "severity", _identifier(self.severity, "severity"))
        if not isinstance(self.retryable, bool):
            raise ValueError("retryable must be boolean")
        object.__setattr__(self, "suggested_repair_scope", _string_tuple(self.suggested_repair_scope, "suggested_repair_scope", allow_empty=False))
        object.__setattr__(self, "remaining_repair_budget", _non_negative_int(self.remaining_repair_budget, "remaining_repair_budget"))
        if not isinstance(self.status, FaultStatus):
            raise ValueError("status must be FaultStatus")

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "fault_id": self.fault_id.value,
            "reporting_instance_id": self.reporting_instance_id, "owning_instance_id": self.owning_instance_id,
            "failed_gate_or_interface_edge": self.failed_gate_or_interface_edge,
            "artifact_ids_and_hashes": [item.as_record() for item in self.artifact_references],
            "observed_result": dict(self.observed_result), "expected_result": dict(self.expected_result),
            "accepted_evidence_ids": [item.value for item in self.accepted_evidence_ids],
            "reproducible_test_or_command_reference": self.reproducible_test_reference.as_record(),
            "severity": self.severity, "retryability": self.retryable,
            "suggested_repair_scope": list(self.suggested_repair_scope),
            "remaining_repair_budget": self.remaining_repair_budget, "status": self.status.value,
        }

    @classmethod
    def from_record(cls, value: object) -> "CreatorFaultRecord":
        record = _mapping(value, "Creator fault")
        expected = {
            "schema_version", "fault_id", "reporting_instance_id", "owning_instance_id",
            "failed_gate_or_interface_edge", "artifact_ids_and_hashes", "observed_result",
            "expected_result", "accepted_evidence_ids",
            "reproducible_test_or_command_reference", "severity", "retryability",
            "suggested_repair_scope", "remaining_repair_budget", "status",
        }
        _keys(record, expected, "Creator fault")
        if record["schema_version"] != CREATOR_FAULT_SCHEMA_VERSION:
            raise ValueError("unsupported Creator fault schema version")
        for name in ("artifact_ids_and_hashes", "accepted_evidence_ids", "suggested_repair_scope"):
            if not isinstance(record[name], list):
                raise ValueError(f"{name} must be an array")
        return cls(
            fault_id=OpaqueId(record["fault_id"]),
            reporting_instance_id=record["reporting_instance_id"],
            owning_instance_id=record["owning_instance_id"],
            failed_gate_or_interface_edge=record["failed_gate_or_interface_edge"],
            artifact_references=tuple(
                ArtifactReference.from_record(item)
                for item in record["artifact_ids_and_hashes"]
            ),
            observed_result=record["observed_result"],
            expected_result=record["expected_result"],
            accepted_evidence_ids=tuple(OpaqueId(item) for item in record["accepted_evidence_ids"]),
            reproducible_test_reference=ArtifactReference.from_record(
                record["reproducible_test_or_command_reference"]
            ),
            severity=record["severity"],
            retryable=record["retryability"],
            suggested_repair_scope=tuple(record["suggested_repair_scope"]),
            remaining_repair_budget=record["remaining_repair_budget"],
            status=_enum(FaultStatus, record["status"], "fault status"),
        )


@dataclass(frozen=True)
class CreatorRepairRequest:
    repair_id: OpaqueId
    fault_id: OpaqueId
    owning_instance_id: str
    allowed_scope: tuple[str, ...]
    preserved_evidence_ids: tuple[OpaqueId, ...]
    integration_edge_ids_to_retest: tuple[str, ...]
    repair_budget: int
    status: RepairStatus = RepairStatus.REQUESTED
    schema_version: int = field(default=CREATOR_REPAIR_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.repair_id, OpaqueId) or not isinstance(self.fault_id, OpaqueId):
            raise ValueError("repair_id and fault_id must be OpaqueIds")
        object.__setattr__(self, "owning_instance_id", _identifier(self.owning_instance_id, "owning_instance_id"))
        object.__setattr__(self, "allowed_scope", _string_tuple(self.allowed_scope, "allowed_scope", allow_empty=False))
        if not isinstance(self.preserved_evidence_ids, tuple) or any(not isinstance(item, OpaqueId) for item in self.preserved_evidence_ids):
            raise ValueError("preserved_evidence_ids must contain OpaqueIds")
        if len(set(self.preserved_evidence_ids)) != len(self.preserved_evidence_ids):
            raise ValueError("preserved_evidence_ids must be unique")
        object.__setattr__(self, "integration_edge_ids_to_retest", _string_tuple(self.integration_edge_ids_to_retest, "integration_edge_ids_to_retest"))
        object.__setattr__(self, "repair_budget", _positive_int(self.repair_budget, "repair_budget"))
        if not isinstance(self.status, RepairStatus):
            raise ValueError("status must be RepairStatus")

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "repair_id": self.repair_id.value,
            "fault_id": self.fault_id.value, "owning_instance_id": self.owning_instance_id,
            "allowed_scope": list(self.allowed_scope),
            "preserved_evidence_ids": [item.value for item in self.preserved_evidence_ids],
            "integration_edge_ids_to_retest": list(self.integration_edge_ids_to_retest),
            "repair_budget": self.repair_budget, "status": self.status.value,
        }

    @classmethod
    def from_record(cls, value: object) -> "CreatorRepairRequest":
        record = _mapping(value, "Creator repair request")
        expected = {
            "schema_version", "repair_id", "fault_id", "owning_instance_id",
            "allowed_scope", "preserved_evidence_ids", "integration_edge_ids_to_retest",
            "repair_budget", "status",
        }
        _keys(record, expected, "Creator repair request")
        if record["schema_version"] != CREATOR_REPAIR_SCHEMA_VERSION:
            raise ValueError("unsupported Creator repair schema version")
        for name in ("allowed_scope", "preserved_evidence_ids", "integration_edge_ids_to_retest"):
            if not isinstance(record[name], list):
                raise ValueError(f"{name} must be an array")
        return cls(
            repair_id=OpaqueId(record["repair_id"]),
            fault_id=OpaqueId(record["fault_id"]),
            owning_instance_id=record["owning_instance_id"],
            allowed_scope=tuple(record["allowed_scope"]),
            preserved_evidence_ids=tuple(OpaqueId(item) for item in record["preserved_evidence_ids"]),
            integration_edge_ids_to_retest=tuple(record["integration_edge_ids_to_retest"]),
            repair_budget=record["repair_budget"],
            status=_enum(RepairStatus, record["status"], "repair status"),
        )


@dataclass(frozen=True)
class PlatformPatchProposal:
    patch_text: str
    test_plan: tuple[str, ...]
    migration_notes: str
    affected_security_boundaries: tuple[str, ...]
    expected_runtime_identity: Sha256Digest
    schema_version: int = field(default=PLATFORM_PATCH_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "patch_text", _text(self.patch_text, "patch_text", maximum=1_000_000))
        if not isinstance(self.test_plan, tuple) or not self.test_plan:
            raise ValueError("test_plan must be a non-empty tuple")
        object.__setattr__(self, "test_plan", tuple(_text(item, "test_plan item", maximum=2048) for item in self.test_plan))
        object.__setattr__(self, "migration_notes", _text(self.migration_notes, "migration_notes", maximum=8192))
        object.__setattr__(self, "affected_security_boundaries", _string_tuple(self.affected_security_boundaries, "affected_security_boundaries", allow_empty=False))
        if not isinstance(self.expected_runtime_identity, Sha256Digest):
            raise ValueError("expected_runtime_identity must be a Sha256Digest")

    def as_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "patch_text": self.patch_text,
            "test_plan": list(self.test_plan), "migration_notes": self.migration_notes,
            "affected_security_boundaries": list(self.affected_security_boundaries),
            "expected_runtime_identity": self.expected_runtime_identity.value,
        }

    @property
    def content_hash(self) -> Sha256Digest:
        return Sha256Digest.of_bytes(canonical_json(self.as_record()).encode())


__all__ = [
    "ArtifactReference", "CancellationBehavior", "CreatorFaultRecord", "CreatorRepairRequest",
    "EVIDENCE_GATE_MANIFEST_SCHEMA_VERSION", "EvidenceGate", "EvidenceGateManifest", "FaultStatus",
    "GateAcceptanceState", "GateRequirement", "GenericCreatorInstanceSpec", "GenericCreatorStatus",
    "GenericCreatorType", "GenericEvidenceRequirement", "GenericProgressMeasurement", "GenericRetryPolicy",
    "PlatformPatchProposal", "RepairStatus", "WorkItemStatus",
]
