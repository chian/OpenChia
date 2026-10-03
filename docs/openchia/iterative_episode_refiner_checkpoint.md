# IterativeEpisodeRefiner coding checkpoint and collaboration handoff

## Current checkpoint: refiner and unified harness, 2026-10-03

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

[ADR 0005](../adr/0005-target-workflow-runs-use-containers.md) records containers
as the Target Workflow Run default on Linux/macOS and explicit container-only
acceptance. The default change, removal of systemd selection from acceptance
tests, and reproduction of the current project environment are **not implemented
in this checkpoint**. The previous systemd failures are historical results of
the wrong acceptance backend, not prerequisites for the container path.

Live container acceptance, model-directed testing/repair and final compatibility
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
