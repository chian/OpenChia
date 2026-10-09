"""Per-role model and reasoning for refiner calls (openchia.refiner_roles).

Motivation (2026-10-09, mango Qwen3.8-27B): the server's best reasoning (xhigh)
is reachable only by omitting reasoning_effort, and is worth it for one long
Designer or emitter call but not for every step of a coding loop. A single Duet
route forced one setting on every refiner role.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.duet_episode_transport import DuetEpisodeBinding
from agent.refiner_role_routes import resolve_role_routes, role_scope, route_key, select_route

DUET_ROUTE = {"provider": "custom", "model": "Qwen3.8-27B", "base_url": "http://mango:8008/v1",
              "api_mode": "chat_completions", "reasoning": {"enabled": True, "effort": "medium"},
              "recovery": {"mode": "retry_on_healthy_probe"}}
PROVIDERS = [{"name": "Mango Coder", "base_url": "http://mango:8010/v1/", "model": "Qwen3-Coder-Next"},
             {"name": "Argo", "base_url": "https://argo/v1", "model": "Claude Opus 5", "key_env": "ARGO_KEY"}]
SPEC = {
    "designer": {"reasoning": "default"},
    "emitter": {"reasoning": "default"},
    "coder": {"custom_provider": "Mango Coder"},
    "implementer": {"reasoning": "low"},
    "measure": {"custom_provider": "Argo", "reasoning": "none"},
}


def _routes():
    return resolve_role_routes(SPEC, DUET_ROUTE, PROVIDERS)


def test_overrides_resolve_from_the_duet_route() -> None:
    routes = _routes()
    assert routes["designer"]["reasoning"] is None  # omitted on the wire -> server default
    assert routes["designer"]["model"] == "Qwen3.8-27B" and "key_env" not in routes["designer"]
    assert routes["implementer"]["reasoning"] == {"enabled": True, "effort": "low"}
    coder = routes["coder"]
    assert (coder["base_url"], coder["model"], coder["key_env"]) == ("http://mango:8010/v1", "Qwen3-Coder-Next", None)
    assert "reasoning" not in coder  # another server inherits no Duet reasoning
    assert routes["measure"]["reasoning"] == {"enabled": False} and routes["measure"]["key_env"] == "ARGO_KEY"
    assert all("recovery" in route for route in routes.values())


@pytest.mark.parametrize("spec, message", [
    ({"coder": {"custom_provider": "Nope"}}, "unknown custom provider"),
    ({"coder": {"temperature": 1}}, "unknown fields"),
    ({"coder": {"reasoning": "extreme"}}, "reasoning must be"),
    ({"coder": {}}, "needs a mapping"),
])
def test_invalid_overrides_are_rejected(spec, message) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_role_routes(spec, DUET_ROUTE, PROVIDERS)


def test_no_spec_means_no_overrides() -> None:
    assert resolve_role_routes(None, DUET_ROUTE, PROVIDERS) == {}


def test_selection_order_scoped_role_then_episode_then_designer_alias() -> None:
    routes = _routes()
    assert select_route(routes, DUET_ROUTE, "launch")[0] == "designer"
    assert select_route(routes, DUET_ROUTE, "implementer")[0] == "implementer"
    assert select_route(routes, DUET_ROUTE, "verify") == (None, DUET_ROUTE)
    with role_scope("emitter"):
        assert select_route(routes, DUET_ROUTE, "implementer")[0] == "emitter"


def test_keys_come_from_key_env_or_the_duet(monkeypatch) -> None:
    routes = _routes()
    monkeypatch.setenv("ARGO_KEY", "secret-from-env")
    assert route_key(routes["measure"], "duet-key") == "secret-from-env"
    assert route_key(routes["coder"], "duet-key") is None  # keyless provider
    assert route_key(routes["designer"], "duet-key") == "duet-key"


def _binding():
    record = {"route": DUET_ROUTE, "role_routes": _routes(), "model_types": ["refinement"], "session_id": "s"}
    return DuetEpisodeBinding("owner", {"artifact_id": "b"}, record, "duet-key")


def test_binding_for_role_gives_the_coder_its_route() -> None:
    coder = _binding().for_role("coder", "implementer")
    assert coder.record["route"]["model"] == "Qwen3-Coder-Next" and coder.api_key is None
    assert coder.record["refiner_role"] == "coder"
    plain = _binding().for_role("verify")
    assert plain.record["route"] is DUET_ROUTE


def test_transport_dispatches_each_call_on_its_role_route(monkeypatch) -> None:
    import agent.duet_episode_transport as transport_module
    from llm_call_library.transport import ModelTransportRequest

    seen = []

    async def fake_invoke(route, key, request, cancel, progress, *, record_activity):
        seen.append((route.get("model"), route.get("reasoning", "absent"), key))
        return "ok", route["model"]

    monkeypatch.setattr(transport_module, "invoke_pinned_route", fake_invoke)
    records = []
    transport = _binding().transport(record_attempt=records.append)

    def call(local_id):
        request = ModelTransportRequest(task="t", model_type="refinement", messages=({"role": "user", "content": "x"},),
                                        temperature=None, max_tokens=8, timeout=5, reasoning_config=None,
                                        main_runtime=None, episode_local_id=local_id)
        return asyncio.run(transport(request))

    call("launch")
    call("verify")

    async def emitter_call():
        with role_scope("emitter"):
            from llm_call_library.transport import ModelTransportRequest as Request
            return await transport(Request(task="t", model_type="refinement", messages=({"role": "user", "content": "x"},),
                                           temperature=None, max_tokens=8, timeout=5, reasoning_config=None,
                                           main_runtime=None, episode_local_id="asm_next_broker_probe"))

    asyncio.run(emitter_call())
    assert seen == [
        ("Qwen3.8-27B", None, "duet-key"),                                 # designer: reasoning omitted
        ("Qwen3.8-27B", {"enabled": True, "effort": "medium"}, "duet-key"),  # verify: the Duet's route
        ("Qwen3.8-27B", None, "duet-key"),                                 # emitter
    ]
    started = [r for r in records if r["state"] == "started"]
    assert [r.get("refiner_role") for r in started] == ["designer", None, "emitter"]


def test_default_reasoning_omits_reasoning_effort_on_the_wire() -> None:
    # _invoke sends reasoning_effort only when the route's reasoning is not None.
    import inspect

    from agent import episode_launch_transport

    source = inspect.getsource(episode_launch_transport._invoke)
    assert 'reasoning = route.get("reasoning", request.reasoning_config)' in source
    assert "if reasoning is not None:" in source
