from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.creator_episode import (
    CREATOR_EPISODE_GRAIN,
    RUN_EPISODE_GRAIN,
    TASK_EPISODE_GRAIN,
    CreatorDesignController,
    CreatorControllerState,
    CreatorRunLogStore,
    RunEpisodeResult,
    RunEpisodeStopReason,
    RunLogReference,
    WorkflowCandidateDesign,
    bind_creator_episode,
    bind_run_episode,
    creator_episode_tree,
    creator_progress_envelope,
    creator_to_parent_update,
)
from agent.duet_contracts import DuetDecision, DuetDesignState, DuetMessageKind
from agent.creator_design_session import CreatorDesignCycleError, CreatorDesignSession
from agent.duet_service import DuetService
from agent.episode_blueprints import workflow_blueprint_from_spec
from agent.episode_contracts import (
    CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
    ChildEpisodeUpdate,
    EpisodeCreationSpec,
    EpisodeCreatorContract,
    EpisodeCreatorContext,
    EpisodeCreatorContextReference,
    EpisodeCreatorReturnContract,
    EpisodeCreditComponentSpec,
    EpisodeDesignSpec,
    EpisodeEvidenceRequirement,
    EpisodeMethodCreditSpec,
    EpisodeWorkflowDesignProjection,
    EpisodeWorkflowSpec,
    NumericProgressMeasure,
    OpaqueId,
    ProgressDirection,
    ProgressStopCriteria,
    Sha256Digest,
)
from method_loop import (
    Context,
    Episode,
    EpisodeGoal,
    EpisodeRecord,
    EpisodeRequest,
    EpisodeRef,
    EpisodeTree,
    EpisodeUpdate,
    Grain,
    UnitRecord,
    UnitRef,
    leaves,
)
from agent.inline_tool_executors import INLINE_TOOL_EXECUTORS, InlineToolContext


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


def _task_spec():
    return EpisodeCreationSpec(
        goal="Produce one test observation.",
        progress=NumericProgressMeasure(
            metric_id=OpaqueId.mint("metric", "task-observation"),
            description="Accepted observations",
            unit="observations",
            direction=ProgressDirection.INCREASE,
            baseline=0,
        ),
        stopping=ProgressStopCriteria(
            target=1,
            minimum_delta=1,
            stagnation_observations=2,
        ),
    )


def _workflow():
    return EpisodeWorkflowSpec(
        (EpisodeDesignSpec("root", None, _task_spec()),)
    )


def _creator_spec():
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
    context_record = {
        "artifact_kind": "task_specification",
        "schema_version": 1,
        "content": {"goal": "Design one nested workflow."},
    }
    context_reference = EpisodeCreatorContextReference(
        artifact_id=OpaqueId.mint("context", "creator-episode-test-context"),
        content_hash=Sha256Digest.of_record(context_record),
        artifact_kind="task_specification",
        schema_version=1,
        purpose="creator_entrypoint",
        required=True,
    )
    return EpisodeCreationSpec(
        goal="Design one nested workflow.",
        progress=NumericProgressMeasure(
            metric_id=OpaqueId.mint("metric", "nested-creator"),
            description="Host method credit",
            unit="normalized credit",
            direction=ProgressDirection.INCREASE,
            baseline=0,
            adapter_id=CREATOR_METHOD_CREDIT_PROGRESS_ADAPTER,
        ),
        stopping=ProgressStopCriteria(
            target=1,
            minimum_delta=0.1,
            stagnation_observations=3,
        ),
        can_create_episodes=True,
        creator_contract=EpisodeCreatorContract(
            design_context=EpisodeCreatorContext(
                entrypoint_artifact_id=context_reference.artifact_id,
                artifact_references=(context_reference,),
            ),
            design_scope="Only the nested goal.",
            assignable_capability_names=(),
            may_assign_creator_capability=False,
            evidence_requirements=(requirement,),
            required_existing_evidence_ids=(),
            credit_assignment=EpisodeMethodCreditSpec((component,)),
            return_contract=EpisodeCreatorReturnContract(
                measurement_ids=("goal_completion",),
                credit_component_ids=("goal_credit",),
            ),
        ),
    )


