"""Resolve immutable Episode references into complete Builder context.

The reference library is design material.  EpisodeBuilder reads it in full and
records every pinned source file it used; a reference is never treated as an
already executable task module merely because its binding can be imported.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import inspect
from pathlib import Path
import subprocess
from types import MappingProxyType
from typing import Mapping

from episode_library import episode_library
from episode_library.models import EpisodeLibraryDesign, EpisodeReference


_BUILTIN_REFERENCE_MODULES = {
    "reasoning.generic": "episode_library.reasoning",
    "reasoning.inquiry": "episode_library.inquiry",
    "question_pipeline.run": "episode_library.question_run",
    "question_pipeline.search_strategy": "episode_library.search_strategy",
    "question_pipeline.web_search": "episode_library.web_search",
    "question_pipeline.page": "episode_library.page",
    "question_pipeline.source_table": "episode_library.source_table",
    "question_pipeline.report": "episode_library.report",
    "question_pipeline.lexical_probe": "episode_library.lexical_probe",
}


@dataclass(frozen=True)
class EpisodeReferenceContext:
    design: EpisodeLibraryDesign
    design_module: str
    design_source: str
    pinned_source_files: Mapping[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.design, EpisodeLibraryDesign):
            raise TypeError("reference context requires an EpisodeLibraryDesign")
        if not isinstance(self.design_module, str) or not self.design_module:
            raise ValueError("reference design module must be non-empty")
        if not isinstance(self.design_source, str) or not self.design_source:
            raise ValueError("reference design source must be non-empty")
        if not isinstance(self.pinned_source_files, Mapping):
            raise TypeError("pinned_source_files must be a mapping")
        object.__setattr__(
            self,
            "pinned_source_files",
            MappingProxyType(dict(self.pinned_source_files)),
        )

    def as_record(self) -> dict[str, object]:
        return {
            "episode_id": self.design.episode_id,
            "qualified_name": self.design.qualified_name,
            "definition": self.design.as_record(),
            "design_module": self.design_module,
            "design_source": self.design_source,
            "pinned_source_files": dict(self.pinned_source_files),
        }


class EpisodeReferenceResolver:
    """Read reference modules and their complete pinned source files."""

    def __init__(self, repository_roots: Mapping[str, str | Path] | None = None) -> None:
        roots: dict[str, Path] = {}
        for repository, raw_path in (repository_roots or {}).items():
            path = Path(raw_path).expanduser().resolve()
            if not path.is_dir():
                raise ValueError(f"reference repository root does not exist: {path}")
            roots[str(repository)] = path
        self._repository_roots = MappingProxyType(roots)

    @staticmethod
    def _module_for(design: EpisodeLibraryDesign) -> str:
        module_name = _BUILTIN_REFERENCE_MODULES.get(design.qualified_name)
        if module_name is None:
            raise ValueError(
                "the referenced Episode has no readable design-module location: "
                f"{design.qualified_name}"
            )
        return module_name

    def _repository_root(self, repository: str) -> Path:
        configured = self._repository_roots.get(repository)
        if configured is not None:
            return configured
        repository_name = repository.rstrip("/").rsplit("/", 1)[-1]
        if repository_name.endswith(".git"):
            repository_name = repository_name[:-4]
        sibling = Path(__file__).resolve().parents[2] / repository_name
        if sibling.is_dir():
            return sibling.resolve()
        raise ValueError(
            "no local immutable source checkout is available for "
            f"{repository!r}"
        )

    @staticmethod
    def _read_git_file(root: Path, revision: str, path: str) -> str:
        completed = subprocess.run(
            ["git", "show", f"{revision}:{path}"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = " ".join(completed.stderr.split())
            raise ValueError(
                f"pinned source is unavailable at {revision}:{path}: {detail}"
            )
        return completed.stdout

    def resolve(self, reference: EpisodeReference) -> EpisodeReferenceContext:
        if not isinstance(reference, EpisodeReference):
            raise TypeError("reference must be an EpisodeReference")
        design = episode_library.resolve(reference.episode_id)
        module_name = self._module_for(design)
        module = importlib.import_module(module_name)
        design_source = inspect.getsource(module)
        files: dict[str, str] = {}
        locations = {
            (item.repository, item.revision, item.path)
            for item in (
                *design.source_symbols,
                *(
                    source
                    for function in design.function_definitions
                    for source in function.source_symbols
                ),
            )
        }
        for repository, revision, path in sorted(locations):
            key = f"{repository}@{revision}:{path}"
            files[key] = self._read_git_file(
                self._repository_root(repository),
                revision,
                path,
            )
        return EpisodeReferenceContext(
            design=design,
            design_module=module_name,
            design_source=design_source,
            pinned_source_files=files,
        )


__all__ = [
    "EpisodeReferenceContext",
    "EpisodeReferenceResolver",
]
