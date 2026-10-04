"""Real launch-file/credential resolution, with no model calls or home writes."""

import json
import os
from pathlib import Path
import stat

import pytest

from agent.episode_launch import read_launch_spec, resolve_launch
from openchia_cli.episode_launch_setup import save_setup
from openchia_cli.episode_test_command import main


def launch_spec(root, model):
    return {
        "project": model,
        "project_root": str(root),
        "env_files": [],
        "routes": {
            "reasoning": {
                "provider": "custom",
                "model": model,
                "base_url": "http://127.0.0.1:9999/v1",
                "api_mode": "chat_completions",
                "auth": {"kind": "env", "env": "PROJECT_KEY", "account": model},
                "fallbacks": [],
            },
            "fast": {
                "provider": "custom",
                "model": model + "-fast",
                "base_url": "http://127.0.0.1:9998/v1",
                "api_mode": "chat_completions",
                "auth": {"kind": "none"},
                "fallbacks": [],
            },
        },
        "model_slots": {"deliberate": "reasoning", "cheap": "fast"},
        "builder_slots": {"planning": "deliberate", "emission": "cheap"},
    }


def test_setup_keeps_projects_and_secrets_separate_and_reuses_launch_resolution(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("PROJECT_KEY", "unrelated-ambient-key")
    before = dict(os.environ)
    secrets = {"a": "private-A-token 'quoted'#\\tail", "b": "private-B-token"}
    receipts = {
        name: save_setup(
            tmp_path / name, launch_spec(tmp_path, name), {"PROJECT_KEY": value}
        )
        for name, value in secrets.items()
    }
    for name in ("a", "b", "a"):
        receipt = receipts[name]
        launch = resolve_launch(read_launch_spec(receipt["launch_file"]))
        assert launch.credentials == {"reasoning": secrets[name], "fast": None}
        assert launch.configuration_hash == receipt["configuration_hash"]
        assert launch.route_names("cheap") == ("fast",)
        assert launch.route_names(launch.builder_model_type("planning")) == ("reasoning",)
        assert launch.route_names(launch.builder_model_type("emission")) == ("fast",)
        assert receipt["model_slots"] == launch.record["resolved_spec"]["model_slots"]
        assert receipt["builder_slots"] == launch.record["resolved_spec"]["builder_slots"]
        assert not receipt["activated"] and not receipt["approved"]
        assert receipt["next"][-1] == "/launch approve HASH_FROM_PREVIEW"
        public = Path(receipt["launch_file"]).read_text(encoding="utf-8") + json.dumps(
            receipt
        )
        assert all(secret not in public for secret in secrets.values())
    assert dict(os.environ) == before

    # The structured CLI uses the same file format and resolver; it neither
    # starts a chat nor borrows the ambient PROJECT_KEY.
    assert (
        main([
            "setup-launch",
            "--directory",
            str(tmp_path / "copy"),
            "--from",
            receipts["a"]["launch_file"],
        ])
        == 0
    )
    copied = json.loads(capsys.readouterr().out)
    assert (
        resolve_launch(read_launch_spec(copied["launch_file"])).credentials["reasoning"]
        == secrets["a"]
    )
    assert copied["credentials_written"] == []
    original = Path(receipts["a"]["launch_file"]).read_bytes()
    with pytest.raises(FileExistsError):
        save_setup(
            tmp_path / "a",
            launch_spec(tmp_path, "replacement"),
            {"PROJECT_KEY": "replacement-secret"},
        )
    assert Path(receipts["a"]["launch_file"]).read_bytes() == original


@pytest.mark.platforms("posix")
def test_setup_files_are_private_and_public_settings_cannot_contain_a_key(tmp_path):
    spec = launch_spec(tmp_path, "reasoner")
    receipt = save_setup(tmp_path / "private", spec, {"PROJECT_KEY": "private-token"})
    assert stat.S_IMODE((tmp_path / "private").stat().st_mode) == 0o700
    for name in ("launch_file", "credentials_file"):
        assert stat.S_IMODE(Path(receipt[name]).stat().st_mode) == 0o600
    spec["routes"]["reasoning"]["model"] = "accidentally-pasted-key"
    with pytest.raises(ValueError, match="credential value also appears"):
        save_setup(
            tmp_path / "invalid", spec, {"PROJECT_KEY": "accidentally-pasted-key"}
        )
    assert not (tmp_path / "invalid" / "launch.json").exists()


def test_register_launch_requires_exact_current_human_approval(tmp_path, capsys):
    from agent.openchia_host import OpenChiaHost

    setup = save_setup(
        tmp_path / "launch", launch_spec(tmp_path, "checked-model"),
        {"PROJECT_KEY": "test-only-credential"},
    )
    host = OpenChiaHost(
        home=tmp_path / "host",
        session_id="launch-registration",
        available_tool_names=(),
        agent_kwargs_factory=lambda *args: {},
    )
    try:
        host.configure_launch(setup["launch_file"])
        arguments = [
            "register-launch", "--file", setup["launch_file"],
            "--duet-store", str(host.store.path),
            "--duet-id", host.identity.duet_id.value,
        ]
        assert main(arguments) == 2
        assert "Human launch approval required" in json.loads(
            capsys.readouterr().out
        )["detail"]
        preview = host.preview_launch()
        host.approve_launch(preview["configuration_hash"])
        assert main(arguments) == 0
        registered = json.loads(capsys.readouterr().out)
        assert registered["configuration_hash"] == preview["configuration_hash"]
        assert registered["approval_ref"]["duet_id"] == host.identity.duet_id.value
        saved = host.store.get_artifact(registered["launch_ref"]["artifact_id"])
        assert saved["record"] == preview["configuration"]

        path = Path(setup["launch_file"])
        changed = json.loads(path.read_text(encoding="utf-8"))
        changed["model_slots"]["deliberate"] = "fast"
        path.write_text(json.dumps(changed), encoding="utf-8")
        assert main(arguments) == 2
        assert "Human launch approval required" in json.loads(
            capsys.readouterr().out
        )["detail"]
        # Registration did not rewrite the previously frozen launch or approve
        # the changed slot, and no model call was needed to enforce the boundary.
        assert host.store.get_artifact(saved["artifact_id"]) == saved
        assert not any(
            row["event_type"] == "model_launch_call"
            for row in host.store.events(host.identity.duet_id.value)
        )
    finally:
        host.close()
