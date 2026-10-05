"""Invalid selector responses must not invent a reasoning action."""

import json

import pytest

from function_library.reasoning import ReasoningSource
from function_library.reasoning_transport import reasoning_transport_scope
from llm_call_library.transport import ModelTransportResponse, model_transport_scope


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response", [[], {}, {"action_inputs": {}, "retry_reason": ""}]
)
async def test_malformed_selection_never_requests_a_fallback_action(response):
    requested = []

    async def model(call):
        return ModelTransportResponse(json.dumps(response), {})

    async def learning(operation, payload):
        requested.append(payload)
        return {**payload, "permitted": False, "reason": "excluded"}

    bundle = {
        "next_ordinal": 0,
        "allowed_actions": ["verify"],
        "contract": {"allowed_actions": ["excluded", "verify"]},
    }
    with model_transport_scope(model), reasoning_transport_scope(learning):
        with pytest.raises(ValueError, match="selection"):
            await ReasoningSource("test", selection_model_type="selector", execution_model_type="executor")._select(bundle)
    assert requested == []
