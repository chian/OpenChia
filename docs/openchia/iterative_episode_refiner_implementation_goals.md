# IterativeEpisodeRefiner: implementation goals

Companion to the [finalized design](iterative_episode_refiner_episodes.md), version 3.
These are proposed future work requests, ready to copy or assign by number. Writing
them does not start implementation, tests, model calls, commits or publication.

Goals are ordered by dependency. Goal 1 is design-only. Goals 2–5 include focused
automated validation when explicitly assigned; Goals 6–7 include real execution
acceptance. Until that later authorization, the existing no-more-tests instruction
remains in force. Use scripts/run_tests.sh for product tests. No goal by itself
authorizes a commit, push, PR publication or merge.

Work update, 2026-10-02: Goal 1 was explicitly assigned. Its deliverables are the
[contracts](iterative_episode_refiner_contracts.md),
[integration map](iterative_episode_refiner_integration.md), and
[self-review](iterative_episode_refiner_contract_review.md), for review before coding.
The user also separately assigned a parallel head start on Goal 5's guidance
organization/content. That does not claim its runtime integration is finished or
authorize Goals 2–4 or 6–7.

Subsequent authorization, 2026-10-02: the user assigned Goals 2–4 to the main
agent, in dependency order. That authorizes their focused implementation and
verification, not Goal 6 live reasoning acceptance or Goal 7 normal-build
activation. Current evidence and remaining work are recorded in the
[implementation status](iterative_episode_refiner_implementation_status.md).

Checkpoint clarification, 2026-10-02: the user subsequently closed the bounded
Goals 2–4 coding assignment as complete. The original wider completion criteria
below remain design history; deferred execution validation and unified recovery
must not be treated as an unfinished mandate to continue that assignment. The
user separately authorized saving a commit, pushing it, opening a draft PR and
creating a dependent harness branch. This does not authorize running tests or
starting harness implementation. See the
[collaboration handoff](iterative_episode_refiner_checkpoint.md).

## Overall goal

Latest user direction: prioritize the executing Episode shape and connect the
existing runtime before detailed verification. Do not run tests at this stage.
Do not add one-off replay mechanisms. Later acceptance/replay must use one
shared, documented CLI/harness; the earlier focused-test sequencing is deferred.
Existing worker/executor facilities are to be reused, not replaced.

> Implement the finalized IterativeEpisodeRefiner as both an Episode-library design
> and OpenChia's normal build-finalization path. It must refine any materialized
> Episode build through measured design, actual code changes and real validation;
> detect conflicting repairs across child loops; preserve scoped authority and
> typed evidence; and return an exact verified build or an honest unresolved
> result. Keep new logic concentrated in the refiner and its library modules, with
> explicit, limited changes to shared infrastructure. Do not call the implementation
> complete until real-path acceptance and ordinary-Episode compatibility are
> demonstrated. Report missing authority or evidence rather than substituting a
> weaker success condition.

Completion means every goal below is satisfied, not merely that the code imports,
unit tests pass or a demonstration works outside the actual runtime.

## Goal 1 — Freeze the executable contracts and integration boundary

> Turn design v3 into exact implementable contracts for every refiner Episode and
> host operation. Specify inputs, repeated units, permitted children, result and
> in-progress report schemas, local measures, admission, yield, continuation,
> conflict returns and recovery. Map each to current repository symbols. Resolve
> structural contradictions before coding. Do not implement or run tests yet.

Done when:

- The approved role graph permits only Parts owners to create Designers or nested
  Parts scopes. The implementer remains inside the Designer's loop.
- Each role has concrete, evidence-backed judgment rules, including the Designer,
  searcher and measurement Episodes. No trusted model-authored quality score or
  “we will decide the metric later” remains.
- Task-specific measures are derived from requirements and frozen before the
  affected coding assignment. Numerical-controller design stays together.
- The A/B cycle has an exact record/eligibility/escalation path during iteration,
  not only a final-result summary. Reassignment preserves history.
- Missing oracle/authority, already-correct work, numerical return and external
  stops have distinct specified outcomes. No semantic turn/time/token budget.
