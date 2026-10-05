# IterativeEpisodeRefiner: Goal 1 repository integration map

This document preserves the original Goal 1 design inspection. Statements below
about then-missing code or unexecuted paths describe that inspection, not the
current checkout. Current harness status and evidence are maintained in the
[harness guide](unified_episode_test_harness_design.md) and
[verification receipts](unified_episode_test_harness_receipts.md).

## Current integration update — 2026-10-03

OpenChia now owns the normal build → refine → validate job after one start under
[ADR 0007](../adr/0007-build-owns-iterative-finalization.md). Failed or materialized
initial Builder receipts enter the same refiner job through the shared experiment
service. Refiner reasoning uses the owning Duet's model configuration; Target
Workflow validation uses its separate approved launch. Native nested continuation
has passed with supplied decisions. Live jobs have reached the refiner with a
fully initialized Duet, but no independently accepted live repair or final build
has yet been demonstrated. See the receipts for failed attempts and exact limits.

The first-time check-design addition at `9b5d11574a` extends existing campaign
records and admission. It adds no runner, store or replay API:

| Responsibility | Current implementation |
| --- | --- |
| Freeze permission to design a check in a new normal-build campaign | `iterative_episode_refiner.measure_preparation.build_measure_policy`; `measure_admission.reviewed_designs.version=1`; old frozen campaigns stay unchanged |
| Validate an original-requirement check and a separately assigned review | `iterative_episode_refiner.measure_design.propose`, `assigned_definition`, `reviewed`; exact requirement scope, execution binding and returned Question-child review |
| Supply available predicates, definitions and review criteria to the assigned Episode | `iterative_episode_refiner.measure_design.context`, through the existing `runtime.snapshot` |
| Run the existing Measure → Question review child and project its returned definition | `iterative_episode_refiner.measure_design_runtime.propose_design`, `propose_reviewed_instrument`, `project`; the existing `propose_measure` action and child interfaces |
| Reject altered reviewed projections at admission | `iterative_episode_refiner.measure_design_runtime.authorize`, called by `measure_admission.grounded_cases`; exact content-addressed provenance |
| Retain definitions/reviews without a second persistence system | `iterative_episode_refiner.records` kinds `measure_definition` and `measure_review`; additive collections in `campaign_store`; `integrity.validate_commit` independently re-derives their committed changes |
| Distinguish review from target correctness or credit | `measurement.close_unit` and `integrity._validate_continuation`; review returns `needs_parent_decision` with zero yield; ordinary measure admission still executes both control classes |

This route supports existing registered observation predicates, not arbitrary
new executable checker code. Reviews retain their judgment provenance and
limitations; they are not independent empirical truth. Five focused checks pass
with supplied model/Builder replies. Those checks do not establish live reasoning
or native confinement. The subsequent live job ended with a missing-`measure_need`
host error before any accepted repair; Task 4 remains open.

## Historical Goal 1 inspection

Implementation priority correction (2026-10-02): the user deferred testing and
replay machinery until the central refiner is connected. The earlier outbox and
standalone recovery proposals below are not current implementation requirements.
The unused refiner outbox and reconstruction verifier were removed. Future
replay/testing must use one documented CLI and shared execution service. See the
[then-current status](iterative_episode_refiner_implementation_status.md) for the
new Episode loops and existing-worker connection, which had not been executed
at that checkpoint.

2026-10-02 — companion to [executable contracts v1](iterative_episode_refiner_contracts.md)
and [design v3](iterative_episode_refiner_episodes.md). The original mapping records
static inspection and proposed boundaries; implementation updates at the end and
the [implementation status](iterative_episode_refiner_implementation_status.md)
distinguish later changes and verification.

Inspected checkout: `52c9c2675995232416012bf19dd644170b7913ab`.
Also inspected the already available merged-main object
`a335059aee74c230429a4093f32330a94789cb22` for executor integration. That is an
inspection baseline, not a claim to have freshly fetched the latest main.

