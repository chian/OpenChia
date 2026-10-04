# IterativeEpisodeRefiner: shared design principles

Status: living design notes, not an approved executable contract or an
implementation receipt. Started 2026-10-02.

This records the direction agreed in the design conversation. Concrete Episode
roles, nesting, numerical policies, and unresolved choices live in the companion
[finalized design](iterative_episode_refiner_episodes.md). Both documents
are intended to be edited as the human and assistant develop the design.

## Terminology

- **Target Workflow**: the scoped, nested Episode workflow being designed,
  built, refined, tested or executed. Its approved contract defines its task;
  it is not a general-purpose agent free to explore the computer.
- **IterativeEpisodeRefiner** (refiner): the separate workflow that investigates,
  repairs and verifies the Target Workflow's implementation.
- **Candidate revision**: an exact implementation state of the Target Workflow,
  including its materialization and source. Different revisions do not rename
  the Target Workflow or silently change its approved semantics.
- **Episode**: one node within a workflow. **Run**: an execution of an exact
  admitted build, not a synonym for the Target Workflow or a revision.

Use `target_workflow` and the existing `target_workflow_ref` for workflow identity
in code. Keep `candidate_ref` for revision identity. References to a target part,
checker or artifact path retain their narrower meanings. The same terms apply
in model instructions, schemas, CLI descriptions, documentation and future work.

## Purpose

The IterativeEpisodeRefiner is an active **designer Episode of reasoning
Episodes**. It takes an initial materialized build, including an incomplete or
broken build, and performs the investigation, repair, execution, and verification
needed to deliver a build that satisfies its declared requirements.

Every materialization admitted by OpenChia must be a valid refinement input,
including novel nested designs, not just a catalog of supported examples. The
refining process and its interfaces are reusable; each assignment has a concrete
goal, permitted changes, and specific evidence needed to establish success.
Generic applicability does not promise that every problem is solvable or every
requirement mechanically provable: missing evidence or authority must be returned
honestly, not hidden by declaring a difficult build unsupported or ready.

It is both an Episode-library reference design and the intended actively used
OpenChia refinement path. A library example that is not connected to the actual
build lifecycle does not fulfill this goal.

## Agreed direction

