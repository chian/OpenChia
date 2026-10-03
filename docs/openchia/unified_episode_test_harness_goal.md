# Goal: Build the unified Episode testing harness

Status: active implementation goal. The user has authorized building and validating
the shared harness, including real Episode experiments. Normal-build activation
remains excluded. The preceding bounded refiner coding assignment is complete.

Refiner baseline: `3e158ebb8a2fddf8a7ba69b6c2256bad39a791d7`, saved in
[draft PR #33](https://github.com/chian/OpenChia/pull/33) on
`feat/iterative-episode-refiner`. This dependent branch is
`feat/unified-episode-test-harness`; active work returns to
`/home/chia/repos/OpenChia`. Compare harness changes against that exact refiner
checkpoint (or the refiner branch while unchanged), not against main. PR #32's
explicit launch routing was subsequently merged into this development branch at
`0b3d90b395`; the saved refiner checkpoint itself is unchanged.

The original checkout's earlier design/guidance copies are preserved locally in
stash `d5c20282bc6868552b4bd738ab745a6c09ed5a0e`, named
`pre-harness-switch: original design and guidance copies (2026-10-02)`.
The current versions are already tracked in the refiner checkpoint. Do not apply
the old stash over them indiscriminately. The separate refiner worktree remains
on its clean saved branch; no other local worktree was switched or removed.

## Objective

Implement one shared testing harness through which Episodes can design, execute,
inspect, and compare experiments on Episode implementations and the iterative
refinement system itself. Make execution scope, replay behavior, evidence,
credit assignment, and numerical control explicit and accessible to both LLMs
and humans. Reuse existing runtime, persistence, admission, and measurement
infrastructure.

The testing Episode designs the experiment. The unified harness makes its choices
explicit, accessible, executable, and measurable. Scope is not a testing sequence
chosen in advance by the harness author or a decision delegated back to the user.

## Requirements

Routing clarification (2026-10-03): the IterativeEpisodeRefiner and its reasoning
children use the owning Duet's model/provider configuration. The supplied
`/home/chia/repos/OpenChia-iterative-refiner/launch_default.json` configures tests
of the Target Workflow, not the refiner. Shared execution and replay must
retain this separation and record which configuration each Run used. A target
test must not mutate the caller's configuration. See the
[routing contract](episode_launch_configuration.md#duet-refiner-and-target-model-boundary).

### 1. The testing Episode owns experimental design

It specifies what it is testing, why, the relevant requirements, expected
outcomes, falsifying outcomes, and how results will be measured. It chooses
execution scope and mode based on that reasoning. The harness validates and
executes the specification; it does not substitute a fixed testing sequence.

### 2. Scope is explicit and inspectable in every test specification

Support addressing individual registered components, declared units, Episode
invocations, nested Episode groups, and complete workflows or refinement jobs.
Identify the exact candidate revision and starting state, what executes, what is
reused, and how parent/child boundaries are handled.

Before execution, expose the resolved scope and dependencies. Missing context or
incompatible boundaries must produce an actionable explanation, never silent
substitution or expansion.

### 3. Modes express what is reused versus recomputed

Support numerical-only replay, execution with recorded external responses, live
execution from saved inputs or state, and fresh live execution through the same
system.

A recording must match the request and context it is used to answer. Divergence
must be reported explicitly; recorded execution must never silently become live
execution. Reports must distinguish what each mode exercised and what it could
not establish.

### 4. Provide one clear interface for humans and LLMs

Provide a documented CLI with structured requests and responses. In-Episode
requests must reach the same underlying service through the approved host/worker
interface.

Make available scopes, modes, required inputs, execution plans, status, results,
and comparisons discoverable. An agent should not need to inspect implementation
files or write a custom runner to conduct a supported experiment.

### 5. Integrate with actual Episode iteration and control

Testing actions must fit into the existing Episode execution and feedback loop.
Return evidence that the testing Episode can use to choose its next experiment,
and that registered host-side functions can use for credit, rarefaction, and
continuation.

Keep separate:

- Whether the tested candidate met its requirement.
- What the experiment established.
- Whether that evidence constitutes new progress for the testing/refining Episode.

Model predictions, test volume, repeated passes, and failure alone are not
authoritative credit. Do not introduce a separate harness-owned semantic stopping
rule.

### 6. Use one execution and evidence path throughout refinement

Candidate checks, measure validation, independent parent acceptance, and
experiments testing the refiner itself must use the shared harness. Preserve
their different judgment contracts without creating separate runners or replay
mechanisms.

Execute through existing admission, confinement, brokers, and audit facilities
wherever those facilities are part of the claim being tested. A narrower
execution must be explicitly identified as narrower evidence.

### 7. Make results useful during nested iteration

Return typed records containing expected versus observed outcomes, evidence
references, affected requirements, candidate identity, regressions, execution
limitations, and unresolved questions.

Children receive appropriately scoped context; parents receive the information
needed for steering and acceptance, with access to supporting detail. Do not
depend on generated prose summaries or expose unrelated child histories by
default. Preserve shared regression history so cross-child repair cycles remain
visible.

### 8. Unify recording, replay, and interruption recovery

Use existing durable stores and identities. Preserve enough coherent state to
support each advertised replay or continuation operation, including nested
execution state where required.

Distinguish continuing an interrupted execution from starting a new experiment
with changed code, inputs, or controls. Preserve original evidence, prevent
duplicate credit, and never present interruption as successful completion.
Unsupported recovery must be reported honestly.

No role-specific or experiment-specific replay machinery may exist alongside
this system.

### 9. Preserve experimental and authority boundaries

Bind each experiment to exact code, inputs, configuration, measures, and relevant
environment state. The testing Episode may choose subsequent experiments, but
cannot retroactively change an earlier experiment's expectations or weaken
assigned acceptance criteria to obtain a pass.

Reused evidence and newly produced evidence must remain distinguishable. Test
execution must not grant additional editing, child-creation, or policy authority.

## Acceptance requirements

Demonstrate through the shared interface that:

- A real testing Episode specifies and executes a justified experiment, inspects
  its evidence, and chooses a follow-up.
- A concrete Episode task has an independently examinable answer or behavior; a
  broken candidate fails and a correct candidate passes.
- Scoped execution and broader nested execution test different stated claims
  without confusing their evidence.
- Numerical replay, recorded-response execution, and live execution are visibly
  distinguishable; incompatible recordings fail explicitly.
- A cross-child regression is visible at the appropriate parent scope.
- Interruption, continuation, and repeated requests preserve evidence without
  false completion or duplicate credit.
- The measuring mechanism distinguishes relevant known-correct and
  known-incorrect results.

Deliver documentation, CLI examples, an architecture-to-code map, and receipts
stating exactly what was demonstrated and what remains unverified.

## Scope limit

Build and validate this unified capability. Do not redesign the refiner, replace
the numerical controller, activate normal-build finalization, or expand into
unrelated repairs. Consult the existing
[integration map](iterative_episode_refiner_integration.md) and
[checkpoint handoff](iterative_episode_refiner_checkpoint.md); historical recovery
proposals are not authority to restore one-off machinery.
