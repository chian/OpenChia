"""Registration, resolution, and attachment of immutable Episode designs."""

from __future__ import annotations

from function_library import LibraryFunction

from .models import EpisodeLibraryDesign, EpisodeReference


class EpisodeLibrary:
    def __init__(self) -> None:
        self._by_id: dict[str, EpisodeLibraryDesign] = {}
        self._by_name: dict[str, EpisodeLibraryDesign] = {}

    def register(self, design: EpisodeLibraryDesign) -> EpisodeLibraryDesign:
        if not isinstance(design, EpisodeLibraryDesign):
            raise TypeError("design must be an EpisodeLibraryDesign")
        if design.qualified_name != design.binding.interface:
            raise ValueError(
                "Episode library name must equal its declared interface"
            )
        if design.episode_id in self._by_id:
            raise ValueError(f"duplicate Episode ID {design.episode_id!r}")
        if design.qualified_name in self._by_name:
            raise ValueError(f"duplicate Episode name {design.qualified_name!r}")
        self._by_id[design.episode_id] = design
        self._by_name[design.qualified_name] = design
        return design

    def resolve(self, episode_id: str) -> EpisodeLibraryDesign:
        try:
            return self._by_id[episode_id]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"unknown Episode library ID {episode_id!r}") from exc

    def resolve_name(self, qualified_name: str) -> EpisodeLibraryDesign:
        try:
            return self._by_name[qualified_name]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"unknown Episode library name {qualified_name!r}") from exc

    def resolve_optional(
        self,
        reference: EpisodeReference | None,
    ) -> EpisodeLibraryDesign | None:
        if reference is None:
            return None
        if not isinstance(reference, EpisodeReference):
            raise TypeError("reference must be an EpisodeReference or None")
        return self.resolve(reference.episode_id)

    def designs(self) -> tuple[EpisodeLibraryDesign, ...]:
        return tuple(self._by_name[name] for name in sorted(self._by_name))

    def compatible_children(
        self,
        parent_id: str,
        slot_name: str,
    ) -> tuple[EpisodeLibraryDesign, ...]:
        parent = self.resolve(parent_id)
        slot = parent.binding.child_slot(slot_name)
        return tuple(
            design
            for design in self.designs()
            if design.binding.interface in slot.accepted_interfaces
        )

    def resolve_function(
        self,
        episode_id: str,
        definition_id: str,
    ) -> LibraryFunction:
        return self.resolve(episode_id).resolve_function(definition_id)

    def validate_attachment(
        self,
        parent_id: str,
        slot_name: str,
        child_id: str,
    ) -> None:
        parent = self.resolve(parent_id)
        child = self.resolve(child_id)
        if not parent.binding.accepts(slot_name, child.binding):
            raise ValueError(
                f"Episode interface {child.binding.interface!r} does not satisfy "
                f"{parent.qualified_name}.{slot_name}"
            )

    def catalog_record(self) -> tuple[dict[str, object], ...]:
        return tuple(design.as_record() for design in self.designs())

    def validate_topology(self) -> None:
        interfaces = {
            design.binding.interface: design for design in self.designs()
        }
        if len(interfaces) != len(self._by_name):
            raise ValueError("Episode interfaces must be unique in one library")
        for design in self.designs():
            for slot in design.binding.child_slots:
                missing = set(slot.accepted_interfaces) - set(interfaces)
                if missing:
                    raise ValueError(
                        f"{design.qualified_name}.{slot.name} accepts missing "
                        f"interfaces {sorted(missing)}"
                    )


__all__ = ["EpisodeLibrary"]
