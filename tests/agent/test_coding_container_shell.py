"""Coding diagnostics run in a per-turn container, cwl-runner style (#72).

A fake Docker-compatible CLI records every invocation and executes ``exec``
commands locally, so the shell's lifecycle and argument contract are tested on
any host without a container runtime.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

from agent.transports.coding_container import CONTEXT_ROOT, ContainerCommandShell, container_shell_for
from agent.transports.refinement_chat import ChatCompletionsCodingSession

FAKE_CLI = r'''#!{python}
import json, os, subprocess, sys
log = os.environ["FAKE_CLI_LOG"]
with open(log, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\n")
verb = sys.argv[1]
if verb == "run":
    if os.environ.get("FAKE_CLI_FAIL_RUN"):
        sys.stderr.write("Cannot connect to the Docker daemon\n"); sys.exit(1)
    print("container-id"); sys.exit(0)
if verb == "exec":
    args = sys.argv[2:]
    workdir = args[args.index("--workdir") + 1]
    command = args[-1]
    sys.exit(subprocess.run(["/bin/sh", "-c", command], cwd=workdir).returncode)
sys.exit(0)
'''


def _fake_cli(tmp_path, monkeypatch, fail_run=False):
    cli = tmp_path / "fake-docker"
    cli.write_text(FAKE_CLI.replace("{python}", sys.executable), encoding="utf-8")
    cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "cli.log"
    monkeypatch.setenv("FAKE_CLI_LOG", str(log))
    if fail_run:
        monkeypatch.setenv("FAKE_CLI_FAIL_RUN", "1")
    return cli, log


def _calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8-sig").splitlines()] if log.exists() else []


def test_container_is_isolated_and_only_the_workspace_is_writable(tmp_path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    shell = ContainerCommandShell(cli="docker", image="sha256:abc", workspace=workspace,
                                  read_only_mounts=((tmp_path, CONTEXT_ROOT),),
                                  resource_arguments=("--memory", "1024"))
    arguments = shell.run_arguments("openchia-coder-x")
    joined = " ".join(arguments)
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges", "--rm"):
        assert flag in joined
    owner = workspace.stat()
    assert f"--user {owner.st_uid}:{owner.st_gid}" in joined
    volumes = [arguments[i + 1] for i, item in enumerate(arguments) if item == "--volume"]
    writable = [v for v in volumes if v.endswith(":rw")]
    assert writable == [f"{workspace.resolve()}:{workspace.resolve()}:rw"]
    assert all(v.endswith(":ro") for v in volumes if v not in writable)
    assert arguments[-3:] == ["sha256:abc", "sleep", "infinity"]
    assert "--memory" in arguments


def test_one_container_per_turn_and_commands_run_via_exec(tmp_path, monkeypatch) -> None:
    cli, log = _fake_cli(tmp_path, monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    shell = ContainerCommandShell(cli=cli, image="img", workspace=workspace)
    assert shell.run("echo hello > out.txt && cat out.txt", 30).startswith("exit 0\nhello")
    assert shell.run("pwd", 30).strip().endswith(str(workspace.resolve()))
    shell.close()
    verbs = [call[0] for call in _calls(log)]
    assert verbs == ["run", "exec", "exec", "rm"]


def test_timeout_removes_the_container_and_the_next_command_restarts_it(tmp_path, monkeypatch) -> None:
    cli, log = _fake_cli(tmp_path, monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    shell = ContainerCommandShell(cli=cli, image="img", workspace=workspace)
    assert "timed out after 1s (container removed)" in shell.run("sleep 5", 1)
    assert shell.run("echo again", 30).startswith("exit 0")
    shell.close()
    verbs = [call[0] for call in _calls(log)]
    assert verbs[:3] == ["run", "exec", "rm"] and verbs.count("run") == 2


def test_unavailable_runtime_is_reported_never_replaced_by_a_host_shell(tmp_path, monkeypatch) -> None:
    cli, log = _fake_cli(tmp_path, monkeypatch, fail_run=True)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    shell = ContainerCommandShell(cli=cli, image="img", workspace=workspace)
    result = shell.run("touch should-not-exist", 30)
    assert result.startswith("error: container shell unavailable") and "no host shell fallback" in result
    assert not (workspace / "should-not-exist").exists()
    assert [call[0] for call in _calls(log)] == ["run"]


def test_non_container_executors_keep_their_existing_path() -> None:
    assert container_shell_for(SimpleNamespace(), "/nonexistent") is None


def test_chat_adapter_routes_run_command_through_the_shell(tmp_path) -> None:
    class RecordingShell:
        def __init__(self):
            self.commands, self.closed, self.interrupted = [], False, False

        def run(self, command, timeout):
            self.commands.append((command, timeout))
            return "exit 0\nfrom-container"

        def interrupt(self):
            self.interrupted = True

        def close(self):
            self.closed = True

    shell = RecordingShell()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    binding = SimpleNamespace(api_key="k", record={"route": {
        "api_mode": "chat_completions", "model": "m", "provider": "custom", "base_url": "https://gw.test/v1"}})
    session = ChatCompletionsCodingSession(
        binding=binding, workspace=workspace, state_dir=tmp_path / "state", instructions="i",
        resume_thread_id=None, on_event=lambda _e: None, client_factory=lambda *_: None,
        command_shell=shell,
    )
    session.ensure_started()
    assert "isolated container" in session._messages[0]["content"]
    assert session._run_command("touch host-file", 5) == "exit 0\nfrom-container"
    assert shell.commands == [("touch host-file", 5)] and not (workspace / "host-file").exists()
    session.close()
    assert shell.closed and shell.interrupted
