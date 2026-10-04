# ADR 0006: Support systemd 255 with host-controlled job lifecycle

Status: Accepted

Date: 2026-10-03

Implementation: launcher, inspection, attestation and resource-discovery changes
are included in the PR #33 checkpoint. The operator-approved, launcher-specific AppArmor profile
now permits this host's namespace setup without an OS upgrade or global policy
disablement. Native service lifecycle and confined worker continuation checks
pass. Installation and doctor share a bounded setup diagnostic; see the
[setup guide](../openchia/systemd_setup.md). Exact verification scope is in the
[verification receipts](../openchia/unified_episode_test_harness_receipts.md).

## Context

OpenChia supports systemd as an execution backend for a Target Workflow, as
described in [ADR 0005](0005-target-workflow-execution-backends.md). The current
development host runs Ubuntu 24.04 with systemd 255.

The previous executor unconditionally requested `PrivatePIDs=yes`, and its
attestation validation required a private process namespace. That setting was introduced
in systemd 257. Systemd 255 rejects the unknown setting before starting the
worker; this is not a disabled setting that an operator can enable. See the
[versioned systemd documentation](https://github.com/systemd/systemd/blob/v257/man/systemd.exec.xml).

A private PID namespace limits which processes a worker can see and address.
It is distinct from Python dependency selection, environment-variable
separation, filesystem restrictions and the Episode's declared scope. It is
also distinct from the host's authority: a private PID namespace does not
prevent the host from observing or terminating its processes.

## Decision

### Support systemd 255 directly

Systemd 255 is a supported baseline. The systemd executor does not require
`PrivatePIDs`, an OS upgrade, or an additional namespace launcher to reproduce
that feature. It runs the Target Workflow in a separate systemd service without
requiring a private PID namespace.

Keep the other agreed execution boundaries: exact admitted code and runtime
identity, explicit interpreter and environment, read-only staged inputs,
restricted filesystem access, network isolation, host-brokered external
requests, worker syscall restrictions and typed host/worker communication.
Removing the private-PID requirement does not remove those controls or grant
the Target Workflow additional capabilities.

### Record the actual isolation provided

The systemd executor must not report a private process namespace when it did not
create one. Its attestation records that fact as false, and validation accepts
that backend's declared isolation requirements. Container validation continues
to require its private process namespace. Existing audit records remain intact;
do not rewrite them or treat missing evidence as successful inspection.

### Keep whole-job authority with the Duet's host

The Duet exercises job-control authority through the host, outside the Target
Workflow. The host retains the exact service identity and the ability to cancel
or forcibly terminate the entire job, including any descendant processes.
Stopping only a launcher or the main PID is insufficient.

Use systemd's service-level stop/kill operations and whole-service termination
policy. Preserve identity checks so a stale request cannot stop an unrelated
service. Confirm termination before treating the execution as stopped or
resuming its interrupted work. An operational stop is not yield-based Episode
completion and remains distinguishable in the audit.

### Leave systemd's internals to systemd

Use systemd's interfaces for service lifecycle and supported resource controls.
Do not require OpenChia to read `cpu.max`, scan host cgroup limits or manage
cgroups before it can launch a systemd job. Systemd's own internal use of cgroups
does not make direct OpenChia cgroup management necessary. This follows the
backend responsibility boundary in ADR 0005.

## Consequences

- Target Workflow execution can use the systemd 255 baseline without demanding
  a machine-wide service-manager upgrade solely for private process IDs.
- Systemd and container execution have explicitly different process-isolation
  guarantees, while sharing the Episode contracts, host authority and Run records.
- Backend compatibility does not override a host's other security policies or
  silently disable its protections. Any separate unmet prerequisite must be
  reported specifically.

## Implementation scope

Update the existing systemd launcher, inspection and attestation validation,
resource discovery and whole-job lifecycle handling. Reuse the existing executor
and unified harness. Do not introduce a refiner-specific runner, alter the
numerical continuation rules, or change the container default decision here.
