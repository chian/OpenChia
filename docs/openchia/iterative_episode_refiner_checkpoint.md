# IterativeEpisodeRefiner coding checkpoint and collaboration handoff

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
