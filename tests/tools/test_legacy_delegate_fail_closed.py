"""The retired model-facing delegation path cannot be restored."""

import json

import pytest

from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest
from tools.registry import ToolRegistry, registry


_SCHEMA = {
    "description": "legacy",
    "parameters": {"type": "object", "properties": {}},
}


def _handler(_args):
    return json.dumps({"legacy": True})


def test_delegate_task_name_is_reserved_for_builtins_and_plugins(tmp_path):
    registry = ToolRegistry()
    with pytest.raises(ValueError, match="reserved"):
        registry.register(
            name="delegate_task",
            toolset="legacy",
            schema=_SCHEMA,
            handler=_handler,
        )
    assert registry.get_entry("delegate_task") is None

    context = PluginContext(
        PluginManifest(name="legacy-plugin", source="user"),
        PluginManager(scope_key=str(tmp_path)),
    )
    with pytest.raises(ValueError, match="reserved"):
        context.register_tool(
            name="delegate_task",
            toolset="legacy",
            schema=_SCHEMA,
            handler=_handler,
        )


def test_delegate_task_is_absent_from_the_model_registry():
    assert registry.get_entry("delegate_task") is None
    result = json.loads(registry.dispatch("delegate_task", {}))
    assert result["error"] == "Unknown tool: delegate_task"
