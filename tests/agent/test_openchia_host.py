import threading
from types import SimpleNamespace

import pytest

from agent.duet_contracts import (
    ContractFieldRecord,
    DuetIdentity,
    DuetPolicy,
    DuetProvenance,
    content_id,
)
from agent.duet_service import DuetProtocolError, DuetService
from agent.duet_store import DuetStore
from agent.episode_blueprints import (
    creation_blueprint_from_spec,
    workflow_blueprint_from_spec,
)
from agent.episode_contracts import (
    CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
    EpisodeCreationSpec,
    EpisodeCreatorContract,
    EpisodeCreatorContext,
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
)
from agent.openchia_host import (
    OpenChiaHost,
    ROOT_PROGRESS_MEASUREMENT_ID,
    WORKFLOW_REVIEW_LENSES,
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
            design_context=context,
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


def _creator_context(host: OpenChiaHost) -> EpisodeCreatorContext:
    reference = host.service.register_creator_context_artifact(
        host.identity.duet_id,
        artifact_kind="task_specification",
        schema_version=1,
        purpose="creator_entrypoint",
        required=True,
        content={
            "goal": "Design and test a nested Episode workflow for the human goal.",
            "required_behavior": ["iterate", "run", "inspect", "revise"],
        },
    )
    return EpisodeCreatorContext(
        entrypoint_artifact_id=reference.artifact_id,
        artifact_references=(reference,),
    )


def _workflow_task(goal: str) -> EpisodeCreationSpec:
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
        execution_capability_names=(),
        safety_bounds=EpisodeSafetyBounds(max_iterations=2, max_depth=2),
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


def test_host_never_treats_control_plane_tools_as_child_capabilities(tmp_path):
    host = OpenChiaHost(
        home=tmp_path,
        session_id="20260930_120000_scope",
        available_tool_names={
            "web_search",
            "openchia_scope",
            "creator_context_artifact",
            "workflow_candidate",
            "episode_progress",
        },
        agent_kwargs_factory=lambda _role, _identity: {},
    )
    try:
        assert host.available_tool_names == frozenset({"web_search"})
        assert host.service.allowed_episode_capabilities == frozenset(
            {"web_search"}
        )
    finally:
        host.close()


def test_host_resumes_the_stored_immutable_policy_after_tools_are_added(tmp_path):
    root = tmp_path / "openchia"
    root.mkdir()
    store = DuetStore(root / "duet.sqlite3")
    session_id = "20260930_120000_policy_resume"
    policy_id = OpaqueId.mint("policy", "openchia-interactive-v1")
    identity = DuetIdentity(
        duet_id=OpaqueId.mint("duet", session_id),
        human_authority_id=OpaqueId.mint("human", f"local:{root.resolve()}"),
        policy_id=policy_id,
        conversation_id=OpaqueId.mint("conversation", session_id),
    )
    stored_policy = DuetPolicy(
        policy_id=policy_id,
        capability_allowlist=("duet_status",),
        maximum_creator_depth=4,
    )
    service = DuetService(store, allowed_episode_capabilities=("web_search",))
    original = service.open_duet(identity, stored_policy)
    store.close()

    host = OpenChiaHost(
        home=tmp_path,
        session_id=session_id,
        available_tool_names={"web_search"},
        agent_kwargs_factory=lambda _role, _identity: {},
    )
    try:
        assert host.identity == identity
        assert host.policy == stored_policy
        assert host.service.latest_draft(identity.duet_id).content_hash == (
            original.content_hash
        )
    finally:
        host.close()


def test_host_atomically_migrates_retired_duet_protocol_tools(tmp_path):
    root = tmp_path / "openchia"
    root.mkdir()
    store = DuetStore(root / "duet.sqlite3")
    session_id = "20260930_120000_retired_policy"
    legacy_policy_fields = {
        "capability_allowlist": sorted(
            {
                "openchia_scope",
                "duet_contract_patch",
                "duet_contract_review",
                "duet_status",
                "episode_workflow_read",
                "duet_answer",
                "duet_decision",
                "episode_creator",
                "creator_context_artifact",
                "creator_context_read",
                "web_search",
            }
        ),
        "minimum_method_credit": 0.0,
        "creator_proposal_bound": 8,
        "maximum_creator_depth": 4,
    }
    legacy_policy_id = content_id("policy", legacy_policy_fields)
    identity = DuetIdentity(
        duet_id=OpaqueId.mint("duet", session_id),
        human_authority_id=OpaqueId.mint("human", f"local:{root.resolve()}"),
        policy_id=legacy_policy_id,
        conversation_id=OpaqueId.mint("conversation", session_id),
    )
    store.create_duet(
        duet_id=identity.duet_id.value,
        identity=identity.as_record(),
        policy={"policy_id": legacy_policy_id.value, **legacy_policy_fields},
        state="collecting_contract",
    )
    store.close()

    host = OpenChiaHost(
        home=tmp_path,
        session_id=session_id,
        available_tool_names={"web_search"},
        agent_kwargs_factory=lambda _role, _identity: {},
    )
    try:
        assert "duet_contract_review" not in host.policy.capability_allowlist
        assert "episode_creator" not in host.policy.capability_allowlist
        assert "episode_workflow_update" in host.policy.capability_allowlist
        persisted = host.store.get_duet(host.identity.duet_id.value)
        assert persisted["identity"]["policy_id"] == host.policy.policy_id.value
        assert persisted["policy"] == host.policy.as_record()
        migration = host.store.events(host.identity.duet_id.value)[0]
        assert migration["event_type"] == "duet_policy_migration"
        assert migration["record"]["removed_capability_names"] == [
            "duet_contract_review",
            "episode_creator",
        ]
        assert migration["record"]["added_capability_names"] == [
            "episode_workflow_update"
        ]
    finally:
        host.close()


def test_new_duet_policy_identity_is_derived_from_immutable_content(tmp_path):
    without_search = OpenChiaHost(
        home=tmp_path / "without-search",
        session_id="20260930_120000_policy_content",
        available_tool_names=set(),
        agent_kwargs_factory=lambda _role, _identity: {},
    )
    with_search = OpenChiaHost(
        home=tmp_path / "with-search",
        session_id="20260930_120000_policy_content",
        available_tool_names={"web_search"},
        agent_kwargs_factory=lambda _role, _identity: {},
    )
    try:
        assert without_search.policy.policy_id != with_search.policy.policy_id
        assert without_search.identity.policy_id == without_search.policy.policy_id
        assert with_search.identity.policy_id == with_search.policy.policy_id
    finally:
        without_search.close()
        with_search.close()


def test_auxiliary_critic_is_owned_closed_and_inherits_pending_stop():
    events = []
    parent = SimpleNamespace(
        _active_children=[],
        _active_children_lock=threading.RLock(),
        _hard_interrupt_requested=threading.Event(),
        _interrupt_requested=True,
    )
    parent._hard_interrupt_requested.set()

    class Critic:
        def hard_interrupt(self, *, tool_reason=None):
            events.append(("interrupt", tool_reason))

        def chat(self, request):
            assert self in parent._active_children
            events.append(("chat", request))
            return "done"

        def close(self):
            events.append(("close", None))

    critic = Critic()
    result = OpenChiaHost._chat_as_interruptible_child(
        parent,
        critic,
        "review request",
    )

    assert result == "done"
    assert events == [
        ("interrupt", "parent OpenChia turn stopped"),
        ("chat", "review request"),
        ("close", None),
    ]
    assert parent._active_children == []


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


def test_critics_run_only_for_explicit_review_and_cache_exact_design(
    tmp_path, monkeypatch
):
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
        "agent.openchia_host.build_creator_workflow_critic_agent",
        lambda **_kwargs: Critic(),
    )
    try:
        blueprint = creation_blueprint_from_spec(
            _creator_spec(_creator_context(host))
        )
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
        workflow = workflow_blueprint_from_spec(
            EpisodeWorkflowSpec(
                (EpisodeDesignSpec("root", None, _workflow_task("Build")),)
            )
        )
        host.record_duet_workflow_revision(
            workflow,
            expected_workflow_hash=None,
        )
        assert calls == []

        first = host.review_episode_design()
        second = host.review_episode_design()
        assert first["cached"] is False
        assert second["cached"] is True
        assert len(calls) == 5
        assert set(first["lenses"]) == set(WORKFLOW_REVIEW_LENSES)
        assert len(host.status()["workflow_review"]["lenses"]) == 5
    finally:
        host.close()