def _run_result(*, revision: int, credit: float) -> RunEpisodeResult:
    workflow = _workflow()
    projection = EpisodeWorkflowDesignProjection(
        artifact_id=OpaqueId.mint("workflow", f"candidate-{revision}"),
        workflow_hash=workflow.workflow_hash,
        episode_count=1,
        workflow_root_count=1,
        measured_outcomes=(),
        credit_components=(),
        method_credit=credit,
        status_values=(),
    )
    return RunEpisodeResult(
        candidate_revision=revision,
        candidate_artifact_id=OpaqueId.mint("design", f"candidate-{revision}"),
        workflow_hash=workflow.workflow_hash,
        run_episode_id=OpaqueId.mint("episode", f"run-{revision}"),
        execution_run_id=OpaqueId.mint("run", f"execution-{revision}"),
        goal_id=f"goal-{revision}",
        goal_reached=False,
        stop_reason=RunEpisodeStopReason.SOURCE_EXHAUSTED,
        units_consumed=1,
        goal_result_ids=(),
        accepted_evidence_ids=(),
        workflow_projection=projection,
        log=RunLogReference(
            artifact_id=OpaqueId.mint("runlog", f"run-{revision}"),
            digest=workflow.workflow_hash,
            location=f"/run-logs/{revision}.json",
            byte_count=1,
        ),
    )


class _OneCandidateDesigner:
    def __init__(self, workflow):
        self.workflow = workflow
        self.calls = 0

    def next_candidate(self, view, previous_runs, boundary_messages):
        self.calls += 1
        if self.calls > 1:
            return None
        return WorkflowCandidateDesign(
            revision=1,
            artifact_id=OpaqueId.mint("design", "candidate-one"),
            workflow=self.workflow,
        )


