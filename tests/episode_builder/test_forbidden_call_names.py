"""Only builtins and effect attributes are forbidden calls; a library attribute
that shares a builtin's name is not. Regression: an admitted-otherwise module
was blocked with ``direct_effect_forbidden: call 'compile'`` for
``re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")``."""

from __future__ import annotations

import ast

from episode_builder import admission


def _call(source: str) -> ast.Call:
    node = ast.parse(source).body[0].value
    assert isinstance(node, ast.Call)
    return node


def test_library_attribute_sharing_a_builtin_name_is_admitted() -> None:
    assert admission._forbidden_call_name(_call('re.compile(r"^[a-z]+$")')) is None
    assert admission._forbidden_call_name(_call("json.load(fh)")) == "load"  # a real effect attribute


def test_builtins_remain_forbidden_bare_and_through_the_builtins_module() -> None:
    assert admission._forbidden_call_name(_call('compile("x", "<s>", "exec")')) == "compile"
    assert admission._forbidden_call_name(_call('builtins.compile("x", "<s>", "exec")')) == "compile"
    assert admission._forbidden_call_name(_call("eval(x)")) == "eval"
    assert admission._forbidden_call_name(_call('open("f")')) == "open"


def test_effect_attributes_remain_forbidden() -> None:
    assert admission._forbidden_call_name(_call('os.system("ls")')) == "system"
    assert admission._forbidden_call_name(_call('path.write_text("x")')) == "write_text"
    assert admission._forbidden_call_name(_call("helper(x)")) is None