def test_human_approval_builds_exact_duet_workflow_without_designer_agent(
    tmp_path, monkeypatch
):
    host = OpenChiaHost(
        home=tmp_path,
        session_id="20260929_120000_openchia",
        available_tool_names={"web_search"},
        agent_kwargs_factory=lambda _role, _identity: {},
    )
    try:
        creator_spec = _creator_spec(_creator_context(host))
        blueprint = creation_blueprint_from_spec(creator_spec)
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
        workflow = EpisodeWorkflowSpec(
            (
                EpisodeDesignSpec("root_episode", None, _workflow_task("Coordinate")),
                EpisodeDesignSpec(
                    "worker_episode",
                    "root_episode",
                    _workflow_task("Build one item"),
                ),
            )
        )
        workflow_blueprint = workflow_blueprint_from_spec(workflow)
        saved = host.record_duet_workflow_revision(
            workflow_blueprint,
            expected_workflow_hash=None,
        )
        assert saved["ready"] is True

        executions = []
        host._run_frozen_workflow = (
            lambda design, run_id, artifact_id: executions.append(
                (design, run_id, artifact_id)
            )
        )
        approval = host.approve_current()
        host._final_threads[approval.launch_id.value].join(timeout=2)
        status = host.status()
        assert approval.kind == "workflow"
        assert status["workflow_approval"]["approval_id"] == approval.approval_id.value
        assert status["launch"]["launch_id"] == approval.launch_id.value
        assert len(executions) == 1
        assert workflow_blueprint_from_spec(executions[0][0].workflow) == (
            workflow_blueprint
        )
        assert not hasattr(host, "_creator_threads")

        observed_run = {}

        class BoundEpisode:
            def __init__(self, **kwargs):
                observed_run.update(kwargs)

            def run(self, context):
                observed_run["context"] = context

        monkeypatch.setattr("agent.openchia_host.Episode", BoundEpisode)
        host._workflow_runtime = lambda **_kwargs: SimpleNamespace(
            source_for_candidate=lambda design, goal: (design, goal)
        )
        host._run_frozen_workflow = OpenChiaHost._run_frozen_workflow.__get__(
            host,
            OpenChiaHost,
        )
        design = executions[0][0]
        host._run_frozen_workflow(
            design,
            "run_" + "c" * 64,
            design.artifact_id,
        )
        assert observed_run["key"] == (
            f"approved-{design.artifact_id.value[-12:]}"
        )

        def broken_runtime(*_args):
            raise NameError("missing runtime binding")

        host._run_frozen_workflow = broken_runtime
        host._run_frozen_workflow_tracked(
            design,
            "run_" + "d" * 64,
            approval.launch_id,
        )
        failed = host.status()
        assert failed["final_run_state"] == "failed"
        assert failed["final_error_code"] == "NameError"
        assert failed["workflow_execution"]["failure"]["message"] == (
            "missing runtime binding"
        )
        assert failed["workflow_execution"]["failure"]["owner"] == (
            "openchia_host"
        )
    finally:
        host.close()


