"""The generic, nestable Episode method.

``Episode`` owns one loop: pull a unit, acquire it, send its binding-produced
value to the injected controller, publish a compact update, and then obey the
controller's structural stop decision.  It has no knowledge of columns,
incidence, rarefaction, hypervolume, or any other surface-specific result.

Nested communication and tracing are deliberately separate:

* :class:`EpisodeGoal` is the immutable objective at one Episode boundary.
* :class:`EpisodeRequest` carries that Goal plus one already-admitted closed record.
* :class:`ChildEpisodeUnit` owns separate credit and report projections for one child.
* :class:`EpisodeUpdate` separates credit, contracted findings and method-owned completion.
* :class:`EpisodeRecord` is the complete recursive trace retained for audit.

Sources and parent-unit hooks never receive a child's unprojected result or a
nested ``EpisodeRecord`` through the method's running view.  The closed child
result and recursive record are retained only in the completed audit trace.  A
child-owned ``on_close`` hook may publish that child's complete record for audit.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import (
    Any,
    Awaitable,
    Callable,
    Iterable,
    Mapping,
    Optional,
    Protocol,
    runtime_checkable,
)

from .identities import EpisodeRef, UnitRef
from .runtime import ControllerFactory, ControllerRuntime, Path, Scope
from .communication import ParentReport, ReportContract

__all__ = [
    "END_EXHAUSTED",
    "END_INCOMPLETE",
    "END_SOURCE_FAILED",
    "END_YIELD_STOP",
    "SOURCE_END_KINDS",
    "SOURCE_END_REASONS",
    "Acquirable",
    "ChildEpisodeUnit",
    "ClosedRecord",
    "Context",
    "Contribution",
    "Episode",
    "EpisodeCompletion",
    "EpisodeGoal",
    "GoalPreview",
    "GoalProposal",
    "GoalState",
    "EpisodeRecord",
    "EpisodeRequest",
    "EpisodeTree",
    "EpisodeUpdate",
    "EpisodeView",
    "EpochMutation",
    "Grain",
    "Leaf",
    "ResumeUnit",
    "SourceEnd",
    "UnitRecord",
    "UnitSource",
    "UnitView",
    "leaves",
]

END_EXHAUSTED = "exhausted"
END_YIELD_STOP = "yield_stop"
END_INCOMPLETE = "incomplete"
END_SOURCE_FAILED = "source_failed"
SOURCE_END_KINDS = (END_SOURCE_FAILED,)
SOURCE_END_REASONS = (END_SOURCE_FAILED,)
EPISODE_END_KINDS = (
    END_EXHAUSTED,
    END_YIELD_STOP,
    END_INCOMPLETE,
    END_SOURCE_FAILED,
)
EPISODE_END_REASONS = ("", *SOURCE_END_REASONS)


def _record_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "as_record"):
        return value.as_record()
    if isinstance(value, Mapping):
        return {str(name): _record_value(item) for name, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_record_value(item) for item in value]
    return repr(value)


def _freeze_json(value: Any) -> Any:
    """Return an immutable JSON value or raise at the Goal boundary."""

    def thaw(item: Any) -> Any:
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        if isinstance(item, Mapping):
            return {str(name): thaw(child) for name, child in item.items()}
        if isinstance(item, (tuple, list)):
            return [thaw(child) for child in item]
        raise TypeError(
            f"{type(item).__name__} is not a JSON-compatible Goal value"
        )

    try:
        normalized = json.loads(
            json.dumps(
                thaw(value),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
            )
        )
    except (TypeError, ValueError) as exc:
        raise TypeError("EpisodeGoal values must be JSON-compatible") from exc

    def freeze(item: Any) -> Any:
        if isinstance(item, dict):
            return MappingProxyType(
                {str(name): freeze(child) for name, child in item.items()}
            )
        if isinstance(item, list):
            return tuple(freeze(child) for child in item)
        return item

    return freeze(normalized)


class ClosedRecord(ABC):
    """An admitted boundary value with a JSON audit projection.

    The surface-owned admission function constructs this value before it enters
    the method loop. Requiring an object instead of a raw mapping prevents an
    unvalidated payload from being substituted at the Episode boundary while
    keeping the generic method independent of any surface's record class.
    """

    @abstractmethod
    def as_record(self) -> Mapping[str, Any]:
        """Return the closed record's JSON audit projection."""

        raise NotImplementedError

    def audit_identifiers(self) -> tuple[str, ...]:
        """Identify bookkeeping values that must stay out of a parent report.

        Records carrying artifact or correlation identities declare them here.
        Records containing only task values have no audit identities.
        """
        return ()


def _require_closed_record(value: Any, name: str) -> ClosedRecord:
    if not isinstance(value, ClosedRecord):
        raise TypeError(f"{name} must be an admitted ClosedRecord")
    record = value.as_record()
    if not isinstance(record, Mapping):
        raise TypeError(f"{name}.as_record() must return a mapping")
    _freeze_json(record)
    return value


