from __future__ import annotations

import pytest

from agent.episode_contracts import OpaqueId, Sha256Digest
from agent.generic_creator_models import (
    ArtifactReference,
    CreatorFaultRecord,
    CreatorRepairRequest,
    EvidenceGate,
    EvidenceGateManifest,
    GateRequirement,
    GenericCreatorStatus,
    GenericCreatorType,
    PlatformPatchProposal,
)
from agent.generic_creator_runtime import (
    GenericCreatorEngine,
    GenericCreatorHostPolicy,
    IsolatedExecutorAttestation,
    evidence_gate_score,
)
from agent.generic_creator_store import GenericCreatorConflictError, GenericCreatorStore
from tests.agent.generic_creator_fixtures import RUNTIME_IDENTITY, creator_spec
from tests.agent.generic_creator_fixtures import work_definition


def _policy(*, descendants: int = 12, depth: int = 4, effectful: bool = False):
    return GenericCreatorHostPolicy(
        allowed_capabilities=frozenset(
            {"read_file", "write_file", "patch", "terminal", "execute_code", "process_manage"}
        ),
        recursive_creators_enabled=True,
        maximum_depth=depth,
        maximum_descendants=descendants,
        isolated_executor=(
            IsolatedExecutorAttestation("sandbox", True, True, True, True)
            if effectful else None
        ),
    )


def _engine(tmp_path, *, policy=None, identity_provider=None):
    store = GenericCreatorStore(tmp_path / "state.sqlite3")
    engine = GenericCreatorEngine(
        store=store,
        policy=policy or _policy(),
        source_root=tmp_path,
        runtime_identity_provider=identity_provider or (lambda: RUNTIME_IDENTITY),
    )
    return store, engine


def _manifest(manifest_id: str = "manifest_root") -> EvidenceGateManifest:
    return EvidenceGateManifest(
        manifest_id,
        1,
        Sha256Digest.of_bytes(b"fixed success criteria"),
        (
            EvidenceGate(
                "build", "Build passes", 2, "test_result", "host_test", 1,
                (), GateRequirement.REQUIRED,
            ),
            EvidenceGate(
                "integration", "Integration passes", 1, "test_result", "host_test", 1,
                ("build",), GateRequirement.REQUIRED,
            ),
            EvidenceGate(
                "optional", "Optional observation", 9, "test_result", "host_test", 1,
                (), GateRequirement.OPTIONAL,
            ),
        ),
    )


def _accept(store, manifest, gate_id, material):
    evidence_id = OpaqueId.mint("evidence", material)
    store.accept_gate_evidence(
        manifest=manifest,
        gate_id=gate_id,
        evidence_id=evidence_id,
        evidence_kind="test_result",
        acceptance_source="host_test",
        evidence_hash=Sha256Digest.of_bytes(material.encode()),
        host_accepted=True,
    )
    return evidence_id


def test_capability_non_escalation_and_effectful_fail_closed(tmp_path) -> None:
    store, engine = _engine(tmp_path)
    root = creator_spec(capabilities=("read_file",), maximum_child_episodes=4)
    engine.admit_root(root)
    with pytest.raises(GenericCreatorConflictError, match="subset"):
        engine.admit_child(
            creator_spec(
                "child", parent_instance_id="root", namespace="root/child",
                capabilities=("read_file", "write_file"), maximum_iterations=2,
                maximum_child_episodes=1, maximum_elapsed_time=10,
            )
        )
    store.close()

    effect_store, effect_engine = _engine(tmp_path / "effect")
    with pytest.raises(GenericCreatorConflictError, match="isolated executor"):
        effect_engine.admit_root(
            creator_spec(capabilities=("write_file",), maximum_child_episodes=1)
        )
    effect_store.close()


def test_child_cannot_replace_parent_success_criteria_references(tmp_path) -> None:
    store, engine = _engine(tmp_path)
    engine.admit_root(creator_spec(maximum_child_episodes=3))
    record = creator_spec(
        "child", parent_instance_id="root", namespace="root/child",
        maximum_iterations=2, maximum_child_episodes=0, maximum_elapsed_time=5,
    ).as_record()
    record["immutable_parent_success_criteria_refs"] = ["different_criteria"]
    from agent.generic_creator_models import GenericCreatorInstanceSpec

    with pytest.raises(GenericCreatorConflictError, match="exact immutable"):
        engine.admit_child(GenericCreatorInstanceSpec.from_record(record))
    store.close()


