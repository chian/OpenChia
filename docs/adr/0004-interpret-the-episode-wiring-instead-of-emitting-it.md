# ADR 0004: Interpret the Episode wiring instead of emitting it

Status: Proposed

Implementation: not implemented. This records a direction and the evidence for
it. The measurement in "Open question" should be taken before committing.

## Context

EpisodeBuilder plans and emits one task-specific Python module per Episode, then
statically admits the closed source package without importing it
([`OPENCHIA_ARCHITECTURE.md`](../../OPENCHIA_ARCHITECTURE.md), "EpisodeBuilder").
That codegen boundary is the origin of most of the subsystem's complexity and,
empirically, most of its defects.

### What the emitted module actually contains

Every emitted module must assign eight module-level values
(`episode_builder/emitter.py:38`):

```
REQUEST_PAYLOAD_CONTRACT   RESULT_PAYLOAD_CONTRACT   PROMPTS
EXECUTION_CAPABILITY_NAMES RESULT_CHANNEL_NAMES      RESULT_CHANNEL_IDS
BINDING                    DESIGN
```

and define builders with fixed signatures (`episode_builder/admission.py:561`):
`build_controller_factory(goal_view, collaborators)`,
`build_episode(grain, key, request, goal_view, collaborators, child_builders)`,
plus root-only `build_goal_state(request, collaborators)` and
`scope_goal_state(goal_state, goal)`.

The emitter contract constrains these severely: no builder uses `global` or
`nonlocal`, generated builders cannot capture or mutate module state, the module
imports no concrete child Episode module (the runtime linker owns child
selection), and — stated outright — *"the module composes the generic
`method_loop` Episode."*

**This is wiring.** It is a near-deterministic function of the approved
Architecture, and the architecture document already concedes the point:
*"Structural facts come from the host and approved Architecture, not from the
planning model."*

### The declarative substrate already exists

`method_loop/binding.py` defines `EpisodeBindingDeclaration`, which describes a
complete Episode declaratively:

```
grain_name, interface, topology_role, goal, unit, result, progress, stopping
admit_request : EpisodeFunctionBinding
open_source   : EpisodeFunctionBinding
controller    : EpisodeControllerBinding
build_result  : EpisodeFunctionBinding
components    : tuple[EpisodeFunctionBinding, ...]
child_slots   : tuple[EpisodeChildSlot, ...]
```

Each `EpisodeFunctionBinding` carries `name`, `library`, `function_id`,
`interface`, `definition_id`, `arguments` — **the same five-field exact pointer
the Architecture already uses** in `EpisodeFunctionSelectionSpec`
(`agent/episode_contract_models.py:290`).

So the emitted module's `BINDING` value is a declaration the host could have
constructed itself, from an approval it already holds, using a vocabulary that
already exists. The planning model is being asked to write out a structure that
is derivable.

Separately, `method_loop.Episode` (`method_loop/episode.py:1009`) is a frozen
dataclass taking `grain`, `key`, `source`, `request`, `build_result`, and
optional `on_unit`/`on_close`. It is already generic; nothing about it requires
a generated module.

### The cost is measured, not hypothetical

The four consecutive fixes landing on `main` in a single day
(`6b67b5ce42`, `558d766a64`, `16f5e73830`, `16ee315caa`) are one defect wearing
four hats: **the emitter and admission hold separate, drifting models of what
generated Python is legal, and violations surface late.**

- `6b67b5ce42` — *"The authoring model had no way to know the admitted roots:
  admission checks `_ALLOWED_IMPORT_ROOTS` only after emission, the emitter
  contract never lists them."* Seven `module_import_forbidden` deficits. The fix
  published a shared constant *"so the two cannot drift."*
- `16f5e73830` — admission indexed `ast.FunctionDef` only, so every `async def`
  was invisible. Because every brokered-library component is necessarily async,
  this *"blocked every Episode that uses the HTTP broker."*
- `16ee315caa` — the module named four real symbols under the wrong library.
  *"Admission checks import roots only, so the module passed and failed at
  import time."* The failure appeared as
  `ProtocolError: worker protocol stream ended inside a frame`, and the cause
  *"had to be recovered by re-launching the worker by hand."*

None of these are failures of care. They are the inherent failure modes of
asking a model to produce structure that must match a contract exactly, then
validating it after the fact with a second, independently-written description of
that contract.

