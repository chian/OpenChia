"""A builder with defaults or varargs is reported as such, not as ``received None``."""

from __future__ import annotations

import pytest

from episode_builder import emitter

MODULE = '''
from types import MappingProxyType
REQUEST_PAYLOAD_CONTRACT = None
RESULT_PAYLOAD_CONTRACT = None
PROMPTS = ()
EXECUTION_CAPABILITY_NAMES = ()
RESULT_CHANNEL_NAMES = ()
RESULT_CHANNEL_IDS = ()
BINDING = None
DESIGN = None
def build_goal_state(request, collaborators):
    return {}
def scope_goal_state(goal_state, goal):
    return MappingProxyType({"goal": goal})
def build_controller_factory(goal_view, collaborators, http_json_fn=None):
    return None
def build_episode(grain, key, request, goal_view, collaborators, child_builders):
    return None
'''


def test_defaulted_builder_parameter_is_named_in_the_error() -> None:
    with pytest.raises(emitter.EpisodeEmissionError) as caught:
        emitter._validate_module_source(
            MODULE, local_id="root", target_module_name="built_episode_test",
            forbidden_module_names=(), is_root=True,
        )
    assert caught.value.code == "builder_signature_invalid"
    assert "default values, *args/**kwargs" in caught.value.detail
    assert "received None" not in caught.value.detail


def test_contract_states_builder_signatures_are_exact() -> None:
    text = emitter._MODULE_CONTRACT["exports"]["builder_signatures_are_exact"]
    assert "no default values" in text and "no *args/**kwargs" in text
