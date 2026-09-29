from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from agent.duet_contracts import (
    ApprovalKind,
    ContractFieldRecord,
    CreatorProgressEnvelope,
    DuetIdentity,
    DuetDesignState,
    DuetMessageKind,
    DuetPolicy,
    DuetProvenance,
    FieldImpact,
)
from agent.duet_service import (
    DuetProtocolError,
    DuetService,
    StaleDuetApprovalError,
    WorkflowAdmissionError,
)
from agent.creator_episode import (
    CreatorRunLogStore,
    RunEpisodeStopReason,
    WorkflowCandidateDesign,
)
from agent.creator_runtime import CreatorRuntime, RunEvaluation
from agent.duet_store import DuetConflictError, DuetStore
from agent.episode_blueprints import (
    creation_blueprint_from_spec,
    workflow_blueprint_from_spec,
)
from agent.episode_contracts import (
    CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
    EpisodeCreationSpec,
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
)
from method_loop import Episode, EpisodeGoal, EpisodeRequest, EpisodeUpdate, Grain, leaves


def _identity(label: str = "test") -> DuetIdentity:
    return DuetIdentity(
        duet_id=OpaqueId.mint("duet", label),
        human_authority_id=OpaqueId.mint("human", label),
        policy_id=OpaqueId.mint("policy", label),
        conversation_id=OpaqueId.mint("conversation", label),
    )


