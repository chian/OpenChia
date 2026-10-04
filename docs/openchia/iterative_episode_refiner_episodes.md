# IterativeEpisodeRefiner: finalized design

Version 3 — 2026-10-02. This is the design baseline for implementation planning,
not a claim that the system is implemented or an authorization to start coding,
run tests, commit, or publish.

This version replaces v2's direct Designer-to-Designer recursion. Only the Parts
owner creates design assignments. Specialists use the same Designer machinery
with task-specific instructions. Cross-part regressions are reported during
iteration, not only when a child finishes.

Related records: [principles](iterative_episode_refiner_principles.md),
[design goal](iterative_episode_refiner_goal.json),
[review](iterative_episode_refiner_review.md), and
[implementation goals](iterative_episode_refiner_implementation_goals.md).

Goal 1 now has a detailed [contract proposal](iterative_episode_refiner_contracts.md),
[repository integration map](iterative_episode_refiner_integration.md), and
[contract self-review](iterative_episode_refiner_contract_review.md). They elaborate
this baseline for review; they do not claim implementation or executable approval.

## 1. What this must do

The IterativeEpisodeRefiner takes an initial materialized Episode build and
finishes its repair and validation. It must accept any materialization-spec'd
build, including broken source, unfamiliar tasks and nested Episodes. Missing
knowledge, evidence or authority produces an explicit unresolved result; it is
not a reason to silently omit a class of builds or claim success.

The same design must be available in the Episode library and used in OpenChia's
normal build-finalization path. A library example alone is not completion.

~~~text
approved Target Workflow Architecture
  -> initial one-shot Builder output, materialization and boundary findings
  -> IterativeEpisodeRefiner
       <-> candidate revisions, build admission and isolated validation Runs
  -> exact verified build, or explicit unresolved result with preserved work
~~~

The existing IterativeEpisodeRefiner service binds notes and evidence to an
approved baseline and classifies proposed changes. It is not this active Episode.
Preserve and rehome that work as Builder/approval boundary services. Do not remove
its approval, provenance or semantic-change safeguards.

The refiner's admitted implementation is independent of the candidate being
repaired. A candidate does not need to import, compile or run before it can be
examined and edited as data. Execution still requires source admission.

