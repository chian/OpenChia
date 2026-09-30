from __future__ import annotations

from dataclasses import replace

import pytest

from agent.duet_contracts import (
    AdmittedCreatorContract,
    ApprovalKind,
    CreatorProgressEnvelope,
    DuetDesignState,
    DuetIdentity,
    DuetPolicy,
)
from agent.duet_service import (
    DuetService,
    StaleDuetApprovalError,
)
from agent.duet_store import DuetConflictError, DuetStore
from agent.episode_blueprints import workflow_blueprint_from_spec
from agent.episode_contracts import (
    CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
    EpisodeCreationSpec,
    EpisodeCreatorContext,
    EpisodeCreatorContextReference,
    EpisodeCreatorContract,
    EpisodeCreatorReturnContract,
    EpisodeCreditComponentSpec,
    EpisodeDesignSpec,
    EpisodeEvidenceMeasurement,
    EpisodeEvidenceRequirement,
    EpisodeMeasuredOutcome,
    EpisodeMethodCreditSpec,
    EpisodeSafetyBounds,
    EpisodeWorkflowSpec,
    NumericProgressMeasure,
    OpaqueId,
    ProgressDirection,
    ProgressStopCriteria,
    Sha256Digest,
)
from method_loop.identities import EpisodeRef


def _identity(label: str = "test", *, policy_id: OpaqueId | None = None) -> DuetIdentity:
    return DuetIdentity(
        duet_id=OpaqueId.mint("duet", label),
        human_authority_id=OpaqueId.mint("human", label),
        policy_id=policy_id or OpaqueId.mint("policy", label),
        conversation_id=OpaqueId.mint("conversation", label),
    )


@pytest.fixture
def duet(tmp_path):
    identity = _identity()
    policy = DuetPolicy(
        policy_id=identity.policy_id,
        maximum_creator_depth=2,
    )
    store = DuetStore(tmp_path / "duet.sqlite3")
    service = DuetService(store, allowed_episode_capabilities={"web_search"})
    service.open_duet(identity, policy)
    yield identity, policy, store, service
    store.close()


def _task_spec(
    goal: str = "Produce one accepted result.",
    *,
    capabilities: tuple[str, ...] = (),
    max_depth: int = 8,
) -> EpisodeCreationSpec:
    return EpisodeCreationSpec(
        goal=goal,
        progress=NumericProgressMeasure(
            metric_id=OpaqueId.mint("metric", goal),
            description="Accepted task results",
            unit="results",
            direction=ProgressDirection.INCREASE,
            baseline=0,
            adapter_id="durable_evidence_count_v1",
        ),
        stopping=ProgressStopCriteria(
            target=1,
            minimum_delta=1,
            stagnation_observations=2,
        ),
        execution_capability_names=capabilities,
        safety_bounds=EpisodeSafetyBounds(
            max_iterations=2,
            max_child_episodes=2,
            max_depth=max_depth,
        ),
    )


def _context(service: DuetService, identity: DuetIdentity) -> EpisodeCreatorContext:
    reference = service.register_creator_context_artifact(
        identity.duet_id,
        artifact_kind="task_specification",
        schema_version=1,
        purpose="creator_entrypoint",
        required=True,
        content={"goal": "Design a tested child workflow.", "constraints": []},
    )
    return EpisodeCreatorContext(
        entrypoint_artifact_id=reference.artifact_id,
        artifact_references=(reference,),
    )


