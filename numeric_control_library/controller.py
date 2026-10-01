"""Explicit composition of credit, rarefaction, and continuation functions."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping, Optional, Protocol, runtime_checkable

from function_library import FunctionImplementation, FunctionLibrary, LibraryFunction

from .credit_assignment import (
    BandStatus,
    CreditAdmission,
    CreditObservation,
    CreditSnapshot,
    EXCLUDED,
    HypervolumeCredit,
    NumericBand,
    NumericIncidenceState,
    NumericYieldProjection,
    ResultColumnSchema,
)
from .continuation import ContinuationDecision


CreditFactory = Callable[
    [ResultColumnSchema, Mapping[str, object]],
    "CreditAssignment",
]
RarefactionImplementation = Callable[
    [NumericIncidenceState, Mapping[str, object]],
    NumericYieldProjection,
]
ContinuationImplementation = Callable[
    [NumericBand, Mapping[str, object]],
    ContinuationDecision,
]


@runtime_checkable
class CreditAssignment(Protocol):
    def state(self) -> CreditSnapshot: ...

    def admit(self, observation: CreditObservation) -> CreditAdmission: ...

    def assign(
        self,
        admission: CreditAdmission,
        before_projection: NumericYieldProjection,
        after_projection: NumericYieldProjection,
    ) -> HypervolumeCredit: ...


@dataclass(frozen=True)
class ComposedControllerStep:
    admission: CreditAdmission
    rarefaction: NumericYieldProjection
    credit: HypervolumeCredit
    decision: ContinuationDecision

    @property
    def stop(self) -> bool:
        return self.decision.stop

    @property
    def requests_transition(self) -> bool:
        return False

    @property
    def goal_commit_ids(self) -> tuple[str, ...]:
        return self.admission.new_identity_ids

    def as_record(self) -> dict[str, object]:
        return {
            "admission": self.admission.as_record(),
            "rarefaction": self.rarefaction.as_record(),
            "credit": self.credit.as_record(),
            "decision": self.decision.as_record(),
        }


@dataclass(frozen=True)
class ComposedControllerState:
    epoch: str
    credit_state: CreditSnapshot
    rarefaction: NumericYieldProjection
    decision: ContinuationDecision
    last_credit: Optional[HypervolumeCredit]
    selected_components: tuple[str, str, str]

    @property
    def stop(self) -> bool:
        return self.decision.stop

    @property
    def requests_transition(self) -> bool:
        return False

    def as_record(self) -> dict[str, object]:
        return {
            "epoch": self.epoch,
            "credit_state": self.credit_state.as_record(),
            "rarefaction": self.rarefaction.as_record(),
            "decision": self.decision.as_record(),
            "last_credit": (
                None if self.last_credit is None else self.last_credit.as_record()
            ),
            "selected_components": list(self.selected_components),
        }


class ComposedIncidenceController:
    """The method-loop adapter over three explicitly selected functions."""

    def __init__(
        self,
        *,
        epoch: str,
        schema: ResultColumnSchema,
        credit_function: LibraryFunction,
        rarefaction_function: LibraryFunction,
        continuation_function: LibraryFunction,
        credit_parameters: Mapping[str, object],
        rarefaction_parameters: Mapping[str, object],
        continuation_parameters: Mapping[str, object],
        credit_factory: CreditFactory,
        rarefaction_implementation: RarefactionImplementation,
        continuation_implementation: ContinuationImplementation,
    ) -> None:
        if not isinstance(epoch, str) or not epoch.strip():
            raise ValueError("epoch must be non-empty text")
        self.epoch = epoch
        self.schema = schema
        self.credit_function = credit_function
        self.rarefaction_function = rarefaction_function
        self.continuation_function = continuation_function
        self.credit_parameters = MappingProxyType(dict(credit_parameters))
        self.rarefaction_parameters = MappingProxyType(dict(rarefaction_parameters))
        self.continuation_parameters = MappingProxyType(
            dict(continuation_parameters)
        )
        self._credit_factory = credit_factory
        self._rarefaction_implementation = rarefaction_implementation
        self._continuation_implementation = continuation_implementation
        assignment = credit_factory(schema, self.credit_parameters)
        if not isinstance(assignment, CreditAssignment):
            raise TypeError(
                "the selected credit function must open a CreditAssignment"
            )
        self._assignment = assignment
        initial_projection = self._estimate(assignment.state().numeric_state)
        initial_decision = self._decide(
            NumericBand.unavailable(BandStatus.INSUFFICIENT)
        )
        self._last_projection = initial_projection
        self._last_credit: Optional[HypervolumeCredit] = None
        self._last_decision = initial_decision

    @property
    def selected_components(self) -> tuple[str, str, str]:
        return (
            self.credit_function.component_id,
            self.rarefaction_function.component_id,
            self.continuation_function.component_id,
        )

    def _estimate(self, state: NumericIncidenceState) -> NumericYieldProjection:
        projection = self._rarefaction_implementation(
            state,
            self.rarefaction_parameters,
        )
        if not isinstance(projection, NumericYieldProjection):
            raise TypeError(
                "the selected rarefaction function must return "
                "NumericYieldProjection"
            )
        return projection

    def _decide(self, band: NumericBand) -> ContinuationDecision:
        decision = self._continuation_implementation(
            band,
            self.continuation_parameters,
        )
        if not isinstance(decision, ContinuationDecision):
            raise TypeError(
                "the selected continuation function must return "
                "ContinuationDecision"
            )
        return decision

    def observe(
        self,
        unit_label: str,
        value: object,
        *,
        is_root: bool,
    ) -> ComposedControllerStep:
        del unit_label, is_root
        if not isinstance(value, CreditObservation):
            raise TypeError(
                "ComposedIncidenceController requires a CreditObservation"
            )
        admission = self._assignment.admit(value)
        projection = self._estimate(admission.after.numeric_state)
        credit = self._assignment.assign(
            admission,
            self._last_projection,
            projection,
        )
        evaluated = self._decide(credit.projected_next)
        decision = (
            ContinuationDecision(
                stop=False,
                outcome="excluded",
                projected_credit=credit.projected_next,
                threshold=evaluated.threshold,
            )
            if value.status is EXCLUDED
            else evaluated
        )
        self._last_projection = projection
        self._last_credit = credit
        self._last_decision = decision
        return ComposedControllerStep(
            admission=admission,
            rarefaction=projection,
            credit=credit,
            decision=decision,
        )

    def state(self) -> ComposedControllerState:
        return ComposedControllerState(
            epoch=self.epoch,
            credit_state=self._assignment.state(),
            rarefaction=self._last_projection,
            decision=self._last_decision,
            last_credit=self._last_credit,
            selected_components=self.selected_components,
        )

    def transitioned(self, epoch: str) -> "ComposedIncidenceController":
        if epoch == self.epoch:
            raise ValueError("a transitioned controller requires a new epoch")
        return ComposedIncidenceController(
            epoch=epoch,
            schema=self.schema,
            credit_function=self.credit_function,
            rarefaction_function=self.rarefaction_function,
            continuation_function=self.continuation_function,
            credit_parameters=self.credit_parameters,
            rarefaction_parameters=self.rarefaction_parameters,
            continuation_parameters=self.continuation_parameters,
            credit_factory=self._credit_factory,
            rarefaction_implementation=self._rarefaction_implementation,
            continuation_implementation=self._continuation_implementation,
        )


def compose_controller(
    *,
    schema: ResultColumnSchema,
    epoch: str,
    credit_function: LibraryFunction,
    rarefaction_function: LibraryFunction,
    continuation_function: LibraryFunction,
    credit_parameters: Mapping[str, object],
    rarefaction_parameters: Mapping[str, object],
    continuation_parameters: Mapping[str, object],
) -> Callable[[tuple[tuple[str, str], ...]], ComposedIncidenceController]:
    """Compose a controller factory from three visible function selections."""

    if not isinstance(schema, ResultColumnSchema):
        raise TypeError("schema must be a ResultColumnSchema")
    selections = (
        credit_function,
        rarefaction_function,
        continuation_function,
    )
    if any(not isinstance(function, LibraryFunction) for function in selections):
        raise TypeError("all selected functions must be LibraryFunction objects")
    if not isinstance(epoch, str) or not epoch.strip():
        raise ValueError("epoch must be non-empty text")
    credit_factory = credit_function.load()
    rarefaction_implementation = rarefaction_function.load()
    continuation_implementation = continuation_function.load()
    frozen_credit_parameters = MappingProxyType(dict(credit_parameters))
    frozen_rarefaction_parameters = MappingProxyType(dict(rarefaction_parameters))
    frozen_continuation_parameters = MappingProxyType(
        dict(continuation_parameters)
    )

    def open_controller(
        path: tuple[tuple[str, str], ...],
    ) -> ComposedIncidenceController:
        if not isinstance(path, tuple) or not path:
            raise ValueError("controller path must be a non-empty tuple")
        return ComposedIncidenceController(
            epoch=epoch,
            schema=schema,
            credit_function=credit_function,
            rarefaction_function=rarefaction_function,
            continuation_function=continuation_function,
            credit_parameters=frozen_credit_parameters,
            rarefaction_parameters=frozen_rarefaction_parameters,
            continuation_parameters=frozen_continuation_parameters,
            credit_factory=credit_factory,
            rarefaction_implementation=rarefaction_implementation,
            continuation_implementation=continuation_implementation,
        )

    return open_controller


controller_function_library = FunctionLibrary()
COMPOSE_INCIDENCE_CONTROLLER = controller_function_library.register(
    LibraryFunction(
        library="controller_composition",
        function_id="compose_incidence_controller",
        interface="controller.compose_numeric_incidence",
        description=(
            "Compose one path-scoped Episode controller from the explicitly "
            "selected schema, credit, rarefaction, and continuation functions."
        ),
        implementation=FunctionImplementation(
            module="numeric_control_library.controller",
            symbol="compose_controller",
            is_async=False,
        ),
        input_type=(
            "ResultColumnSchema, runtime epoch, and the three selected "
            "LibraryFunction objects with their complete arguments"
        ),
        output_type="method_loop.ControllerFactory",
        effect=(
            "Creates one isolated numerical controller per structural Episode path."
        ),
        failure_contract=(
            "Rejects absent or unloadable selections, malformed arguments, and "
            "an absent positional result schema before the Episode opens."
        ),
        provenance={
            "composition": (
                "explicit schema + credit + rarefaction + continuation"
            ),
            "runtime_input": "epoch and structural Episode path",
        },
    )
)


__all__ = [
    "COMPOSE_INCIDENCE_CONTROLLER",
    "ComposedControllerState",
    "ComposedControllerStep",
    "ComposedIncidenceController",
    "CreditAssignment",
    "compose_controller",
    "controller_function_library",
]
