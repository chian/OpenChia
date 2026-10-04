# IterativeEpisodeRefiner coding checkpoint and collaboration handoff

## Current checkpoint: one build owns refinement, 2026-10-03

[ADR 0007](../adr/0007-build-owns-iterative-finalization.md) records the user's
explicit instruction: OpenChia must own the full build → refine → validate cycle
after one start. This supersedes the earlier activation deferral.

`OpenChiaHost.start_build` now passes either a failed partial build or a
materialized build directly to the existing refiner via `ExperimentService`.
The host materializes the fixed library refiner, records its authorization under
the original human-approved job (not a fabricated second human approval), and
uses the owning Duet's model route. Target Workflow validation retains its own
launch. Status exposes the campaign and experiment IDs; cancellation reaches
the whole job. A static Builder pass is not a completed build. The code publishes
success only for a host-verified accepted revision.

Latest focused validation: **12 passed across four files in 67.7 seconds**.
The failed-build handoff runs through an actual systemd worker, reaches a
supplied refiner model response, and verifies cancellation and stopped-worker
identity. The materialized-build case runs in-process. A separate plan-resolution
regression was reproduced red and passed after correction (**1 passed in 2.7
seconds**): a revised valid implementation plan can clear its old uncertainty
without rewriting history or accepting forged result-channel identities.
These are not live reasoning or successful-repair receipts. The older ordinary
testing-launch fixture has now been updated and passes: it binds its owning
Duet, enters the real refiner, explicitly cancels that job, and separately tests
an approved `/run` of the admitted source. Cancellation is not successful build
completion. This preserves `/run` compatibility without bypassing refinement or
claiming that source admission establishes acceptance.

A live job from `899ff4a220` now demonstrates automatic failed-build handoff to
the native refiner with the actual owning Duet configuration. The parent repaired
a rejected assignment proposal through its normal next unit and entered its
Designer child. The job was cancelled after two plans hit a misleading host
rejection: both contained all contribution keys plus one preservation-only key.
Feedback now identifies missing and unexpected keys without changing admission.
No candidate repair or final acceptance has been demonstrated. Exact IDs are in
`acceptance/setup_inputs.json` and the receipt log.

The normal-build policy now supplies a frozen grant for registered requirement
grounding functions. `measure_preparation` uses only the original approved task
to make cases available to the existing Measure child. The first source covers
the exact scheduling goal and derives controls with the independent exhaustive
solver. No check is installed or credited merely by making it available. Other
contract fields and unfamiliar tasks remain explicit gaps; this is not a general
prose-to-oracle implementation. A changed problem does not inherit these cases.
The Measure-to-parent return also fixes a missing argument that previously
raised instead of recording the parent's useful new measurement decision.

The parent's declared measure groups now include admitted checks with their exact
criteria, instruments and original-check links. Existing static checks remain;
the verifier cannot omit a newly admitted member. Grouping is not another credit
event or a passing observation. Finalization retains the original measure/control
provenance rather than treating the group label as its own oracle.

**Still unfinished:** establish measures for the remaining original requirements,
then verify automatic repair and final acceptance through one normal start.
Static admission is not a substitute. Final compatibility remains open. Do not
ask for routine iteration approval again. Focused validation is recorded in the
receipt log; it is not a live repair or final-acceptance receipt.

## Earlier checkpoint: systemd 255 and native nested continuation, 2026-10-03

This update saves all current work to existing draft PR #33 and both remote
branches, `feat/iterative-episode-refiner` and `feat/unified-episode-test-harness`.
The active checkout remains `/home/chia/repos/OpenChia`; the secondary worktree
is not changed. No history rewrite or normal-build refiner activation is included.
The PR records the exact published checkpoint commit.

The checkpoint adds systemd 255 compatibility under
[ADR 0006](../adr/0006-support-systemd-255.md), the approved AppArmor setup guide
and policy file, and the shared install/doctor namespace diagnostic. The diagnostic
reports failures without changing host security policy. The operator separately
approved and installed the launcher-specific profile on this host; it permits
user namespaces for services using that launcher, not only OpenChia.

