from __future__ import annotations

from dataclasses import dataclass
import json
from types import SimpleNamespace

from agent.creator_episode import RUN_EPISODE_GRAIN, WorkflowCandidateDesign
from agent.episode_contracts import (
    TERMINAL_RESULT_PROGRESS_ADAPTER,
    ChildEpisodeUpdate,
    EpisodeCreationSpec,
    EpisodeDeliverableContract,
    EpisodeDeliverableKind,
    EpisodeDesignSpec,
    EpisodeSafetyBounds,
    EpisodeWorkflowSpec,
    NumericProgressMeasure,
    OpaqueId,
    ProgressDirection,
    ProgressStopCriteria,
)
from agent.workflow_runtime import WorkflowRuntime
from method_loop import Context, Episode, EpisodeGoal, EpisodeRequest, EpisodeTree, Grain


@dataclass(frozen=True)
class _Step:
    stop: bool
    requests_transition: bool = False


@dataclass(frozen=True)
class _State:
    observations: int
    stop: bool


class _OneRoot:
    epoch = "one-root"

    def __init__(self):
        self.observations = 0

    def observe(self, unit_label, value, *, is_root):
        self.observations += 1
        return _Step(stop=True)

    def state(self):
        return _State(self.observations, self.observations >= 1)

    def transitioned(self, epoch):
        raise ValueError("no transition")


def _task(goal: str) -> EpisodeCreationSpec:
    return EpisodeCreationSpec(
        goal=goal,
        progress=NumericProgressMeasure(
            metric_id=OpaqueId.mint("metric", goal),
            description="Persisted terminal result",
            unit="results",
            direction=ProgressDirection.INCREASE,
            baseline=0,
            adapter_id=TERMINAL_RESULT_PROGRESS_ADAPTER,
        ),
        stopping=ProgressStopCriteria(
            target=1,
            minimum_delta=1,
            stagnation_observations=3,
        ),
        safety_bounds=EpisodeSafetyBounds(max_iterations=3),
    )


def _shared_state_task(goal: str) -> EpisodeCreationSpec:
    return EpisodeCreationSpec(
        goal=goal,
        progress=NumericProgressMeasure(
            metric_id=OpaqueId.mint("metric", goal),
            description="Persisted terminal result",
            unit="results",
            direction=ProgressDirection.INCREASE,
            baseline=0,
            adapter_id=TERMINAL_RESULT_PROGRESS_ADAPTER,
        ),
        stopping=ProgressStopCriteria(
            target=1,
            minimum_delta=1,
            stagnation_observations=3,
        ),
        deliverable=EpisodeDeliverableContract(
            kind=EpisodeDeliverableKind.SHARED_STATE,
            description="One committed shared-state write.",
            tool_names=("write_file",),
        ),
        safety_bounds=EpisodeSafetyBounds(max_iterations=3),
    )


def test_frozen_workflow_runs_children_then_parent_with_typed_updates(monkeypatch):
    prompts = []

    def prepare(_agent, prompt):
        prompts.append(json.loads(prompt))
        return SimpleNamespace(
            result={"failed": False, "final_response": "stored result"},
            state=None,
        )

    monkeypatch.setattr(
        "agent.conversation_loop.prepare_conversation_turn",
        prepare,
    )
    workflow = EpisodeWorkflowSpec(
        (
            EpisodeDesignSpec("root", None, _task("Synthesize the child result.")),
            EpisodeDesignSpec("child", "root", _task("Produce a child result.")),
        )
    )
    candidate = WorkflowCandidateDesign(
        revision=1,
        artifact_id=OpaqueId.mint("design", "nested-workflow"),
        workflow=workflow,
    )
    persisted = []

    def result_sink(*, episode_id, result):
        persisted.append((episode_id, result["final_response"]))
        return OpaqueId.mint("result", episode_id)

    runtime = WorkflowRuntime(
        agent_factory=lambda **_kwargs: SimpleNamespace(
            _episode_progress_reports=[]
        ),
        result_sink=result_sink,
    )
    run_grain = Grain(
        name=RUN_EPISODE_GRAIN,
        unit="one frozen workflow",
        result="one typed root update",
        controller=lambda _path: _OneRoot(),
    )
    run_goal = EpisodeGoal.root(
        objective={"kind": "test-run"},
        result_contract={"kind": "typed-root"},
    )
    run = Episode(
        grain=run_grain,
        key="candidate-1",
        source=runtime.source_for_candidate(candidate, run_goal),
        request=EpisodeRequest(goal=run_goal),
        bound=1,
    )
    record = run.run(
        Context(
            tree=EpisodeTree(
                root=run_grain,
                children={
                    run_grain: (runtime.task_grain,),
                    runtime.task_grain: (runtime.task_grain,),
                },
                self_nesting=(runtime.task_grain.name,),
                max_depth=3,
            ),
            run_id="nested-workflow-run",
        )
    )

    root_record = record.unit_records[0].child
    assert root_record is not None
    assert root_record.controller_state.phase.value == "succeeded"
    assert len(persisted) == 2
    assert prompts[0]["child_updates"] == []
    [root_child_update] = prompts[1]["child_updates"]
    assert ChildEpisodeUpdate.from_record(
        root_child_update["controller_input"]
    ).goal_reached is True


def test_early_turn_result_does_not_fabricate_a_shared_state_deliverable(monkeypatch):
    monkeypatch.setattr(
        "agent.conversation_loop.prepare_conversation_turn",
        lambda _agent, _prompt: SimpleNamespace(
            result={"failed": False, "final_response": "no write occurred"},
            state=None,
        ),
    )
    candidate = WorkflowCandidateDesign(
        revision=1,
        artifact_id=OpaqueId.mint("design", "shared-state-missing"),
        workflow=EpisodeWorkflowSpec(
            (
                EpisodeDesignSpec(
                    "root",
                    None,
                    _shared_state_task("Materialize the declared output."),
                ),
            )
        ),
    )
    runtime = WorkflowRuntime(
        agent_factory=lambda **_kwargs: SimpleNamespace(
            _episode_progress_reports=[]
        ),
        result_sink=lambda **_kwargs: OpaqueId.mint("result", "stored"),
    )
    run_grain = Grain(
        name=RUN_EPISODE_GRAIN,
        unit="one frozen workflow",
        result="one typed root update",
        controller=lambda _path: _OneRoot(),
    )
    run_goal = EpisodeGoal.root(
        objective={"kind": "test-run"},
        result_contract={"kind": "typed-root"},
    )
    record = Episode(
        grain=run_grain,
        key="candidate-1",
        source=runtime.source_for_candidate(candidate, run_goal),
        request=EpisodeRequest(goal=run_goal),
        bound=1,
    ).run(
        Context(
            tree=EpisodeTree(
                root=run_grain,
                children={run_grain: (runtime.task_grain,)},
                max_depth=2,
            ),
            run_id="shared-state-missing-run",
        )
    )

    task_record = record.unit_records[0].child
    assert task_record.controller_state.phase.value == "stopped"
    assert task_record.controller_state.stop_reason.value == "deliverable_missing"
