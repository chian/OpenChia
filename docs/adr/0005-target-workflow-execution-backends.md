# ADR 0005: Target Workflow execution supports containers and systemd

Status: Accepted

Date: 2026-10-03

Implementation: both executors exist. Changing the Linux default and deriving
an explicit, recorded execution environment from the current project remain
implementation work. Systemd compatibility changes are tracked separately in
[ADR 0006](0006-support-systemd-255.md).

## Context

The **Target Workflow** is the scoped, nested Episode workflow being designed,
built, refined, tested or executed. It performs a defined task under its approved
contract; it is not an agent freelancing through the computer. The
**IterativeEpisodeRefiner** is the separate workflow that investigates, repairs
and verifies its implementation. A **candidate revision** is one exact
implementation state of the Target Workflow, not another name for the workflow.

The design distinction is between doing the task and iterating on the workflow
that will do the task. Executing a candidate revision must have its own defined
runtime, inputs and state so the refiner can tell exactly what it evaluated.
Matching the refiner's dependencies or settings does not combine their purposes,
state or authority. Results return through their defined interfaces.

The execution boundary is required; containers are one implementation, not the
definition of that boundary. A systemd sandbox can also provide it on Linux.
This is not based on an expectation that the Target Workflow will ignore its
scope; existing admission and confinement requirements remain in force.
Nor does the boundary require a separate process or container at every
parent-child Episode call: nested Episodes within one admitted Target Workflow
can share its Run.

Wilke's container implementation in [PR #7](https://github.com/chian/OpenChia/pull/7)
added macOS support while preserving systemd as the Linux default. Commit
`4b5f0e1eee` explicitly selected systemd when a Linux host had `systemd-run`,
otherwise containers. The CLI used that selector, and reasoning/continuation
tests also selected systemd directly. That was an implemented compatibility
choice, not a technical requirement that Linux Episode Runs avoid containers.

## Decision

### 1. Support both existing execution backends

Target Workflow Runs support the existing container executor on Linux and macOS
and the existing systemd executor on Linux. Containers are the default; systemd
is an explicitly selectable option. A default is a selection preference, not
an architectural dependency on containers.

Reuse the existing Run executor interface, worker, registration, brokers and
audit. Do not create a refiner-specific runner. Both backends implement the same
shared execution boundary, with backend-specific process isolation described in
[ADR 0006](0006-support-systemd-255.md). Record the selected backend and its effective
environment; do not silently fall back to another backend or in-process execution
when setup fails.

On macOS the Linux container daemon normally runs in a VM; on Linux it can run
directly. Both must satisfy the same Run confinement and identity checks. The
presence or version of host `systemd-run` must not select the normal Run backend.

### 2. Keep the refiner and Target Workflow execution boundary explicit

This decision does not relocate Duet, Builder or refinement orchestration from
their host environment, or remove existing restrictions on refiner Episodes.
Design/build work that does not execute a candidate must not require either
execution backend to be running. Runtime setup belongs to execution, not design.
The existing container factory already defers setup until execution is requested.

Whenever the human, refiner or testing Episode requests execution of a Target
Workflow candidate revision, that execution uses the separate Run boundary.
Its approved nested workflow runs there; nesting alone does not require
additional containers or grant children new creation authority.

Inputs, results, proposed edits and requests cross through existing typed,
authorized interfaces. The host owns admission, authoritative persistence,
credit and continuation validation. Target Workflow output is evidence to evaluate,
not authority to edit its evaluator or redefine acceptance. Neither backend
replaces the host's checks.

### 3. Default to the current project's environment, without its authority

The current project's resolved runtime environment and applicable settings are
the default starting specification for either backend. Resolve and freeze that
environment explicitly for execution; do not inherit the host's changing
environment live. Comparisons between candidate revisions keep the environment
fixed unless changing it is part of the declared experiment.

- Resolve the environment from the owning project/profile. Capture the Python
  version, relevant dependency versions, staged code and applicable nonsecret
  settings. Use the existing package-management and runtime-identity mechanisms;
  do not introduce a second dependency manager or environment record system.
- Recreate dependencies for the execution platform. Copying a macOS
  virtual-environment directory is not a valid Linux environment. Report any
  incompatibility or required substitution rather than silently claiming an
  exact copy. Dependency availability does not widen admitted imports or
  capabilities.
- Carry relevant environment variables and settings through an explicit
  nonsecret selection. Record the effective values and necessary execution-path
  translations with the existing Run inputs/identity. Do not copy the entire
  process environment or mount the host's live environment and home directory.
