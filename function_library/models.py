"""The common definition object exported by every Episode function library."""

from __future__ import annotations

import importlib
import inspect
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from numbers import Real
from types import MappingProxyType
from typing import Any, Callable, Mapping

from method_loop import EpisodeFunctionBinding


_DOTTED_NAME = re.compile(r"^[a-z][a-z0-9_.-]*$")
_MODULE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_REVISION = re.compile(r"^[0-9a-f]{40,64}$")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be non-empty text")
    return value


def _freeze_json(value: object, name: str) -> object:
    """Copy and freeze JSON-shaped definition data before hashing it."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} numbers must be finite")
        return value
    if isinstance(value, Mapping):
        keys = tuple(value)
        if any(not isinstance(key, str) or not key for key in keys):
            raise ValueError(f"{name} keys must be non-empty strings")
        return MappingProxyType(
            {
                key: _freeze_json(value[key], f"{name}.{key}")
                for key in sorted(keys)
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(
            _freeze_json(item, f"{name}[{index}]")
            for index, item in enumerate(value)
        )
    raise ValueError(f"{name} must contain only JSON-shaped values")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class FunctionImplementation:
    """An importable Python implementation and its execution shape."""

    module: str
    symbol: str
    is_async: bool

    def __post_init__(self) -> None:
        if not _MODULE.fullmatch(_text(self.module, "implementation module")):
            raise ValueError("implementation module must be a dotted Python name")
        if not isinstance(self.symbol, str) or not self.symbol.isidentifier():
            raise ValueError("implementation symbol must be a Python identifier")
        if not isinstance(self.is_async, bool):
            raise ValueError("is_async must be boolean")

    def load(self) -> Callable[..., Any]:
        value = getattr(importlib.import_module(self.module), self.symbol, None)
        if not callable(value):
            raise ValueError(f"{self.module}.{self.symbol} is not callable")
        if inspect.iscoroutinefunction(value) is not self.is_async:
            expected = "async" if self.is_async else "synchronous"
            raise ValueError(
                f"{self.module}.{self.symbol} must be {expected}"
            )
        return value

    def as_record(self) -> dict[str, object]:
        return {
            "kind": "python",
            "module": self.module,
            "symbol": self.symbol,
            "is_async": self.is_async,
        }


@dataclass(frozen=True)
class FunctionEvaluationSpec:
    """Deterministic scenarios that must pass before a function is admitted."""

    implementation: FunctionImplementation
    scenario_ids: tuple[str, ...]
    arguments: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.implementation, FunctionImplementation):
            raise TypeError("evaluation implementation must be a FunctionImplementation")
        if self.implementation.is_async:
            raise ValueError("function admission evaluation must be synchronous")
        if not isinstance(self.scenario_ids, tuple) or not self.scenario_ids:
            raise ValueError("evaluation must declare at least one scenario ID")
        scenario_ids = tuple(
            _text(value, "evaluation scenario ID") for value in self.scenario_ids
        )
        if any(not _DOTTED_NAME.fullmatch(value) for value in scenario_ids):
            raise ValueError("evaluation scenario IDs must be lowercase dotted names")
        if len(set(scenario_ids)) != len(scenario_ids):
            raise ValueError("evaluation scenario IDs must be unique")
        if not isinstance(self.arguments, Mapping):
            raise ValueError("evaluation arguments must be an object")
        object.__setattr__(self, "scenario_ids", scenario_ids)
        object.__setattr__(
            self,
            "arguments",
            _freeze_json(self.arguments, "evaluation arguments"),
        )

    def as_record(self) -> dict[str, object]:
        return {
            "implementation": self.implementation.as_record(),
            "scenario_ids": list(self.scenario_ids),
            "arguments": _thaw_json(self.arguments),
        }


@dataclass(frozen=True)
class FunctionScenarioOutcome:
    """One scenario's finite numerical observations and invariant result."""

    scenario_id: str
    passed: bool
    measurements: Mapping[str, Real]
    failure: str = ""

    def __post_init__(self) -> None:
        scenario_id = _text(self.scenario_id, "evaluation scenario ID")
        if not _DOTTED_NAME.fullmatch(scenario_id):
            raise ValueError("evaluation scenario ID must be a lowercase dotted name")
        if not isinstance(self.passed, bool):
            raise TypeError("scenario passed must be boolean")
        if not isinstance(self.measurements, Mapping) or not self.measurements:
            raise ValueError("scenario measurements must be a non-empty object")
        measurements: dict[str, float] = {}
        for name, raw in self.measurements.items():
            if not isinstance(name, str) or not _DOTTED_NAME.fullmatch(name):
                raise ValueError(
                    "scenario measurement names must be lowercase dotted names"
                )
            if isinstance(raw, bool) or not isinstance(raw, Real):
                raise ValueError("scenario measurements must be real numbers")
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError("scenario measurements must be finite")
            measurements[name] = value
        if not isinstance(self.failure, str) or "\x00" in self.failure:
            raise ValueError("scenario failure must be text")
        if self.passed and self.failure:
            raise ValueError("a passing scenario cannot carry a failure")
        if not self.passed and not self.failure.strip():
            raise ValueError("a failing scenario must say which invariant failed")
        object.__setattr__(self, "scenario_id", scenario_id)
        object.__setattr__(self, "measurements", MappingProxyType(measurements))

    def as_record(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "passed": self.passed,
            "measurements": dict(self.measurements),
            "failure": self.failure,
        }