def test_creator_unit_is_design_run_log_inspect_cycle(tmp_path):
    creator_grain = Grain(
        name=CREATOR_EPISODE_GRAIN,
        unit="one frozen candidate Run Episode",
        result="one logged host-measured candidate outcome",
        controller=lambda _path: CreatorDesignController(
            minimum_credit=0.8,
            minimum_delta=0.05,
            stagnation_observations=3,
        ),
    )
    run_grain = Grain(
        name=RUN_EPISODE_GRAIN,
        unit="one nested workflow execution",
        result="one logged goal result",
        controller=lambda _path: _StopAfterOne(),
    )
    task_grain = Grain(
        name=TASK_EPISODE_GRAIN,
        unit="one task observation",
        result="one task result",
        controller=lambda _path: _StopAfterOne(),
    )
    workflow = _workflow()
    log_store = CreatorRunLogStore(tmp_path / "run_logs")

    def run_builder(candidate, creator_goal):
        def source_factory(run_goal):
            task_goal = EpisodeGoal.child(
                run_goal,
                objective={"task": "test candidate"},
                result_contract={"kind": "task_result"},
            )
            task = Episode(
                grain=task_grain,
                key="root",
                source=leaves(
                    [{"observation": "accepted"}],
                    extract=lambda unit: unit,
                    result=lambda unit, accepted: {"accepted_count": 1},
                ),
                request=EpisodeRequest(goal=task_goal),
                to_parent=lambda record: EpisodeUpdate(
                    record_id=record.episode_id,
                    goal=record.goal,
                    controller_input={"goal_reached": True},
                ),
            )

            class _Source:
                consumed = False

                def next(self, view):
                    if self.consumed:
                        return None
                    self.consumed = True
                    return task

            return _Source()

        def projector(candidate, record, log):
            projection = EpisodeWorkflowDesignProjection(
                artifact_id=OpaqueId.mint("workflow", "candidate-one"),
                workflow_hash=candidate.workflow.workflow_hash,
                episode_count=1,
                workflow_root_count=1,
                measured_outcomes=(),
                credit_components=(),
                method_credit=1,
                status_values=(),
            )
            return RunEpisodeResult(
                candidate_revision=candidate.revision,
                candidate_artifact_id=candidate.artifact_id,
                workflow_hash=candidate.workflow.workflow_hash,
                run_episode_id=OpaqueId(record.episode_id),
                execution_run_id=OpaqueId.mint("run", record.episode_id),
                goal_id=record.goal.goal_id,
                goal_reached=True,
                stop_reason=RunEpisodeStopReason.TARGET_REACHED,
                units_consumed=record.units_consumed,
                goal_result_ids=(OpaqueId.mint("result", record.episode_id),),
                accepted_evidence_ids=(
                    OpaqueId.mint("evidence", record.episode_id),
                ),
                workflow_projection=projection,
                log=log,
            )

        return bind_run_episode(
            grain=run_grain,
            candidate=candidate,
            creator_goal=creator_goal,
            source_factory=source_factory,
            log_store=log_store,
            result_projector=projector,
            bound=1,
        )

    creator_goal = EpisodeGoal.root(
        objective={"task": "design workflow"},
        result_contract={"kind": "approved_workflow_candidate"},
    )
    creator = bind_creator_episode(
        key="creator",
        goal=creator_goal,
        grain=creator_grain,
        designer=_OneCandidateDesigner(workflow),
        run_builder=run_builder,
        claim_boundary_messages=lambda _unit: (),
        proposal_bound=8,
    )
    record = creator.run(
        Context(
            tree=creator_episode_tree(
                creator_grain=creator_grain,
                run_grain=run_grain,
                task_grain=task_grain,
                max_depth=4,
            ),
            run_id="creator-test-run",
        )
    )

    assert record.units_consumed == 1
    result = record.unit_records[0].episode_update.controller_input
    assert isinstance(result, RunEpisodeResult)
    assert Path(result.log.location).is_file()
    assert result.log.artifact_id.value in Path(result.log.location).name
    assert "creator_episode" in log_store.read(result.log)
    envelope = creator_progress_envelope(record)
    assert envelope.state is DuetDesignState.SEALED
    assert envelope.method_credit == 1
    assert envelope.accepted_evidence_ids == result.accepted_evidence_ids


def test_waiting_for_duet_consumes_no_creator_units(tmp_path):
    creator_grain = Grain(
        name=CREATOR_EPISODE_GRAIN,
        unit="one candidate run",
        result="one result",
        controller=lambda _path: CreatorDesignController(
            minimum_credit=1,
            minimum_delta=0.1,
            stagnation_observations=3,
        ),
    )
    run_grain = Grain(
        name=RUN_EPISODE_GRAIN,
        unit="one run",
        result="one result",
        controller=lambda _path: _StopAfterOne(),
    )
    task_grain = Grain(
        name=TASK_EPISODE_GRAIN,
        unit="one task",
        result="one result",
        controller=lambda _path: _StopAfterOne(),
    )
    designer = _OneCandidateDesigner(_workflow())
    decision = DuetDecision(
        message_id=OpaqueId.mint("decision", "pause"),
        duet_id=OpaqueId.mint("duet", "pause"),
        creator_episode_id=OpaqueId.mint("episode", "pause"),
        kind=DuetMessageKind.PAUSE,
        expected_unit_index=0,
        code="human_pause",
    )
    creator = bind_creator_episode(
        key="creator",
        goal=EpisodeGoal.root(
            objective={"task": "wait"},
            result_contract={"kind": "candidate"},
        ),
        grain=creator_grain,
        designer=designer,
        run_builder=lambda *_args: (_ for _ in ()).throw(AssertionError("must not run")),
        claim_boundary_messages=lambda _unit: (decision,),
        proposal_bound=8,
    )
    record = creator.run(
        Context(
            tree=creator_episode_tree(
                creator_grain=creator_grain,
                run_grain=run_grain,
                task_grain=task_grain,
                max_depth=4,
            ),
            run_id="waiting-run",
        )
    )

    assert record.units_consumed == 0
    assert designer.calls == 0
    assert creator_progress_envelope(
        record, waiting_on_duet=True
    ).state is DuetDesignState.WAITING_ON_DUET


