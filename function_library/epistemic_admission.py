"""Deterministic admission from host-committed observations and scoped state."""

from __future__ import annotations

import hashlib
from typing import Mapping

from .epistemic_contract import EpistemicContract
from .epistemic_schemas import canonical, identity
from .models import _freeze_json, _thaw_json


def scope_record(
    contract: EpistemicContract, *, episode_id: str, workflow_id: str
) -> dict:
    return {
        "tier": contract.scope_tier,
        "key": episode_id if contract.scope_tier == "episode" else workflow_id,
        "goal_class": contract.goal_class,
        "domain": contract.domain,
        "environment": _thaw_json(contract.environment),
        "assumptions": sorted(contract.assumptions),
    }


def applicable(record: Mapping, scope: Mapping) -> bool:
    return record["status"] == "active" and record["scope"] == scope


def _hash(record):
    return (
        "sha256:"
        + hashlib.sha256(
            canonical({k: v for k, v in record.items() if k != "content_hash"})
        ).hexdigest()
    )


def _evidence(refs: object, evidence: Mapping) -> tuple[Mapping, ...]:
    if (
        not isinstance(refs, (list, tuple))
        or not refs
        or any(ref not in evidence for ref in refs)
    ):
        raise ValueError("support requires committed authorized evidence")
    return tuple(evidence[ref] for ref in refs)


def _lesson(
    body: Mapping,
    result: Mapping,
    contract: EpistemicContract,
    scope: Mapping,
    evidence: Mapping,
) -> tuple[str, dict, tuple[str, ...]]:
    if body["scope_tier"] != contract.scope_tier:
        raise ValueError("lesson exceeds or changes frozen scope authority")
    if result["status"] != "failed" or body["action_class"] != result["action_class"]:
        raise ValueError("negative knowledge must describe the current failed action")
    support = _evidence(body["evidence_refs"], evidence)
    expected = {
        "action_class": result["action_class"],
        "goal_class": contract.goal_class,
        "action_inputs": _thaw_json(result["action_inputs"]),
        "environment": _thaw_json(contract.environment),
        "assumptions": sorted(contract.assumptions),
        "expected_observation": result["expected_observation"],
        "observed_outcome": result["observed_outcome"],
        "status": "failed",
    }
    if expected["expected_observation"] == expected["observed_outcome"]:
        raise ValueError("failure needs a distinct expected and observed outcome")
    if not any(item["body"]["observation"] == expected for item in support):
        raise ValueError(
            "failure narration lacks an independently committed matching observation"
        )
    # Neither prose nor a model-selected lesson ID determines equivalence or policy.
    key = identity(
        "lesson",
        {
            "scope": scope,
            "action_class": result["action_class"],
            "action_inputs": result["action_inputs"],
        },
    )
    admitted = {
        "claim": f"A recorded attempt of {result['action_class']} for {contract.goal_class} failed under the attached conditions.",
        "action_class": result["action_class"],
        "expected_observation": result["expected_observation"],
        "action_inputs": _thaw_json(result["action_inputs"]),
        "observed_outcome": result["observed_outcome"],
        "policy_effect": {
            "kind": "avoid_repetition",
            "strength": contract.policy_strength,
            "target_action_class": result["action_class"],
        },
        "reopening_conditions": [
            "environment_changed",
            "assumptions_changed",
            "action_inputs_changed",
            "admitted_contrary_observation",
        ],
        "known_limitations": [
            "One recorded attempt; no claim of universal impossibility."
        ],
    }
    return key, admitted, tuple(body["evidence_refs"])


def _entity(
    body: Mapping, contract: EpistemicContract, scope: Mapping, evidence: Mapping
) -> tuple[str, dict, tuple[str, ...]]:
    if set(body["fields"]) != set(contract.required_fields):
        raise ValueError(
            "formulation must satisfy exactly the frozen field requirements"
        )
    kinds = set()
    refs = []
    anchors = []
    for link in body["evidence"]:
        source = _evidence([link["ref"]], evidence)[0]
        if (
            link["kind"] != source["body"]["kind"]
            or link["quote"] not in source["body"]["text"]
        ):
            raise ValueError(
                "evidence must quote the committed source in its declared class"
            )
        kinds.add(link["kind"])
        refs.append(link["ref"])
        anchors.append(source["content_hash"])
    if not set(contract.required_evidence).issubset(kinds):
        raise ValueError("missing required evidence classes, including counterevidence")
    # Evidence-equivalent formulations share an identity. Model labels are display data.
    key = identity("entity", {"scope": scope, "anchors": sorted(set(anchors))})
    return key, _thaw_json(body), tuple(sorted(set(refs)))