def _creator_spec() -> EpisodeCreationSpec:
    requirement = EpisodeEvidenceRequirement(
        requirement_id="goal_evidence",
        evidence_kind_id="goal_observation",
        acceptance_source_id="run_episode_host",
        minimum_count=1,
    )
    component = EpisodeCreditComponentSpec(
        component_id="goal_credit",
        measurement_id="goal_completion",
        direction=ProgressDirection.INCREASE,
        normalization_baseline=0,
        normalization_target=1,
        weight=1,
        evidence_requirement_ids=(requirement.requirement_id,),
    )
    return EpisodeCreationSpec(
        goal="Design and test a complete nested Episode workflow for the Duet goal.",
        unit="one design, Run Episode, log inspection, and revision cycle",
        result="one host-validated workflow candidate with measured goal credit",
        progress=NumericProgressMeasure(
            metric_id=OpaqueId.mint("metric", "creator-method-credit"),
            description="Host-computed method credit from accepted Run Episode evidence",
            unit="normalized method credit",
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
        execution_capability_names=("web_search",),
        creator_contract=EpisodeCreatorContract(
            design_instructions="Iterate full workflow candidates using Run Episode logs.",
            design_scope="The workflow required to satisfy the Duet's frozen goal.",
            assignable_capability_names=("web_search",),
            may_assign_creator_capability=False,
            evidence_requirements=(requirement,),
            required_existing_evidence_ids=(),
            credit_assignment=EpisodeMethodCreditSpec((component,)),
            return_contract=EpisodeCreatorReturnContract(
                measurement_ids=("goal_completion",),
                credit_component_ids=("goal_credit",),
            ),
        ),
        safety_bounds=EpisodeSafetyBounds(
            max_iterations=8,
            max_child_episodes=8,
            max_depth=4,
        ),
    )


def _draft_fields(
    spec: EpisodeCreationSpec,
    provenance: DuetProvenance = DuetProvenance.HUMAN_INPUT,
) -> tuple[ContractFieldRecord, ...]:
    record = creation_blueprint_from_spec(spec)
    return tuple(
        ContractFieldRecord(
            field_path=path,
            value=record[path],
            provenance=provenance,
            approved=provenance is DuetProvenance.HUMAN_INPUT,
            impact=FieldImpact.HIGH if path == "creator_contract" else FieldImpact.MEDIUM,
        )
        for path in (
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
    )


@pytest.fixture
def duet(tmp_path):
    identity = _identity()
    policy = DuetPolicy(policy_id=identity.policy_id, minimum_method_credit=0.8)
    store = DuetStore(tmp_path / "duet.sqlite3")
    service = DuetService(store, allowed_episode_capabilities={"web_search"})
    yield identity, policy, store, service
    store.close()


def test_incomplete_contract_requests_fields_and_creates_nothing(duet):
    identity, policy, store, service = duet
    draft = service.open_duet(identity, policy)

    assert draft.ready is False
    requests = service.information_requests(identity.duet_id)
    assert {item.field_path for item in requests} == {
        "goal",
        "unit",
        "result",
        "progress",
        "stopping",
        "execution_capability_names",
        "creator_contract",
        "deliverable",
        "safety_bounds",
    }
    assert store.latest_artifact(
        duet_id=identity.duet_id.value,
        kind=ApprovalKind.CREATOR_CONTRACT.value,
    ) is None
    by_field = {item.field_path: item for item in requests}
    assert by_field["goal"].answer_schema["type"] == "string"
    assert "design_instructions" in by_field["creator_contract"].answer_schema["properties"]
    status = service.duet_status(identity.duet_id)
    assert status["configuration"] == {}
    assert status["contract_review"] is None
    assert all(
        item["disposition"] == "unresolved"
        for item in status["design_ledger"]
    )

    service.patch_contract(
        identity.duet_id,
        expected_revision=draft.revision,
        patches=(
            ContractFieldRecord(
                field_path="goal",
                value="Produce a verified result.",
                provenance=DuetProvenance.LLM_PROPOSAL,
            ),
        ),
        actor=DuetProvenance.LLM_PROPOSAL,
    )
    status = service.duet_status(identity.duet_id)
    goal = next(
        item for item in status["design_ledger"] if item["field_path"] == "goal"
    )
    assert goal["disposition"] == "llm_proposed"
    assert status["configuration"]["goal"] == "Produce a verified result."
    assert status["unconfirmed_proposal_ids"] == ["goal"]


def test_llm_cannot_replace_human_field_and_exact_approval_is_required(duet):
    identity, policy, _store, service = duet
    spec = _creator_spec()
    draft = service.open_duet(identity, policy, initial_fields=_draft_fields(spec))
    assert draft.ready is True

    with pytest.raises(DuetProtocolError, match="human-fixed"):
        service.patch_contract(
            identity.duet_id,
            expected_revision=draft.revision,
            patches=(
                ContractFieldRecord(
                    field_path="goal",
                    value="Replace the human goal.",
                    provenance=DuetProvenance.LLM_PROPOSAL,
                ),
            ),
            actor=DuetProvenance.LLM_PROPOSAL,
        )

    frozen = service.freeze_creator_contract(
        identity.duet_id, expected_revision=draft.revision
    )
    approval = service.record_human_approval(
        identity,
        kind=ApprovalKind.CREATOR_CONTRACT,
        artifact_id=frozen.artifact_id,
        content_hash=frozen.content_hash,
        revision=frozen.revision,
    )
    with pytest.raises(StaleDuetApprovalError):
        service.submit_episode_creator(
            contract_artifact_id=frozen.artifact_id,
            content_hash=replace(
                frozen.content_hash,
                value="sha256:" + "0" * 64,
            ),
            human_approval_id=approval.approval_id,
        )

    creator_id = service.submit_episode_creator(
        contract_artifact_id=frozen.artifact_id,
        content_hash=frozen.content_hash,
        human_approval_id=approval.approval_id,
    )
    assert creator_id.value.startswith("episode_")


def test_new_draft_revision_invalidates_creator_approval(duet):
    identity, policy, _store, service = duet
    spec = _creator_spec()
    draft = service.open_duet(identity, policy, initial_fields=_draft_fields(spec))
    frozen = service.freeze_creator_contract(
        identity.duet_id, expected_revision=draft.revision
    )
    approval = service.record_human_approval(
        identity,
        kind=ApprovalKind.CREATOR_CONTRACT,
        artifact_id=frozen.artifact_id,
        content_hash=frozen.content_hash,
        revision=frozen.revision,
    )
    service.patch_contract(
        identity.duet_id,
        expected_revision=draft.revision,
        patches=(
            ContractFieldRecord(
                field_path="goal",
                value=spec.goal + " Preserve an exact audit trail.",
                provenance=DuetProvenance.HUMAN_INPUT,
                approved=True,
            ),
        ),
        actor=DuetProvenance.HUMAN_INPUT,
    )

    with pytest.raises(StaleDuetApprovalError, match="later draft"):
        service.submit_episode_creator(
            contract_artifact_id=frozen.artifact_id,
            content_hash=frozen.content_hash,
            human_approval_id=approval.approval_id,
        )


def _admitted_creator(identity, policy, service):
    spec = _creator_spec()
    draft = service.open_duet(identity, policy, initial_fields=_draft_fields(spec))
    frozen = service.freeze_creator_contract(
        identity.duet_id, expected_revision=draft.revision
    )
    approval = service.record_human_approval(
        identity,
        kind=ApprovalKind.CREATOR_CONTRACT,
        artifact_id=frozen.artifact_id,
        content_hash=frozen.content_hash,
        revision=frozen.revision,
    )
    creator_id = service.submit_episode_creator(
        contract_artifact_id=frozen.artifact_id,
        content_hash=frozen.content_hash,
        human_approval_id=approval.approval_id,
    )
    return spec, creator_id


def _task_spec(*, capabilities=("web_search",), creator=False):
    return EpisodeCreationSpec(
        goal="Collect one accepted observation for the frozen workflow goal.",
        progress=NumericProgressMeasure(
            metric_id=OpaqueId.mint("metric", "task-progress"),
            description="Accepted task observations",
            unit="observations",
            direction=ProgressDirection.INCREASE,
            baseline=0,
            adapter_id=(
                CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER
                if creator
                else "durable_evidence_count_v1"
            ),
        ),
        stopping=ProgressStopCriteria(
            target=1,
            minimum_delta=1,
            stagnation_observations=2,
        ),
        can_create_episodes=creator,
        execution_capability_names=capabilities,
        creator_contract=_creator_spec().creator_contract if creator else None,
        safety_bounds=EpisodeSafetyBounds(max_iterations=3, max_depth=2),
    )


def test_invalid_workflow_persists_no_candidate(duet):
    identity, policy, store, service = duet
    _spec, creator_id = _admitted_creator(identity, policy, service)
    invalid = EpisodeWorkflowSpec(
        (
            EpisodeDesignSpec("first", None, _task_spec()),
            EpisodeDesignSpec("second", None, _task_spec()),
        )
    )

    with pytest.raises(WorkflowAdmissionError) as caught:
        service.submit_workflow_candidate(
            creator_episode_id=creator_id,
            revision=1,
            workflow=invalid,
            measured_outcomes=(),
        )
    assert {item.code for item in caught.value.deficits} == {"single_root_required"}
    assert store.latest_artifact(
        duet_id=identity.duet_id.value,
        kind=ApprovalKind.WORKFLOW.value,
        creator_episode_id=creator_id.value,
    ) is None

    recursive = EpisodeWorkflowSpec(
        (EpisodeDesignSpec("root", None, _task_spec(creator=True)),)
    )
    with pytest.raises(WorkflowAdmissionError) as recursive_error:
        service.submit_workflow_candidate(
            creator_episode_id=creator_id,
            revision=1,
            workflow=recursive,
            measured_outcomes=(),
        )
    assert "recursive_creator_not_authorized" in {
        item.code for item in recursive_error.value.deficits
    }


def test_recursive_creator_is_allowed_only_by_an_explicit_narrower_contract(tmp_path):
    identity = _identity("recursive")
    policy = DuetPolicy(
        policy_id=identity.policy_id,
        minimum_method_credit=0.8,
        maximum_creator_depth=2,
    )
    parent_spec = _creator_spec()
    parent_spec = replace(
        parent_spec,
        creator_contract=replace(
            parent_spec.creator_contract,
            may_assign_creator_capability=True,
        ),
    )
    with DuetStore(tmp_path / "recursive.sqlite3") as store:
        service = DuetService(
            store,
            allowed_episode_capabilities={"web_search"},
        )
        draft = service.open_duet(
            identity,
            policy,
            initial_fields=_draft_fields(parent_spec),
        )
        frozen = service.freeze_creator_contract(
            identity.duet_id,
            expected_revision=draft.revision,
        )
        approval = service.record_human_approval(
            identity,
            kind=ApprovalKind.CREATOR_CONTRACT,
            artifact_id=frozen.artifact_id,
            content_hash=frozen.content_hash,
            revision=frozen.revision,
        )
        creator_id = service.submit_episode_creator(
            contract_artifact_id=frozen.artifact_id,
            content_hash=frozen.content_hash,
            human_approval_id=approval.approval_id,
        )
        nested_creator_spec = _task_spec(creator=True)
        nested_creator_spec = replace(
            nested_creator_spec,
            creator_contract=replace(
                nested_creator_spec.creator_contract,
                may_assign_creator_capability=True,
            ),
        )
        recursive_workflow = EpisodeWorkflowSpec(
            (EpisodeDesignSpec("root", None, nested_creator_spec),)
        )
        design = service.freeze_workflow_design(
            creator_episode_id=creator_id,
            workflow_blueprint=workflow_blueprint_from_spec(recursive_workflow),
        )
        nested_creator_id = service.admit_nested_creator(
            parent_creator_episode_id=creator_id,
            workflow_design_artifact_id=design.artifact_id,
            node_local_id="root",
        )
        nested_row = store.get_creator(nested_creator_id.value)
        assert nested_row["parent_creator_episode_id"] == creator_id.value
        assert nested_row["design_artifact_id"] == design.artifact_id.value
        assert service.creator_contract(nested_creator_id).contract == (
            design.workflow.episodes[0].contract
        )
        service.publish_creator_progress(
            CreatorProgressEnvelope(
                creator_episode_id=nested_creator_id,
                sequence=1,
                state=DuetDesignState.REFINING,
                candidate_revision=1,
                deficit_count=0,
                validation_codes=(),
                accepted_evidence_ids=(),
                method_credit=0.2,
            )
        )
        root_status = service.duet_status(identity.duet_id)
        assert root_status["creator_episode_id"] == creator_id.value
        assert root_status["creator_progress"] is None
        assert root_status["state"] == DuetDesignState.CREATOR_ADMITTED.value
        with pytest.raises(WorkflowAdmissionError) as depth_error:
            service.freeze_workflow_design(
                creator_episode_id=nested_creator_id,
                workflow_blueprint=workflow_blueprint_from_spec(
                    EpisodeWorkflowSpec(
                        (
                            EpisodeDesignSpec(
                                "root",
                                None,
                                nested_creator_spec,
                            ),
                        )
                    )
                ),
            )
        assert "creator_depth_exceeded" in {
            item.code for item in depth_error.value.deficits
        }
        creator_with_predeclared_child = EpisodeWorkflowSpec(
            (
                EpisodeDesignSpec("root", None, _task_spec(creator=True)),
                EpisodeDesignSpec("child", "root", _task_spec()),
            )
        )
        with pytest.raises(WorkflowAdmissionError) as invalid_shape:
            service.freeze_workflow_design(
                creator_episode_id=creator_id,
                workflow_blueprint=workflow_blueprint_from_spec(
                    creator_with_predeclared_child
                ),
            )

    assert design.workflow.episodes[0].contract.can_create_episodes is True
    assert set(
        design.workflow.episodes[0]
        .contract.creator_contract.assignable_capability_names
    ) <= set(parent_spec.creator_contract.assignable_capability_names)
    assert "creator_node_must_be_leaf" in {
        item.code for item in invalid_shape.value.deficits
    }


def test_host_credit_workflow_approval_and_atomic_launch(duet):
    identity, policy, store, service = duet
    _spec, creator_id = _admitted_creator(identity, policy, service)
    evidence_id = service.register_evidence(
        duet_id=identity.duet_id,
        creator_episode_id=creator_id,
        evidence_kind_id="goal_observation",
        acceptance_source_id="run_episode_host",
        observation={"goal_reached": True},
    )
    workflow = EpisodeWorkflowSpec(
        (EpisodeDesignSpec("root", None, _task_spec()),)
    )
    design = service.freeze_workflow_design(
        creator_episode_id=creator_id,
        workflow_blueprint=workflow_blueprint_from_spec(workflow),
    )
    assert design.workflow_hash == design.workflow.workflow_hash
    assert design.revision == 1
    workflow = design.workflow
    outcomes = (
        EpisodeMeasuredOutcome(
            measurement_id="goal_completion",
            value=1,
            evidence=(
                EpisodeEvidenceMeasurement(
                    requirement_id="goal_evidence",
                    accepted_evidence_ids=(evidence_id,),
                ),
            ),
        ),
    )
    candidate = service.submit_workflow_candidate(
        creator_episode_id=creator_id,
        revision=1,
        workflow=workflow,
        measured_outcomes=outcomes,
    )
    assert candidate.projection.method_credit == 1
    approval = service.approve_workflow(identity, candidate)
    launch_id = service.launch_workflow(
        workflow_artifact_id=candidate.artifact_id,
        workflow_hash=candidate.workflow_hash,
        workflow_approval_id=approval.approval.approval_id,
        run_id="workflow-run",
    )
    launched = store.launched_episodes(launch_id.value)
    assert len(launched) == 1
    assert launched[0]["designed_by_episode_id"] == creator_id.value
    assert launched[0]["workflow_parent_episode_id"] is None


def test_human_guidance_is_applied_once_at_the_declared_creator_boundary(duet):
    identity, policy, _store, service = duet
    _spec, creator_id = _admitted_creator(identity, policy, service)
    guidance = service.record_creator_guidance(
        identity,
        creator_episode_id=creator_id,
        expected_unit_index=0,
        instruction="Keep the next workflow focused on the human-specified goal.",
    )
    decision = service.record_human_decision(
        identity,
        creator_episode_id=creator_id,
        kind=DuetMessageKind.OVERRIDE,
        expected_unit_index=0,
        code="human_guidance",
        guidance_artifact_ids=(guidance.guidance_id,),
    )

    assert service.submit_duet_decision(decision.message_id) is True
    assert service.submit_duet_decision(decision.message_id) is False
    claimed = service.claim_boundary_messages(creator_id, unit_index=0)
    assert claimed == (decision,)
    [resolved] = service.creator_boundary_records(claimed)
    assert resolved["trusted_human_guidance"][0]["instruction"] == (
        "Keep the next workflow focused on the human-specified goal."
    )
    assert service.claim_boundary_messages(creator_id, unit_index=1) == ()


def test_creator_progress_is_atomic_monotonic_and_visible_without_log_content(duet):
    identity, policy, _store, service = duet
    _spec, creator_id = _admitted_creator(identity, policy, service)
    evidence_id = OpaqueId.mint("evidence", "progress-visible")
    envelope = CreatorProgressEnvelope(
        creator_episode_id=creator_id,
        sequence=1,
        state=DuetDesignState.REFINING,
        candidate_revision=1,
        deficit_count=0,
        validation_codes=(),
        accepted_evidence_ids=(evidence_id,),
        method_credit=0.5,
    )

    first_id = service.publish_creator_progress(envelope)
    assert service.publish_creator_progress(envelope) == first_id
    status = service.duet_status(identity.duet_id)
    assert status["state"] == DuetDesignState.REFINING.value
    assert status["creator_episode_id"] == creator_id.value
    assert status["creator_progress"] == envelope.as_record()
    assert "log" not in status["creator_progress"]

    with pytest.raises(DuetConflictError, match="moved backwards"):
        service.publish_creator_progress(
            replace(envelope, sequence=0, state=DuetDesignState.DESIGNING)
        )


def test_low_credit_run_is_retained_for_learning_but_not_approvable(duet):
    identity, policy, store, service = duet
    _spec, creator_id = _admitted_creator(identity, policy, service)
    evidence_id = service.register_evidence(
        duet_id=identity.duet_id,
        creator_episode_id=creator_id,
        evidence_kind_id="goal_observation",
        acceptance_source_id="run_episode_host",
        observation={"goal_reached": False, "partial_credit": 0.5},
    )
    candidate = service.submit_workflow_candidate(
        creator_episode_id=creator_id,
        revision=1,
        workflow=EpisodeWorkflowSpec(
            (EpisodeDesignSpec("root", None, _task_spec()),)
        ),
        measured_outcomes=(
            EpisodeMeasuredOutcome(
                measurement_id="goal_completion",
                value=0.5,
                evidence=(
                    EpisodeEvidenceMeasurement(
                        requirement_id="goal_evidence",
                        accepted_evidence_ids=(evidence_id,),
                    ),
                ),
            ),
        ),
    )

    assert candidate.projection.method_credit == 0.5
    assert store.get_artifact(candidate.artifact_id.value) is not None
    with pytest.raises(WorkflowAdmissionError, match="credit_below_threshold"):
        service.approve_workflow(identity, candidate)


def test_later_measured_candidate_invalidates_an_older_workflow_approval(duet):
    identity, policy, _store, service = duet
    _spec, creator_id = _admitted_creator(identity, policy, service)
    evidence_id = service.register_evidence(
        duet_id=identity.duet_id,
        creator_episode_id=creator_id,
        evidence_kind_id="goal_observation",
        acceptance_source_id="run_episode_host",
        observation={"goal_reached": True},
    )
    workflow = EpisodeWorkflowSpec(
        (EpisodeDesignSpec("root", None, _task_spec()),)
    )
    outcomes = (
        EpisodeMeasuredOutcome(
            measurement_id="goal_completion",
            value=1,
            evidence=(
                EpisodeEvidenceMeasurement(
                    requirement_id="goal_evidence",
                    accepted_evidence_ids=(evidence_id,),
                ),
            ),
        ),
    )
    first = service.submit_workflow_candidate(
        creator_episode_id=creator_id,
        revision=1,
        workflow=workflow,
        measured_outcomes=outcomes,
    )
    approval = service.approve_workflow(identity, first)
    service.submit_workflow_candidate(
        creator_episode_id=creator_id,
        revision=2,
        workflow=workflow,
        measured_outcomes=outcomes,
    )

    with pytest.raises(StaleDuetApprovalError, match="later candidate"):
        service.launch_workflow(
            workflow_artifact_id=first.artifact_id,
            workflow_hash=first.workflow_hash,
            workflow_approval_id=approval.approval.approval_id,
            run_id="stale-workflow-run",
        )


def test_creator_runtime_seals_run_log_before_publishing_closed_progress(duet, tmp_path):
    identity, policy, _store, service = duet
    _spec, creator_id = _admitted_creator(identity, policy, service)
    evidence_id = service.register_evidence(
        duet_id=identity.duet_id,
        creator_episode_id=creator_id,
        evidence_kind_id="goal_observation",
        acceptance_source_id="run_episode_host",
        observation={"goal_reached": True},
    )
    workflow = EpisodeWorkflowSpec(
        (EpisodeDesignSpec("root", None, _task_spec()),)
    )
    design = service.freeze_workflow_design(
        creator_episode_id=creator_id,
        workflow_blueprint=workflow_blueprint_from_spec(workflow),
    )

    class _Designer:
        used = False

        def next_candidate(self, view, previous_runs, boundary_messages):
            assert previous_runs == ()
            assert boundary_messages == ()
            if self.used:
                return None
            self.used = True
            return WorkflowCandidateDesign(
                revision=design.revision,
                artifact_id=design.artifact_id,
                workflow=design.workflow,
            )

    @dataclass(frozen=True)
    class _Step:
        stop: bool
        requests_transition: bool = False

    @dataclass(frozen=True)
    class _State:
        observations: int
        stop: bool

    class _StopAfterOne:
        epoch = "one"

        def __init__(self):
            self.observations = 0

        def observe(self, unit_label, value, *, is_root):
            self.observations += 1
            return _Step(stop=True)

        def state(self):
            return _State(self.observations, self.observations >= 1)

        def transitioned(self, epoch):
            raise ValueError("no transition")

    task_grain = Grain(
        name="task_episode",
        unit="one deterministic task observation",
        result="one deterministic task result",
        controller=lambda _path: _StopAfterOne(),
    )

    def run_source_factory(candidate, run_goal):
        task_goal = EpisodeGoal.child(
            run_goal,
            objective={"kind": "exercise_frozen_candidate"},
            result_contract={"kind": "accepted_task_result"},
        )
        task = Episode(
            grain=task_grain,
            key="root",
            source=leaves(
                [{"accepted": True}],
                extract=lambda unit: unit,
                result=lambda unit, accepted: accepted,
            ),
            request=EpisodeRequest(goal=task_goal),
            to_parent=lambda record: EpisodeUpdate(
                record_id=record.episode_id,
                goal=record.goal,
                controller_input={"goal_reached": True},
            ),
        )

        class _Source:
            used = False

            def next(self, view):
                if self.used:
                    return None
                self.used = True
                return task

        return _Source()

    outcomes = (
        EpisodeMeasuredOutcome(
            measurement_id="goal_completion",
            value=1,
            evidence=(
                EpisodeEvidenceMeasurement(
                    requirement_id="goal_evidence",
                    accepted_evidence_ids=(evidence_id,),
                ),
            ),
        ),
    )
    log_store = CreatorRunLogStore(tmp_path / "creator_run_logs")

    def evaluate(candidate, record, log):
        assert candidate.artifact_id == design.artifact_id
        assert "task_episode" in log_store.read(log)
        return RunEvaluation(
            goal_reached=True,
            stop_reason=RunEpisodeStopReason.TARGET_REACHED,
            goal_result_ids=(OpaqueId.mint("result", record.episode_id),),
            accepted_evidence_ids=(evidence_id,),
            measured_outcomes=outcomes,
        )

    runtime = CreatorRuntime(
        service=service,
        creator_episode_id=creator_id,
        designer=_Designer(),
        log_store=log_store,
        run_source_factory=run_source_factory,
        run_evaluator=evaluate,
    )
    record = runtime.run(
        goal=EpisodeGoal.root(
            objective={"kind": "design_tested_workflow"},
            result_contract={"kind": "measured_workflow_candidate"},
        ),
        task_grain=task_grain,
        run_id="creator-runtime-test",
        max_depth=3,
    )

    result = record.unit_records[0].episode_update.controller_input
    assert result.log.location.endswith(".json")
    assert result.goal_reached is True
    status = service.duet_status(identity.duet_id)
    assert status["creator_progress"]["state"] == (
        DuetDesignState.AWAITING_WORKFLOW_APPROVAL.value
    )
    assert status["creator_progress"]["method_credit"] == 1
    assert "log" not in status["creator_progress"]
