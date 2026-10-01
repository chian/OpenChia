"""Immutable node and edge parts of an Episode materialization plan."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping, Optional

from agent.duet_contracts import content_id
from agent.episode_contracts import Sha256Digest
from handoff_library import HandoffPayloadContract

from ._contract_base import (
    _DEFINITION_ID,
    _EPISODE_ID,
    _DOTTED_NAME,
    _TOKEN,
    _array,
    _derivation_basis,
    _json_mapping,
    _local_id,
    _record,
    _text,
    _thaw_json,
    _token,
    _tuple_of_strings,
)


_INTERFACE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_RESULT_CHANNEL_ID = re.compile(r"^result_channel_[0-9a-f]{64}$")


def _json_mapping_tuple(
    value: object,
    name: str,
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be a tuple")
    return tuple(
        _json_mapping(item, f"{name}[{index}]")
        for index, item in enumerate(value)
    )


def _payload_contract_record(
    value: object,
    name: str,
) -> Mapping[str, object]:
    if isinstance(value, HandoffPayloadContract):
        contract = value
    else:
        contract = HandoffPayloadContract.from_record(value)
    return _json_mapping(contract.as_record(), name)


def _binding_record(value: object, name: str) -> Mapping[str, object]:
    record = _record(
        value,
        name,
        {
            "role",
            "source",
            "library",
            "function_id",
            "interface",
            "definition_id",
            "arguments",
            "basis",
        },
    )
    role = _token(record["role"], f"{name}.role")
    source = record["source"]
    if source not in {"library", "reference", "generated"}:
        raise ValueError(f"{name}.source is invalid")
    library = _text(record["library"], f"{name}.library", maximum=512)
    function_id = _text(
        record["function_id"],
        f"{name}.function_id",
        maximum=512,
    )
    interface = _text(record["interface"], f"{name}.interface", maximum=512)
    if _INTERFACE.fullmatch(library) is None:
        raise ValueError(f"{name}.library must be a lowercase dotted name")
    if _INTERFACE.fullmatch(function_id) is None:
        raise ValueError(f"{name}.function_id must be a lowercase dotted name")
    if _INTERFACE.fullmatch(interface) is None:
        raise ValueError(f"{name}.interface must be a lowercase dotted name")
    definition_id = _text(
        record["definition_id"],
        f"{name}.definition_id",
        maximum=128,
    )
    if source in {"library", "reference"}:
        if _DEFINITION_ID.fullmatch(definition_id) is None:
            raise ValueError(
                f"{name}.definition_id must identify exact referenced semantics"
            )
    elif definition_id != "generated":
        raise ValueError(
            f"{name}.definition_id must be 'generated' before emission"
        )
    return _json_mapping(
        {
            "role": role,
            "source": source,
            "library": library,
            "function_id": function_id,
            "interface": interface,
            "definition_id": definition_id,
            "arguments": _json_mapping(record["arguments"], f"{name}.arguments"),
            "basis": _text(record["basis"], f"{name}.basis", maximum=2048),
        },
        name,
    )


def _binding_tuple(
    value: object,
    name: str,
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, tuple) or not value:
        raise ValueError(f"{name} must be a non-empty tuple")
    bindings = tuple(
        _binding_record(item, f"{name}[{index}]")
        for index, item in enumerate(value)
    )
    roles = [str(binding["role"]) for binding in bindings]
    if len(set(roles)) != len(roles):
        raise ValueError(f"{name} roles must be unique")
    return tuple(sorted(bindings, key=lambda binding: str(binding["role"])))


@dataclass(frozen=True)
class NodeMaterializationPlan:
    """Every implementation choice for one frozen Duet Episode node."""

    local_id: str
    parent_local_id: Optional[str]
    contract_hash: Sha256Digest
    reference_episode_id: Optional[str]
    reference_evidence_hash: Optional[Sha256Digest]
    module_name: str
    interface: str
    grain_name: str
    topology_role: str
    capability_names: tuple[str, ...]
    result_channel_names: tuple[str, ...]
    result_channel_ids: tuple[str, ...]
    request_payload_contract: Mapping[str, object]
    result_payload_contract: Mapping[str, object]
    selected_function_bindings: tuple[Mapping[str, object], ...]
    generated_component_specs: tuple[Mapping[str, object], ...]
    prompt_specs: tuple[Mapping[str, object], ...]
    goal_state_spec: Mapping[str, object]
    child_slot_names: tuple[str, ...]
    derivation_basis: Mapping[str, str]
    function_definition_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "local_id", _local_id(self.local_id, "local_id"))
        if self.parent_local_id is not None:
            object.__setattr__(
                self,
                "parent_local_id",
                _local_id(self.parent_local_id, "parent_local_id"),
            )
        if not isinstance(self.contract_hash, Sha256Digest):
            object.__setattr__(
                self,
                "contract_hash",
                Sha256Digest(self.contract_hash),
            )
        if self.reference_episode_id is not None:
            reference = _text(
                self.reference_episode_id,
                "reference_episode_id",
                maximum=72,
            )
            if _EPISODE_ID.fullmatch(reference) is None:
                raise ValueError("reference_episode_id must be a durable Episode ID")
        if self.reference_evidence_hash is not None and not isinstance(
            self.reference_evidence_hash,
            Sha256Digest,
        ):
            object.__setattr__(
                self,
                "reference_evidence_hash",
                Sha256Digest(self.reference_evidence_hash),
            )
        if (self.reference_episode_id is None) != (
            self.reference_evidence_hash is None
        ):
            raise ValueError(
                "Episode references require an exact reference evidence hash"
            )
        module_name = _text(self.module_name, "module_name", maximum=512)
        if _DOTTED_NAME.fullmatch(module_name) is None:
            raise ValueError("module_name must be a dotted Python module name")
        object.__setattr__(self, "module_name", module_name)
        interface = _text(self.interface, "interface", maximum=512)
        if _INTERFACE.fullmatch(interface) is None:
            raise ValueError("interface must be a lowercase dotted name")
        object.__setattr__(self, "interface", interface)
        object.__setattr__(self, "grain_name", _token(self.grain_name, "grain_name"))
        if self.topology_role not in {"branch", "leaf"}:
            raise ValueError("topology_role must be branch or leaf")
        object.__setattr__(
            self,
            "capability_names",
            _tuple_of_strings(self.capability_names, "capability_names"),
        )
        result_channel_names = _tuple_of_strings(
            self.result_channel_names,
            "result_channel_names",
            pattern=_INTERFACE,
        )
        if not result_channel_names:
            raise ValueError(
                "result_channel_names must contain at least one channel"
            )
        object.__setattr__(
            self,
            "result_channel_names",
            result_channel_names,
        )
        result_channel_ids = _tuple_of_strings(
            self.result_channel_ids,
            "result_channel_ids",
            pattern=_RESULT_CHANNEL_ID,
        )
        expected_channel_ids = tuple(
            content_id(
                "result_channel",
                {
                    "contract_hash": self.contract_hash.value,
                    "episode_local_id": self.local_id,
                    "name": name,
                },
            ).value
            for name in self.result_channel_names
        )
        if result_channel_ids != expected_channel_ids:
            raise ValueError(
                "result_channel_ids must be host-derived from the exact contract "
                "and semantic names"
            )
        object.__setattr__(self, "result_channel_ids", result_channel_ids)
        object.__setattr__(
            self,
            "request_payload_contract",
            _payload_contract_record(
                self.request_payload_contract,
                "request_payload_contract",
            ),
        )
        object.__setattr__(
            self,
            "result_payload_contract",
            _payload_contract_record(
                self.result_payload_contract,
                "result_payload_contract",
            ),
        )
        bindings = _binding_tuple(
            self.selected_function_bindings,
            "selected_function_bindings",
        )
        object.__setattr__(self, "selected_function_bindings", bindings)
        object.__setattr__(
            self,
            "generated_component_specs",
            _json_mapping_tuple(
                self.generated_component_specs,
                "generated_component_specs",
            ),
        )
        object.__setattr__(
            self,
            "prompt_specs",
            _json_mapping_tuple(self.prompt_specs, "prompt_specs"),
        )
        object.__setattr__(
            self,
            "goal_state_spec",
            _json_mapping(self.goal_state_spec, "goal_state_spec"),
        )
        child_slots = _tuple_of_strings(
            self.child_slot_names,
            "child_slot_names",
            pattern=_TOKEN,
        )
        if self.topology_role == "leaf" and child_slots:
            raise ValueError("a leaf materialization plan cannot declare child slots")
        if self.topology_role == "branch" and not child_slots:
            raise ValueError("a branch materialization plan requires child slots")
        object.__setattr__(self, "child_slot_names", child_slots)
        object.__setattr__(
            self,
            "derivation_basis",
            _derivation_basis(self.derivation_basis, "derivation_basis"),
        )
        definition_ids = _tuple_of_strings(
            self.function_definition_ids,
            "function_definition_ids",
            pattern=_DEFINITION_ID,
        )
        bound_ids = {
            binding["definition_id"]
            for binding in bindings
            if binding["source"] == "library"
        }
        if set(definition_ids) != bound_ids:
            raise ValueError(
                "function_definition_ids must exactly index executable library "
                "bindings"
            )
        object.__setattr__(self, "function_definition_ids", definition_ids)

    def as_record(self) -> dict[str, Any]:
        return {
            "local_id": self.local_id,
            "parent_local_id": self.parent_local_id,
            "contract_hash": self.contract_hash.value,
            "reference_episode_id": self.reference_episode_id,
            "reference_evidence_hash": (
                None
                if self.reference_evidence_hash is None
                else self.reference_evidence_hash.value
            ),
            "module_name": self.module_name,
            "interface": self.interface,
            "grain_name": self.grain_name,
            "topology_role": self.topology_role,
            "capability_names": list(self.capability_names),
            "result_channel_names": list(self.result_channel_names),
            "result_channel_ids": list(self.result_channel_ids),
            "request_payload_contract": _thaw_json(self.request_payload_contract),
            "result_payload_contract": _thaw_json(self.result_payload_contract),
            "selected_function_bindings": _thaw_json(self.selected_function_bindings),
            "generated_component_specs": _thaw_json(
                self.generated_component_specs
            ),
            "prompt_specs": _thaw_json(self.prompt_specs),
            "goal_state_spec": _thaw_json(self.goal_state_spec),
            "child_slot_names": list(self.child_slot_names),
            "derivation_basis": dict(self.derivation_basis),
            "function_definition_ids": list(self.function_definition_ids),
        }

    @classmethod
    def from_record(cls, value: object) -> "NodeMaterializationPlan":
        fields = {
            "local_id",
            "parent_local_id",
            "contract_hash",
            "reference_episode_id",
            "reference_evidence_hash",
            "module_name",
            "interface",
            "grain_name",
            "topology_role",
            "capability_names",
            "result_channel_names",
            "result_channel_ids",
            "request_payload_contract",
            "result_payload_contract",
            "selected_function_bindings",
            "generated_component_specs",
            "prompt_specs",
            "goal_state_spec",
            "child_slot_names",
            "derivation_basis",
            "function_definition_ids",
        }
        record = _record(value, "node materialization plan", fields)
        return cls(
            local_id=record["local_id"],
            parent_local_id=record["parent_local_id"],
            contract_hash=Sha256Digest(record["contract_hash"]),
            reference_episode_id=record["reference_episode_id"],
            reference_evidence_hash=(
                None
                if record["reference_evidence_hash"] is None
                else Sha256Digest(record["reference_evidence_hash"])
            ),
            module_name=record["module_name"],
            interface=record["interface"],
            grain_name=record["grain_name"],
            topology_role=record["topology_role"],
            capability_names=tuple(
                _array(record["capability_names"], "capability_names")
            ),
            result_channel_names=tuple(
                _array(record["result_channel_names"], "result_channel_names")
            ),
            result_channel_ids=tuple(
                _array(record["result_channel_ids"], "result_channel_ids")
            ),
            request_payload_contract=record["request_payload_contract"],
            result_payload_contract=record["result_payload_contract"],
            selected_function_bindings=tuple(
                _array(
                    record["selected_function_bindings"],
                    "selected_function_bindings",
                )
            ),
            generated_component_specs=tuple(
                _array(
                    record["generated_component_specs"],
                    "generated_component_specs",
                )
            ),
            prompt_specs=tuple(_array(record["prompt_specs"], "prompt_specs")),
            goal_state_spec=record["goal_state_spec"],
            child_slot_names=tuple(
                _array(record["child_slot_names"], "child_slot_names")
            ),
            derivation_basis=record["derivation_basis"],
            function_definition_ids=tuple(
                _array(
                    record["function_definition_ids"],
                    "function_definition_ids",
                )
            ),
        )


@dataclass(frozen=True)
class EdgeMaterializationPlan:
    """One parent-owned wrapper around a direct child Episode."""

    parent_local_id: str
    child_local_id: str
    slot_name: str
    child_interface: str
    prepare_request: str
    receive_result: str
    build_child: str
    request_payload_contract: Mapping[str, object]
    result_payload_contract: Mapping[str, object]
    derivation_basis: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parent_local_id",
            _local_id(self.parent_local_id, "parent_local_id"),
        )
        object.__setattr__(
            self,
            "child_local_id",
            _local_id(self.child_local_id, "child_local_id"),
        )
        if self.parent_local_id == self.child_local_id:
            raise ValueError("an edge cannot make an Episode its own child")
        object.__setattr__(self, "slot_name", _token(self.slot_name, "slot_name"))
        child_interface = _text(
            self.child_interface,
            "child_interface",
            maximum=512,
        )
        if _INTERFACE.fullmatch(child_interface) is None:
            raise ValueError("child_interface must be a lowercase dotted name")
        object.__setattr__(self, "child_interface", child_interface)
        for name in ("prepare_request", "receive_result", "build_child"):
            object.__setattr__(
                self,
                name,
                _text(getattr(self, name), name, maximum=8192),
            )
        object.__setattr__(
            self,
            "request_payload_contract",
            _payload_contract_record(
                self.request_payload_contract,
                "request_payload_contract",
            ),
        )
        object.__setattr__(
            self,
            "result_payload_contract",
            _payload_contract_record(
                self.result_payload_contract,
                "result_payload_contract",
            ),
        )
        object.__setattr__(
            self,
            "derivation_basis",
            _derivation_basis(self.derivation_basis, "derivation_basis"),
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "parent_local_id": self.parent_local_id,
            "child_local_id": self.child_local_id,
            "slot_name": self.slot_name,
            "child_interface": self.child_interface,
            "prepare_request": self.prepare_request,
            "receive_result": self.receive_result,
            "build_child": self.build_child,
            "request_payload_contract": _thaw_json(self.request_payload_contract),
            "result_payload_contract": _thaw_json(self.result_payload_contract),
            "derivation_basis": dict(self.derivation_basis),
        }

    @classmethod
    def from_record(cls, value: object) -> "EdgeMaterializationPlan":
        record = _record(
            value,
            "edge materialization plan",
            {
                "parent_local_id",
                "child_local_id",
                "slot_name",
                "child_interface",
                "prepare_request",
                "receive_result",
                "build_child",
                "request_payload_contract",
                "result_payload_contract",
                "derivation_basis",
            },
        )
        return cls(**record)
