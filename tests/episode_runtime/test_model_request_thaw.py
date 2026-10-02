"""A worker's frozen MODEL_REQUEST body must reach the host broker as plain
JSON (issue #21): the decoder turns lists into tuples for hashing, and the
broker contract requires a two-item ``list`` of messages."""

from __future__ import annotations

import ast
import inspect
import textwrap

from episode_runtime import broker, executor, protocol

REQUEST = {
    "task": "episode_structured_json_fast",
    "messages": [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ],
    "temperature": 0.0,
    "max_tokens": 128,
    "timeout": 30,
    "reasoning_config": None,
    "main_runtime": None,
}


def test_frozen_request_is_rejected_until_thawed() -> None:
    frozen = protocol._freeze_json(REQUEST, "request")
    assert isinstance(frozen["messages"], tuple)
    try:
        broker.admit_model_request(frozen)
    except broker.ModelBrokerError:
        pass
    else:  # pragma: no cover - the premise of the regression
        raise AssertionError("frozen request unexpectedly admitted")
    admitted = broker.admit_model_request(protocol._thaw_json(frozen))
    assert admitted.task == REQUEST["task"]


def test_executor_thaws_the_model_request_before_admission_and_brokering() -> None:
    source = inspect.getsource(executor._RunExecutorBase.execute)
    tree = ast.parse(textwrap.dedent(source))
    thawed_names: set[str] = set()
    broker_arguments: list[str] = []
    admit_arguments: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            callee = node.value.func
            if isinstance(callee, ast.Name) and callee.id == "_thaw_json":
                thawed_names.update(
                    target.id for target in node.targets if isinstance(target, ast.Name)
                )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "model_broker" and node.args:
                broker_arguments.append(ast.unparse(node.args[0]))
            if node.func.id == "admit_model_request" and node.args:
                admit_arguments.append(ast.unparse(node.args[0]))
    assert admit_arguments and set(admit_arguments) <= thawed_names
    assert broker_arguments and set(broker_arguments) <= thawed_names
