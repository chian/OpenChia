# Scheduling acceptance — one-start build cancelled for a feedback fix; testing Episode pending

Current attempt, 2026-10-03: the ordinary `OpenChiaHost.start_build` entry was
called once from commit `899ff4a220`, with a fully initialized owning Duet using
its configured `gpt-5.6-sol-900k` route and `xhigh` reasoning effort. The Target
Workflow retains its separate approved launch file. The initial Builder attempt
failed source planning; OpenChia automatically entered the shipped refiner in a
native systemd worker. No operator launched that next stage or repaired its code.
The job was then cancelled to correct a host feedback defect: two Designer plans
covered all assigned contribution keys but included a preservation-only key.
Both received the misleading rejection "plan must cover the assigned contribution."
The cancelled job has no verified build. This is not a completed repair or
acceptance receipt; no operator edited its candidate.
Current job and Run identities appear in `current_build_job` in
[setup_inputs.json](setup_inputs.json). The earlier failed attempt below is
retained as historical evidence, not the current job's status.

The human approved the exact scheduling Target Workflow and designated launch
configuration on 2026-10-03. Their hashes and actual approval/store references
are recorded in [setup_inputs.json](setup_inputs.json). The ordinary host recorded
the approvals in a separate workspace and started real Builder calls. The testing
Episode is not yet approved. These files describe setup; the authority store,
Builder receipts and Run records are the authoritative evidence. The first build
ended **blocked**, with no emitted module and no Target Workflow Run.
See the [live-build receipt](../unified_episode_test_harness_receipts.md#approved-live-build-first-attempt-blocked-2026-10-03).

The acceptance workspace is `/home/chia/repos/OpenChia-acceptance-0RN3r9BH`.
It is a private record directory, not another code checkout or a custom runner.
Existing user Duets and the secondary checkout are unchanged. The target blueprint
is now approved and must not be silently edited; a changed design needs new approval.

The **Target Workflow** here is the scheduling workflow, not the testing Episode
or IterativeEpisodeRefiner. Each acceptance Run explicitly selects and records
its existing execution backend, with no silent fallback. Container and systemd
execution share this harness and its task criteria; see
[ADR 0005](../../adr/0005-target-workflow-execution-backends.md). The container
default change remains pending. The systemd setup failures are resolved on this
host, and native worker checks pass. Live-model acceptance is not yet established.

- [schedule_target.blueprint.json](schedule_target.blueprint.json) is one complete
  Architecture blueprint for the existing `reasoning.generic` reference.
- [setup_inputs.json](setup_inputs.json) names the real model slots and known
  measurement contract. Its `null` fields are unresolved setup inputs, not valid
  artifact references. This checklist is not an ExperimentSpec or TestingContract.

## Target design and review choices

The single root `schedule_reasoner` solves the existing seven-job problem with
two workers and one laser. The exact task and constraints appear both in its
goal and its approved evidence. The independent solver's answer is not included.

The repeated unit chooses `solve`, `verify`, or `revise`. It uses the ordinary
reasoning source, host learning admission, result projection and controller.
There are no children, repeatable calls, external HTTP capabilities or testing
capabilities. Lessons remain Episode-local and advisory.

The reference uses `reasoning` for selection and execution. The designated
launch file also offers `fast` and `non_reasoning`; this draft does not select
either. Builder planning and emission use `reasoning`. Confirm those exact
bindings in the materialized specification before execution. Target/tester
launch settings never configure the IterativeEpisodeRefiner, which uses its
owning Duet's configuration.

Numerical control is frozen to the reference's paired-incidence rarefaction
(`uncertainty_alpha: 0.05`) and predicted-credit upper-bound continuation
(`max_predicted_marginal_hypervolume: 0.01`). This is not the older acceptance
run's substituted `0.9` threshold. There is no semantic turn or time budget and
no promised call count; an operational interruption is not normal completion.

Answers have three string-valued fields: `schedule` (JSON-encoded job starts),
`makespan` (integer text), and `optimality_argument`. The registered
`refinement_checks.optimal_resource_schedule_v1` measure checks feasibility,
truthful makespan and optimality by exhaustive enumeration. It accepts different
optimal schedules. Explanation text remains inspectable but is not certified
as a mathematical proof. Target learning credit does not itself establish
correctness.

The proposed measure addresses the **first admitted frontier answer**, using
`/workflow_result/result/admitted_problem_frontier/0/body/fields`. An empty
frontier cannot establish success. This is not an all-frontier check. Changing
the projection or the threshold requires review before approval.

## Local validation only

From the repository's prepared Python environment, this parses the ordinary
blueprint/spec and resolves its reference without opening any stores:

```bash
python -B - <<'PY'
import json
from pathlib import Path
from agent.episode_blueprints import workflow_spec_from_blueprint
from episode_library import episode_library

path = Path("docs/openchia/acceptance/schedule_target.blueprint.json")
workflow = workflow_spec_from_blueprint(json.loads(path.read_text(encoding="utf-8")))
for node in workflow.episodes:
    episode_library.resolve(node.episode_reference.episode_id)
print({"structurally_valid": True, "approval_checked": False,
       "workflow_hash": workflow.workflow_hash.value})
PY
```

This validation does not query approval. It is not Builder admission, correct
reasoning or a live test.
If registered definitions change, resolve and review the draft again; do not
silently substitute new IDs.

## Human setup and approval sequence

1. Select one existing OpenChia home/store set for this acceptance work and record
   its paths in `setup_inputs.json`. Do not silently combine the default home
   with the old worktree-local home. Create a new target Duet rather than
   replacing an unrelated approved workflow, for example with
   `/bg new Prepare the seven-job scheduling acceptance Target Workflow Architecture`.
   Supply the complete blueprint JSON as Architecture input to that Duet;
   naming this file alone is not an import command.
2. Review the exact resulting Architecture with `/bg TARGET_DUET_ID episode`
   (and `episode edit` if needed). The human records the Architecture decision
   with `/bg TARGET_DUET_ID approve`. Do not simulate this step by inserting
   approval records or using test-fixture helpers.
3. Configure that target Duet through the existing commands:

   ```text
   /bg TARGET_DUET_ID launch load /home/chia/repos/OpenChia-iterative-refiner/launch_default.json
   /bg TARGET_DUET_ID launch preview
   /bg TARGET_DUET_ID launch approve HASH_FROM_THIS_PREVIEW
   /bg TARGET_DUET_ID build
   /bg TARGET_DUET_ID build status
   ```

   Launch approval is separate from Architecture approval. The file contains
   routing and credential references; keep credential values out of these
   documents and all child inputs. Continue only after an admitted build exists.
4. Record the actual target Duet, candidate/build receipt and environment
   references. Register its already-approved launch with
   `openchia test register-launch --file /home/chia/repos/OpenChia-iterative-refiner/launch_default.json --duet-store DUET_STORE --duet-id TARGET_DUET_ID`.
   This command does not grant approval. Prepare the criterion from
   `openchia test describe` and the predicate/projection in `setup_inputs.json`.
   Persist its grounding through the existing shared artifact API. Include
   independently derived positive controls and negative controls covering both
   an infeasible schedule claiming the optimum and a feasible nonoptimal one.
   Then use `openchia test register-measure --file CRITERION_JSON --duet-store DUET_STORE --duet-id TARGET_DUET_ID --build-store BUILD_STORE`
   and retain its exact `requirement_ref` and `measure_ref`.
5. Only now prepare the separate Testing Duet's Architecture using
   `reasoning.testing`, with `episode_testing` capability and a frozen
   TestingContract naming the exact target, build, environment, launch and
   requirement/measure references. Let its model choose experiments and
   follow-ups from observed evidence; do not script its answers or choices.
   Freeze its own numerical controller during this later design review.
   Review and approve that Architecture, configure/approve its launch separately
   using the same designated file, and build it. Approving a tester as a
   replacement in the target Duet would stale the target's authority head.
6. After reviewing the tester's admitted materialization, explicitly run it with
   `/bg TESTER_DUET_ID run`. This uses the existing shared service and native Run
   boundary. Inspect results with the shared `openchia test history`, `results`
   and `run-record` commands against the same stores. Do not replace an
   unavailable confined Run with an in-process fixture.

The unresolved tester/access fields are intentional. This target draft alone
does not establish known-broken/correct candidate execution, nested scope
testing, recorded or numerical replay, interruption continuation, or refiner
repair. Those require their own exact inputs and evidence within the existing
harness. Positive/negative predicate controls validate the measuring mechanism;
they do not substitute for actual candidate Runs.

Run the actual task and let observed failures drive refinement. A naturally
failing candidate followed by an independently verified repair satisfies the
fail/pass demonstration; do not script the model's choices or prescribe a
failure-then-success sequence. A first-pass success establishes correctness for
that case, not repair behavior. The iterator may also return unresolved when
useful yield runs out; iteration is not a guarantee of eventual success.

## Acceptance evidence checked on 2026-10-03

These are the goal's acceptance requirements, not additional implementation
tasks. The [receipt log](../unified_episode_test_harness_receipts.md) records the
executed checks and their failures; test names alone are not passing evidence.

| Required demonstration | Existing evidence and its limit |
| --- | --- |
| A testing Episode chooses an experiment and a follow-up from evidence | `test_testing_episode.py` executes the real generated loop and host learning, but choices are scripted. Live model-directed experimental design is **not demonstrated**. |
| A broken candidate fails and a correct candidate passes on an examinable task | `test_scheduling_measure.py` accepts distinct optimal schedules and rejects infeasible, nonoptimal, malformed and falsely reported answers. Its executor supplies those answers; it does **not execute broken/correct candidate implementations**. That acceptance case remains open. |
| Scoped and broader nested execution establish distinct claims | `test_scoped_execution.py` executes generated nested sources, then selected invocations, rejects omitted children and forbids promotion of narrow recordings to whole-workflow evidence. `test_unit_execution.py` covers declared-unit scope. Execution is in-process with supplied model responses, not native confinement. |
| Numerical, recorded-response and live execution remain distinct; incompatible recordings fail | `test_numerical_execution.py` recomputes actual ledger history without calls or new credit. `test_recorded_execution.py` exercises brokers, frames and stores, including matched reuse and explicit divergence, but its executor emits supplied exchanges. Stock reasoning's Run-specific prompts also correctly diverge on a new Run; they are not silently normalized for replay. |
| Cross-child regression is visible to the responsible parent | `records/test_refinement_regression.py` drives admitted source revisions and contrasting supplied results through the shared service. Indexed parent history exposes the opposing outcomes without reconstructing the audit. It proves history visibility, not that the edited code caused those supplied outcomes. |
| Interruption, continuation and repeats preserve evidence and credit | `test_nested_continuation.py` passes through the shared experiment service and real systemd workers: uninterrupted and resumed nested loops have equal results, controller history and operation counts, without duplicate child returns, calls, edits or credit. Current authority and stopped predecessor checks are real. Model choices and target observations are supplied; the comment-only edit does not demonstrate repair. CLI continuation and native single-Episode continuation also pass. |
| The measure distinguishes known-correct and known-incorrect results | `test_scheduling_measure.py` verifies the registered exhaustive-solver predicate, multiple optimal witnesses, negative controls and rejection of mislabeled controls or a caller-invented optimum. This establishes the fixed benchmark's measuring mechanism, not an LLM's reasoning ability. |

The native setup blocker is resolved on this systemd 255 host. The unsupported
private-PID requirement was removed under ADR 0006; the other isolation checks
remain. The operator-approved AppArmor exception permits namespace setup without
global disablement. Real worker execution, single-Episode and nested-refiner
continuation pass with supplied model replies. No alternate executor was
substituted; the container backend still has no installed runtime. See the [setup guide](../systemd_setup.md)
and [dated receipts](../unified_episode_test_harness_receipts.md).

The store, target approval, launch, environment and failed-build references in
`setup_inputs.json` are now real. The blocked BuildReceipt is not a runnable
candidate. The independent solver grounding is persisted, but criterion
registration requires an admitted build and has not occurred. Remaining nulls
are unresolved, not invented receipts.
A supported systemd environment is available. The testing Episode still needs
the separate exact Architecture and launch approval described above.