def test_attested_effectful_capability_can_be_admitted(tmp_path) -> None:
    store, engine = _engine(tmp_path, policy=_policy(effectful=True))
    engine.admit_root(creator_spec(capabilities=("write_file",), maximum_child_episodes=1))
    assert store.instance("root")["status"] is GenericCreatorStatus.ADMITTED
    store.close()


def test_depth_and_aggregate_descendant_limits(tmp_path) -> None:
    store, engine = _engine(tmp_path, policy=_policy(descendants=2, depth=2))
    engine.admit_root(creator_spec(maximum_child_episodes=2, maximum_depth=2))
    engine.admit_child(
        creator_spec(
            "child", parent_instance_id="root", namespace="root/child",
            maximum_iterations=5, maximum_child_episodes=1, maximum_depth=2,
            maximum_elapsed_time=20,
        )
    )
    engine.admit_child(
        creator_spec(
                "grandchild", parent_instance_id="child", namespace="root/child/grandchild",
                maximum_iterations=2, maximum_child_episodes=0, maximum_depth=2,
            maximum_elapsed_time=5,
        )
    )
    with pytest.raises(GenericCreatorConflictError, match="descendant limit"):
        engine.admit_child(
            creator_spec(
                "extra", parent_instance_id="root", namespace="root/extra",
                maximum_iterations=1, maximum_child_episodes=1, maximum_depth=2,
                maximum_elapsed_time=1,
            )
        )
    store.close()


def test_budget_reservation_cap_and_unused_return(tmp_path) -> None:
    store, engine = _engine(tmp_path)
    engine.admit_root(
        creator_spec(maximum_iterations=10, maximum_child_episodes=4, maximum_elapsed_time=50)
    )
    child = creator_spec(
        "child", parent_instance_id="root", namespace="root/child",
        maximum_iterations=4, maximum_child_episodes=1, maximum_elapsed_time=10,
    )
    engine.admit_child(child)
    assert store.budget("root")["iterations_remaining"] == 6
    engine.consume_iteration("child", elapsed=2)
    engine.cancel("child")
    assert store.budget("root")["iterations_remaining"] == 9
    assert store.budget("root")["elapsed_remaining"] == 48
    # The child's unused descendant slot returns; the launched child itself
    # still counts against the aggregate Episode cap.
    assert store.budget("root")["child_slots_remaining"] == 3
    assert store.instance("child")["status"] is GenericCreatorStatus.CANCELLED
    store.close()


def test_iteration_and_elapsed_caps_block_but_never_succeed(tmp_path) -> None:
    store, engine = _engine(tmp_path)
    engine.admit_root(
        creator_spec(maximum_iterations=1, maximum_child_episodes=1, maximum_elapsed_time=1)
    )
    engine.consume_iteration("root", elapsed=0.5)
    with pytest.raises(GenericCreatorConflictError, match="cap reached"):
        engine.consume_iteration("root", elapsed=0.6)
    assert store.instance("root")["status"] is GenericCreatorStatus.BLOCKED
    store.close()


def test_cancellation_propagates_and_persists(tmp_path) -> None:
    path = tmp_path / "state.sqlite3"
    store, engine = _engine(tmp_path)
    engine.admit_root(creator_spec(maximum_child_episodes=3))
    engine.admit_child(
        creator_spec(
            "child", parent_instance_id="root", namespace="root/child",
            maximum_iterations=2, maximum_child_episodes=1, maximum_elapsed_time=5,
        )
    )
    engine.cancel("root")
    store.close()
    with GenericCreatorStore(path) as reopened:
        assert reopened.instance("root")["status"] is GenericCreatorStatus.CANCELLED
        assert reopened.instance("child")["status"] is GenericCreatorStatus.CANCELLED


def test_deterministic_gate_score_dependency_and_no_child_claim_credit(tmp_path) -> None:
    store, engine = _engine(tmp_path)
    engine.admit_root(creator_spec(maximum_child_episodes=1))
    manifest = _manifest()
    store.put_manifest("root", manifest, approved=True)
    integration_evidence = _accept(store, manifest, "integration", "integration-first")
    assert engine.current_score(manifest.manifest_id) == 0
    _accept(store, manifest, "build", "build")
    assert engine.current_score(manifest.manifest_id) == 1
    assert evidence_gate_score(manifest, {"integration": (integration_evidence,)}) == 0
    store.close()


