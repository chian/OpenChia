"""Registered-component scope inside the existing admitted Run worker.

This is an invocation shape, not another executor. No Episode controller,
ancestor, child builder or host learning operation is run by this scope.
"""

from collections.abc import Mapping
from dataclasses import dataclass
import inspect

from function_library.epistemic_contract import exact, names
from function_library.models import _freeze_json, _thaw_json


def component_input(value):
    value = exact(value, {"binding_role", "adapter", "inputs"}, "component input")
    names((value["binding_role"],), "binding_role", nonempty=True)
    if value["adapter"] not in {"json_keywords", "numeric_band"}:
        raise ValueError("component adapter must be json_keywords or numeric_band")
    if not isinstance(value["inputs"], Mapping):
        raise ValueError("component inputs must be a keyword-argument object")
    return _thaw_json(_freeze_json(value, "component input"))


def call_arguments(binding, payload):
    """Decode only explicit data; never accept types or imports from a request."""
    payload = component_input(payload)
    inputs = payload["inputs"]
    if payload["adapter"] == "json_keywords":
        if binding["arguments"]:
            raise ValueError(
                "json_keywords cannot apply this binding's nonempty configuration; "
                "select a supported typed adapter, not replacement parameters"
            )
        return inputs
    if binding["interface"] != "continuation.numeric_credit_band":
        raise ValueError(
            "numeric_band requires a continuation.numeric_credit_band binding"
        )
    from numeric_control_library.credit_assignment import BandStatus, NumericBand

    exact(inputs, {"projected_credit"}, "numeric-band call inputs")
    band = exact(
        inputs["projected_credit"],
        {"value", "lower", "upper", "uncertainty_alpha", "status"},
        "projected credit band",
    )
    return {
        "projected_credit": NumericBand(**{
            **band,
            "status": BandStatus(band["status"]),
        }),
        "parameters": _thaw_json(binding["arguments"]),
    }


@dataclass(frozen=True)
class ComponentScope:
    kind: str
    entry_local_id: str
    included_local_ids: tuple[str, ...]
    included_grains: tuple[str, ...]
    path_grains: tuple[str, ...]
    workflow_hash: str
    binding: Mapping
    input_payload: Mapping

    def __post_init__(self):
        if self.kind != "component":
            raise ValueError("component scope requires kind=component")
        for field in ("included_local_ids", "included_grains", "path_grains"):
            object.__setattr__(
                self, field, names(getattr(self, field), field, nonempty=True)
            )
        if (
            self.included_local_ids != (self.entry_local_id,)
            or len(self.included_grains) != 1
        ):
            raise ValueError("component scope selects exactly one owning Episode")
        if self.path_grains[-1] != self.included_grains[0]:
            raise ValueError("component address must end at its owning Episode")
        for field in ("binding", "input_payload"):
            object.__setattr__(self, field, _freeze_json(getattr(self, field), field))
        if self.input_payload["binding_role"] != self.binding["role"]:
            raise ValueError("component input names a different bound role")
        call_arguments(self.binding, self.input_payload)

    def entry_path(self, run_id):
        return tuple(
            (grain, run_id if index == 0 else "component")
            for index, grain in enumerate(self.path_grains)
        )

    def as_record(self):
        return {
            field: _thaw_json(getattr(self, field))
            for field in self.__dataclass_fields__
        }

    @classmethod
    def from_record(cls, value):
        return cls(**exact(value, set(cls.__dataclass_fields__), "component scope"))

    def validate_plan(self, plan):
        from .broker import admitted_call_graph, resolve_call_path

        nodes = {node.local_id: node for node in plan.nodes}
        node = nodes.get(self.entry_local_id)
        if node is None or self.included_grains != (node.grain_name,):
            raise ValueError("component owner differs from the admitted plan")
        paths, edges = admitted_call_graph(plan)
        if resolve_call_path(paths, edges, self.path_grains) != self.entry_local_id:
            raise ValueError("component address differs from the admitted call graph")
        if (
            self.binding["source"] != "library"
            or self.binding not in node.selected_function_bindings
        ):
            raise ValueError(
                "component selection differs from the exact admitted binding"
            )


