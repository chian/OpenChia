# OpenChia

OpenChia is a terminal environment for designing, materializing, running, and
refining persistent nested Episode workflows through a human–LLM Duet.

```text
human <----> conversational LLM
                  |
                DUET
                  |
        Workflow Architecture
                  |
          exact human approval
                  |
            EpisodeBuilder
                  |
      Materialized Specification
                  |
          explicit human Run
                  |
          validated Run audit
                  |
      IterativeEpisodeRefiner
                  |
       proposed successor design
                  |
          exact human approval
```

The Duet is the human, a search-capable conversational LLM, and the host
protocol that joins them. It owns the complete Workflow Architecture. The LLM
cannot edit OpenChia, approve a design, build it, or run it. EpisodeBuilder and
IterativeEpisodeRefiner are separate host-controlled subsystems, not Agents or
Episodes.

Every task Episode has a stable identity, a goal, a repeated unit, a result,
numeric credit, a registered rarefaction function, a registered numerical
continuation function, declared capabilities, typed parent/child handoffs, and
its fixed place in the approved tree. Rarefaction measures the predicted value
of continuing from observed credit; Episodes continue while projected credit
supports more work and return when the registered numerical rule resolves.

## Start

From this checkout:

```bash
source ./activate
openchia
```

On first launch, OpenChia asks you to select an inference provider if one is not
already configured.

## Work with the Duet

Describe the workflow you want in ordinary conversation. The Duet can search
for design context, ask questions, and propose complete Architecture revisions.
The host validates and persists each proposal. `/approve` is the only operation
that freezes the exact current proposal.

`/episode` opens one Workspace with two distinct views:

- **Workflow Architecture** is the Duet-owned, human-approved design input to
  EpisodeBuilder.
- **Materialized Specification** is the detailed, source-linked result of one
  build of that Architecture.

Both views support part-level navigation, change highlighting, and exact human
notes. Architecture notes can guide the initial design. Materialized notes can
request implementation changes after inspection. An ordinary prompt after a
build is preserved as candidate guidance for both the semantic and
implementation layers so the Duet can resolve which layer it addresses without
losing the human's exact words.

The core controls are:

```text
/episode                         browse both Workspace views
/episode edit                    edit the mutable Workflow Architecture
/episode diff                    show stable changes in both views
/duet                            show authority, build, and Run state
/queue ...                       manage the foreground Duet FIFO
/bg ...                          work with additional independent Duets
/approve                         approve the exact current proposal
/decline                         reject a pending refinement proposal
/build [status]                  materialize or inspect the approved design
/run [status|evidence [RUN_ID]]  run or inspect one admitted materialization
/logs [RUN_ID]                   inspect a validated terminal Run audit
/stop                            cancel OpenChia-owned active work
/help                            show all OpenChia and session controls
```

Browsing and note-taking remain available while a Duet turn is active. Direct
Architecture replacement waits until that turn finishes. Background Duets have
the same Architecture, build, Run, evidence, and Workspace operations under
their own durable identities.

## Authority and execution boundaries

Human approval binds one exact Architecture artifact and content hash. `/build`
is a separate action: EpisodeBuilder plans leaf-first, emits one task-specific
module per Episode, statically admits the closed source package without loading
it, and records an immutable build receipt. `/run` is another separate action.

The Run worker executes a content-addressed staged package rather than the live
checkout. It verifies its complete local-source and interpreter identity before
imports, then activates generated modules only inside its filesystem and
syscall policies. Model calls cross a typed broker boundary. Terminal results
and chunked audit records are committed durably before they become refinement
evidence.

Run audit content is untrusted reference data, never an instruction channel.
The human may also request refinement before running, based on static inspection
of the Materialized Specification. A refinement produces a successor proposal;
it cannot alter the approved baseline or authorize another build. The human
must approve the successor explicitly.

See [OpenChia architecture](OPENCHIA_ARCHITECTURE.md) for ownership and runtime
boundaries and [Duet-owned Episode design](docs/openchia/duet_owned_episode_design.md)
for the materialization and refinement flow.

## Run execution backends

An approved, materialized workflow runs its Episodes under a host-inspected,
network-less, read-only executor. Two backends implement the same protocol and
evidence chain:

- **systemd** (Linux): a transient user service with cgroup ceilings,
  `ProtectSystem=strict`, private PID/network namespaces, Landlock ABI 7 and
  seccomp applied by the worker.
- **container** (macOS, or Linux without systemd): the same worker inside an
  OCI container launched through a Docker-compatible CLI (Docker Desktop,
  Rancher Desktop, Podman) with `--network none --read-only --cap-drop ALL
  --security-opt no-new-privileges`, the VM's cgroup allocation as the
  ceiling, and the image's interpreter identity pinned by digest. The
  container needs a Linux kernel with Landlock ABI 7 (6.15+); Rancher
  Desktop and Docker Desktop ship one.

The backend is chosen automatically. Override it with
`OPENCHIA_RUN_EXECUTOR=systemd|container`; pick the image with
`OPENCHIA_CONTAINER_IMAGE` (default `python:3.14-slim`, which must match the
host's Python minor version).

## Lineage and license

OpenChia uses the terminal and provider infrastructure originally developed in
[NousResearch/hermes-agent](https://github.com/nousresearch/hermes-agent). The
Episode method loop derives from nano-graphrag. Attribution and license details
are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [LICENSE](LICENSE), and
[method_loop/LICENSE](method_loop/LICENSE).