Native service lifecycle, reasoning-worker and single-Episode continuation checks
pass. Native nested `Parts → Designer → Implementer` continuation now also passes
through the common experiment service and existing systemd executor. It verifies
current authority, stopped predecessor, one child return, unchanged old evidence
and no duplicate calls, edits or credit; its result matches uninterrupted execution.
The continuation test exposed and fixed the frozen starting-state lookup in the
shared service. Its old loopback driver is removed.

Exact validation and earlier failures are retained in the
[receipt log](unified_episode_test_harness_receipts.md): latest broad check
**343 passed, 1 failed, 2 skipped**; focused rerun **9 passed, 1 failed**; final
native nested comparison **1 passed in 844.7 seconds**. The focused passes and
final comparison resolve the known failures, not constitute a full green rerun.
Installation/doctor checks separately passed **21 tests**. These use supplied
model decisions and target observations where documented. The nested source
edit is a comment; it is not evidence of autonomous repair.

Tasks 1–3 and task 5's compatibility/documentation checkpoint are complete.
**Task 4 remains:** actual live-model testing and independently checked reasoning
and repair. Its [acceptance draft](acceptance/README.md) still awaits exact human
approval and real build/setup references. A naturally encountered failure and
verified repair are appropriate evidence; no model-authored fail/pass script is
required or permitted. No fixture approval substitutes for the human decision.

[ADR 0005](../adr/0005-target-workflow-execution-backends.md) supports both
container and systemd execution. Container-default changes and project-environment
reproduction remain pending; this checkpoint does not claim they are implemented
or that a container runtime is installed. Refiner model routing still uses the
owning Duet, separate from the Target Workflow's approved launch configuration.

## Earlier saved checkpoint: refiner and unified harness, 2026-10-03

