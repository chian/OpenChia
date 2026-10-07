"""Credit result columns are the host-derived channel IDs, never the names.

Regression for a Run that died at ``episode_started`` with
``ValueError: result column must be a stable opaque ID``: the generated
``controller.schema`` function built ``ResultColumnSchema`` from
``RESULT_CHANNEL_NAMES`` (``"asm_health_observation"``, a human label) instead
of ``RESULT_CHANNEL_IDS``. Nothing in the module contract said which of the two
exported tuples is the credit column set, and admission did not look.
"""

from __future__ import annotations

import ast
from pathlib import Path

from episode_builder import admission, emitter

IDS = (
    "result_channel_d139fc544ac3dd4d567e5e5e77a807cb1d353ab94354d20310f0600322d55e22",
    "result_channel_ca6280ce722f1e63528a530bbe681353ca2da7d595cda5322c5cbbc629a24d4c",
)

PREAMBLE = (
    "from numeric_control_library import ResultColumnSchema\n"
    'RESULT_CHANNEL_NAMES = ("asm_health_observation", "asm_collections_observation")\n'
    f"RESULT_CHANNEL_IDS = {IDS!r}\n"
)


def _deficits(source: str) -> list[str]:
    return list(admission._result_column_deficits(ast.parse(PREAMBLE + source)))


def test_the_runs_actual_shape_is_a_deficit() -> None:
    # The emitted module: a parameter defaulting to the names, re-tupled.
    found = _deficits(
        "def schema(result_channel_names=RESULT_CHANNEL_NAMES):\n"
        "    columns = tuple(result_channel_names or ())\n"
        "    return ResultColumnSchema(columns=columns, reference_point=(0.0, 0.0))\n"
    )
    assert len(found) == 1
    assert "RESULT_CHANNEL_IDS" in found[0]
    assert "asm_health_observation" in found[0]


def test_direct_names_and_literals_are_deficits() -> None:
    assert _deficits("S = ResultColumnSchema(RESULT_CHANNEL_NAMES, (0.0, 0.0))\n")
    assert _deficits('S = ResultColumnSchema(columns=("report",), reference_point=(0.0,))\n')


def test_channel_ids_pass() -> None:
    assert not _deficits(
        "def schema():\n"
        "    return ResultColumnSchema(columns=RESULT_CHANNEL_IDS,"
        " reference_point=tuple(0.0 for _ in RESULT_CHANNEL_IDS))\n"
    )
    assert not _deficits("S = ResultColumnSchema(RESULT_CHANNEL_IDS, (0.0, 0.0))\n")


def test_computed_columns_are_left_to_the_runtime() -> None:
    # A parameter without a default shadows the module name of the same spelling.
    assert not _deficits(
        "def schema(RESULT_CHANNEL_NAMES):\n"
        "    return ResultColumnSchema(columns=tuple(RESULT_CHANNEL_NAMES), reference_point=(0.0, 0.0))\n"
    )
    assert not _deficits(
        "def schema(view):\n"
        '    return ResultColumnSchema(columns=tuple(view["ids"]), reference_point=(0.0, 0.0))\n'
    )


def test_inspection_reports_the_deficit_code() -> None:
    source = ast.parse(
        PREAMBLE
        + "S = ResultColumnSchema(columns=RESULT_CHANNEL_NAMES, reference_point=(0.0, 0.0))\n"
    )
    found = admission._result_column_deficits(source)
    assert found and "human labels" in found[0]
    wired = ast.parse(Path(admission.__file__).read_text(encoding="utf-8-sig"))
    calls = {
        node.args[0].value
        for node in ast.walk(wired)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "add"
        and node.args and isinstance(node.args[0], ast.Constant)
    }
    assert "result_columns_not_channel_ids" in calls


def test_contract_names_the_column_set() -> None:
    contract = emitter._MODULE_CONTRACT
    assert "credit result columns" in contract["exports"]["RESULT_CHANNEL_IDS"]
    rule = contract["credit_schema"]["rule"]
    assert "columns=RESULT_CHANNEL_IDS" in rule
    assert "never RESULT_CHANNEL_NAMES" in rule
    assert "columns=RESULT_CHANNEL_IDS" in contract["credit_schema"]["example"]
