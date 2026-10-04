"""Installation/doctor check for the optional systemd Target Workflow backend.

This runs only a bounded, credential-free namespace probe, not an Episode. It
uses the executor's service properties and never changes host security policy.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess

from hermes_platform.host.facts import os_family
from hermes_platform.resolver import locate_command
from openchia_cli.doctor_report import Finding, check_info, check_ok, check_warn, doctor_check

_GUIDE = "docs/openchia/systemd_setup.md"


def inspect_systemd_setup() -> dict:
    """Return JSON-ready observations; success proves namespaces, not an Episode Run."""
    report = {
        "backend": "systemd", "status": "unavailable", "summary": "Linux only",
        "observations": {}, "remediation": [],
    }
    if not os_family().startswith("linux"):
        return report
    commands = {name: locate_command(name).command for name in ("systemd-run", "systemctl", "env", "readlink")}
    missing = [name for name, command in commands.items() if not command]
    if missing:
        report["summary"] = f"Missing commands: {', '.join(missing)}"
        report["remediation"] = [f"Systemd execution prerequisites: {_GUIDE}"]
        return report

    from episode_runtime.executor import ExecutorResources, _systemd_properties

    unit = f"openchia-systemd-check-{secrets.token_hex(12)}.service"
    observations = report["observations"]
    observations["unit"] = unit
    try:
        manager = subprocess.run(
            [*commands["systemctl"], "--user", "show", "--property=Version", "--value"],
            capture_output=True, text=True, encoding="utf-8", timeout=5,
        )
        if manager.returncode:
            report["summary"] = "The current session cannot reach a user systemd manager"
            observations["detail"] = manager.stderr.strip()[-2048:]
            report["remediation"] = [f"Check the login session/user service manager: {_GUIDE}"]
            return report
        observations["systemd_version"] = manager.stdout.strip()
        paths = ("/proc/self/ns/mnt", "/proc/self/ns/net")
        host_namespaces = tuple(os.readlink(path) for path in paths)
        properties = _systemd_properties(ExecutorResources(None, None, 100, None, 100_000), ())
        # Watchdogs bound this diagnostic only; these are not Episode stopping rules.
        result = subprocess.run(
            [*commands["systemd-run"], "--user", "--quiet", "--collect", "--wait", "--pipe",
             f"--unit={unit}", "--property=RuntimeMaxSec=10s",
             "--property=TimeoutStartSec=10s", "--property=TimeoutStopSec=2s",
             *(f"--property={value}" for value in properties if value != "BindReadOnlyPaths="),
             *commands["env"], "-i", *commands["readlink"], *paths],
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        actual = tuple(result.stdout.splitlines())
        observations["returncode"] = result.returncode
        observations["detail"] = result.stderr.strip()[-2048:]
        observations["filesystem_namespace_isolated"] = (
            len(actual) == 2 and actual[0].startswith("mnt:[") and actual[0] != host_namespaces[0]
        )
        observations["network_namespace_isolated"] = (
            len(actual) == 2 and actual[1].startswith("net:[") and actual[1] != host_namespaces[1]
        )
        if result.returncode == 0 and all(observations[key] for key in (
            "filesystem_namespace_isolated", "network_namespace_isolated",
        )):
            report.update(status="ready", summary="Systemd filesystem/network namespace check passed")
            return report
        report.update(status="blocked", summary="Systemd could not establish the required namespaces")
    except (OSError, subprocess.TimeoutExpired) as exc:
        report.update(status="blocked", summary="Systemd setup check could not complete")
        observations["detail"] = str(exc)[-2048:]
        try:
            cleanup = subprocess.run(
                [*commands["systemctl"], "--user", "stop", unit],
                capture_output=True, text=True, encoding="utf-8", timeout=5,
            )
            observations["cleanup_returncode"] = cleanup.returncode
        except (OSError, subprocess.TimeoutExpired) as cleanup_error:
            observations["cleanup_error"] = str(cleanup_error)[-2048:]
    report["remediation"] = [
        f"Inspect this probe: journalctl --user -u {unit}",
        "For Ubuntu AppArmor user-namespace denials, review the launcher-specific profile; "
        f"do not disable AppArmor globally. Instructions: {_GUIDE}",
    ]
    return report


@doctor_check()
def check_episode_runtime(should_fix: bool, finding: Finding) -> None:
    """Security policy changes require operator approval, even with doctor --fix."""
    report = inspect_systemd_setup()
    if report["summary"] == "Linux only":
        check_info("Systemd Target Workflow backend: Linux only; container setup is separate")
        return
    if report["status"] == "ready":
        check_ok(report["summary"])
        check_info("Host setup check only; no Target Workflow or model was run")
        return
    check_warn(report["summary"], "(optional systemd backend)")
    for remedy in report["remediation"]:
        check_info(remedy)
    finding.manual_issues.append("Systemd Target Workflow backend not ready; see " + _GUIDE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable observations")
    args = parser.parse_args()
    if args.json:
        report = inspect_systemd_setup()
        print(json.dumps(report, sort_keys=True))
        return int(report["status"] != "ready")
    return int(bool(check_episode_runtime(False).manual_issues))


if __name__ == "__main__":
    raise SystemExit(main())
