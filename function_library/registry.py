"""Build-time resolution for explicitly imported Episode functions."""

from __future__ import annotations

from .models import FunctionEvaluationReport, LibraryFunction


class FunctionLibrary:
    def __init__(
        self,
        *,
        evaluated_interfaces: tuple[str, ...] = (),
    ) -> None:
        if not isinstance(evaluated_interfaces, tuple) or any(
            not isinstance(interface, str) or not interface.strip()
            for interface in evaluated_interfaces
        ):
            raise ValueError("evaluated_interfaces must be a tuple of names")
        if len(set(evaluated_interfaces)) != len(evaluated_interfaces):
            raise ValueError("evaluated_interfaces must be unique")
        self._functions: dict[str, LibraryFunction] = {}
        self._evaluated_interfaces = frozenset(evaluated_interfaces)
        self._evaluation_reports: dict[str, FunctionEvaluationReport] = {}

    def _evaluate(
        self,
        function: LibraryFunction,
    ) -> FunctionEvaluationReport | None:
        specification = function.evaluation
        if specification is None:
            if function.interface in self._evaluated_interfaces:
                raise ValueError(
                    f"{function.component_id} requires deterministic admission "
                    "scenarios"
                )
            return None
        target = function.load()
        evaluator = specification.implementation.load()
        report = evaluator(target, specification.arguments)
        if not isinstance(report, FunctionEvaluationReport):
            raise TypeError(
                "function admission evaluator must return FunctionEvaluationReport"
            )
        if report.scenario_ids != specification.scenario_ids:
            raise ValueError(
                "function admission evaluator returned scenarios other than its "
                "declared scenario IDs"
            )
        if not report.passed:
            failed = tuple(
                outcome.scenario_id
                for outcome in report.outcomes
                if not outcome.passed
            )
            raise ValueError(
                f"{function.component_id} failed admission scenarios {failed!r}"
            )
        return report

    def register(self, function: LibraryFunction) -> LibraryFunction:
        if not isinstance(function, LibraryFunction):
            raise TypeError("function must be a LibraryFunction")
        component_id = function.component_id
        if component_id in self._functions:
            raise ValueError(f"duplicate library function {component_id!r}")
        report = self._evaluate(function)
        self._functions[component_id] = function
        if report is not None:
            self._evaluation_reports[component_id] = report
        return function

    def resolve(self, component_id: str) -> LibraryFunction:
        try:
            return self._functions[component_id]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"unknown library function {component_id!r}") from exc

    def functions(self) -> tuple[LibraryFunction, ...]:
        return tuple(self._functions[key] for key in sorted(self._functions))

    def validate_implementation(self, component_id: str) -> None:
        self.resolve(component_id).load()

    def evaluation_report(
        self,
        component_id: str,
    ) -> FunctionEvaluationReport | None:
        function = self.resolve(component_id)
        return self._evaluation_reports.get(function.component_id)


__all__ = ["FunctionLibrary"]