def test_creator_stagnation_counts_failure_to_improve_the_best_candidate():
    controller = CreatorDesignController(
        minimum_credit=1,
        minimum_delta=0.05,
        stagnation_observations=3,
    )

    assert controller.observe(
        "candidate-1", _run_result(revision=1, credit=0.9), is_root=True
    ).no_progress is False
    assert controller.observe(
        "candidate-2", _run_result(revision=2, credit=0.1), is_root=True
    ).no_progress is False
    assert controller.observe(
        "candidate-3", _run_result(revision=3, credit=0.9), is_root=True
    ).no_progress is False
    final = controller.observe(
        "candidate-4", _run_result(revision=4, credit=0.89), is_root=True
    )

    assert final.no_progress is True
    assert final.progress_value == 0.9
    assert final.progress_delta == 0
    assert controller.state().stagnant_observations == 3


def test_nested_creator_returns_only_a_closed_child_update():
    result = replace(
        _run_result(revision=1, credit=1),
        goal_reached=True,
        stop_reason=RunEpisodeStopReason.TARGET_REACHED,
    )
    goal = EpisodeGoal.child(
        EpisodeGoal.root(
            objective={"kind": "outer"},
            result_contract={"kind": "outer_result"},
        ),
        objective={"kind": "nested_creator"},
        result_contract={"kind": "workflow"},
    )
    path = (("outer_episode", "parent"), (CREATOR_EPISODE_GRAIN, "nested"))
    episode_ref = EpisodeRef(run_id="nested-creator-run", path=path)
    step = SimpleNamespace(progress_delta=1.0)
    record = EpisodeRecord(
        scope_level=CREATOR_EPISODE_GRAIN,
        scope_key="nested",
        units_consumed=1,
        ended_by="yield_stop",
        unit_records=(
            UnitRecord(
                unit_label="candidate-1",
                controller_input=result,
                controller_step=step,
                epoch="creator_design_v1",
                unit_ref=UnitRef(episode_ref.episode_id, 0),
            ),
        ),
        controller_state=CreatorControllerState(
            observations=1,
            progress_value=1,
            best_credit=1,
            stagnant_observations=0,
            stagnation_anchor=1,
            successful_candidate=True,
            no_progress=False,
            stop=True,
        ),
        request=EpisodeRequest(goal=goal),
        path=path,
        episode_ref=episode_ref,
    )

    update = creator_to_parent_update(record, spec=_creator_spec())
    closed = update.controller_input

    assert isinstance(closed, ChildEpisodeUpdate)
    assert closed.goal_reached is True
    assert closed.accepted_result_ids == (
        result.workflow_projection.artifact_id,
    )
    assert update.prompt_context["workflow_design"] == (
        result.workflow_projection.as_record()
    )
    assert result.log.location not in str(update.as_record())


def test_creator_log_read_rejects_a_reference_that_changes_identity_or_size(tmp_path):
    log_store = CreatorRunLogStore(tmp_path / "run_logs")
    creator_grain = Grain(
        name=CREATOR_EPISODE_GRAIN,
        unit="one candidate",
        result="one result",
        controller=lambda _path: CreatorDesignController(
            minimum_credit=1,
            minimum_delta=0.1,
            stagnation_observations=3,
        ),
    )
    record = Episode(
        grain=creator_grain,
        key="log-record",
        source=leaves(
            [{"accepted": True}],
            extract=lambda unit: unit,
            result=lambda unit, accepted: accepted,
        ),
        request=EpisodeRequest(
            goal=EpisodeGoal.root(
                objective={"task": "log"},
                result_contract={"kind": "audit"},
            )
        ),
        bound=0,
    ).run(
        Context(
            tree=EpisodeTree(root=creator_grain, children={}),
            run_id="log-integrity-run",
        )
    )
    reference = log_store.persist(record)

    with pytest.raises(PermissionError, match="artifact identity"):
        log_store.read(
            replace(
                reference,
                artifact_id=OpaqueId.mint("runlog", "different-artifact"),
            )
        )
    with pytest.raises(RuntimeError, match="byte count"):
        log_store.read(replace(reference, byte_count=reference.byte_count + 1))


