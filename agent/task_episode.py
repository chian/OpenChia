"""Bind a fixed-contract Hermes turn loop as an ordinary task Episode.

One model/tool iteration is one Episode unit.  The model may name only
previously registered evidence identities; the host owns arithmetic, stopping,
terminal-result persistence, and the compact update returned to the containing
Episode.  No task transcript or tool output crosses that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional, Protocol

from agent.episode_contracts import (
    ChildEpisodePhase,
    ChildEpisodeStopReason,
    DURABLE_EVIDENCE_PROGRESS_ADAPTER,
    TERMINAL_RESULT_PROGRESS_ADAPTER,
    EpisodeCreationSpec,
    EpisodeDeliverableKind,
    OpaqueId,
    ProgressDirection,
    Sha256Digest,
    ChildEpisodeUpdate,
)
from agent.episode_progress_adapters import validate_progress_contract
from method_loop import (
    Episode,
    EpisodeGoal,
    EpisodeRecord,
    EpisodeRequest,
    EpisodeUpdate,
    Grain,
    Leaf,
)
from method_loop.identities import EpisodeRef


TASK_EPISODE_GRAIN = "task_episode"


class TaskIterationAction(str, Enum):
    CONTINUE = "continue"
    FINAL = "final"
    FAILED = "failed"


@dataclass(frozen=True)
class TaskIterationObservation:
    """Host-derived input for one task controller step."""

    action: TaskIterationAction
    accepted_evidence_ids: tuple[OpaqueId, ...] = ()
    result_artifact_id: Optional[OpaqueId] = None
    deliverable_ready: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.action, TaskIterationAction):
            raise ValueError("action must be a TaskIterationAction")
        if not isinstance(self.accepted_evidence_ids, tuple) or any(
            not isinstance(item, OpaqueId) for item in self.accepted_evidence_ids
        ):
            raise ValueError("accepted_evidence_ids must be a tuple of OpaqueIds")
        if len(set(self.accepted_evidence_ids)) != len(
            self.accepted_evidence_ids
        ):
            raise ValueError("accepted_evidence_ids must be unique")
        if self.result_artifact_id is not None and not isinstance(
            self.result_artifact_id, OpaqueId
        ):
            raise ValueError("result_artifact_id must be an OpaqueId or None")
        if not isinstance(self.deliverable_ready, bool):
            raise ValueError("deliverable_ready must be boolean")
        if self.action is TaskIterationAction.CONTINUE and self.result_artifact_id:
            raise ValueError("a continuing iteration cannot carry a terminal result")

    def as_record(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "accepted_evidence_ids": [
                item.value for item in self.accepted_evidence_ids
            ],
            "result_artifact_id": (
                None
                if self.result_artifact_id is None
                else self.result_artifact_id.value
            ),
            "deliverable_ready": self.deliverable_ready,
        }


@dataclass(frozen=True)
class TaskControllerStep:
    stop: bool
    requests_transition: bool
    phase: ChildEpisodePhase
    stop_reason: ChildEpisodeStopReason
    progress_value: float
    progress_delta: float
    observations: int
    stagnant_observations: int
    accepted_result_id: Optional[OpaqueId]

    def as_record(self) -> dict[str, Any]:
        return {
            "stop": self.stop,
            "requests_transition": self.requests_transition,
            "phase": self.phase.value,
            "stop_reason": self.stop_reason.value,
            "progress_value": self.progress_value,
            "progress_delta": self.progress_delta,
            "observations": self.observations,
            "stagnant_observations": self.stagnant_observations,
            "accepted_result_id": (
                None
                if self.accepted_result_id is None
                else self.accepted_result_id.value
            ),
        }


class TaskEpisodeController:
    """Numerical controller for one immutable ordinary-task contract."""

    def __init__(self, spec: EpisodeCreationSpec) -> None:
        if spec.can_create_episodes:
            raise ValueError("TaskEpisodeController cannot run a Creator contract")
        self.spec = spec
        self.adapter = validate_progress_contract(
            spec.progress,
            spec.stopping,
            model_created=False,
        )
        if self.adapter.adapter_id not in {
            DURABLE_EVIDENCE_PROGRESS_ADAPTER,
            TERMINAL_RESULT_PROGRESS_ADAPTER,
        }:
            raise ValueError("unsupported ordinary task progress adapter")
        self.epoch = spec.spec_hash.value
        self._accepted_evidence_ids: set[OpaqueId] = set()
        self._value = float(spec.progress.baseline)
        self._delta = 0.0
        self._anchor = self._value
        self._observations = 0
        self._stagnant = 0
        self._phase = ChildEpisodePhase.RUNNING
        self._reason = ChildEpisodeStopReason.NONE
        self._accepted_result_id: Optional[OpaqueId] = None

    def _target_reached(self) -> bool:
        if self.spec.progress.direction is ProgressDirection.INCREASE:
            return self._value >= self.spec.stopping.target
        return self._value <= self.spec.stopping.target

    def _step(self) -> TaskControllerStep:
        stop = self._phase is not ChildEpisodePhase.RUNNING
        return TaskControllerStep(
            stop=stop,
            requests_transition=stop and self._phase is not ChildEpisodePhase.SUCCEEDED,
            phase=self._phase,
            stop_reason=self._reason,
            progress_value=self._value,
            progress_delta=self._delta,
            observations=self._observations,
            stagnant_observations=self._stagnant,
            accepted_result_id=self._accepted_result_id,
        )

    def observe(
        self,
        unit_label: str,
        value: object,
        *,
        is_root: bool,
    ) -> TaskControllerStep:
        if isinstance(value, ChildEpisodeUpdate):
            return self._step()
        if not isinstance(value, TaskIterationObservation):
            raise TypeError(
                "TaskEpisodeController requires TaskIterationObservation"
            )
        previous = self._value
        self._accepted_evidence_ids.update(value.accepted_evidence_ids)
        if self.adapter.adapter_id == DURABLE_EVIDENCE_PROGRESS_ADAPTER:
            count = float(len(self._accepted_evidence_ids))
            self._value = (
                self.spec.progress.baseline + count
                if self.spec.progress.direction is ProgressDirection.INCREASE
                else self.spec.progress.baseline - count
            )
        elif (
            value.action is TaskIterationAction.FINAL
            and value.result_artifact_id is not None
        ):
            self._value = self.spec.stopping.target
        self._delta = self._value - previous
        self._observations += 1

        directional = self._value - self._anchor
        if self.spec.progress.direction is ProgressDirection.DECREASE:
            directional = -directional
        if directional >= self.spec.stopping.minimum_delta:
            self._anchor = self._value
            self._stagnant = 0
        else:
            self._stagnant += 1

        if value.action is TaskIterationAction.FAILED:
            self._phase = ChildEpisodePhase.FAILED
            self._reason = ChildEpisodeStopReason.ERROR
        elif value.action is TaskIterationAction.FINAL:
            if not self._target_reached():
                self._phase = ChildEpisodePhase.STOPPED
                self._reason = ChildEpisodeStopReason.SOURCE_EXHAUSTED
            elif not value.deliverable_ready or value.result_artifact_id is None:
                self._phase = ChildEpisodePhase.STOPPED
                self._reason = ChildEpisodeStopReason.DELIVERABLE_MISSING
            else:
                self._phase = ChildEpisodePhase.SUCCEEDED
                self._reason = ChildEpisodeStopReason.TARGET_REACHED
                self._accepted_result_id = value.result_artifact_id
        elif self._stagnant >= self.spec.stopping.stagnation_observations:
            self._phase = ChildEpisodePhase.STOPPED
            self._reason = ChildEpisodeStopReason.NO_PROGRESS
        return self._step()

    def state(self) -> TaskControllerStep:
        return self._step()

    def transitioned(self, epoch: str) -> "TaskEpisodeController":
        raise ValueError("task Episode contracts do not transition controller epochs")


class TaskAgentFactory(Protocol):
    def __call__(
        self,
        *,
        spec: EpisodeCreationSpec,
        episode_id: str,
    ) -> Any: ...


class ResultSink(Protocol):
    def __call__(
        self,
        *,
        episode_id: str,
        result: dict[str, Any],
    ) -> OpaqueId: ...


def _tool_names_since_turn_start(state: Any) -> set[str]:
    names: set[str] = set()
    start = int(getattr(state, "current_turn_user_idx", -1)) + 1
    for message in getattr(state, "messages", ())[start:]:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or ():
            if not isinstance(call, dict):
                continue
            function = call.get("function")
            if isinstance(function, dict) and isinstance(function.get("name"), str):
                names.add(function["name"])
    return names


class _HermesIterationSource:
    def __init__(
        self,
        *,
        agent: Any,
        prompt: str,
        spec: EpisodeCreationSpec,
        episode_id: str,
        result_sink: ResultSink,
    ) -> None:
        if getattr(agent, "api_mode", None) == "codex_app_server":
            raise ValueError(
                "task Episodes require an iteration-transparent model transport"
            )
        self.agent = agent
        self.prompt = prompt
        self.spec = spec
        self.episode_id = episode_id
        self.result_sink = result_sink
        self._prepared: Any = None
        self._terminal = False
        self._report_index = 0

    def _new_evidence(self) -> tuple[OpaqueId, ...]:
        reports = getattr(self.agent, "_episode_progress_reports", ())
        new_reports = reports[self._report_index :]
        self._report_index = len(reports)
        values = []
        for report in new_reports:
            values.extend(report)
        return tuple(OpaqueId(item) for item in dict.fromkeys(values))

    def _deliverable_ready(self, state: Any) -> bool:
        contract = self.spec.deliverable
        if contract.kind is EpisodeDeliverableKind.TYPED_STATUS:
            return True
        return bool(set(contract.tool_names) & _tool_names_since_turn_start(state))

    def _advance(self) -> TaskIterationObservation:
        from agent.conversation_loop import (
            advance_conversation_iteration,
            finalize_conversation_turn,
            prepare_conversation_turn,
        )

        if self._prepared is None:
            self._prepared = prepare_conversation_turn(self.agent, self.prompt)
        prepared = self._prepared
        if prepared.result is not None:
            result = prepared.result
            state = None
            action = (
                TaskIterationAction.FAILED
                if result.get("failed")
                else TaskIterationAction.FINAL
            )
        else:
            state = prepared.state
            verdict = advance_conversation_iteration(self.agent, state)
            if verdict.action == "continue":
                return TaskIterationObservation(
                    action=TaskIterationAction.CONTINUE,
                    accepted_evidence_ids=self._new_evidence(),
                )
            result = (
                verdict.result
                if verdict.action == "return"
                else finalize_conversation_turn(self.agent, state)
            )
            action = (
                TaskIterationAction.FAILED
                if result.get("failed")
                else TaskIterationAction.FINAL
            )
        self._terminal = True
        result_id = None
        if action is TaskIterationAction.FINAL:
            result_id = self.result_sink(
                episode_id=self.episode_id,
                result=result,
            )
            if not isinstance(result_id, OpaqueId):
                raise TypeError("ResultSink must return an OpaqueId")
        return TaskIterationObservation(
            action=action,
            accepted_evidence_ids=self._new_evidence(),
            result_artifact_id=result_id,
            deliverable_ready=self._deliverable_ready(state),
        )

    def next(self, view: Any) -> Optional[Leaf]:
        if self._terminal:
            return None
        index = view.units_consumed
        return Leaf(
            unit=index,
            label=f"model-tool-iteration-{index}",
            extract=lambda _unit: self._advance(),
            result=lambda _unit, observation: observation,
        )


def task_episode_grain(spec_by_key: dict[str, EpisodeCreationSpec]) -> Grain:
    """Build one recursive task Grain whose controller varies by workflow node."""

    def controller(path: tuple[tuple[str, str], ...]) -> TaskEpisodeController:
        try:
            spec = spec_by_key[path[-1][1]]
        except KeyError as exc:
            raise ValueError("task Episode path has no declared contract") from exc
        return TaskEpisodeController(spec)

    return Grain(
        name=TASK_EPISODE_GRAIN,
        unit="one fixed-contract model/tool iteration or predeclared child Episode",
        result="one host-validated typed task result",
        controller=controller,
    )


class TaskRuntimeBindings:
    """One shared task Grain with contracts routed by structural node key."""

    def __init__(self) -> None:
        self._specs: dict[str, EpisodeCreationSpec] = {}
        self.grain = task_episode_grain(self._specs)

    def register(self, key: str, spec: EpisodeCreationSpec) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("task runtime key must be non-empty text")
        if not isinstance(spec, EpisodeCreationSpec) or spec.can_create_episodes:
            raise TypeError("task runtime bindings require an ordinary task spec")
        prior = self._specs.get(key)
        if prior is not None and prior != spec:
            raise ValueError("task runtime key names another contract")
        self._specs[key] = spec


def bind_task_episode(
    *,
    key: str,
    goal: EpisodeGoal,
    spec: EpisodeCreationSpec,
    grain: Grain,
    source: Any,
) -> Episode:
    """Bind an already-composed task source to a compact typed parent update."""

    if grain.name != TASK_EPISODE_GRAIN:
        raise ValueError("task Episode grain must use the task_episode name")

    def to_parent(record: EpisodeRecord) -> EpisodeUpdate:
        state = record.controller_state
        if not isinstance(state, TaskControllerStep):
            raise TypeError("task Episode controller returned an invalid state")
        phase = state.phase
        reason = state.stop_reason
        if record.ended_by == "bound_hit":
            phase = ChildEpisodePhase.BOUND_HIT
            reason = ChildEpisodeStopReason.SAFETY_BOUND
        elif phase is ChildEpisodePhase.RUNNING:
            phase = ChildEpisodePhase.STOPPED
            reason = ChildEpisodeStopReason.SOURCE_EXHAUSTED
        if len(record.path) < 2:
            raise ValueError("task Episode parent identity is unavailable")
        update = ChildEpisodeUpdate(
            child_episode_id=OpaqueId(record.episode_id),
            parent_episode_id=OpaqueId(
                EpisodeRef(run_id=record.run_id, path=record.path[:-1]).episode_id
            ),
            sequence=record.units_consumed,
            phase=phase,
            stop_reason=reason,
            progress_value=state.progress_value,
            progress_delta=state.progress_delta,
            observations=state.observations,
            units_consumed=record.units_consumed,
            requests_transition=phase not in {
                ChildEpisodePhase.RUNNING,
                ChildEpisodePhase.SUCCEEDED,
            },
            spec_hash=spec.spec_hash,
            checkpoint_hash=Sha256Digest.of_record(record.as_record()),
            accepted_result_ids=(
                (state.accepted_result_id,)
                if phase is ChildEpisodePhase.SUCCEEDED
                and state.accepted_result_id is not None
                else ()
            ),
        )
        return EpisodeUpdate(
            record_id=record.episode_id,
            goal=record.goal,
            controller_input=update,
            prompt_context=update.as_record(),
        )

    bound = None if spec.safety_bounds is None else spec.safety_bounds.max_iterations
    return Episode(
        grain=grain,
        key=key,
        source=source,
        request=EpisodeRequest(goal=goal),
        to_parent=to_parent,
        bound=bound,
    )


def hermes_iteration_source(
    *,
    agent: Any,
    prompt: str,
    spec: EpisodeCreationSpec,
    episode_id: str,
    result_sink: ResultSink,
) -> Any:
    return _HermesIterationSource(
        agent=agent,
        prompt=prompt,
        spec=spec,
        episode_id=episode_id,
        result_sink=result_sink,
    )


__all__ = [
    "TASK_EPISODE_GRAIN",
    "ResultSink",
    "TaskAgentFactory",
    "TaskControllerStep",
    "TaskEpisodeController",
    "TaskIterationAction",
    "TaskIterationObservation",
    "TaskRuntimeBindings",
    "bind_task_episode",
    "hermes_iteration_source",
    "task_episode_grain",
]