def _creator_spec(context: EpisodeCreatorContext) -> EpisodeCreationSpec:
    evidence = EpisodeEvidenceRequirement(
        requirement_id="root_run",
        evidence_kind_id="root_episode_terminal_update",
        acceptance_source_id="run_episode_host",
        minimum_count=1,
    )
    credit = EpisodeCreditComponentSpec(
        component_id="root_progress_credit",
        measurement_id="root_episode_progress",
        direction=ProgressDirection.INCREASE,
        normalization_baseline=0,
        normalization_target=1,
        weight=1,
        evidence_requirement_ids=(evidence.requirement_id,),
    )
    return EpisodeCreationSpec(
        goal="Design and test a child workflow.",
        unit="one design, run, observe, and revise cycle",
        result="one host-measured workflow",
        progress=NumericProgressMeasure(
            metric_id=OpaqueId.mint("metric", "creator-credit"),
            description="Host-computed method credit",
            unit="normalized credit",
            direction=ProgressDirection.INCREASE,
            baseline=0,
            adapter_id=CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
        ),
        stopping=ProgressStopCriteria(
            target=0.8,
            minimum_delta=0.05,
            stagnation_observations=3,
        ),
        can_create_episodes=True,
        execution_capability_names=(),
        creator_contract=EpisodeCreatorContract(
            design_context=context,
            design_scope="The explicit Creator node's child workflow.",
            assignable_capability_names=("web_search",),
            may_assign_creator_capability=True,
            evidence_requirements=(evidence,),
            required_existing_evidence_ids=(),
            credit_assignment=EpisodeMethodCreditSpec((credit,)),
            return_contract=EpisodeCreatorReturnContract(
                measurement_ids=("root_episode_progress",),
                credit_component_ids=(credit.component_id,),
            ),
        ),
        safety_bounds=EpisodeSafetyBounds(
            max_iterations=4,
            max_child_episodes=4,
            max_depth=8,
        ),
    )


def _workflow(*nodes: EpisodeDesignSpec) -> tuple[EpisodeWorkflowSpec, dict]:
    spec = EpisodeWorkflowSpec(tuple(nodes))
    return spec, workflow_blueprint_from_spec(spec)


def _persist_freeze_approve(
    service: DuetService,
    identity: DuetIdentity,
    blueprint: dict,
):
    draft = service.record_duet_workflow_draft(
        duet_id=identity.duet_id,
        workflow_blueprint=blueprint,
        expected_workflow_hash=None,
        source_stage="duet",
    )
    frozen = service.freeze_duet_workflow(
        duet_id=identity.duet_id,
        source_draft_artifact_id=OpaqueId(draft["artifact_id"]),
        source_draft_hash=Sha256Digest(draft["content_hash"]),
    )
    approval = service.record_human_approval(
        identity,
        kind=ApprovalKind.WORKFLOW,
        artifact_id=frozen.artifact_id,
        content_hash=frozen.workflow_hash,
        revision=frozen.revision,
    )
    return draft, frozen, approval


def test_open_duet_has_no_implicit_creator_contract_or_creator_episode(duet):
    identity, _policy, store, service = duet

    status = service.duet_status(identity.duet_id)

    assert status["state"] == DuetDesignState.DESIGNING.value
    assert status["episode_workflow_draft"] is None
    assert status["creator_episodes"] == []
    assert store.creators(identity.duet_id.value) == ()


def test_empty_context_ledger_does_not_block_an_ordinary_workflow(duet):
    identity, _policy, store, service = duet
    _workflow_spec, blueprint = _workflow(
        EpisodeDesignSpec("root", None, _task_spec())
    )

    normalized, deficits = service.validate_duet_workflow(
        identity.duet_id,
        blueprint,
    )
    _draft, frozen, approval = _persist_freeze_approve(
        service,
        identity,
        blueprint,
    )
    launch_id = service.launch_duet_workflow(
        frozen=frozen,
        workflow_approval_id=approval.approval_id,
        run_id="empty-context-ledger",
    )
    status = service.duet_status(identity.duet_id)

    assert normalized is not None
    assert deficits == ()
    assert status["creator_context_artifacts"] == []
    assert status["creator_context_policy"] == {
        "required_for": "explicit_creator_episode_nodes_only",
        "ordinary_task_workflows_require_context_artifacts": False,
        "creation_tool": "creator_context_artifact",
        "read_tool": "creator_context_read",
        "accepted_artifact_kind": "creator_context",
        "prior_workflow_approval_or_contract_is_context": False,
    }
    launch = store.latest_launch(identity.duet_id.value)
    assert launch["launch_id"] == launch_id.value
    assert launch["status"] == "queued"


