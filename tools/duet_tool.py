"""Model-facing schemas for the restricted Duet protocol."""

from __future__ import annotations

from typing import Any

from agent.episode_blueprints import EPISODE_WORKFLOW_BLUEPRINT_SCHEMA
from tools.registry import registry


OPENCHIA_SCOPE_SCHEMA = {
    "name": "openchia_scope",
    "description": (
        "Read the exact host-derived authority boundary for this Duet: callable "
        "tools, assignable Episode capabilities, and allowed operations."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
}


DUET_STATUS_SCHEMA = {
    "name": "duet_status",
    "description": (
        "Read the durable Duet workflow state, current draft metadata, "
        "validation, and exact human approval state."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
}


EPISODE_WORKFLOW_READ_SCHEMA = {
    "name": "episode_workflow_read",
    "description": (
        "Read one exact Duet-owned Episode workflow revision after verifying "
        "its artifact identity and content hash."
    ),
    "parameters": {
        "type": "object",
        "properties": {"artifact_id": {"type": "string"}},
        "required": ["artifact_id"],
        "additionalProperties": False,
    },
}


EPISODE_WORKFLOW_UPDATE_SCHEMA = {
    "name": "episode_workflow_update",
    "description": (
        "Persist one complete Duet-owned Episode workflow revision. The host "
        "validates it deterministically and uses expected_workflow_hash as a "
        "compare-and-swap guard."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "expected_workflow_hash": {"type": ["string", "null"]},
            "workflow": EPISODE_WORKFLOW_BLUEPRINT_SCHEMA,
        },
        "required": ["expected_workflow_hash", "workflow"],
        "additionalProperties": False,
    },
}


def _agent_bound_only(**_kwargs: Any) -> dict[str, Any]:
    raise RuntimeError("Duet tools require an active OpenChia-bound agent")


for schema in (
    OPENCHIA_SCOPE_SCHEMA,
    DUET_STATUS_SCHEMA,
    EPISODE_WORKFLOW_READ_SCHEMA,
    EPISODE_WORKFLOW_UPDATE_SCHEMA,
):
    registry.register(
        schema["name"],
        "duet",
        schema,
        _agent_bound_only,
        is_async=False,
    )

__all__ = [
    "DUET_STATUS_SCHEMA",
    "EPISODE_WORKFLOW_READ_SCHEMA",
    "EPISODE_WORKFLOW_UPDATE_SCHEMA",
    "OPENCHIA_SCOPE_SCHEMA",
]
