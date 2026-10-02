"""An ``async def`` generated component is a present top-level function.

Components that call the brokered libraries (``http_json``, ``http_request``)
must be async, so admission and the emitter's pre-check index both kinds of
def; only the four runtime-called builders stay synchronous."""

from __future__ import annotations

import ast

import pytest

from episode_builder import admission, emitter

_ROOT_MODULE = '''
import types
from types import MappingProxyType

REQUEST_PAYLOAD_CONTRACT = None
RESULT_PAYLOAD_CONTRACT = None
PROMPTS = ()
EXECUTION_CAPABILITY_NAMES = ()
RESULT_CHANNEL_NAMES = ()
RESULT_CHANNEL_IDS = ()
BINDING = None
DESIGN = None


async def execute_probe(unit, call_json):
    return await call_json("GET", unit)


def build_goal_state(request, collaborators):
    return {}


def scope_goal_state(goal_state, goal):
    return MappingProxyType({"goal": goal})


def build_controller_factory(goal_view, collaborators):
    return None


def build_episode(grain, key, request, goal_view, collaborators, child_builders):
    return None
'''


def test_top_level_index_includes_async_defs() -> None:
    tree = ast.parse("async def execute_probe(unit): ...\ndef build_episode(): ...\n")
    assert set(admission._top_level_functions(tree)) == {"execute_probe", "build_episode"}


def test_emitter_precheck_accepts_async_component() -> None:
    emitter._validate_module_source(
        _ROOT_MODULE,
        local_id="root",
        target_module_name="built_episode_test",
        forbidden_module_names=(),
        is_root=True,
    )


def test_async_builder_is_still_rejected() -> None:
    source = _ROOT_MODULE.replace(
        "def build_episode(grain", "async def build_episode(grain"
    )
    with pytest.raises(emitter.EpisodeEmissionError) as caught:
        emitter._validate_module_source(
            source,
            local_id="root",
            target_module_name="built_episode_test",
            forbidden_module_names=(),
            is_root=True,
        )
    assert caught.value.code == "builder_async_forbidden"