def test_explicit_creator_uses_a_context_receipt_not_a_prior_workflow(duet):
    identity, _policy, _store, service = duet
    _task_workflow, task_blueprint = _workflow(
        EpisodeDesignSpec("root", None, _task_spec())
    )
    _draft, frozen, _approval = _persist_freeze_approve(
        service,
        identity,
        task_blueprint,
    )
    wrong_context = EpisodeCreatorContext(
        entrypoint_artifact_id=frozen.artifact_id,
        artifact_references=(
            EpisodeCreatorContextReference(
                artifact_id=frozen.artifact_id,
                content_hash=frozen.workflow_hash,
                artifact_kind="task_specification",
                schema_version=1,
                purpose="creator_entrypoint",
                required=True,
            ),
        ),
    )
    _wrong_workflow, wrong_blueprint = _workflow(
        EpisodeDesignSpec("designer", None, _creator_spec(wrong_context))
    )

    _normalized, wrong_deficits = service.validate_duet_workflow(
        identity.duet_id,
        wrong_blueprint,
    )

    assert [item.code for item in wrong_deficits] == [
        "context_artifact_kind_mismatch"
    ]
    assert "creator_context_artifact" in wrong_deficits[0].detail

    valid_context = _context(service, identity)
    _valid_workflow, valid_blueprint = _workflow(
        EpisodeDesignSpec("designer", None, _creator_spec(valid_context))
    )
    normalized, valid_deficits = service.validate_duet_workflow(
        identity.duet_id,
        valid_blueprint,
    )

    assert normalized is not None
    assert valid_deficits == ()
    [artifact] = service.duet_status(identity.duet_id)[
        "creator_context_artifacts"
    ]
    assert artifact["artifact_id"] == valid_context.entrypoint_artifact_id.value


def test_duet_workflow_is_exact_hash_guarded_source_of_truth(duet):
    identity, _policy, _store, service = duet
    _spec, blueprint = _workflow(EpisodeDesignSpec("root", None, _task_spec()))

    draft = service.record_duet_workflow_draft(
        duet_id=identity.duet_id,
        workflow_blueprint=blueprint,
        expected_workflow_hash=None,
        source_stage="duet",
    )
    loaded = service.read_episode_workflow_draft(
        identity.duet_id,
        OpaqueId(draft["artifact_id"]),
    )

    assert loaded["workflow"] == blueprint
    assert loaded["content_hash"] == Sha256Digest.of_record(blueprint).value
    assert service.duet_status(identity.duet_id)["ready"] is True
    with pytest.raises(DuetConflictError):
        service.record_duet_workflow_draft(
            duet_id=identity.duet_id,
            workflow_blueprint=blueprint,
            expected_workflow_hash="sha256:" + "0" * 64,
            source_stage="duet",
        )


def test_approval_freezes_and_launches_workflow_without_fake_creator(duet):
    identity, _policy, store, service = duet
    workflow, blueprint = _workflow(
        EpisodeDesignSpec("root", None, _task_spec())
    )
    _draft, frozen, approval = _persist_freeze_approve(
        service, identity, blueprint
    )

    launch_id = service.launch_duet_workflow(
        frozen=frozen,
        workflow_approval_id=approval.approval_id,
        run_id="run-direct",
    )
    launch = store.latest_launch(identity.duet_id.value)
    [node] = store.launched_episodes(launch_id.value)

    assert launch["workflow_artifact_id"] == frozen.artifact_id.value
    assert launch["approval_id"] == approval.approval_id.value
    assert store.creators(identity.duet_id.value) == ()
    assert node["design_artifact_id"] == frozen.artifact_id.value
    assert node["runtime_key"] == f"{frozen.artifact_id.value}:root"
    assert node["episode_id"] == EpisodeRef(
        run_id="run-direct",
        path=(
            ("run_episode", f"approved-{frozen.artifact_id.value[-12:]}"),
            ("task_episode", node["runtime_key"]),
        ),
    ).episode_id
    assert tuple(node.local_id for node in frozen.workflow.episodes) == (
        "root",
    )
    assert frozen.workflow.episodes[0].contract.goal == (
        workflow.episodes[0].contract.goal
    )


