# ADR 0010: Target Workflow environments follow candidate revisions

Status: Accepted

Date: 2026-10-05

## Context

An implementation that runs only in its coding agent's session is not a
reproducible Target Workflow. Independent validation and later Runs need the
same declared dependencies without inheriting that session's mutable state.
Installing dependencies into OpenChia's own Python or changing personal
configuration would cross the boundary established in ADR 0009.

## Decision

Implementer authors the Target Workflow's environment recipe as an ordinary
scoped candidate artifact, alongside its source. The host resolves that recipe
through OpenChia PM in the selected existing Run backend. The admitted build
retains the recipe and exact resolution. Coding diagnostics, validation and
ordinary Runs use this shared preparation service; no separate installer or
execution controller is added.

The recipe declares Python major/minor, bounded registry dependencies, permitted
top-level imports and explanatory setup instructions. Instructions are data,
not shell commands. The host retains the resolved lock and hashes the installed
files. Cache reuse requires the exact recipe, resolution and selected runtime
identity. A Run binds the prepared environment identity; continuation cannot
substitute a different dependency closure.

Preparation has narrowly scoped write access to managed output/cache and may
use installation network access. This does not grant network or write access
to the executing Target Workflow. The existing systemd or container backend
performs preparation. Native systemd preparation hides personal homes using
`ProtectHome=tmpfs`, with explicit read-only inputs and managed writable output.
It does not change host security policy or install system packages.

Dependency modules are not imported by the OpenChia host. The worker verifies
the exact dependency tree, then installs its registered syscall and filesystem
policies before allowing dependency imports. Dependencies and standard-library
resources are read-only. Unbound imports, writes, subprocesses and network
access remain denied by the worker boundary. Workflows without a recipe retain
the existing no-dependency policy.

Complete preparation stdout/stderr are retained in the existing Builder blob
store. Typed diagnostics and log references return through the existing
Implementer feedback and parent-report paths. A prepared environment is not
workflow correctness or progress credit. Existing measurement, independent
acceptance, rarefaction and continuation retain those responsibilities.

## Initial supported scope

The first implementation supports the selected backend's existing Python and
public PyPI wheels with a frozen lock. It rejects arbitrary URLs, source builds,
editable dependencies, executable startup hooks and packages shadowing runtime
modules. It does not install Python versions or OS packages. No private registry
credential reference is currently admitted: preparation receives no ambient
credentials or personal package-manager configuration. Supporting private
registries requires an explicit approved-reference policy, not environment
inheritance.

Native-wheel imports may fail if they need shared libraries or capabilities
outside the admitted read roots. Such failures are evidence for refinement, not
permission to relax confinement automatically. Container and non-Linux
availability follow the existing backend; this ADR does not assert verification
on an OS where the implementation has not been exercised.

## Consequences and verification

Environment edits are reviewed and versioned with code; an invalid recipe can
be repaired within the existing Episode loop. Fresh validation can reproduce
the environment without the coding transcript or workspace. Preparation remains
cancellable through the owning Run's existing task and backend lifecycle.

The BuildManifest schema requires explicit recipe and lock fields, including
`null` for builds without dependencies. Older artifacts missing those fields
must be rebuilt. There is no historical-artifact migration or compatibility
reader, consistent with this goal's scope.

Verification must distinguish the following: recipe/lock integrity, actual
backend preparation, dependency imports under confinement, and a real reasoning
agent producing a dependency-bearing implementation that passes independent
execution. Unit checks alone do not establish the last result.

The [Target Workflow environment guide](../openchia/target_workflow_environment.md)
records the interfaces, boundaries and current verification. This extends
[ADR 0009](0009-implementer-uses-an-existing-coding-agent.md) and preserves
[ADR 0005](0005-target-workflow-execution-backends.md) and
[ADR 0007](0007-build-owns-iterative-finalization.md).
