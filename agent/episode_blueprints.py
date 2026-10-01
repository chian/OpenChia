"""Translate model-friendly Episode blueprints into immutable design contracts.

Models describe goals, progress credit, continuation semantics, capabilities,
topology, and optional durable library references. Executable function binding
belongs to EpisodeBuilder, after the Duet design has been frozen.
"""

from __future__ import annotations

from typing import Any, Mapping

from agent.episode_contracts import (
    EpisodeCreationSpec,
    EpisodeWorkflowSpec,
    MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
    MAX_EPISODE_GOAL_CHARS,
)


CREATION_BLUEPRINT_FIELDS = (
    "goal",
    "unit",
    "result",
    "progress",
    "stopping",
    "execution_capability_names",
    "deliverable",
)
_CREATION_FIELDS = set(CREATION_BLUEPRINT_FIELDS)
_WORKFLOW_NODE_FIELDS = {
    "local_id",
    "workflow_parent_local_id",
    "contract",
}
_OPTIONAL_WORKFLOW_NODE_FIELDS = {"episode_reference"}


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


def creation_blueprint_from_spec(spec: EpisodeCreationSpec) -> dict[str, Any]:
    """Project an internal contract into the schema a model may edit."""

    if not isinstance(spec, EpisodeCreationSpec):
        raise TypeError("creation blueprint projection requires an EpisodeCreationSpec")
    record = spec.as_record()
    return {
        "goal": record["goal"],
        "unit": record["unit"],
        "result": record["result"],
        "progress": record["progress"],
        "stopping": record["stopping"],
        "execution_capability_names": record["execution_capability_names"],
        "deliverable": record["deliverable"],
    }


def creation_spec_from_blueprint(
    value: object,
) -> EpisodeCreationSpec:
    """Validate a model-facing Episode design contract."""

    record = _object(value, "Episode creation blueprint")
    _exact_fields(record, _CREATION_FIELDS, "Episode creation blueprint")
    internal = {
        "goal": record["goal"],
        "unit": record["unit"],
        "result": record["result"],
        "progress": record["progress"],
        "stopping": record["stopping"],
        "execution_capability_names": record["execution_capability_names"],
        "deliverable": record["deliverable"],
        "capability_inheritance": "inherit_parent",
    }
    return EpisodeCreationSpec.from_record(internal)


def workflow_blueprint_from_spec(workflow: EpisodeWorkflowSpec) -> dict[str, Any]:
    if not isinstance(workflow, EpisodeWorkflowSpec):
        raise TypeError("workflow blueprint projection requires an EpisodeWorkflowSpec")
    return {
        "episodes": [
            {
                "local_id": item.local_id,
                "workflow_parent_local_id": item.workflow_parent_local_id,
                "contract": creation_blueprint_from_spec(item.contract),
                "episode_reference": (
                    None
                    if item.episode_reference is None
                    else item.episode_reference.as_record()
                ),
            }
            for item in workflow.episodes
        ]
    }


def workflow_spec_from_blueprint(
    value: object,
) -> EpisodeWorkflowSpec:
    """Translate one complete Duet workflow blueprint."""

    record = _object(value, "Episode workflow blueprint")
    _exact_fields(record, {"episodes"}, "Episode workflow blueprint")
    raw_episodes = record["episodes"]
    if not isinstance(raw_episodes, list) or not raw_episodes:
        raise ValueError("workflow blueprint episodes must be a non-empty array")
    episodes = []
    for index, raw_node in enumerate(raw_episodes):
        node = _object(raw_node, f"workflow node {index}")
        actual_fields = set(node)
        if not _WORKFLOW_NODE_FIELDS.issubset(actual_fields) or not actual_fields.issubset(
            _WORKFLOW_NODE_FIELDS | _OPTIONAL_WORKFLOW_NODE_FIELDS
        ):
            raise ValueError(
                f"malformed workflow node {index}: "
                f"missing={sorted(_WORKFLOW_NODE_FIELDS - actual_fields)!r}, "
                f"unknown={sorted(actual_fields - _WORKFLOW_NODE_FIELDS - _OPTIONAL_WORKFLOW_NODE_FIELDS)!r}"
            )
        episodes.append(
            {
                "local_id": node["local_id"],
                "workflow_parent_local_id": node["workflow_parent_local_id"],
                "contract": creation_spec_from_blueprint(node["contract"]).as_record(),
                "episode_reference": node.get("episode_reference"),
            }
        )
    return EpisodeWorkflowSpec.from_record(
        {
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
        "description": {
            "type": "string",
            "maxLength": MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
        },
        "tool_names": {
            "type": "array",
            "items": {"type": "string"},
            "uniqueItems": True,
        },
    },
    "required": ["kind", "description", "tool_names"],
    "additionalProperties": False,
}


EPISODE_CREATION_BLUEPRINT_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {
            "type": "string",
            "maxLength": MAX_EPISODE_GOAL_CHARS,
            "description": "The stable change in the world this Episode should achieve.",
        },
        "unit": {
            "type": "string",
            "maxLength": MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
            "description": "One complete repeatable attempt-observe-learn cycle.",
        },
        "result": {
            "type": "string",
            "maxLength": MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
            "description": "The concrete artifact, state, or typed outcome produced.",
        },
        "progress": {
            "type": "string",
            "maxLength": MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
            "description": (
                "A concise code specification for the measured numeric credit or "
                "progress signal produced after each unit. EpisodeBuilder binds its "
                "implementation explicitly in the built Episode module."
            ),
        },
        "stopping": {
            "type": "string",
            "maxLength": MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
            "description": (
                "A concise code specification for numerical continuation and closure. "
                "It states how measured credit and paired-incidence future-credit "
                "estimates determine another unit or a typed stop. EpisodeBuilder "
                "binds the referenced functions and parameters explicitly."
            ),
        },
        "execution_capability_names": {
            "type": "array",
            "description": "Least-privilege execution tools assigned to this Episode.",
            "items": {"type": "string"},
            "uniqueItems": True,
        },
        "deliverable": EPISODE_DELIVERABLE_BLUEPRINT_SCHEMA,
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
                    "episode_reference": {
                        "oneOf": [
                            {"type": "null"},
                            {
                                "type": "object",
                                "properties": {
                                    "episode_id": {"type": "string"},
                                },
                                "required": ["episode_id"],
                                "additionalProperties": False,
                            },
                        ],
                        "description": (
                            "Optional durable Episode library design to use as a "
                            "reference while building this node."
                        ),
                    },
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
    "EPISODE_DELIVERABLE_BLUEPRINT_SCHEMA",
    "EPISODE_WORKFLOW_BLUEPRINT_SCHEMA",
    "creation_blueprint_from_spec",
    "creation_spec_from_blueprint",
    "workflow_blueprint_from_spec",
    "workflow_spec_from_blueprint",
]