def test_unchanged_approved_workflow_can_be_relaunched_as_new_attempt(duet):
    identity, _policy, store, service = duet
    _workflow_spec, blueprint = _workflow(
        EpisodeDesignSpec("root", None, _task_spec())
    )
    _draft, frozen, approval = _persist_freeze_approve(
        service, identity, blueprint
    )

    first = service.launch_duet_workflow(
        frozen=frozen,
        workflow_approval_id=approval.approval_id,
        run_id="run-1",
    )
    second = service.launch_duet_workflow(
        frozen=frozen,
        workflow_approval_id=approval.approval_id,
        run_id="run-2",
    )

    assert first != second
    assert store.latest_launch(identity.duet_id.value)["attempt"] == 2


def test_only_explicit_creator_node_gets_creator_contract(duet):
    identity, _policy, store, service = duet
    creator_spec = _creator_spec(_context(service, identity))
    _workflow_spec, blueprint = _workflow(
        EpisodeDesignSpec("designer", None, creator_spec)
    )
    _draft, frozen, approval = _persist_freeze_approve(
        service, identity, blueprint
    )

    creator_id = service.admit_workflow_creator(
        frozen_workflow=frozen,
        workflow_approval_id=approval.approval_id,
        node_local_id="designer",
    )
    admitted = service.creator_contract(creator_id)

    assert isinstance(admitted, AdmittedCreatorContract)
    assert admitted.node_local_id == "designer"
    assert admitted.source_design_artifact_id == frozen.artifact_id
    assert admitted.contract == frozen.workflow.episodes[0].contract
    assert store.creators(identity.duet_id.value)[0]["node_local_id"] == "designer"


def test_non_creator_node_cannot_be_admitted_as_creator(duet):
    identity, _policy, _store, service = duet
    _workflow_spec, blueprint = _workflow(
        EpisodeDesignSpec("root", None, _task_spec())
    )
    _draft, frozen, approval = _persist_freeze_approve(
        service, identity, blueprint
    )

    with pytest.raises(Exception, match="not a Creator Episode"):
        service.admit_workflow_creator(
            frozen_workflow=frozen,
            workflow_approval_id=approval.approval_id,
            node_local_id="root",
        )


def test_creator_depth_uses_authority_tree_not_work_graph_depth(duet):
    identity, _policy, _store, service = duet
    creator = _creator_spec(_context(service, identity))
    workflow, blueprint = _workflow(
        EpisodeDesignSpec("root", None, _task_spec(max_depth=8)),
        EpisodeDesignSpec("middle", "root", _task_spec(max_depth=8)),
        EpisodeDesignSpec("designer", "middle", creator),
    )

    normalized, deficits = service.validate_duet_workflow(
        identity.duet_id, blueprint
    )

    assert tuple(node.local_id for node in normalized.episodes) == tuple(
        node.local_id for node in workflow.episodes
    )
    assert tuple(
        node.workflow_parent_local_id for node in normalized.episodes
    ) == tuple(node.workflow_parent_local_id for node in workflow.episodes)
    assert "creator_depth_exceeded" not in {item.code for item in deficits}


def test_capability_escalation_is_rejected_deterministically(duet):
    identity, _policy, _store, service = duet
    _workflow_spec, blueprint = _workflow(
        EpisodeDesignSpec(
            "root",
            None,
            _task_spec(capabilities=("terminal",)),
        )
    )

    _normalized, deficits = service.validate_duet_workflow(
        identity.duet_id, blueprint
    )

    assert "capability_escalation" in {item.code for item in deficits}


def test_new_workflow_revision_invalidates_prior_approval(duet):
    identity, _policy, _store, service = duet
    _workflow_spec, blueprint = _workflow(
        EpisodeDesignSpec("root", None, _task_spec("first"))
    )
    draft, frozen, approval = _persist_freeze_approve(
        service, identity, blueprint
    )
    _replacement, replacement_blueprint = _workflow(
        EpisodeDesignSpec("root", None, _task_spec("second"))
    )
    service.record_duet_workflow_draft(
        duet_id=identity.duet_id,
        workflow_blueprint=replacement_blueprint,
        expected_workflow_hash=draft["content_hash"],
        source_stage="duet",
    )

    with pytest.raises(StaleDuetApprovalError):
        service.launch_duet_workflow(
            frozen=frozen,
            workflow_approval_id=approval.approval_id,
            run_id="stale-run",
        )