def test_complete_requires_host_evidence_and_preserves_normalized_score(tmp_path) -> None:
    store, engine = _engine(tmp_path)
    engine.admit_root(creator_spec(maximum_child_episodes=1))
    manifest = _manifest()
    store.put_manifest("root", manifest, approved=True)
    with pytest.raises(GenericCreatorConflictError, match="has not reached target"):
        engine.complete("root", manifest.manifest_id)
    _accept(store, manifest, "build", "build")
    _accept(store, manifest, "integration", "integration")
    assert engine.complete("root", manifest.manifest_id) == 1
    assert store.instance("root")["status"] is GenericCreatorStatus.SUCCEEDED
    store.close()


def test_worklist_retry_requires_new_evidence_and_independent_acceptance(tmp_path) -> None:
    store, engine = _engine(tmp_path)
    spec = creator_spec(
        creator_type=GenericCreatorType.WORKLIST_FACTORY_CREATOR,
        maximum_child_episodes=4,
    )
    engine.admit_root(spec)
    engine.start_work_item("root", "item_a")
    engine.fail_work_item("root", "item_a", evidence_sequence=1)
    engine.retry_work_item("root", "item_a", evidence_sequence=2)
    with pytest.raises(GenericCreatorConflictError, match="new evidence"):
        engine.fail_work_item("root", "item_a", evidence_sequence=2)
    manifest = EvidenceGateManifest(
        "manifest_root", 1, Sha256Digest.of_bytes(b"worklist criteria"),
        (
            EvidenceGate(
                "check_a", "Independent check", 1, "test_result", "host_test", 1,
                (), GateRequirement.REQUIRED,
            ),
        ),
    )
    store.put_manifest("root", manifest, approved=True)
    check_evidence = _accept(store, manifest, "check_a", "item-a-check")
    artifact_id, _, _ = store.put_artifact(
        producer_instance_id="root", producing_episode_id="builder", namespace="root",
        artifact_key="item_a", kind="item", record={"done": True}, expected_revision=None,
    )
    with pytest.raises(GenericCreatorConflictError, match="every independent check"):
        engine.accept_work_item(
            "root", "item_a", artifact_id=artifact_id,
            independently_accepted_checks={}, evidence_sequence=3,
        )
    engine.accept_work_item(
        "root", "item_a", artifact_id=artifact_id,
        independently_accepted_checks={"check_a": check_evidence}, evidence_sequence=3,
    )
    assert store.work_items("root")[0]["status"] == "accepted"
    store.close()


def test_typed_fault_reopens_only_owner_and_requires_integration_retest(tmp_path) -> None:
    store, engine = _engine(tmp_path)
    integration = creator_spec(
        creator_type=GenericCreatorType.INTEGRATION_HANDOFF_CREATOR,
        maximum_child_episodes=3,
    )
    engine.admit_root(integration)
    owner = creator_spec(
        "child", parent_instance_id="root", namespace="root/child",
        maximum_iterations=3, maximum_child_episodes=1, maximum_elapsed_time=10,
    )
    engine.admit_child(owner)
    artifact_id, digest, _ = store.put_artifact(
        producer_instance_id="child", producing_episode_id="builder", namespace="root/child",
        artifact_key="component", kind="component", record={"version": 1}, expected_revision=None,
    )
    reference = ArtifactReference(artifact_id, digest)
    fault_id = OpaqueId.mint("fault", "edge-a")
    manifest = _manifest()
    store.put_manifest("root", manifest, approved=True)
    accepted = _accept(store, manifest, "build", "prior")
    fault = CreatorFaultRecord(
        fault_id, "root", "child", "edge_a", (reference,), {"value": 0}, {"value": 1},
        (accepted,), reference, "high", True, ("component",), 2,
    )
    engine.report_fault(fault)
    repair = CreatorRepairRequest(
        OpaqueId.mint("repair", "edge-a"), fault_id, "child", ("component",),
        (accepted,), ("edge_a",), 1,
    )
    engine.request_repair(repair)
    assert store.instance("child")["status"] is GenericCreatorStatus.REPAIRING
    assert store.integration_edges("root")[0]["retest_required"] is True
    assert store.artifact(artifact_id)["record"] == {"version": 1}
    assert store.fault(fault_id).status.value == "repair_requested"
    with pytest.raises(GenericCreatorConflictError, match="before affected"):
        engine.verify_repair(repair.repair_id)
    engine.accept_integration_edge("root", "edge_a", evidence_ids=(accepted,))
    engine.verify_repair(repair.repair_id)
    assert store.fault(fault_id).status.value == "verified"
    assert store.repair(repair.repair_id).status.value == "verified"
    store.close()


