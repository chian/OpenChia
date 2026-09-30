import pytest

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


def test_shadow_review_parser_accepts_json_and_rejects_bad_verdict():
    parsed = OpenChiaHost._parse_contract_review(
        """```json
        {"verdict":"concern","summary":"Check evidence.","findings":[{"code":"weak_evidence","severity":"high","fields":["progress"],"explanation":"Evidence is self-reported.","question":"What host accepts it?"}]}
        ```"""
    )
    assert parsed["verdict"] == "concern"
    assert parsed["findings"][0]["fields"] == ["progress"]
    with pytest.raises(ValueError, match="verdict"):
        OpenChiaHost._parse_contract_review(
            '{"verdict":"maybe","summary":"x","findings":[]}'
        )


def test_host_records_exact_human_answer_for_duet_submission(tmp_path):
    host = OpenChiaHost(
        home=tmp_path,
        session_id="20260930_120000_answer",
        available_tool_names={"web_search"},
        agent_kwargs_factory=lambda _role, _identity: {},
    )
    try:
        answer = host.record_human_answer(
            "goal",
            "Design a measured nested Episode workflow.",
        )
        status = host.status()
        assert status["pending_human_answer"]["answer_artifact_id"] == (
            answer.answer_id.value
        )
        assert "goal" not in host.service.latest_draft(
            host.identity.duet_id
        ).materialized()

        draft = host.service.submit_duet_answer(answer.answer_id)
        goal = next(item for item in draft.fields if item.field_path == "goal")
        assert goal.value == "Design a measured nested Episode workflow."
        assert goal.human_fixed is True
    finally:
        host.close()


def test_shadow_review_is_cached_by_exact_contract_hash(tmp_path, monkeypatch):
    host = OpenChiaHost(
        home=tmp_path,
        session_id="20260929_120000_review",
        available_tool_names={"web_search"},
        agent_kwargs_factory=lambda _role, _identity: {},
    )
    calls = []

    class Critic:
        def chat(self, request):
            calls.append(request)
            return '{"verdict":"pass","summary":"Coherent.","findings":[]}'

    monkeypatch.setattr(
        "agent.openchia_host.build_duet_contract_critic_agent",
        lambda **_kwargs: Critic(),
    )
    try:
        blueprint = creation_blueprint_from_spec(_creator_spec())
        draft = host.service.latest_draft(host.identity.duet_id)
        host.service.patch_contract(
            host.identity.duet_id,
            expected_revision=draft.revision,
            patches=tuple(
                ContractFieldRecord(
                    field_path=field,
                    value=blueprint[field],
                    provenance=DuetProvenance.HUMAN_INPUT,
                    approved=True,
                )
                for field in blueprint
            ),
            actor=DuetProvenance.HUMAN_INPUT,
        )
        first = host.review_contract()
        second = host.review_contract()
        assert first["verdict"] == "pass"
        assert first["cached"] is False
        assert second["cached"] is True
        assert len(calls) == 1
        assert host.status()["contract_review"]["verdict"] == "pass"
    finally:
        host.close()


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
