"""Closed qualitative records. Text remains evidence-bearing data, never policy code."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping

from .epistemic_contract import exact, names
from .models import _freeze_json, _thaw_json, _text


def _closed_shape(**properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _array_shape(items, *, nonempty=False, unique=False):
    return {
        "type": "array",
        "items": items,
        "minItems": int(nonempty),
        "uniqueItems": unique,
    }


_TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
_NAMES = _array_shape(_TEXT, nonempty=True, unique=True)
# Descriptive schema is part of the exact registered definition. The existing
# validator below remains authoritative; no model-supplied schema is accepted.
ATTEMPT_SHAPE = _freeze_json(
    _closed_shape(
        action_class=_TEXT,
        action_inputs={"type": "object"},
        status={"enum": ["succeeded", "failed", "inconclusive", "blocked"]},
        expected_observation=_TEXT,
        observed_outcome=_TEXT,
        candidate_lessons=_array_shape(
            _closed_shape(
                claim=_TEXT,
                scope_tier=_TEXT,
                action_class=_TEXT,
                reopening_conditions=_NAMES,
                evidence_refs=_NAMES,
            )
        ),
        entities=_array_shape(
            _closed_shape(
                key=_TEXT,
                fields={
                    "type": "object",
                    "additionalProperties": _TEXT,
                    "description": "Exactly contract.required_fields; every value is a string, including serialized structured answers.",
                },
                evidence=_array_shape(
                    _closed_shape(kind=_TEXT, ref=_TEXT, quote=_TEXT)
                ),
                answer_contract=_closed_shape(
                    answer_forms=_NAMES,
                    acceptance_tests=_NAMES,
                    falsification_tests=_NAMES,
                ),
                uncertainties=_array_shape(_TEXT, unique=True),
            )
        ),
        revisions=_array_shape(
            _closed_shape(
                target_id=_TEXT,
                kind={
                    "enum": [
                        "superseded",
                        "narrowed",
                        "contradicted_pending_resolution",
                        "reopened",
                        "invalidated",
                    ]
                },
                evidence_refs=_NAMES,
                reason=_TEXT,
            )
        ),
    ),
    "attempt_shape",
)


def canonical(value: object) -> bytes:
    return json.dumps(
        _thaw_json(_freeze_json(value, "artifact")),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def identity(kind: str, value: object) -> str:
    return f"{kind}_{hashlib.sha256(canonical(value)).hexdigest()}"


def model_call_id(text: str, task: str, route: Mapping) -> str:
    return identity(
        "call",
        {
            "raw_response": text,
            "task": task,
            "route": {str(k): str(v) for k, v in route.items() if v is not None},
        },
    )


@dataclass(frozen=True)
class ArtifactEnvelope:
    schema_id: str
    schema_version: int
    episode_id: str
    run_id: str
    unit_id: str
    producer_call_id: str
    evidence_refs: tuple[str, ...]
    body: Mapping[str, object]
    parent_artifact_ids: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "schema_id",
            "episode_id",
            "run_id",
            "unit_id",
            "producer_call_id",
        ):
            _text(getattr(self, name), name)
        if type(self.schema_version) is not int or self.schema_version < 1:
            raise ValueError("schema version must be a positive integer")
        for name in ("evidence_refs", "parent_artifact_ids", "supersedes"):
            object.__setattr__(self, name, names(getattr(self, name), name))
        if not isinstance(self.body, Mapping):
            raise ValueError("artifact body must be an object")
        object.__setattr__(self, "body", _freeze_json(self.body, "body"))

    def semantic_record(self) -> dict:
        return {
            name: _thaw_json(getattr(self, name)) for name in self.__dataclass_fields__
        }

    def as_record(self) -> dict:
        record = self.semantic_record()
        return {
            "artifact_id": identity("artifact", record),
            "content_hash": "sha256:" + hashlib.sha256(canonical(record)).hexdigest(),
            **record,
        }


def _objects(value: object, name: str) -> tuple[Mapping, ...]:
    if not isinstance(value, (tuple, list)) or any(
        not isinstance(v, Mapping) for v in value
    ):
        raise ValueError(f"{name} must be an array of objects")
    return tuple(value)


def validate_attempt(value: object) -> Mapping:
    record = exact(
        value,
        {
            "action_class",
            "action_inputs",
            "status",
            "expected_observation",
            "observed_outcome",
            "candidate_lessons",
            "entities",
            "revisions",
        },
        "reasoning attempt",
    )
    for name in ("action_class", "expected_observation", "observed_outcome"):
        _text(record[name], name)
    if not isinstance(record["action_inputs"], Mapping):
        raise ValueError("action inputs must be a typed object")
    if record["status"] not in {"succeeded", "failed", "inconclusive", "blocked"}:
        raise ValueError("invalid attempt status")
    for lesson in _objects(record["candidate_lessons"], "candidate lessons"):
        exact(
            lesson,
            {
                "claim",
                "scope_tier",
                "action_class",
                "reopening_conditions",
                "evidence_refs",
            },
            "candidate lesson",
        )
        _text(lesson["claim"], "lesson claim")
        names(lesson["reopening_conditions"], "reopening conditions", nonempty=True)
        names(lesson["evidence_refs"], "lesson evidence", nonempty=True)
        _text(lesson["scope_tier"], "scope tier")
        _text(lesson["action_class"], "lesson action class")
    for entity in _objects(record["entities"], "entities"):
        exact(
            entity,
            {"key", "fields", "evidence", "answer_contract", "uncertainties"},
            "entity",
        )
        _text(entity["key"], "entity key")
        if not isinstance(entity["fields"], Mapping):
            raise ValueError("entity fields must be an object")
        for value in entity["fields"].values():
            _text(value, "entity field")
        names(entity["uncertainties"], "uncertainties")
        for evidence in _objects(entity["evidence"], "entity evidence"):
            exact(evidence, {"kind", "ref", "quote"}, "evidence link")
            for value in evidence.values():
                _text(value, "evidence link")
        answer = exact(
            entity["answer_contract"],
            {"answer_forms", "acceptance_tests", "falsification_tests"},
            "answer contract",
        )
        for name, value in answer.items():
            names(value, name, nonempty=True)
    for revision in _objects(record["revisions"], "revisions"):
        exact(revision, {"target_id", "kind", "evidence_refs", "reason"}, "revision")
        if revision["kind"] not in {
            "superseded",
            "narrowed",
            "contradicted_pending_resolution",
            "reopened",
            "invalidated",
        }:
            raise ValueError("unknown revision transition")
        _text(revision["target_id"], "revision target")
        _text(revision["reason"], "revision reason")
        names(revision["evidence_refs"], "revision evidence", nonempty=True)
    return _freeze_json(record, "attempt")


def project_candidates(result: Mapping) -> tuple[dict, ...]:
    return tuple(
        {"kind": kind, "body": _thaw_json(item)}
        for kind, field in (
            ("lesson", "candidate_lessons"),
            ("entity", "entities"),
            ("revision", "revisions"),
        )
        for item in result[field]
    )


def project_result(state: Mapping) -> dict:
    active = [item for item in state["records"] if item["status"] == "active"]
    return {
        "admitted_problem_frontier": [
            item for item in active if item["kind"] == "entity"
        ],
        "answer_contracts": [
            item["body"]["answer_contract"]
            for item in active
            if item["kind"] == "entity"
        ],
        "durable_lessons": [item for item in active if item["kind"] == "lesson"],
        "retired_candidates": [
            item for item in state["records"] if item["status"] != "active"
        ],
        "unresolved_decisive_uncertainties": sorted({
            v
            for item in active
            if item["kind"] == "entity"
            for v in item["body"]["uncertainties"]
        }),
    }