The refiner and its reasoning children use the Duet's model/provider
configuration. Target Workflow test Runs use the Target Workflow's selected launch
configuration through the shared harness; they do not change the refiner's
model. No separate refiner launch file is required. This configuration boundary
is distinct from the approved Episode nesting and capability boundaries; see
the [routing contract](episode_launch_configuration.md#duet-refiner-and-target-model-boundary).

## 2. Episode ownership and nesting

### RefineParts: choose work and make the whole scope work

The root IterativeEpisodeRefiner is a RefineParts Episode. A nested RefineParts
has the same responsibilities for a smaller scope.

It owns the requirements for that scope, decomposition, dependencies, selection
of the next problem, and assessment of each result's contribution to the whole.
A part is a behavioral problem, not necessarily a file or Target Workflow Episode node.

Only this role may create a DesignPart assignment or authorize a nested
RefineParts. It can choose a separate problem, a prerequisite, or a joint problem
when attempted repairs show that earlier boundaries were wrong.

### DesignPart: design and realize a working solution for the assigned part

The Designer owns its approach through implementation and part acceptance. It
does not return successfully just because it wrote a design document.

It uses task-specific instructions and examples but the same underlying Designer
loop. Numerical-controller design is one assignment covering credit, rarefaction
and continuation together, not three independently completed specialties.

The Designer may call implementation, investigation, measurement and verification
children. It may not create another Designer or a Parts Episode, including through
a helper acting on its behalf. New design subproblems go back to its Parts owner.

### RefineImplementation: make and measure actual code changes

This is the coding Episode. It proposes scoped source/specification-detail edits,
has the host commit candidate revisions, and measures them under its own fixed
local contract. Its local measurement is not the parent's VerifyBehavior Episode.

It cannot change its goal, measuring rule or protected checks to make a failure
pass. A deficient assignment, inadequate measure or cross-part conflict returns
to the Designer, and to the Parts owner when broader coordination is needed.

### The allowed structure

~~~text
RefineParts: choose an eligible problem
  DesignPart: choose and evaluate approaches for that problem
    required design/measure preparation
    RefineImplementation: edit -> local measurement -> iterate
    required part acceptance
  required assessment of contribution to the enclosing whole

RefineParts may instead delegate a proper sub-scope to RefineParts
  that owner selects and coordinates its own DesignPart assignments
  all levels use the same campaign revision and regression history
~~~

Implementation follows admission of its design and local measure. Acceptance
follows a candidate result. These are required steps, not interchangeable sibling
choices. Each parent keeps responsibility for finishing its declared unit.

If a Designer needs a new design assignment, it returns a structured unresolved
result. The Parts owner decides whether to split, merge or replace assignments.
Its own loop continues; that child return does not end the refinement campaign.
An unchanged assignment is not restarted with its history erased.

Recursion belongs to the Parts owners. A nested scope must have a specific
contribution, inherited constraints and an identified parent responsible for
cross-scope effects. Do not add wrappers around equivalent active work. Dependency
cycles return to the nearest owner that can address the coupled problem.

## 3. Specialties and finding design guidance

Start with a reusable Designer, not a separate implementation for each task type.
Its assignment can carry instructions for reasoning, calculation, simulation,
goal/contract design, numerical-controller design, or an unfamiliar combination.
The general route remains available when no established specialty fits.

The Parts owner can reuse a suitable instruction set or call FindDesignSupport
to search approved library material. Use existing search/library components where
their contracts fit; do not create a second Episode or function registry.

FindDesignSupport returns selected instructions/examples, exact source identities,
why they apply, their assumptions and limitations, conflicts, and missing coverage.
A relevant example is guidance, not proof that its implementation or checks fit
the current task. Broad example curation remains later work.

Prepare the specialty instructions before the child starts. Later retrieved
material enters as typed reference data; it does not rewrite the active system
prompt, goal or judgment contract. Raw web pages and model-written summaries do
not become privileged instructions. The parent admits the assignment and concrete
checks; finding a plausible example cannot silently change either.

A new specialist implementation is justified only if it needs a different
declared repeated unit or child workflow that the reusable design cannot express.
It requires the normal approval/materialization process, not invention during
an active Run.

## 4. Goals, repeated units, measures and calls

Every assignment identifies its goal, parent, scope, exact baseline, protected
requirements, required evidence, concrete local measure, authority, instruction
references, return contract and fixed numerical-control components. Each child
receives relevant prior attempts and the requirements it must preserve.

| Episode | Goal and repeated unit | Basis of its own progress |
| --- | --- | --- |
| RefineParts | Satisfy the enclosing scope; select a problem, obtain its result and assess its contribution | Newly established contribution to the whole or useful admitted learning, not part counts or summed child scores |
| DesignPart | Realize a solution to the assigned problem; choose an approach, prepare it, implement it and assess the part | Measured improvement under the part contract or useful admitted design knowledge, not design prose |
| RefineImplementation | Meet the implementation contract; attempt a candidate change and perform local measurement | New demonstrated improvement with required regression guards, not edit volume |
| FindDesignSupport | Fill a named gap in design guidance; search, compare and admit applicable material | Evidence-backed coverage of that gap, not retrieved-document counts |
| ResolveQuestion | Resolve a decision-relevant uncertainty; choose a discriminating observation and assess it | A supported distinction that changes the decision state, not confidence or speculation |
| EstablishMeasure | Supply an adequate instrument for a named requirement; propose/revise it and check adequacy | A demonstrated improvement in what the instrument can reliably establish, not assertion counts |
| VerifyBehavior | Determine whether the exact candidate meets the parent's requirements; perform an independent check or justified bundle | New operative evidence, including counterexamples; a favorable verdict is not itself credit |

| Parent | Permitted children and purpose |
| --- | --- |
| RefineParts | DesignPart for a selected problem; RefineParts for a coordinated sub-scope; FindDesignSupport, ResolveQuestion or EstablishMeasure for a specific prerequisite; VerifyBehavior for baseline/integration acceptance |
| DesignPart | RefineImplementation for scoped realization; FindDesignSupport/ResolveQuestion/EstablishMeasure for identified needs; VerifyBehavior for part acceptance |
| RefineImplementation | ResolveQuestion for a concrete implementation uncertainty |
| EstablishMeasure | ResolveQuestion for missing grounding |
| FindDesignSupport, ResolveQuestion, VerifyBehavior | No designer or coordinator children; permitted observations/execution stay inside their declared unit |

RefineParts owns assignment/decomposition proposals. DesignPart owns design and
implementation proposals inside its assignment. RefineImplementation owns source
editing, including a check instrument when explicitly assigned to build one.
The other roles cannot repair the target or change the criterion being evaluated.
The host owns publication, admission, credit and authoritative status.

When an instrument needs code, its owner routes a grounded instrument-building
assignment through the existing design/coding path. This may be preparation inside
the current scope; a new independent design goal requires the Parts owner. The
instrument cannot certify itself, and its coding loop needs a valid local measure.

Each unit declares its stages and possible outcomes. A partial result can advance
an eligible prerequisite or close an incomplete attempt. Repetition belongs to
an Episode's measured loop, not an uncounted retry loop hidden in a stage.

The current child-result wrapper supports parent-owned projection, but it does
not alone supply the designer's multi-stage execution. Required child execution
and continuation must be explicitly represented and audited, not hidden inside
a supposedly pure projector.

## 5. How assignments and measures stay faithful to the task

The Parts owner and Designer derive assignments from the approved purpose, the
target's repeated unit and result meaning, its interfaces and enclosing role,
and committed evidence of its current behavior. The relationship must be explicit:

~~~text
required behavior -> observed gap -> proposed repair/design
  -> local measure -> candidate implementation -> parent acceptance
~~~

The three judgments remain separate:

- Implementer: did the candidate improve the assigned implementation and preserve
  the required conditions under its local measure?
- Designer: does the implemented approach satisfy the part's actual requirements?
- Parts owner: does that result improve the whole, including its interaction with
  other parts?

The child must receive its measure before coding starts. Challenge a proposed
measure with incorrect or trivial outcomes that it should reject; do not derive
expected behavior from the defective implementation. A schema-valid proposal or
agreement between models is not proof of adequacy.

Role-level admission, credit and continuation policies are pre-established.
Target-specific instruments are versioned artifacts admitted under those policies.
A Designer repairing a target's credit function cannot change the function judging
its own work. Changing an active child criterion requires a successor assignment;
changing the approved purpose requires the relevant Duet approval.

Some domains lack a mechanical oracle. Preserve the limits of the evidence and
the declared human/review requirement. Do not invent objective certainty or create
an endless chain of agents judging other agents to conceal missing grounding.

## 6. Shared state and information passed between Episodes

There is one campaign workspace containing the working materialization, code,
requirement status and compact review record. “Shared” means shared within this
refinement effort, not unrestricted global memory or identical model contexts.

Keep three information products distinct:

1. **Audit:** exact calls, source/check/environment revisions, observations and
   admission/measurement decisions. Raw content is evidence, not instructions.
2. **Local iteration state:** assignment, current candidate, alternatives tried,
   measured outcomes, assumptions, unresolved questions and applicable lessons.
   Collect these records during the units; do not reconstruct them later from
   an LLM summary. Retrieve the relevant history before selecting another action.
3. **Parent report:** a deterministic, registered projection of admitted records
   answering the decisions that parent still owns. Unsupported explanations
   remain claims, even when they are well-formed JSON.

| Return boundary | Information the parent needs |
| --- | --- |
| Implementer -> Designer | Exact candidate changes, local results, regressions/stale checks, unmet conditions and evidence that a design or measure needs reconsideration |
| Designer -> Parts owner | Part acceptance, dependencies, assumptions, relevant failed approaches and specific new/conflicting design work requiring coordination |
| Nested Parts -> enclosing Parts | Integrated sub-scope result, composition evidence and unresolved cross-scope dependencies; not every internal conversation |
| Support search -> caller | Applicable instructions/examples, source identity, applicability limits, conflicts and missing guidance |
| Inquiry/measurement/verification -> caller | The supported answer, instrument or determination requested, including counterevidence, unperformed checks and limitations |

Every report binds the request, goal, examined/produced revision, evidence and
environment. It distinguishes actual change from partial, blocked or interrupted
work and identifies any parent decision needed. Evidence handles permit focused
drill-down. A large unresolved set may use an indexed artifact and bounded view;
readiness and eligibility use the full state, not just the displayed page.

Siblings receive relevant dependency changes through their common owner, not
each other's transcripts. Original evidence identities survive every projection:
an echoed parent hypothesis is not independent confirmation. Reassignment, a new
child ID or a paraphrase cannot erase attempt history or create fresh evidence.

Each boundary must support the parent's next decisions without requiring the
whole child transcript. If it cannot, change the report or the problem boundary.

## 7. Preventing repair cycles

Prohibiting Designer-to-Designer calls reduces hidden coordination, but it is
not sufficient: siblings can still alternate between incompatible repairs.

~~~text
A passes, B fails -> A fails, B passes -> A passes, B fails
~~~

### Record effects during the loop

After each admitted candidate change, persist its baseline/result identity,
assignment and responsible Episode, check results, affected requirements and
dependencies, and which previous passes became stale. A missing recheck is
unknown, not green. Conservatively invalidate evidence when change impact cannot
be established. Do not require every check to run after every edit, but do not
claim preservation without applicable evidence.

The campaign record is shared across all Parts owners and child invocations.
Children get the relevant preservation checks and conflict history. Parent-facing
state is updated at unit boundaries, not only at final child return.

This need not wake a parent model on every edit. The host records effects and
checks the declared conflict/eligibility rules. A conflict requiring a broader
decision causes a correlated return at a safe unit boundary so the owning parent
can act. It must not wait for a successful child result to become visible.

### Recognize and route a possible cycle

Detect exact revisits using stable candidate/contract/environment identities.
Also flag repeated opposing regressions even when source edits are not identical.
Similar pass/fail patterns are a warning, not proof that different attempts have
no value. Keep actual measurements, conditions and evidence available for diagnosis.

A conflict report identifies the requirements involved, candidate transitions,
supporting observations, already-tried approaches and the decision needed. A raw
model assertion cannot establish a block or an enforceable exclusion by itself.

The nearest Parts owner covering both sides then chooses to:

- Issue a joint assignment requiring A and B to hold on the same candidate.
- Correct a missing dependency, a bad measure or a wrongly assumed boundary.
- Authorize a justified reopening after a material change.
- Return an explicit specification conflict or authority/evidence gap when the
  requirements cannot currently be reconciled.

Close or replace affected assignments explicitly; do not silently edit their
criteria. The replacement inherits relevant history. If the current Parts owner
does not cover both sides, escalate to the next enclosing owner.

Restoring an old pass or switching back to an old candidate cannot repeatedly
earn credit. Current correctness changes immediately; historical credit remains
an audit fact. New, useful knowledge from the conflict may earn credit only through
its separate admission. There is no fixed retry-count rule that declares success.

## 8. Candidate consistency, yield and stopping

Edits are scoped, revision-checked transactions. Retain the approved baseline and
evaluated candidates; the latest working edit is not automatically the selected
result. Overlapping work is serialized or reconciled by its owner. Start with
serialized edits in a campaign; parallel source editing is not required for the
first implementation.

Every evaluation binds exact code, specification, checks, fixtures, dependencies
and environment. Reusing a pass requires a validated dependency match. Changes
reopen affected requirements; no owner combines passes from incompatible versions.

The host computes yield from admitted durable changes. Failure, delegation,
patch size, new labels and repeated lessons have no inherent positive yield.
Useful lessons require evidence, scope, novelty, applicability and reopening
conditions. Parent credit measures its own contribution, not child credit totals.

Valid repaired output representations receive ordinary admission and credit
judgment. Representation repair is not a new substantive reasoning unit; actual
failed implementations remain recorded as failed candidate attempts.

Each Episode has its own fixed credit, rarefaction and continuation contract.
Initial assessment of the unchanged candidate is a declared path: already-correct
work returns without invented edits. The numerical policy must account for a
satisfied goal with no remaining required opportunities.

Numerical return with unmet requirements is incomplete, not ready. Blocking,
invalid contracts, cancellation, interruption and resource limits remain distinct.
An unresolved scope conflict can require a parent decision under the frozen
eligibility policy; that is not a successful completion or a budget-based stop.
Optional improvements do not silently become new mandatory work.

The MINI review shows requirement/target, finding, status and latest evidence.
The final result names one exact admitted build and evidence for all mandatory
requirements, including whole-workflow behavior, or an explicit unresolved frontier.

## 9. Host execution, authority and recovery

Use the existing registries, handoffs, stores, model broker and executor. Designer
workers propose edits and results; the host validates authority, admits source,
publishes state, executes scoped checks and computes credit. No parallel database,
general memory service, model-call stack or replacement executor is part of this
design. Extend existing persistence with the necessary records/indexes.

Validation Runs have their own identities and evidence linked to the campaign,
requesting Episode and unit. A target sub-Episode requires an admitted harness
and typed inputs; it is not assumed independently runnable. Do not call the
single-active-session start_run action recursively or replace its session state.

Persist evidence before credit-bearing changes. Use stable operation identities
and atomic writes or recoverable stages so retries return existing receipts,
never double credit. Recover pending child/measurement/parent-decision stages
explicitly; current one-shot worker execution is not arbitrary process resumption.
Cancellation must leave a consistent candidate and honest terminal state.

The Target Workflow Architecture and the refiner's approved role graph are different
artifacts. The refiner adds scoped edit/evaluation authority and Parts-owned
recursive invocation; it does not grant arbitrary spawning to ordinary Episodes.
Concrete assignments, source identities and active control components stay fixed.
Semantic target changes go through the Duet. Successful validation does not itself
authorize production execution, a commit, a merge or publication.

## 10. Code ownership and unavoidable integration

Most new behavior belongs in the existing iterative_episode_refiner/ package,
split into focused modules for campaign state, assignments, reports, conflict
handling, guidance selection, Episode functions and host operations. These names
describe responsibilities, not a mandate to add an entire new framework.

Use episode_library/ for the refiner's reference definitions and registrations,
and narrowly scoped additions in existing function/handoff/numerical libraries.
Place package tests in tests/iterative_episode_refiner/ and integration tests in
the corresponding runtime/builder/agent test areas. That package test directory
does not yet exist in the inspected checkout.

Generated-source admission currently permits the established Episode/function
library roots, not direct imports of the host refiner package. Keep worker-facing
functions in the admitted library paths and host state behind scoped operations.
Do not broadly whitelist the host package or relax source admission to simplify
integration.

| Existing area | What remains there / expected integration |
| --- | --- |
| iterative_episode_refiner.service, .workspace, .contracts | Preserve/reclassify existing baseline, approval and workspace boundary work; put new active-loop responsibilities in focused modules, not appended to these large files |
| episode_library and function/handoff/numeric registries | Add exact refiner bindings and required components; do not redefine existing Episode behavior or introduce a second registry |
| episode_builder | Keep initial materialization and source admission; consume/reuse boundary services and expose exact initial candidate artifacts |
| method_loop.EpisodeTree, ChildEpisodeUnit, ControllerRuntime | Reuse controllers and parent-owned projection; add only the missing declared continuation/Parts-recursion support needed by this real consumer |
| episode_runtime.linker, worker/protocol/brokers and stores | Carry approved refiner roles/capabilities, scoped operations, durable receipts and correlated parent-decision returns across the real worker boundary |
| RunExecutor and its backends | Reuse execution, identity, confinement, audit and cancellation; do not build another launcher |
| agent.openchia_host | One narrow build-finalization integration plus validation-Run routing; use a focused sibling/service for new logic instead of growing the host facade |

Inspection baseline: checkout 52c9c2675995232416012bf19dd644170b7913ab
and fetched merged-main object a335059aee74c230429a4093f32330a94789cb22.
The latter supplies the shared RunExecutor protocol and systemd/container paths.
The current library refiner foundation is generic reasoning, currently a leaf.
The method loop supports declared recursive edges, but the inspected linker builds
a concrete plan tree; Parts recursion is not already an end-to-end capability.

The current host materializes through EpisodeBuilder.build, persists the
materialized baseline, and emits build_finished. That is the integration area
for the active finalizer, not a reason to change the general conversational turn
loop. The old workspace projects persisted facts; it is not already a candidate
editing engine. Existing narrow authority-reader protocols are useful boundaries
to extend rather than replacing host ownership.

This supports a relatively independent implementation, not a promise of zero
shared changes or zero regression risk. Keep the new package behind explicit
inputs and host capabilities. Do not add refiner-specific conditionals throughout
the general runtime, change global defaults early, or alter prompt/provider,
gateway, CLI, desktop or TUI behavior as part of the algorithm work.

## 11. Merge and rollout plan

Use a dedicated implementation branch/worktree based on the then-current main;
the inspected feature branch is not assumed to be a safe implementation base.
Do not reset or discard the current design work. Carry the finalized documents
forward explicitly. This design task itself creates no branch, commit or PR.

Keep changes in reviewable groups:

1. Exact contracts, host interface and refiner-local state/report/cycle logic.
2. Focused reusable library/runtime support needed for the actual refiner consumer.
3. The executing refiner Episodes, instruction selection and explicit real-path
   acceptance harness.
4. Builder-boundary reclassification and the narrow normal-build activation change.

Mechanical moves must be separated from behavior changes and update internal
callers/docs; do not keep compatibility shims or duplicate old boundary logic.
Keep existing serialized artifacts readable; migrations must be additive or have
an explicit versioned reader. Ordinary Episode execution should not pay for or
invoke refiner-specific work.

Develop and validate through an explicit approved refiner entry point before
changing normal build behavior. This is staged integration, not permission to
merge unreachable code with no concrete consumer. Production activation is a
separate reviewed change after real-path evidence. If temporary configuration is
needed, use existing configuration mechanisms, not a new behavioral environment
variable. The final delivery must activate the refiner for normal materialized
builds; leaving it permanently opt-in does not meet the objective.

Compatibility and end-to-end validation are required before activation, including
actual isolated host/worker execution. Mock-only or in-process receipts cannot
establish that boundary. Work can be kept mergeable by limiting shared changes and
rebasing reviewed work, but mergeability cannot be guaranteed without inspection
and verification against the eventual main revision.

## 12. Acceptance and next work

The [implementation goals](iterative_episode_refiner_implementation_goals.md)
provide bounded, copyable requests with concrete completion conditions. Exact
schemas and initial numerical settings are specified in the Goal 1 contract
proposal. Later empirical calibration still requires evidence and a successor
approved contract; an active model cannot improvise those rules.

Final acceptance must demonstrate actual code refinement and inspectable correct
results for more than one kind of target, including a nested workflow. Include
an already-correct build, a broken build, an A/B repair cycle resolved through a
joint assignment, missing evidence, and interrupted/replayed work. A cycle finding
or honest unresolved result is not the same as solving the target.

Inspect the exact produced build, protected checks, credit history and final
behavior. Show that old states and repeated failures cannot farm credit, and that
unrelated ordinary Episodes retain their behavior. Small invariant tests are
necessary evidence for their mechanisms, not proof of the full system.

No product tests or live runs are authorized or performed by finalizing these
documents. A later goal explicitly authorizing validation is required before
resuming them.
