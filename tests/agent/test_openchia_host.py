from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from agent.duet_contracts import ApprovalKind
from agent.episode_blueprints import workflow_blueprint_from_spec
from agent.episode_contracts import (
    CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
    EpisodeCreationSpec,
    EpisodeCreatorContext,
    EpisodeCreatorContract,
    EpisodeCreatorReturnContract,
    EpisodeCreditComponentSpec,
    EpisodeDesignSpec,
    EpisodeEvidenceRequirement,
    EpisodeMethodCreditSpec,
    EpisodeSafetyBounds,
    EpisodeWorkflowSpec,
    NumericProgressMeasure,
    OpaqueId,
    ProgressDirection,
    ProgressStopCriteria,
    Sha256Digest,
    TERMINAL_RESULT_PROGRESS_ADAPTER,
)
from agent.openchia_host import OpenChiaHost


def _host(tmp_path, *, session_id="host", tools=()):
    return OpenChiaHost(
        home=tmp_path,
        session_id=session_id,
        available_tool_names=set(tools),
        agent_kwargs_factory=lambda _role, _identity: {},
    )


def _task(goal: str = "Produce one result.") -> EpisodeCreationSpec:
    return EpisodeCreationSpec(
        goal=goal,
        progress=NumericProgressMeasure(
            metric_id=OpaqueId.mint("metric", goal),
            description="Accepted results",
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
        execution_capability_names=(),
        safety_bounds=EpisodeSafetyBounds(
            max_iterations=2,
            max_child_episodes=2,
            max_depth=8,
        ),
    )


def _blueprint(goal: str = "Produce one result.") -> dict:
    return workflow_blueprint_from_spec(
        EpisodeWorkflowSpec(
            (EpisodeDesignSpec("root", None, _task(goal)),)
        )
    )


def _terminal_blueprint(goal: str = "Produce one result.") -> dict:
    task = EpisodeCreationSpec(
        goal=goal,
        progress=NumericProgressMeasure(
            metric_id=OpaqueId.mint("metric", f"terminal:{goal}"),
            description="Persisted terminal result",
            unit="results",
            direction=ProgressDirection.INCREASE,
            baseline=0,
            adapter_id=TERMINAL_RESULT_PROGRESS_ADAPTER,
        ),
        stopping=ProgressStopCriteria(
            target=1,
            minimum_delta=1,
            stagnation_observations=2,
        ),
        execution_capability_names=(),
        safety_bounds=EpisodeSafetyBounds(
            max_iterations=2,
            max_child_episodes=2,
            max_depth=8,
        ),
    )
    return workflow_blueprint_from_spec(
        EpisodeWorkflowSpec((EpisodeDesignSpec("root", None, task),))
    )


def _creator_blueprint(host: OpenChiaHost) -> tuple[dict, str]:
    reference = host.service.register_creator_context_artifact(
        host.identity.duet_id,
        artifact_kind="task_specification",
        schema_version=1,
        purpose="creator_entrypoint",
        required=True,
        content={
            "goal": "Design and test one child Episode workflow.",
            "result": "A host-measured child workflow candidate.",
        },
    )
    context = EpisodeCreatorContext(
        entrypoint_artifact_id=reference.artifact_id,
        artifact_references=(reference,),
    )
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
    creator = EpisodeCreationSpec(
        goal="Design and test one child workflow.",
        unit="one design, run, observe, and revise cycle",
        result="one host-measured workflow candidate",
        progress=NumericProgressMeasure(
            metric_id=OpaqueId.mint("metric", "host-creator-credit"),
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
        creator_contract=EpisodeCreatorContract(
            design_context=context,
            design_scope="Design only the declared child task workflow.",
            assignable_capability_names=(),
            may_assign_creator_capability=False,
            evidence_requirements=(evidence,),
            required_existing_evidence_ids=(),
            credit_assignment=EpisodeMethodCreditSpec((credit,)),
            return_contract=EpisodeCreatorReturnContract(
                measurement_ids=("root_episode_progress",),
                credit_component_ids=(credit.component_id,),
            ),
        ),
        safety_bounds=EpisodeSafetyBounds(
            max_iterations=2,
            max_child_episodes=2,
            max_depth=8,
        ),
    )
    workflow = EpisodeWorkflowSpec(
        (EpisodeDesignSpec("designer", None, creator),)
    )
    return workflow_blueprint_from_spec(workflow), reference.artifact_id.value


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


def test_host_filters_control_plane_tools_from_episode_capability_ceiling(tmp_path):
    host = _host(
        tmp_path,
        tools={
            "web_search",
            "openchia_scope",
            "creator_context_artifact",
            "workflow_candidate",
            "episode_progress",
        },
    )
    try:
        assert host.available_tool_names == frozenset({"web_search"})
        assert host.service.allowed_episode_capabilities == frozenset(
            {"web_search"}
        )
    finally:
        host.close()


def test_resumed_host_rebinds_current_policy_without_changing_duet_authority(tmp_path):
    first = _host(
        tmp_path,
        session_id="resume-policy",
        tools={"web_search"},
    )
    original_duet_id = first.identity.duet_id
    original_human_id = first.identity.human_authority_id
    original_conversation_id = first.identity.conversation_id
    first.close()

    second = _host(
        tmp_path,
        session_id="resume-policy",
        tools={"web_search", "web_extract"},
    )
    try:
        assert second.identity.duet_id == original_duet_id
        assert second.identity.human_authority_id == original_human_id
        assert second.identity.conversation_id == original_conversation_id
        assert "web_extract" in second.policy.capability_allowlist
        assert any(
            event["event_type"] == "duet_policy_rebound"
            for event in second.store.events(second.identity.duet_id.value)
        )
    finally:
        second.close()


def test_execution_helpers_are_role_bound_and_identity_scoped(tmp_path):
    host = _host(tmp_path)
    creator_id = OpaqueId.mint("creator", "explicit-node")
    try:
        assert host._role_agent_kwargs("creator", creator_id.value) == {}
        assert host._creator_log_store(creator_id).root == (
            tmp_path / "openchia" / "run_logs" / creator_id.value
        ).resolve()
    finally:
        host.close()


def test_episode_editor_surface_is_always_the_persisted_workflow(tmp_path):
    host = _host(tmp_path)
    try:
        saved = host.record_duet_workflow_revision(
            _blueprint(),
            expected_workflow_hash=None,
        )
        snapshot = host.episode_workflow_configuration()

        assert snapshot["source_artifact_id"] == saved["artifact_id"]
        assert snapshot["configuration"]["episodes"][0]["local_id"] == "root"
        assert not hasattr(host, "episode_configuration")
        assert not hasattr(host, "episode_editor_document")
    finally:
        host.close()


def test_point_edit_appends_workflow_revision_without_creator_or_review(tmp_path):
    host = _host(tmp_path)
    try:
        first = host.record_duet_workflow_revision(
            _blueprint("first"),
            expected_workflow_hash=None,
        )
        second = host.record_episode_workflow_revision(
            _blueprint("second"),
            source_artifact_id=first["artifact_id"],
            expected_workflow_hash=first["content_hash"],
        )

        assert second["revision"] == 2
        assert host.store.creators(host.identity.duet_id.value) == ()
        assert host.store.latest_artifact(
            duet_id=host.identity.duet_id.value,
            kind="workflow_shadow_review",
            unowned_only=True,
        ) is None
    finally:
        host.close()


def test_approve_records_one_workflow_approval_and_launches_directly(
    tmp_path,
    monkeypatch,
):
    host = _host(tmp_path)
    completed = threading.Event()

    def finish(design, run_id, launch_id, approval_id):
        host.store.set_launch_status(launch_id.value, "completed")
        completed.set()

    monkeypatch.setattr(host, "_run_frozen_workflow_tracked", finish)
    try:
        saved = host.record_duet_workflow_revision(
            _blueprint(),
            expected_workflow_hash=None,
        )
        receipt = host.approve_current()
        assert completed.wait(2)

        approvals = [
            event
            for event in host.store.events(host.identity.duet_id.value)
            if event["event_type"].endswith("_approved")
        ]
        assert receipt.kind == ApprovalKind.WORKFLOW.value
        assert len(approvals) == 1
        assert approvals[0]["event_type"] == "workflow_approved"
        assert host.store.creators(host.identity.duet_id.value) == ()
        launch = host.store.latest_launch(host.identity.duet_id.value)
        assert launch["workflow_artifact_id"] == receipt.artifact_id.value
        assert launch["status"] == "completed"
        assert launch["workflow_artifact_id"] != saved["artifact_id"]
        assert host.status()["final_run_state"] == "completed"
    finally:
        host.close()


def test_approved_workflow_executes_directly_and_persists_its_run_log(
    tmp_path,
    monkeypatch,
):
    host = _host(tmp_path)
    monkeypatch.setattr(
        host,
        "_task_agent",
        lambda **_kwargs: SimpleNamespace(_episode_progress_reports=[]),
    )
    monkeypatch.setattr(
        "agent.conversation_loop.prepare_conversation_turn",
        lambda _agent, _prompt: SimpleNamespace(
            result={"failed": False, "final_response": "accepted result"},
            state=None,
        ),
    )
    try:
        host.record_duet_workflow_revision(
            _terminal_blueprint(),
            expected_workflow_hash=None,
        )
        receipt = host.approve_current()
        thread = host._final_threads[receipt.launch_id.value]
        thread.join(timeout=3)

        assert thread.is_alive() is False
        status = host.status()
        assert status["final_run_state"] == "completed"
        activity = status["workflow_execution"]["current_activity"]
        log_artifact_id = activity["details"]["run_log_artifact_id"]
        artifact = host.store.get_artifact(log_artifact_id)
        assert artifact["kind"] == "workflow_run_log"
        assert artifact["record"]["launch_id"] == receipt.launch_id.value
        assert len(host.run_log_locations()) == 1
        assert host.store.creators(host.identity.duet_id.value) == ()
    finally:
        host.close()


def test_explicit_creator_reads_context_builds_and_tests_child_workflow(
    tmp_path,
    monkeypatch,
):
    host = _host(tmp_path)
    creator_blueprint, context_artifact_id = _creator_blueprint(host)
    child_blueprint = _terminal_blueprint("Produce the tested child result.")

    class CreatorAgent:
        def __init__(self):
            self._creator_context_read_ids = set()
            self._creator_log_references = {}

        def chat(self, _request):
            self._creator_context_read_ids.add(context_artifact_id)
            self._creator_workflow_submit(child_blueprint)
            return "candidate submitted"

    monkeypatch.setattr(
        "agent.openchia_host.build_creator_agent",
        lambda **_kwargs: CreatorAgent(),
    )
    monkeypatch.setattr(
        host,
        "_task_agent",
        lambda **_kwargs: SimpleNamespace(_episode_progress_reports=[]),
    )
    monkeypatch.setattr(
        "agent.conversation_loop.prepare_conversation_turn",
        lambda _agent, _prompt: SimpleNamespace(
            result={"failed": False, "final_response": "tested child result"},
            state=None,
        ),
    )
    try:
        host.record_duet_workflow_revision(
            creator_blueprint,
            expected_workflow_hash=None,
        )
        receipt = host.approve_current()
        thread = host._final_threads[receipt.launch_id.value]
        thread.join(timeout=3)

        assert thread.is_alive() is False
        status = host.status()
        assert status["final_run_state"] == "completed"
        [creator] = status["creator_episodes"]
        assert creator["node_local_id"] == "designer"
        assert creator["progress"]["state"] == "sealed"
        assert creator["progress"]["method_credit"] == 1.0
        assert host.store.latest_artifact(
            duet_id=host.identity.duet_id.value,
            kind="workflow_design",
            creator_episode_id=creator["creator_episode_id"],
        ) is not None
        assert host.store.latest_artifact(
            duet_id=host.identity.duet_id.value,
            kind="workflow",
            creator_episode_id=creator["creator_episode_id"],
        ) is not None
    finally:
        host.close()


def test_approved_workflow_reports_typed_terminal_failure_with_its_log(
    tmp_path,
    monkeypatch,
):
    host = _host(tmp_path)
    monkeypatch.setattr(
        host,
        "_task_agent",
        lambda **_kwargs: SimpleNamespace(_episode_progress_reports=[]),
    )
    monkeypatch.setattr(
        "agent.conversation_loop.prepare_conversation_turn",
        lambda _agent, _prompt: SimpleNamespace(
            result={"failed": False, "final_response": "unchecked claim"},
            state=None,
        ),
    )
    try:
        host.record_duet_workflow_revision(
            _blueprint(),
            expected_workflow_hash=None,
        )
        receipt = host.approve_current()
        thread = host._final_threads[receipt.launch_id.value]
        thread.join(timeout=3)

        assert thread.is_alive() is False
        status = host.status()
        assert status["final_run_state"] == "failed"
        failure = status["workflow_execution"]["failure"]
        assert failure["error_code"] == "workflow_goal_not_reached"
        assert failure["owner"] == "episode_execution"
        assert failure["root_update"]["goal_reached"] is False
        assert failure["run_log"]["artifact_id"]
        assert host.store.latest_launch(host.identity.duet_id.value)[
            "status"
        ] == "failed"
    finally:
        host.close()


def test_workflow_failure_record_explains_owner_and_next_action(tmp_path):
    host = _host(tmp_path)
    try:
        saved = host.record_duet_workflow_revision(
            _blueprint(),
            expected_workflow_hash=None,
        )
        frozen = host.service.freeze_duet_workflow(
            duet_id=host.identity.duet_id,
            source_draft_artifact_id=OpaqueId(saved["artifact_id"]),
            source_draft_hash=Sha256Digest(saved["content_hash"]),
        )
        record = host._workflow_failure_record(
            design=frozen,
            launch_id=OpaqueId.mint("launch", "failure"),
            exc=TypeError("bad host binding"),
        )

        assert record["owner"] == "openchia_host"
        assert record["design_change_required"] is False
        assert "runtime" in record["suggested_action"].lower()
        assert record["message"] == "bad host binding"
    finally:
        host.close()


def test_status_exposes_workflow_and_not_fake_root_creator_fields(tmp_path):
    host = _host(tmp_path)
    try:
        host.record_duet_workflow_revision(
            _blueprint(),
            expected_workflow_hash=None,
        )
        status = host.status()

        assert status["episode_workflow"]["validation_state"] == "ready"
        assert status["creator_episodes"] == []
        assert set(status).issuperset(
            {
                "duet_id",
                "state",
                "episode_workflow",
                "creator_episodes",
            }
        )
    finally:
        host.close()