@dataclass(frozen=True)
class FunctionEvaluationReport:
    """The complete deterministic admission result for one function."""

    outcomes: tuple[FunctionScenarioOutcome, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.outcomes, tuple) or not self.outcomes:
            raise ValueError("an evaluation report must contain scenario outcomes")
        if any(
            not isinstance(outcome, FunctionScenarioOutcome)
            for outcome in self.outcomes
        ):
            raise TypeError(
                "evaluation outcomes must be FunctionScenarioOutcome values"
            )
        scenario_ids = self.scenario_ids
        if len(set(scenario_ids)) != len(scenario_ids):
            raise ValueError("evaluation report scenario IDs must be unique")

    @property
    def scenario_ids(self) -> tuple[str, ...]:
        return tuple(outcome.scenario_id for outcome in self.outcomes)

    @property
    def passed(self) -> bool:
        return all(outcome.passed for outcome in self.outcomes)

    def as_record(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "outcomes": [outcome.as_record() for outcome in self.outcomes],
        }


@dataclass(frozen=True)
class SourceSymbolReference:
    """One symbol pinned to an immutable external source revision."""

    repository: str
    revision: str
    path: str
    symbol: str

    def __post_init__(self) -> None:
        _text(self.repository, "source repository")
        if not _REVISION.fullmatch(_text(self.revision, "source revision")):
            raise ValueError("source revision must be a full hexadecimal commit ID")
        path = _text(self.path, "source path")
        parts = path.split("/")
        if path.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("source path must be a normalized repository-relative path")
        symbol = _text(self.symbol, "source symbol")
        if not _MODULE.fullmatch(symbol):
            raise ValueError("source symbol must be a dotted Python qualified name")

    def as_record(self) -> dict[str, str]:
        return {
            "repository": self.repository,
            "revision": self.revision,
            "path": self.path,
            "symbol": self.symbol,
        }


class FunctionUnavailableError(RuntimeError):
    """Raised before execution when a selected function is reference-only."""


