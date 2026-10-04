"""Real agent construction and persisted routing; no model calls are made."""

import json

import pytest

from hermes_state import SessionDB
from openchia_cli.config import save_config
from openchia_cli.duet_cli import OpenChiaCLI


def background_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    # Credentials are resolved again on reopen, never serialized in the session.
    save_config({"providers": {
        "local-a": {"base_url": "http://127.0.0.1:9999/v1"},
        "local-b": {"base_url": "http://127.0.0.1:9998/v1"},
    }})
    cli = OpenChiaCLI.__new__(OpenChiaCLI)
    cli._initialize_background_duets()
    cli._session_db = SessionDB(tmp_path / "sessions.db")
    cli.session_id = "foreground"
    cli._session_db.create_session(cli.session_id, "openchia")
    cli.max_turns = 10
    cli.reasoning_config = None
    cli.service_tier = None
    cli._background_task_counter = 0
    cli._agent_running = False
    cli._app = None
    cli._background_tasks = {}
    cli._tool_names = lambda agent: ()
    for name in (
        "_providers_only", "_providers_ignore", "_providers_order", "_provider_sort",
        "_provider_require_params", "_provider_data_collection", "_openrouter_min_coding_score", "_fallback_model",
    ):
        setattr(cli, name, None)
    cli.route = {
        "model": "local-route-a",
        "runtime": {
            "provider": "custom", "requested_provider": "custom:local-a",
            "base_url": "http://127.0.0.1:9999/v1", "api_mode": "chat_completions",
            "api_key": "no-key-required",
        },
    }
    cli._resolve_turn_agent_config = lambda prompt: cli.route
    return cli


def test_background_agent_reopens_its_own_route_after_foreground_changes(tmp_path, monkeypatch):
    cli = background_cli(tmp_path, monkeypatch)
    contexts = []
    try:
        original = cli._create_background_duet("duet_route_a", "start")
        contexts.append(original)
        saved = cli._session_db.get_session(original.duet_id)
        route = SessionDB.session_gateway_runtime(saved)
        assert saved["model"] == original.agent.model
        assert route["base_url"] == original.agent.base_url
        cli.route = {"model": "local-route-b", "runtime": {
            **cli.route["runtime"], "base_url": "http://127.0.0.1:9998/v1",
            "requested_provider": "custom:local-b",
        }}
        second = cli._create_background_duet("duet_route_b", "start")
        contexts.append(second)
        assert second.agent.model != original.agent.model
        original.host.close()
        original.agent.close()
        contexts.remove(original)
        reopened = cli._restore_background_duet("duet_route_a", "status")
        contexts.append(reopened)
        assert reopened.agent.model == saved["model"]
        assert reopened.agent.base_url == route["base_url"]
        assert reopened.agent.requested_provider == route["provider"]
        assert reopened.agent._duet_identity == reopened.host.identity
    finally:
        for context in reversed(contexts):
            context.host.close()
            context.agent.close()
        cli._session_db.close()


@pytest.mark.parametrize("configuration,expected", [
    ("{broken", "invalid JSON"),
    ("[]", "must be an object"),
    (json.dumps({"gateway_runtime": {"provider": "nonexistent-test-provider"}}), "could not reopen"),
])
def test_background_reopen_reports_bad_route_without_rewriting_session(tmp_path, monkeypatch, configuration, expected):
    cli = background_cli(tmp_path, monkeypatch)
    output = []
    cli._print_openchia = output.append
    try:
        cli._session_db.create_session("duet_invalid_route", "openchia", model="saved-model")
        cli._session_db.update_session_meta("duet_invalid_route", configuration)
        before = cli._session_db.get_session("duet_invalid_route")
        assert cli._process_background_duet_command("/bg duet_invalid_route build continue")
        assert any(expected in line for line in output)
        assert "duet_invalid_route" not in cli._background_duets
        assert cli._session_db.get_session("duet_invalid_route") == before
    finally:
        cli._session_db.close()
