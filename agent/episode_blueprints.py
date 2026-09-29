"""Translate model-friendly Episode blueprints into host-owned contracts.

Models describe goals, measurements, stopping rules, capabilities, and topology.
They never mint opaque identities, select schema versions, or assert creation
authority.  This module is the strict boundary that adds those host-owned
fields before the immutable contracts in :mod:`agent.episode_contracts` are
constructed.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from agent.episode_contracts import (
    EPISODE_CREATION_SCHEMA_VERSION,
    EPISODE_WORKFLOW_SCHEMA_VERSION,
    CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
    EpisodeCreationSpec,
    EpisodeWorkflowSpec,
    OpaqueId,
)


CREATION_BLUEPRINT_FIELDS = (
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
_CREATION_FIELDS = set(CREATION_BLUEPRINT_FIELDS)
_PROGRESS_FIELDS = {
    "description",
    "unit",
    "direction",
    "baseline",
    "adapter_id",
}
_WORKFLOW_NODE_FIELDS = {
    "local_id",
    "workflow_parent_local_id",
    "contract",
}


def _object(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return value


def _exact_fields(record: Mapping[str, Any], expected: set[str], name: str) -> None:
    actual = set(record)
    if actual != expected:
        raise ValueError(
            f"malformed {name}: missing={sorted(expected - actual)!r}, "
            f"unknown={sorted(actual - expected)!r}"
        )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def creation_blueprint_from_spec(spec: EpisodeCreationSpec) -> dict[str, Any]:
    """Project an internal contract into the schema a model may edit."""

    if not isinstance(spec, EpisodeCreationSpec):
        raise TypeError("creation blueprint projection requires an EpisodeCreationSpec")
    record = spec.as_record()
    progress = dict(record["progress"])
    progress.pop("metric_id")
    return {
        "goal": record["goal"],
        "unit": record["unit"],
        "result": record["result"],
        "progress": progress,
        "stopping": record["stopping"],
        "execution_capability_names": record["execution_capability_names"],
        "creator_contract": record["creator_contract"],
        "deliverable": record["deliverable"],
        "safety_bounds": record["safety_bounds"],
    }


def creation_spec_from_blueprint(
    value: object,
    *,
    identity_namespace: str,
) -> EpisodeCreationSpec:
    """Validate a blueprint and add only host-owned contract fields."""

    record = _object(value, "Episode creation blueprint")
    _exact_fields(record, _CREATION_FIELDS, "Episode creation blueprint")
    progress = _object(record["progress"], "progress blueprint")
    _exact_fields(progress, _PROGRESS_FIELDS, "progress blueprint")
    if not isinstance(identity_namespace, str) or not identity_namespace:
        raise ValueError("identity_namespace must be non-empty text")
    metric_material = _canonical_json(
        {
            "namespace": identity_namespace,
            "progress": progress,
        }
    )
    metric_id = OpaqueId.mint("metric", metric_material)
    creator_contract = record["creator_contract"]
    if (
        creator_contract is not None
        and progress["adapter_id"] != CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER
    ):
        raise ValueError(
            "Creator blueprints must use the host-owned "
            "creator_method_credit_v1 progress adapter"
        )
    internal = {
        "schema_version": EPISODE_CREATION_SCHEMA_VERSION,
        "goal": record["goal"],
        "unit": record["unit"],
        "result": record["result"],
        "progress": {"metric_id": metric_id.value, **dict(progress)},
        "stopping": record["stopping"],
        "can_create_episodes": creator_contract is not None,
        "execution_capability_names": record["execution_capability_names"],
        "creator_contract": creator_contract,
        "deliverable": record["deliverable"],
        "safety_bounds": record["safety_bounds"],
        "capability_inheritance": "inherit_parent",
    }
    spec = EpisodeCreationSpec.from_record(internal)
    from agent.episode_progress_adapters import validate_progress_contract

    validate_progress_contract(
        spec.progress,
        spec.stopping,
        model_created=creator_contract is None,
    )
    return spec


def workflow_blueprint_from_spec(workflow: EpisodeWorkflowSpec) -> dict[str, Any]:
    if not isinstance(workflow, EpisodeWorkflowSpec):
        raise TypeError("workflow blueprint projection requires an EpisodeWorkflowSpec")
    return {
        "episodes": [
            {
                "local_id": item.local_id,
                "workflow_parent_local_id": item.workflow_parent_local_id,
                "contract": creation_blueprint_from_spec(item.contract),
            }
            for item in workflow.episodes
        ]
    }


def workflow_spec_from_blueprint(
    value: object,
    *,
    identity_namespace: str,
) -> EpisodeWorkflowSpec:
    """Translate a complete workflow blueprint and derive every metric ID."""

    record = _object(value, "Episode workflow blueprint")
    _exact_fields(record, {"episodes"}, "Episode workflow blueprint")
    raw_episodes = record["episodes"]
    if not isinstance(raw_episodes, list) or not raw_episodes:
        raise ValueError("workflow blueprint episodes must be a non-empty array")
    episodes = []
    for index, raw_node in enumerate(raw_episodes):
        node = _object(raw_node, f"workflow node {index}")
        _exact_fields(node, _WORKFLOW_NODE_FIELDS, f"workflow node {index}")
        local_id = node["local_id"]
        episodes.append(
            {
                "local_id": local_id,
                "workflow_parent_local_id": node["workflow_parent_local_id"],
                "contract": creation_spec_from_blueprint(
                    node["contract"],
                    identity_namespace=f"{identity_namespace}:{local_id}",
                ).as_record(),
            }
        )
    return EpisodeWorkflowSpec.from_record(
        {
            "schema_version": EPISODE_WORKFLOW_SCHEMA_VERSION,
            "episodes": episodes,
        }
    )


EPISODE_CREATION_BLUEPRINT_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "unit": {"type": "string"},
        "result": {"type": "string"},
        "progress": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "unit": {"type": "string"},
                "direction": {"type": "string", "enum": ["increase", "decrease"]},
                "baseline": {"type": "number"},
                "adapter_id": {"type": "string"},
            },
            "required": sorted(_PROGRESS_FIELDS),
            "additionalProperties": False,
        },
        "stopping": {
            "type": "object",
            "properties": {
                "target": {"type": "number"},
                "minimum_delta": {"type": "number", "exclusiveMinimum": 0},
                "stagnation_observations": {"type": "integer", "minimum": 2},
            },
            "required": ["target", "minimum_delta", "stagnation_observations"],
            "additionalProperties": False,
        },
        "execution_capability_names": {
            "type": "array",
            "items": {"type": "string"},
            "uniqueItems": True,
        },
        "creator_contract": {"type": ["object", "null"]},
        "deliverable": {"type": "object"},
        "safety_bounds": {"type": ["object", "null"]},
    },
    "required": sorted(_CREATION_FIELDS),
    "additionalProperties": False,
}


EPISODE_WORKFLOW_BLUEPRINT_SCHEMA = {
    "type": "object",
    "properties": {
        "episodes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "local_id": {"type": "string"},
                    "workflow_parent_local_id": {"type": ["string", "null"]},
                    "contract": EPISODE_CREATION_BLUEPRINT_SCHEMA,
                },
                "required": sorted(_WORKFLOW_NODE_FIELDS),
                "additionalProperties": False,
            },
        }
    },
    "required": ["episodes"],
    "additionalProperties": False,
}


__all__ = [
    "CREATION_BLUEPRINT_FIELDS",
    "EPISODE_CREATION_BLUEPRINT_SCHEMA",
    "EPISODE_WORKFLOW_BLUEPRINT_SCHEMA",
    "creation_blueprint_from_spec",
    "creation_spec_from_blueprint",
    "workflow_blueprint_from_spec",
    "workflow_spec_from_blueprint",
]
