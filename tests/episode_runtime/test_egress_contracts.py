"""A Run registration binds the approved egress allowlist into its identity.

``RunRegistration.egress_policy`` maps each node ``local_id`` to its approved
rules. It is part of ``semantic_record`` so the Run id and registration hash
change with it, and the worker receives it in INITIALIZE without any secret.
"""
from __future__ import annotations

from types import MappingProxyType

import pytest

from agent.episode_contracts import EpisodeEgressRule, OpaqueId, Sha256Digest
from episode_runtime.contracts import (
    RUNTIME_WORKER_ENTRYPOINT,
    RunEventKind,
    RunRegistration,
    RuntimeIdentity,
    RuntimePolicy,
)
from handoff_library import DuetLaunchRequest


def _rule(name: str = "ragstack_query", **overrides) -> EpisodeEgressRule:
    record = {
        "name": name,
        "host": "www.bv-brc.org",
        "path_prefix": "/ragstack/asm-next/api/",
        "methods": ["GET", "POST"],
        "read_only": True,
        "max_requests": 1500,
        "max_response_bytes": 262144,
        "credential": "patric",
    }
    record.update(overrides)
    return EpisodeEgressRule.from_record(record)


def _digest(label: str) -> Sha256Digest:
    return Sha256Digest.of_bytes(label.encode())


def _registration(egress_policy=None) -> RunRegistration:
    workflow_id = OpaqueId.mint("workflow", "egress")
    kwargs = {} if egress_policy is None else {"egress_policy": egress_policy}
    return RunRegistration(
        duet_id=OpaqueId.mint("duet", "egress"),
        admission_authority_id=OpaqueId.mint("admission", "egress"),
        admission_authority_hash=_digest("admission"),
        authority_head_approval_id=OpaqueId.mint("approval", "head"),
        authority_head_approval_hash=_digest("head"),
        workflow_approval_id=OpaqueId.mint("approval", "workflow"),
        workflow_approval_hash=_digest("workflow-approval"),
        workflow_id=workflow_id,
        workflow_hash=_digest("workflow"),
        build_request_id=OpaqueId.mint("build_request", "egress"),
        build_attempt_id=OpaqueId.mint("build_attempt", "egress"),
        build_receipt_id=OpaqueId.mint("build_receipt", "egress"),
        manifest_id=OpaqueId.mint("manifest", "egress"),
        manifest_hash=_digest("manifest"),
        launch_request=DuetLaunchRequest(
            request_id=OpaqueId.mint("request", "egress").value,
            workflow_id=workflow_id.value,
            goal_id=OpaqueId.mint("goal", "egress").value,
            artifact_ids_by_role={},
        ),
        runtime_identity=RuntimeIdentity(
            worker_entrypoint=RUNTIME_WORKER_ENTRYPOINT,
            runtime_source_manifest_id=OpaqueId.mint("runtime_source_manifest", "x"),
            runtime_source_manifest_hash=_digest("source"),
            interpreter_runtime_id=OpaqueId.mint("interpreter_runtime", "x"),
            interpreter_runtime_hash=_digest("interpreter"),
        ),
        runtime_policy=RuntimePolicy(),
        **kwargs,
    )


def test_registration_without_egress_records_an_empty_policy():
    registration = _registration()
    assert registration.semantic_record()["egress_policy"] == {}
    assert RunRegistration.from_record(registration.as_record()) == registration


def test_egress_policy_is_canonical_frozen_and_round_trips():
    registration = _registration(
        {"worker": [_rule()], "fetcher": (_rule("lookup", methods=["GET"]),)}
    )
    record = registration.semantic_record()["egress_policy"]
    assert list(record) == ["fetcher", "worker"]
    assert record["worker"] == [_rule().as_record()]
    assert isinstance(registration.egress_policy, MappingProxyType)
    assert registration.egress_policy["fetcher"] == (_rule("lookup", methods=["GET"]),)
    restored = RunRegistration.from_record(registration.as_record())
    assert restored == registration
    assert restored.registration_hash == registration.registration_hash


def test_run_identity_covers_the_egress_policy():
    plain = _registration()
    with_rule = _registration({"root": [_rule()]})
    smaller_budget = _registration({"root": [_rule(max_requests=1)]})
    assert len({plain.run_id, with_rule.run_id, smaller_budget.run_id}) == 3
    assert len(
        {
            plain.registration_hash,
            with_rule.registration_hash,
            smaller_budget.registration_hash,
        }
    ) == 3


def test_tampered_egress_policy_record_is_stale():
    record = _registration({"root": [_rule()]}).as_record()
    record["egress_policy"]["root"][0]["max_requests"] = 999999
    with pytest.raises(ValueError, match="stale"):
        RunRegistration.from_record(record)


@pytest.mark.parametrize(
    "policy",
    [
        {"root": []},
        {"Root": [_rule()]},
        {"root": [_rule(), _rule()]},
        {"root": [_rule().as_record()]},
    ],
)
def test_malformed_egress_policies_are_rejected(policy):
    with pytest.raises((TypeError, ValueError)):
        _registration(policy)


def test_registration_record_keys_stay_exact():
    record = _registration().as_record()
    del record["egress_policy"]
    with pytest.raises(ValueError):
        RunRegistration.from_record(record)


def test_http_event_kinds_have_their_canonical_values():
    assert RunEventKind("http_requested") is RunEventKind.HTTP_REQUESTED
    assert RunEventKind("http_responded") is RunEventKind.HTTP_RESPONDED
