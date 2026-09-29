from agent.duet_contracts import ContractFieldRecord, DuetProvenance
from agent.episode_blueprints import creation_blueprint_from_spec
from agent.episode_contracts import (
    CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
    EpisodeCreationSpec,
    EpisodeCreatorContract,
    EpisodeCreatorReturnContract,
    EpisodeCreditComponentSpec,
    EpisodeEvidenceRequirement,
    EpisodeMethodCreditSpec,
    EpisodeSafetyBounds,
    NumericProgressMeasure,
    OpaqueId,
    ProgressDirection,
    ProgressStopCriteria,
    Sha256Digest,
)
from agent.openchia_host import OpenChiaHost, ROOT_PROGRESS_MEASUREMENT_ID


def _creator_spec() -> EpisodeCreationSpec:
    evidence = EpisodeEvidenceRequirement(
        requirement_id="root_run",
        evidence_kind_id="root_episode_terminal_update",
        acceptance_source_id="run_episode_host",
        minimum_count=1,
    )
    credit = EpisodeCreditComponentSpec(
        component_id="root_progress_credit",
        measurement_id=ROOT_PROGRESS_MEASUREMENT_ID,
        direction=ProgressDirection.INCREASE,
        normalization_baseline=0,
        normalization_target=1,
        weight=1,
        evidence_requirement_ids=(evidence.requirement_id,),
    )
    return EpisodeCreationSpec(
        goal="Design and test a nested Episode workflow for the human goal.",
        unit="one complete design, Run, inspect, and revision cycle",
        result="one host-measured workflow candidate",
        progress=NumericProgressMeasure(
            metric_id=OpaqueId.mint("metric", "creator-credit"),
            description="Host-computed workflow method credit",
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
        execution_capability_names=("web_search",),
        creator_contract=EpisodeCreatorContract(
            design_instructions="Iterate complete workflow candidates.",
            design_scope="The human-approved task.",
            assignable_capability_names=("web_search",),
            may_assign_creator_capability=True,
            evidence_requirements=(evidence,),
            required_existing_evidence_ids=(),
            credit_assignment=EpisodeMethodCreditSpec((credit,)),
            return_contract=EpisodeCreatorReturnContract(
                measurement_ids=(ROOT_PROGRESS_MEASUREMENT_ID,),
                credit_component_ids=(credit.component_id,),
            ),
        ),
        safety_bounds=EpisodeSafetyBounds(
            max_iterations=8,
            max_child_episodes=8,
            max_depth=8,
        ),
    )


def test_human_approval_is_visible_to_duet_and_creator_launch_is_idempotent(
    tmp_path,
):
    host = OpenChiaHost(
        home=tmp_path,
        session_id="20260929_120000_openchia",
        available_tool_names={"web_search"},
        agent_kwargs_factory=lambda _role, _identity: {},
    )
    try:
        blueprint = creation_blueprint_from_spec(_creator_spec())
        draft = host.service.latest_draft(host.identity.duet_id)
        draft = host.service.patch_contract(
            host.identity.duet_id,
            expected_revision=draft.revision,
            patches=tuple(
                ContractFieldRecord(
                    field_path=field,
                    value=blueprint[field],
                    provenance=DuetProvenance.HUMAN_INPUT,
                    approved=True,
                )
                for field in (
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
            ),
            actor=DuetProvenance.HUMAN_INPUT,
        )
        assert draft.ready is True
        approval = host.approve_current()
        status = host.status()
        assert status["creator_contract_approval"]["approval_id"] == (
            approval.approval_id.value
        )
        frozen = host.store.get_artifact(approval.artifact_id.value)["record"]
        creator_id = host.service.submit_episode_creator(
            contract_artifact_id=approval.artifact_id,
            content_hash=Sha256Digest(frozen["content_hash"]),
            human_approval_id=approval.approval_id,
        )
        assert frozen["contract"]["goal"] == _creator_spec().goal

        calls = []
        host._run_creator = lambda value, execution: calls.append(
            (value.value, execution.value)
        )
        first = host.launch_creator(creator_id)
        host._creator_threads[creator_id.value].join(timeout=2)
        second = host.launch_creator(creator_id)
        assert first.execution_id == second.execution_id
        assert len(calls) == 1
        assert second.state.value == "completed"
    finally:
        host.close()
