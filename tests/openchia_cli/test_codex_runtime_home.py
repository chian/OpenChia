"""Private configuration is shared by OpenChia's launcher, migration and sessions.

These check configuration isolation, not a model's coding ability.
"""

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from agent.secret_scope import set_multiplex_active
from agent.transports.codex_app_server_session import CodexAppServerSession
from agent.transports.hermes_tools_mcp_server import HERMES_TOOLS_MCP_SERVER_NAME
from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from openchia_cli.codex_runtime_home import DEFAULT_CODEX_CONFIG, prepare_codex_home
from openchia_cli.codex_runtime_plugin_migration import migrate
from openchia_cli.config import atomic_config_write


def test_profiles_and_migration_never_use_personal_codex_home(tmp_path, monkeypatch):
    personal = tmp_path / ".codex"
    personal.mkdir()
    personal_config = personal / "config.toml"
    personal_config.write_text('default_permissions = ":danger-full-access"\n', encoding="utf-8")
    original = personal_config.read_bytes()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(personal))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "launch-profile"))
    homes, sessions = [], []
    set_multiplex_active(True)
    try:
        for name in ("a", "b", "a"):
            profile = tmp_path / name
            token = set_hermes_home_override(profile)
            try:
                home = prepare_codex_home()
                report = migrate({}, discover_plugins=False)
                assert report.written and not report.errors
                assert report.target_path == home / "config.toml"
                assert home == profile / "codex"
                config = tomllib.loads(report.target_path.read_text(encoding="utf-8"))
                assert config["default_permissions"] == ":workspace"
                callback = config["mcp_servers"][HERMES_TOOLS_MCP_SERVER_NAME]
                assert callback["env"]["HERMES_HOME"] == str(profile)
                homes.append(home)
                sessions.append(CodexAppServerSession())
            finally:
                reset_hermes_home_override(token)
    finally:
        set_multiplex_active(False)
    # A deferred start keeps its original profile even outside that context.
    assert [session._codex_home for session in sessions] == list(map(str, homes))
    assert homes[0] == homes[2] and homes[0] != homes[1]
    assert personal_config.read_bytes() == original
    assert os.environ["CODEX_HOME"] == str(personal)
    assert sorted(path.name for path in personal.iterdir()) == ["config.toml"]


def test_repo_launcher_passes_private_home_only_to_child(tmp_path, monkeypatch):
    profile = tmp_path / "openchia"
    profile.mkdir()
    personal = tmp_path / "personal-codex"
    monkeypatch.setenv("HERMES_HOME", str(profile))
    monkeypatch.setenv("CODEX_HOME", str(personal))
    parent_codex = {"CODEX_THREAD_ID": "personal-thread", "CODEX_SESSION_ID": "personal-session",
                    "CODEX_PERMISSION_PROFILE": ":danger-full-access"}
    for name, value in parent_codex.items():
        monkeypatch.setenv(name, value)
    # A real Python child reports the launch environment without a model call.
    atomic_config_write(profile / "config.yaml", {"model": {"codex_bin": sys.executable}})
    probe = (
        "import json,os,pathlib; p=pathlib.Path(os.environ['CODEX_HOME']); "
        "print(json.dumps({'home':str(p),'config':(p/'config.toml').read_text(encoding='utf-8'),"
        "'codex_env':{k:v for k,v in os.environ.items() if k.startswith('CODEX_')}}))"
    )
    launcher = Path(__file__).resolve().parents[2] / "scripts" / "openchia-codex"
    result = subprocess.run([sys.executable, str(launcher), "-c", probe],
                            capture_output=True, text=True, encoding="utf-8", check=True)
    observed = json.loads(result.stdout)
    assert observed == {"home": str(profile / "codex"), "config": DEFAULT_CODEX_CONFIG,
                        "codex_env": {"CODEX_HOME": str(profile / "codex")}}
    config = profile / "codex" / "config.toml"
    config.write_text(DEFAULT_CODEX_CONFIG + "# operator-owned private setting\n", encoding="utf-8")
    before = config.read_bytes()
    assert prepare_codex_home() == profile / "codex"
    assert config.read_bytes() == before
    assert os.environ["CODEX_HOME"] == str(personal) and not personal.exists()
    assert {name: os.environ[name] for name in parent_codex} == parent_codex