Model-routing boundary (clarified 2026-10-03): the refiner and its reasoning
children use the owning Duet's model/provider configuration. The Target Workflow
uses its own selected launch configuration when tested through the harness.
Requesting a Target Workflow Run must not change the refiner's configuration. See the
[canonical routing contract](episode_launch_configuration.md#duet-refiner-and-target-model-boundary);
shared model settings do not imply shared prompts or authority.

1. **The existing named refiner is not this active refiner.** Its useful baseline,
   provenance, change-classification, and boundary checks belong at the
   Builder/approval boundaries. They do not substitute for a repair-and-validation
   loop. Approval remains a Duet/host responsibility.

2. **The refinement tree need not mirror the Target Workflow tree.** One problem may span
   several Episodes in the Target Workflow; one Episode in the Target Workflow may need several investigations.
   Nesting follows concrete repair goals and dependencies.

3. **Use defined, callable child Episodes with fixed interfaces.** The parent
   selects appropriate work and children adapt their reasoning within their
   contracts. Dynamic assignments do not authorize arbitrary new Episode types,
   capabilities, scoring rules, or task architectures.

4. **One shared editable materialization workspace.** The parent and children
   work against a common specification and the corresponding code. “Global” here
   means shared throughout this refinement effort, not unrestricted system-wide
   memory. Stable target identities connect specifications, source, and findings.

5. **Mutable working state, immutable execution evidence.** Edits create candidate
   revisions. Validation runs against exact admitted snapshots; an edit cannot
   retroactively change what a prior Run tested. Specification and implementation
   must remain linked rather than becoming independently drifting documents.

6. **Keep the review surface MINI.** A compact checklist records what must work,
   what failed, repair status, and the latest verification evidence. Detailed
   diffs and audit are available when needed, not forced into the normal view.
   This is not a new issue-tracker product.

7. **Verify first; repair only when needed.** If the assigned requirement already
   passes with applicable evidence, that child returns promptly. It must not
   invent work to justify its existence. A patch is a candidate, not proof of a
   fix. Valid repaired outputs enter ordinary admission and credit judgment.

8. **The parent can cause real execution.** Refinement needs host-mediated build
   checks and validation Runs, not merely advice to a human to run something.
   Reuse the existing executor, isolation, identity, and audit machinery. A broken
   target is repairable as data even when it is not yet admissible for execution.

9. **Local success is not composition success.** Parents recheck their own goals
   after children return. Final readiness requires evidence about the composed
   workflow's intended behavior, not only individually passing modules.

10. **Tests must establish the claim being made.** Syntax, schemas, and mock-based
    control tests have legitimate but limited meanings. Task correctness needs
    inspectable answers or independently grounded acceptance criteria. Transport
    and execution claims require the real transport and execution path. Missing
    evidence must remain visible.

11. **Host-governed yield remains the controller.** Failure, narration, delegation,
    and patch volume do not themselves earn credit. Credit values admitted durable
    changes relevant to the goal. Deduplication, evidence lineage, scoped lessons,
    and reopening remain necessary. The model cannot award itself success or
    score its own prose authoritatively.

12. **Return and readiness are different facts.** Registered numerical continuation
    governs further work. Yield exhaustion with unresolved requirements does not
    make a build ready. Resource interruption, cancellation, missing authority,
    and missing capabilities also cannot masquerade as a successful build.

13. **Protect the requirement while repairing its implementation.** The shared
    working specification is editable, but a child cannot make a failed check
    pass by silently weakening the intended behavior or its acceptance criteria.
    Changes outside the designer's approved edit authority return to the Duet.

14. **Nest by outcome ownership and actual decisions.** Parts-making and selection
    sit above the Designer. The Designer owns realizing its approach, including
    the implementer and the feedback from acceptance. It does not hand a paper
    design back to the parts selector as though the part had been solved.

15. **A prerequisite is not an optional sibling choice.** Establishing an admissible
    design/measure precedes implementation; assessing the result follows it.
    Choices occur among eligible parts, design alternatives, unresolved decisions
    and implementation approaches. A serial stage need not be a new Episode, but
    its required continuation must be explicit. Design can itself contain nested
    decision problems; it is not necessarily one prompt before coding.

16. **An Episode is also an information boundary.** Its own loop needs relevant
    detailed attempt history, evidence, current alternatives and lessons. Its
    parent needs a different, decision-specific report. Shared workspace access
    does not mean shared prompts or all-to-all transcripts. Define what the child
    must retain and what the parent must learn before accepting a nesting.

17. **Reports are evidence-linked projections, not authoritative LLM summaries.**
    The host admits structured observations and derives the operative return
    report. Model explanations remain proposals or reading aids. Reports retain
    revision, scope, counterevidence, uncertainty and the original evidence
    lineage; repeating a parent's hypothesis does not independently confirm it.

18. **Compact reports must preserve future steering.** Return the applicable
    failed-route distinctions, unresolved decisions and dependency changes needed
    to avoid circular retries. Keep full evidence available through scoped typed
    retrieval. Renaming a problem or assigning a new child does not erase its
    history; materially changed conditions may legitimately reopen it.

19. **Specialize assignments before multiplying implementations.** Use the same
    Designer with selected task-specific instructions and examples. A support
    search Episode can find relevant library material and expose its limits.
    Keep a general route for unfamiliar tasks. Numerical-controller design stays
    together across credit, rarefaction and continuation.

20. **Only Parts owners create design work.** A specialist Designer does not call
    another Designer or create a Parts wrapper to do so indirectly. It keeps its
    implementation and support children, but sends new design problems to its
    owner. That owner can split, merge or replace assignments, or delegate a
    coordinated sub-scope to another Parts owner with shared campaign history.

21. **Expose regressions during iteration.** Record candidate/check changes and
    stale evidence at unit boundaries. Do not wait for a final child summary to
    reveal an A/B repair cycle. The common owner can issue a joint assignment;
    returning to an old passing state is not repeatedly new progress. A suspected
    cycle requires diagnosis, not an automatic claim that further work is useless.

22. **Keep implementation concentrated and integration explicit.** Most new work
    belongs in the refiner and its library modules. Shared runtime/host changes
    must be narrow, justified and separately reviewed. Reuse existing persistence,
    registries and execution. Validate before normal-build activation; do not
    promise zero regression risk or leave the final product permanently opt-in.

## Architecture boundaries to preserve

- An approved designer contract must state the callable roles, allowed nesting,
  edit scopes, execution capabilities, admission policies, and numerical rules.
  Version 3 fixes creation of design assignments at the Parts owners. Its exact
  executable representation still requires approval/materialization work; it is
  not permission to bypass current checks.
- Ordinary task Episodes do not acquire unrestricted spawning, code editing, or
  host execution authority as a side effect of adding the designer.
- Each child assignment has an immutable goal and typed handoff. Shared state
  changes are explicit admitted transitions, not silent goal mutation.
- Candidate source, Run logs, child prose, and retrieved lessons are reference
  data, never privileged instructions. Supply current state through typed input,
  preserving the conversation's cached prompt prefix.
- A new revision can invalidate a prior pass. Retain the old evidence for audit
  and reopen affected requirements; do not keep stale green status.
- No turn, token, or wall-clock allowance is the semantic completion condition.
  Operational safeguards remain distinguishable from completion.

## Existing foundations and gaps

These are inspection findings, not claims that the new refiner has been built.

| Area | Foundation | Remaining design work |
| --- | --- | --- |
| Reasoning | `episode_library/reasoning.py` supplies the generic reasoning reference, currently a leaf | Define the designer's branch roles and target-specific verification/admission |
| Nesting | `method_loop.EpisodeTree` declares permitted child types and explicit recursive edges | Carry Parts-owned recursion and the permitted designer children through approval, materialization, and linking |
| Linking | `episode_runtime.linker` binds exact declared child slots from a materialized plan | Do not assume the method loop's recursion support is already exposed end to end |
| Materialization | `episode_builder.inspection.MaterializedSpecification` projects an exact build attempt | An editable working specification must update underlying candidate artifacts, not only the projection |
| Existing refiner | `iterative_episode_refiner.service` binds baselines and produces proposals | Reclassify that boundary machinery; add the actual active Episode loop |
| Runtime | Merged main has `RunExecutor`, systemd/container backends, and brokered HTTP | Add an authorized designer-to-validation-Run operation with its own Run lineage |
| Host launch | `OpenChiaHost.start_run` launches the current admitted build with one active session Run | Do not recursively call that user-facing operation or overwrite its session state |

The runtime findings refer to merged main at
[`a335059aee74`](https://github.com/chian/OpenChia/tree/a335059aee74c230429a4093f32330a94789cb22),
including Wilke's [PR #11](https://github.com/chian/OpenChia/pull/11).
They are static inspection findings; no new runtime tests were run for this design.

The current behavior remains documented in
[Duet-owned Episode design](duet_owned_episode_design.md). The active designer
described here is a proposed change to that lifecycle, not a claim that its
additional authority already exists.

## Design completeness and the next boundary

For every Episode: its goal, immutable inputs, repeated unit, eligible decisions,
required continuations, editable state, result, admission evidence, credit-bearing
transitions, and return behavior. Define its local working information, the
parent's steering report and the permitted evidence drill-down. Names and a
permitted-child diagram alone are not a complete Episode design.

The finalized v3 design now makes those high-level responsibilities explicit; its
[structural self-review](iterative_episode_refiner_review.md) walks successful,
failing, already-correct, blocked, regression and information-loss cases. These
are design walkthroughs, not executed tests. The next boundary is explicit
authorization of the [implementation goals](iterative_episode_refiner_implementation_goals.md),
beginning with exact executable contracts and numerical policies. Finalizing
these documents does not implement code or authorize another test run.
