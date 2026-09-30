"""Host composition for Creator design experiments.

This module joins the generic Creator and Run Episode bindings to the Duet
evidence/credit service.  It does not decide how a task-specific workflow is
executed or measured: the Run source and evaluator are injected.  It does own
the invariant that every completed experiment is logged before its measured
result is admitted and returned to the Creator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from agent.creator_episode import (
    CREATOR_EPISODE_GRAIN,
    RUN_EPISODE_GRAIN,
    CandidateDesigner,
    CreatorDesignController,
    CreatorRunLogStore,
    RunEpisodeResult,
    RunEpisodeStopReason,
    RunLogReference,
    WorkflowCandidateDesign,
    bind_creator_episode,
    bind_run_episode,
    creator_progress_envelope,
    creator_to_parent_update,
    creator_unit_progress_envelope,
)
from agent.duet_contracts import DuetMessageKind
from agent.duet_service import DuetService
from agent.episode_contracts import (
    EpisodeCreationSpec,
    EpisodeMeasuredOutcome,
    OpaqueId,
)
from method_loop import (
    Context,
    Episode,
    EpisodeGoal,
    EpisodeRecord,
    EpisodeTree,
    Grain,
)
from agent.creator_episode import creator_episode_tree


@dataclass(frozen=True)
class RunEvaluation:
    """Host-measured goal information extracted from one Run Episode."""

    goal_reached: bool
    stop_reason: RunEpisodeStopReason
    goal_result_ids: tuple[OpaqueId, ...]
    accepted_evidence_ids: tuple[OpaqueId, ...]
    measured_outcomes: tuple[EpisodeMeasuredOutcome, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.goal_reached, bool):
            raise ValueError("goal_reached must be boolean")
        if not isinstance(self.stop_reason, RunEpisodeStopReason):
            raise ValueError("stop_reason must be a RunEpisodeStopReason")
        for name in ("goal_result_ids", "accepted_evidence_ids"):
            values = getattr(self, name)
            if not isinstance(values, tuple) or any(
                not isinstance(item, OpaqueId) for item in values
            ):
                raise ValueError(f"{name} must be a tuple of OpaqueIds")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must be unique")
        if not isinstance(self.measured_outcomes, tuple) or any(
            not isinstance(item, EpisodeMeasuredOutcome)
            for item in self.measured_outcomes
        ):
            raise ValueError(
                "measured_outcomes must contain EpisodeMeasuredOutcome values"
            )


class RunEvaluator(Protocol):
    def __call__(
        self,
        candidate: WorkflowCandidateDesign,
        record: EpisodeRecord,
        log: RunLogReference,
    ) -> RunEvaluation: ...


class RunSourceFactory(Protocol):
    def __call__(
        self,
        candidate: WorkflowCandidateDesign,
        run_goal: EpisodeGoal,
    ) -> Any: ...


@dataclass(frozen=True)
class _RunControllerStep:
    stop: bool
    requests_transition: bool = False


@dataclass(frozen=True)
class _RunControllerState:
    observations: int
    stop: bool


class _OneWorkflowRunController:
    epoch = "one_frozen_workflow_run_v1"

    def __init__(self) -> None:
        self.observations = 0

    def observe(self, unit_label: str, value: object, *, is_root: bool) -> _RunControllerStep:
        self.observations += 1
        return _RunControllerStep(stop=True)

    def state(self) -> _RunControllerState:
        return _RunControllerState(self.observations, self.observations >= 1)

    def transitioned(self, epoch: str) -> "_OneWorkflowRunController":
        raise ValueError("a frozen workflow Run Episode has one controller epoch")


class CreatorRuntimeBindings:
    """Shared grains and path-routed contracts for one recursive Creator tree."""

    def __init__(self) -> None:
        self._specs: dict[str, EpisodeCreationSpec] = {}
        self.creator_grain = Grain(
            name=CREATOR_EPISODE_GRAIN,
            unit="one frozen workflow candidate Run Episode",
            result="one host-logged measured workflow outcome",
            controller=self._creator_controller,
        )
        self.run_grain = Grain(
            name=RUN_EPISODE_GRAIN,
            unit="one frozen nested workflow execution",
            result="one host-logged measured goal outcome",
            controller=lambda _path: _OneWorkflowRunController(),
        )

    def register(
        self,
        runtime_key: OpaqueId | str,
        spec: EpisodeCreationSpec,
    ) -> None:
        key = runtime_key.value if isinstance(runtime_key, OpaqueId) else runtime_key
        if not isinstance(key, str) or not key:
            raise TypeError("Creator runtime key must be non-empty text")
        if not isinstance(spec, EpisodeCreationSpec) or not spec.can_create_episodes:
            raise TypeError("Creator bindings require a Creator Episode spec")
        prior = self._specs.get(key)
        if prior is not None and prior != spec:
            raise ValueError("Creator identity was registered with another contract")
        self._specs[key] = spec

    def _creator_controller(
        self,
        path: tuple[tuple[str, str], ...],
    ) -> CreatorDesignController:
        try:
            spec = self._specs[path[-1][1]]
        except KeyError as exc:
            raise ValueError("Creator path has no registered contract") from exc
        return CreatorDesignController(
            minimum_credit=spec.stopping.target,
            minimum_delta=spec.stopping.minimum_delta,
            stagnation_observations=spec.stopping.stagnation_observations,
        )


class CreatorRuntime:
    """Compose one admitted Creator into its measured design/run loop."""

    def __init__(
        self,
        *,
        service: DuetService,
        creator_episode_id: OpaqueId,
        designer: CandidateDesigner,
        log_store: CreatorRunLogStore,
        run_source_factory: RunSourceFactory,
        run_evaluator: RunEvaluator,
        bindings: CreatorRuntimeBindings | None = None,
    ) -> None:
        self.service = service
        self.creator_episode_id = creator_episode_id
        self.designer = designer
        self.log_store = log_store
        self.run_source_factory = run_source_factory
        self.run_evaluator = run_evaluator
        self.frozen_contract = service.creator_contract(creator_episode_id)
        self.bindings = bindings or CreatorRuntimeBindings()
        self.bindings.register(
            creator_episode_id,
            self.frozen_contract.contract,
        )
        self._creator_grain = self.bindings.creator_grain
        self._run_grain = self.bindings.run_grain

    @property
    def creator_grain(self) -> Grain:
        return self._creator_grain

    @property
    def run_grain(self) -> Grain:
        return self._run_grain

    def _build_run(
        self,
        candidate: WorkflowCandidateDesign,
        creator_goal: EpisodeGoal,
    ) -> Episode:
        def projector(
            candidate: WorkflowCandidateDesign,
            record: EpisodeRecord,
            log: RunLogReference,
        ) -> RunEpisodeResult:
            evaluation = self.run_evaluator(candidate, record, log)
            admitted = self.service.submit_workflow_candidate(
                creator_episode_id=self.creator_episode_id,
                revision=candidate.revision,
                workflow=candidate.workflow,
                measured_outcomes=evaluation.measured_outcomes,
            )
            return RunEpisodeResult(
                candidate_revision=candidate.revision,
                candidate_artifact_id=candidate.artifact_id,
                workflow_hash=candidate.workflow.workflow_hash,
                run_episode_id=OpaqueId(record.episode_id),
                execution_run_id=OpaqueId.mint("run", record.run_id),
                goal_id=record.goal.goal_id,
                goal_reached=evaluation.goal_reached,
                stop_reason=evaluation.stop_reason,
                units_consumed=record.units_consumed,
                goal_result_ids=evaluation.goal_result_ids,
                accepted_evidence_ids=evaluation.accepted_evidence_ids,
                workflow_projection=admitted.projection,
                log=log,
            )

        return bind_run_episode(
            grain=self.run_grain,
            candidate=candidate,
            creator_goal=creator_goal,
            source_factory=lambda run_goal: self.run_source_factory(
                candidate, run_goal
            ),
            log_store=self.log_store,
            result_projector=projector,
            bound=1,
        )

    def bind(
        self,
        *,
        goal: EpisodeGoal,
        nested: bool = False,
        runtime_key: str | None = None,
    ) -> Episode:
        policy = self.service.policy(self.frozen_contract.duet_id)
        key = runtime_key or self.creator_episode_id.value
        self.bindings.register(key, self.frozen_contract.contract)

        def publish_unit(_item: Any, contribution: Any, unit_view: Any) -> None:
            result = contribution.controller_input
            self.service.publish_creator_progress(
                creator_unit_progress_envelope(
                    creator_episode_id=self.creator_episode_id,
                    sequence=unit_view.unit_ref.unit_index + 1,
                    result=result,
                    step=unit_view.controller_step,
                    proposal_bound=policy.creator_proposal_bound,
                )
            )

        def publish_close(
            record: EpisodeRecord,
            boundary_kind: DuetMessageKind | None,
        ) -> None:
            self.service.publish_creator_progress(
                creator_progress_envelope(
                    record,
                    creator_episode_id=self.creator_episode_id,
                    waiting_on_duet=(
                        boundary_kind is DuetMessageKind.PAUSE
                        or (
                            boundary_kind is None
                            and record.ended_by == "exhausted"
                            and not getattr(
                                record.controller_state,
                                "successful_candidate",
                                False,
                            )
                            and not getattr(
                                record.controller_state,
                                "no_progress",
                                False,
                            )
                        )
                    ),
                    cancelled=boundary_kind is DuetMessageKind.CANCEL,
                )
            )

        return bind_creator_episode(
            key=key,
            goal=goal,
            grain=self.creator_grain,
            designer=self.designer,
            run_builder=self._build_run,
            claim_boundary_messages=lambda unit_index: (
                self.service.claim_boundary_messages(
                    self.creator_episode_id,
                    unit_index=unit_index,
                )
            ),
            proposal_bound=policy.creator_proposal_bound,
            on_unit=publish_unit,
            on_close=publish_close,
            to_parent=(
                (lambda record: creator_to_parent_update(
                    record,
                    spec=self.frozen_contract.contract,
                ))
                if nested
                else None
            ),
        )

    def run(
        self,
        *,
        goal: EpisodeGoal,
        run_id: str,
        task_grain: Grain | None = None,
        max_depth: int | None = None,
        tree: EpisodeTree | None = None,
    ) -> EpisodeRecord:
        """Run with the exact topology used by the injected workflow builders.

        The default tree supports ordinary nested task Episodes. A runtime that
        supplies a task-specific ``CreatorNodeBuilder`` must also supply the
        corresponding explicit tree; admission never weakens tree validation.
        """

        episode = self.bind(goal=goal)
        if tree is None:
            if task_grain is None or max_depth is None:
                raise ValueError(
                    "ordinary Creator execution requires task_grain and max_depth"
                )
            tree = creator_episode_tree(
                creator_grain=self.creator_grain,
                run_grain=self.run_grain,
                task_grain=task_grain,
                max_depth=max_depth,
                allow_recursive_creators=bool(
                    self.frozen_contract.contract.creator_contract
                    and self.frozen_contract.contract.creator_contract
                    .may_assign_creator_capability
                ),
            )
        elif tree.root != self.creator_grain:
            raise ValueError("an explicit Creator runtime tree has the wrong root")
        return episode.run(
            Context(
                tree=tree,
                run_id=run_id,
            )
        )


__all__ = [
    "CreatorRuntime",
    "CreatorRuntimeBindings",
    "RunEvaluation",
    "RunEvaluator",
    "RunSourceFactory",
]