Implementation update: the dedicated `feat/iterative-episode-refiner` worktree
was subsequently fast-forwarded to fetched `openchia/main` at
`697d440a169204a20f8c951648c040304e9e2857` (PR #26), preserving the design and
guidance work. ADR 0004 remains proposed/unimplemented; it is not assumed to
replace the actual builder/linker. See the [implementation status](iterative_episode_refiner_implementation_status.md)
for code and test evidence; the historical Goal 1 mapping below is not a completion
claim.

PR #31 update: the worktree is now based on
`9980990488089f4c53bfe4c61f3054312ed70db8`. Initial preparation consumes
`BuildStore.read_materialization_handoff(receipt_id)` and imports its verified
record into existing Duet storage. The Builder's static requirements and
baseline replace any independently reconstructed static checklist. Original
contract coverage remains separate for behavioral judgment. See
[handoff contract](materialization_refiner_handoff.md) and the current status
for the source-level evaluation and raw-source admission connections and their
remaining verification requirements.

## Current measurement-loop mapping (source review, not execution evidence)

Model-routing clarification, 2026-10-03: `execute_refinement` must receive the
owning Duet's model/provider configuration. Target validation Runs must use the
target's selected launch configuration through the shared harness, not inherit
the refiner broker accidentally. The current entry accepts injected brokers;
automatic Duet binding and end-to-end routing separation are not yet verified.
See the [routing contract](episode_launch_configuration.md#duet-refiner-and-target-model-boundary).

This is Goal 4's task-specific measurement work, not the later harness for testing
the refiner. All observations still use Goal 3's existing executor connection.

| Responsibility | Current implementation |
| --- | --- |
| Parent selects a named prerequisite; child returns original evidence | `function_library/refinement.RefinementUnit`, `runtime_proposals`, `investigation`, `prerequisites` |
| Preserve criteria while acquiring expected values/control inputs | `grounding.specification`, `prepare_acquisitions`, `authorize_acquisitions`; optional frozen acquisition refs and complete case templates |
| Execute an independently approved read-only source | `checking.reference_definition`, `instrument_builds.source_scope`, `candidate_source.project_candidate_sources`, existing `RefinementEvaluations` |
| Refine checker code through ordinary Parts/Designer/Implementer assignments | `instrument_builds`, `materialization_edits`, `instrument_return.checker_from_return`; same candidate/store/edit/evaluation paths |
| Combine constructed checker and acquired cases; demonstrate adequacy | `instrument_return._construction_grounding`, `measure_admission.grounded_cases`, `measure_controls`; both control classes remain required |
| Make an admitted measure available to its parent | `measures.admitted_measures`, `prerequisites.parent_prerequisites`, `runtime.snapshot`; original reports, not copied child scores |
| Assign it without mutating active criteria or erasing history | `succession.validate_replacements`, `_preserve_measure`, `_preserved_instruments`; exact accepted baseline-checker substitution only |
| Retain independent grounding in final build evidence | `finalization._observation_rows`, `_confirm_observations`, `finalize_result`; existing Run/binding and measure-admission references |

The source review found and corrected two connection issues: unavailable
instrument placeholders were dereferenced while preparing comparison context,
and successor checks rejected even the exact independently admitted replacement
of a constructed checker's baseline. The latter permission applies only to a
future parent-owned assignment; it does not equate different checker sources for
credit or relax any original criterion/guard/input/capability.

No project imports, tests, actual Runs or migrations were executed for this review.
This map does not prove transport, cancellation/recovery, ordinary-Episode
compatibility or model-driven repair. See the stable five-item inventory in the
implementation status; defects found during review stay under those items.

Recovery boundary: the current `RefinementSession` creates its invocation maps in
memory and starts from one active root. It does not reconstruct an interrupted
nested stack for a fresh Run. Operation-level idempotency is implemented separately
in the existing transaction path; that does not imply resumed Episode execution.
Restoration remains deferred to the user-requested unified execution/replay work,
not a new refiner-only recovery API. This is a known implementation gap under
Goal 3 in addition to the unexecuted verification requirements.

## 1. Existing foundations versus required changes

| Contract responsibility | Existing symbol/path | Required change / boundary |
| --- | --- | --- |
| Exact IDs, canonical JSON, hashes | `agent.episode_contract_models.OpaqueId`, `Sha256Digest`; `agent.duet_contracts.content_id`, `canonical_json` | Reuse these conventions; choose one existing canonical representation per new schema, not competing hash implementations |
| Approved target and numerical selections | `EpisodeCreationSpec`, `EpisodeNumericalControlSpec`, `EpisodeFunctionSelectionSpec`, `EpisodeWorkflowSpec` in `agent/episode_contract_models.py`; `FrozenDuetWorkflow`, `WorkflowAdmissionAuthority` | Preserve exact target approval; add an explicitly versioned repeatable-call extension for approved refiner execution |
| Legacy boundary classification | `iterative_episode_refiner.service.IterativeEpisodeRefiner`, `RefinementAuthorityReader`; `contracts.py` | Reuse provenance, exact baseline and semantic-change checks. Rehome into Builder/approval services in Goal 7; they are not the active Episode |
| Shared workspace projection | `iterative_episode_refiner/workspace.py` | Extend projection from admitted campaign facts; it is not already an editing engine |
| Transactional artifact persistence | `agent.duet_store.DuetStore.transaction`, `_put_artifact`, `put_artifacts_with_events` | Store campaign artifacts in the existing database; add focused campaign CAS/index/outbox operations rather than another database |
| Source blobs and build records | `episode_builder.store.BuildStore.put_blob`, `read_blob`, `put_plan`, `put_admission_report`, `put_manifest`, `publish_source_package` | Reuse immutable source storage and admission/publication. Add explicit candidate-to-build lineage, including non-runnable candidates |
| Initial materialization | `episode_builder.service.EpisodeBuilder.build`; `NodeMaterializationPlan`, `EdgeMaterializationPlan`, `WorkflowMaterializationPlan` | Preserve the one-shot build boundary; carry stage/call bindings into exact plans and expose initial artifacts even when behavior is broken |
| Source admission | `episode_builder/admission.py`, especially `_ALLOWED_IMPORT_ROOTS` | Keep host refiner imports unavailable to generated workers; generated candidates and check harnesses still require admission |
| Reference library and child interfaces | `episode_library.models.EpisodeLibraryDesign`, `registry.EpisodeLibrary`; `method_loop.binding.EpisodeBindingDeclaration`, `EpisodeChildSlot` | Register seven role designs and exact child slots; no second Episode catalog |
| Existing qualitative leaf | `episode_library/reasoning.py`; `function_library.reasoning.ReasoningSource`, `HostReceiptController` | Reuse patterns and generic primitives. Do not pretend the existing leaf implements child stages or mutate its receipt semantics for all users |
| Function and schema selection | `function_library.registry.FunctionLibrary`, `models.LibraryFunction`, `FunctionImplementation`; `epistemic.resolve_component`, `EpistemicContract` | Register refiner schemas/projectors/admission/yield/projection and numeric adapter through existing infrastructure; preserve old definition identities |
| Generic Episode loop and identity | `method_loop.episode.Episode`, `EpisodeGoal`, `EpisodeRequest`, `EpisodeRecord`; `method_loop.identities.EpisodeRef`, `UnitRef` | Keep loop ownership and runtime identity; relate actual identities to durable campaign invocation/unit IDs |
| Child result boundary | `ChildEpisodeUnit`, `EpisodeCompletion`, `EpisodeUpdate` | Keep pure parent-owned projection; add opt-in declared staged acquisition and durable continuation without hiding execution in `receive_result` |
| Recursive topology | `EpisodeTree` (`self_nesting`, `recursive_edges`); `Context.can_enter/enter` | Reuse existing graph checks. Materializer/linker must actually carry approved repeatable edges and enforce scope admission |
| Staged worker linking | `episode_runtime.linker.prepare_source_package`, `ActivatedSourcePackage.link`, `_GoalViewRegistry` | Resolve exact templates/stages, distinguish root instance from recursive root-template calls, and bind host-approved invocation inputs |
| Numeric control | `MarginalHypervolumeAssignment`, `CreditObservation`, `NumericBand`, `paired_incidence`, `predicted_credit_upper_bound`, `ComposedIncidenceController` | Reuse domains/algorithms; add registered host composer/goal-aware numeric adapter only for refiner contracts |
| Learning integrity | `episode_runtime.learning.LearningLedger`, `learning_integrity.validate_learning_commit`; `RunStore._new_event` | Reuse scoping/equivalence principles and publication-boundary validation. Existing Run-local checkpoint storage is not cross-Run campaign state |
| Worker transport | `episode_runtime.protocol` frames; `worker.py`, `broker.py`, `learning_broker.py`; `function_library.reasoning_transport` | Add a closed scoped-refinement request/response family and worker-facing library adapter; do not overload raw logs or arbitrary learning payloads with edit authority |
| Run audit and recovery | `RunStore.publish_registration`, `claim_run`, `append_event`, `finalize_run`, `complete_terminal_publication` | Preserve claim/terminal invariants; add correlated host-origin receipt events and duplicate-safe publication; no campaign credit written by workers |
| Actual execution | merged-main `episode_runtime.executor.RunExecutor`, `_RunExecutorBase`, systemd/container implementations | Reuse exact source identity, isolation, brokers and cancellation for validation; no replacement launcher |
| Host lifecycle | `agent.openchia_host.start_build`, build worker, baseline persistence, `start_run` | A focused build-finalization sibling/service owns campaign start/status and validation routing; never recursively call single-session `start_run` |

## 2. Structural mismatches resolved by the proposed contracts

### A. A concrete tree does not carry repeatable Parts calls

`EpisodeWorkflowSpec` rejects parent cycles. `WorkflowMaterializationPlan` requires
one structural edge per non-root node, a single parent for each child, and exact
slot coverage. `ActivatedSourcePackage.link` constructs a tree without supplying
the method loop's recursive declarations. Merely registering a new library Episode
cannot make Parts recursion work across this chain.

Decision: preserve the structural tree and add separately declared repeatable call
bindings (§8.2 of the contracts). The v2 workflow/plan encoding must name exact
callee templates, request/return bindings, invocation admission and attenuation.
Slot coverage is the disjoint union of structural and repeatable bindings; no slot
can have both. Existing tree edges retain all their current checks.

The linker builds the complete approved call graph, marks its recursive edges,
and supplies only admitted builders. Root-template calls use their actual parent
path, not the special root-instance path currently selected by local ID alone.
Each logical invocation receives separate controller state and a host-admitted
assignment. It cannot use a fresh identity to erase campaign history.

This is additional executable authority that must be approved explicitly. It is
not a reinterpretation of an existing approval that granted only a concrete tree.

### B. Child projection does not implement a serial design unit

`ChildEpisodeUnit._finish_async` calls child `build_result`, projects its result,
then returns a contribution for the parent's controller. It does not execute
implementation followed by independent acceptance and enclosing assessment.

Decision: an opt-in staged acquisition adapter with registered finite stage graphs
and durable pending-stage receipts. It composes existing child execution and pure
handoffs; new actions occur in named stages. Extend unit audit to reference every
stage/child, not squeeze several children into a single existing `child_record`.
Existing one-child units keep their representation and behavior.

The parent controller observes the closed semantic unit once. Intermediate durable
candidate/check/conflict changes remain visible to ancestors and can cause a
typed incomplete return before the entire realization path succeeds.

### C. Source exhaustion is not an authenticated parent-decision return

`SourceEnd` currently accepts only `source_failed`; `None` ends a source by
exhaustion. Neither expresses the reason/evidence needed to unwind a cross-level
conflict safely. Generic reasoning's HostReceipt also reserves normal stop for
its yield-based completed state.

Decision: add an opt-in typed incomplete return carrying a host receipt and reason;
propagate it through child completion and the staged adapter. Distinguish it from
numerical return and actual Run termination. Preserve existing source/receipt
encodings and semantics. Do not use Python exceptions alone as the durable report.

### D. Run-local learning is not campaign persistence

`LearningLedger` reconstructs its state/history from one Run's events, and commits
full state snapshots with learning receipts. A refiner must retain the same
candidate/assignment history across validation Runs and recovery Runs.

Decision: campaign state belongs to the existing transactional DuetStore, with
RunStore holding original execution evidence and correlated campaign receipt refs.
Reuse existing learning types/admission helpers where their contracts fit, not a
second memory API or a copied Run-local ledger with disconnected authority.

### E. “All builds” is not “all builds can already execute”

Source preparation requires an admitted package. The refiner cannot depend on
importing broken Target Workflow code in order to repair it. Existing build lifecycle
also does not equate source admission with demonstrated task performance.

Decision: stage the refiner from its separately approved implementation; read
candidate blobs as untrusted data. Only evaluation requires candidate/harness
source admission. Normal activation later adds verified-readiness as a distinct
fact, not an altered meaning for old build receipts.

## 3. Persistence and migrations

Keep immutable refiner records in DuetStore's existing `artifacts` and
`duet_events`. Source/check/instrument bytes reuse BuildStore blobs. Execution
observations remain in RunStore. No new database or storage root is required.

Add these **indexes and transaction guards in the same Duet database**, not
independent competing copies of artifact bodies:

| Proposed table | Required uniqueness / purpose |
| --- | --- |
| refinement_campaign_heads | campaign_id primary key; authority head, state version, candidate and latest commit refs; compare-and-swap |
| refinement_operations | (campaign_id, operation_id) unique; payload hash, stage, request/receipt refs, evaluation Run linkage, pending/committed status |
| refinement_invocations | invocation_id primary key; assignment, parent, Parts owner, pending stage and current status |
| refinement_fact_credits | (campaign_id, judgment_lineage, semantic_fact_key) unique; originating transition/measurement refs |
| refinement_check_index | campaign/requirement/criterion/applicability keys; latest operative observation refs/status, including stale |
| refinement_receipt_outbox | receipt_id primary key; Target Workflow Run, publication/reconciliation status |

Immutable commit artifacts contain ordered deltas with a predecessor commit ref.
Indexes and optional verified checkpoints accelerate retrieval; replay from deltas
must reconstruct them. Do not embed the full growing campaign snapshot in every
Run event. Conflict/lesson status comes from transitions, not edited-away history.

Use DuetStore's existing transaction/locking/canonical-artifact mechanisms, exposed
through a focused campaign persistence seam. Extend CAS checks to the campaign
head as well as authority head. Directly storing a model proposal in `artifacts`
must not create any operative index/credit entry. The publishing operation invokes
independent integrity validation of its exact predecessor, delta and measurement.

An existing `refinement_cycles` row represents the old approval/proposal process.
Do not reinterpret those rows as executed repair campaigns. Link when appropriate;
keep old records readable and their old meaning intact.

Migration rules:

- New campaign artifacts have explicit schema ID/version. Readers select exact
  schema versions; unsupported future versions fail visibly.
- Extend the existing DuetStore schema transactionally and additively. Existing
  artifacts, event bodies and approval hashes are never rewritten to add defaults.
- Legacy workflow records retain their exact old encoding. Only workflows using
  new call bindings use a v2 record with `schema_version`, `episodes` and
  `repeatable_calls`. New plan/staged-call encodings likewise have explicit versions.
- A v1 record read and reserialized as v1 must retain its content identity. Moving
  it to v2 is a new artifact and, where authority changes, a new approval.
- Old function/Episode definitions and ordinary protocol frames remain supported.
  New source identity binds all new runtime/library files actually used. No optional
  default can silently grant refinement capability to an old registration.
- Mechanical Python moves update internal imports/docs; no internal re-export
  shims. Preserving persisted data formats is separate from preserving old imports.
- Active campaigns stay pinned to their versions. Incompatible software may report
  inability to resume; it must not silently swap controllers or acceptance rules.

## 4. Host and worker ownership

Put new host-only state/admission/conflict/report logic in focused modules of
`iterative_episode_refiner/`, not appended to the large legacy service/contracts
files. Suggested responsibility names: `campaign_contracts`, `assignments`,
`candidates`, `measures`, `reports`, `conflicts`, `campaign_store`, `host_operations`.
Only add modules justified by implemented consumers; this list is not a framework
generation checklist.

Worker-facing sources and typed adapters belong in admitted `function_library/`
modules; handoff definitions in `handoff_library/`; reference Episode bindings in
`episode_library/`; the numeric adapter/composer in `numeric_control_library/`.
They exchange closed records with the host and never import host state machinery.

Add `REFINEMENT_REQUEST` / `REFINEMENT_RESPONSE` to the existing closed transport,
with only §11's allowed operation names. Broker creation is capability-gated and
must use a finalizable lifecycle. The host resolves actual caller lineage and
authority, not the worker's claimed role. Worker-bound token/reference scope is
limited to its assignment and invocation.

The worker may propose source bytes, not write arbitrary host files. The host
publishes candidate blobs and runs only admitted harnesses under RunExecutor.
No permissive shell broker, direct host code execution, new unrestricted memory
tool, global learning privilege or model-selected runtime import root is needed.

## 5. Specialty guidance interface and parallel ownership

The unvalidated Goal 5 guidance catalog was removed on 2026-10-04. The following
interface remains a design proposal, not an available library or evidence that
its examples worked. The admission policy allows nano-graphrag references and
the refiner's validated Episodes and dependencies. This catalog removal does
not establish validation of every remaining registered design. New examples
require successful end-to-end execution before admission.

The root index lists subjects only. Subjects have their own compact `index.json`
and `instructions/` / `examples/` bodies. Initial subjects: general, goal_contract,
numerical_controller, reasoning, calculation, simulation, measurement, composition.
Common/general guidance is explicitly selected, not unconditionally included.

Parent-facing card fields:

```text
guidance_id, version, title, kind, subject, roles[], description,
use_when, do_not_use_when, body_path, source_refs[], validation_status
```

`kind` distinguishes principle, role instruction, specialty instruction, worked
example and check pattern; no redundant level field is required. The agent
preparing the content owns the final documented encoding of those fields; runtime
parsing must follow that reviewed schema, not infer missing data.
`use_when` and `do_not_use_when` are concise strings, not executable predicates;
roles and source refs are arrays. The catalog README defines the closed validation
categories and relative-path rules.
An item is the card plus its body, pinned together by canonical content identity.
Referenced example/check artifacts require their own exact identities.

Selection request: `{subject_filters, role, need_keys, task_conditions,
required_interfaces, catalog_ref}`. Response: scoped cards and a complete-index
reference; no instruction bodies are injected until selected. Resolving an item
loads its full body and precise source refs. Admission checks its applicability
to the named decision under the assignment's policy, not just a tag match.

FindDesignSupport returns selected refs, applicability evidence, conflicts and
uncovered needs using the §7 projection. The parent can use a known selection
without a search Episode, or search when it has a real gap. A numerical-controller
assignment browses its own subject plus explicitly requested common guidance,
not every task-type directory. Unfamiliar work uses the general route or reports
missing guidance; it is not forced into the nearest example.

Before child start, only the approved instruction package can enter the fixed
prompt. Later material is typed reference input. Illustrations, mechanism tests
and partial acceptance receipts do not qualify as proven library examples.

## 6. Implementation order and safe concurrent work

The original implementation sequence was **1 -> 2 -> 3 -> 4 -> 6 -> 7**.
Future Goal 5 content must come from validated work, not invented examples.

| Ownership | Files/decisions |
| --- | --- |
| Goal 1 owner / integration owner | Shared schemas, authority, stage/recursion/return interfaces, store transaction boundary and numerical contracts |
| Goal 2 main implementation | Campaign state, projections, equivalence and conflict handling; define agreed Python types first |
| Goal 3, following Goal 2 | Actual protocol, broker, source/linker, recovery and scoped execution integration |
| Goal 4, following Goal 3 | Executing library Episodes and host-receipt sources using the real boundary |
| Goal 5 content | Admit examples only from validated work; the unvalidated draft catalog was deleted |
| Goal 5 later integration | Catalog resolution/search and frozen scoped input, through reviewed interfaces |
| Goal 6 | Real-path acceptance cases and inspectable receipts; preparation can precede execution |
| Goal 7 | Legacy boundary rehome and normal build activation, last |

Single writer per shared contract/registry/host file. Separate worktrees are useful
once implementation begins, but current agents share the workspace; scoped file
ownership is the actual protection now. A clean Git merge is not proof that state,
credit and recovery contracts agree. Do not parallelize those judgments merely
because their implementations occupy different files.

## 7. Static review, not execution evidence

Read existing recursion tests in `tests/method_loop/test_episode_tree_recursion.py`:
they cover explicit recursive declarations, correct parent goals, and parent-owned
projection. They do not establish end-to-end materialization of Parts recursion.
Inspected the runtime learning/publication implementation and identified existing
invariant tests in `tests/episode_runtime/test_epistemic_learning.py` and broker
boundary tests. None were run for this design task.

The current checkout has no `tests/episode_builder/` or
`tests/iterative_episode_refiner/` directory. New test placement must mirror actual
source responsibilities; do not claim those suites already exist. Mechanism tests,
isolated transport tests and live reasoning/repair acceptance remain distinct
completion evidence in Goals 2–7.

This mapping supports concentrated refiner/library work with a finite list of
shared changes. It does not claim zero regression risk, a finished migration,
validated numerical calibration or a merge-ready implementation.

## Implementation update: approved repeatable calls

The optional workflow field is `repeatable_calls = {version: 1, bindings: [...]}`.
The materialization field is `repeatable_calls = {version: 1, edges: [...]}`;
each edge carries its exact `EpisodeRepeatableCallSpec`. Both fields are absent
for old workflows/plans, preserving their previous semantic records. Physical
edges still cover each non-root concrete template exactly once. `all_edges`
supplies the disjoint union to emission, admission, inspection and runtime linking.

Current symbols:

- `agent.episode_call_contracts.EpisodeRepeatableCallSpec` and the existing
  `EpisodeWorkflowSpec`/blueprint conversion own frozen call authority.
- `episode_builder.call_plan` resolves registered pointers, adds call slots after
  concrete planning and checks exact approval correspondence. `EdgeMaterializationPlan`
  carries an optional call binding; `WorkflowMaterializationPlan` retains separate
  concrete and repeatable edge collections.
- `function_library.episode_calls.BUILD_REPEATABLE_CHILD` awaits the runtime's
  exact slot builder. It does not choose templates or authorize campaign writes.
- `episode_runtime.repeatable` supplies graph construction, exact declaration
  checks and invocation guards; `linker` supplies the actual parent path and
  instance identity. These modules are in the staged runtime source manifest.

The guard ABI receives keyword arguments `request` (typed child EpisodeRequest),
`parent_request`, `invocation` (runtime-derived Run/template/slot/path/instance
identities), plus the exact frozen selection arguments. `request_schema` must
return the unchanged typed request. `authority_attenuation` and
`invocation_admission` must return exactly `True` from their registered
implementations; they may be asynchronous. A model-supplied boolean is not called
or consumed by this interface. For the refiner, the final admission implementation
must obtain its decision from the authenticated host campaign operation; that
production policy/transport connection is still outstanding.

The refiner uses separate root and callable Parts entries. The root keeps its
empty Duet request. Recursive Parts calls target the predeclared child template
with the campaign/assignment/invocation payload, retaining the supplied scoped
goal view; they never reopen root goal state. Both entries execute the same Parts
loop. This avoids weakening launch admission or pretending the root's empty
request contract accepts a different parent payload. These are task-input entry
contracts, not separate model configurations; both use the Duet's configuration.

`episode_library.refinement.materialization_bindings` supplies the fixed adapters
only for exact registered refiner references selected in the approved workflow.
The existing planner records them, the reference resolver provides their library
source, and the existing linker checks the emitted selections. Each entry has
one materialized `report` channel. The shared builder/result functions receive
its exact IDs through the generated ABI wrapper; child handoffs and the host
session correlate them with the committed report. These are unexecuted changes,
not evidence of successful approval/build/worker transport.
