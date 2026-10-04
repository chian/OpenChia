# Systemd setup for Target Workflow execution

OpenChia supports systemd 255 without `PrivatePIDs`. The Duet's host controls
the whole service, including termination of descendants. This is separate from
container setup and does not change model/provider configuration.

## Check during installation or later

Source installation (including unattended installation) and source-update
completion run the same check used by `hermes doctor`. It launches a short-lived
service using the executor's sandbox properties and compares its actual mount
and network namespaces with the host's. Merely accepting `PrivateNetwork=yes`
is insufficient: systemd can accept that property but skip creating a namespace.

Run just this diagnostic, with the installed project's Python environment:

```bash
python -m openchia_cli.doctor_episode_runtime --json
```

The result contains `backend`, `status`, `summary`, `observations` and
`remediation`. Status is `ready`, `blocked` or `unavailable`; JSON-mode exit status
is zero only for `ready`. The observations include the exact diagnostic service
name and the user manager's version. No Target Workflow, model call, credential
access or host configuration change occurs. The service has a short operational
timeout and is collected after exit. This checks host namespace setup, not
Builder admission, worker execution or reasoning correctness.

A warning does not prevent installation of Duet or design/build capabilities.
It means the optional systemd execution backend needs setup. Installation,
`--yes` and `hermes doctor --fix` never authorize a security-policy change.
Missing binaries and an inaccessible user manager are reported separately from
namespace failures. Run the check in the login session/account that will launch
Episodes; a disconnected user bus is not an AppArmor problem.

## Ubuntu 24.04 AppArmor restriction

Ubuntu can deny namespace capabilities to `/usr/lib/systemd/systemd-executor`.
The service journal then reports `226/NAMESPACE`; the kernel audit identifies
`apparmor="DENIED"`, `profile="unprivileged_userns"`, `capname="sys_admin"`
and the service launcher executable. Inspect the specific diagnostic unit from
the report and the kernel audit:

```bash
journalctl --user -u <diagnostic-unit>
sudo journalctl -k --since '10 minutes ago'
```

Do not assume every namespace failure is AppArmor. Missing kernel features,
another container's restrictions or a different policy need their own diagnosis.

For that confirmed Ubuntu denial, the reviewed profile is
[`scripts/apparmor/openchia-systemd-executor`](../../scripts/apparmor/openchia-systemd-executor).
It grants user-namespace use to the systemd launcher without disabling AppArmor
or changing the global unprivileged-user-namespace setting. Its scope is **all
services launched through that executable**, not just OpenChia. Review that
scope with the machine's administrator before installing it. Do not overwrite an
existing profile for this executable; reconcile the existing policy instead.

From a source checkout, after that review and approval:

```bash
apparmor_parser --skip-kernel-load --skip-cache scripts/apparmor/openchia-systemd-executor
sudo install -o root -g root -m 0644 scripts/apparmor/openchia-systemd-executor /etc/apparmor.d/openchia-systemd-executor
sudo apparmor_parser --replace /etc/apparmor.d/openchia-systemd-executor
python -m openchia_cli.doctor_episode_runtime --json
```

No reboot or systemd upgrade is required. A file on disk is not proof that the
profile is loaded or effective; rerun the diagnostic.

To undo only this newly installed profile, unload it and retain it outside
AppArmor's auto-loaded directory (choose an unused backup destination):

```bash
sudo apparmor_parser --remove /etc/apparmor.d/openchia-systemd-executor
sudo mv /etc/apparmor.d/openchia-systemd-executor /etc/openchia-systemd-executor.disabled
```

See [Ubuntu's release notes](https://documentation.ubuntu.com/release-notes/24.04/)
for the user-namespace restriction and executable-specific profile mechanism,
and [ADR 0006](../adr/0006-support-systemd-255.md) for OpenChia's backend decision.