def admit_candidates(
    *,
    contract: EpistemicContract,
    result: Mapping,
    candidates: tuple,
    prior_state: Mapping,
    evidence: Mapping,
    scope: Mapping,
    audit_ref: str,
) -> dict:
    records = _thaw_json(_freeze_json(prior_state["records"], "prior state"))
    by_id = {item["record_id"]: item for item in records}
    transitions, rejected = [], []
    touched = set()
    handlers = {"lesson": _lesson, "entity": _entity}
    for candidate in candidates:
        body, kind = candidate["body"], candidate["kind"]
        candidate_id = identity("candidate", {"scope": scope, **candidate})
        try:
            if kind == "revision":
                target = by_id.get(body["target_id"])
                support = _evidence(body["evidence_refs"], evidence)
                if target is None or target["scope"] != scope:
                    raise ValueError("revision target is outside writable scope")
                if target["record_id"] in touched:
                    raise ValueError("a unit cannot admit and revise the same record")
                selectors = [{"target_id": target["record_id"], "kind": body["kind"]}]
                if target["kind"] == "lesson":
                    selectors.append({
                        "action_class": target["body"]["action_class"],
                        "kind": body["kind"],
                        "action_inputs": target["body"]["action_inputs"],
                        "environment": scope["environment"],
                    })
                if not any(
                    item["body"]["observation"].get("revises") in selectors
                    for item in support
                ):
                    raise ValueError("revision needs independent contrary evidence")
                if target["status"] != "active":
                    raise ValueError("revision target is no longer operative")
                before = dict(target)
                target["status"] = body["kind"]
                target["content_hash"] = _hash(target)
                transition = {
                    "event_type": "action_class_reopened"
                    if body["kind"] == "reopened"
                    else "entity_invalidated",
                    "before": before,
                    "after": dict(target),
                    "evidence_refs": list(body["evidence_refs"]),
                }
            else:
                args = (
                    (body, result, contract, scope, evidence)
                    if kind == "lesson"
                    else (body, contract, scope, evidence)
                )
                key, admitted, refs = handlers[kind](*args)
                previous = [
                    r
                    for r in records
                    if r.get("equivalence_key", r["record_id"]) == key
                ]
                supersedes = []
                equivalence_key = key
                if previous:
                    if any(r["status"] == "active" for r in previous) or set(
                        refs
                    ).issubset({ref for r in previous for ref in r["evidence_refs"]}):
                        raise ValueError(
                            "duplicate or previously explored equivalent state; zero incremental yield"
                        )
                    supersedes = [r["record_id"] for r in previous]
                    key = identity(
                        kind,
                        {
                            "equivalence_key": key,
                            "evidence_refs": refs,
                            "supersedes": supersedes,
                        },
                    )
                if kind == "entity" and any(
                    item["kind"] == "entity"
                    and item["scope"] == scope
                    and set(refs).intersection(item["evidence_refs"])
                    for item in records
                ):
                    raise ValueError(
                        "overlapping evidence formulation requires explicit revision, not additional credit"
                    )
                record = {
                    "record_id": key,
                    "equivalence_key": equivalence_key,
                    "supersedes": supersedes,
                    "schema_id": f"openchia.admitted-{kind}",
                    "schema_version": 1,
                    "kind": kind,
                    "status": "active",
                    "scope": dict(scope),
                    "body": admitted,
                    "evidence_refs": list(refs),
                    "candidate_id": candidate_id,
                    "admission_audit_ref": audit_ref,
                }
                record["content_hash"] = _hash(record)
                records.append(record)
                by_id[key] = record
                transition = {
                    "event_type": "action_class_excluded"
                    if kind == "lesson"
                    else "answer_contract_completed",
                    "before": None,
                    "after": record,
                    "evidence_refs": list(refs),
                }
            touched.add(transition["after"]["record_id"])
            transition["candidate_id"] = candidate_id
            transition["audit_ref"] = audit_ref
            transition["transition_id"] = identity("transition", transition)
            transitions.append(transition)
        except (ValueError, KeyError) as exc:
            rejected.append({"candidate_id": candidate_id, "reason": str(exc)})
    return {
        "state": {"records": records},
        "transitions": transitions,
        "rejections": rejected,
    }


def measure_yield(
    *, prior_state: Mapping, next_state: Mapping, admitted_delta: Mapping
) -> dict:
    """Only new, operative evidence-backed state earns a distinct identity."""
    before = {item["record_id"]: item for item in prior_state["records"]}
    after = {item["record_id"]: item for item in next_state["records"]}
    identities = []
    for event in admitted_delta["transitions"]:
        if (
            not event["audit_ref"]
            or not event["evidence_refs"]
            or event["after"] != after.get(event["after"]["record_id"])
        ):
            raise ValueError(
                "yield must reference an admitted evidence-backed state delta"
            )
        key = event["after"]["record_id"]
        if event["before"] != before.get(key):
            raise ValueError("yield predecessor differs from durable state")
        known = {
            item.get("equivalence_key", item["record_id"])
            for item in prior_state["records"]
        }
        if (
            event["before"] is None
            and event["after"]["status"] == "active"
            and event["after"].get("equivalence_key", key) not in known
        ):
            identities.append(key)
    return {
        "realized_yield": len(set(identities)),
        "identity_ids": sorted(set(identities)),
        "transition_ids": [
            item["transition_id"] for item in admitted_delta["transitions"]
        ],
        "evidence_refs": sorted({
            ref
            for item in admitted_delta["transitions"]
            for ref in item["evidence_refs"]
        }),
    }
