"""Execute a frozen ordinary-task Episode workflow inside one Run Episode.

The workflow topology is fixed before execution.  Children run in declaration
order and return only typed updates; the containing task's Hermes turn begins
after those updates are available.  Creator-capable nodes require an explicit
task-specific builder because their loop unit is a workflow experiment, not a
Hermes model/tool iteration.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Optional, Protocol

from agent.creator_episode import WorkflowCandidateDesign
from agent.duet_contracts import canonical_json
from agent.episode_contracts import EpisodeCreationSpec, EpisodeDesignSpec, OpaqueId
from agent.task_episode import (
    ResultSink,
    TaskRuntimeBindings,
    bind_task_episode,
    hermes_iteration_source,
)
from method_loop import Episode, EpisodeGoal, EpisodeUpdate, Grain


class WorkflowRuntimeError(RuntimeError):
    """A frozen workflow has no executable binding for one of its nodes."""


class WorkflowTaskAgentFactory(Protocol):
    def __call__(
        self,
        *,
        spec: EpisodeCreationSpec,
        episode_id: str,
        accepted_evidence_ids: tuple[OpaqueId, ...],
    ) -> Any: ...


class CreatorNodeBuilder(Protocol):
    def __call__(
        self,
        *,
        node: EpisodeDesignSpec,
        goal: EpisodeGoal,
        runtime_key: str,
    ) -> Episode: ...


class _TaskWithChildrenSource:
    def __init__(
        self,
        *,
        children: tuple[Episode, ...],
        spec: EpisodeCreationSpec,
        agent_factory: WorkflowTaskAgentFactory,
        evidence_ids: tuple[OpaqueId, ...],
        result_sink: ResultSink,
    ) -> None:
        self.children = children
        self.spec = spec
        self.agent_factory = agent_factory
        self.evidence_ids = evidence_ids
        self.result_sink = result_sink
        self._child_index = 0
        self._iterations: Any = None

    def next(self, view: Any) -> Any:
        if self._child_index < len(self.children):
            child = self.children[self._child_index]
            self._child_index += 1
            return child
        if self._iterations is None:
            agent = self.agent_factory(
                spec=self.spec,
                episode_id=view.episode_ref.episode_id,
                accepted_evidence_ids=self.evidence_ids,
            )
            prompt = canonical_json(
                {
                    "operation": "execute_fixed_episode_contract",
                    "episode_id": view.episode_ref.episode_id,
                    "goal": view.goal.as_record(),
                    "contract": self.spec.as_record(),
                    "child_updates": [
                        update.as_record() for update in view.updates
                    ],
                    "required_action": (
                        "Execute only this contract. Report only registered "
                        "evidence identities with episode_progress, then return "
                        "the declared result."
                    ),
                }
            )
            self._iterations = hermes_iteration_source(
                agent=agent,
                prompt=prompt,
                spec=self.spec,
                episode_id=view.episode_ref.episode_id,
                result_sink=self.result_sink,
            )
        return self._iterations.next(view)


class _SingleRootSource:
    def __init__(self, root: Episode) -> None:
        self.root = root
        self._consumed = False

    def next(self, view: Any) -> Optional[Episode]:
        if self._consumed:
            return None
        self._consumed = True
        return self.root


class WorkflowRuntime:
    """Task-specific collaborators around the generic nested Episode method."""

    def __init__(
        self,
        *,
        agent_factory: WorkflowTaskAgentFactory,
        result_sink: ResultSink,
        evidence_ids_for_node: Optional[
            Callable[[EpisodeDesignSpec], Iterable[OpaqueId]]
        ] = None,
        creator_node_builder: Optional[CreatorNodeBuilder] = None,
        bindings: Optional[TaskRuntimeBindings] = None,
    ) -> None:
        self.agent_factory = agent_factory
        self.result_sink = result_sink
        self.evidence_ids_for_node = evidence_ids_for_node or (lambda _node: ())
        self.creator_node_builder = creator_node_builder
        self.bindings = bindings or TaskRuntimeBindings()
        self.task_grain: Grain = self.bindings.grain

    @staticmethod
    def _children_by_parent(
        candidate: WorkflowCandidateDesign,
    ) -> dict[Optional[str], list[EpisodeDesignSpec]]:
        children: dict[Optional[str], list[EpisodeDesignSpec]] = {}
        for item in candidate.workflow.episodes:
            children.setdefault(item.workflow_parent_local_id, []).append(item)
        return children

    def _build_node(
        self,
        *,
        node: EpisodeDesignSpec,
        key_namespace: str,
        parent_goal: EpisodeGoal,
        children_by_parent: dict[Optional[str], list[EpisodeDesignSpec]],
    ) -> Episode:
        goal = EpisodeGoal.child(
            parent_goal,
            objective={"kind": "execute_declared_episode", "goal": node.contract.goal},
            result_contract={
                "kind": "typed_episode_result",
                "spec_hash": node.contract.spec_hash.value,
            },
        )
        runtime_key = f"{key_namespace}:{node.local_id}"
        if node.contract.can_create_episodes:
            if children_by_parent.get(node.local_id):
                raise WorkflowRuntimeError(
                    "a Creator workflow node cannot have predeclared children"
                )
            if self.creator_node_builder is None:
                raise WorkflowRuntimeError(
                    "creator-capable workflow nodes require a CreatorNodeBuilder"
                )
            return self.creator_node_builder(
                node=node,
                goal=goal,
                runtime_key=runtime_key,
            )
        children = tuple(
            self._build_node(
                node=child,
                key_namespace=key_namespace,
                parent_goal=goal,
                children_by_parent=children_by_parent,
            )
            for child in children_by_parent.get(node.local_id, ())
        )
        evidence_ids = tuple(self.evidence_ids_for_node(node))
        if any(not isinstance(item, OpaqueId) for item in evidence_ids):
            raise TypeError("evidence_ids_for_node must return OpaqueIds")
        return bind_task_episode(
            key=runtime_key,
            goal=goal,
            spec=node.contract,
            grain=self.task_grain,
            source=_TaskWithChildrenSource(
                children=children,
                spec=node.contract,
                agent_factory=self.agent_factory,
                evidence_ids=evidence_ids,
                result_sink=self.result_sink,
            ),
        )

    def source_for_candidate(
        self,
        candidate: WorkflowCandidateDesign,
        run_goal: EpisodeGoal,
    ) -> Any:
        """Build the single frozen root launched by a candidate Run Episode."""

        key_namespace = candidate.artifact_id.value
        for item in candidate.workflow.episodes:
            if not item.contract.can_create_episodes:
                self.bindings.register(
                    f"{key_namespace}:{item.local_id}",
                    item.contract,
                )
        children_by_parent = self._children_by_parent(candidate)
        roots = children_by_parent.get(None, ())
        if len(roots) != 1:
            raise WorkflowRuntimeError("a Run Episode requires one workflow root")
        root = self._build_node(
            node=roots[0],
            key_namespace=key_namespace,
            parent_goal=run_goal,
            children_by_parent=children_by_parent,
        )
        return _SingleRootSource(root)


__all__ = [
    "CreatorNodeBuilder",
    "WorkflowRuntime",
    "WorkflowRuntimeError",
    "WorkflowTaskAgentFactory",
]
