# ADR 0007: OpenChia owns the full build → refine → validate cycle after one start

Status: Accepted

Date: 2026-10-03

Implementation: in progress. The normal build now hands the initial receipt to
the existing refiner through the shared harness. Failed-build handoff and
cancellation pass in a real systemd worker with supplied model responses;
materialized-build handoff also passes in-process. Live autonomous repair and
independent acceptance through this entry point are not yet demonstrated.

## Context

The scheduling acceptance attempt stopped after initial materialization failed.
The operator then considered manually repairing the output and launching another
build. That is not OpenChia's intended workflow and does not exercise its refiner.
At that point, an explicit experimental refiner entry point existed, but the
normal build entry point did not hand its results to it.

## Decision

**OpenChia must own the full build → refine → validate cycle after one start.**

After the initial approval and launch setup, one `/build` command starts the
whole job. OpenChia—not the user or a coding assistant—starts the Builder,
starts the IterativeEpisodeRefiner, runs validation, and returns validation
failures to the refiner. It must not stop between these stages to wait for
another command or routine approval. The required sequence is:

1. Run the initial Builder attempt.
2. Pass its result directly to the IterativeEpisodeRefiner, including partial
   code, incomplete plans and failures. Do not end the job at this handoff.
3. Let the refiner select and implement the needed repairs.
4. Run validation through the existing unified harness.
5. Feed failed validation back into refinement automatically. Repeat repair and
   validation under the Episode's numerical continuation rule, without another
   user command, routine approval or coding-assistant intervention.
6. Return the independently accepted build, or an explicit unresolved,
   interrupted or cancelled result. Never call an unfinished build complete.

> **Update 2026-10-08 (#66).** Step 1 no longer runs a separate Builder
> generation pass. `/build` starts the IterativeEpisodeRefiner directly from the
> approved Architecture: its Designer commissions MaterializationImplementer,
> Code Implementer, Measure and Verify to construct and validate the candidate.
> EpisodeBuilder supplies the shared validators and source admission, not a
> compulsory initial construction strategy
> ([refiner Episodes](../openchia/iterative_episode_refiner_episodes.md),
> `iterative_episode_refiner/construction.py`). The ownership decision above —
> one `/build` owns construction, repair and validation without further
> commands — is unchanged. See the design deck review (chian/OpenChia#68, D5).

A failed Builder attempt or failed validation supplies evidence for the next
refinement decision. Failure alone must not end the job or require the user or
coding assistant to launch the refiner, issue another build command, repair the
code, or start validation. OpenChia owns those actions within the approved job.

A candidate needing no repair proceeds directly to validation; it must not be
changed merely to demonstrate iteration.

The initial attempt's source, partial plan, diagnostics, requirements and evidence
become the refiner's input whether materialization passes or fails. Static
admission alone does not establish behavioral acceptance. The refiner owns its
Parts → Designer → Implementer iterations, child selection, scoped revisions and
validation through the unified harness. Neither the user nor the coding assistant
manually launches each repair or test.

### Approval covers iteration

Approval authorizes the job and its bounded refinement policy, not just one
attempt. Routine repairs and small task-preserving improvements proceed within
that authority without another approval prompt. The host records each revision
and its relationship to the original goal. An active Run retains its exact frozen
contract; revisions take effect in subsequent attempts, never by rewriting an
active or historical contract.

Changing the original goal, weakening acceptance criteria or expanding execution
authority is not a small improvement. Such changes remain outside the refinement
grant. Do not manufacture human-approval events for host-authorized iterations.

The job also authorizes establishing checks for the original requirements. Its
local and acceptance measures declare this accumulation rule before refinement
starts. A newly admitted check is added with its original criterion, controls,
limits and evidence; it cannot replace or remove an earlier mandatory check.
Each validation request fixes the exact checks it will run. Earlier results are
not rewritten, and a pass from before a new check existed does not satisfy it.

### One lifecycle and one execution system

The normal build entry point must not report a terminal state between the Builder
and refiner. Status distinguishes materializing, refining and validating, while
retaining the exact initial receipt and later candidate/Run identities.
Cancellation stops the whole job, including in-flight validation Runs. Existing
shared records and continuation mechanisms remain the recovery interface.

Use the existing refiner Episodes, host admission, numerical controller, Run
executor and unified testing harness. Do not add a hand-written retry loop, a
second runner, fabricated model responses, or a fixed attempt budget.

The refiner uses its owning Duet's model configuration. Target Workflow validation
uses that workflow's approved launch configuration. These routes remain separate.

### Completion means acceptance

The job reports success only when the host has verified the selected candidate
against the original requirements. Child completion and a materialized source
package are not substitutes. Yield exhaustion with unresolved requirements,
unavailable required evidence, cancellation, interruption and invalid execution
remain distinct terminal outcomes. Iteration does not guarantee success.

## Verification required

Exercise the normal build entry point once. Show that its initial failed build
enters the real refiner automatically, that refiner-owned revisions and validation
occur without another start/approval call, and that the returned build matches
the independently accepted revision. Also cover a build requiring no repair,
whole-job cancellation and an unresolved return. Supplied model responses may
verify orchestration but do not establish live reasoning or successful repair.

## Superseded restriction

This decision replaces the earlier implementation-stage restriction that normal
builds must not activate refinement. The unified-harness design and earlier
receipts used that restriction to describe an intermediate checkpoint. Their
historical test results remain valid at the scopes actually exercised; they do
not establish this newly required automatic handoff.
