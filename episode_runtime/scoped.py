"""Immutable selected-invocation execution within an admitted workflow."""

from dataclasses import dataclass
from typing import Mapping

from function_library.epistemic_contract import exact, names
from function_library.models import _freeze_json, _thaw_json
from method_loop.identities import normalize_structural_path


@dataclass(frozen=True)
class RunScope:
    kind: str
    entry_local_id: str
    included_local_ids: tuple[str, ...]
    included_grains: tuple[str, ...]
    boundary_ref: Mapping
    boundary: Mapping

    def __post_init__(self):
        if self.kind not in {"episode", "nested"}:
            raise ValueError("selected invocation scope must be episode or nested")
        for field in ("included_local_ids", "included_grains"):
            object.__setattr__(
                self, field, names(getattr(self, field), field, nonempty=True)
            )
        if self.entry_local_id not in self.included_local_ids:
            raise ValueError("selected invocation must include its entry")
        if self.kind == "episode" and len(self.included_local_ids) != 1:
            raise ValueError("multiple selected Episodes require nested scope")
        self._validate_boundary()
        object.__setattr__(self, "boundary", _freeze_json(self.boundary, "boundary"))
        object.__setattr__(
            self, "boundary_ref", _freeze_json(self.boundary_ref, "boundary_ref")
        )

    def _validate_boundary(self):
        exact(
            self.boundary,
            {
                "source_run_id",
                "source_workflow_hash",
                "source_build_receipt_id",
                "episode_path",
                "source_launch_request",
                "entry_request",
                "parent_goal_id",
                "goal_view",
                "goal_state_id",
                "initial_goal_state_id",
                "event_ref",
                "recording_ref",
            },
            "saved invocation boundary",
        )
        path = self.source_path
        if not path or path[0][1] != self.boundary["source_run_id"]:
            raise ValueError("boundary path differs from the source Run")
        if self.boundary["goal_state_id"] != self.boundary["initial_goal_state_id"]:
            raise ValueError("this boundary requires non-initial GoalState restoration")

    @property
    def workflow_hash(self):
        return self.boundary["source_workflow_hash"]

    @property
    def path_grains(self):
        return tuple(grain for grain, _ in self.source_path)

    @property
    def source_path(self):
        return normalize_structural_path(
            tuple(
                (part["grain"], part["key"]) for part in self.boundary["episode_path"]
            )
        )

    def entry_path(self, run_id):
        path = self.source_path
        return ((path[0][0], run_id), *path[1:])

    def as_record(self):
        return {
            field: _thaw_json(getattr(self, field))
            for field in self.__dataclass_fields__
        }

    @classmethod
    def from_record(cls, value):
        return cls(**exact(value, set(cls.__dataclass_fields__), "Run scope"))

    def validate_plan(self, plan):
        from .broker import admitted_call_graph, resolve_call_path

        paths, edges = admitted_call_graph(plan)
        if resolve_call_path(paths, edges, self.path_grains) != self.entry_local_id:
            raise ValueError("saved invocation does not address the selected entry")
        nodes = {node.local_id: node for node in plan.nodes}
        if set(self.included_local_ids) - nodes.keys():
            raise ValueError("selected scope names an unknown Episode")
        if set(self.included_grains) != {
            nodes[key].grain_name for key in self.included_local_ids
        }:
            raise ValueError("selected scope grains differ from the admitted plan")
        reachable = {self.entry_local_id}
        pending = [self.entry_local_id]
        while pending:
            parent = pending.pop()
            for edge in plan.all_edges:
                if edge.parent_local_id != parent:
                    continue
                if edge.child_local_id not in self.included_local_ids:
                    raise ValueError(
                        "selected execution could leave its declared scope"
                    )
                if edge.child_local_id not in reachable:
                    reachable.add(edge.child_local_id)
                    pending.append(edge.child_local_id)
        if reachable != set(self.included_local_ids):
            raise ValueError("selected execution contains disconnected Episodes")


