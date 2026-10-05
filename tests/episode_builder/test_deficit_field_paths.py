"""Every literal deficit field_path admission can emit must satisfy
BuildDeficit's shape rule; an invalid one turns a deficit into a crashed
admission (``source_inspection_failure: deficit field_path has an invalid
shape``), which is what happened the first time binding_contract_mismatch fired."""

from __future__ import annotations

import ast
import inspect

from episode_builder import _contract_base, admission


def _literal_field_paths() -> set[str]:
    tree = ast.parse(inspect.getsource(admission))
    paths: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in {"add", "_deficit"} or len(node.args) < 2:
            continue
        path = node.args[1]
        if isinstance(path, ast.Constant) and isinstance(path.value, str):
            paths.add(path.value)
        elif isinstance(path, ast.JoinedStr):
            # f"module_source.{name}": check the literal prefix only
            literal = "".join(v.value for v in path.values if isinstance(v, ast.Constant))
            paths.add(literal.rstrip(".") or "module_source")
    return paths


def test_every_literal_deficit_path_has_a_valid_shape() -> None:
    paths = _literal_field_paths()
    assert "module_source.binding" in paths
    bad = sorted(p for p in paths if _contract_base._FIELD_PATH.fullmatch(p) is None)
    assert bad == [], bad


def test_binding_mismatch_deficit_constructs() -> None:
    deficit = admission._deficit(
        "binding_contract_mismatch", "module_source.binding", "x", local_id="root"
    )
    assert deficit.field_path == "module_source.binding"
