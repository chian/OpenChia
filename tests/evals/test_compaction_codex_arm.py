"""The evaluation's Codex process and rollout lookup share OpenChia's home."""

import json
import os
from pathlib import Path
import runpy
import sys

import pytest

from openchia_cli.config import atomic_config_write


@pytest.mark.platforms("posix")
def test_eval_launch_and_rollout_lookup_ignore_personal_codex(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    personal = tmp_path / "personal-codex"
    personal.mkdir()
    personal_config = personal / "config.toml"
    personal_config.write_text('default_permissions = ":danger-full-access"\n', encoding="utf-8")
    original = personal_config.read_bytes()
    monkeypatch.setenv("HERMES_HOME", str(profile))
    monkeypatch.setenv("CODEX_HOME", str(personal))
    monkeypatch.setenv("CODEX_THREAD_ID", "personal-thread")
    binary = tmp_path / "codex"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "print(json.dumps({'argv': sys.argv[1:], 'codex_env': "
        "{k: v for k, v in os.environ.items() if k.startswith('CODEX_')}}))\n",
        encoding="utf-8",
    )
    binary.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    atomic_config_write(profile / "config.yaml", {"model": {"codex_bin": str(binary)}})
    script = Path(__file__).resolve().parents[2] / "evals/compaction/scripts/codex_arm.py"
    monkeypatch.setattr(sys, "argv", [str(script), "lineage.json", "questions.json", str(tmp_path), "out.json"])
    monkeypatch.setattr(sys, "path", list(sys.path))
    arm = runpy.run_path(str(script))
    for args in ([], ["resume", "owned-thread"]):
        observed = json.loads(arm["codex"](args, "test prompt"))
        assert observed["argv"] == ["exec", *args, "--skip-git-repo-check", "test prompt"]
        assert observed["codex_env"] == {"CODEX_HOME": str(profile / "codex")}
    for home in (profile / "codex", personal):
        rollout = home / "sessions/2026/10/05/rollout-session.jsonl"
        rollout.parent.mkdir(parents=True)
        rollout.write_text("{}\n", encoding="utf-8")
    assert Path(arm["newest_rollout"]()).is_relative_to(profile / "codex")
    assert personal_config.read_bytes() == original
    assert os.environ["CODEX_HOME"] == str(personal)
    assert os.environ["CODEX_THREAD_ID"] == "personal-thread"
