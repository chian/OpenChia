"""Generated modules must call compose_controller with its real keywords.

Regression for a Run that died at ``episode_started`` with ``TypeError:
compose_controller() got an unexpected keyword argument 'credit'``: the
generated build_controller_factory called
``compose_controller(schema=…, epoch=goal_view.get("epoch", 0), credit=…,
credit_arguments=…, rarefaction=…, …)``. The real function is keyword-only
with ``credit_function``/``credit_parameters`` etc. and needs a text epoch.
The constructor check only covered dataclasses, so admission passed it.
"""

from __future__ import annotations

import ast

from episode_builder import admission, emitter
from numeric_control_library import controller

PREAMBLE = "from numeric_control_library import compose_controller\n"


def _deficits(source: str) -> list[str]:
    return list(admission._constructor_argument_deficits(ast.parse(PREAMBLE + source)))


def test_signature_is_read_from_the_function() -> None:
    spec = admission.constructor_signatures()["numeric_control_library.compose_controller"]
    assert spec["required"] == [
        "schema", "epoch", "credit_function", "rarefaction_function",
        "continuation_function", "credit_parameters", "rarefaction_parameters",
        "continuation_parameters",
    ]
    assert spec["keyword_only"] == spec["required"]
    assert emitter._MODULE_CONTRACT["constructor_signatures"]["classes"][
        "numeric_control_library.compose_controller"
    ] == spec
    assert controller.compose_controller.__name__ == "compose_controller"


def test_the_runs_actual_call_is_a_deficit() -> None:
    found = _deficits(
        "def build_controller_factory(goal_view, collaborators):\n"
        "    return compose_controller(schema=S, epoch=goal_view.get('epoch', 0),\n"
        "        credit=C, credit_arguments={}, rarefaction=R,\n"
        "        rarefaction_arguments={'uncertainty_alpha': 0.05},\n"
        "        continuation=K, continuation_arguments={})\n"
    )
    text = " ".join(found)
    assert "'credit'" in text and "credit_function" in text
    assert "epoch must be non-empty text" in text


def test_epoch_through_a_local_name_is_resolved() -> None:
    found = _deficits(
        "def build_controller_factory(goal_view, collaborators):\n"
        "    epoch = goal_view.get('epoch', 0) if goal_view else 0\n"
        "    return compose_controller(schema=S, epoch=epoch, credit_function=C,\n"
        "        rarefaction_function=R, continuation_function=K, credit_parameters={},\n"
        "        rarefaction_parameters={}, continuation_parameters={})\n"
    )
    assert not found  # an IfExp is computed: left to the runtime
    found = _deficits(
        "def build_controller_factory(goal_view, collaborators):\n"
        "    epoch = goal_view.get('epoch', 0)\n"
        "    return compose_controller(schema=S, epoch=epoch, credit_function=C,\n"
        "        rarefaction_function=R, continuation_function=K, credit_parameters={},\n"
        "        rarefaction_parameters={}, continuation_parameters={})\n"
    )
    assert any("epoch must be non-empty text" in item for item in found)


def test_correct_call_passes() -> None:
    assert not _deficits(
        "EPOCH = 'asm-next-probe-v1'\n"
        "F = compose_controller(schema=S, epoch=EPOCH, credit_function=C,\n"
        "    rarefaction_function=R, continuation_function=K, credit_parameters={},\n"
        "    rarefaction_parameters={'uncertainty_alpha': 0.05}, continuation_parameters={})\n"
    )


def test_positional_call_is_a_deficit() -> None:
    found = _deficits("F = compose_controller(S, 'e', C, R, K, {}, {}, {})\n")
    assert any("keyword-only" in item for item in found)


def test_contract_shows_the_keywords() -> None:
    text = emitter._MODULE_CONTRACT["builder_runtime"]["compose_controller"] if "compose_controller" in emitter._MODULE_CONTRACT.get("builder_runtime", {}) else None
    if text is None:
        text = next(
            value["compose_controller"]
            for value in emitter._MODULE_CONTRACT.values()
            if isinstance(value, dict) and "compose_controller" in value
        )
    assert "credit_function=" in text and "credit_parameters=" in text
    assert "keyword-only" in text