## Decision

**Narrow codegen to the part that is genuinely novel. Interpret the rest.**

1. The host derives the `EpisodeBindingDeclaration` for each Episode directly
   from the approved Architecture. The Architecture already carries every field
   it needs, in the same vocabulary.
2. Every role that resolves to a registered library function —
   `admit_request`, `open_source`, `controller`, `build_result`, and any
   `components` entry with a registry implementation — is bound by identity, not
   emitted. No source is generated for it and none is admitted.
3. `PROMPTS` is data. It travels in the approved artifact and is hashed with it.
   It is never code.
4. Codegen survives **only** for a `components` entry with no registry
   implementation: a genuinely novel task body, such as "call this endpoint with
   these parameters and extract this measurement." That module is small, has one
   job, and is the only thing the AST admission gate must inspect.

The human approval boundary is unchanged. The build receipt still records
exactly what was materialized; it simply records resolved bindings for most
Episodes and a small admitted source blob for the rest.

## Consequences

### What this removes

- The import-surface negotiation between emitter and admission, and the whole
  class of defects above. There is no import surface to negotiate when there is
  no module.
- Most of the ~29 static-admission rejection codes, which exist to police
  generated structure that would no longer be generated.
- The need for the planning model to reproduce frozen numerical function records
  exactly — the host writes them, so they cannot be misreproduced.
- The duplicated function-selection admission between
  `agent/episode_blueprints.py:137` and `episode_builder/planner.py:357`
  (an open finding): with one resolution path there is one implementation.

### What survives unchanged

- `episode_runtime/` in full. A novel component body is still untrusted code
  and still needs the closure, the sandbox, Landlock/seccomp, and the broker.
  **This ADR does not reduce the isolation requirement.**
- The AST admission gate — now applied to a much smaller surface, which makes it
  easier to test exhaustively. Its current lack of negative tests is a separate
  open finding and is not resolved by this change.
- Human approval, content-hash authority, and the evidence chain.

### What it costs

- **Expressiveness becomes gated by the registry.** Today a planning model can
  write anything the admission gate permits. Afterwards, anything structural
  must be a registered function — which means code review, tests, and a release
  to add one. That is a real reduction in what a Duet can design unaided, and it
  is the central trade: *fewer things possible, far more of them correct.*
- A registry must actually exist. It presently does not: the catalog is a
  hand-edited 21-entry tuple literal at `episode_builder/planner.py:322`, only
  four `FunctionLibrary` instances exist, and two are never queried. Building
  the registry is a prerequisite, not a side effect.
- Migration. Existing approved Architectures and build receipts must either be
  re-derived or explicitly grandfathered.

### Relationship to other records

This is the mechanism by which [ADR 0003](0003-episode-workflows-are-not-cwl-workflows.md)'s
composition becomes available: once a component is a registry entry resolved by
identity, a CWL `CommandLineTool` descriptor is a natural thing for that entry to
describe. Declarative components are the precondition.

## Alternatives considered

**Keep emitting, and fix the drift.** Make admission the single source of truth
for every rule and have the emitter consume it. This is the direction
`6b67b5ce42` already took, and it is a genuine improvement. Rejected as the
primary answer because it reduces the frequency of the defect class without
removing it: a model asked to produce exact structure will sometimes produce
near-miss structure, and the cost of each near-miss is a failed build or an
`ImportError` inside a sandbox.

**Emit, but verify by round-trip.** Generate the module, import it in a
throwaway sandbox, and compare the resulting `BINDING` against the one the host
derived from the approval. Catches `16ee315caa`-class errors early and is
strictly better than today. Rejected as primary because if the host can derive
the expected binding, it can use it.

**Full declarative, no codegen at all.** Every component must be registered.
Cleanest, and it deletes the admission gate entirely — but it blocks any workflow
needing a task body nobody has written yet, which is most first-of-a-kind
scientific work and the reason OpenChia exists.

## Open question — measure before committing

**What fraction of `components` entries in real Architectures resolve to a
registered function, and what fraction are genuinely novel?**

The entire value of this ADR depends on that ratio. If most components are novel
task bodies, the emitted surface shrinks far less than argued and the trade is
poor. If most are wiring and brokered calls, the surface nearly vanishes.

The BV-BRC `asm-next` workflow is the available sample. Classify its emitted
components before acting on this record.
