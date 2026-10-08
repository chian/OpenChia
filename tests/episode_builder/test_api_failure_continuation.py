"""Real SDK errors stop direct Builder calls.

The loopback endpoint supplies source fixtures, not a reasoning benchmark.
"""

import json

import pytest

from agent.duet_store import DuetStore
from agent.episode_launch import resolve_launch
from agent.episode_launch_transport import LaunchModelTransport
from episode_builder.evidence import model_call_evidence_for_attempt
from episode_builder.service import EpisodeBuilder
from episode_builder.store import BuildStore
from llm_call_library import CallOptions
from llm_call_library.transport import ModelCallFailed, model_transport_scope
from tests.agent.test_episode_model_failure_reporting import error_server
from tests.episode_runtime.test_reasoning_workflow import _approved_request, _plan_response, _module_response


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", [1, 2], ids=["planning", "emission"])
async def test_api_failure_stops_builder(tmp_path, fail_at):
    request = _approved_request(tmp_path)
    builds = BuildStore(tmp_path)
    builder = EpisodeBuilder(
        store=builds, planning_options=CallOptions(model_type="planner"),
        emission_options=CallOptions(model_type="writer"),
        model_slot_catalog={"selector": {}, "executor": {}},
    )

    def respond(body, ordinal):
        if ordinal == fail_at:
            return None
        prompt = json.loads(body["messages"][-1]["content"])
        return json.dumps(_plan_response(prompt) if "node" in prompt else _module_response(prompt))

    with error_server("chat_completions", "Server overloaded", respond=respond) as (endpoint, calls), DuetStore(tmp_path / "duet.db") as artifacts:
        launch = resolve_launch({
            "project": "builder-stop", "project_root": str(tmp_path), "env_files": [],
            "routes": {"primary": {
                "provider": "custom", "model": "fixture", "base_url": endpoint,
                "api_mode": "chat_completions", "auth": {"kind": "none"},
            }},
            "model_slots": {"planner": "primary", "writer": "primary"},
            "builder_slots": {"planning": "planner", "emission": "writer"},
        })
        receipts = []
        transport = LaunchModelTransport(launch, launch_id="builder-stop", record_attempt=receipts.append)
        with model_transport_scope(transport), pytest.raises(ModelCallFailed):
            await builder.build(request)
        assert len(calls) == fail_at
        assert builds.receipts_for_build_request(request.build_request_id) == ()
        attempt, = builds.attempts_for_build_request(request.build_request_id)
        original = model_call_evidence_for_attempt(builds, attempt)
        assert len(original) == fail_at
        assert sum(row["failure"] is not None and row["failure"]["kind"] == "model-call" for row in original) == 1
