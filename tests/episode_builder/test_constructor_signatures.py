"""Generated modules must construct library classes with their real fields.

Regression for a Run that died with ``TypeError: EpisodeLibraryDesign.__init__()
missing 4 required positional arguments`` after admission had passed the
module: the model built ``EpisodeFunctionBinding(function=…, arguments=…)``
and ``EpisodeLibraryDesign(function_definitions=…)`` because nothing showed it
the signatures and nothing checked the calls."""

from __future__ import annotations

import ast

from episode_builder import admission, emitter


def _deficits(source: str) -> list[str]:
    return list(admission._constructor_argument_deficits(ast.parse(source)))


def test_signatures_come_from_the_dataclasses() -> None:
    signatures = admission.constructor_signatures()
    design = signatures["episode_library.models.EpisodeLibraryDesign"]
    assert design["required"] == [
        "qualified_name", "title", "binding", "function_definitions", "source_symbols",
    ]
    assert design["derived"] == ["episode_id"]
    binding = signatures["method_loop.EpisodeFunctionBinding"]
    assert binding["required"] == ["name", "library", "function_id", "interface", "definition_id"]
    assert binding["optional"] == ["arguments"]
    assert signatures["method_loop.EpisodeTopologyRole"]["members"] == ["BRANCH", "LEAF"]
    assert emitter._MODULE_CONTRACT["constructor_signatures"]["classes"] == signatures


def test_the_runs_actual_mistakes_are_deficits() -> None:
    found = _deficits(
        "from episode_library.models import EpisodeLibraryDesign\n"
        "from method_loop import EpisodeFunctionBinding\n"
        "DESIGN = EpisodeLibraryDesign(function_definitions=())\n"
        "B = EpisodeFunctionBinding(function=None, arguments={})\n"
    )
    assert len(found) == 2
    assert "EpisodeLibraryDesign at line 3" in found[0]
    assert "missing required field(s) ['qualified_name', 'title', 'binding', 'source_symbols']" in found[0]
    assert "EpisodeFunctionBinding at line 4" in found[1]
    assert "unknown keyword(s) ['function']" in found[1]
    assert "missing required field(s) ['name', 'library', 'function_id', 'interface', 'definition_id']" in found[1]


def test_correct_constructions_pass_including_aliases_and_positional() -> None:
    assert _deficits(
        "from method_loop import EpisodeFunctionBinding as EFB, EpisodeTopologyRole\n"
        "import function_library.models\n"
        "b = EFB(name='x', library='l', function_id='f', interface='i', definition_id='d')\n"
        "c = EFB('x', 'l', 'f', 'i', 'd', {})\n"
        "impl = function_library.models.FunctionImplementation(module='m', symbol='s', is_async=False)\n"
        "role = EpisodeTopologyRole.LEAF\n"
    ) == []


def test_unpacked_arguments_are_not_judged() -> None:
    assert _deficits(
        "from method_loop import EpisodeFunctionBinding\n"
        "b = EpisodeFunctionBinding(**record)\n"
    ) == []


def test_emitter_contract_explains_the_construction() -> None:
    construction = emitter._MODULE_CONTRACT["binding_construction"]
    assert ".definition_id" in construction["EpisodeFunctionBinding"]
    assert "EpisodeBindingDeclaration(" in construction["example"]
    assert "EpisodeLibraryDesign(" in construction["example"]
