"""Behavior contracts for explicitly recursive Episode topology."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from method_loop import (
    ChildEpisodeUnit,
    ClosedRecord,
    Context,
    Episode,
    EpisodeGoal,
    EpisodeRequest,
    EpisodeTree,
    Grain,
    Leaf,
    ReportContract,
)


# Since d75f85aa5b every child invocation needs a parent-owned report contract
# and a synthesis callback; the parent receives only the requested fields.
_REPORT = ReportContract(
    decision="whether the parent needs another child unit",
    measurements={},
    information={"value": "the child's result value"},
)


def _synthesize(result, completion, request):
    return {"value": result.value}


@dataclass(frozen=True)
class _Message(ClosedRecord):
    value: int

    def as_record(self):
        return {"value": self.value}


@dataclass(frozen=True)
class _Step:
    stop: bool = False
    requests_transition: bool = False


@dataclass(frozen=True)
class _State:
    observations: int
    stop: bool = False


class _CountingController:
    epoch = "initial"

    def __init__(self) -> None:
        self._observations = 0

    def observe(self, unit_label, value, *, is_root):
        self._observations += 1
        return _Step()

    def state(self):
        return _State(observations=self._observations)

    def transitioned(self, epoch):
        controller = _CountingController()
        controller.epoch = epoch
        return controller


class _SequenceSource:
    def __init__(self, *items) -> None:
        self._items = list(items)

    def next(self, view):
        if not self._items:
            return None
        return self._items.pop(0)


def _grain(name: str) -> Grain:
    return Grain(
        name=name,
        unit=f"one {name} unit",
        result=f"one {name} result",
        controller=lambda _path: _CountingController(),
    )


def _nested_run(*, run_id: str):
    root_grain = _grain("root")
    child_grain = _grain("child")
    root_goal = EpisodeGoal.for_grain(root_grain, objective={"task": "root"})
    child_goal = EpisodeGoal.for_grain(
        child_grain,
        parent=root_goal,
        objective={"task": "child"},
    )
    child = Episode(
        grain=child_grain,
        key="child",
        source=_SequenceSource(
            Leaf(
                unit=1,
                extract=lambda unit: unit,
                result=lambda unit, extracted: _Message(extracted),
                label="leaf",
            )
        ),
        request=EpisodeRequest(goal=child_goal, message=_Message(1), report_contract=_REPORT),
        build_result=lambda record: _Message(record.units_consumed),
    )
    root = Episode(
        grain=root_grain,
        key="root",
        source=_SequenceSource(
            ChildEpisodeUnit(
                synthesize_report=_synthesize,
                child=child,
                receive_result=lambda result, completion, request: _Message(
                    result.value
                ),
            )
        ),
        request=EpisodeRequest(goal=root_goal, message=_Message(0)),
        build_result=lambda record: _Message(record.units_consumed),
    )
    record = root.run(
        Context(
            tree=EpisodeTree(
                root=root_grain,
                children={root_grain: (child_grain,)},
            ),
            run_id=run_id,
        )
    )
    return record


def test_parent_owned_child_edge_preserves_identity_and_projection():
    first = _nested_run(run_id="recursive-run")
    second = _nested_run(run_id="recursive-run")

    unit = first.unit_records[0]
    child = unit.child
    assert child is not None
    assert child.path == (("root", "root"), ("child", "child"))
    assert first.episode_id == second.episode_id
    assert child.episode_id == second.unit_records[0].child.episode_id
    assert first.episode_id != child.episode_id
    assert child.goal.parent_goal_id == first.goal.goal_id
    assert unit.child_result == _Message(1)
    assert unit.controller_input == _Message(1)
    assert unit.episode_update.controller_input == _Message(1)


def test_child_goal_must_refine_the_containing_goal():
    root_grain = _grain("root")
    child_grain = _grain("child")
    actual_goal = EpisodeGoal.for_grain(root_grain, objective={"task": "actual"})
    unrelated_goal = EpisodeGoal.for_grain(
        root_grain,
        objective={"task": "unrelated"},
    )
    wrong_child = Episode(
        grain=child_grain,
        key="wrong-child",
        source=_SequenceSource(),
        request=EpisodeRequest(
            goal=EpisodeGoal.for_grain(
                child_grain,
                parent=unrelated_goal,
                objective={"task": "child"},
            ),
            message=_Message(1),
            report_contract=_REPORT,
        ),
        build_result=lambda record: _Message(record.units_consumed),
    )
    root = Episode(
        grain=root_grain,
        key="root",
        source=_SequenceSource(
            ChildEpisodeUnit(
                synthesize_report=_synthesize,
                child=wrong_child,
                receive_result=lambda result, completion, request: result,
            )
        ),
        request=EpisodeRequest(goal=actual_goal, message=_Message(0)),
        build_result=lambda record: _Message(record.units_consumed),
    )

    with pytest.raises(
        ValueError,
        match="child Episode Goal must name the containing Episode Goal",
    ):
        root.run(
            Context(
                tree=EpisodeTree(
                    root=root_grain,
                    children={root_grain: (child_grain,)},
                ),
                run_id="wrong-link-run",
            )
        )


def test_undeclared_recursive_cycles_remain_invalid():
    root = _grain("root")
    child = _grain("child")

    with pytest.raises(ValueError, match="may self-nest only when declared"):
        EpisodeTree(root=root, children={root: (root,)})

    recursive = EpisodeTree(
        root=root,
        children={root: (root,)},
        self_nesting=(root.name,),
    )
    assert recursive.allowed_children(root.name) == (root,)

    with pytest.raises(ValueError, match="require explicit recursive_edges"):
        EpisodeTree(
            root=root,
            children={root: (child,), child: (root,)},
        )
