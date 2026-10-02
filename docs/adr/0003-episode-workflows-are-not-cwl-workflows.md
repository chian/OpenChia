# ADR 0003: Episode workflows are not CWL workflows

Status: Proposed

Implementation: the Episode model described here is implemented. The CWL
composition in "Consequences" is a direction, not a commitment.

## Context

OpenChia's first real workflow is the BV-BRC RAGstack `asm-next` parameter and
structure study (see [ADR 0002](0002-run-http-requests-are-host-brokered.md)).
That places OpenChia squarely in a domain where the Common Workflow Language is
the established standard, with multiple independent engines (`cwltool`, Toil,
Arvados, StreamFlow, REANA), a large corpus of existing tool descriptors, and
CWLProv for provenance.

Any bioinformatics collaborator will therefore ask the obvious question: why is
OpenChia defining a bespoke Episode structure instead of emitting CWL? The
rationale currently exists only in the shape of the code. This record states it
so the decision can be argued with rather than inferred.

The question is sharper than it looks, because the two models are not
alternatives at the same layer, and conflating them has a real cost: it invites
either reinventing what CWL already does well, or forcing a stopping-rule
semantics into a standard that cannot express it.

## Decision

OpenChia models a workflow as a nested tree of Episodes rather than as a CWL
workflow graph, because the two answer different questions.

**A CWL workflow describes a graph of deterministic process invocations whose
shape is known before execution. An Episode describes a goal pursued by repeated
attempts, where a registered numerical function decides at runtime how long to
keep trying.**

Four properties of the Episode model have no CWL expression. Each is load-bearing
for OpenChia's purpose and none is incidental.

### 1. A stopping rule under uncertainty

A CWL workflow is an explicitly acyclic graph. `scatter` provides bounded
iteration over an array whose length may be determined at runtime; `when`
provides conditional execution. Neither expresses *continue while the projected
value of continuing justifies further work*.

`EpisodeCreationSpec` carries `numeric_control: EpisodeNumericalControlSpec`,
which names two registered functions by exact identity
(`library`, `function_id`, `interface`, `definition_id`, `arguments`):

- `rarefaction` — the predicted value of continuing, derived from observed credit;
- `continuation` — the numerical verdict that governs whether the Episode runs
  another unit or returns to its parent.

Loop constructs have been discussed for CWL and exist as engine extensions, but
they are `while`-style control flow. They are not a value-of-information
estimator, and they carry no notion of diminishing returns.

### 2. Credit is first-class and deliberately non-compositional

CWL has no vocabulary for partial success: a step's process exits zero or
non-zero. An Episode declares `goal`, `progress`, `stopping`, a repeated `unit`,
and a `result`, and credit assignment owns stable result identities,
normalization, and marginal dominated hypervolume.

The composition rule is an explicit modelling decision: a parent receives
distinct child identities by declared result channel and recomputes progress on
its own scale. **It does not sum child hypervolumes.** Progress is not additive
up the tree; each level re-measures on its own terms.

### 3. Non-determinism is assumed, not fought

CWL's central value proposition is reproducibility: the same inputs in the same
container yield the same outputs. An Episode calls a model across a typed broker,
so re-execution will not match.

OpenChia therefore pursues a different property. It does not promise that a Run
reproduces; it promises that a Run is *attestable* — a content-addressed closure,
a verified interpreter identity, an inspected executor, and a hash-linked
evidence chain. **Reproduce versus attest.** The second cannot be retrofitted
onto a standard designed for the first, and conformance to CWL would imply a
guarantee OpenChia cannot make.

### 4. Untrusted content is a structural concern

In CWL, data flowing between steps is inert; nothing downstream interprets it as
instruction, so prompt injection is not a category that exists.

In OpenChia a model reads Episode output, so the containment is expressed in the
types. `handoff_library` defines `ParentRequest` and `ChildResult` as closed
records, and the architecture requires that raw task prose, source contents, and
log text never become upward instructions. This is injection containment as a
structural property of the handoff, not a filter applied after the fact.

## Consequences

### What this costs

The cost is real and should not be minimized. Against CWL, OpenChia gives up:

- a standard with multiple independent engines; OpenChia has one implementation;
- a mature type system for scientific data (`File` with `secondaryFiles`,
  `Directory`, records, enums) — the Episode deliverable contract is thin by
  comparison;
- a large corpus of existing tool descriptors, plus container and resource
  requirements as standard vocabulary;
- CWLProv and portability across established HPC and cloud schedulers;
- the simplicity of interpreting declarative data. Because EpisodeBuilder emits
  Python, OpenChia additionally owns a planner, an emitter, a static-admission
  gate, closure staging, and interpreter identity — machinery a CWL engine does
  not need.

**If a workflow is a static DAG of deterministic tools, CWL is the correct choice
and the Episode model is overkill.** The Episode machinery earns its complexity
only where there is a genuine stopping decision to make under uncertainty.

### Where the two compose

They are not competitors at the same layer. The natural architecture is
**Episode as the adaptive outer loop, CWL as the deterministic inner tool
execution**: an Episode's `unit` invokes a CWL `CommandLineTool` or sub-workflow
as a declared capability. CWL does reproducible, portable, containerized tool
execution; the Episode observes the result, assigns credit, and decides whether
another iteration is warranted.

This direction also addresses a known weakness. The registered-function catalog
is presently a hand-edited tuple literal in `episode_builder/planner.py` rather
than anything derived from the libraries, and the seven `*_library` packages have
no shared registry. CWL tool descriptors are a far better-specified substrate for
"registered, validated, reusable component with typed arguments" than what exists
today. Adopting them for the tool layer would resolve that by borrowing a
standard instead of inventing one.

Nothing here commits OpenChia to that integration. It records that the Episode
model is not an attempt to replace CWL, and that the boundary between them is the
stopping decision.

### Open question

Whether the Episode deliverable contract should adopt CWL's data types
(`File`, `Directory`, `secondaryFiles`) outright rather than continue to define
its own. Deferred until a workflow needs to carry file artifacts between
Episodes; today deliverables are descriptive.
