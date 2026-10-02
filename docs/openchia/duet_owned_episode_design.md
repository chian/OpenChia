# Duet-owned Episode design

The Duet is the human and conversational LLM working together through a host
that preserves identity and authority. It owns the complete Workflow
Architecture. The Duet is not an Episode, and the conversational LLM cannot
approve, build, or execute task work.

```text
conversation / exact notes
           |
           v
 Workflow Architecture proposal
           |
     human approval
           |
           v
     EpisodeBuilder
           |
 Materialized Specification
           |
       human Run
           |
           v
   validated Run audit
           |
           v
 IterativeEpisodeRefiner
           |
 successor proposal -> human approval -> fresh build
```

## Architecture admission

Each workflow node is a task-specific Episode with a durable local ID, goal,
repeatable unit, result, numeric credit, exact registered rarefaction and
continuation selections, capabilities, deliverable, and typed edges. The
topology is complete before approval.

Function selections are approved data, not planner choices. Each selection
contains its library, function ID, interface, immutable definition ID, and
function-specific arguments. The host exposes the catalog from the actual
function registries and validates arguments through that definition. Missing,
stale, or mismatched selections are Architecture deficits.

An optional reference Episode is design evidence. It can reduce repeated
description, but it never fills an omitted field or changes the active
Architecture by itself.

## EpisodeBuilder

EpisodeBuilder has four responsibilities with explicit intermediate artifacts:

1. Admit and persist the exact approved input.
2. Derive a leaf-first materialization plan while preserving every frozen
   structural and numerical value.
3. Emit one task-specific source module per Episode plus host-owned literal
   declarations that bind source to plan and approval.
4. Compile and inspect the complete package without importing it, then persist
   its manifest and terminal build receipt.

The host supplies structural facts: Episode and parent identities, child
topology, capability subsets, result-channel identities, handoff targets,
reference hashes, and exact numerical function records. The planning model
writes implementation details and task-specific prompts. Its structured return
must echo the host-owned values exactly. A mismatch is a blocking finding.

The finalized child node plan is the sole source for the child identity,
interface, and request/result payload contracts repeated by its parent's edge.
The Builder instantiates those exact values in the parent planner's output
template. The planner writes the parent-owned slot name and request/result
projection specifications around them while those child facts remain
field-identical. Slot names describe the child's role in that parent and match
the edge binding roles and child-builder keys. Admitted edges store their
payload contracts directly from the finalized child plan.
Structural admission bindings use the exact
library definition selected by node position and carry the same complete
payload-contract records. Generic empty handoff examples express schema
notation; task-specific edges carry the finalized child's exact vocabulary.

The source package is immutable and human-readable. It contains each Episode
module, the approved input, the plan, inspection findings, and the manifest
that binds their hashes. Building does not import generated Python, construct
an Episode tree, or claim runtime success.

## Composition boundary

A parent module declares child slots and typed request/result projections. It
does not import a concrete child module. The runtime linker supplies exact
child builders from the admitted manifest. A child result is first correlated
to the matching request and admitted stable result channels, then projected
onto the parent's credit scale.

Every module declares the collaborators it uses. Capability inheritance is
checked against the approved parent/child relation. Effectful work crosses a
declared collaborator boundary rather than an undeclared filesystem, process,
network, or import path.

## Numerical method

Credit assignment owns accepted identities, normalization, and marginal
dominated hypervolume. Rarefaction consumes only numeric paired-incidence
history derived from that credit state. The registered continuation function
consumes the projected marginal-credit band and the exact approved arguments.
The resulting numeric verdict controls continuation and return through the
Episode tree.

Parents recompute credit from distinct identities by result channel on their
own scale. Child hypervolumes are not additive. A log, source text, or model
explanation has no authority to override the numeric controller.

## Isolated Run

A Run consumes one exact admitted build receipt. Before launch, the host stages
a content-addressed closure containing the generated package and every local
runtime source module, plus the selected interpreter and standard-library
identity. The worker verifies that identity before application imports. Its
closed source finder admits only the staged modules.

The worker enters filesystem confinement and syscall filtering before it
activates generated code. A typed broker mediates allowed model calls. Run
state advances through registered, claimed, and terminal protocol phases.
Results and chunked audit manifests are written durably and correlated to the
Run, build, package, and runtime identities before terminal acknowledgement.

Run records contain typed inputs, measurements, transitions, errors, terminal
results, and log artifacts. Their paths are host-issued references. Audit text
is never injected as an instruction.

## One Workspace, two views

The Workspace combines related but non-interchangeable views:

- **Workflow Architecture** shows the Duet-owned semantic design that the human
  can edit and approve.
- **Materialized Specification** shows the detailed implementation of one build
  with source symbols, prompts, bindings, findings, and hashes.

Both use the same stable Episode IDs so the human can navigate from a design
node to its implementation. Each retains an independent diff baseline and
change markers. Human notes bind to an exact view, Episode, part, JSON pointer,
baseline artifact, and hash. Reading and note-taking continue while the Duet is
working; a direct Architecture replacement is admitted only against the still
current idle authority head.

## IterativeEpisodeRefiner

IterativeEpisodeRefiner is a host subsystem with three modular concerns:

1. **Baseline selection** pins one approved Architecture and one exact admitted
   materialization, plus validated terminal Run evidence when available.
2. **Change analysis** binds exact human notes to the named parts and records
   their target coverage and semantic-versus-implementation classification.
3. **Proposal production** returns a successor proposal to the Duet with a
   traceable diff and lineage to its baseline.

Static implementation refinement is valid before a Run. After a Run, validated
audit records add measured behavior to the same process. Generated source and
Run records remain untrusted reference material: they can inform a proposal but
cannot issue instructions or change its authority target.

Only explicitly addressed Episodes enter a targeted successor build. An exact
global directive addresses every Episode. Unaffected Episode plans and source
modules are reused byte-for-byte from the pinned baseline.

The refiner cannot alter an approved artifact, approve its proposal, start a
build, or start a Run. The human accepts or declines the proposal through the
Duet. Acceptance creates a new approved Architecture for a semantic change, or
an approved implementation decision against the unchanged Architecture for an
implementation-preserving change. The later explicit `/build` action creates
the fresh build lineage.

## Human action boundaries

- Conversation and notes can produce an Architecture or refinement proposal.
- `/approve` records the human decision over the exact current proposal.
- `/build` materializes the exact current approval.
- `/run` executes the exact current admitted build.
- `/decline` rejects a pending refinement while preserving its approved
  baseline.

Each action checks that the authority head and baseline identities are still
the ones the human inspected. Concurrent changes fail as conflicts instead of
being merged implicitly.
