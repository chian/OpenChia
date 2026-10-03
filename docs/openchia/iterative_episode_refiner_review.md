# IterativeEpisodeRefiner: design v3 review

Reviewed 2026-10-02 against the conversation, the
[permanent requirements](iterative_episode_refiner_goal.json),
[finalized design](iterative_episode_refiner_episodes.md), and
[implementation goals](iterative_episode_refiner_implementation_goals.md).

This is a structural self-review and static repository inspection, not an
independent review, executable workflow approval, test result, or proof that the
implemented refiner solves tasks. No product tests or live model runs were performed.

## What changed since v2

The prior review covered v2, not the later decisions. Its conclusion did not
establish safety against the user's A/B repair-cycle example. Version 3 supersedes
it in these ways:

- The Designer no longer creates Designers or Parts wrappers. Only Parts owners
  create new design work and coordinate recursive sub-scopes.
- One reusable Designer receives task-specific instructions/examples. An optional
  support-search Episode supplies relevant library material with provenance and
  applicability limits. Numerical-controller design remains one coupled assignment.
- Shared regression history updates during child iteration. A conflict can return
  control to the owner at a unit boundary, before successful child completion.
- The design identifies where code can stay concentrated, where integration is
  unavoidable, and how activation and merge review are separated.
- Seven copyable implementation goals now specify concrete completion evidence.

The Designer still owns implementation and part acceptance. Returning a newly
discovered design problem is an unresolved/escalation result, not permission to
declare that its original part is finished.

## Requirement-by-requirement review

“Covered” means addressed in the high-level design, not implemented or tested.
Section references below refer to design v3.

| Requirement | Evidence in the final design | Assessment |
| --- | --- | --- |
| R01 Permanent objective and review | Goal JSON retains the original objective, requirements and iteration history; this review records the v3 changes | Covered |
| R02 Complete build-finalization lifecycle | §1 initial Builder output -> active refiner -> exact verified build or explicit unresolved result | Covered |
| R03 All materialized builds | §1 includes broken, unfamiliar and nested targets; repair is not gated on executable source admission | Covered, not universal solvability |
| R04 Outcome ownership independent of target tree | §2 behavioral parts, Designer ownership and Parts-owned recursion | Covered |
| R05 Nested design workflow | §§2–4 measured design/support/implementation children and coordinated Parts sub-scopes; no autonomous Designer recursion | Covered under the user's later restriction |
| R06 Actual coding and its own metric | §§2, 4–5 RefineImplementation edits source and performs local measurement | Covered |
| R07 Independent parent acceptance | §§4–5 VerifyBehavior is parent acceptance, distinct from the coding metric | Covered |
| R08 Faithful task-specific assignments | §5 requirement -> evidence -> design -> measure -> implementation -> parent judgment, with explicit oracle limits | Covered structurally; exact policies are Goal 1 |
| R09 Every role's inputs/unit/result/authority/progress | §4 common contract and role/call tables; §6 return reports; §8 continuation | Covered at this design level |
| R10 Host-owned numerical control | §§4, 8–9 admission before authoritative credit, and no summing child scores | Covered |
| R11 Success versus return, already-correct and external stops | §8 declared initial assessment and distinct incomplete/blocked/interrupted outcomes | Covered |
| R12 Shared workspace and versioned evidence | §§6–8 exact candidate/check references, invalidation and compact review | Covered |
| R13 Real host-mediated Runs | §9 separate validation lineage using the existing executor, without recursive session start_run | Covered as required integration |
| R14 Zero-yield failure, useful learning and replay | §§7–9 old-state deduplication, evidence-linked lessons, representation repair and stable operation identity | Covered |
| R15 Authority and frozen contracts | §§3–5, 9 restricted creation, exact assignments, approved refiner graph and semantic changes through Duet | Covered as proposed executable authority |
| R16 Feedback, recursion, scope escalation and return | §§2, 7 Parts ownership, nearest covering owner, explicit successor assignment and shared history | Covered |
| R17 Successful and adverse path review | Walkthroughs below and future Goal 6 | Conceptually reviewed; not executed |
| R18 Current symbols and missing integration | §10 pinned repository inspection and exact component map | Covered |
| R19 Reconcile requirements and present the plan | This review and the finalized v3 document | Covered by this handoff |
| R20 High level first; no tests or production changes now | §12 and the implementation-goal authorization preamble | Preserved |
| R21 Implementer inside the actual Designer | §§2, 4 Designer owns approach through implementation and part acceptance | Covered |
| R22 Parts-making and selection above Designer | §2 root/nested Parts owners select and coordinate problems | Covered |
| R23 Choices versus prerequisites and returns | §§2, 4 required stages; design recursion restricted by the later R27 decision | Covered |
| R24 Information boundaries and anti-repeat history | §§6–7 local state, admitted reports, original evidence identity, dependency deltas and in-loop effects | Covered |
| R25 Reusable specialization and support search | §3 and FindDesignSupport's §4 contract; general route remains available | Covered |
| R26 Numerical controller stays together | §§2–3 credit/rarefaction/continuation form one design assignment | Covered |
| R27 Only Parts owners create design work | §§2, 4 no direct or helper-mediated Designer creation by specialists | Covered |
| R28 Repair-cycle recognition and coordinated response | §7 in-loop effects, exact revisits, suspected opposing regressions and joint assignments | Covered structurally; actual resolution is Goal 6 |
| R29 Relatively separate, mergeable implementation | §§10–11 package boundaries, import restrictions, shared interfaces and activation/compatibility gates | Covered without a zero-risk guarantee |
| R30 Final text and concrete driving goals | Finalized design plus seven ordered goal statements and their completion conditions | Covered |