@dataclass(frozen=True)
class FreshEntryScope(RunScope):
    """New typed test input to a declared child, never a recorded parent context."""

    def _validate_boundary(self):
        value = exact(
            self.boundary,
            {
                "origin",
                "workflow_hash",
                "build_receipt_id",
                "path_grains",
                "path_local_ids",
                "edge_slots",
                "goals",
                "input_payload",
                "definition_ref",
                "input_evidence_ref",
                "limitations",
            },
            "fresh typed entry boundary",
        )
        if value["origin"] != "fresh_typed_entry" or len(value["path_grains"]) < 2:
            raise ValueError("fresh typed entry must name a declared non-root child")
        if not (
            len(value["path_grains"])
            == len(value["path_local_ids"])
            == len(value["goals"])
            and len(value["edge_slots"]) + 1 == len(value["path_grains"])
        ):
            raise ValueError("fresh typed entry path and goal declarations disagree")

    @property
    def workflow_hash(self):
        return self.boundary["workflow_hash"]

    @property
    def path_grains(self):
        return tuple(self.boundary["path_grains"])

    @property
    def source_path(self):
        raise ValueError("fresh typed entry has no recorded source invocation")

    def entry_path(self, run_id):
        return tuple(
            (grain, run_id if index == 0 else "test-entry")
            for index, grain in enumerate(self.path_grains)
        )

    def validate_plan(self, plan):
        super().validate_plan(plan)
        local_ids = self.boundary["path_local_ids"]
        if local_ids[0] != plan.root_local_id or local_ids[-1] != self.entry_local_id:
            raise ValueError(
                "fresh entry path differs from the declared root and entry"
            )
        for parent, child, slot in zip(
            local_ids, local_ids[1:], self.boundary["edge_slots"]
        ):
            if not any(
                edge.parent_local_id == parent
                and edge.child_local_id == child
                and edge.slot_name == slot
                for edge in plan.edges
            ):
                raise ValueError(
                    "fresh entry requires concrete approved edges; call guards cannot be bypassed"
                )

    def goal(self, registration):
        from method_loop import EpisodeGoal

        declarations = self.boundary["goals"]
        goal = EpisodeGoal.root(
            objective=declarations[0]["objective"],
            result_contract=_thaw_json(declarations[0]["result_contract"]),
            task_context={
                "duet_launch_request": registration.launch_request.as_record()
            },
        )
        for declaration in declarations[1:]:
            goal = EpisodeGoal.child(
                goal,
                objective=declaration["objective"],
                result_contract=_thaw_json(declaration["result_contract"]),
            )
        return goal

    def restore(self, registration, plan, root_module, goal_state):
        from agent.duet_contracts import content_id
        from handoff_library import ParentRequestAddress, admit_parent_request
        from method_loop import EpisodeRequest
        from method_loop.identities import EpisodeRef

        self.validate_plan(plan)
        goal = self.goal(registration)
        node = next(item for item in plan.nodes if item.local_id == self.entry_local_id)
        path = self.entry_path(registration.logical_run_id.value)
        address = ParentRequestAddress(
            content_id(
                "request",
                {"run_id": registration.logical_run_id.value, "boundary": self.boundary_ref},
            ).value,
            EpisodeRef(registration.logical_run_id.value, path[:-1]).episode_id,
            EpisodeRef(registration.logical_run_id.value, path).episode_id,
            goal.goal_id,
            node.interface,
        )
        from dataclasses import asdict

        message = admit_parent_request(
            {**asdict(address), **_thaw_json(self.boundary["input_payload"])},
            address,
            node.request_payload_contract,
        )
        return (
            node.local_id,
            EpisodeRequest(goal, message),
            path,
            root_module.scope_goal_state(goal_state, goal),
        )


def validate_execution_path(registration, path):
    scope = registration.execution_scope
    if scope is None:
        return
    path = tuple((part["grain"], part["key"]) for part in path)
    prefix = scope.entry_path(registration.logical_run_id.value)
    if (
        (scope.kind == "component" and path != prefix)
        or path[: len(prefix)] != prefix
        or any(grain not in scope.included_grains for grain, _ in path[len(prefix) :])
    ):
        raise ValueError(
            "worker request is outside the exact experimental execution scope"
        )


