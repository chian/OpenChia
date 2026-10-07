"""Callbacks handed to method_loop must take the arguments the runtime passes.

Regression for a Run that died at ``episode_started`` with ``TypeError:
_probe_leaf.<locals>.result() takes 1 positional argument but 2 were given``:
the generated source built ``Leaf(unit=acquire, extract=extract,
result=result, ...)`` with a local ``def result(observation)``, while
method_loop calls ``result(unit, accepted)``.
"""

from __future__ import annotations

import ast

from episode_builder import admission, emitter

PREAMBLE = "from method_loop import Leaf, Episode, ChildEpisodeUnit\n"


def _deficits(source: str) -> list[str]:
    return list(admission._callback_arity_deficits(ast.parse(PREAMBLE + source)))


def test_arities_are_read_from_the_runtime() -> None:
    arities = admission.callback_arities()
    assert arities["method_loop.Leaf"]["callbacks"] == {"extract": 1, "result": 2, "accept": 2}
    assert arities["method_loop.Leaf"]["fields"][:4] == ["unit", "extract", "result", "label"]
    assert emitter._MODULE_CONTRACT["callback_arities"]["classes"] == arities


def test_the_runs_actual_shape_is_a_deficit() -> None:
    found = _deficits(
        "def _probe_leaf(probe, ledger):\n"
        "    async def acquire(ctx=None):\n"
        "        return None\n"
        "    def extract(observation):\n"
        "        return {}\n"
        "    def result(observation):\n"
        "        return observation\n"
        "    return Leaf(unit=acquire, extract=extract, result=result, label='p')\n"
    )
    assert len(found) == 2
    assert any("method_loop.Leaf.result" in item and "2 positional" in item for item in found)
    assert any("method_loop.Leaf.unit" in item and "acquire" in item for item in found)


def test_positional_lambdas_and_module_defs_are_checked() -> None:
    assert _deficits("L = Leaf(None, lambda a, b: a, lambda x: x, 'l')\n")  # extract takes 1, result 2
    assert _deficits("def r(x):\n    return x\nL = Leaf(None, lambda u: u, r, 'l')\n")


def test_correct_callbacks_pass() -> None:
    assert not _deficits(
        "def make():\n"
        "    def extract(unit):\n"
        "        return unit\n"
        "    def result(unit, accepted):\n"
        "        return accepted\n"
        "    return Leaf(unit=None, extract=extract, result=result, label='p')\n"
        "L2 = Leaf(None, lambda item: item, lambda _, item: item, 'ref')\n"
        "def flexible(*args):\n"
        "    return args\n"
        "L3 = Leaf(None, flexible, flexible, 'v')\n"
    )


def test_unresolvable_callbacks_are_left_to_the_runtime() -> None:
    assert not _deficits(
        "def make(result):\n"
        "    return Leaf(unit=None, extract=lambda u: u, result=result, label='p')\n"
        "class S:\n"
        "    def result(self, unit, accepted):\n"
        "        return accepted\n"
        "    def leaf(self):\n"
        "        return Leaf(None, lambda u: u, self.result, 'p')\n"
    )


def test_contract_states_the_leaf_calls() -> None:
    assert "result(unit, accepted)" in str(emitter._MODULE_CONTRACT)


def test_contract_states_leaf_credit_and_result_rules() -> None:
    contract = str(emitter._MODULE_CONTRACT)
    assert "unit is the unit's input VALUE" in contract
    assert "naming EVERY id in RESULT_CHANNEL_IDS" in contract
    assert "ClosedRecord INSTANCE, never a dict" in contract
