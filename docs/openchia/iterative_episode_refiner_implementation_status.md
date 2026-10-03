# IterativeEpisodeRefiner implementation status

2026-10-02 checkpoint: the user closed the bounded Goals 2–4 coding assignment as
complete, not stalled or blocked. Execution validation, unified testing/replay,
interrupted nested-session restoration, and normal-build activation are separate
follow-up work; they must not silently reopen or expand this completed assignment.
This is an implementation checkpoint, not a claim of live reasoning acceptance,
runtime compatibility, or merge readiness. No new tests or live Runs are being
performed to save it. See the [collaboration handoff](iterative_episode_refiner_checkpoint.md).

Routing clarification, 2026-10-03: the active refiner must use the owning Duet's
model/provider configuration. The Target Workflow launch JSON is for testing
the Target Workflow, not for launching the refiner. The explicit refiner entry accepts a
broker; automatic Duet configuration binding and separation from Target Workflow Runs
remain unverified. This does not reopen the completed coding assignment or
claim normal-build activation. See the
[routing contract](episode_launch_configuration.md#duet-refiner-and-target-model-boundary).

Worktree: `OpenChia-iterative-refiner`, branch `feat/iterative-episode-refiner`,
based on merged OpenChia main `9980990488089f4c53bfe4c61f3054312ed70db8`
(PR #31). The branch was fast-forwarded without creating a commit, and the
unfinished edits were reconciled with the merge. A pre-update copy is at
`/tmp/openchia-refiner-pr31.J2BS5g/unfinished-work.tar` on this development host.

## Historical tracking at the end of coding — not an active work queue

The tables and dated entries below retain the source-review findings and missing
execution evidence. They explain the saved implementation, not remaining work on
the now-complete bounded assignment. Earlier completion labels and countdowns are
superseded by the checkpoint statement above; they do not establish test results.

| Assigned goal | Current implementation position | Missing proof |
| --- | --- | --- |
| 2 — Durable refinement state | Candidate revisions, evidence, reports, shared conflicts, succession and host credit are present in source. | Current-tree state/recovery and compatibility checks remain unexecuted. |
| 3 — Real execution connection | Explicit admitted entry, scoped host operations and the existing worker/executor path are connected in source. | Actual transport/confinement/cancellation remain unverified; interrupted nested-session restoration is not implemented and is deferred to the unified recovery work. |
| 4 — Executing refinement Episodes | Parts → Designer → Implementer and supporting roles are registered; measurement preparation and independent parent acceptance have source paths. | Complete integration review and later real execution remain required. |

| Stable review item | Current state |
| --- | --- |
| 1. Preserve measurement evidence | Final publication now includes the original independent evidence-source Runs, as well as target/checker/adequacy Runs. Source-only implementation, not execution evidence. |
| 2. Handle missing measurement prerequisites | A missing instrument reference preserves the unresolved decision context instead of raising during comparison. Source admissions are scoped to the assigned measure so an independent reference build cannot mask a target's rejection. Unexecuted. |
| 3. Construct and admit task-specific measures | Authorized evidence acquisition and constructed-checker return are connected in source. The full case set, both control classes and original criteria remain mandatory. Parent use is part of item 4, not assumed complete. |
| 4. Review the complete refinement loop | The main source trace now covers assignment → measure preparation → design → implementation/local measurement → independent acceptance, plus approved call materialization/linking. Runtime and ordinary-Episode compatibility are unverified. Interrupted nested-session restoration is a known deferred gap, not merely an unexecuted check. |
| 5. Reconcile documentation | Current measurement interfaces and tracking are updated here and in the contracts. Further integration findings must update these same records. |

No tests, project-import probes, model calls, actual Runs or migrations have been
executed during these updates. The user's deferral of unified testing/replay
remains in force. No normal-build activation, new execution service or replay API
was added during those updates. Commit/push and a draft PR are now separately
authorized to preserve and share the completed coding checkpoint.

### Item 4 source-review findings and verification boundary

- `design.refinement_workflow_spec` declares the fixed role graph and reusable
  calls before approval. `call_plan` materializes only those declared targets and
  exact function selections; `repeatable.admitted_builder` validates the original
  request, parent goal/context and invocation policies. The linker uses concrete
  invocation paths, not a child-created replacement topology.
- `RefinementSession` binds the exact approved refiner manifest and numerical
  selections. `_caller`, `_prepare_child`, `_enter_child` and the campaign
  assignment admission enforce parent identity, allowed roles and attenuated
  scope. `_receive_child` compares the typed handoff with the original host report.
  Only Parts owns new Designers/nested Parts; only Implementer submits code edits.
- `execution.execute_refinement` is still an explicit entry. Ordinary executor
  calls have no refiner session and reject refinement requests. Validation
  target/checker/provider Runs use the existing executor without that authority.
  No normal Builder activation was added.
- `CampaignStore.commit_attempt` records an attempt first, resolves external
  evidence outside its write transaction, and atomically applies records/indexes/
  credit only after independent integrity validation. An existing operation
  commit is returned without awarding credit again. This is source evidence for
  the intended transaction path, not a crash-recovery test result.
- `validate_return`, `root_readiness` and `finalize_result` distinguish a numerical
  unresolved return or external stop from a verified build. Final publication
  depends on independent original evidence, not a worker success label.

Known deferred recovery gap: the runtime session initializes `calls` and
`pending` in memory and requires one active root assignment. It does not
reconstruct a suspended parent/child stack and mid-unit execution position in a
fresh authorized Run. Durable operation idempotency and an external-stop snapshot
do **not** establish that capability. No one-off replay/rehydration mechanism was
added to work around it. The user-directed unified execution/replay phase must
address it alongside actual transport, cancellation, crash and compatibility
validation. This remains a disclosed technical limitation for the unified harness
follow-up, not a reason to reopen the user's completed bounded coding assignment.

## Measurement evidence acquisition and checker handoff — not executed

- `ResolveQuestion` is a supporting role introduced by design v3 (§4), not a
  pre-existing OpenChia Episode. It selects a parent-authorized observation and
  returns original evidence; it cannot edit the target, invent an oracle, change
  acceptance criteria or create children. Its general reasoning capability has
  not been demonstrated.
- A frozen acquisition specification names an independently approved read-only
  workflow, original question need and fixed case template. The common evaluator
  uses that workflow's existing admitted source and typed launch. Candidate edits
  cannot alter the provider, and the provider receives no refiner capabilities.
- A returned question may fill only the delegated expected value and positive/
  negative control inputs. `grounding.py` reconstructs the original report,
  observation, source receipt and scope; model-authored expected answers are not
  admitted through this path. The payload predicate checks structure, not truth;
  the exact source/projection authority is a necessary independent premise.
- Construction specifications may name exact acquisition routes in addition to
  precommitted cases. A returned checker must retain all those routes/cases and
  controls. Source substitution still requires its independently accepted
  Designer/Verify return. The same executable-control path judges adequacy before
  the resulting measure can be used in a future authorized assignment.
- `finalization.py` confirms original evidence-source registrations, successful
  audit values and independently approved builds outside the campaign writer
  transaction. Its existing final receipt retains those Run/binding references
  and measure-admission evidence. This does not rerun anything or produce credit.
- Reviewing parent use exposed an integration mismatch in succession: even an
  admitted constructed-checker measure could not replace its original baseline
  instrument. Successor validation now recognizes only that exact independently
  accepted substitution. Mandatory criteria, guards, inputs and capabilities
  remain fixed; source-sensitive credit identities and active assignments are
  unchanged. This is an item 4 correction, not a new scope item or passing test.
- Additive data fields: optional `measure_admission.acquisition_refs` in policy,
  optional `acquisition_refs` in a construction specification, and optional
  `measure_proposal.grounding_acquisition_refs`. Older records omit them. No new
  database, index collection or migration accompanies this connection.

## Constructed checker return into measure admission — not executed

The repaired-checker return is now connected in source. It uses the original
Designer/Verify reports and evaluation-source records, not another acceptance
runner or a model summary.

- The host offers exact specification/report/source selections within the owning
  branch. It requires an attained Designer report under the specification's fixed
  acceptance measure, successful independent Verify observations for every
  required check and guard, and the same candidate/package's admitted source.
  Compilation and local coding success are insufficient.
- An optional Measure proposal selection derives a descriptor pinned to that
  source receipt. Admission re-derives the source substitution and requires the
  original grounded cases, controls, expected outcomes, mappings and limitations.
  Existing reference data holds the descriptors/bundle; no new index, database,
  worker operation, topology or execution mechanism was added.
- The selected checker goes through the same executable-control preparation and
  common evaluation service. Actual positive/negative control outcomes remain
  necessary for admission. Original construction reports/source and control Run
  evidence are retained with the resulting measure.
- Later edits or assignment supersession cannot silently change the admitted
  checker. Active criteria stay frozen; using a new measure requires an authorized
  future/successor assignment. Source/plan comparison, rather than new receipt or
  report identities, prevents repeated packaging of identical code from creating
  another adequacy fact.
- The only new refinement-record field is optional
  `measure_proposal.instrument_return_ref`. Old proposals omit it unchanged.
  The new `instrument_return` module owns this concrete handoff, not execution,
  persistence or a separate testing/replay system.

Formatting and source/whitespace inspection only. No tests, project imports,
model calls, Runs or migrations were executed, and normal-builder activation is
unchanged. Two implementation blocks remain from the progress inventory: the
authorized missing-grounding/evidence route and consolidated integration,
compatibility and documentation review. Actual execution verification remains
deferred; this is not proof of end-to-end repair or goal completion.

## Checker source and plan repair through the same loop — not executed

The first item in the latest four-item progress inventory is implemented in
source. It is not execution evidence or completion of Goals 2–4.

- Explicit frozen `editable_instrument_refs` selects a subset of independently
  authorized instrument-building specifications. Preparation retains the original
  approved workflow, Builder receipt and handoff, including partial/rejected
  builds, and adds namespaced modules to the same candidate. No second campaign,
  child topology, runner or persistence system was introduced.
- The Implementer uses ordinary file and implementation-detail edits. Checker
  plans have exact namespaced targets in the existing frozen allowlist, their own
  scoped context and original before values. The common Builder plan validators
  preserve approved topology/contracts; affected modules must fit the assignment
  and the Designer's admitted change scope, excluding protected paths.
- One immutable materialization revision can carry primary and checker plans.
  Changes preserve the other packages and invalidate current check state. Shared
  cycle comparison includes checker-plan meaning as well as source bytes, so
  neither plan revisions nor package separation hide a return to prior content.
- Source admission and execution bindings select the checker package's current
  plan and modules. Typed launch validation follows that revised root interface.
  The existing evaluation service and executor remain the sole Run path; original
  BuildStore/approval evidence is checked against the selected package. Checker
  receipts cannot be substituted for final primary-target source admission.
- Schema changes are optional `campaign.instrument_builds_ref` and
  `materialization.instrument_plans`; older records omit them unchanged. There is
  no additional database migration, replay interface or normal-builder hook.

Only formatting and source/whitespace inspection were performed. No tests, project
imports, model calls, Runs or migrations were executed. Remaining implementation:
returning the repaired instrument to measure adequacy/admission; completing the
authorized missing-grounding/evidence route; and consolidated integration,
compatibility and documentation review. Unified execution verification is still
deferred. The checker source/plan path is not yet a functioning end-to-end measure
construction claim. Earlier entries below describe their historical state.

## Measurement prerequisites return with original specifications — not executed

EstablishMeasure previously had only instrument proposals or question children;
the specified instrument-building/grounding request was not expressible in its
response contract. That missing branch is now wired into the existing loop:

- The host derives selectable missing-authority/grounding requests from the exact
  parent requirement scope and frozen policy. An optional frozen
  `instrument_build_refs` catalog provides independently grounded construction
  specifications, including input/output contracts, separate local/acceptance
  measures and positive/negative controls. No proposal can invent that authority.
- Selecting a need uses the existing `propose_measure` operation. A typed,
  host-rederived `measure_prerequisite` is stored, then ordinary unit closure and
  parent reports return its original reference with `needs_parent_decision`.
  The request is not a usable measure or credit-bearing progress.
- Parents can pass returned requests in assignment `prerequisite_refs`. Ownership,
  actual child return and complete requirement coverage are checked. Original
  references survive into the assigned goal/input/context through descendants;
  no LLM summary or implied expansion of paths, measures or child topology occurs.
- The existing campaign index gains `measure_need`, supported by its same
  transactional collection migration. No additional runtime operation, scheduler,
  test runner or replay mechanism was added. Legacy proposals/assignments without
  the optional reference fields keep their shapes.

Formatting/source/whitespace inspection only; no project imports, tests, model
calls, Runs or migrations were executed. This closes the prerequisite request and
information-flow gap, not checker construction. Scoped auxiliary-checker candidate
editing/admission, new independent grounding acquisition and the handback into
adequacy evaluation remain unfinished. Compatibility and complete execution remain
unverified; normal-build activation is unchanged.

## Review handoff and existing-store index migration — not executed

The two narrower items from the latest progress inventory are now implemented in
source. They remain unverified; this does not complete Goals 2–4.

- The explicit refiner return publishes a `review_handoff` containing the exact
  baseline/build, candidate, root report, Run evidence, original decisions/source
  references, verification gaps and history cursor. It distinguishes a genuine
  terminal report from an external stop's last-known snapshot. Publication adds
  neither credit nor execution/approval authority.
- The existing Duet proposal service accepts an optional `review_handoff_id`.
  Both proposal recording and human-requested cycle entry check that it still
  describes the same baseline and campaign return. The existing request still
  needs real human notes and an explicit replacement Architecture. No executing
  Episode calls it automatically. Old unlinked proposal bodies/hashes are unchanged.
- `CampaignStore` now recognizes an older collection-only index constraint and
  replaces that index table transactionally, copying every row before replacement
  and recreating its lookup index. It uses the existing Duet write transaction;
  artifacts, operation identities, campaign heads and credit rows are untouched.
  Unknown layouts/collections/extensions are rejected instead of downgraded.
  No new database, schema-version store, recovery worker or replay API is added.
- Corrected a wrong exception import in the unfinished handoff module during
  source inspection. The new result/record paths were formatted; tracked legacy
  proposal/service edits were kept narrow.

Only formatting and source/whitespace inspection were performed. No imports,
tests, model calls, Runs or database migration were executed. The large remaining
implementation gap is task-specific measure construction/grounding for unfamiliar
tasks, including authorized construction of a new checker when none exists.
Compatibility and complete nested behavior still need later unified verification.
Normal-builder activation remains unchanged. Earlier entries below are historical;
their remaining-work lists are superseded by subsequent entries.

## Executable adequacy controls for checking measures — not executed

`EstablishMeasure` can now propose a measure using an already approved checking
workflow and have the common evaluation service exercise independently supplied
correct/incorrect examples. Merely asserting those outcomes is still insufficient.

- Complete task cases, checker identity, input mappings, controls, interpretation,
  limitations and purposes are checked before execution. The frozen assignment
  must explicitly authorize `bind_measure_control` and `observe_measure_control`.
  Existing assignments do not acquire those operations automatically.
- Executable controls are committed fixtures `{typed_status, expected_outcome}`,
  with positive and negative cases selected by the independently authorized
  grounding. They are never labelled as actual target Runs. The same checker-input
  preparation and the same existing executor are used for fixtures and target
  results; there is no second runner, model tool, subprocess path or replay API.
- `measure_control_run` binds each proposal/case/control to its exact admitted
  registration before execution, or records a known preparation gap without a
  registration. `measure_control_observation` binds actual terminal evidence and
  the frozen extraction/predicate result. Wrong/missing checker output is an error,
  not a made-up verdict. Neither record updates target behavior checks or earns
  repair credit.
- Admission requires actual outcomes for every declared control. It rejects
  unexecuted, unavailable, failed or incorrectly classified controls, retains
  original evidence, and installs the measure only for its authorized owner.
  Publication re-derives comparisons from the admitted control observations.
  Parent/measure context includes a bounded set of original verdicts and refs;
  admission records retain the complete control-run set, including rejections.
- Final publication now retains used measure-admission references and confirms
  original control Run/source/value provenance without rerunning the controls.
  Their Run evidence joins the candidate/checker evidence in the final artifact.

Schema: two v1 record kinds, a `measure_control` collection in the existing
campaign index, optional `control_run_refs` on measure admissions, and optional
`measure_admission_refs` on final artifacts. The still-pending index-constraint
migration must include this collection for pre-existing development stores.
No tests, project imports, model calls or Runs were executed; formatting and
source/whitespace inspection only. This is not proof of control execution and not
universal oracle validity. Building new checker code, obtaining missing grounding,
approval handoff, migration/compatibility and later unified verification remain
unfinished. Normal-build activation remains unchanged.

## Checker prerequisites return to the parent loop — not executed

The shared evaluator now returns known post-target checking gaps through the same
unit closure and parent-report mechanism as preflight evaluation gaps.

- `prepare_checking` either resolves the existing approved checker launch or
  identifies unavailable/invalid checker source or an incompatible typed input.
  It first validates the actual successful Target Workflow Run. Target evidence corruption
  and unexpected errors are not converted into ordinary measurement results.
- An immutable successor `evaluation_run` record retains the target registration
  and carries `checking_gap`, with exact original target-binding/execution refs.
  There is no fabricated checker registration, observation, verdict or credit.
  The existing `bind_evaluation_run` boundary independently repeats preparation
  and checks the cause and unchanged registration before admitting the gap.
- The existing per-request index becomes unavailable. A gap cannot be overwritten
  with a checker Run on that request; later authorized evaluation gets its own
  request and preserves history. This uses normal campaign operations, not a new
  retry, replay or recovery mechanism.
- Unit closure and independent publication validation use the same unresolved
  decision projection. Parent reports retain every context's gap, even if a
  different case ran successfully. Parent context receives the cause, candidate,
  measure/check identities and evidence references, not a bulky registration dump.
- Source/approval failures do not authorize rebuilding or changing the checker.
  Input incompatibility does not authorize weakening the input or acceptance
  contract. The parent must select an existing authorized repair/prerequisite or
  return the missing authority. Final readiness still cannot bypass checking.

Schema effect: optional closed `checking_gap` on the existing v1 evaluation-run
record; no new table, index, worker operation, capability or normal-build hook.
No tests, imports, model calls or Runs. Formatting and source/whitespace review
only. This covers the known preparation gaps, not arbitrary executor failures or
proof of the nested repair loop. Instrument building/adequacy, general grounding,
approval handoff, the earlier migration and later unified verification remain.

## Approved checking Episodes through the existing evaluator — not executed

The native evaluation binding can now name an already approved, separately built
checking workflow. The candidate and checker run in sequence through the same
`RefinementEvaluations` service and existing executor; neither gets the refiner's
host privileges. This implements a checking connection, not a new testing harness
or automatic certification of newly generated checker code.

- An optional frozen instrument `checker_ref` names exact workflow/build/approval
  references, a typed launch template, and declared target-result input mappings.
  Source/approval identity is checked against the existing BuildStore and Duet
  approval records. The checker cannot simply be the Target Workflow itself.
- The host reads the candidate's original successful Run evidence and projects
  only declared typed-status fields into the checker launch. Existing root
  handoff validation checks the resulting payload. No raw Run-log injection,
  artifact-body access, new capabilities or runtime topology creation is added.
- The existing `evaluation_run` record gains optional `target_run_ref` and
  `target_execution_ref` fields. The checker binding supersedes the request's
  active binding while retaining the original immutable target binding. Host
  admission reconstructs both the actual approved checker registration and its
  exact input from target evidence; a second checker replacement is rejected.
- A successful Target Workflow Run cannot be observed as a verdict when its frozen measure
  requires a checker. Failed target/checker execution remains an error, not a
  pass. Final evidence publication retains both Runs and source bindings.
- Predicate-only adequacy controls explicitly cannot admit a checker-backed
  measure. This route requires a checker already authorized in the initial frozen
  measurement policy. Building a checker and demonstrating its adequacy through
  real independent controls remain unfinished work, not assumed from its approval.

Only optional v1 fields were added; older native bindings keep their shape/hashes.
No new index, database, runner, replay path, worker operation or normal-build hook.
The changes are confined to refiner modules and this design documentation.
Formatting and source/whitespace inspection only: no tests, project imports,
model calls or Runs. This route remains unproven. Missing stored checker source,
revoked approval or an invalid result-to-input projection currently fails closed;
the full typed prerequisite/repair return for those execution-time gaps is still
unfinished. General instrument construction/grounding, approval-needed handoff,
the earlier storage migration, unified verification and activation remain pending.

## Multiple grounded input cases in the shared evaluator — not executed

A composed measure can now retain independently authorized cases with different
native input contexts. This removes the previous one-context-per-measure limit;
it does not create expected answers or new oracle authority.

- Multi-context admissions give each check an exact `execution_binding` and
  retain the full `evaluation_bindings` set. A check belongs to one context, so
  a pass for one input cannot overwrite another input's failure. Single-context
  admissions retain their previous record shape and identities.
- `resolve_evaluations` groups the frozen checks by binding and independently
  derives each request's availability. An unbound ambiguous check is a gap, not
  permission to pick an input. Investigation requests preserve the whole selected
  check set for cross-context guards. Parent availability aggregates all groups.
- The existing service records the requests, admits candidate source once, and
  uses the existing executor for each executable native context. There is no new
  runner, scheduler or per-role testing/replay path. Interrupted work cannot
  manufacture observations for unexecuted cases.
- Available cases may run while another context is unavailable. Unit closure
  retains an original unresolved request, and parent reports carry every remaining
  context gap from the unit rather than allowing the last successful case to hide
  the others. Whole-build readiness continues to require every mandatory case.
- Repair credit includes context-bound input meaning, while duplicate payloads
  do not become novel by repackaging. Successor comparisons retain prior facts.
  Regression vectors can now reveal fixing input A while breaking input B; older
  checks without explicit case bindings retain their previous context grouping.

Schema changes are optional v1 fields on checks, measure admissions and selected
evaluation requests; no new table/index or migration is introduced by this slice.
No tests, imports, model calls or Runs were executed. Formatting and source/
whitespace review only. Independent checking workflows, instrument construction
and broader task-specific grounding remain unfinished; unified verification and
normal-build activation remain deferred.

## Whole-build readiness and exact final evidence artifact — not executed

The explicit refiner entry now returns a `verified_build` artifact only after
whole-build acceptance; otherwise its result includes typed verification gaps.
Run termination, Episode disposition and build readiness are separate fields.

- `readiness.py` checks the complete mandatory catalog, root composition checks,
  transitive guards, independent current verifier observations, child returns,
  unresolved conflicts and exact candidate source admission. Root numerical
  attainment uses this same projection; root context exposes its gaps. Bounded
  parent-report excerpts cannot hide an unaccepted requirement.
- Confirmed conflicts block readiness. An exact revisit alone remains a warning;
  suspected local opposing regressions need current passing checks together.
  Such historical warnings remain linked in the final artifact.
- `finalization.py` reuses the actual terminal Run evidence, admitted Builder
  package and original stored observation attempts. It checks the candidate's
  host-admitted source binding, approval, immutable receipts and original Run
  observation values. It does not rerun predicates/static checks or launch a
  validation Run; judgment stays in the shared evaluator. Cross-store reads occur
  outside the Duet transaction, followed by a current-authority and unchanged-
  campaign check before immutable artifact/audit publication.
- The evidence artifact binds manifest/materialization, candidate, complete
  check/requirement coverage, measures, grounding and limitations, original
  observations and validation Runs, environment and exact root numerical return.
  Existing dependency-compatible evidence retains its original provenance.
  No new credit, table, index or replay interface is introduced.
- `RefinementRunResult` carries `build_status`, `verified_build` and
  `verification_gaps`. An interrupted, unresolved or inconsistent result cannot
  publish verified readiness. The artifact is evidence, not permission to launch
  production or approve a changed architecture.

No tests, imports, model calls or Runs have been executed. Source formatting and
whitespace review only. This finalization path is implemented but unproven. General
measurement/instrument construction, broader validation contexts, the explicit
human successor-proposal handoff and the previously noted storage migration remain
unfinished. Unified testing/replay and normal-build activation remain deferred.

## Exact typed validation inputs through the existing launch path — not executed

Native validation no longer always launches with empty payload maps. A frozen
evaluation binding can reference one committed, content-hashed existing
`DuetLaunchRequest` record. Its workflow/goal must match the approved target;
the usual root handoff validates its artifact IDs, numbers, states and flags.
The host supplies a fresh request identity while preserving the payload.

- `evaluation_inputs.py` projects that ordinary launch contract. Empty inputs
  remain supported where the target allows them. It does not invent a second
  request schema, runner, artifact-body transport or storage capability.
- Availability now checks the actual candidate root interface for execution
  checks. Invalid or unavailable launch inputs return `launch_input_invalid`
  through the existing parent-decision path. Static-only requests do not require
  a materialized executable root interface.
- Grounded-measure admission accepts the same typed input reference and checks
  target identity/types without consulting mutable Target Workflow code. The original
  independently authorized grounding, controls and ownership remain required.
- The shared evaluation service supplies the payload to the existing executor.
  Run-binding admission independently reconstructs it from the frozen evaluation
  reference and verifies it against the actual BuildStore root interface. A Run
  with different inputs cannot supply observations for this request.
- Existing credit, prerequisite, succession and regression comparisons now use
  input values rather than template/request identity. Repackaging the same
  payload cannot make repeated work novel. Prior empty-input fact identities
  remain unchanged. Exact input references still govern admission; unsupported
  inputs retain their original references and explicit availability gaps.

No tests, imports, model calls, validation Runs or replay were performed. Source
formatting and whitespace inspection only. This is not complete generic
instrument execution: multiple input contexts, newly built/independent checking
Episodes and rich artifact-body consumption beyond existing target capabilities
remain unresolved. It also does not complete task-specific measurement grounding
or final VerifiedBuild publication. Normal-build activation is unchanged.

## Explicit root result and authenticated unresolved return — not executed

The explicit entry now returns `RefinementRunResult` rather than bare Run
evidence. Its read-only projection retains the original verified RunStore
evidence, root report, exact selected candidate, typed decision records and
candidate-bound admitted-source references. It does not execute another Run,
publish a build, create a human note or approve a successor.

- Parent reports include optional `child_report_refs` for their bounded returned
  direct-child reports. Superseded branches are not reintroduced as active child
  returns. The root projection follows committed typed links and retains original
  decisions; there is no LLM summary or raw audit-text instruction channel.
- The host now validates **both** successful and blocked refiner terminal frames
  against the exact published root report, root Episode identity and host-derived
  disposition. Previously an arbitrary blocked frame bypassed that verification.
  Ordinary non-refiner Runs retain their existing path.
- Numerical exhaustion and a parent-decision return remain distinct Episode
  dispositions even though both map to Run `blocked`. Neither becomes attainment.
  External termination remains external; its projected campaign state, when
  available, is not described as a terminal Episode report. Executor exceptions
  and cancellation still propagate normally.
- The existing Duet approval service requires real human notes and explicit human
  initiation. The result is information for that decision, not fabricated input
  to the old service. Original decision records may include historical rejected
  proposals; the root's unresolved scope and provenance remain visible.

Schema effects: one host return-object schema and an optional parent-report field;
no new database/index or change to the Episode's typed report-ID handoff. Original
v1 report bodies/hashes remain readable. `execute_refinement` is an unactivated
explicit API; its return now wraps (and exposes) the original `run_evidence`.
No normal-build hook was changed.

Formatting and source/whitespace inspection only; no tests, imports, model calls
or Runs. Exact `VerifiedBuild` publication and preparation of an approvable
successor contract remain unfinished, along with generic instrument construction
and execution. This return projection is not evidence that the refiner has run.

## Ordinary parent-owned successor assignments — not executed

Previously only joint-conflict repair supplied `supersedes_assignment_refs`;
ordinary parent choices could not replace an inadequate child assignment. The
proposal, admission, context and numerical-history paths are now connected:

- Parts/prerequisite assignment proposals can identify returned direct children
  they replace. A Designer's plan proposal can identify the returned Implementer
  it replaces. Only the existing permitted child graph is available; no specialist
  can obtain a Designer/Parts child through succession.
- `succession.py` validates the existing assignment/report records. A predecessor
  must have returned to this assigning parent, have a committed report, and not
  already be superseded. The successor retains its original requirements,
  contributions, slices, preservation checks, protected paths and authority.
  The old indexes close and the new child becomes ready in the same existing
  assignment transaction. No separate lifecycle store or operation was added.
- Authorized measure checks now occur at assignment admission, including the
  predecessor-scoped admitted catalog. Successors and their descendants can use
  that catalog; unrelated branches cannot. A changed measure must preserve every
  mandatory typed check, exact guards and established instrument/input binding.
  New admitted coverage may be added. Changing the measure for the same direct
  contribution/slices cannot be presented as unlinked fresh work.
- Equivalent check meanings are mapped between predecessor/successor measure
  identities in the existing credit and numerical history projections. Credit
  publication independently uses the same inherited fact set. Historical unit
  observations remain observations, not new successful units. Original evidence,
  receipts and credit rows are not rewritten; another role's score is not copied.
- Focused context includes bounded original predecessor reports/goals and the
  parent's returned direct-child assignments with their admitted measures. The
  shared regression/conflict records remain visible. Historical evidence does not
  mark a successor check current or replace independent parent acceptance.

No new artifact kind, database table, runner, replay interface or test fixture.
Source inspection, formatting and whitespace checks only; no imports, tests,
model calls or Runs. This is an implemented child replacement path, not proof of
the complete nested refiner. Root/successor approval handoff, more general
criterion revision, instrument-building/grounding and independent instrument
execution remain unfinished. Normal-build activation is unchanged.

## Measurement gaps return through the existing evaluation path — not executed

The shared evaluation service no longer treats a missing/ambiguous native
instrument binding or unsupported input route as an ordinary worker exception.
`evaluation_plan.resolve_evaluation` derives available checks and exact gaps from
the assignment's unchanged measure, scope, environment and authorized bindings.
The request admission path independently repeats this projection before committing
the existing evaluation record/index. Unauthorized selections still fail admission.

- New evaluation records include a closed `availability` projection. Missing
  coverage names the original requirements; missing guards name their check keys.
  Frozen checks not yet installed remain explicit gaps instead of disappearing
  from the requested judgment. Investigation guard selection uses the same
  authorized definitions before the evaluation service checks availability.
  Environment mismatch and missing/ambiguous/unsupported instrument routes remain
  distinct. Missing bindings have null instrument/capability refs, not invented
  executable identities. Previous v1 records retain their original bodies/hashes.
- An unavailable request does not admit source or register a Run. Source/Run
  binding admission also rejects it. Partial requirement coverage alone does not
  suppress available checks through the ordinary native validation path.
- At unit close, the outstanding evaluation gap produces
  `needs_parent_decision` with the original request reference. Publication
  re-derives both this disposition and the exact decision reference. A gap is not
  a behavior failure, success, or credit-bearing observation. Any real measured
  evidence still follows the existing role judgment rules.
- Parents receive the typed decision bodies linked to their bounded direct-child
  reports, not only opaque references or an LLM summary. Their context also
  contains host-derived availability for their own acceptance judgment. An
  unavailable route does not force another automatic baseline-verification child;
  the parent can select a permitted prerequisite instead. It cannot replace its
  active acceptance measure or claim that skipping verification satisfies it.

This finishes the previously partial availability wiring, not the generic
instrument-execution requirement. Native target-root execution remains the only
implemented route; arbitrary instrument inputs and independent instrument builds
remain unfinished. No additional runner, replay path, index or database was added.
Source inspection and formatting only; no tests, imports, model calls or Runs.

## Parent progress from prerequisite children — not executed

The parent loop previously counted returned verifier evidence but not the useful
decision change from obtaining an admitted measure or resolving a prerequisite.
`prerequisites.py` now connects those results to the parent's own unit judgment:

- Only a direct permitted child actually entered and returned in the current
  parent unit is eligible. The original report and source record remain linked;
  child credit, completion labels and model prose are not inputs to the value.
- A measure must have passed host admission, remain available within this owner's
  scope, and match the parent's original requested purpose and requirements. Its
  criterion/instrument combinations identify availability facts. Regrouping the
  same cases or repeating an admission cannot create additional parent credit.
- A question/support result must still be current under its named need, evidence
  dependencies, fixed outcome meanings and preservation guards. Supported or
  refuted questions can inform the parent; support requires applicability. Both
  retain advisory strength, applicability and limitations.
- The parent's ordinary unit transaction stores a `prerequisite_assessment` and
  uses those decision facts in its yield and numerical continuation. Publication
  independently re-derives the assessments. They **do not** satisfy implementation
  or enclosing acceptance checks; the independent VerifyBehavior path is unchanged.
- Subsequent context and parent reports include bounded assessment references,
  original evidence and current/stale status in the model-facing context. No new
  child spawning permission, system-prompt mutation or free-form summary channel
  was introduced.

Composed measures can now retain several independently authorized complete cases
for one requirement, with every case's controls and guards. The previous one-case
restriction was unnecessary. All cases still use one compatible native instrument
context, and the proposed requirement set must match the parent's exact request.

Schema effects: one closed assessment artifact kind and optional
`prerequisite_assessment_refs` on unit, local-context and parent-report records;
older bodies retain their hashes. No new table, runner, replay mechanism or
verification fixture. Formatting/whitespace inspection only: no tests, imports,
model calls or Runs. General instrument-building/grounding, root/successor measure
coordination and full nested execution remain unfinished or unverified.

## Candidate plan repair, including missing nodes — not executed

The candidate-edit path now accepts explicitly authorized materialization choices
as well as source edits. This fills the earlier missing/partial-plan repair path;
it does not approve a different workflow or activate normal build finalization.

- A frozen `materialization_edit_targets` list permits exact
  `/episodes/<local_id>/parts/node_plan` targets or named implementation fields.
  Whole-node targets accept the Builder's planner-choice object, not model-written
  host identities. A missing plan uses `before: null` and must name an Episode
  already present in the approved workflow. All edits retain exact before values.
- `episode_builder/plan_choices.py` extracts the existing deterministic node/edge
  construction used by initial planning. Candidate repairs reuse it and the
  existing payload admission and native plan checks. The host derives module,
  channel, reference and contract identities. Frozen numerical selections,
  capabilities, topology and repeatable-call authority remain unchanged.
- `plan_repair.py` admits a batch of choices before constructing the new graph.
  Changed child payloads/interfaces require matching parent edges in the same
  batch. Both source paths must be editable under the assigning Designer's plan.
  Host-rebound approved repeatable edges also contribute their caller paths to
  this scope check. Partial plans retain missing-node/edge diagnostics; structural
  checks cannot erase a recorded unresolved design choice or an authority deficit.
- Preparation now retains host-derived editable paths for *all approved nodes*,
  including those the initial planner never completed. Missing plans/source are
  still missing, not fabricated successes. Newly supplied source for such a node
  is labelled `candidate_raw_source` and goes through ordinary declaration
  attachment and source admission. Existing emitted source preserves its original
  host declaration; the host replaces that suffix from the authorized revised plan.
- Scoped context supplies the current plan, adjacent edges, missing nodes, exact
  editable values, original design and existing Builder function/binding inputs.
  The original materialization and its baseline observations remain immutable.
  Referenced-node checks may use their exact hash-matched reference context;
  missing or changed reference evidence remains blocked.
- A plan edit commits an immutable `materialization` record with the candidate in
  the existing campaign transaction. Check dependencies include the plan reference,
  so a plan change cannot retain stale passing source/behavior observations. Exact
  revisit detection compares effective plan content, not its new record ID.
  No edit earns credit until the ordinary observation and judgment path values it.

Schema effects: one closed `materialization` artifact kind, no new database/index.
Explicit-path dependency fingerprints now include the materialization reference
under the empty (non-file) key; older development observations lacking it become
stale rather than being rewritten or trusted. Existing campaign-index migration
work noted below is still outstanding.

These changes have only been read and formatted. No tests, import probes, model
calls, validation Runs or replay were performed. Semantic task changes still need
successor approval; this path cannot resolve such authority by treating it as an
implementation fix. Complete task-specific measures, remaining prerequisite
children and end-to-end parent coordination are still unfinished. The historical
sections below describe earlier slices and are not current passing evidence.

## Native support/question evaluation and parent findings — not executed

Support and question proposals previously stored a claim and returned a
`proposal_ref` that the shared evaluation service rejected. There was no operative
finding or role-specific progress path. The native execution route is now wired:

- The frozen policy can provide exact `investigation_need_refs`. Each binds an
  original requirement and named decision to a mandatory, grounded execution
  check, a target option/source, applicability/limits and the meaning of each
  decisive outcome. Child assignment admission requires coverage of its declared
  contribution. The child cannot write or change these meanings.
- The model selects an observation bundle by check identity. The host includes
  its guards and binds the choice to the current assignment/unit. All observations
  pass through `RefinementEvaluations`, ordinary source admission, the existing
  executor and authenticated Run evidence. This is the same native Target Workflow
  route as verification, not a new support runner or fabricated observation.
- `investigation.py` projects current evidence to bounded advisory findings.
  Reports and subsequent caller context retain the named decision/option or
  source, measured state, exact candidate/measure/environment, applicability,
  limitations and original observation/evidence refs. Relevant selected reference
  bodies enter as data, never system-prompt replacements or model summaries.
- A supported or refuted question option can resolve its named distinction.
  Support requires demonstrated applicability; rejecting a source leaves the
  guidance gap open and earns no closure credit. Current dependencies and passing
  guards are required. Stale/contradicted evidence has no operative finding.
  Unit measurement, publication checks and numerical control use these same
  decision facts without copying child scores to parents.
- Unavailable candidate execution returns to the caller as a source-admission
  decision, also for these roles. It is not a negative answer or a successful
  guidance search.

This completes only the native-observation path. It does not implement library
queries, general reference/review instruments, new instrument code or admission
of dynamically designed investigation needs. Those remain required work; the
Goal 5 guidance files are unchanged. A passing example alone is not authority to
claim task applicability: the parent must already have grounded the relevant
check and its limited decision meaning.

No new table, host action, worker capability or replay facility was added. New
parent reports carry `investigation_findings`; earlier v1 reports can omit it
without changing their identities. Formatting and whitespace inspection only;
no tests, model calls or Runs were performed.

## Verifier determinations versus repair progress — not executed

VerifyBehavior's credit path now matches its goal of establishing behavior,
including counterevidence. Previously it could finish a decisive failing check,
but its unit measurement and rarefaction inputs still admitted only passes.

- `judgment.operative_check_facts` supplies the same role-specific projection to
  unit measurement, numerical observation and independent publication validation.
  It requires authorized checks under the assignment's own measure and purpose,
  operative current-candidate evidence, and resolved required guards. Unit credit
  additionally requires that unit's committed original evidence.
- Verification facts distinguish the exact criterion, evidence kind, environment,
  extraction/dependencies, instrument inputs and pass/fail outcome. They omit Run,
  candidate, assignment and output-variant identities. Repeating a failure or
  alternating already-known outcomes cannot earn those facts again within the
  judgment lineage. Acquisition errors, inconclusive results, stale evidence and
  contradictions earn no determination credit.
- A verifier may establish a native check result without establishing an entire
  multi-check requirement. Implementer/Designer/Parts repair credit still requires
  passing evidence, passing preservation guards and, for materialization, all
  checks for the requirement. Parent projections never copy verifier credit.
- Exact pass/fail check outcomes already present in the Builder handoff are
  excluded from fresh verifier facts. The earlier exclusion of satisfied baseline
  requirements remains in force for repair progress.

No artifact/table or runner was added. These source changes have not been tested
or executed; no claim of negative-verification transport coverage is made.
The native support/question path is now present as described above; broader
support search, general instruments, successor criteria and complete nested
execution remain unfinished. Plan repair was connected subsequently as above.

## Composed grounded measures — first admission route, not executed

EstablishMeasure can now compose independently authorized cases and submit the
result to the existing evaluation service. Previously every consumer accepted
only the initial `policy.check_refs`; newly proposed instruments remained inert.

- The frozen policy may explicitly supply `measure_admission` with an exact
  `adequacy_measure_ref` and authorized `grounding_refs`. The assignment must use
  that adequacy measure, and its permitted actions must include `admit_measure`.
  No such authority is invented by preparation or the worker.
- `measure_admission.py` supports registered observation predicates with committed,
  independently supplied positive/negative controls. A proposed case manifest
  composes exact grounding references. The host preserves the requested original
  requirements, expected values, observation extraction, domain, environment,
  independence/uncertainty limits, guards and authorized instrument inputs.
- This first route supports the native Target Workflow instrument already handled
  by the shared evaluation service. It does **not** certify arbitrary generated
  instruments, independent-execution or approved-review claims. Those unsupported
  routes produce a recorded rejection/parent-decision return, not usable checks.
- Successful admission installs checks and a scoped measure/evaluation binding in
  the campaign transaction. They become selectable by the assigning parent and
  its descendants. A later Designer can select them before creating its coder;
  existing active/ready/waiting assignments cannot have their criteria replaced.
- Context, assignment admission, plan admission, evaluation, parent judgment and
  attainment now consult the admitted scoped catalog as well as initial checks.
  The frozen policy itself is not mutated. Returned reports retain admission refs.
- Control results and original fixture/grounding evidence are retained. Publication
  re-derives successful admission, and unit credit counts distinct demonstrated
  requirement/criterion/instrument combinations. Re-grouping cases or adding new
  proposal/assignment labels does not create new adequacy credit. Rejection earns
  zero and returns its host-derived reason to the owner.

Schema effects: one closed `measure_admission` artifact kind and a `measure`
collection in the existing campaign index; no new database or runner. Old parent
reports without `measure_admission_refs` remain readable unchanged. The index
collection constraint still needs the unified schema migration for pre-existing
development campaign databases; only the fresh-table declaration has changed.
No database or persisted campaign was opened or migrated during this work.

This is partial implementation, not proof of a generic instrument-design loop.
Generating/validating new instrument code, obtaining new grounding, broader support
observation instruments, root/successor measure coordination, partial-plan repair and complete
execution remain open. No tests, model calls, Runs, replay, or activation occurred.

## Parent-local assessment of returned evidence — not executed

`judgment.py` now connects independent child verification to the parent's ordinary
unit close. It is a projection of existing evidence, not another execution or
replay service:

- Only a direct VerifyBehavior invocation actually entered in this parent unit
  and durably returned is eligible. Its original observation must still be
  operative and applicable to the current candidate. Designer/Implementer claims,
  another parent's reports, old unit returns and child numerical scores are not
  accepted as contributions.
- The host evaluates each applicable frozen parent-local predicate over the
  original observed value. Runtime reuse requires matching requirement,
  environment, dependency scope, observation path and an instrument/input context
  already authorized for that parent check. Static reuse requires the exact
  native check and predicate. Unmatched checks remain uncovered; disagreement or
  acquisition failure cannot become a passing assessment.
- A `parent_assessment` retains its parent assignment/check, exact candidate,
  source report/observation refs and the original evidence refs. It is committed
  atomically with the parent's unit receipt and credit, without overwriting the
  child observation index or manufacturing another Run. The publication boundary
  independently re-derives the expected assessments before accepting credit.
- Existing guard, static all-check, baseline exclusion and semantic deduplication
  rules apply on the parent's own measure. Repeated reports/restored passes do
  not acquire new semantic identities. Reports and scoped context retain bounded
  assessment references; runtime context labels historical assessments whose
  source or dependency state is no longer current.
- Judgment purpose now follows ownership, not the first check in a list:
  Parts requests composition; Designer requests acceptance; its VerifyBehavior
  child inherits that choice. Context, evaluation admission, attainment and
  report gaps use the same purpose. This fixes a concrete baseline-loop mismatch
  when acceptance/composition checks share a measure. Verification can finish a
  determinate failing assessment; the enclosing repair still requires passes.

No new database/index, host action, worker capability, or replay mechanism was
added. The new assessment kind is a closed v1 record. New unit/report/context
records emit `assessment_refs`; earlier v1 records without that field remain
readable with their original hashes. No persisted records were rewritten.

These changes have only been read and formatted, not run. The verifier's own
negative-determination credit is now implemented as described above, but remains
unverified. Broader support/measure judgments and full end-to-end parent acceptance
remain unfinished/unverified.
Task-specific instrument admission remains partial. The later plan-repair slice
is described above and remains unexecuted.

## Refiner materialization and nested interfaces — not executed

The seven reasoning roles now have eight library entry bindings: the launch
Parts entry and the callable Parts entry share the same implementation. This is
not an extra stage or a new role. The launch entry keeps the existing empty Duet
request; recursive Parts receives the fixed campaign/assignment/invocation parent
request. The workflow proposal declares both before approval. Launch can choose
Designer directly; it does not have to call another Parts just to begin work.

- The Builder reference resolver now locates the refiner library entries.
- Exact approved refiner references fix their source, result, Episode builder,
  schema and host-receipt controller adapters. The planner copies those bindings
  rather than selecting the ordinary incidence controller for a host receipt.
  Only exact registered reference IDs select this behavior; a generated interface
  name or a modified lookalike reference cannot opt in. Other Episode references
  retain their existing materialization behavior.
- Builder planning retains the required empty launch contract, the typed child
  contract and one `report` channel. ABI wrappers receive their materialized
  channel IDs and use the shared registered role implementation. The wrappers
  still go through ordinary emission, static admission and isolated activation.
- Child results correlate the original report ID in both the typed artifact role
  and the declared result channel. Worker and host admission check the exact
  child channel IDs. Repeatable receive bindings now carry the fixed payload
  contract required by the existing planner.
- Host session validation distinguishes the launch entry from callable Parts,
  checks the exact frozen reference/adapters, and resolves the actual parent's
  template from its runtime path. Activated bindings are compared with the plan
  by the existing linker. The declaration-only refiner library module is included
  in the existing staged source manifest for that check; host campaign/admission
  services are not added to the worker import surface. No root-request exception
  or new approval was added.

These edits address concrete interface conflicts found by reading the code. No
refiner package has been built or executed to demonstrate them. No tests, live
Runs or model calls were run, and normal-build activation remains unchanged.
Current development workflow proposals/fixtures using the former root-as-callee
shape need rebuilding under the revised references; existing approved artifacts
are not silently rewritten.

Task-specific measure admission, support-role evaluation, partial-plan/detail
repair, and complete parent progress/acceptance remain unfinished. Full execution
and lifecycle integration also remain unverified. No completion claim is made.

## PR #31 handoff integration — not executed

The Builder now owns the initial materialization handoff, static requirement
identities, callable checks and initial satisfaction measurement. The Refiner
does not reconstruct those requirements or rerun checks when importing them.

- `preparation.prepare_refinement` reads the exact published handoff and checks
  it against the selected workspace baseline. It imports the verified record
  into the existing Duet artifact store, retaining its native identity and hash.
  Campaign admission checks that imported record against the BuildStore copy.
- The initial candidate uses the handoff's exact file map, including rejected raw
  source. The original raw/completed source kinds remain available to the coding
  roles. Missing or ambiguous files stay missing, not fabricated.
- The task catalog projects the Builder's static requirement IDs unchanged.
  Approved contract fields and call boundaries remain separate coverage anchors
  for parent-owned behavioral measures, not requirements discharged by static
  checks. Baseline observations are not installed as fresh Run observations or
  awarded refinement credit.
- Parts/Designer context includes scoped static checks and original observations,
  dependency relationships and the registered progress definition. The recorded
  baseline remains explicitly labelled as baseline; it is not a verdict on an
  edited candidate. Raw model transcripts are not spliced into role prompts.
- The existing pending source-admission extraction retains PR #31's accumulated
  emission findings, cancellation behavior and terminal handoff publication.
  The new static checks distinguish concrete planning inputs from host-installed
  repeatable call bindings; module admission includes both kinds of edge.

The next implementation pass connects candidate materialization checks through
the same evaluation service as validation Runs:

- `episode_builder.emitter.complete_module_source` is the common raw-source
  completion step for initial emissions and repaired candidates. It retains the
  existing syntax/export checks and host declaration attachment. It does not
  import or execute Target Workflow code.
- `candidate_source.project_candidate_sources` keeps raw and completed source
  distinct. Completed inputs must preserve their exact host declaration; raw
  inputs receive it through the common completion step. Invalid inputs remain
  candidate evidence and produce typed Builder deficits. Valid independent
  modules still reach ordinary whole-package admission.
- Source/Run binding re-derives the completed file hashes from the exact candidate
  and checks the validation plan against its baseline. The input candidate's raw
  hashes need not equal completed-module hashes, but the host's deterministic
  projection must match the actual package.
- `materialization.py` proposes local, acceptance and composition checks from
  the Builder's exact requirements before campaign admission. The supplied policy
  must authorize `observe_materialization`; preparation does not grant that
  authority itself. Behavioral check proposals remain separate.
- `evaluation.py` admits static observations before considering a validation Run.
  Static-only work does not launch an unnecessary Run. Mixed evaluations run
  behavioral checks only after complete source admission. Both kinds enter the
  same observation, regression, parent-report and numerical-control paths.
  A static-only child can return its scoped determination even when an unrelated
  part blocks the whole package. A verifier needing runtime evidence instead
  returns the source-admission failure to its owner.
- Static source-shape checks may consume candidate-derived raw input. This is
  explicitly labelled candidate provenance, not a fabricated model emission.
  Recorded check identities must still match the frozen Builder handoff.
- Static credit is keyed by requirement, not check count. The registered
  `requirement_satisfaction` function requires all declared checks. Baseline
  satisfied requirements are excluded from fresh credit and numerical incidence;
  later restored passes cannot earn duplicate credit. Publication checks enforce
  the same rule independently of the proposed unit receipt.

These are unexecuted implementation changes. The unreleased check record now
requires `evidence_kind` (`materialization` or `execution`); older development
fixtures/campaign inputs need to declare it. No migration of existing campaign
data was attempted. No separate replay mechanism or testing harness was added.

**Next central work:** admitting task-specific behavioral measures and their
instruments, completing support-role evaluation, and permitting approved
materialization-detail/partial-plan repair through the same path. The refiner's
own emitted root/call wrappers also remain unexecuted. At this stage the source
adapter still required the original plan; the later candidate-plan path above
removes that restriction without changing approved workflow authority.

The `evaluation.py` connection uses the existing executor for a native approved
Target Workflow and records source/Run correlation. It is not a general instrument
implementation yet, has not executed, and does not handle every support/measurement
request. No normal-build activation occurred. No tests, model calls, validation
Runs, or replay were run during this update.

## User-directed priority correction

The user has resumed implementation with a narrower order: build the actual
Parts → Designer → Implementer system and connect the existing worker/executor
first. Do not run tests now. Do not build refiner-specific replay facilities or
more separate test infrastructure. Unified testing/replay belongs to the later
acceptance work, with one documented, agent-usable CLI and explicit arguments.
This instruction supersedes the earlier verification-first sequence below.

Removed the standalone `recovery.py` projection-reconstruction verifier and
`CampaignStore.verify`, plus the subprocess evaluation fixture and tests that
depended on that disconnected execution path. Removed its dedicated recovery
tests too. The ordinary transactional revision history and duplicate-credit
checks remain part of campaign operation, not a separate replay service.
The unused refiner receipt-outbox scaffolding was also removed; later unified
replay must not depend on an unconnected refiner-only reconciliation path.
Removed work is recoverable from
`/tmp/openchia-refiner-ablation.fx25zH/removed-work.tar` on this development host.

The immediate deliverable is the registered Episode structure and its common
operation path, not additional proof machinery. The old passing counts below
are historical evidence only; they do not describe the current edited tree.

## Central implementation after that correction — not executed

- `episode_library/refinement.py` registers the seven agreed role designs plus
  the distinct launch entry described above;
  `iterative_episode_refiner/design.py` assembles their complete workflow proposal
  for the ordinary Duet approval and Builder path. It does not grant approval.
- `function_library/refinement.py` spells out the actual unit sequences using
  existing `Episode` and `ChildEpisodeUnit`: Parts selects work; Designer admits
  design then calls Implementer then VerifyBehavior; Parts requests enclosing
  verification. Baseline verification can return already-correct work without edits.
  Prerequisite children return into the enclosing measured loop. No separate
  general-purpose stage engine or hidden retry scheduler was added.
- `iterative_episode_refiner/runtime.py` and `runtime_proposals.py` connect those
  role requests to the existing campaign records: scoped assignments, model-event
  provenance, source edits, typed child returns, host credit, and joint repair
  selection/resolution. Models receive scoped original observations, history,
  conflicts, lessons, design plans and rejection feedback—not transcript summaries.
- One refinement channel was added to the existing worker protocol and executor.
  `execution.execute_refinement` supplies its explicitly approved host session.
  Ordinary Runs have no such session. The existing worker, confinement and Run
  executor are reused; the user's normal build/Run lifecycle is not redirected.
- `preparation.py` reads the actual baseline through the existing workspace
  and the Builder's immutable handoff. It proposes the initial source revision
  and root Parts assignment, preserving static requirements and separate contract
  coverage. Rejected raw source is retained; genuinely missing source remains
  absent on writable planned paths. The host supplies the
  authorized policy and measures. Preparation does not approve or run anything.
  After host admission, `start_refinement` installs that proposal through the
  existing campaign boundary; `execute_refinement` uses the existing executor.
- Role context now includes the assigned goal, original requirement values,
  relevant materialization findings, available measures and explicit measurement
  gaps. Parts/support roles no longer receive all source bodies by default;
  Designer/Implementer receive their scoped source. This is a typed projection,
  not a model-written summary of the materialization.
- A Designer now selects the Implementer's local measure in its design plan;
  it cannot change its own parent-assigned acceptance criterion. Plan admission
  requires installed, authorized local checks covering the assigned contribution.
  The coding child and each edit retain that exact plan/measure pairing.
- EstablishMeasure now accepts a parent-defined purpose and requirement scope,
  proposes an exact instrument/grounding/control contract, and can call its
  permitted ResolveQuestion child for a prerequisite. Proposals are indexed as
  **proposed**, not installed measures or positive yield. Typed parent reports
  retain their references; the parent's context includes the direct child report
  and proposed instrument, without a model-generated summary. The role passes
  the exact proposal reference to the shared evaluation entry point for adequacy.

**Still central and unfinished:** task-specific measure creation/admission (the
proposal/parent handoff is present, but operative measures still require
predeclared checks); and completion of the one shared validation service behind
`evaluations.evaluate`, beyond its unexecuted native-workflow route. That service
must bind exact candidate source and parent checks to existing admitted Runs.
No test fixture may substitute for it. The
support/measurement role loops are registered, but their complete task-specific
behavior depends on these same connections. Source admission and emitted wrapper
compatibility also remain unverified. The new preparation path still needs the
parent-measure/admission connection; it is not an autonomous ready-to-run setup.
In particular, resolving instrument-build or missing-grounding requests and
admitting newly demonstrated instruments are not replaced by the new proposal
schema. They still need the shared validation/admission path.

No tests, live model calls, worker Runs, or replay checks were run after this
correction. Formatting only was applied. These additions are implementation in
progress, not evidence that an end-to-end repair has succeeded.

Future test/replay work must expose one documented CLI over the shared execution
service, selecting persisted Run/campaign, candidate and check identities with
explicit arguments. Callers must not reconstruct internal state or use private
per-role replay helpers. That CLI/harness is deferred to the later work requested
by the user; no alternative replay command was added here.

## Durable state implemented so far

| Responsibility | Actual implementation |
| --- | --- |
| Immutable typed artifacts, canonical identities, evidence pointers | `iterative_episode_refiner/records.py` |
| Audit-first attempts, transactional candidate/index/credit CAS, duplicate-operation protection | `campaign_store.py`, using existing `DuetStore` artifacts/events/transactions |
| Exact source blobs and original Run evidence | `evidence.py`, existing `BuildStore` and `RunStore` |
| Scope/role admission, Designer-owned Implementer, scoped file changes and invalidations | `state_machine.py` |
| Registered predicates, actual observation admission, conditional lessons, unit measurement | `measurement.py`, `function_library/refinement_checks.py` |
| Host numeric continuation and role-specific attainment | `control.py`, existing numerical libraries, `function_library/refinement_control.py` |
| Independent credit/continuation checks before operative writes | `integrity.py` |
| Exact revisits, opposing regressions, contradictory evidence | `cycles.py` |
| Typed unwinding to the actual Parts owner, joint assignment and evidenced resolution | `coordination.py` |
| Focused lesson/action context and deterministic parent reports | `context.py`, `reports.py` |

New tables are additive indexes in the existing Duet database, created by
`CampaignStore`; they are not a second database. The old `refinement_cycles`
meaning is unchanged. New campaign records remain version 1/unreleased. Old
workflow/materialization encodings are retained when the optional repeatable-call
extension is absent. No Run encoding change has been made yet.

The causal write path is: durable attempt → committed evidence lookup →
host admission → immutable candidate/observation/lesson/receipt records →
independent integrity checks → atomic deltas/indexes/credit/commit/Duet event.
An invalid proposal remains audited without becoming operative. Retrying an
identical operation returns its existing commit; changing its payload is rejected.

Source changes invalidate dependent checks immediately. Cumulative credit does not
force invalid evidence to remain operative. Exact source revisits are warnings,
not a proof of futility. Opposing regressions use comparable measured outcomes in
candidate-revision order, including the editing assignments, not prose summaries.
Late results cannot reorder that repair history. A joint assignment retains the
original criteria, guards, evidence and credit lineage. The conflict remains open
until all required checks pass on one current candidate.

A failure itself earns zero. Separately admitted advisory lessons are conditional
on the exact candidate and retrieve before a matching retry. Negative progress
identities are keyed to the grounded criterion, inputs and environment, not source
bytes, Run IDs, prose, or the grouping of a lesson. Cosmetic variants and splitting
a multi-criterion lesson cannot mint fresh credit. Conflicting evidence suspends
the operative lesson instead of keeping whichever result would be favorable.

## Historical verification evidence and limits (before ablation)

The earlier focused suite exercised SQLite transactions, immutable blob storage
and RunStore audit records. The now-removed evaluation fixture executed Python in
fresh subprocesses and recorded their computed answers. It **used inert executor
attestation** and did not prove confinement, the new worker transport, or
autonomous/model-driven reasoning. Its removed tests are not current coverage.

Covered scenarios include:

- stale edits, invalid paths and immediate evidence invalidation;
- restored correctness without duplicate credit;
- failure with and without an admitted lesson, scope-aware retrieval and reopening;
- crash injection, atomic rollback, identical retry, and corrupted projection detection;
- independent publication rejection of forged numerical completion;
- computed order-preservation/deduplication repairs that oscillate across child
  assignments, unwind through Designer to Parts, and succeed under a joint repair;
- independent part verification before Designer completion, while enclosing
  composition remains explicitly unverified;
- contradictory computed answers from unchanged source with an undeclared input,
  making the check unresolved and suspending its lesson.

Latest full focused run: **18 passed**, using:

```sh
HERMES_PYTHON=<isolated-PM-test-interpreter> scripts/run_tests.sh tests/iterative_episode_refiner --file-retries 0 -q
```

No result here is a Goal 6 acceptance receipt. The test proposes the fixes; it
does not demonstrate an LLM discovering them. No confinement result is inferred
from a RunStore fixture.

## Repeatable-call integration added

`agent/episode_call_contracts.py` now carries exact call selections in an optional
v1 workflow extension, preserved by the existing blueprint and approval path.
The concrete parent tree is unchanged. `episode_builder/call_plan.py` adds the
approved call slots only after concrete template planning; the materialization
plan separately records its v1 repeatable edges and indexes all their registered
function definitions. Unknown functions, overlapping concrete slots, omitted
approved calls and altered policy arguments fail admission. Existing registry,
source-emission, source-declaration and specification-inspection paths are reused.

`episode_runtime/repeatable.py` constructs the declared method-loop graph and
guards asynchronous template invocation. The runtime verifies the actual parent
path, child request/goal/address and exact schema, attenuation and admission
functions before construction. `linker.py` derives a nested root-template
instance's identity from its actual path, rather than treating every root-template
call as the Run root. The new dependencies are included in the staged source
closure. `function_library/episode_calls.py` supplies the reusable async builder.

This is **not yet a demonstrated executing refiner**. The role policies, scoped
host session and worker transport added above have not been executed; the shared
validation service and task-specific measure admission remain to be connected.
The call-materialization tests carry registered pointers as identity sentinels;
they exercise real approval, Builder, source admission, activation and linking,
but do not execute those sentinels as refiner policies. The separate invocation
test uses deterministic test policies to check construction denial and correlation.

Combined focused verification: **45 passed** across 14 files, including all 18
state tests, builder checks, call-boundary checks and the existing in-process
inquiry loop. Ruff and `git diff --check` pass. Command:

```sh
HERMES_PYTHON=<isolated-PM-test-interpreter> scripts/run_tests.sh tests/iterative_episode_refiner tests/agent/test_repeatable_episode_calls.py tests/episode_builder tests/episode_runtime/test_repeatable_invocations.py tests/episode_runtime/test_reasoning_workflow.py --file-retries 0 -q -k 'not live_confined_reasoning_worker'
```

The confined inquiry test skipped on the earlier unfiltered invocation; it was
explicitly deselected for this compatibility run. This supplies no new confined
worker evidence. The existing runtime test fixture required a relative conftest
import and the current executor-kind/unit/invocation attestation fields after the
merged executor API change; those fixture corrections do not weaken assertions.

## Earlier remaining-work inventory (order superseded above)

The state/control core is present, but the full goal remains unproven. Required
next work includes:

1. Complete the task-specific measure/progress contracts and role projections,
   including distinct joint-acceptance facts, supported negative verifier
   determinations, baseline EXCLUDED incidence, and parent remeasurement of child
   evidence without copying child credit.
2. Supply the production refiner's repeatable-call policies and prove nested Parts
   execution through the real worker. The generic approval/build/link boundary is
   present, but its actual campaign admission and recovery are not yet connected.
3. Add finite declared semantic-unit stages, durable pending-stage recovery and
   authenticated incomplete child returns. The current campaign invocation/index
   logic is not yet the executing method-loop adapter.
4. Connect a scoped host broker to the real worker protocol. Authenticate the
   active invocation and producer events; implement receipt outbox publication,
   rejection, cancellation and replay. Keep blocking persistence off the event loop.
5. Bind exact candidate/harness validation to separately registered, admitted Runs
   through the existing executor; preserve confinement and the user's session Run.
   Connect implementation-detail classification to existing approval boundaries.
6. Register and execute Parts → Designer → Implementer and support/verification
   roles through an explicit approved refiner entry point, including genuine
   parent acceptance and already-correct behavior.
7. Verify these paths with actual transport/confinement and compatibility checks.
   An unavailable capability is an explicit unverified requirement, not permission
   to replace this evidence with an in-process substitute.

Goal 5 guidance content is preserved separately in
`episode_library/refinement_guidance/`; its runtime consumption is not yet proven.
Goals 6–7 remain outside this assignment. The legacy refiner service remains
unchanged; its presence is not evidence that the executing refiner is complete.
