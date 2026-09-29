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


EPISODE_DELIVERABLE_BLUEPRINT_SCHEMA = {
    "type": "object",
    "description": (
        "How successful work becomes usable outside the Episode. typed_status needs "
        "no materialization tools; shared_state requires at least one named effectful tool."
    ),
    "properties": {
        "kind": {"type": "string", "enum": ["typed_status", "shared_state"]},
        "description": {"type": "string"},
        "tool_names": {
            "type": "array",
            "items": {"type": "string"},
            "uniqueItems": True,
        },
    },
    "required": ["kind", "description", "tool_names"],
    "additionalProperties": False,
}


EPISODE_SAFETY_BOUNDS_BLUEPRINT_SCHEMA = {
    "type": ["object", "null"],
    "description": (
        "Hard resource caps; reaching one is not success. At least one value must be "
        "non-null when the object is used."
    ),
    "properties": {
        "max_iterations": {"type": ["integer", "null"], "minimum": 1},
        "max_child_episodes": {"type": ["integer", "null"], "minimum": 1},
        "max_depth": {"type": ["integer", "null"], "minimum": 1},
        "max_elapsed_seconds": {"type": ["number", "null"], "exclusiveMinimum": 0},
    },
    "required": [
        "max_iterations",
        "max_child_episodes",
        "max_depth",
        "max_elapsed_seconds",
    ],
    "additionalProperties": False,
}


_EVIDENCE_REQUIREMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "requirement_id": {"type": "string"},
        "evidence_kind_id": {"type": "string"},
        "acceptance_source_id": {"type": "string"},
        "minimum_count": {"type": "integer", "minimum": 1},
    },
    "required": [
        "requirement_id",
        "evidence_kind_id",
        "acceptance_source_id",
        "minimum_count",
    ],
    "additionalProperties": False,
}


_CREDIT_COMPONENT_SCHEMA = {
    "type": "object",
    "properties": {
        "component_id": {"type": "string"},
        "measurement_id": {"type": "string"},
        "direction": {"type": "string", "enum": ["increase", "decrease"]},
        "normalization_baseline": {"type": "number"},
        "normalization_target": {"type": "number"},
        "weight": {"type": "number", "minimum": 0},
        "evidence_requirement_ids": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string"},
            "uniqueItems": True,
        },
    },
    "required": [
        "component_id",
        "measurement_id",
        "direction",
        "normalization_baseline",
        "normalization_target",
        "weight",
        "evidence_requirement_ids",
    ],
    "additionalProperties": False,
}


EPISODE_CREATOR_CONTRACT_BLUEPRINT_SCHEMA = {
    "type": ["object", "null"],
    "description": (
        "A bounded workflow-design commission. Non-null grants Creator authority; null "
        "creates an ordinary task Episode."
    ),
    "properties": {
        "design_instructions": {"type": "string"},
        "design_scope": {"type": "string"},
        "assignable_capability_names": {
            "type": "array",
            "items": {"type": "string"},
            "uniqueItems": True,
        },
        "may_assign_creator_capability": {"type": "boolean"},
        "evidence_requirements": {
            "type": "array",
            "minItems": 1,
            "items": _EVIDENCE_REQUIREMENT_SCHEMA,
        },
        "required_existing_evidence_ids": {
            "type": "array",
            "items": {"type": "string"},
            "uniqueItems": True,
        },
        "credit_assignment": {
            "type": "object",
            "properties": {
                "aggregation": {
                    "type": "string",
                    "enum": ["normalized_weighted_sum_v1"],
                },
                "components": {
                    "type": "array",
                    "minItems": 1,
                    "items": _CREDIT_COMPONENT_SCHEMA,
                },
            },
            "required": ["aggregation", "components"],
            "additionalProperties": False,
        },
        "return_contract": {
            "type": "object",
            "properties": {
                "measurement_ids": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string"},
                    "uniqueItems": True,
                },
                "credit_component_ids": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"type": "string"},
                    "uniqueItems": True,
                },
                "status_fields": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "workflow_valid",
                            "measurements_complete",
                            "evidence_requirements_met",
                            "credit_complete",
                        ],
                    },
                    "uniqueItems": True,
                },
            },
            "required": ["measurement_ids", "credit_component_ids", "status_fields"],
            "additionalProperties": False,
        },
    },
    "required": [
        "design_instructions",
        "design_scope",
        "assignable_capability_names",
        "may_assign_creator_capability",
        "evidence_requirements",
        "required_existing_evidence_ids",
        "credit_assignment",
        "return_contract",
    ],
    "additionalProperties": False,
}


EPISODE_CREATION_BLUEPRINT_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {
            "type": "string",
            "description": "The stable change in the world this Episode should achieve.",
        },
        "unit": {
            "type": "string",
            "description": "One complete repeatable attempt-observe-learn cycle.",
        },
        "result": {
            "type": "string",
            "description": "The concrete artifact, state, or typed outcome produced.",
        },
        "progress": {
            "type": "object",
            "description": "One host-observable numeric progress quantity.",
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
            "description": "Success target and numerical no-progress behavior.",
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
            "description": "Least-privilege execution tools assigned to this Episode.",
            "items": {"type": "string"},
            "uniqueItems": True,
        },
        "creator_contract": EPISODE_CREATOR_CONTRACT_BLUEPRINT_SCHEMA,
        "deliverable": EPISODE_DELIVERABLE_BLUEPRINT_SCHEMA,
        "safety_bounds": EPISODE_SAFETY_BOUNDS_BLUEPRINT_SCHEMA,
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
    "EPISODE_CREATOR_CONTRACT_BLUEPRINT_SCHEMA",
    "EPISODE_DELIVERABLE_BLUEPRINT_SCHEMA",
    "EPISODE_SAFETY_BOUNDS_BLUEPRINT_SCHEMA",
    "EPISODE_WORKFLOW_BLUEPRINT_SCHEMA",
    "creation_blueprint_from_spec",
    "creation_spec_from_blueprint",
    "workflow_blueprint_from_spec",
    "workflow_spec_from_blueprint",
]
