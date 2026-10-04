"""Installation diagnostics report real sandbox readiness without changing policy."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from openchia_cli import doctor_episode_runtime as diagnostic


@pytest.mark.platforms("linux")
def test_native_diagnostic_reports_observed_namespaces(monkeypatch):
    runtime_dir = Path("/run/user") / str(os.getuid())
    if (runtime_dir / "bus").exists():
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir / 'bus'}")
    result = subprocess.run(
        [sys.executable, "-m", "openchia_cli.doctor_episode_runtime", "--json"],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    report = json.loads(result.stdout)
    observations = report["observations"]
    if report["status"] == "ready":
        assert result.returncode == observations["returncode"] == 0
        assert observations["filesystem_namespace_isolated"]
        assert observations["network_namespace_isolated"]
        assert not report["remediation"]
    else:
        assert result.returncode == 1
        assert report["status"] in {"blocked", "unavailable"}
        assert report["remediation"]
        assert not (observations.get("returncode") == 0
                    and observations.get("filesystem_namespace_isolated")
                    and observations.get("network_namespace_isolated"))


@pytest.mark.platforms("linux")
@pytest.mark.parametrize("exit_code", [0, 226])
def test_accepted_properties_without_isolation_never_pass_or_change_policy(
    monkeypatch, exit_code, capsys,
):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "--property=Version" in command:
            return subprocess.CompletedProcess(command, 0, "255\n", "")
        # Emulate a manager accepting the settings but leaving host namespaces.
        return subprocess.CompletedProcess(command, exit_code, "\n".join(
            os.readlink(path) for path in ("/proc/self/ns/mnt", "/proc/self/ns/net")
        ) + "\n", "namespace denied" if exit_code else "")

    from hermes_platform.resolver import Candidate, Resolution

    monkeypatch.setattr(diagnostic, "locate_command", lambda name: Resolution(
        "explicit_path", (Candidate(f"/usr/bin/{name}", "fixture", True),),
    ))
    monkeypatch.setattr(diagnostic.subprocess, "run", run)
    report = diagnostic.inspect_systemd_setup()
    assert report["status"] == "blocked"
    assert not report["observations"]["filesystem_namespace_isolated"]
    assert not report["observations"]["network_namespace_isolated"]
    finding = diagnostic.check_episode_runtime(True)
    assert finding.manual_issues and finding.fixed == 0
    assert "AppArmor" in capsys.readouterr().out
    assert all(Path(command[0]).name in {"systemctl", "systemd-run"} for command in calls)