def test_creator_design_session_exposes_prior_log_and_freezes_one_submission():
    workflow = _workflow()
    creator_spec = _creator_spec()
    required_context_id = (
        creator_spec.creator_contract.design_context.entrypoint_artifact_id.value
    )
    creator_id = OpaqueId.mint("episode", "creator-design-session")

    class _Service(DuetService):
        def __init__(self):
            self.revision = 0

        def creator_contract(self, requested_id):
            assert requested_id == creator_id
            return SimpleNamespace(
                artifact_id=OpaqueId.mint("contract", "creator-design-session"),
                content_hash=workflow.workflow_hash,
                contract=creator_spec,
            )

        def freeze_workflow_design(
            self,
            *,
            creator_episode_id,
            workflow_blueprint,
            consumed_context_artifact_ids,
        ):
            assert creator_episode_id == creator_id
            assert workflow_blueprint == workflow_blueprint_from_spec(workflow)
            assert consumed_context_artifact_ids == (required_context_id,)
            self.revision += 1
            return SimpleNamespace(
                revision=self.revision,
                artifact_id=OpaqueId.mint("design", f"revision-{self.revision}"),
                workflow=workflow,
            )

        def creator_boundary_records(self, messages):
            assert messages == ()
            return ()

    class _Agent:
        def __init__(self):
            self._creator_log_references = {}
            self._creator_workflow_submit = None
            self._creator_context_read_ids = {required_context_id}
            self._creator_reviewed_workflow_hashes = {
                Sha256Digest.of_record(
                    workflow_blueprint_from_spec(workflow)
                ).value
            }
            self.request = None

        def chat(self, message):
            import json

            self.request = json.loads(message)
            result = INLINE_TOOL_EXECUTORS["workflow_candidate"](
                self,
                {"workflow": workflow_blueprint_from_spec(workflow)},
                InlineToolContext(effective_task_id="creator-design"),
            )
            assert json.loads(result)["accepted"] is True
            return "candidate submitted"

    previous = _run_result(revision=1, credit=0.2)
    agent = _Agent()
    session = CreatorDesignSession(
        service=_Service(),
        creator_episode_id=creator_id,
        agent=agent,
    )
    candidate = session.next_candidate(
        SimpleNamespace(units_consumed=1),
        (previous,),
        (),
    )

    assert candidate is not None
    assert candidate.revision == 1
    assert previous.log.artifact_id.value in agent._creator_log_references
    assert agent.request["previous_run_results"][0]["log"] == previous.log.as_record()
    assert agent._creator_workflow_submit is None

    class _RejectingAgent:
        def __init__(self):
            self._creator_log_references = {}
            self._creator_context_read_ids = {required_context_id}

        def chat(self, _message):
            self._creator_last_candidate_result = {
                "accepted": False,
                "reason": "ValueError",
                "message": "episodes[2].contract.result_schema is required",
            }
            return "candidate rejected"

    rejecting_session = CreatorDesignSession(
        service=_Service(),
        creator_episode_id=creator_id,
        agent=_RejectingAgent(),
    )
    with pytest.raises(CreatorDesignCycleError) as rejected:
        rejecting_session.next_candidate(
            SimpleNamespace(units_consumed=0),
            (),
            (),
        )
    assert rejected.value.code == "candidate_rejected"
    assert rejected.value.details["candidate_submission"]["message"] == (
        "episodes[2].contract.result_schema is required"
    )