- The file/symbol map identifies required shared changes, staged import/capability
  boundaries, existing state to reuse, and version/migration handling.

Deliver the contracts and mapping for review; executable workflow/authority
approval remains separate from this document's existence.

## Goal 2 — Implement durable candidates, reports and cycle handling

> Implement the refiner's campaign state, candidate revisions, requirement/check
> records, typed reports, scoped learning and conflict handling using existing
> persistence. Preserve evidence across reassignment and restart. Demonstrate the
> state/replay behavior with focused invariant tests, without changing normal
> build activation or claiming full reasoning acceptance.

Done when:

- Edits preserve the baseline, bind an exact new revision and invalidate affected
  evidence. Unknown impact cannot leave stale green status.
- Each attempted change produces the required local and parent-facing records;
  return reports are derived from admitted records, not a generated narrative.
- Exact revisits and opposing regressions are distinguishable from legitimate new
  evidence or changed conditions. A/B conflicts reach their common Parts owner.
- A successor joint assignment inherits both sides' attempts and preservation
  checks. Repeated restoration of an old pass earns no new credit.
- Failure alone yields zero. An evidence-linked, scoped, new operative lesson can
  yield positively under the frozen function. Replays award no duplicate credit.
- Crash injection around writes never exposes uncommitted success or loses the
  causal evidence. Old serialized artifacts remain readable.

These tests establish state and control invariants, not that the system can reason
about or repair an arbitrary real Episode.

## Goal 3 — Connect scoped operations to the real host and worker

> Implement the approved refiner's scoped candidate-edit, measurement and
> validation-Run operations through the existing host/runtime boundary. Reuse
> source admission, Run registration, executor backends, brokers, audit and
> cancellation. Add only the shared mechanisms required by the refiner consumer,
> and verify them across the actual worker transport.

Done when:

- A confined designer cannot directly mutate host state, broader learning, sibling
  assignments or global policy; the host admits each requested operation.
- Validation executes the exact admitted candidate with a separate Run identity
  linked to its campaign/unit; it does not overwrite the user's session Run.
- The current source-import restrictions remain meaningful. Worker functions use
  admitted library paths; host implementation imports are not broadly exposed.
- Declared stage continuations and Parts recursion work through approval,
  materialization and linking, rather than existing only in an in-process driver.
- Cross-part conflicts can return control at unit boundaries with correlated
  evidence and honest status. A worker's unsupported “blocked” claim is not authority.
- Cancellation, rejected operations, crashes and replay preserve consistent
  evidence and do not double-credit or manufacture completion.

Unavailable confinement or transport means this goal remains unverified; report
the exact requirement instead of replacing this proof with a mock.

## Goal 4 — Implement the executing refinement Episodes

> Implement RefineParts, DesignPart, RefineImplementation and their required
> support/verification children as registered library designs using the existing
> Episode machinery. Drive actual scoped code changes through local measurement,
> part acceptance and enclosing acceptance. Keep normal build activation unchanged
> while validating this explicit refiner entry point.

Done when:

- Parts owners choose, split or combine work based on evidence, independently of
  the target workflow's node layout. Only they create design assignments.
- A Designer owns its implementation/evaluation feedback and cannot escape a
  difficult problem by creating another Designer or a Parts wrapper.
- The implementer makes actual candidate changes and uses its own measure; the
  parent's VerifyBehavior remains a separate judgment.
- Already-correct work returns without edits. Partial progress, invalid measures,
  missing evidence and yield exhaustion produce their specified honest outcomes.
- A conflict updates the shared record during iteration and returns to its owner
  for a joint assignment or other justified action.
- Host-derived progress and registered continuation govern every loop. Delegation,
  patches, repeated failures and paraphrases are not inherently rewarded.

Use real imports and real operations in focused integration checks. Scripted
choices can check routing, but cannot satisfy the live reasoning goal below.

## Goal 5 — Add reusable specialty instructions and guidance search