def test_point_edit_supersedes_review_and_approval_without_automatic_agents(
    tmp_path, monkeypatch
):
    host = OpenChiaHost(
        home=tmp_path,
        session_id="20260930_120000_creator_revision",
        available_tool_names={"web_search"},
        agent_kwargs_factory=lambda _role, _identity: {},
    )
    try:
        blueprint = creation_blueprint_from_spec(
            _creator_spec(_creator_context(host))
        )
        initial = host.service.latest_draft(host.identity.duet_id)
        host.replace_episode_configuration(
            blueprint,
            expected_revision=initial.revision,
        )
        workflow = workflow_blueprint_from_spec(
            EpisodeWorkflowSpec(
                (EpisodeDesignSpec("root", None, _workflow_task("Build")),)
            )
        )
        saved = host.record_duet_workflow_revision(
            workflow,
            expected_workflow_hash=None,
        )
        host._run_frozen_workflow = lambda *_args: None
        approval = host.approve_current()
        host._final_threads[approval.launch_id.value].join(timeout=2)

        def unexpected_agent(**_kwargs):
            raise AssertionError("a point edit must not construct any model worker")

        monkeypatch.setattr(
            "agent.openchia_host.build_creator_workflow_critic_agent",
            unexpected_agent,
        )
        monkeypatch.setattr(
            "agent.openchia_host.build_creator_agent",
            unexpected_agent,
        )
        monkeypatch.setattr(
            "agent.openchia_host.build_task_episode_agent",
            unexpected_agent,
        )

        snapshot = host.episode_workflow_configuration()
        edited = snapshot["configuration"]
        edited["episodes"][0]["contract"]["goal"] = "Build precisely"
        revised = host.record_episode_workflow_revision(
            edited,
            source_artifact_id=snapshot["source_artifact_id"],
            expected_workflow_hash=snapshot["content_hash"],
        )

        assert revised["revision"] == saved["revision"] + 1
        assert revised["ready"] is True
        assert not hasattr(host, "_creator_threads")
        assert host.has_active_work() is False
        assert host.store.get_artifact(approval.artifact_id.value) is not None
        status = host.status()
        assert status["workflow_approval"] is None
        assert status["superseded_workflow_approval"]["approval_id"] == (
            approval.approval_id.value
        )
        assert status["launch"] is None
        assert status["superseded_launch"]["launch_id"] == approval.launch_id.value
    finally:
        host.close()