def test_creator_progress_does_not_overwrite_duet_workflow_state(duet):
    identity, _policy, store, service = duet
    creator_spec = _creator_spec(_context(service, identity))
    _workflow_spec, blueprint = _workflow(
        EpisodeDesignSpec("designer", None, creator_spec)
    )
    _draft, frozen, approval = _persist_freeze_approve(
        service, identity, blueprint
    )
    creator_id = service.admit_workflow_creator(
        frozen_workflow=frozen,
        workflow_approval_id=approval.approval_id,
        node_local_id="designer",
    )
    state_before = store.get_duet(identity.duet_id.value)["state"]

    service.publish_creator_progress(
        CreatorProgressEnvelope(
            creator_episode_id=creator_id,
            sequence=1,
            state=DuetDesignState.REFINING,
            candidate_revision=1,
            deficit_count=0,
            validation_codes=(),
            accepted_evidence_ids=(),
            method_credit=0.5,
        )
    )

    assert store.get_duet(identity.duet_id.value)["state"] == state_before
    assert service.duet_status(identity.duet_id)["creator_episodes"][0][
        "state"
    ] == DuetDesignState.REFINING.value


def test_creator_candidate_does_not_overwrite_duet_workflow_state(duet):
    identity, _policy, store, service = duet
    context = _context(service, identity)
    creator_spec = _creator_spec(context)
    _workflow_spec, blueprint = _workflow(
        EpisodeDesignSpec("designer", None, creator_spec)
    )
    _draft, frozen, approval = _persist_freeze_approve(
        service, identity, blueprint
    )
    service.launch_duet_workflow(
        frozen=frozen,
        workflow_approval_id=approval.approval_id,
        run_id="creator-parent-run",
    )
    creator_id = service.admit_workflow_creator(
        frozen_workflow=frozen,
        workflow_approval_id=approval.approval_id,
        node_local_id="designer",
    )
    _child_workflow, child_blueprint = _workflow(
        EpisodeDesignSpec("child", None, _task_spec())
    )
    design = service.freeze_workflow_design(
        creator_episode_id=creator_id,
        workflow_blueprint=child_blueprint,
        consumed_context_artifact_ids=tuple(
            item.artifact_id.value for item in context.artifact_references
        ),
    )
    evidence_id = service.register_evidence(
        duet_id=identity.duet_id,
        creator_episode_id=creator_id,
        evidence_kind_id="root_episode_terminal_update",
        acceptance_source_id="run_episode_host",
        observation={"goal_reached": True},
        source_artifact_id=design.artifact_id,
    )

    service.submit_workflow_candidate(
        creator_episode_id=creator_id,
        revision=1,
        workflow=design.workflow,
        measured_outcomes=(
            EpisodeMeasuredOutcome(
                measurement_id="root_episode_progress",
                value=1.0,
                evidence=(
                    EpisodeEvidenceMeasurement(
                        requirement_id="root_run",
                        accepted_evidence_ids=(evidence_id,),
                    ),
                ),
            ),
        ),
    )

    assert store.get_duet(identity.duet_id.value)["state"] == (
        DuetDesignState.LAUNCHED.value
    )


def test_host_policy_rebind_preserves_duet_authority(tmp_path):
    store = DuetStore(tmp_path / "duet.sqlite3")
    try:
        old_identity = _identity("resume")
        old_policy = DuetPolicy(policy_id=old_identity.policy_id)
        service = DuetService(store, allowed_episode_capabilities={"web_search"})
        service.open_duet(old_identity, old_policy)

        new_policy_id = OpaqueId.mint("policy", "resume-new")
        new_identity = replace(old_identity, policy_id=new_policy_id)
        new_policy = DuetPolicy(
            policy_id=new_policy_id,
            maximum_creator_depth=3,
        )
        service.open_duet(new_identity, new_policy)

        row = store.get_duet(old_identity.duet_id.value)
        assert row["identity"] == new_identity.as_record()
        assert row["policy"] == new_policy.as_record()
        assert any(
            event["event_type"] == "duet_policy_rebound"
            for event in store.events(old_identity.duet_id.value)
        )
    finally:
        store.close()