def test_runtime_identity_change_invalidates_tree(tmp_path) -> None:
    identities = iter((RUNTIME_IDENTITY, Sha256Digest.of_bytes(b"changed")))
    store, engine = _engine(tmp_path, identity_provider=lambda: next(identities))
    engine.admit_root(creator_spec(maximum_child_episodes=1))
    with pytest.raises(GenericCreatorConflictError, match="identity changed"):
        engine.start("root")
    assert store.instance("root")["status"] is GenericCreatorStatus.INVALIDATED
    store.close()


def test_platform_patch_is_content_addressed_but_never_applied(tmp_path) -> None:
    store, engine = _engine(tmp_path)
    engine.admit_root(creator_spec(maximum_child_episodes=1))
    proposal = PlatformPatchProposal(
        "*** Begin Patch\n*** Update File: host.py\n@@\n-old\n+new\n*** End Patch",
        ("scripts/run_tests.sh tests/agent",),
        "No state migration",
        ("runtime_integrity",),
        Sha256Digest.of_bytes(b"new runtime"),
    )
    reference = engine.propose_platform_patch("root", "episode", proposal)
    stored = store.artifact(reference.artifact_id)
    assert stored["kind"] == "platform_patch_proposal"
    assert store.audit_events("root")[-1]["event_type"] == "platform_patch_proposed_not_applied"
    store.close()


def test_orchestrator_admits_exact_declared_children_and_resumes(tmp_path) -> None:
    store, engine = _engine(tmp_path)
    orchestrator = creator_spec(
        creator_type=GenericCreatorType.GENERIC_ORCHESTRATOR_CREATOR,
        maximum_iterations=20, maximum_child_episodes=4, maximum_elapsed_time=40,
    )
    engine.admit_root(orchestrator)
    assert engine.orchestrator_next_action("root")["instance_id"] == "planner"
    child_types = {
        "planner": GenericCreatorType.PLAN_CONTEXT_CREATOR,
        "portfolio": GenericCreatorType.RAREFACTION_PORTFOLIO_CREATOR,
        "integration": GenericCreatorType.INTEGRATION_HANDOFF_CREATOR,
        "qualification": GenericCreatorType.QUALIFICATION_RELEASE_CREATOR,
    }
    children = tuple(
        creator_spec(
            child_id, creator_type=child_type, parent_instance_id="root",
            namespace=f"root/{child_id}", maximum_iterations=2,
            maximum_child_episodes=0, maximum_elapsed_time=5,
        )
        for child_id, child_type in child_types.items()
    )
    engine.admit_orchestrator_children("root", children)
    # Exact durable identities make an interrupted admission call resumable.
    engine.admit_orchestrator_children("root", children)
    action = engine.orchestrator_next_action("root")
    assert action["decision"] == "run_instance"
    assert action["instance_id"] == "planner"
    store.close()


def test_qualification_emits_fault_for_unaccepted_integration_edge(tmp_path) -> None:
    store, engine = _engine(tmp_path)
    root = creator_spec(
        creator_type=GenericCreatorType.QUALIFICATION_RELEASE_CREATOR,
        maximum_child_episodes=2,
    )
    engine.admit_root(root)
    integration_definition = work_definition(GenericCreatorType.INTEGRATION_HANDOFF_CREATOR)
    integration_definition["gate_ownership"] = {"edge_a": "integration"}
    integration = creator_spec(
        "integration", creator_type=GenericCreatorType.INTEGRATION_HANDOFF_CREATOR,
        parent_instance_id="root", namespace="root/integration",
        maximum_iterations=3, maximum_child_episodes=0, maximum_elapsed_time=10,
        definition=integration_definition,
    )
    engine.admit_child(integration)
    test_id, test_hash, _ = store.put_artifact(
        producer_instance_id="root", producing_episode_id="qualification",
        namespace="root", artifact_key="qualification_test", kind="test",
        record={"command": "offline conformance"}, expected_revision=None,
    )
    manifest = _manifest()
    store.put_manifest("root", manifest, approved=True)
    _accept(store, manifest, "build", "build")
    _accept(store, manifest, "integration", "integration")
    with pytest.raises(GenericCreatorConflictError, match="release-blocking faults"):
        engine.qualify_release(
            "root", manifest_id=manifest.manifest_id, integrated_artifacts=(),
            integration_instance_ids=("integration",),
            reproducible_test_reference=ArtifactReference(test_id, test_hash),
            producing_episode_id="qualification",
        )
    assert store.audit_events("root")[-1]["event_type"] == "fault_reported"
    store.close()