def validate_component_event(registration, kind, episode_id, payload):
    from .contracts import RunEventKind
    from .protocol import episode_id_for_path
    from .scoped import validate_execution_path

    scope = registration.execution_scope
    if kind not in {
        RunEventKind.EPISODE_STARTED,
        RunEventKind.UNIT_COMPLETED,
        RunEventKind.EPISODE_COMPLETED,
        RunEventKind.COMPONENT_OBSERVED,
    }:
        return
    if not isinstance(scope, ComponentScope):
        if kind is RunEventKind.COMPONENT_OBSERVED:
            raise ValueError("component observations require component scope")
        return
    if kind is not RunEventKind.COMPONENT_OBSERVED:
        raise ValueError(
            "component scope cannot run an Episode or claim Episode completion"
        )
    exact(
        payload,
        {"episode_path", "execution_scope", "component_result"},
        "component observation",
    )
    validate_execution_path(registration, payload["episode_path"])
    if episode_id != episode_id_for_path(registration.logical_run_id, payload["episode_path"]):
        raise ValueError("component observation names a different owner")
    if _freeze_json(payload["execution_scope"], "scope") != _freeze_json(
        scope.as_record(), "scope"
    ):
        raise ValueError("component observation changed its exact scope")
    result = exact(
        payload["component_result"], {"status", "value", "error"}, "component result"
    )
    if result["status"] == "returned":
        if result["error"] is not None:
            raise ValueError("returned component result cannot contain an error")
    elif result["status"] == "raised":
        exact(result["error"], {"type", "message"}, "component exception")
        if result["value"] is not None:
            raise ValueError("raised component result cannot contain a value")
    else:
        raise ValueError("unknown component observation status")


@dataclass
class LinkedComponentRun:
    registration: object
    definition: object
    event_sink: object

    async def run(self):
        from .contracts import RunEventKind
        from .linker import _CURRENT_RUNTIME_EPISODE_ID, _CURRENT_RUNTIME_EPISODE_PATH
        from .protocol import episode_id_for_path

        scope = self.registration.execution_scope
        path = tuple(
            {"grain": grain, "key": key}
            for grain, key in scope.entry_path(self.registration.logical_run_id.value)
        )
        episode_id = episode_id_for_path(self.registration.logical_run_id, path)
        target = self.definition.load()
        arguments = call_arguments(scope.binding, scope.input_payload)
        inspect.signature(target).bind(**arguments)
        self.definition.admit_arguments(scope.binding["arguments"])
        id_token = _CURRENT_RUNTIME_EPISODE_ID.set(episode_id)
        path_token = _CURRENT_RUNTIME_EPISODE_PATH.set(
            scope.entry_path(self.registration.logical_run_id.value)
        )
        try:
            try:
                value = target(**arguments)
                if inspect.isawaitable(value):
                    value = await value
            except Exception as exc:
                result = {
                    "status": "raised",
                    "value": None,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                }
            else:
                # Unsupported object outputs are not silently represented by repr
                # or a type name. A typed adapter is required for those interfaces.
                if hasattr(value, "as_record"):
                    value = value.as_record()
                result = {
                    "status": "returned",
                    "value": _thaw_json(_freeze_json(value, "component result")),
                    "error": None,
                }
            payload = {
                "episode_path": path,
                "execution_scope": scope.as_record(),
                "component_result": result,
            }
            await self.event_sink(RunEventKind.COMPONENT_OBSERVED, episode_id, payload)
            return {
                "outcome": "succeeded",
                "execution_scope": scope.as_record(),
                "component_result": result,
                "limitations": [
                    "Only the selected bound function executed; no Episode loop, ancestors or children executed.",
                    "A returned or raised observation is not candidate acceptance, Episode completion or admitted progress.",
                ],
            }
        finally:
            _CURRENT_RUNTIME_EPISODE_PATH.reset(path_token)
            _CURRENT_RUNTIME_EPISODE_ID.reset(id_token)