def scope_from_record(value):
    from .components import ComponentScope
    from .units import UnitScope

    if value is None:
        return None
    decoder = {"component": ComponentScope, "unit": UnitScope}.get(
        value.get("kind"),
        FreshEntryScope
        if value.get("boundary", {}).get("origin") == "fresh_typed_entry"
        else RunScope,
    )
    return decoder.from_record(value)


def initial_launch(registration):
    from .contracts import _launch_request_from_record

    return (
        registration.launch_request
        if registration.execution_scope is None
        or registration.execution_scope.kind == "component"
        or isinstance(registration.execution_scope, FreshEntryScope)
        else _launch_request_from_record(
            registration.execution_scope.boundary["source_launch_request"]
        )
    )


def restore_entry(registration, plan, root_module, goal_state):
    """Restore only recorded, typed entry context; ancestors do not execute."""
    from types import MappingProxyType
    from agent.duet_contracts import canonical_json, content_id
    from handoff_library import ParentRequestAddress, admit_parent_request
    from method_loop import EpisodeGoal, EpisodeRequest, ReportContract
    from method_loop.identities import EpisodeRef

    scope = registration.execution_scope
    if scope is None:
        goal = EpisodeGoal.root(
            objective=root_module.BINDING.goal,
            result_contract=root_module.RESULT_PAYLOAD_CONTRACT.as_record(),
            task_context={
                "duet_launch_request": registration.launch_request.as_record()
            },
        )
        root = next(node for node in plan.nodes if node.local_id == plan.root_local_id)
        path = ((root.grain_name, registration.logical_run_id.value),)
        return (
            root.local_id,
            EpisodeRequest(goal, registration.launch_request),
            path,
            root_module.scope_goal_state(goal_state, goal),
        )
    scope.validate_plan(plan)
    if isinstance(scope, FreshEntryScope):
        return scope.restore(registration, plan, root_module, goal_state)
    boundary = scope.boundary
    if goal_state.state_id != boundary["goal_state_id"]:
        raise ValueError(
            "saved boundary GoalState differs from reproducible initial state; restoration is required"
        )
    goal = EpisodeGoal.from_record(boundary["entry_request"]["goal"])
    declared_report = boundary["entry_request"]["report_contract"]
    report_contract = (
        None if declared_report is None else ReportContract.from_record(declared_report)
    )
    if goal.parent_goal_id != boundary["parent_goal_id"]:
        raise ValueError("saved entry Goal differs from its actual parent")
    node = next(node for node in plan.nodes if node.local_id == scope.entry_local_id)
    path = scope.entry_path(registration.logical_run_id.value)
    if len(path) == 1:
        message = initial_launch(registration)
        if canonical_json(message.as_record()) != canonical_json(
            boundary["entry_request"]["message"]
        ):
            raise ValueError("saved root request differs from source launch")
    else:
        raw = _thaw_json(boundary["entry_request"]["message"])
        source_run = boundary["source_run_id"]
        source_path = scope.source_path
        admit_parent_request(
            raw,
            ParentRequestAddress(
                raw["request_id"],
                EpisodeRef(source_run, source_path[:-1]).episode_id,
                EpisodeRef(source_run, source_path).episode_id,
                goal.goal_id,
                node.interface,
            ),
            node.request_payload_contract,
        )
        raw.update(
            request_id=content_id(
                "request",
                {"source": raw["request_id"], "run_id": registration.logical_run_id.value},
            ).value,
            parent_episode_id=EpisodeRef(
                registration.logical_run_id.value, path[:-1]
            ).episode_id,
            child_episode_id=EpisodeRef(registration.logical_run_id.value, path).episode_id,
        )
        message = admit_parent_request(
            raw,
            ParentRequestAddress(
                raw["request_id"],
                raw["parent_episode_id"],
                raw["child_episode_id"],
                goal.goal_id,
                node.interface,
            ),
            node.request_payload_contract,
        )
    view = root_module.scope_goal_state(goal_state, goal)
    if type(view) is not MappingProxyType or canonical_json(
        _thaw_json(_freeze_json(view, "goal view"))
    ) != canonical_json(boundary["goal_view"]):
        raise ValueError(
            "reconstructed goal view differs from the exact recorded boundary"
        )
    return node.local_id, EpisodeRequest(goal, message, report_contract), path, view
