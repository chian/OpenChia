"""Translate model-friendly Episode blueprints into immutable design contracts.

Models describe goals, progress credit, continuation semantics, exact numerical
function selections, capabilities, topology, and optional durable library
references. Task-specific executable binding belongs to EpisodeBuilder after
the Duet design has been frozen; rarefaction and continuation bindings do not.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from agent.duet_contracts import ContractDeficit, content_id
from agent.episode_contracts import (
    EpisodeContractError,
    EpisodeCreationSpec,
    EpisodeFunctionSelectionSpec,
    EpisodeNumericalControlSpec,
    EpisodeWorkflowSpec,
    MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
    MAX_EPISODE_GOAL_CHARS,
    OpaqueId,
    Sha256Digest,
)
from function_library import LibraryFunction
from function_library.epistemic import epistemic_function_library
from numeric_control_library.continuation import continuation_function_library
from numeric_control_library.rarefaction import rarefaction_function_library


CREATION_BLUEPRINT_FIELDS = (
    "goal",
    "unit",
    "result",
    "progress",
    "stopping",
    "numeric_control",
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
WORKFLOW_DRAFT_FIELDS = {
    "duet_id",
    "revision",
    "source_stage",
    "workflow_blueprint_hash",
    "workflow_blueprint",
    "workflow_hash",
    "validation_deficits",
    "ready",
    "refinement_id",
    "baseline_id",
    "proposal_id",
    "human_note_ids",
}
INITIAL_WORKFLOW_SOURCE_STAGES = frozenset({"duet", "human_edit"})
REFINEMENT_WORKFLOW_SOURCE_STAGES = frozenset(
    {"refinement_duet", "refinement_human_edit"}
)


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


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _selection_record(function: LibraryFunction) -> dict[str, object]:
    return {
        "library": function.library,
        "function_id": function.function_id,
        "interface": function.interface,
        "definition_id": function.definition_id,
    }


def _selection_schema(function: LibraryFunction) -> dict[str, object]:
    parameter_schema = function.provenance.get("parameter_schema")
    if not isinstance(parameter_schema, Mapping):
        raise ValueError(
            f"{function.component_id} has no function-owned parameter schema"
        )
    identity = _selection_record(function)
    return {
        "type": "object",
        "description": (
            f"Exact registered selection {function.component_id}: "
            f"{function.description} Its arguments are part of the "
            "human-approved Architecture."
        ),
        "properties": {
            name: {"type": "string", "enum": [value]}
            for name, value in identity.items()
        }
        | {"arguments": _plain_json(parameter_schema)},
        "required": [*identity, "arguments"],
        "additionalProperties": False,
    }


_RAREFACTION_FUNCTIONS = tuple(
    function
    for function in rarefaction_function_library.functions()
    if (
        rarefaction_function_library.evaluation_report(function.component_id)
        is not None
    )
)
_CONTINUATION_FUNCTIONS = continuation_function_library.functions()


def _admit_selection(
    selection: EpisodeFunctionSelectionSpec,
    functions: tuple[LibraryFunction, ...],
    *,
    role: str,
) -> None:
    function = next(
        (
            item
            for item in functions
            if item.definition_id == selection.definition_id
        ),
        None,
    )
    if function is None:
        raise EpisodeContractError(
            f"{role} must name a registered admissible function definition",
            field_path=("numeric_control", role, "definition_id"),
        )
    expected = _selection_record(function)
    actual = {
        "library": selection.library,
        "function_id": selection.function_id,
        "interface": selection.interface,
        "definition_id": selection.definition_id,
    }
    if actual != expected:
        raise EpisodeContractError(
            f"{role} readable function pointer differs from its definition ID",
            field_path=("numeric_control", role),
        )
    try:
        function.admit_arguments(selection.arguments)
    except (TypeError, ValueError) as exc:
        raise EpisodeContractError(
            str(exc),
            field_path=("numeric_control", role, "arguments"),
        ) from exc
    if role == "rarefaction" and rarefaction_function_library.evaluation_report(
        function.component_id
    ) is None:
        raise EpisodeContractError(
            "rarefaction must name an evaluated registered function",
            field_path=("numeric_control", role, "definition_id"),
        )


def admit_numerical_control(spec: EpisodeNumericalControlSpec) -> None:
    """Admit exact Architecture-owned functions and their own arguments."""

    if not isinstance(spec, EpisodeNumericalControlSpec):
        raise TypeError("spec must be an EpisodeNumericalControlSpec")
    _admit_selection(
        spec.rarefaction,
        _RAREFACTION_FUNCTIONS,
        role="rarefaction",
    )
    _admit_selection(
        spec.continuation,
        _CONTINUATION_FUNCTIONS,
        role="continuation",
    )


def creation_blueprint_from_spec(spec: EpisodeCreationSpec) -> dict[str, Any]:
    """Project an internal contract into the schema a model may edit."""

    if not isinstance(spec, EpisodeCreationSpec):
        raise TypeError("creation blueprint projection requires an EpisodeCreationSpec")
    record = spec.as_record()
    blueprint = {
        "goal": record["goal"],
        "unit": record["unit"],
        "result": record["result"],
        "progress": record["progress"],
        "stopping": record["stopping"],
        "numeric_control": record["numeric_control"],
        "execution_capability_names": record["execution_capability_names"],
        "deliverable": record["deliverable"],
    }
    if "epistemic" in record:
        blueprint["epistemic"] = record["epistemic"]
    return blueprint


def creation_spec_from_blueprint(
    value: object,
) -> EpisodeCreationSpec:
    """Validate a model-facing Episode design contract."""

    record = _object(value, "Episode creation blueprint")
    _exact_fields(record, _CREATION_FIELDS | ({"epistemic"} if "epistemic" in record else set()), "Episode creation blueprint")
    internal = {
        "goal": record["goal"],
        "unit": record["unit"],
        "result": record["result"],
        "progress": record["progress"],
        "stopping": record["stopping"],
        "numeric_control": record["numeric_control"],
        "execution_capability_names": record["execution_capability_names"],
        "deliverable": record["deliverable"],
        "capability_inheritance": "inherit_parent",
    }
    if "epistemic" in record:
        internal["epistemic"] = record["epistemic"]
    spec = EpisodeCreationSpec.from_record(internal)
    admit_numerical_control(spec.numeric_control)
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
            missing = sorted(_WORKFLOW_NODE_FIELDS - actual_fields)
            unknown = sorted(
                actual_fields
                - _WORKFLOW_NODE_FIELDS
                - _OPTIONAL_WORKFLOW_NODE_FIELDS
            )
            raise ValueError(
                f"malformed workflow node {index}: "
                f"missing={missing!r}, unknown={unknown!r}"
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


def workflow_draft_record(
    *,
    duet_id: OpaqueId,
    revision: int,
    source_stage: str,
    blueprint: Mapping[str, Any],
    workflow: Optional[EpisodeWorkflowSpec],
    deficits: tuple[ContractDeficit, ...],
    refinement_id: Optional[OpaqueId],
    baseline_id: Optional[OpaqueId],
    proposal_id: Optional[OpaqueId],
    human_note_ids: tuple[OpaqueId, ...],
) -> tuple[dict[str, Any], Sha256Digest, OpaqueId]:
    """Encode the one immutable Architecture-draft artifact shape."""

    blueprint_hash = Sha256Digest.of_record(blueprint)
    record = {
        "duet_id": duet_id.value,
        "revision": revision,
        "source_stage": source_stage,
        "workflow_blueprint_hash": blueprint_hash.value,
        "workflow_blueprint": dict(blueprint),
        "workflow_hash": (
            None if workflow is None else workflow.workflow_hash.value
        ),
        "validation_deficits": [item.as_record() for item in deficits],
        "ready": not deficits,
        "refinement_id": (
            None if refinement_id is None else refinement_id.value
        ),
        "baseline_id": None if baseline_id is None else baseline_id.value,
        "proposal_id": None if proposal_id is None else proposal_id.value,
        "human_note_ids": [item.value for item in human_note_ids],
    }
    return record, blueprint_hash, content_id(
        "episode_workflow_draft",
        record,
    )


EPISODE_DELIVERABLE_BLUEPRINT_SCHEMA = {
    "type": "object",
    "description": (
        "How successful work becomes usable outside the Episode. The current "
        "isolated runtime returns a closed typed terminal status."
    ),
    "properties": {
        "kind": {"type": "string", "enum": ["typed_status"]},
        "description": {
            "type": "string",
            "maxLength": MAX_EPISODE_BLUEPRINT_TEXT_CHARS,
        },
        "tool_names": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 0,
            "uniqueItems": True,
        },
    },
    "required": ["kind", "description", "tool_names"],
    "additionalProperties": False,
}


EPISODE_NUMERICAL_CONTROL_BLUEPRINT_SCHEMA = {
    "type": "object",
    "description": (
        "Exact registered numerical functions and function-owned arguments. "
        "Human approval freezes these values, and EpisodeBuilder reproduces "
        "them verbatim."
    ),
    "properties": {
        "rarefaction": {
            "oneOf": [
                _selection_schema(function)
                for function in _RAREFACTION_FUNCTIONS
            ]
        },
        "continuation": {
            "oneOf": [
                _selection_schema(function)
                for function in _CONTINUATION_FUNCTIONS
            ]
        },
    },
    "required": ["rarefaction", "continuation"],
    "additionalProperties": False,
}


EPISODE_CREATION_BLUEPRINT_SCHEMA = {
    "type": "object",
    "properties": {
        "epistemic": {
            "type": "object",
            "description": "Optional exact reasoning policy: required for reasoning.generic and reasoning.inquiry. Evidence is human-approved source data. Components are exact registered epistemic selections.",
            "properties": {
                "goal_class": {"type": "string"}, "domain": {"type": "string"},
                "allowed_actions": {"type": "array", "items": {"type": "string"}},
                "environment": {"type": "object"},
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "required_fields": {"type": "array", "items": {"type": "string"}},
                "required_evidence": {"type": "array", "items": {"type": "string"}},
                "scope_tier": {"type": "string", "enum": ["episode", "workflow"]},
                "policy_strength": {"type": "string", "enum": ["advisory", "enforceable"]},
                "evidence": {"type": "array", "items": {"type": "object", "properties": {
                    "kind": {"type": "string"}, "text": {"type": "string"}, "observation": {"type": "object"}},
                    "required": ["kind", "text", "observation"], "additionalProperties": False}},
                "components": {"type": "object", "properties": {
                    function.interface.split(".")[-1]: _selection_schema(function)
                    for function in epistemic_function_library.functions()
                }, "required": ["result_schema", "state_projector", "admission", "yield_function", "result_projection"], "additionalProperties": False},
            },
            "required": ["goal_class", "domain", "allowed_actions", "environment", "assumptions", "required_fields", "required_evidence", "scope_tier", "policy_strength", "evidence", "components"],
            "additionalProperties": False,
        },
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
                "estimates determine another unit or a typed stop. numeric_control "
                "carries the exact approved functions and their own arguments; "
                "EpisodeBuilder uses those bindings verbatim."
            ),
        },
        "numeric_control": EPISODE_NUMERICAL_CONTROL_BLUEPRINT_SCHEMA,
        "execution_capability_names": {
            "type": "array",
            "description": (
                "External runtime collaborators assigned to this Episode. The "
                "current isolated runtime uses its admitted internal function "
                "libraries and model broker, so this list is empty."
            ),
            "items": {"type": "string"},
            "maxItems": 0,
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
    "EPISODE_NUMERICAL_CONTROL_BLUEPRINT_SCHEMA",
    "EPISODE_WORKFLOW_BLUEPRINT_SCHEMA",
    "INITIAL_WORKFLOW_SOURCE_STAGES",
    "REFINEMENT_WORKFLOW_SOURCE_STAGES",
    "WORKFLOW_DRAFT_FIELDS",
    "admit_numerical_control",
    "creation_blueprint_from_spec",
    "creation_spec_from_blueprint",
    "workflow_blueprint_from_spec",
    "workflow_draft_record",
    "workflow_spec_from_blueprint",
]
