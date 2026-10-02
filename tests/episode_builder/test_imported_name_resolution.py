"""Admission resolves imported *names*, not just import roots, against the
real library modules without importing them; the emitter shows the model the
same surface. Regression for a Run that died with
``ImportError: cannot import name 'EpisodeControllerBinding' from
'episode_library.models'`` after admission had passed the module."""

from __future__ import annotations

import ast
from pathlib import Path

from episode_builder import admission, emitter

REPO = Path(__file__).resolve().parents[2]


def _codes(source: str) -> list[tuple[str, str]]:
    return list(admission._imported_name_deficits(ast.parse(source), REPO))


def test_wrong_module_for_a_real_class_is_a_deficit() -> None:
    found = _codes(
        "from episode_library.models import EpisodeLibraryDesign, EpisodeControllerBinding\n"
    )
    assert [code for code, _ in found] == ["imported_name_missing"]
    assert "'EpisodeControllerBinding' from 'episode_library.models'" in found[0][1]


def test_right_modules_pass() -> None:
    assert _codes(
        "from method_loop import Episode, EpisodeControllerBinding, EpisodeBindingDeclaration\n"
        "from function_library.models import FunctionImplementation, LibraryFunction\n"
        "from episode_library.models import EpisodeLibraryDesign\n"
        "from http_call_library import HTTP_JSON, HttpJsonResult, http_json\n"
        "from numeric_control_library import ResultColumnSchema, paired_incidence\n"
        "from handoff_library import admit_child_result\n"
        "import numeric_control_library.credit_assignment\n"
        "import json\n"
        "from typing import Any\n"
    ) == []


def test_missing_module_is_a_deficit() -> None:
    found = _codes("import numeric_control_library.nope\nfrom method_loop.absent import x\n")
    assert [code for code, _ in found] == [
        "imported_module_missing",
        "imported_module_missing",
    ]


def test_exported_names_follow_re_exports_and_submodules() -> None:
    names = admission._exported_names(REPO / "episode_library" / "models.py")
    assert names is not None
    assert "EpisodeLibraryDesign" in names
    assert "EpisodeBindingDeclaration" in names  # re-imported into the module
    assert "EpisodeControllerBinding" not in names
    # a package's submodule is importable as a name from the package
    assert _codes("from numeric_control_library import credit_assignment\n") == []


def test_emitter_contract_lists_the_real_exports() -> None:
    exports = emitter._MODULE_CONTRACT["library_exports"]["exports"]
    assert "EpisodeControllerBinding" in exports["method_loop"]
    assert "EpisodeControllerBinding" not in exports["episode_library.models"]
    assert exports["episode_library.models"] == ["EpisodeLibraryDesign", "EpisodeReference"]
    assert "FunctionImplementation" in exports["function_library.models"]
    assert "http_json" in exports["http_call_library"]