def test_episode_editor_targets_the_nested_workflow_and_revalidates_edits(tmp_path):
    host = OpenChiaHost(
        home=tmp_path,
        session_id="20260930_120000_episode_workflow_editor",
        available_tool_names={"web_search"},
        agent_kwargs_factory=lambda _role, _identity: {},
    )
    try:
        context = _creator_context(host)
        blueprint = creation_blueprint_from_spec(_creator_spec(context))
        initial = host.service.latest_draft(host.identity.duet_id)
        host.replace_episode_configuration(
            blueprint,
            expected_revision=initial.revision,
        )
        with pytest.raises(DuetProtocolError, match="no Episode workflow draft"):
            host.episode_workflow_configuration()

        rejected_blueprint = {"episodes": []}
        rejected_receipt = host.record_duet_workflow_revision(
            rejected_blueprint,
            expected_workflow_hash=None,
        )
        assert rejected_receipt["ready"] is False
        rejected = host.episode_workflow_configuration()
        assert rejected["configuration"] == rejected_blueprint
        assert rejected["source_kind"] == "episode_workflow_draft"
        assert rejected["validation_error"] is not None

        workflow = EpisodeWorkflowSpec(
            (
                EpisodeDesignSpec("root_episode", None, _workflow_task("Coordinate")),
                EpisodeDesignSpec(
                    "worker_episode",
                    "root_episode",
                    _workflow_task("Build one item"),
                ),
            )
        )
        workflow_blueprint = workflow_blueprint_from_spec(workflow)
        saved = host.record_duet_workflow_revision(
            workflow_blueprint,
            expected_workflow_hash=rejected["content_hash"],
        )
        snapshot = host.episode_workflow_configuration()
        assert [
            node["local_id"] for node in snapshot["configuration"]["episodes"]
        ] == ["root_episode", "worker_episode"]
        assert snapshot["configuration"]["episodes"][1]["contract"]["goal"] == (
            "Build one item"
        )
        assert snapshot["content_hash"] == Sha256Digest.of_record(
            workflow_blueprint
        ).value
        assert snapshot["workflow_hash"] == saved["workflow_hash"]
        status_reference = host.service.duet_status(host.identity.duet_id)[
            "episode_workflow_draft"
        ]
        assert status_reference["artifact_id"] == snapshot["source_artifact_id"]
        exact_workflow = host.service.read_episode_workflow_draft(
            host.identity.duet_id,
            OpaqueId(status_reference["artifact_id"]),
        )
        assert exact_workflow["workflow"] == workflow_blueprint
        assert exact_workflow["content_hash"] == snapshot["content_hash"]
        edited = snapshot["configuration"]
        edited["episodes"][1]["contract"]["goal"] = "Build and verify one item"
        receipt = host.record_episode_workflow_revision(
            edited,
            source_artifact_id=snapshot["source_artifact_id"],
            expected_workflow_hash=snapshot["content_hash"],
        )
        revised = host.episode_workflow_configuration()
        assert receipt["revision"] == saved["revision"] + 1
        assert revised["configuration"]["episodes"][1]["contract"]["goal"] == (
            "Build and verify one item"
        )
        assert receipt["ready"] is True
        assert not hasattr(host, "_creator_threads")
        assert host.has_active_work() is False
    finally:
        host.close()
