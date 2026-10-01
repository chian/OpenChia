"""Immutable records for reusable Episode library entries."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from function_library import LibraryFunction, SourceSymbolReference
from method_loop import EpisodeBindingDeclaration


_QUALIFIED_NAME = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_EPISODE_ID = re.compile(r"^episode_[0-9a-f]{64}$")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be non-empty text")
    return value


def _canonical(record: Mapping[str, Any]) -> bytes:
    return json.dumps(
        record,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class EpisodeLibraryDesign:
    """One independently selectable Episode reference."""

    qualified_name: str
    title: str
    binding: EpisodeBindingDeclaration
    function_definitions: tuple[LibraryFunction, ...]
    source_symbols: tuple[SourceSymbolReference, ...]
    episode_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not _QUALIFIED_NAME.fullmatch(
            _text(self.qualified_name, "qualified name")
        ):
            raise ValueError("qualified name must contain lowercase dotted identifiers")
        _text(self.title, "title")
        if not isinstance(self.binding, EpisodeBindingDeclaration):
            raise ValueError("binding must be an EpisodeBindingDeclaration")
        if not isinstance(self.function_definitions, tuple):
            raise ValueError("function_definitions must be a tuple")
        if any(
            not isinstance(function, LibraryFunction)
            for function in self.function_definitions
        ):
            raise ValueError(
                "function_definitions must contain LibraryFunction values"
            )
        definition_ids = [
            function.definition_id for function in self.function_definitions
        ]
        component_ids = [
            function.component_id for function in self.function_definitions
        ]
        if len(set(definition_ids)) != len(definition_ids):
            raise ValueError("function definitions must not repeat")
        if len(set(component_ids)) != len(component_ids):
            raise ValueError(
                "one Episode design cannot select multiple definitions of one component"
            )
        object.__setattr__(
            self,
            "function_definitions",
            tuple(
                sorted(
                    self.function_definitions,
                    key=lambda function: function.component_id,
                )
            ),
        )
        definitions = {
            function.definition_id: function
            for function in self.function_definitions
        }
        bindings = self.binding.function_bindings()
        selected_ids = {selection.definition_id for selection in bindings}
        missing = selected_ids - set(definitions)
        extra = set(definitions) - selected_ids
        if missing or extra:
            raise ValueError(
                "function definitions must exactly cover the binding selections: "
                f"missing={sorted(missing)}, extra={sorted(extra)}"
            )
        for selection in bindings:
            function = definitions[selection.definition_id]
            if (
                selection.library != function.library
                or selection.function_id != function.function_id
                or selection.interface != function.interface
            ):
                raise ValueError(
                    f"function definition does not match binding {selection.name!r}"
                )
        if not isinstance(self.source_symbols, tuple):
            raise ValueError("source_symbols must be a tuple")
        if any(
            not isinstance(item, SourceSymbolReference)
            for item in self.source_symbols
        ):
            raise ValueError("source_symbols must contain SourceSymbolReference values")
        if len(set(self.source_symbols)) != len(self.source_symbols):
            raise ValueError("source_symbols must be unique")
        object.__setattr__(
            self,
            "source_symbols",
            tuple(
                sorted(
                    self.source_symbols,
                    key=lambda item: (
                        item.repository,
                        item.revision,
                        item.path,
                        item.symbol,
                    ),
                )
            ),
        )
        digest = hashlib.sha256(_canonical(self.semantic_record())).hexdigest()
        object.__setattr__(self, "episode_id", f"episode_{digest}")

    def semantic_record(self) -> dict[str, Any]:
        return {
            "qualified_name": self.qualified_name,
            "binding": self.binding.as_record(),
            "function_definitions": [
                function.as_record() for function in self.function_definitions
            ],
            "source_symbols": [item.as_record() for item in self.source_symbols],
        }

    def definition_record(self) -> dict[str, Any]:
        return {"title": self.title, **self.semantic_record()}

    def as_record(self) -> dict[str, Any]:
        return {"episode_id": self.episode_id, **self.definition_record()}

    def resolve_function(self, definition_id: str) -> LibraryFunction:
        function = next(
            (
                item
                for item in self.function_definitions
                if item.definition_id == definition_id
            ),
            None,
        )
        if function is None:
            raise ValueError(
                f"Episode {self.qualified_name!r} does not select "
                f"function definition {definition_id!r}"
            )
        return function


@dataclass(frozen=True)
class EpisodeReference:
    """A persisted pointer to one immutable Episode library design."""

    episode_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.episode_id, str) or not _EPISODE_ID.fullmatch(
            self.episode_id
        ):
            raise ValueError("Episode reference must contain a durable episode ID")

    def as_record(self) -> dict[str, str]:
        return {"episode_id": self.episode_id}

    @classmethod
    def from_record(cls, value: object) -> "EpisodeReference":
        if not isinstance(value, Mapping) or set(value) != {"episode_id"}:
            raise ValueError("Episode reference must contain exactly episode_id")
        return cls(episode_id=value["episode_id"])


__all__ = [
    "EpisodeLibraryDesign",
    "EpisodeReference",
]
