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
        "validation, exact human approval state, and project launch setup: "
        "model slots, routes, credential references and launch approval."
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
}


_LAUNCH_SETTING = {"anyOf": [
    {"type": "string"},
    {"type": "object", "properties": {"env": {"type": "string"}},
     "required": ["env"], "additionalProperties": False},
]}

DUET_LAUNCH_PROPOSE_SCHEMA = {
    "name": "duet_launch_propose",
    "description": (
        "Prepare a complete project launch configuration for human review. "
        "Proposals contain model settings and credential references, never secret "
        "values. This saves a proposal only. The human selects a file destination "
        "and approves its resolved settings through /launch. model_slots maps "
        "function-level model_type names to routes; builder_slots selects slots "
        "for planning and emission. env_files are relative to project_root."
    ),
    "parameters": {
        "type": "object", "required": ["configuration"], "additionalProperties": False,
        "properties": {"configuration": {
            "type": "object", "additionalProperties": False,
            "required": ["project", "project_root", "env_files", "routes", "model_slots", "builder_slots"],
            "properties": {
                "project": {"type": "string"},
                "project_root": {"type": "string"},
                "env_files": {"type": "array", "items": {"type": "string"}},
                "model_slots": {"type": "object", "additionalProperties": {"type": "string"}},
                "builder_slots": {
                    "type": "object", "required": ["planning", "emission"], "additionalProperties": False,
                    "properties": {"planning": {"type": "string"}, "emission": {"type": "string"}},
                },
                "routes": {"type": "object", "additionalProperties": {
                    "type": "object", "additionalProperties": False,
                    "required": ["provider", "model", "base_url", "api_mode", "auth"],
                    "properties": {
                        **{name: _LAUNCH_SETTING for name in ("provider", "model", "base_url", "api_mode")},
                        "auth": {"type": "object", "additionalProperties": False,
                                 "required": ["kind"], "properties": {
                                     "kind": {"type": "string", "enum": ["env", "codex_login", "none"]},
                                     "env": {"type": "string"}, "account": {"type": "string"},
                                 }},
                        "reasoning": {"type": "object", "additionalProperties": False,
                                      "required": ["enabled", "effort"], "properties": {
                                          "enabled": {"type": "boolean"}, "effort": {"type": "string"},
                                      }},
                        "fallbacks": {"type": "array", "items": {"type": "string"}},
                    },
                }},
            },
        }},
    },
}


EPISODE_ARCHITECTURE_SUBMIT_SCHEMA = {
    "name": "episode_architecture_submit",
    "description": (
        "Submit the complete mutable workflow Architecture during initial Duet "
        "design. Bind a replacement to the exact current draft identity (the "
        "artifact id, content hash and revision exactly as duet_status reports "
        "them), or pass JSON null — not the string \"null\" — in all three "
        "expected_* fields for the first Architecture. The host validates and "
        "persists the candidate; approved Architectures use the separate "
        "refinement operation."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "candidate_workflow_architecture": (
                EPISODE_WORKFLOW_BLUEPRINT_SCHEMA
            ),
            "expected_artifact_id": {
                "type": ["string", "null"],
                "description": "Exact current mutable draft ID, or null for the first draft.",
            },
            "expected_content_hash": {
                "type": ["string", "null"],
                "description": "Exact current mutable draft content hash, or null for the first draft.",
            },
            "expected_revision": {
                "type": ["integer", "null"],
                "minimum": 1,
                "description": "Exact current mutable draft revision, or null for the first draft.",
            },
            "human_note_ids": {
                "type": "array",
                "items": {"type": "string"},
                "uniqueItems": True,
                "description": "Saved initial-Architecture human notes addressed by this candidate.",
            },
        },
        "required": [
            "candidate_workflow_architecture",
            "expected_artifact_id",
            "expected_content_hash",
            "expected_revision",
            "human_note_ids",
        ],
        "additionalProperties": False,
    },
}


EPISODE_WORKSPACE_READ_SCHEMA = {
    "name": "episode_workspace_read",
    "description": (
        "Read one host-selected, already validated Architecture or Materialized "
        "part by its opaque target ID, or recover the exact historical part "
        "anchored by a saved human note ID. Returns exact target metadata, saved "
        "human notes, and separately delimited untrusted reference data. A "
        "terminal baseline also includes its validated Run evidence, audit "
        "events, and durable log location inside that untrusted block."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target_id": {
                "type": "string",
                "description": (
                    "Opaque ID of the saved target selected through the "
                    "host-owned refinement workspace."
                ),
            },
            "note_id": {
                "type": "string",
                "description": (
                    "Opaque ID of a saved human note whose exact historical "
                    "workspace target must be recovered."
                ),
            },
        },
        "oneOf": [
            {"required": ["target_id"]},
            {"required": ["note_id"]},
        ],
        "additionalProperties": False,
    },
}


EPISODE_REFINEMENT_REQUEST_SCHEMA = {
    "name": "episode_refinement_request",
    "description": (
        "Submit one atomic refinement proposal against an exact baseline. "
        "Carry the complete candidate workflow Architecture, the IDs of saved "
        "human notes used, and any implementation directives linked to exact "
        "saved note and target IDs. The host validates, classifies, and mints "
        "all proposal and decision identities."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "baseline_id": {
                "type": "string",
                "description": "Exact immutable refinement baseline ID.",
            },
            "candidate_workflow_architecture": (
                EPISODE_WORKFLOW_BLUEPRINT_SCHEMA
            ),
            "human_note_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "uniqueItems": True,
                "description": (
                    "Exact IDs of persisted human-authored workspace notes "
                    "translated by this proposal."
                ),
            },
            "implementation_directives": {
                "type": "array",
                "description": (
                    "Implementation directives, each grounded in one saved "
                    "human note and its exact saved target."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "human_note_id": {"type": "string"},
                        "target_id": {"type": "string"},
                        "instruction": {"type": "string"},
                    },
                    "required": [
                        "human_note_id",
                        "target_id",
                        "instruction",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "baseline_id",
            "candidate_workflow_architecture",
            "human_note_ids",
            "implementation_directives",
        ],
        "additionalProperties": False,
    },
}


def _agent_bound_only(**_kwargs: Any) -> dict[str, Any]:
    raise RuntimeError("Duet tools require an active OpenChia-bound agent")


for schema in (
    OPENCHIA_SCOPE_SCHEMA,
    DUET_STATUS_SCHEMA,
    DUET_LAUNCH_PROPOSE_SCHEMA,
    EPISODE_ARCHITECTURE_SUBMIT_SCHEMA,
    EPISODE_WORKSPACE_READ_SCHEMA,
    EPISODE_REFINEMENT_REQUEST_SCHEMA,
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
    "DUET_LAUNCH_PROPOSE_SCHEMA",
    "EPISODE_ARCHITECTURE_SUBMIT_SCHEMA",
    "EPISODE_REFINEMENT_REQUEST_SCHEMA",
    "EPISODE_WORKSPACE_READ_SCHEMA",
    "OPENCHIA_SCOPE_SCHEMA",
]
