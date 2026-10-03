# ADR 0005: Target Workflow Runs use containers

Status: Accepted

Date: 2026-10-03

Implementation: the container executor exists. Changing the Linux default,
making acceptance explicitly container-only, and deriving the default container
environment from the current project remain implementation work. This record
does not claim those changes or a successful live acceptance Run.

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

We choose containers to implement that execution boundary consistently on Linux
and macOS. This is not based on an expectation that the Target Workflow will
ignore its scope; existing admission and confinement requirements remain in
force. The distinction alone does not make containers logically necessary.
Nor does it require a separate container at every parent-child Episode call:
nested Episodes within one admitted Target Workflow can share its Run.

Wilke's container implementation in [PR #7](https://github.com/chian/OpenChia/pull/7)
added macOS support while preserving systemd as the Linux default. Commit
`4b5f0e1eee` explicitly selected systemd when a Linux host had `systemd-run`,
otherwise containers. The CLI used that selector, and reasoning/continuation
tests also selected systemd directly. That was an implemented compatibility
choice, not a technical requirement that Linux Episode Runs avoid containers.

## Decision

### 1. Use the existing container executor on both platforms

Target Workflow Runs default to `ContainerRunExecutor` on Linux and macOS. The
acceptance path selects it explicitly. Neither path automatically falls back to
systemd or in-process execution when container setup is unavailable.

Reuse the existing Run executor, worker, registration, brokers and audit. Do not
create a refiner-specific runner. The systemd backend may remain an explicitly
selected alternative for its own use and coverage; it is not acceptance evidence
for the container path or a prerequisite for that path to work.

On macOS the Linux container daemon normally runs in a VM; on Linux it can run
directly. Both must satisfy the same Run confinement and identity checks. The
presence or version of host `systemd-run` must not select the normal Run backend.

### 2. Keep the refiner and Target Workflow execution boundary explicit

This decision does not relocate Duet, Builder or refinement orchestration from
their host environment, or remove existing restrictions on refiner Episodes.
Design/build work that does not execute a candidate must not require a running
container daemon. The existing container factory already defers runtime setup
until execution is requested.

Whenever the human, refiner or testing Episode requests execution of a Target
Workflow candidate revision, that execution uses the separate Run boundary.
Its approved nested workflow runs there; nesting alone does not require
additional containers or grant children new creation authority.

Inputs, results, proposed edits and requests cross through existing typed,
authorized interfaces. The host owns admission, authoritative persistence,
credit and continuation validation. Target Workflow output is evidence to evaluate,
not authority to edit its evaluator or redefine acceptance. The container
supports this separation; it does not replace the host's checks.

### 3. Default to the current project's environment, without its authority

The default is to reproduce the current project's resolved runtime environment
and applicable settings inside the container, rather than require an unrelated
environment to be configured by hand. This is a frozen, inspectable reproduction
for a Run, not live inheritance of the host's changing environment.

- Resolve the environment from the owning project/profile. Capture the Python
  version, relevant dependency versions, staged code and applicable nonsecret
  settings. Use the existing package-management and runtime-identity mechanisms;
  do not introduce a second dependency manager or environment record system.
- Recreate dependencies for the container's Linux platform. Copying a macOS
  virtual-environment directory is not a valid Linux environment. Report any
  incompatibility or required substitution rather than silently claiming an
  exact copy. Dependency availability does not widen admitted imports or
  capabilities.
- Carry relevant environment variables and settings through an explicit
  nonsecret selection. Record the effective values and necessary container-path
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
actual image, interpreter, staged inputs and effective settings must still be
identified in the Run evidence. A changed environment is visible to comparison
and replay; it is not an unnoticed repair of the candidate. A frozen environment
does not promise deterministic model replies or identical kernels across hosts.

### 4. Preserve confinement and honest failure reporting

Keep read-only staged inputs, bounded writable scratch, resource controls,
network isolation, and host-brokered model/HTTP requests. Keep existing worker
restrictions and confinement inspection. Do not weaken them to make a container
launch pass.

Missing runtime access, unsupported kernel capabilities or an invalid image is
an execution/setup failure, not proof that the candidate passed or failed its
task. Operational termination is not yield-based Episode completion. Report
container-path failures as such rather than making systemd repairs a dependency.

## Why not just a Python virtual environment?

A Python environment can reproduce package selection and is useful within a
container. It is not the refiner/Target Workflow execution boundary. A process
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

- One default execution mechanism covers Target Workflow Runs on Linux and macOS,
  including Runs requested by the unified testing harness. Acceptance tests
  must exercise that mechanism rather than hardcode a different backend.
- Containers require runtime setup and image management. That is a real cost;
  design-only work must remain usable without them.
- A properly configured systemd sandbox can also enforce isolation. Containers
  are not inherently required by Episode semantics or automatically stronger.
  We choose the shared container path and identifiable target environment rather
  than host-OS-dependent default execution.
- Linux containers share a kernel with their Linux host; an image alone is not
  a complete security boundary. Inspection, worker restrictions and the host's
  authority checks remain necessary.
- This decision neither approves any particular workflow nor changes its frozen
  topology, result schema, numerical controller or capability contract. It is
  independent of [ADR 0004](0004-interpret-the-episode-wiring-instead-of-emitting-it.md)'s
  proposed change to code generation.

## Implementation follow-through

Extend the existing selector, container executor, shared Run records and unified
harness. Change the default and the tests that directly choose systemd; keep
backend-specific tests accurately labeled. Implement the environment reproduction
described above without ambient credential inheritance. Verify real container
execution before claiming acceptance; this ADR alone supplies no such evidence.