This section describes checkpoint `c000277bac`, not the current update above.
The systemd/AppArmor setup and native checks have since progressed; use
the [current task status](unified_episode_test_harness_design.md#task-status)
and [dated receipts](unified_episode_test_harness_receipts.md) for current results.

The user requested saving **all current work in existing PR #33**, including the
unified harness. This supersedes the original instruction below to keep harness
changes out of that PR. The active checkout is `/home/chia/repos/OpenChia` on
`feat/unified-episode-test-harness`; its checkpoint also advances the existing
PR's `feat/iterative-episode-refiner` branch without rewriting history.

The checkpoint includes the shared Run/test records and discovery interface,
refiner-to-harness routing, testing Episode and CLI, scoped execution, recorded
and numerical replay, continuation implementation and tests, the Duet-versus-
Target Workflow model-routing integration, and all current design/receipt notes.
Merged PR #34 (`637ea47fbd`) is included through merge `684ce78bc9`.

**Target Workflow** is now the canonical term in documentation, code descriptions,
model instructions and CLI text. Existing `target_workflow_ref` identifies it;
`candidate_ref` identifies a candidate revision. This terminology change does not
rewrite stored evidence or change approval schemas. The IterativeEpisodeRefiner
and the Target Workflow have different tasks and contracts; neither is an
unrestricted computer agent.

### Verification and remaining work

This is a preservation checkpoint, not a claim that the harness goal or live
acceptance is complete. Earlier exact test results and their limits remain in
the [receipt log](unified_episode_test_harness_receipts.md). The latest broad
receipt was 444 passed, 4 failed and 2 skipped; subsequent focused checks and
fixture corrections are recorded separately, not presented as a clean full run.
Nested continuation has loopback coverage, not container execution proof.

[ADR 0005](../adr/0005-target-workflow-execution-backends.md), revised after this
checkpoint, supports container and systemd execution with containers as the
Target Workflow Run default. It replaces the earlier container-only decision.
The default change and reproduction of the current project environment are
**not implemented in this checkpoint**. The recorded systemd failures were
unresolved at that checkpoint; no backend acceptance result is implied by this decision.

Live backend acceptance, model-directed testing/repair and final compatibility
remain unproven. The [acceptance preparation](acceptance/README.md) identifies
the missing exact build/approval references; no fixture approval substitutes for
them. Normal-build refinement remains unactivated. Saving does not install a
container runtime, change execution defaults, launch Episodes, or resume work on
those remaining items. Continue against the existing stable task IDs in the
[harness implementation map](unified_episode_test_harness_design.md).

Checkpoint validation is static only: Python syntax, JSON parsing, terminology
searches, whitespace checks and a scan for common credential patterns. No new
behavioral tests were run. Earlier test receipts predate these wording changes.

## Original checkpoint: 2026-10-02 (historical)

2026-10-02. This note accompanies the saved `feat/iterative-episode-refiner`
branch and its draft PR. The user explicitly closed the bounded Goals 2–4 coding
assignment as **complete**, not stalled or blocked. Saving the checkpoint does
not reopen that assignment or claim the complete product has passed acceptance.

## What is being saved

- The editable design, exact contracts, repository mapping and implementation
  history for the Parts → Designer → Implementer refinement loop.
- Candidate revisions, evidence, typed parent reports, shared regression/cycle
  records, host-side admission and credit, and parent-owned reassignment.
- Registered refinement Episodes and the source-level connections for scoped
  edits, task-specific measurements and independent parent acceptance.
- Approved repeatable-call materialization/linking and scoped requests through
  the existing worker/executor boundary; no replacement execution service.
- The specialty-guidance catalog and examples. The copies in the original and
  secondary worktrees matched when this checkpoint was prepared.
- Existing draft test files as source artifacts, not as proof that this checkpoint
  passes them. No new tests are added or run as part of saving the work.

The latest design/contracts/integration notes are those saved with this branch.
Earlier copies in the original checkout are not the implementation baseline.

## Verification and activation boundary

No test suite, import probe, live model acceptance or actual validation Run is
executed for this checkpoint. Static Git/diff inspection is not behavioral proof.
The draft PR is for preservation, coordination and review, not a merge-readiness
claim. Normal build finalization has not been activated.

Interrupted nested-session restoration is a known implementation gap: durable
operation idempotency is not restoration of the suspended Episode stack. Address
that through the forthcoming unified harness/recovery work, not a refiner-only
replay API. Other unverified behavior and historical source-review findings are
retained in [implementation status](iterative_episode_refiner_implementation_status.md).

## Branch and collaboration boundary

- Refiner checkpoint: `feat/iterative-episode-refiner`, based on merged PR #31,
  commit `9980990488089f4c53bfe4c61f3054312ed70db8`.
- Remote main was observed at PR #32, commit
  `ac04e69bf14e533b04a856a504c1173d93089295`, while saving this checkpoint. That
  later launch-routing work is not merged or rebased into this preservation step.
  Coordinate integration before claiming compatibility or merge readiness.
- Dependent follow-up: `feat/unified-episode-test-harness`, created from the
  saved refiner checkpoint. Keep harness changes separate from this PR; before
  the refiner merges, compare them against the refiner branch, not against main.
- The user requested returning active work to `/home/chia/repos/OpenChia` on
  the harness branch. Preserve its earlier local document copies before switching.
  The clean secondary refiner worktree can remain as the saved baseline; other
  collaborators' worktrees are not part of this operation.

The PR and Git history provide exact published commit identities. No branch is
force-pushed or merged as part of this handoff.

## Next task: unified testing harness, not more refiner scope

Subsequent routing clarification (2026-10-03): refiner reasoning uses the
owning Duet's model/provider configuration; tests of the Target Workflow use that
target's launch configuration. There is no separate refiner launch-file
requirement. See the [routing contract](episode_launch_configuration.md#duet-refiner-and-target-model-boundary).

The testing Episode owns the experiment: what it tests, why, expected and
falsifying outcomes, execution scope, reused inputs/results and measurement.
The harness must make those choices transparent, flexible and LLM-accessible
alongside Episode iteration, host credit and numerical control. It must not
replace that reasoning with a fixed testing sequence.

Use one service and documented human/agent CLI for candidate checks, parent
acceptance and tests of the refiner itself, reusing existing runtime and evidence
facilities. Recorded observations, recorded external responses, live execution
from saved state and fresh live execution must be distinguishable. No hidden
live fallback, model-awarded credit, one-off replay mechanism or weakened task
criterion is permitted.

The dependent branch will retain the agreed harness requirements as editable
documentation. Branch preparation and requirements recording do not start its
implementation, live execution or normal-build activation.