@dataclass(frozen=True)
class LibraryFunction:
    """One reusable function that an Episode can select by importing it."""

    library: str
    function_id: str
    interface: str
    description: str
    implementation: FunctionImplementation | None
    input_type: str
    output_type: str
    effect: str
    failure_contract: str
    provenance: Mapping[str, object]
    evaluation: FunctionEvaluationSpec | None = None
    source_symbols: tuple[SourceSymbolReference, ...] = ()
    definition_id: str = field(init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.library, "function library"),
            (self.function_id, "function ID"),
            (self.interface, "function interface"),
        ):
            if not _DOTTED_NAME.fullmatch(_text(value, name)):
                raise ValueError(f"{name} must be a lowercase dotted name")
        for value, name in (
            (self.description, "function description"),
            (self.input_type, "input type"),
            (self.output_type, "output type"),
            (self.effect, "function effect"),
            (self.failure_contract, "failure contract"),
        ):
            _text(value, name)
        if self.implementation is not None and not isinstance(
            self.implementation, FunctionImplementation
        ):
            raise ValueError("implementation must be a FunctionImplementation or None")
        if self.evaluation is not None and not isinstance(
            self.evaluation, FunctionEvaluationSpec
        ):
            raise ValueError("evaluation must be a FunctionEvaluationSpec or None")
        if self.evaluation is not None and self.implementation is None:
            raise ValueError("a source-only function cannot run admission scenarios")
        if not isinstance(self.source_symbols, tuple) or any(
            not isinstance(item, SourceSymbolReference)
            for item in self.source_symbols
        ):
            raise ValueError("source_symbols must contain SourceSymbolReference values")
        if len(set(self.source_symbols)) != len(self.source_symbols):
            raise ValueError("source_symbols must be unique")
        if self.implementation is None and not self.source_symbols:
            raise ValueError(
                "a non-executable function must identify its immutable source symbols"
            )
        if not isinstance(self.provenance, Mapping):
            raise ValueError("provenance must be an object")
        object.__setattr__(
            self,
            "provenance",
            _freeze_json(self.provenance, "function provenance"),
        )
        record = self.definition_record()
        try:
            encoded = json.dumps(
                record,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("function provenance must be JSON-shaped") from exc
        object.__setattr__(
            self,
            "definition_id",
            f"function_{hashlib.sha256(encoded).hexdigest()}",
        )

    @property
    def component_id(self) -> str:
        return f"{self.library}.{self.function_id}"

    @property
    def executable(self) -> bool:
        return self.implementation is not None

    def load(self) -> Callable[..., Any]:
        if self.implementation is None:
            locations = ", ".join(
                f"{item.repository}@{item.revision}:{item.path}::{item.symbol}"
                for item in self.source_symbols
            )
            raise FunctionUnavailableError(
                f"{self.component_id} is source-backed but not executable: {locations}"
            )
        return self.implementation.load()

    def bind(
        self,
        name: str,
        *,
        arguments: Mapping[str, object] | None = None,
    ) -> EpisodeFunctionBinding:
        return EpisodeFunctionBinding(
            name=name,
            library=self.library,
            function_id=self.function_id,
            interface=self.interface,
            definition_id=self.definition_id,
            arguments={} if arguments is None else arguments,
        )

    def definition_record(self) -> dict[str, object]:
        return {
            "library": self.library,
            "function_id": self.function_id,
            "interface": self.interface,
            "description": self.description,
            "implementation": (
                None
                if self.implementation is None
                else self.implementation.as_record()
            ),
            "evaluation": (
                None if self.evaluation is None else self.evaluation.as_record()
            ),
            "source_symbols": [item.as_record() for item in self.source_symbols],
            "input_type": self.input_type,
            "output_type": self.output_type,
            "effect": self.effect,
            "failure_contract": self.failure_contract,
            "provenance": _thaw_json(self.provenance),
        }

    def as_record(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "definition_id": self.definition_id,
            **self.definition_record(),
        }


__all__ = [
    "FunctionEvaluationReport",
    "FunctionEvaluationSpec",
    "FunctionImplementation",
    "FunctionScenarioOutcome",
    "FunctionUnavailableError",
    "LibraryFunction",
    "SourceSymbolReference",
]