@dataclass(frozen=True)
class EpisodeGoal:
    """The immutable objective and result contract for one Episode.

    A root Goal has no ``parent_goal_id``. A child Goal is made with
    :meth:`child`, which records the parent Goal it refines. The method loop
    validates that link before it runs a nested Episode.
    """

    objective: Any
    result_contract: Any
    task_context: Any = None
    parent_goal_id: str = ""
    goal_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.parent_goal_id, str):
            raise TypeError("EpisodeGoal.parent_goal_id must be a string")
        if self.parent_goal_id and self.task_context is None:
            raise ValueError(
                "a child EpisodeGoal must preserve its root task_context"
            )
        objective = _freeze_json(self.objective)
        result_contract = _freeze_json(self.result_contract)
        task_context = _freeze_json(
            self.task_context
            if self.task_context is not None
            else {
                "root_objective": _record_value(objective),
                "root_result_contract": _record_value(result_contract),
            }
        )
        body = {
            "objective": _record_value(objective),
            "result_contract": _record_value(result_contract),
            "task_context": _record_value(task_context),
            "parent_goal_id": self.parent_goal_id,
        }
        digest = hashlib.sha256(
            json.dumps(
                body,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        object.__setattr__(self, "objective", objective)
        object.__setattr__(self, "result_contract", result_contract)
        object.__setattr__(self, "task_context", task_context)
        object.__setattr__(self, "goal_id", f"goal_{digest[:24]}")

    @classmethod
    def root(
        cls,
        *,
        objective: Any,
        result_contract: Any,
        task_context: Any = None,
    ) -> "EpisodeGoal":
        return cls(
            objective=objective,
            result_contract=result_contract,
            task_context=task_context,
        )

    @classmethod
    def child(
        cls,
        parent: "EpisodeGoal",
        *,
        objective: Any,
        result_contract: Any,
    ) -> "EpisodeGoal":
        if not isinstance(parent, EpisodeGoal):
            raise TypeError("a child Goal requires an EpisodeGoal parent")
        return cls(
            objective=objective,
            result_contract=result_contract,
            task_context=parent.task_context,
            parent_goal_id=parent.goal_id,
        )

    @classmethod
    def for_grain(
        cls,
        grain: Any,
        *,
        objective: Any,
        parent: Optional["EpisodeGoal"] = None,
        result_contract: Any = None,
    ) -> "EpisodeGoal":
        """Build the standard Goal for a declared Grain.

        Bindings supply only the local objective. The Grain supplies the
        generic unit/result contract unless a binding has a more precise JSON
        contract to record.
        """

        if not isinstance(grain, Grain):
            raise TypeError("EpisodeGoal.for_grain requires a Grain")
        contract = (
            result_contract
            if result_contract is not None
            else {
                "grain": grain.name,
                "unit": grain.unit,
                "result": grain.result,
            }
        )
        if parent is None:
            return cls.root(objective=objective, result_contract=contract)
        return cls.child(
            parent,
            objective=objective,
            result_contract=contract,
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "parent_goal_id": self.parent_goal_id,
            "objective": _record_value(self.objective),
            "result_contract": _record_value(self.result_contract),
            "task_context": _record_value(self.task_context),
        }

    @classmethod
    def from_record(cls, value: Any) -> "EpisodeGoal":
        """Restore a Goal while revalidating its content-derived identity."""

        if not isinstance(value, Mapping):
            raise TypeError("EpisodeGoal state must be a mapping")
        expected = {
            "goal_id",
            "parent_goal_id",
            "objective",
            "result_contract",
            "task_context",
        }
        if set(value) != expected:
            raise ValueError("malformed EpisodeGoal state")
        goal = cls(
            objective=value["objective"],
            result_contract=value["result_contract"],
            task_context=value["task_context"],
            parent_goal_id=value["parent_goal_id"],
        )
        if value["goal_id"] != goal.goal_id:
            raise ValueError("EpisodeGoal goal_id does not match its persisted content")
        return goal


@dataclass(frozen=True)
class SourceEnd:
    """One source-owned stop selected from the method's closed vocabulary.

    Detailed errors belong in an audit artifact. They do not cross the
    steering boundary as free text.
    """

    kind: str

    def __post_init__(self) -> None:
        if self.kind not in SOURCE_END_KINDS:
            raise ValueError(f"unknown source end kind {self.kind!r}")


@dataclass(frozen=True)
class EpochMutation:
    """A source proposal for a new root-controller epoch."""

    epoch: str

    def __post_init__(self) -> None:
        if not isinstance(self.epoch, str) or not self.epoch.strip():
            raise ValueError("EpochMutation.epoch must be a non-empty stable id")


@dataclass(frozen=True)
class EpisodeRequest:
    """The Goal and admitted closed record supplied when an Episode opens."""

    goal: EpisodeGoal
    message: ClosedRecord
    report_contract: Optional[ReportContract] = None

    def __post_init__(self) -> None:
        if not isinstance(self.goal, EpisodeGoal):
            raise TypeError("EpisodeRequest.goal must be an EpisodeGoal")
        _require_closed_record(self.message, "EpisodeRequest.message")
        if self.report_contract is not None and not isinstance(self.report_contract, ReportContract):
            raise TypeError("EpisodeRequest.report_contract must be a ReportContract")

    def as_record(self) -> dict[str, Any]:
        return {
            "goal": self.goal.as_record(),
            "message": _record_value(self.message),
            "report_contract": None if self.report_contract is None else self.report_contract.as_record(),
        }


@dataclass(frozen=True)
class EpisodeCompletion:
    """Method-owned facts about how one child Episode ended."""

    ended_by: str
    end_reason: str
    units_consumed: int

    def __post_init__(self) -> None:
        if self.ended_by not in EPISODE_END_KINDS:
            raise ValueError("EpisodeCompletion.ended_by must be a method end kind")
        if self.end_reason not in EPISODE_END_REASONS:
            raise ValueError(
                "EpisodeCompletion.end_reason must be a closed reason code"
            )
        expected_reason = (
            self.ended_by if self.ended_by in SOURCE_END_REASONS else ""
        )
        if self.end_reason != expected_reason:
            raise ValueError(
                "EpisodeCompletion.end_reason does not match its end kind"
            )
        if (
            isinstance(self.units_consumed, bool)
            or not isinstance(self.units_consumed, int)
            or self.units_consumed < 0
        ):
            raise ValueError(
                "EpisodeCompletion.units_consumed must be a non-negative integer"
            )

    @classmethod
    def from_record(cls, record: "EpisodeRecord") -> "EpisodeCompletion":
        if not isinstance(record, EpisodeRecord):
            raise TypeError("EpisodeCompletion requires an EpisodeRecord")
        return cls(
            ended_by=record.ended_by,
            end_reason=record.end_reason,
            units_consumed=record.units_consumed,
        )

    def as_record(self) -> dict[str, Any]:
        return {
            "ended_by": self.ended_by,
            "end_reason": self.end_reason,
            "units_consumed": self.units_consumed,
        }


@dataclass(frozen=True)
class EpisodeUpdate:
    """Method-owned correlation of completion and parent projection."""

    record_id: str
    goal: EpisodeGoal
    completion: EpisodeCompletion
    controller_input: ClosedRecord
    report: ParentReport

    def __post_init__(self) -> None:
        if not isinstance(self.record_id, str) or not self.record_id:
            raise ValueError("EpisodeUpdate.record_id must be a non-empty string")
        if not isinstance(self.goal, EpisodeGoal):
            raise TypeError("EpisodeUpdate.goal must be an EpisodeGoal")
        if not isinstance(self.completion, EpisodeCompletion):
            raise TypeError("EpisodeUpdate.completion must be an EpisodeCompletion")
        _require_closed_record(
            self.controller_input,
            "EpisodeUpdate.controller_input",
        )
        if not isinstance(self.report, ParentReport):
            raise TypeError("EpisodeUpdate.report must be a synthesized ParentReport")

    def as_record(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "goal": self.goal.as_record(),
            "completion": self.completion.as_record(),
            "controller_input": _record_value(self.controller_input),
            "report": self.report.as_record(),
        }


@dataclass(frozen=True)
class GoalProposal:
    """A binding's proposed Goal result, before numerical control.

    The proposal carries no write capability. Only the Goal state installed on
    :class:`Context` can preview it and, after the controller transition,
    commit the identities selected by that transition.
    """

    payload: Any


@dataclass(frozen=True)
class GoalPreview:
    """A non-mutating Goal projection prepared for one controller step."""

    controller_input: Any
    candidate_result_ids: tuple[str, ...]
    state_id: str
    no_commit_result: Any = None
    token: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.state_id, str) or not self.state_id:
            raise ValueError("GoalPreview.state_id must be a non-empty string")
        if not isinstance(self.candidate_result_ids, tuple):
            raise TypeError("GoalPreview.candidate_result_ids must be a tuple")
        if any(
            not isinstance(result_id, str) or not result_id
            for result_id in self.candidate_result_ids
        ):
            raise ValueError("Goal result identities must be non-empty strings")
        if len(set(self.candidate_result_ids)) != len(self.candidate_result_ids):
            raise ValueError("Goal result identities must be unique")


@runtime_checkable
class GoalState(Protocol):
    """The method-owned mutable Goal boundary.

    ``preview`` must not mutate state. ``commit`` is called only after the
    numerical controller returns a non-empty subset of the previewed result
    identities.
    """

    @property
    def state_id(self) -> str: ...

    def preview(self, proposal: GoalProposal, unit_ref: UnitRef) -> GoalPreview: ...

    def commit(
        self,
        preview: GoalPreview,
        result_ids: tuple[str, ...],
    ) -> Any: ...


@dataclass(frozen=True)
class Contribution:
    """Only projected steering state visible to a containing Episode hook."""

    controller_input: Any
    episode_update: Optional[EpisodeUpdate] = None
    goal_result: Any = None


@dataclass(frozen=True)
class _AcquiredUnit:
    contribution: Contribution
    child_record: Optional["EpisodeRecord"] = None
    child_result: Optional[ClosedRecord] = None
    goal_proposal: Optional[GoalProposal] = None

    def __post_init__(self) -> None:
        if not isinstance(self.contribution, Contribution):
            raise TypeError("an acquired unit requires a Contribution")
        if (self.child_record is None) != (self.child_result is None):
            raise ValueError(
                "a nested acquisition must retain both its child record and "
                "closed child result"
            )
        if self.child_result is not None:
            _require_closed_record(self.child_result, "child_result")


@dataclass(frozen=True)
class UnitRecord:
    """The full trace of one acquired unit."""

    unit_label: str
    controller_input: Any
    controller_step: Any
    epoch: str
    unit_ref: UnitRef
    episode_update: Optional[EpisodeUpdate] = None
    child: Optional["EpisodeRecord"] = None
    child_result: Optional[ClosedRecord] = None
    goal_result: Any = None

    @property
    def unit_id(self) -> str:
        return self.unit_ref.unit_id

    def as_record(self) -> dict[str, Any]:
        return {
            "unit_label": self.unit_label,
            "unit_ref": self.unit_ref.as_record(),
            "unit_id": self.unit_id,
            "epoch": self.epoch,
            "controller_input": _record_value(self.controller_input),
            "controller_step": _record_value(self.controller_step),
            "episode_update": (
                self.episode_update.as_record()
                if self.episode_update is not None
                else None
            ),
            "goal_result": _record_value(self.goal_result),
            "child": self.child.as_record() if self.child is not None else None,
            "child_result": (
                _record_value(self.child_result)
                if self.child_result is not None
                else None
            ),
        }


@dataclass(frozen=True)
class UnitView:
    """The per-unit information visible to a post-controller hook."""

    unit_label: str
    controller_input: Any
    controller_step: Any
    epoch: str
    unit_ref: UnitRef
    episode_update: Optional[EpisodeUpdate] = None
    goal_result: Any = None


@dataclass(frozen=True)
class ResumeUnit:
    """One previously completed input restored at a durable boundary."""

    label: str
    controller_input: Any

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("ResumeUnit.label must be a non-empty string")


@dataclass(frozen=True)
class EpisodeRecord:
    """The complete recursive trace of one Episode."""

    scope_level: str
    scope_key: str
    units_consumed: int
    ended_by: str
    unit_records: tuple[UnitRecord, ...]
    controller_state: Any
    request: EpisodeRequest
    path: Path = ()
    end_reason: str = ""
    episode_ref: Optional[EpisodeRef] = None

    @property
    def goal(self) -> EpisodeGoal:
        return self.request.goal

    @property
    def episode_id(self) -> str:
        return self.episode_ref.episode_id if self.episode_ref is not None else ""

    @property
    def run_id(self) -> str:
        return self.episode_ref.run_id if self.episode_ref is not None else ""

    def as_record(self) -> dict[str, Any]:
        return {
            "scope_level": self.scope_level,
            "scope_key": self.scope_key,
            "path": [list(item) for item in self.path],
            "episode_ref": (
                self.episode_ref.as_record() if self.episode_ref else None
            ),
            "episode_id": self.episode_id,
            "run_id": self.run_id,
            "goal": self.goal.as_record(),
            "request": self.request.as_record(),
            "units_consumed": self.units_consumed,
            "ended_by": self.ended_by,
            "end_reason": self.end_reason,
            "controller_state": _record_value(self.controller_state),
            "units": [unit.as_record() for unit in self.unit_records],
        }


@dataclass(frozen=True)
class Grain:
    """One loop level and the controller function bound to that level."""

    name: str
    unit: str
    result: str
    controller: ControllerFactory

    def __post_init__(self) -> None:
        for field_name in ("name", "unit", "result"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Grain.{field_name} must be a non-empty sentence")
        if not callable(self.controller):
            raise TypeError("Grain.controller must be a controller function")


def _episode_tree_options(
    root: Any,
    self_nesting: Any,
    recursive_edges: Any,
) -> tuple[set[str], set[tuple[str, str]]]:
    """Validate tree-wide recursion declarations."""

    if not isinstance(root, Grain):
        raise TypeError("EpisodeTree.root must be a Grain")
    if not isinstance(self_nesting, tuple) or any(
        not isinstance(name, str) or not name for name in self_nesting
    ):
        raise TypeError("EpisodeTree.self_nesting must be a tuple of grain names")
    if len(set(self_nesting)) != len(self_nesting):
        raise ValueError("EpisodeTree.self_nesting contains duplicates")
    if not isinstance(recursive_edges, tuple):
        raise TypeError("EpisodeTree.recursive_edges must be a tuple")
    normalized_edges: set[tuple[str, str]] = set()
    for edge in recursive_edges:
        if (
            not isinstance(edge, tuple)
            or len(edge) != 2
            or any(not isinstance(name, str) or not name for name in edge)
        ):
            raise TypeError(
                "EpisodeTree.recursive_edges must contain grain-name pairs"
            )
        normalized_edges.add(edge)
    if len(normalized_edges) != len(recursive_edges):
        raise ValueError("EpisodeTree.recursive_edges contains duplicates")
    normalized_edges.update((name, name) for name in self_nesting)
    return set(self_nesting), normalized_edges


def _declare_tree_grain(by_name: dict[str, Grain], grain: Any, role: str) -> Grain:
    if not isinstance(grain, Grain):
        raise TypeError(f"EpisodeTree {role} must be Grain values")
    known = by_name.get(grain.name)
    if known is not None and known != grain:
        raise ValueError(f"grain {grain.name!r} has conflicting declarations")
    by_name[grain.name] = grain
    return grain


def _normalize_tree_children(
    children: Mapping[Grain, Iterable[Grain]],
    recursive_names: set[str],
    by_name: dict[str, Grain],
) -> dict[Grain, tuple[Grain, ...]]:
    normalized: dict[Grain, tuple[Grain, ...]] = {}
    for raw_parent, raw_children in children.items():
        parent = _declare_tree_grain(by_name, raw_parent, "parent keys")
        declared_children = tuple(raw_children)
        child_names: set[str] = set()
        for raw_child in declared_children:
            if not isinstance(raw_child, Grain):
                raise TypeError("EpisodeTree children must be Grain values")
            if raw_child.name in child_names:
                raise ValueError(
                    f"grain {raw_child.name!r} is listed twice under {parent.name!r}"
                )
            child_names.add(raw_child.name)
            child = _declare_tree_grain(by_name, raw_child, "children")
            if child.name == parent.name:
                if child.name not in recursive_names:
                    raise ValueError(
                        f"grain {child.name!r} may self-nest only when "
                        "declared in EpisodeTree.self_nesting"
                    )
                continue
        normalized[parent] = declared_children
    return normalized


def _tree_edges(
    normalized: Mapping[Grain, tuple[Grain, ...]],
) -> set[tuple[str, str]]:
    return {
        (parent.name, child.name)
        for parent, children in normalized.items()
        for child in children
    }


def _cyclic_tree_edges(
    normalized: Mapping[Grain, tuple[Grain, ...]],
) -> set[tuple[str, str]]:
    adjacency = {
        parent.name: {child.name for child in children}
        for parent, children in normalized.items()
    }

    def reaches(start: str, target: str) -> bool:
        frontier = [start]
        seen: set[str] = set()
        while frontier:
            current = frontier.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            frontier.extend(adjacency.get(current, ()))
        return False

    return {
        (parent, child)
        for parent, children in adjacency.items()
        for child in children
        if reaches(child, parent)
    }


def _reachable_tree_grains(
    root: Grain,
    normalized: Mapping[Grain, tuple[Grain, ...]],
) -> set[str]:
    reachable = {root.name}
    frontier = [root]
    while frontier:
        parent = frontier.pop()
        for child in normalized.get(parent, ()):
            if child.name not in reachable:
                reachable.add(child.name)
                frontier.append(child)
    return reachable


def _validate_tree_graph(
    root: Grain,
    normalized: Mapping[Grain, tuple[Grain, ...]],
    by_name: Mapping[str, Grain],
    recursive_names: set[str],
    recursive_edges: set[tuple[str, str]],
) -> None:
    unreachable = set(by_name) - _reachable_tree_grains(root, normalized)
    if unreachable:
        raise ValueError(
            f"EpisodeTree has unreachable parent grains: {sorted(unreachable)}"
        )
    unknown_recursive = recursive_names - set(by_name)
    if unknown_recursive:
        raise ValueError(
            "EpisodeTree.self_nesting names undeclared grains: "
            f"{sorted(unknown_recursive)}"
        )
    self_edges = {
        child.name
        for parent, declared_children in normalized.items()
        for child in declared_children
        if parent.name == child.name
    }
    missing_self_edges = recursive_names - self_edges
    if missing_self_edges:
        raise ValueError(
            "self-nesting grains must declare their own Grain as a child: "
            f"{sorted(missing_self_edges)}"
        )
    actual_edges = _tree_edges(normalized)
    undeclared_edges = recursive_edges - actual_edges
    if undeclared_edges:
        raise ValueError(
            "EpisodeTree.recursive_edges names undeclared edges: "
            f"{sorted(undeclared_edges)}"
        )
    missing_recursive = _cyclic_tree_edges(normalized) - recursive_edges
    if missing_recursive:
        raise ValueError(
            "cyclic EpisodeTree edges require explicit recursive_edges: "
            f"{sorted(missing_recursive)}"
        )


@dataclass(frozen=True)
class EpisodeTree:
    """The Episode types allowed beneath each parent Episode type.

    Runtime Episode instances still form an ordinary tree of paths. This
    declaration describes which *types* may occupy each child position, so a
    parent may choose among several child bindings without weakening nesting
    validation. Type-level cycles are allowed only when every cyclic edge is
    declared. Each Episode instance applies its own numerical progress
    controller to determine when its loop has yielded enough.
    """

    root: Grain
    children: Mapping[Grain, Iterable[Grain]] = field(default_factory=dict)
    self_nesting: tuple[str, ...] = ()
    recursive_edges: tuple[tuple[str, str], ...] = ()
    def __post_init__(self) -> None:
        recursive_names, recursive_edges = _episode_tree_options(
            self.root,
            self.self_nesting,
            self.recursive_edges,
        )
        by_name: dict[str, Grain] = {self.root.name: self.root}
        normalized = _normalize_tree_children(
            self.children,
            recursive_names,
            by_name,
        )
        _validate_tree_graph(
            self.root,
            normalized,
            by_name,
            recursive_names,
            recursive_edges,
        )

        object.__setattr__(self, "children", normalized)
        object.__setattr__(self, "_by_name", by_name)
        object.__setattr__(
            self,
            "recursive_edges",
            tuple(sorted(recursive_edges)),
        )

    @classmethod
    def linear(cls, grains: Iterable[Grain]) -> "EpisodeTree":
        """Build the declaration for a single linear path."""

        ordered = tuple(grains)
        if not ordered:
            raise ValueError("a linear EpisodeTree needs at least one Grain")
        return cls(
            root=ordered[0],
            children={
                parent: (child,)
                for parent, child in zip(ordered, ordered[1:])
            },
        )

    @classmethod
    def recursive(cls, grain: Grain) -> "EpisodeTree":
        """Declare one reusable Episode type that may construct itself.

        Every instance owns its own controller and stopping rule.
        """

        return cls(
            root=grain,
            children={grain: (grain,)},
            self_nesting=(grain.name,),
        )

    def allowed_children(self, parent_name: str) -> tuple[Grain, ...]:
        parent = self._by_name.get(str(parent_name))
        if parent is None:
            return ()
        return tuple(self.children.get(parent, ()))


@dataclass(frozen=True)
class EpisodeView:
    """The compact running state visible to one Episode's source."""

    grain: Grain
    key: str
    path: Path
    units_consumed: int
    updates: tuple[EpisodeUpdate, ...]
    controller_state: Any
    episode_ref: EpisodeRef
    request: EpisodeRequest

    @property
    def goal(self) -> EpisodeGoal:
        return self.request.goal

    @property
    def child_reports(self) -> tuple[ParentReport, ...]:
        return tuple(update.report for update in self.updates)

    def model_inputs(self, declared_inputs: Mapping[str, Any], *, reports: tuple[ParentReport, ...]) -> dict[str, Any]:
        """Deliver only the parent-selected, admitted direct-child reports."""
        return _model_inputs(declared_inputs, self.child_reports, reports)


def _model_inputs(declared_inputs, available, selected):
    if not isinstance(declared_inputs, Mapping) or "child_reports" in declared_inputs:
        raise ValueError("child_reports is owned by the method's reporting boundary")
    if not isinstance(selected, tuple) or any(
        not any(report is admitted for admitted in available) for report in selected
    ):
        raise ValueError("model inputs require reports admitted for this parent")
    inputs = _record_value(_freeze_json(declared_inputs))
    for report in available:
        report.validate_model_inputs(inputs)
    return {
        **inputs,
        "child_reports": [report.as_record() for report in selected],
    }


class UnitSource(Protocol):
    """Return the next unit, ``None``, or a typed :class:`SourceEnd`."""

    def next(self, view: EpisodeView) -> Any: ...


@runtime_checkable
class Acquirable(Protocol):
    """Implemented by :class:`Leaf` and parent-owned ChildEpisodeUnit."""

    label: str

    def acquire(self, ctx: "Context") -> _AcquiredUnit: ...

    async def acquire_async(self, ctx: "Context") -> _AcquiredUnit: ...


def _leaf_acquisition(
    unit: Any,
    extract: Callable[[Any], Any],
    accept: Optional[Callable[[Any, Any], Any]],
    result: Callable[[Any, Any], Any],
) -> _AcquiredUnit:
    extracted = extract(unit)
    accepted = accept(unit, extracted) if accept is not None else extracted
    projected = result(unit, accepted)
    if isinstance(projected, GoalProposal):
        return _AcquiredUnit(
            contribution=Contribution(controller_input=None),
            goal_proposal=projected,
        )
    return _AcquiredUnit(Contribution(controller_input=projected))


async def _leaf_acquisition_async(
    unit: Any,
    extract: Callable[[Any], Any],
    accept: Optional[Callable[[Any, Any], Any]],
    result: Callable[[Any, Any], Any],
) -> _AcquiredUnit:
    extracted = extract(unit)
    if inspect.isawaitable(extracted):
        extracted = await extracted
    accepted = accept(unit, extracted) if accept is not None else extracted
    if inspect.isawaitable(accepted):
        accepted = await accepted
    projected = result(unit, accepted)
    if inspect.isawaitable(projected):
        projected = await projected
    if isinstance(projected, GoalProposal):
        return _AcquiredUnit(
            contribution=Contribution(controller_input=None),
            goal_proposal=projected,
        )
    return _AcquiredUnit(Contribution(controller_input=projected))


@dataclass(frozen=True)
class Leaf:
    """A raw unit bound to extraction, acceptance, and result projection."""

    unit: Any
    extract: Callable[[Any], Any]
    result: Callable[[Any, Any], Any]
    label: str
    accept: Optional[Callable[[Any, Any], Any]] = None

    def acquire(self, ctx: "Context") -> _AcquiredUnit:
        return _leaf_acquisition(self.unit, self.extract, self.accept, self.result)

    async def acquire_async(self, ctx: "Context") -> _AcquiredUnit:
        return await _leaf_acquisition_async(
            self.unit, self.extract, self.accept, self.result
        )


@dataclass(frozen=True)
class Episode:
    """One instance of one Grain, composed from swappable parts."""

    grain: Grain
    key: str
    source: UnitSource
    request: EpisodeRequest
    build_result: Callable[
        [EpisodeRecord], ClosedRecord | Awaitable[ClosedRecord]
    ]
    on_unit: Optional[Callable[[Any, Contribution, UnitView], Any]] = None
    on_close: Optional[Callable[[EpisodeRecord], Any]] = None
    resume_units: tuple[ResumeUnit, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.grain, Grain):
            raise TypeError(
                f"Episode.grain must be a Grain, got {type(self.grain).__name__}"
            )
        if not isinstance(self.key, str) or not self.key:
            raise ValueError("Episode.key must be a non-empty string")
        if not hasattr(self.source, "next"):
            raise TypeError(
                "Episode.source must implement UnitSource.next(view); wrap a "
                "plain iterable with leaves(...)"
            )
        if not callable(self.build_result):
            raise TypeError("Episode.build_result must be callable")
        if self.on_close is not None and not callable(self.on_close):
            raise TypeError("Episode.on_close must be callable")
        if not isinstance(self.request, EpisodeRequest):
            raise TypeError("Episode.request must be an EpisodeRequest")
        if not isinstance(self.resume_units, tuple) or any(
            not isinstance(unit, ResumeUnit) for unit in self.resume_units
        ):
            raise TypeError("Episode.resume_units must contain ResumeUnit values")

    @property
    def label(self) -> str:
        return self.key

    @property
    def goal(self) -> EpisodeGoal:
        return self.request.goal

    @classmethod
    def identity(
        cls,
        ctx: "Context",
        grain: Grain,
        key: str,
        *,
        parent_path: Path = (),
    ) -> EpisodeRef:
        path = tuple(parent_path) + ((grain.name, str(key)),)
        return EpisodeRef(run_id=ctx.require_run_id(), path=path)

    def run(self, ctx: "Context") -> EpisodeRecord:
        self._validate_position(ctx)
        if not ctx.path and not ctx.has_run_id:
            ctx.bind_run_id(self.key)
        scope = ctx.enter(self.grain, self.key)
        ctx._active_episodes[scope] = self
        try:
            record = self._run_loop(ctx, scope)
            if self.on_close is not None:
                result = self.on_close(record)
                if inspect.isawaitable(result):
                    raise TypeError(
                        "an async Episode.on_close callback requires run_async()"
                    )
            return record
        finally:
            ctx.leave(scope)

    async def run_async(self, ctx: "Context") -> EpisodeRecord:
        self._validate_position(ctx)
        if not ctx.path and not ctx.has_run_id:
            ctx.bind_run_id(self.key)
        scope = ctx.enter(self.grain, self.key)
        ctx._active_episodes[scope] = self
        try:
            record = await self._run_loop_async(ctx, scope)
            if self.on_close is not None:
                result = self.on_close(record)
                if inspect.isawaitable(result):
                    await result
            return record
        finally:
            ctx.leave(scope)

    async def run_unit_async(self, ctx: "Context", *, expected_label: str, starting_unit_index: int = 0) -> UnitRecord:
        """Observe one identified unit, without closing the containing Episode.

        Experimental stepping shares acquisition, goal commitment, controller
        advancement and hooks with the ordinary loop. It does not invent a
        stopping decision or call the Episode's result/close callbacks.
        """
        if self.resume_units:
            raise ValueError("unit stepping requires coherent source restoration, not controller-only resume_units")
        if type(starting_unit_index) is not int or starting_unit_index < 0:
            raise ValueError("unit stepping requires a nonnegative restored position")
        self._validate_position(ctx)
        if not ctx.path and not ctx.has_run_id:
            ctx.bind_run_id(self.key)
        scope = ctx.enter(self.grain, self.key)
        ctx._active_episodes[scope] = self
        try:
            item = self.source.next(self._view(ctx, scope, [], unit_offset=starting_unit_index))
            if inspect.isawaitable(item):
                item = await item
            if item is None or isinstance(item, SourceEnd):
                raise ValueError("the selected unit is unavailable at this source boundary")
            if item.label != expected_label:
                raise ValueError("the source selected a different unit; no replacement is acquired")
            records: list[UnitRecord] = []
            await self._acquire_unit_async(ctx, scope, records, item, unit_offset=starting_unit_index)
            return records[0]
        finally:
            ctx.leave(scope)

    def _view(
        self,
        ctx: "Context",
        scope: Scope,
        records: list[UnitRecord],
        *, unit_offset: int = 0,
    ) -> EpisodeView:
        return EpisodeView(
            grain=self.grain,
            key=self.key,
            path=scope,
            units_consumed=unit_offset + len(records),
            updates=tuple(ctx._child_updates.get(scope, ())),
            controller_state=ctx.runtime.state(scope),
            episode_ref=EpisodeRef(run_id=ctx.require_run_id(), path=scope),
            request=self.request,
        )

    def _validate_position(self, ctx: "Context") -> None:
        if ctx.path and not self.goal.parent_goal_id:
            raise ValueError("a nested Episode must carry a child Goal")
        if not ctx.path and self.goal.parent_goal_id:
            raise ValueError("a root Episode Goal may not name a parent Goal")
        parent = ctx._active_episodes.get(ctx.path)
        if parent is not None:
            if not isinstance(self.request.report_contract, ReportContract):
                raise ValueError("a child requires its parent's reporting contract before execution")
            if not ctx._child_edges or ctx._child_edges[-1] is not self:
                raise ValueError("nested execution requires the parent's ChildEpisodeUnit reporting boundary")
            if self.goal.parent_goal_id != parent.goal.goal_id:
                raise ValueError("child Goal does not belong to the active parent Episode")

    def _validate_child(self, item: Any) -> None:
        if isinstance(item, Episode):
            raise TypeError(
                "a nested Episode must be carried by a parent-owned "
                "ChildEpisodeUnit"
            )
        if not isinstance(item, ChildEpisodeUnit):
            return
        if item.child.goal.parent_goal_id != self.goal.goal_id:
            raise ValueError(
                "a child Episode Goal must name the containing Episode Goal"
            )

    def _record(
        self,
        ctx: "Context",
        scope: Scope,
        records: list[UnitRecord],
        ended_by: str,
        end_reason: str,
    ) -> EpisodeRecord:
        path = scope
        return EpisodeRecord(
            scope_level=path[-1][0],
            scope_key=path[-1][1],
            units_consumed=len(records),
            ended_by=ended_by,
            unit_records=tuple(records),
            controller_state=ctx.runtime.state(scope),
            path=path,
            end_reason=end_reason,
            episode_ref=EpisodeRef(run_id=ctx.require_run_id(), path=path),
            request=self.request,
        )

    def _append_record(
        self,
        ctx: "Context",
        scope: Scope,
        records: list[UnitRecord],
        label: str,
        acquired: _AcquiredUnit,
        *, unit_offset: int = 0,
    ) -> tuple[UnitRecord, UnitView, Contribution]:
        unit_ref = UnitRef(
            EpisodeRef(run_id=ctx.require_run_id(), path=scope).episode_id,
            unit_offset + len(records),
        )
        controller_input = acquired.contribution.controller_input
        goal_preview: Optional[GoalPreview] = None
        if acquired.goal_proposal is not None:
            goal_preview = ctx._preview_goal(acquired.goal_proposal, unit_ref)
            controller_input = goal_preview.controller_input
        step = ctx.runtime.advance(scope, label, controller_input)
        goal_result = acquired.contribution.goal_result
        if goal_preview is not None:
            result_ids = getattr(step, "goal_commit_ids", None)
            if result_ids is None:
                raise TypeError(
                    "a controller step handling a Goal proposal must expose "
                    "goal_commit_ids"
                )
            result_ids = tuple(str(result_id) for result_id in result_ids)
            candidates = set(goal_preview.candidate_result_ids)
            unknown = sorted(set(result_ids) - candidates)
            if unknown:
                raise ValueError(
                    "controller selected Goal identities absent from its "
                    f"preview: {unknown}"
                )
            goal_result = (
                ctx._commit_goal(goal_preview, result_ids)
                if result_ids
                else goal_preview.no_commit_result
            )
        contribution = Contribution(
            controller_input=controller_input,
            episode_update=acquired.contribution.episode_update,
            goal_result=goal_result,
        )
        record = UnitRecord(
            unit_label=label,
            controller_input=controller_input,
            controller_step=step,
            epoch=ctx.runtime.epoch(scope),
            unit_ref=unit_ref,
            episode_update=acquired.contribution.episode_update,
            child=acquired.child_record,
            child_result=acquired.child_result,
            goal_result=goal_result,
        )
        view = UnitView(
            unit_label=label,
            controller_input=record.controller_input,
            controller_step=record.controller_step,
            epoch=record.epoch,
            unit_ref=record.unit_ref,
            episode_update=record.episode_update,
            goal_result=goal_result,
        )
        records.append(record)
        return record, view, contribution

    def _restore_units(
        self,
        ctx: "Context",
        scope: Scope,
    ) -> list[UnitRecord]:
        records: list[UnitRecord] = []
        for prior in self.resume_units:
            self._append_record(
                ctx,
                scope,
                records,
                prior.label,
                _AcquiredUnit(Contribution(prior.controller_input)),
            )
        return records

    @staticmethod
    def _state_stops(state: Any) -> bool:
        stop = getattr(state, "stop", None)
        if not isinstance(stop, bool):
            raise TypeError("a controller state must expose a boolean stop")
        return stop

    def _stop_end(
        self,
        ctx: "Context",
        scope: Scope,
        records: list[UnitRecord],
        step: Any,
    ) -> tuple[Scope, Optional[str]]:
        if step.requests_transition and len(scope) == 1:
            proposal = getattr(self.source, "next_epoch", None)
            mutation = proposal(self._view(ctx, scope, records)) if proposal else None
            if isinstance(mutation, EpochMutation):
                return ctx.transition(scope, mutation), None
            return scope, END_INCOMPLETE
        return scope, END_YIELD_STOP

    async def _stop_end_async(
        self,
        ctx: "Context",
        scope: Scope,
        records: list[UnitRecord],
        step: Any,
    ) -> tuple[Scope, Optional[str]]:
        if step.requests_transition and len(scope) == 1:
            proposal = getattr(self.source, "next_epoch", None)
            mutation = proposal(self._view(ctx, scope, records)) if proposal else None
            if inspect.isawaitable(mutation):
                mutation = await mutation
            if isinstance(mutation, EpochMutation):
                return ctx.transition(scope, mutation), None
            return scope, END_INCOMPLETE
        return scope, END_YIELD_STOP

    def _run_loop(self, ctx: "Context", scope: Scope) -> EpisodeRecord:
        records = self._restore_units(ctx, scope)
        ended_by, end_reason = END_EXHAUSTED, ""
        if records and self._state_stops(ctx.runtime.state(scope)):
            return self._record(ctx, scope, records, END_YIELD_STOP, "")
        while True:
            item = self.source.next(self._view(ctx, scope, records))
            if item is None:
                break
            if isinstance(item, SourceEnd):
                ended_by, end_reason = item.kind, item.kind
                break
            self._validate_child(item)
            acquired = item.acquire(ctx)
            if not isinstance(acquired, _AcquiredUnit):
                raise TypeError("Acquirable.acquire() returned an invalid result")
            _, unit_view, contribution = self._append_record(
                ctx, scope, records, item.label, acquired
            )
            if self.on_unit is not None:
                self.on_unit(item, contribution, unit_view)
            step = unit_view.controller_step
            if step.stop:
                scope, end = self._stop_end(ctx, scope, records, step)
                if end is None:
                    continue
                ended_by = end
                break
        return self._record(ctx, scope, records, ended_by, end_reason)

    async def _run_loop_async(
        self,
        ctx: "Context",
        scope: Scope,
    ) -> EpisodeRecord:
        records = self._restore_units(ctx, scope)
        ended_by, end_reason = END_EXHAUSTED, ""
        if records and self._state_stops(ctx.runtime.state(scope)):
            return self._record(ctx, scope, records, END_YIELD_STOP, "")
        while True:
            item = self.source.next(self._view(ctx, scope, records))
            if inspect.isawaitable(item):
                item = await item
            if item is None:
                break
            if isinstance(item, SourceEnd):
                ended_by, end_reason = item.kind, item.kind
                break
            step = await self._acquire_unit_async(ctx, scope, records, item)
            if step.stop:
                scope, end = await self._stop_end_async(
                    ctx, scope, records, step
                )
                if end is None:
                    continue
                ended_by = end
                break
        return self._record(ctx, scope, records, ended_by, end_reason)

    async def _acquire_unit_async(self, ctx, scope, records, item, *, unit_offset=0):
        self._validate_child(item)
        acquired = item.acquire_async(ctx)
        if inspect.isawaitable(acquired):
            acquired = await acquired
        if not isinstance(acquired, _AcquiredUnit):
            raise TypeError("Acquirable.acquire_async() returned an invalid result")
        _, unit_view, contribution = self._append_record(
            ctx, scope, records, item.label, acquired, unit_offset=unit_offset
        )
        if self.on_unit is not None:
            result = self.on_unit(item, contribution, unit_view)
            if inspect.isawaitable(result):
                await result
        return unit_view.controller_step


@dataclass(frozen=True)
class ChildEpisodeUnit:
    """A parent-owned invocation edge around one child Episode.

    The child owns ``build_result``. The parent owns separate callbacks for
    credit projection and report synthesis. The unprojected result is retained
    in the audit record; model input delivery uses the synthesized report.
    """

    child: Episode
    receive_result: Callable[
        [ClosedRecord, EpisodeCompletion, EpisodeRequest],
        ClosedRecord | Awaitable[ClosedRecord],
    ]
    synthesize_report: Callable[
        [ClosedRecord, EpisodeCompletion, EpisodeRequest],
        Mapping[str, Any] | Awaitable[Mapping[str, Any]],
    ]

    def __post_init__(self) -> None:
        if not isinstance(self.child, Episode):
            raise TypeError("ChildEpisodeUnit.child must be an Episode")
        if not callable(self.receive_result):
            raise TypeError("ChildEpisodeUnit.receive_result must be callable")
        if not callable(self.synthesize_report):
            raise TypeError("ChildEpisodeUnit.synthesize_report must be callable")
        if not isinstance(self.child.request.report_contract, ReportContract):
            raise TypeError("a child invocation requires a parent-owned reporting contract")

    def _admit_report(self, value, child_result, record):
        identifiers = tuple(dict.fromkeys((
            record.episode_id,
            record.goal.goal_id,
            *self.child.request.message.audit_identifiers(),
            *child_result.audit_identifiers(),
        )))
        return self.child.request.report_contract.admit(value, audit_identifiers=identifiers)

    @property
    def label(self) -> str:
        return self.child.label

    def _finish(self, record: EpisodeRecord) -> _AcquiredUnit:
        child_result = self.child.build_result(record)
        if inspect.isawaitable(child_result):
            raise TypeError(
                "an async Episode.build_result callback requires acquire_async()"
            )
        child_result = _require_closed_record(
            child_result,
            "Episode.build_result()",
        )
        completion = EpisodeCompletion.from_record(record)
        controller_input = self.receive_result(
            child_result,
            completion,
            self.child.request,
        )
        if inspect.isawaitable(controller_input):
            raise TypeError(
                "an async ChildEpisodeUnit.receive_result callback requires "
                "acquire_async()"
            )
        controller_input = _require_closed_record(
            controller_input,
            "ChildEpisodeUnit.receive_result()",
        )
        report = self.synthesize_report(child_result, completion, self.child.request)
        if inspect.isawaitable(report):
            raise TypeError("an async report synthesis requires acquire_async()")
        update = EpisodeUpdate(
            record_id=record.episode_id,
            goal=record.goal,
            completion=completion,
            controller_input=controller_input,
            report=self._admit_report(report, child_result, record),
        )
        return _AcquiredUnit(
            contribution=Contribution(
                controller_input=controller_input,
                episode_update=update,
            ),
            child_record=record,
            child_result=child_result,
        )

    async def _finish_async(self, record: EpisodeRecord) -> _AcquiredUnit:
        child_result = self.child.build_result(record)
        if inspect.isawaitable(child_result):
            child_result = await child_result
        child_result = _require_closed_record(
            child_result,
            "Episode.build_result()",
        )
        completion = EpisodeCompletion.from_record(record)
        controller_input = self.receive_result(
            child_result,
            completion,
            self.child.request,
        )
        if inspect.isawaitable(controller_input):
            controller_input = await controller_input
        controller_input = _require_closed_record(
            controller_input,
            "ChildEpisodeUnit.receive_result()",
        )
        report = self.synthesize_report(child_result, completion, self.child.request)
        if inspect.isawaitable(report):
            report = await report
        update = EpisodeUpdate(
            record_id=record.episode_id,
            goal=record.goal,
            completion=completion,
            controller_input=controller_input,
            report=self._admit_report(report, child_result, record),
        )
        return _AcquiredUnit(
            contribution=Contribution(
                controller_input=controller_input,
                episode_update=update,
            ),
            child_record=record,
            child_result=child_result,
        )

    def acquire(self, ctx: "Context") -> _AcquiredUnit:
        with ctx._child_invocation(self.child):
            acquired = self._finish(self.child.run(ctx))
        ctx._receive_child_update(acquired.contribution.episode_update)
        return acquired

    async def acquire_async(self, ctx: "Context") -> _AcquiredUnit:
        with ctx._child_invocation(self.child):
            acquired = await self._finish_async(await self.child.run_async(ctx))
        ctx._receive_child_update(acquired.contribution.episode_update)
        return acquired


class _LeafSource:
    def __init__(
        self,
        inner: Any,
        extract: Callable[[Any], Any],
        result: Callable[[Any, Any], Any],
        label: Optional[Callable[[Any], str]],
        accept: Optional[Callable[[Any, Any], Any]],
    ) -> None:
        if hasattr(inner, "next"):
            self._pull = inner.next
        else:
            iterator = iter(inner)
            self._pull = lambda _view: next(iterator, None)
        self._extract = extract
        self._result = result
        self._label = label
        self._accept = accept
        self._index = 0

    def _wrap(self, unit: Any) -> Any:
        if unit is None or isinstance(unit, SourceEnd):
            return unit
        if isinstance(unit, Acquirable):
            raise TypeError(
                "leaves(...) wraps raw units; its source returned an Acquirable"
            )
        label = (
            str(self._label(unit))
            if self._label is not None
            else f"unit-{self._index}"
        )
        self._index += 1
        return Leaf(
            unit=unit,
            extract=self._extract,
            accept=self._accept,
            result=self._result,
            label=label,
        )

    def next(self, view: EpisodeView) -> Any:
        unit = self._pull(view)
        if inspect.isawaitable(unit):
            return self._wrap_awaitable(unit)
        return self._wrap(unit)

    async def _wrap_awaitable(self, awaitable: Any) -> Any:
        return self._wrap(await awaitable)


def leaves(
    units: Any,
    extract: Callable[[Any], Any],
    result: Callable[[Any, Any], Any],
    label: Optional[Callable[[Any], str]] = None,
    accept: Optional[Callable[[Any, Any], Any]] = None,
) -> UnitSource:
    """Wrap a raw-unit source with the bound leaf operations."""

    return _LeafSource(units, extract, result, label, accept)


class Context:
    """Run identity, nesting, controller routing, and the Goal write boundary."""

    def __init__(
        self,
        *,
        tree: EpisodeTree,
        run_id: Optional[str] = None,
        runtime: Optional[ControllerRuntime] = None,
        goal_state: Optional[GoalState] = None,
        boundary_path: Path = (),
    ) -> None:
        if not isinstance(tree, EpisodeTree):
            raise TypeError("Context.tree must be an EpisodeTree")
        self.runtime = runtime if runtime is not None else ControllerRuntime()
        self.tree = tree
        parent: Path = ()
        for grain_name, key in boundary_path:
            allowed = (tree.root,) if not parent else tree.allowed_children(parent[-1][0])
            if not isinstance(key, str) or not key or grain_name not in {grain.name for grain in allowed}:
                raise ValueError("frozen context boundary is outside the declared Episode tree")
            parent = (*parent, (grain_name, key))
        self._boundary_path = parent
        if goal_state is not None and not isinstance(goal_state, GoalState):
            raise TypeError("Context.goal_state must implement GoalState")
        self.__goal_state = goal_state
        self._stack: list[Path] = []
        self._active_episodes: dict[Path, Episode] = {}
        self._child_edges: list[Episode] = []
        self._child_updates: dict[Path, list[EpisodeUpdate]] = {}
        self._grains: dict[str, Grain] = {}
        self._run_id: Optional[str] = None
        if run_id is not None:
            self.bind_run_id(run_id)

    def _receive_child_update(self, update: EpisodeUpdate) -> None:
        if not self.path:
            raise ValueError("a child report requires an active parent Episode")
        self._child_updates.setdefault(self.path, []).append(update)

    @contextmanager
    def _child_invocation(self, child: Episode):
        if self.path not in self._active_episodes:
            raise ValueError("a child invocation requires an active parent Episode")
        self._child_edges.append(child)
        try:
            yield
        finally:
            self._child_edges.pop()

    @property
    def child_reports(self) -> tuple[ParentReport, ...]:
        return tuple(update.report for update in self._child_updates.get(self.path, ()))

    def model_inputs(self, declared_inputs: Mapping[str, Any], *, reports: tuple[ParentReport, ...]) -> dict[str, Any]:
        """Deliver the reports selected by an active Episode's binding."""
        if not self.path:
            raise ValueError("model inputs require an active Episode")
        return _model_inputs(declared_inputs, self.child_reports, reports)

    def _preview_goal(
        self,
        proposal: GoalProposal,
        unit_ref: UnitRef,
    ) -> GoalPreview:
        state = self.__goal_state
        if state is None:
            raise RuntimeError("a Goal proposal requires a method-owned GoalState")
        before = state.state_id
        preview = state.preview(proposal, unit_ref)
        if not isinstance(preview, GoalPreview):
            raise TypeError("GoalState.preview() must return GoalPreview")
        after = state.state_id
        if before != after or preview.state_id != before:
            raise RuntimeError("GoalState.preview() mutated Goal state")
        return preview

    def _commit_goal(
        self,
        preview: GoalPreview,
        result_ids: tuple[str, ...],
    ) -> Any:
        state = self.__goal_state
        if state is None:
            raise RuntimeError("Goal commit requires a method-owned GoalState")
        if not result_ids:
            raise ValueError("GoalState.commit() requires credited result identities")
        if state.state_id != preview.state_id:
            raise RuntimeError("Goal state changed between preview and commit")
        return state.commit(preview, result_ids)

    def bind_run_id(self, run_id: str) -> None:
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("Context run_id must be a non-empty string")
        if self._run_id is not None and self._run_id != run_id:
            raise ValueError("Context run_id is already bound")
        self._run_id = run_id

    @property
    def has_run_id(self) -> bool:
        return self._run_id is not None

    def require_run_id(self) -> str:
        if self._run_id is None:
            raise RuntimeError(
                "Context run_id must be bound before Episode identity is read"
            )
        return self._run_id

    @property
    def path(self) -> Path:
        return self._stack[-1] if self._stack else self._boundary_path

    def _allowed_next(self, parent: Path) -> tuple[Grain, ...]:
        if not parent:
            return (self.tree.root,)
        return self.tree.allowed_children(parent[-1][0])

    def can_enter(self, grain: Grain) -> bool:
        """Whether ``grain`` can occupy the next structural position."""

        parent = self.path
        return any(item == grain for item in self._allowed_next(parent))

    def enter(self, grain: Grain, key: str) -> Scope:
        if not isinstance(grain, Grain):
            raise TypeError(f"enter() needs a Grain, got {type(grain).__name__}")
        known = self._grains.get(grain.name)
        if known is not None and known is not grain and known != grain:
            raise ValueError(f"grain {grain.name!r} was declared more than once")
        parent = self.path
        allowed = self._allowed_next(parent)
        declared = next(
            (item for item in allowed if item.name == grain.name),
            None,
        )
        if declared is None:
            raise ValueError(
                f"grain {grain.name!r} may not nest under "
                f"{parent[-1][0] if parent else 'the root'}; allowed: "
                f"{[item.name for item in allowed]}"
            )
        if declared != grain:
            raise ValueError(
                f"grain {grain.name!r} differs from its EpisodeTree declaration"
            )
        path: Path = tuple(parent) + ((grain.name, str(key)),)
        scope = self.runtime.open_scope(path, grain.controller)
        self._grains[grain.name] = grain
        self._stack.append(scope)
        return scope

    def leave(self, scope: Scope) -> None:
        if not self._stack or self._stack[-1] != scope:
            raise RuntimeError("episodes must close in nesting order")
        self._stack.pop()
        self._active_episodes.pop(scope, None)

    def transition(self, scope: Scope, mutation: EpochMutation) -> Scope:
        if scope != self.path or len(scope) != 1:
            raise ValueError("only the open root episode may transition epoch")
        return self.runtime.transition_scope(scope, mutation.epoch)
