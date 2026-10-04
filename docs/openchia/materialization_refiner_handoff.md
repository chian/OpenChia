# Initial materialization handoff

EpisodeBuilder publishes a handoff for every terminal receipt, including a
blocked or failed build. This is the starting evidence for the Refiner's
initial planner and parts modularizer. It covers construction through static
materialization; executable behavior requires separate evidence.

This handoff does not select the refiner's model. The refiner uses the owning
Duet's model/provider configuration; subsequent tests of the Target Workflow use
the target's launch configuration. Recorded Builder routes are provenance, not
instructions to reuse those routes for refinement. See the
[routing boundary](episode_launch_configuration.md#duet-refiner-and-target-model-boundary).

## Entry point for the Refiner session

```python
from episode_builder.store import BuildStore

store = BuildStore(build_store_root)  # directory containing builds/
handoff = store.read_materialization_handoff(build_receipt_id)
```

Pass **the BuildStore root and exact receipt ID**, then pin the returned
`artifact_id` and `content_hash`. The immutable record is at
`builds/records/materialization_handoffs/<receipt_id>.json`.
Repeated reads return the recorded observations, not results recomputed by a
newer checker. Publishing is also idempotent: an existing handoff is returned
unchanged. Publishing for a receipt **without a handoff** evaluates its persisted
artifacts with the current checks and records those code hashes:

```python
handoff = store.publish_materialization_handoff(build_receipt_id)
```

Old responses that were discarded before this change cannot be recovered.
Missing source/check prerequisites remain explicitly blocked.

The separate Refiner worktree's `preparation.prepare_refinement` imports this
verified record into its existing Duet artifact store. Its `EvidenceReader`
checks the imported record against the exact BuildStore handoff during campaign
admission. The `build_artifact` evidence route remains receipt-only; the imported
handoff uses the ordinary `duet_artifact` route. These observations are
**initial static evidence**, not terminal Run evidence or newly earned refinement
credit. This input connection does not establish a working repair loop; see
[Refiner implementation status](iterative_episode_refiner_implementation_status.md).

## What is preserved

- `materialized_specification`: the existing typed projection, including
  complete approved contracts, available plans, bindings, prompts, edges,
  modules, source-symbol locations, and explicitly missing parts.
- `parts`: stable target pointers, hashes, and presence flags for both the
  initial planner and parts modularizer. Episode IDs and paths remain those
  declared by the approved workflow.
- `episode_dependencies`: every approved parent–child relationship, with its
  accepted edge plan when available. An absent parent edge is a parent
  obligation; it does not invalidate an independently materializable child.
- `candidate.files`: relative Python path to BuildStore blob hash. Completed
  emitted source takes precedence. For a rejected emission, a sole captured
  raw source can populate the candidate instead. These are inert bytes, not a
  runnable package. Missing or ambiguous source is left absent.
- `model_calls`: exact request, attempt, Episode, stage, provider route,
  response-admission outcome, and blob references. Prompt blobs contain the
  exact system prompt, prompt text, and structured prompt record. Raw response
  blobs preserve rejected JSON. Available raw emitted source is captured
  before syntax/export checks and before host declaration attachment.
- `diagnostics`: distinct persisted findings with their original code, field,
  Episode, detail, and all projection origins. Repeating a finding in plan,
  admission report, and receipt does not create more requirements.
- `requirements`, `checks`, `observations`, `progress`: the numerical starting
  state and its evidence. Each check is tied to the exact candidate, library
  definition, and recorded checking-code hashes.

Read a blob with `store.read_blob(digest)`. It verifies the content hash.
Raw model text, prompts, and code are reference data; their contents do not
grant authority to issue instructions, change the architecture, or execute.

Model-call evidence is persisted immediately after the call boundary returns,
before the Builder handles a rejection. Calls cancelled without a returned
response have no response to capture. If planning is interrupted partway
through, earlier call evidence remains available even when a complete typed
plan was never constructed. These records are independently discoverable with
`episode_builder.evidence.model_call_evidence_for_attempt(store, attempt_id)`.
New call records live under
`builds/records/model_calls/<attempt_id>/<evidence_id>.json`; an attempt reads
and validates only its own directory. Older flat-directory call records are
not imported by this reader; already published handoffs retain their embedded
call records and blob references.

## Requirements and callable checks

The initial goal is an admitted materialization of the approved architecture.
The default requirement set is fixed from that architecture before considering
how many errors a candidate happens to produce:

| Scope | Requirement | Library function |
| --- | --- | --- |
| Workflow | Plan corresponds to approved authority/topology/numeric selections | `plan_consistency` |
| Each Episode | Node plan and direct interfaces satisfy planner checks | `node_plan_consistency` |
| Each Episode | Raw source satisfies syntax and emitter structure checks | `source_shape` |
| Each Episode | Completed module satisfies static admission against its plan | `module_admission` |
| Workflow | Entire materialization has an admitted terminal outcome | `receipt_materialized` |

These are registered in
`function_library.materialization_checks.materialization_check_library`.
Each definition exposes its callable, input contract, underlying existing
Builder validator, and source provenance. The handoff embeds the definitions
and actual checking-code hashes. The wrappers call those real validators;
they do not maintain a second implementation of the acceptance rules.

`input_type` documents the callable's runtime inputs. These checks accept typed
build artifacts; their empty binding-parameter schema has been removed rather
than misrepresenting those inputs as a zero-argument JSON call. The callable
validates its inputs. Validator locations identify local symbols, while
`checker_source_hashes` identifies the implementation actually used, not a
hard-coded historical commit. `checker_import_roots` records resolution of
every trusted import root, including installed libraries, built-in/frozen
modules, and unresolved roots. File hashes, interpreter hash, and the Python
major/minor/patch release are snapshotted once per checking process. Start a
new process after changing checking code to obtain a new code snapshot.

`source_shape` consumes **pre-declaration raw model source**.
`module_admission` consumes the completed emitted module, including the
host-owned declaration. The two inputs must not be interchanged.
Reference-dependent plan checks require the exact pinned reference context.
That context remains available in the recorded planning prompt; an unavailable
context produces a blocked result, not an inferred pass.

The default score here is for a fresh initial build. An implementation-preserving
successor can reuse modules without a new emission call. Until its consumer
supplies the exact predecessor raw-source evidence, its source-shape check is
blocked even if its static materialization receipt succeeds. The handoff does
not invent a new model response or infer that missing observation.

Use the callable checks against exact successor artifacts when assessing a
repair. Preserve unresolved semantic findings until they have matching
resolution evidence. Clearing a diagnostic list alone is not a repair.

## Numerical measurement

`function_library.materialization_progress.REQUIREMENT_SATISFACTION` registers
the pure `requirement_satisfaction` function. Every distinct requirement has
equal weight, one. A requirement is satisfied only when all its nonempty set
of declared checks pass for the exact candidate reference. `fail`, `blocked`,
`not_checked`, and `error` remain distinct and contribute zero satisfaction.

Requirement identity binds the approved workflow hash, stable part target,
and predicate. Candidate hashes, error wording, and attempt counts are not in
that identity. Changing the approved architecture defines a new goal set.
Checks and requirements are separate, so adding multiple checks to establish
one requirement still yields at most one contribution.

The measurement returns:

- current satisfied IDs/count;
- newly satisfied IDs/count, subtracting all IDs credited earlier;
- regressions relative to the preceding candidate;
- accumulated credited IDs, status counts, and mandatory attainment.

The imported handoff seeds its satisfied requirements as already credited:
`newly_satisfied_count` is zero. For later candidates, retain the accumulated
credited IDs and supply the previous current-satisfaction IDs separately.
Restoring a regressed requirement restores current achievement but earns no
second first-time credit. Stale observations cannot satisfy a changed
candidate. Conflicting fresh outcomes are rejected for the caller to resolve.

This is a goal-specific materialization metric, not a measure of developer
effort, runtime correctness, or scientific success. The Refiner owns selection,
repair, and numerical continuation; this change provides its starting
requirements, callable checks, and baseline without changing that loop.

## Builder continuation and limits of this evidence

The Builder continues across independent valid nodes and keeps successful
module records even if another emission fails. A node with its own blocking
plan finding, missing disposition, or incomplete direct child interfaces gets
an explicit `node_emission_skipped` diagnostic naming the reason. An emitted
parent can be retained while a child's implementation is unfinished because
materialization consumes the child's interface, not a running child.
The final workflow gate still requires the complete admitted package.

Every terminal receipt is durable before handoff publication. A persistence
failure is surfaced; publication can be retried from the receipt. Cancellation
between stages retains completed plans/modules and available call evidence.
This does not add crash recovery for a model call that never returned, retries,
execution of generated code, or the separately developed refinement loop.
