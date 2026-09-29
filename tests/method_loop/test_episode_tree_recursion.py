"""Behavior contracts for explicitly recursive Episode topology."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from method_loop import (
    Context,
    Episode,
    EpisodeGoal,
    EpisodeRequest,
    EpisodeTree,
    EpisodeUpdate,
    Grain,
)


@dataclass(frozen=True)
class _Step:
    stop: bool
    requests_transition: bool = False


@dataclass(frozen=True)
class _State:
    observations: int
    stop: bool


class _StopAfterOneController:
    epoch = "initial"

    def __init__(self) -> None:
        self._observations = 0

    def observe(self, unit_label, value, *, is_root):
        self._observations += 1
        return _Step(stop=self._observations >= 1)

    def state(self):
        return _State(
            observations=self._observations,
            stop=self._observations >= 1,
        )

    def transitioned(self, epoch):
        controller = _StopAfterOneController()
        controller.epoch = epoch
        return controller


class _SequenceSource:
    def __init__(self, *items) -> None:
        self._items = list(items)

    def next(self, view):
        if not self._items:
            return None
        return self._items.pop(0)


def _grain() -> Grain:
    return Grain(
        name="agent",
        unit="one agent action",
        result="an agent progress observation",
        controller=lambda _path: _StopAfterOneController(),
    )


def _child_update(record) -> EpisodeUpdate:
    return EpisodeUpdate(
        record_id=record.episode_id,
        goal=record.goal,
        controller_input={"completed_children": 1},
    )


def _run_one_child(grain: Grain, *, run_id: str):
    root_goal = EpisodeGoal.root(
        objective={"task": "root"},
        result_contract={"kind": "answer"},
    )
    child_goal = EpisodeGoal.child(
        root_goal,
        objective={"task": "child"},
        result_contract={"kind": "answer"},
    )
    child = Episode(
        grain=grain,
        key="child",
        source=_SequenceSource(),
        request=EpisodeRequest(goal=child_goal),
        to_parent=_child_update,
    )
    root = Episode(
        grain=grain,
        key="root",
        source=_SequenceSource(child),
        request=EpisodeRequest(goal=root_goal),
    )
    record = root.run(
        Context(
            tree=EpisodeTree.recursive(grain, max_depth=2),
            run_id=run_id,
        )
    )
    return record


def test_declared_self_recursion_preserves_identity_goal_link_and_depth_bound():
    grain = _grain()

    first = _run_one_child(grain, run_id="recursive-run")
    second = _run_one_child(grain, run_id="recursive-run")

    first_unit = first.unit_records[0]
    first_child = first_unit.child
    second_child = second.unit_records[0].child
    assert first.path == (("agent", "root"),)
    assert first_child is not None
    assert second_child is not None
    assert first_child.path == (("agent", "root"), ("agent", "child"))
    assert first.episode_id == second.episode_id
    assert first_child.episode_id == second_child.episode_id
    assert first.episode_id != first_child.episode_id
    assert first_child.goal.parent_goal_id == first.goal.goal_id
    assert first_unit.episode_update is not None
    assert first_unit.episode_update.goal == first_child.goal

    context = Context(
        tree=EpisodeTree.recursive(grain, max_depth=2),
        run_id="depth-run",
    )
    root_scope = context.enter(grain, "root")
    child_scope = context.enter(grain, "child")
    assert not context.can_enter(grain)
    with pytest.raises(ValueError, match="depth bound 2 was reached"):
        context.enter(grain, "grandchild")
    context.leave(child_scope)
    context.leave(root_scope)

    unrelated_goal = EpisodeGoal.root(
        objective={"task": "unrelated"},
        result_contract={"kind": "answer"},
    )
    wrong_child = Episode(
        grain=grain,
        key="wrong-child",
        source=_SequenceSource(),
        request=EpisodeRequest(
            goal=EpisodeGoal.child(
                unrelated_goal,
                objective={"task": "child"},
                result_contract={"kind": "answer"},
            )
        ),
        to_parent=_child_update,
    )
    actual_goal = EpisodeGoal.root(
        objective={"task": "actual"},
        result_contract={"kind": "answer"},
    )
    actual_root = Episode(
        grain=grain,
        key="root",
        source=_SequenceSource(wrong_child),
        request=EpisodeRequest(goal=actual_goal),
    )
    with pytest.raises(
        ValueError,
        match="child Episode Goal must name the containing Episode Goal",
    ):
        actual_root.run(
            Context(
                tree=EpisodeTree.recursive(grain, max_depth=2),
                run_id="wrong-link-run",
            )
        )


def test_undeclared_recursive_cycles_remain_invalid():
    root = _grain()
    child = Grain(
        name="child",
        unit="one child action",
        result="one child observation",
        controller=lambda _path: _StopAfterOneController(),
    )

    with pytest.raises(ValueError, match="may self-nest only when declared"):
        EpisodeTree(root=root, children={root: (root,)})

    with pytest.raises(ValueError, match="require an explicit max_depth"):
        EpisodeTree(
            root=root,
            children={root: (root,)},
            self_nesting=(root.name,),
        )

    with pytest.raises(ValueError, match="require explicit recursive_edges"):
        EpisodeTree(
            root=root,
            children={root: (child,), child: (root,)},
        )


def test_explicit_bounded_type_cycle_supports_nested_creator_shape():
    creator = _grain()
    run = Grain(
        name="run",
        unit="one tested workflow",
        result="one measured outcome",
        controller=lambda _path: _StopAfterOneController(),
    )
    task = Grain(
        name="task",
        unit="one task action",
        result="one task observation",
        controller=lambda _path: _StopAfterOneController(),
    )
    tree = EpisodeTree(
        root=creator,
        children={
            creator: (run,),
            run: (task, creator),
            task: (task, creator),
        },
        self_nesting=(task.name,),
        recursive_edges=(
            (creator.name, run.name),
            (run.name, task.name),
            (run.name, creator.name),
            (task.name, creator.name),
        ),
        max_depth=4,
    )
    context = Context(tree=tree, run_id="creator-cycle")

    creator_scope = context.enter(creator, "root")
    run_scope = context.enter(run, "candidate")
    task_scope = context.enter(task, "task")
    assert context.can_enter(creator)
    nested_creator_scope = context.enter(creator, "nested")
    assert not context.can_enter(run)
    context.leave(nested_creator_scope)
    context.leave(task_scope)
    context.leave(run_scope)
    context.leave(creator_scope)