## Path and information checks

| Situation | Required path/evidence | What must not happen |
| --- | --- | --- |
| The initial build works | Initial assessment establishes the unchanged candidate; registered continuation returns it | Invented repairs or false evidence of code improvement |
| The source cannot compile | The independent refiner reads and edits it as data; admission precedes execution | Requiring the broken target to run its own refiner |
| A repair succeeds locally | Code/local evidence -> Designer's part acceptance -> Parts owner's enclosing assessment | Equating a patch or local pass with whole-workflow correctness |
| A Designer discovers another design problem | Report scope/dependency evidence to its Parts owner, which decides the assignment | Creating a Designer or a Parts wrapper to avoid oversight |
| A proper sub-scope needs several designs | The Parts owner delegates to nested Parts with inherited constraints and shared history | A fresh private history or automatic target-tree mirroring |
| Repairs alternate between A and B | Each change exposes check results and invalidations; the common owner considers a joint A+B assignment | Waiting only for final child summaries or repeatedly crediting restored old states |
| Repeated statuses accompany materially different work | Preserve real measurements and conditions; treat the pattern as a diagnostic warning | Banning all further work because a coarse status pattern repeated |
| A new joint assignment starts | Close/replace prior assignments explicitly; inherit attempts and preservation checks | Erasing history, silently changing a child's goal, or manufacturing fresh credit |
| A parent hypothesis is repeated by children | Original evidence/claim identities remain unchanged | Treating more reports as independent confirmation |
| Guidance is missing or irrelevant | Search reports limits; parent uses the general route or names a missing requirement | Invented examples, forced specialty classification or hidden policy changes |
| An example's checks do not fit the task | Parent rejects/adapts the proposed instrument under its adequacy policy | Copying the example's success criterion without checking the actual requirement |
| The measure itself needs code | A grounded instrument assignment uses the permitted coding path; a new design scope goes to Parts | Instrument self-certification or starting an unmeasurable coding loop |
| No adequate oracle exists | Explicit measurement/evidence/authority gap | Model agreement presented as objective proof |
| Source, checks or dependencies change | Re-evaluate applicability and invalidate stale passes before reuse | Combining evidence from incompatible candidate versions |
| Parent assessment is interrupted | Preserve the pending stage and receipts; resume without duplicate credit | Child completion implying final build readiness |
| Continued work has no predicted yield | Return unresolved requirements with the selected candidate | Treating numerical exhaustion as “all errors fixed” |
| Resource limits or cancellation occur | Preserve work with the distinct external terminal state | Budget-based semantic completion |
| A semantic target change is needed | Successor proposal through the Duet | A specialist weakening the task to pass its own checks |

A compact report must preserve the parent decision and its evidence. The
implementer's edit history stays local unless needed; the Designer returns part
acceptance and coordination needs; nested Parts return composition and cross-scope
effects. Bounded views do not omit requirements from the authoritative readiness
check. In-progress reports and final reports reference the same durable facts.

## Static code-boundary findings

Inspected checkout: 52c9c2675995232416012bf19dd644170b7913ab.
Inspected fetched-main object: a335059aee74c230429a4093f32330a94789cb22.
No new fetch, branch switch, commit or product execution was needed for this review.

- iterative_episode_refiner/service.py explicitly describes host machinery, not
  an Agent or Episode. Its RefinementAuthorityReader is an existing narrow
  authority interface. Preserve that boundary while reclassifying its role.
- iterative_episode_refiner/workspace.py projects facts owned by DuetStore and
  EpisodeBuilder. It must not be mistaken for an existing writable candidate engine.
- EpisodeBuilder.build is an existing materialization entry point. The host
  persists its receipt/baseline and emits build_finished; active finalization
  needs an explicit integration there, not edits throughout the general turn loop.
- EpisodeLibrary.register/compatible_children/validate_attachment already provide
  exact library registration and child-interface checks. Reuse them.
- Generated-source admission's allowed roots exclude the host refiner package.
  Keep worker functions in admitted libraries; a broad new host import allowance
  would contradict the intended authority boundary.
- EpisodeTree has explicit recursive edges; the inspected linker creates a
  concrete tree. Parts recursion and multi-stage returns require real integration,
  not merely a new library entry.
- The fetched main RunExecutor protocol and backends already own launch,
  confinement, source identity and audit. The existing host start_run is a
  single-session action, not a nested validation API.

Conclusion: the bulk of new state/policy/coordination code can be concentrated
in the refiner with worker-facing functions/library definitions at existing
boundaries. Approval/materialization, protocol, persistence and host integration
still need shared changes. Those are substantive interfaces, even when their
responsibilities are narrow. Regression risk and merge conflicts cannot be
excluded without later verification against the implementation's actual base.

## Remaining work, not hidden completion claims

The high-level design is finalized. Exact executable contracts and numerical
policies are Goal 1; implementation and mechanism validation are Goals 2–5;
real task acceptance is Goal 6; normal-build activation and compatibility are
Goal 7. Their stated completion conditions remain unmet until executed.

This review does not approve an executable workflow, claim independent review,
or prove generic correctness. It provides a coherent implementation baseline and
identifies the evidence needed before the system can be called working.