- Keep model/API credentials, login stores, approval state, host control sockets
  and writable audit/learning stores outside the candidate. In particular, do
  not expose the container daemon socket. Secret-backed settings remain host
  broker configuration, as required by
  [ADR 0002](0002-run-http-requests-are-host-brokered.md).
- Preserve model routing: the refiner uses its owning Duet's configuration;
  the Target Workflow uses its approved Target Workflow launch configuration. Reproducing
  dependencies or environment settings does not make those configurations
  interchangeable or pass credentials into the worker.

An explicitly selected target environment may differ from this default. Its
actual backend, interpreter, dependency identity, staged inputs, effective
settings and image identity (when containerized) must still be identified in the
Run evidence. A changed environment is visible to comparison
and replay; it is not an unnoticed repair of the candidate. A frozen environment
does not promise deterministic model replies or identical kernels across hosts.

### 4. Preserve confinement and honest failure reporting

Keep read-only staged inputs, bounded writable scratch, resource controls,
network isolation, and host-brokered model/HTTP requests. Keep existing worker
restrictions and confinement inspection. Do not weaken them to make a backend
launch pass.

Missing runtime access, unsupported systemd or kernel capabilities, or an invalid
image is an execution/setup failure, not proof that the candidate passed or
failed its task. Operational termination is not yield-based Episode completion.
Report the selected backend and the actual unmet prerequisite.

### 5. Keep backend mechanics behind their own interfaces

The systemd backend uses systemd's service-management interface for launch,
lifecycle, supported resource settings and inspection. OpenChia must not require
direct reads of `cpu.max`, a scan of the host's cgroup hierarchy, or custom cgroup
management as a prerequisite for systemd execution. Resource settings go through
the service interface; ancestor constraints remain systemd's responsibility.

Container cgroup setup and limits belong to the Docker-compatible runtime and
its executor adapter. They are not a shared prerequisite imposed on systemd.
Shared Run records describe execution identity, effective environment and
declared controls without forcing both backends to use the same low-level
inspection mechanism.

Systemd itself uses cgroups internally for resource control; this decision is
about what OpenChia manages, not a claim that systemd is cgroup-free. See
[systemd's resource-control documentation](https://github.com/systemd/systemd/blob/main/man/systemd.resource-control.xml).
Process isolation requirements are separate from CPU-allocation discovery;
[ADR 0006](0006-support-systemd-255.md) records the systemd 255 compatibility
decision and the host's whole-job control authority.

## Why not just a Python virtual environment?

A Python environment can reproduce package selection and is useful with either
backend. It is not the refiner/Target Workflow execution boundary. A process
using a different `venv` still has the operating-system permissions of the user running
it; changing Python's package directories does not prevent access to that user's
files, network or other available resources. Activation also does not provide an
independent, sanitized set of environment variables.

Python's [venv documentation](https://docs.python.org/3/library/venv.html)
describes package isolation and recommends recreating environments rather than
moving their directories. We need both dependency control and restrictions on
what executing code can access. A virtual environment supplies the former, not
the latter.

## Consequences and alternatives

- One execution interface covers Target Workflow Runs, including Runs requested
  by the unified testing harness. Backend choice does not change Episode semantics.
- Containers require runtime setup, image management and dependency rebuilds.
  They reduce ambient environment coupling but do not prevent choosing the wrong
  image, mounts or environment variables; explicit configuration remains necessary.
- Systemd avoids a container daemon and image lifecycle, but depends on the host's
  service manager and required kernel features. Interpreter and
  dependencies still need explicit selection. Containers are not automatically
  stronger, and systemd does not mean unrestricted execution in the Duet process.
- Linux containers share a kernel with their Linux host; an image alone is not
  a complete security boundary. Inspection, worker restrictions and the host's
  authority checks remain necessary.
- This decision neither approves any particular workflow nor changes its frozen
  topology, result schema, numerical controller or capability contract. It is
  independent of [ADR 0004](0004-interpret-the-episode-wiring-instead-of-emitting-it.md)'s
  proposed change to code generation.

## Implementation follow-through

Extend the existing selector, executors, shared Run records and unified harness.
Apply the container default while retaining explicit systemd selection. Implement
the environment reproduction described above without ambient credential
inheritance or a separate backend-specific record system. Replace the systemd
path's direct cgroup-allocation prerequisite with systemd-owned resource handling.