> Equip the reusable Designer with versioned, task-specific instruction sets and
> an optional FindDesignSupport Episode that retrieves suitable library guidance,
> examples and checks. Keep unfamiliar tasks on the general route and preserve
> fixed assignments, scoped context and source provenance.

Done when:

- A parent can supply appropriate guidance for reasoning, calculation or other
  task types without adding a separate runtime class for every specialty.
- Numerical-controller guidance covers credit, rarefaction and continuation as
  one coupled assignment.
- Search returns applicability, source identities, limitations, conflicting
  guidance and missing coverage; retrieved volume is not the progress measure.
- The child receives a focused package before starting. Later evidence does not
  rewrite its system prompt or active judgment contract.
- An irrelevant example can be rejected and absent guidance is reported rather
  than fabricated. Raw content cannot authorize operations or promote policy.
- Reuse appropriate existing search/library components. Add only the example
  material needed to demonstrate this consumer, not a speculative large catalog.

## Goal 6 — Demonstrate real repair, reasoning and cycle resolution

> Run the refiner through its actual admitted, isolated execution path on concrete
> Episode builds with inspectable answers or independently grounded acceptance
> checks. Use real model-driven design and code changes. Demonstrate that the final
> candidate solves the original task and that an A/B repair cycle is resolved by
> coordinated work, not hidden by weakened tests or an artificial stop.

Done when:

- At least two materially different target kinds are exercised, including a
  nested workflow. This is evidence of breadth, not proof of universal solvability.
- A broken initial build is changed into a candidate that genuinely meets its
  original requirements, with final source and expected/observed results inspectable.
- The A/B case uses real executable behavior: separate repairs conflict, the
  record reveals it, the owner creates a joint assignment, and both original
  requirements finally hold on the same exact candidate.
- An already-correct build is preserved. A missing-oracle/capability case returns
  honestly. Interrupted work recovers without stale success or duplicate credit.
- The receipt records exact source, input, checks, model/configuration, numerical
  settings, execution path, results and unresolved limitations. Any substitution
  from shipped configuration is explicit.
- A real task result is checked independently of the model claiming it solved it.
  Hand-written worker/model events, in-process brokers, skipped confinement tests
  and mock-only control tests are not substitutes for this acceptance.

Repair shortcomings within the approved design and repeat relevant validation.
If required evidence or authority is unavailable, preserve work and report the
specific blocker; do not relabel this goal complete.

## Goal 7 — Activate normal build finalization and prepare the merge

> Connect the proven refiner to OpenChia's normal materialization lifecycle, retain
> the same design in the Episode library, and rehome the old named refiner's
> boundary responsibilities without losing safeguards. Demonstrate compatibility
> and prepare a reviewable change based on current main. Do not commit, push or
> publish a PR without separate authorization.

Done when:

- Every initial build from an approved materialization enters the refinement
  path, without a task-type whitelist. Broken initial output is repairable, not
  rejected merely because it cannot yet run.
- Build/source admission, refinement-in-progress, verified readiness and unresolved
  outcomes remain distinct in host state and the compact review surface.
- Production launch cannot mistake an initial admitted build or an interrupted
  refinement for verified completion. Candidate publication preserves approval.
- Old provenance/approval/classification work is owned by Builder/approval boundary
  services; there is only one active refiner and no duplicate shadow implementation.
- Existing Episode execution, persisted artifacts, prompt caching, capability
  restrictions and session Run behavior retain their contracts.
- Shared changes are listed and justified. Mechanical moves are separated from
  behavior changes; dependencies and unnecessary UI/provider edits are absent.
- Focused compatibility tests and the real normal-build path pass on the exact
  proposed revision. Branch/main differences and genuine integration blockers are
  reported; no blanket guarantee of conflict-free merging is claimed.

## Required handoff for each implementation goal

Report what is complete and incomplete, files changed, shared-code changes,
schema/migration effects, verification actually performed, evidence locations,
and the next dependency. Keep invariant-test evidence separate from live task
acceptance. If no validation was authorized or a required check was skipped,
say so and do not claim the corresponding completion condition.
