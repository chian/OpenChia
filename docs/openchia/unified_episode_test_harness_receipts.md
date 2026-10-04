# Episode testing harness: verification receipts

Return to the [current guide](unified_episode_test_harness_design.md).
These chronological receipts preserve what each run did and did not establish.
They do not replace the goal's end-to-end acceptance requirements.

**2026-10-03 checkpoint clarification:** "Target Workflow" now names the scoped
workflow being built and tested, distinct from the refiner and from a candidate
revision. The revised [ADR 0005](../adr/0005-target-workflow-execution-backends.md)
supports container and systemd execution, replacing the earlier container-only
decision. At that checkpoint, the systemd failures remained unresolved; the
decision itself did not establish successful execution through either backend.
No new behavioral tests or live Runs were performed for this terminology/save
checkpoint, and these earlier receipts do not verify the newly named head.

### Live one-start retry after host feedback correction, 2026-10-03

Clean source `7222da1a21` started the ordinary build entry once:
`build_request_2f512662e164f8a9f46cad98a884254b94180cefd01c0450fe767be405855f32`.
The actual owning Duet route is unchanged, separate from the approved Target
Workflow launch. The initial receipt
`build_receipt_83028c19946fe7e368664b00a71a06ceffcac62d8800b3b48511739d9d786846`
reports an invalid pre-emission generated-function identifier, missing source
and a mismatched numerical composer binding. It emitted no module.

OpenChia automatically continued into native systemd refiner Run
`run_11c36b0e256340542a5ed70b287e99e90d04b933b2b6a13c224c4ff70c866d89`, through
`experiment_c25d2a8b6bd00b97ef9ab4782cc8f570a38763ec6b765db41e1aeac3d6bfb1a3`.
At this observation the initial Verify child has returned and the parent has
issued its first live model request. The job is live, not accepted or complete.
No candidate edits, supplied model responses or manual stage starts were used.
`acceptance/setup_inputs.json` identifies this attempt separately from the
cancelled predecessor. This receipt proves the repeated automatic handoff,
not source repair or target correctness.

### Live Designer feedback defect and cancellation, 2026-10-03

The one-start job below reached its Designer after the Parts Episode corrected
an invalid assignment-reference proposal through the normal loop. The Designer
then proposed two plans. Each covered all 16 assigned contribution keys and
included one extra, preservation-only key. Both were rejected with "plan must
cover the assigned contribution," although neither omitted a contribution key.
The missing/extra distinction matters to the next repair decision.

The operator cancelled the whole job before changing host code. The durable
job result records `cancelled` and no verified build. No operator changed the
candidate, waived admission, or manually launched another stage. This proves
automatic handoff and feedback-driven proposal correction, not source repair
or independently accepted target behavior.

The focused regression reproduced the misleading error before the fix:
**2 failed in 23.1 seconds**, with retries disabled. The fix retains exact-key
equality but reports both missing and unexpected keys. Proposal guidance also
shows complete artifact-reference objects instead of suggesting ID strings.
The canonical post-fix run passed **13 tests across three files in 67.9 seconds**,
retries disabled: `test_plan_feedback.py`, `test_campaign_state.py` and
`test_control_integrity.py` under `tests/iterative_episode_refiner`. Corrected
plans admit without changing candidate code or earning credit from plan admission
alone. These are host feedback/admission checks, not live acceptance. Ruff and
`git diff --check` pass.

### Ordinary launch compatibility after automatic refinement, 2026-10-03

The old launch fixture failed on the current tree (**1 failed in 2.9 seconds**)
because it supplied no owning Duet binding and expected `/build` to finish at
`materialized`. It now binds a distinct supplied refiner route, starts the normal
build, waits for the real refiner call, and explicitly cancels the job. The
cancelled job retains admitted source; the subsequent explicit `/run` tests
launch approval, nested experimental dispatch and host measurement as before.
Both target and tester builds take this route. No production preflight, refiner
handoff or final-acceptance check was bypassed or weakened.

The focused canonical run passed **1 test in 91.9 seconds**, retries disabled.
The final combined run with `tests/agent/test_build_refinement_job.py` passed
**3 tests across two files in 107.5 seconds**, also without retries. The existing
native failed-build handoff/cancellation case remains green. Ruff and
`git diff --check` pass. Model choices and in-process confinement
attestation remain fixtures. This proves compatibility of explicit `/run` with
admitted source from a cancelled build, not successful whole-build refinement.

### Live one-start build reaches the native refiner, 2026-10-03

From clean source commit `899ff4a220`, the ordinary `OpenChiaHost.start_build`
entry started build request
`build_request_c83fa094bd72734af5604677e45dd990212511f6c0e2a5ba4c9a2e8257e2a722`.
The owning Duet is a fully initialized `AIAgent`, bound through `bind_duet`,
using the existing conversational configuration (`gpt-5.6-sol-900k`, `xhigh`).
The Target Workflow and its Builder retain their separately approved launch.
Only the build start and status inspection were operator calls; no operator
launched the refiner, supplied a model answer, or edited the candidate.

The real initial Builder response failed planning: generated binding 5 did not
use the required pre-emission `generated` identifier. The retained receipt is
`build_receipt_69fc4b020becd3ddba3484324e9208dc560002fa17c10295e36cf0d55e426bad`,
with zero emitted modules. OpenChia automatically advanced the same job to
refinement and started native systemd Run
`run_e0a83dce815f8e0bbd664236b1d10c8d9466b4a054bf3528c183838c5ff44b38`
through experiment
`experiment_142e3745046a5c506369045ba4e43323bf4723ea6edbb605590fbb9521fd9d32`.
The committed Run prefix shows the initial verification child completing and
the parent issuing its first live model request. At this observation the job
is still running; no repaired or independently accepted build is claimed.

An earlier invocation in this session passed the reasoning configuration helper
arguments incorrectly. It was cancelled before refiner execution, preserving
`build_request_cc7421893aa9af574d0d4d7ea679876b031e7e0f0cade0c3ee1fc8edd5329e0b`
as a cancelled job. That operator setup error is not acceptance evidence. The
corrected invocation above preserves the actual Duet reasoning configuration.

### Admitted checks reach parent validation, 2026-10-03

The canonical runner passed **9 tests across five files in 123.5 seconds**,
retries disabled: `test_registered_measure_preparation.py`,
`test_campaign_measurements.py`, `test_measure_control_experiments.py`,
`test_refinement_experiments.py` under `tests/episode_runtime/testing`, and
`tests/agent/test_build_refinement_job.py`.

Normal-build campaigns now declare local and acceptance measure groups before
refinement starts. Admission retains the original check and projects it into
the matching group with the same predicate, controls, execution binding, guards
and evidence. Parent validation discovers those checks through the existing
evaluation resolver and shared experiment service. It rejects omission of a
new mandatory check; earlier requests retain their original exact check sets.
Grouping earns no additional adequacy credit. Final provenance follows the used
checks back to the original measure admission and its controls and limitations.

The new integration case uses independently derived scheduling controls and
supplied target answers. The common measurement service reports the correct
answer as passing and an infeasible answer as failing under the parent's group.
Neither measurement grants parent acceptance by itself. This is measurement
integration, not execution of the supplied answers by a candidate or live repair.
The existing native handoff/cancellation limits below still apply.

An initial focused run failed because group bindings were mixed into the source
measure's binding list. The existing record validator rejected that mismatch.
The fix preserves that validator and derives group bindings from the admitted
projected checks. Focused reruns passed **3 tests in 39.0 seconds**, then **3 in
42.9 seconds** after adding the shared-service measurement case.

Remaining gaps include measurement coverage beyond the exact scheduling goal,
live autonomous repair/acceptance through one start, and the older launch-fixture
compatibility failure. This receipt does not establish whole-build acceptance.

### Registered task grounding and Measure-to-parent return, 2026-10-03

The canonical runner passed **7 tests across four files in 77.2 seconds**, retries
disabled: `tests/episode_runtime/testing/test_registered_measure_preparation.py`,
`test_measure_control_experiments.py`, `test_scheduling_measure.py` in that same
directory, and `tests/agent/test_build_refinement_job.py`. Ruff and
`git diff --check` also pass. No live model call was made for this receipt.

The new integration test approves/builds the scheduling fixture, prepares the
campaign through the normal preparation code, and gets its measurement cases
from the registered source and original requirements. It does not supply the
expected optimum or controls. The independent exhaustive solver supplies those;
Measure uses the existing proposal/admission route and common control judgments.
A forged expected-answer case is rejected with no checks or facts admitted.
The valid case distinguishes positive, infeasible, suboptimal and empty-answer
controls. Its typed return gives the parent a useful new measurement decision,
not whole-build acceptance. A second case changes the approved worker count:
the familiar benchmark ID alone does not make the source applicable.

The parent-return regression was reproduced by restoring the old `_fact_keys`
call: **1 failed, 1 deselected in 13.4 seconds**, with a missing `proposal`
argument while closing the parent unit. Restoring the fix gives the passing
combined result above. The initial focused run passed **2 tests in 24.5 seconds**.

The existing independent-checker controls and supplied-answer scheduling tests
remain green. Normal-build failed-attempt handoff/cancellation still passes
through the real systemd worker, and materialized-build handoff passes in-process.
Those use supplied model responses. The new measurement test exercises host
admission, parent return and credit, not autonomous reasoning or target execution.

**Still unverified/incomplete:** whole-build adoption of newly admitted measures,
measurement coverage beyond the supported scheduling goal, and live autonomous
repair through one start. The older launch-fixture compatibility failure below
has not been retested or fixed by this change. The goal is not complete.

### Normal build → refiner handoff and cancellation, 2026-10-03

The canonical runner passed **12 tests across four files in 67.7 seconds**, with
retries disabled: `tests/agent/test_build_refinement_job.py`,
`tests/episode_builder/test_reference_context.py`,
`tests/episode_runtime/testing/test_refinement_job_experiments.py`, and
`tests/openchia_cli/test_openchia_cli_commands.py`.

The normal entry is called once. A rejected initial Builder output enters the
real refiner in a native systemd worker, uses its owning Duet's route rather than
the Target Workflow launch, and stays in the same active build job. Cancellation
retains the original failed receipt and the cancelled refiner evidence, verifies
the exact worker stopped, and survives reopening the host. No second human
approval is added. A separately materialized initial build enters the same
refiner path in-process. Both use supplied model responses and cancel at the
first refiner request; neither demonstrates a behavioral repair or acceptance.

Builder reference evidence now contains the registered function implementations
in both planning and emission context, bound to the plan's evidence hash. Its
regression failed before the fix and passes. The fixed refiner adapters use
ordinary Builder source admission; no model response is fabricated in production.

A separate implementation-plan regression failed on a stale
`design_choice_unresolved` finding, then passed (**1 test in 2.7 seconds**).
Revised node choices replace only that node's old implementation uncertainties;
current unresolved choices and authority restrictions remain. The original plan
is immutable and host-derived channel identities remain mandatory.

The older `tests/agent/test_episode_testing_launch.py` currently fails (**1
failed in 3.0 seconds**): its one-shot host fixture has no owning Duet model
binding. It must be updated to exercise the new full lifecycle once behavioral
measure setup is connected; skipping refinement or borrowing the target launch
would not be a valid fix. The broad suite is not claimed green.

Earlier runs of the new handoff test failed on test setup/inspection mistakes:
an empty learning environment, a string passed instead of an OpaqueId, and a
missing executor argument to the stopped-worker check. The passing run above
includes their corrections. These receipts do not establish a green broad
compatibility suite or the full goal.

**Remaining completion gap:** the normal-build campaign still needs the parent's
task-specific behavioral measure setup. Static checks cannot discharge the
original behavioral requirements. Live automatic repair/acceptance remains Task
4; [ADR 0007](../adr/0007-build-owns-iterative-finalization.md) requires the system
to own that work without a manual restart at the Builder/refiner boundary.

### Approved live build: first attempt blocked, 2026-10-03

The human approved the exact scheduling Target Workflow and designated launch
configuration. The ordinary `OpenChiaHost`/`DuetService` APIs recorded the draft,
workflow approval, launch selection and launch approval in a new private workspace
at `/home/chia/repos/OpenChia-acceptance-0RN3r9BH`. No fixture approvals, supplied
model responses or replacement Builder were used. The shared `register-launch`
CLI verified the existing approval and stored its public configuration reference.
Exact IDs are in [the setup record](acceptance/setup_inputs.json).

`OpenChiaHost.start_build` invoked the real model on the approved `reasoning`
slot: `sol_medium`, `gpt-5.6-sol`, medium effort. Its single planning call
succeeded in **168.578 seconds**. The Builder then returned a **blocked** receipt,
with zero planned nodes and zero emitted modules:

- A generated component used an invented `function_...` identifier rather than
  the required pre-emission literal `generated`.
- The model left `result_channel_names` unresolved because the reference did
  not expose its credit schema's exact channels.
- No module was emitted, so whole-build admission also reported `missing_module`.

The saved prompt confirms a concrete context gap: the reference contained its
design module and function metadata, but `pinned_source_files` was empty and
the implementation of `reasoning_credit_schema` was absent. That registered
function actually returns one column; the model proposed four category names.
This is not a missing user choice about the scheduling problem. The separate
invented binding identifier also violated an explicit planning rule. Neither
finding has been silently repaired or waived.

The failed receipt is
`build_receipt_2edf155b421f3efcb8e6dd3f181a023b39534f803143284a1bb77dc2986ce8ea`;
the corresponding model evidence is
`build_model_call_bc445ccfbd1e441d4140a9fe0619a12ca855bddd02843f66a1ebfdd2573b3f6b`.
The ordinary Builder also published its immutable materialization handoff and
refinement baseline. These preserve the failure for subsequent refinement.
The build launched from commit `4213967c09` with a clean checkout; subsequent
changes in this step are setup/receipt documentation only.

The independent solver separately derived optimum 14 and a feasible witness.
Its checker accepted that control and rejected an infeasible schedule claiming
14 and a feasible delayed schedule completing at 15. This prepares measurement
grounding; no criterion was registered against the unadmitted build. These are
not candidate executions or evidence of successful reasoning/repair.

**Task 4 remains open.** No Target Workflow worker or testing Episode has run,
and no repaired build exists. No frozen design, threshold, production source or
admission rule was changed to turn this failure into a pass.

### Native nested continuation: passing shared-service comparison, 2026-10-03

The final canonical run of
`tests/iterative_episode_refiner/test_nested_continuation.py` passed
**1 test in 844.7 seconds**, one worker, retries disabled, with the runner's
operational file timeout set to 1800 seconds. No Episode controller or semantic
stopping threshold changed. This completes task 3's native nested-continuation
verification, not task 4's live reasoning acceptance.

The test executes `Parts → Designer → Implementer` in real confined systemd
workers through `ExperimentService.run` and `continue_run`. It cancels the first
physical Run after Implementer's final unit reply is durable but before the host
accepts the child return. The old worker is verified stopped. Continuation keeps
the logical identity, uses a new executor identity, and checks current authority
both before launch and after reconstruction. Only physical startup events may
precede the reconstruction gate; no old model call, edit, target check or credit
admission is repeated.

The resumed child returns once. Repeating the continuation request returns the
existing Run without another call, edit or credit update. The resumed and
uninterrupted cases have equal terminal disposition, normalized numerical
history, campaign operations, model-call counts, target-check counts and unique
unit counts. Both end with disposition `attained` under the fixture's contract.
During this run, the shared `run-record` CLI also exposed the cancelled original
and succeeded continuation with current indexes: seven original model responses
and two new responses after continuation, not nine repeated responses.

**Evidence limit:** Builder/model decisions and Target Workflow observations are
supplied. The applied source change is a comment, not a behavioral repair. This
proves native refiner execution and continuation through the common service; it
does not prove live-model experimental design, target correctness or autonomous
repair. Those remain task 4. The nine focused passes below plus this final pass
resolve the known failures; the entire 64-file suite was not rerun green.

### Focused continuation rerun, 2026-10-03

The six-file canonical rerun finished **9 passed, 1 failed in 719.0 seconds**,
two workers with retries disabled. Reasoning execution passed both in-process
and confined cases (**217.8 seconds** for that file), along with confined
single-Episode continuation, execution admission, refiner-job routing and CLI
continuation. No Episode stopping threshold changed.

The remaining nested test reached the real executor's continuation preflight,
past the corrected frozen-starting-state lookup. Its own inspection callback
then incorrectly tried to read an unpublished Run's journal. The executor
deliberately authorizes before publishing the new registration, then authorizes
again after worker reconstruction. The assertion was changed to distinguish
those two stages, and the interrupted case moved before the uninterrupted
comparison.

The next one-file run **failed in 266.0 seconds** at the second stage: the
callback still incorrectly required an empty journal, overlooking the native
executor's `runtime_ready` and `run_started` events. It reached that stage
without repeating campaign effects or model calls, but did not admit new work.
After reviewing the executor and reconstruction sequence, the callback now
allows only those physical-startup events before activation. The final audit
check locates the single `run_reconstructed` event after startup instead of
assuming it is the journal's first event. It still forbids new Episode work
before authorization and checks unchanged original evidence, campaign effects,
model calls and target executions. Native nested recovery was not yet a passing
claim at that point; the subsequent passing comparison is recorded above.

### Compatibility after native setup, 2026-10-03

The canonical check finished **343 passed, 1 failed, 2 skipped across 64 files
in 883.9 seconds**, with three workers, retries disabled and runtime sources
unchanged throughout. It covered runtime, Builder, refiner and method-loop tests,
reasoning selection, repeatable calls, ordinary testing launch, launch setup and
CLI continuation. The nested continuation comparison ran separately below.

The sole failure was the confined reasoning fixture's separate **180-second
`wait_for`**. The trace shows it handling a learning `select` request at unit
ordinal 18 when cancelled; it is not a launch or AppArmor refusal. Native
single-Episode continuation and service lifecycle checks passed in this batch.
The optional live-model and live-container cases skipped. This is not a
whole-system acceptance pass, and the timeout is not attributed conclusively to
load or to a specific storage cost.

The reasoning fixture now relies on the canonical runner's operational file
timeout instead of its own additional deadline. Its frozen continuation threshold
remains **0.1**, not the reference/live-benchmark default **0.01**; these timings
are not performance evidence for the default. The nested-continuation lookup
described below is also corrected. The subsequent focused result is recorded
above; the Episode controllers and their thresholds are unchanged. Focused
Ruff and `git diff --check` pass.

### Native nested continuation: first shared-service run, 2026-10-03

The nested comparison now calls `ExperimentService.run` and `continue_run`
through the actual systemd executor, worker pipes and current-authority gate.
The former test-only loopback/reconstruction driver is removed. Refiner model
choices and Target Workflow observations remain supplied fixtures; the source
change is a comment, not a demonstrated behavioral repair.

The first canonical check, one worker with retries disabled, **failed after
694.5 seconds**. Uninterrupted `Parts → Designer → Implementer` execution passed
its assertions. The interrupted case durably closed Implementer's unit, stopped
the physical worker and retained the waiting parents. The common service then
refused continuation before launching a replacement worker: `execution.py`
looked for `plan.subject.starting_state`, whereas the frozen preview stores it
under `plan.scope.starting_state`. This is a continuation defect, not an
AppArmor failure or a passing recovery receipt. Task 3 remains open.

### Approved AppArmor setup and installation diagnostic, 2026-10-03

The operator approved the executable-specific exception. The reviewed
`scripts/apparmor/openchia-systemd-executor` was installed as root-owned mode
0644 at `/etc/apparmor.d/openchia-systemd-executor` and loaded with
`apparmor_parser`. AppArmor remains enabled and
`kernel.apparmor_restrict_unprivileged_userns` remains **1**. The exception
applies to all services using `/usr/lib/systemd/systemd-executor`, not only
OpenChia. No systemd upgrade, global AppArmor disablement or replacement
executor was used. Setup and reversible removal are documented in
[the systemd setup guide](systemd_setup.md).

The real diagnostic returns `ready` on systemd **255.4-1ubuntu8.17**, having
observed distinct mount and network namespaces. Source installation (including
unattended installation) and `hermes doctor` invoke the same diagnostic. It does
not run an Episode or access model credentials, and never installs security
policy automatically, including under `doctor --fix`.

The four-file canonical CLI check, three workers with retries disabled, passed
**21 tests in 7.3 seconds**: diagnostic behavior (3), source completion (6),
doctor exit status (7), and source-update compatibility (5). The diagnostic test
executes the real namespace probe; the refusal cases also cover systemd accepting
properties without creating the namespaces. The install-path assertion confirms
unattended installation invokes the check without requesting policy changes.

After the policy was installed, a three-file native/runtime check first returned
**4 passed, 2 failed in 54.2 seconds**. Native service inspection and descendant
termination passed, but the full worker exposed a pre-existing startup race:
the host rejected an inactive unit before its first invocation. Correcting that
race exposed a second issue in the previously unexercised worker path: importing
library definitions did not preload their lazily referenced implementations
before Landlock. The next two-file check returned **1 passed, 2 failed in
56.8 seconds**, with that explicit loader error. The loader now preloads selected
definitions from verified library exports, without executing generated code
before confinement. The executor also inspects the actual network namespace
instead of trusting the requested property.

The final three-file canonical runtime check passed **6 tests in 198.8 seconds**,
three workers and retries disabled:

- Native service lifecycle and backend attestation: **3 passed** (default and
  explicit resource settings, actual namespace/mount inspection, whole-job stop).
- Confined interrupted continuation: **1 passed**. Two distinct real systemd
  workers preserve the committed model replies and positive credit, verify the
  first worker is stopped, reconstruct through the shared gate, then return
  normally without repeating calls or awarding the same credit twice.
- Reasoning workflow: **2 passed**, one in-process and one real confined worker.
  The native case uses actual host/worker messages and host model audit events,
  including rejection and repair of malformed responses.

Builder/model answers in these runtime checks are supplied fixtures; this is
not the live-model scheduling benchmark. The continuation case is one inquiry
Episode, not the remaining native nested-refiner acceptance. Live container
execution, live-model experimental design and independently checked reasoning
acceptance remain unverified. Focused Ruff and `git diff --check` pass.

### Systemd 255 compatibility work, 2026-10-03

[ADR 0006](../adr/0006-support-systemd-255.md) records the approved compatibility
decision. The current worktree removes the unsupported `PrivatePIDs` request and
mandatory private-PID attestation for systemd only; the container requirement is
unchanged. Direct host cgroup-allocation discovery is removed. Explicit resource
settings and whole-service stop behavior use systemd's existing interfaces.

The canonical two-file check, two workers and retries disabled, returned
**17 passed, 2 failed, 1 skipped in 2.8 seconds**. Container checks passed
**16**, with their live-daemon case skipped. The attestation invariant passed,
including rejection of weakened container isolation and of missing other
systemd isolation facts. Both real-systemd service cases failed before the helper
program started. The test covers default and explicit resource settings, actual
mount inspection, and termination of the service and its child; those native
claims therefore remain **unverified**, not passing.

The service journal reports `226/NAMESPACE` and failure to establish mount
namespacing. The matching kernel audit records AppArmor denying `sys_admin`
inside `unprivileged_userns` for `/usr/lib/systemd/systemd-executor`. The network
namespace request was also skipped by systemd for lack of privilege. This is
distinct from the earlier unknown-property rejection. An explicit `PrivateUsers`
diagnostic encountered the same denial; no additional namespace mechanism is
being added to the worker.

A separate four-file canonical check, three workers and retries disabled, passed
**15 tests in 15.6 seconds**: continuation identity (2), worker stderr diagnostics
(2), executor HTTP protocol loop (1), and egress contracts (10). The HTTP-loop
test uses real pipes and stores but a supplied worker/inspection; it does not
prove native confinement. Focused Ruff and `git diff --check` pass.

The obsolete synthetic cgroup-hierarchy tests were replaced with the real-service
and backend-attestation checks in `test_systemd_executor.py`; their old source is
recoverable from Git. At this point no host security policy had been changed and
operator approval for a launcher-specific AppArmor exception was outstanding.
Full native worker continuation and live model-directed acceptance had not been
rerun on that edit. The later approved setup is recorded above.

### CLI HTTP credentials and compatibility corrections, 2026-10-03

The five-file canonical check finished **69 passed, 1 failed, 1 skipped in
60.7 seconds**, with Python sources frozen, three workers and retries disabled.
It covered CLI continuation, container arguments, the testing-Episode loop,
non-native reasoning execution and the 50 egress-contract checks. The already
diagnosed native reasoning test was explicitly deselected; the live container
test skipped without its configured image. Neither is counted as a pass.

The sole failure was in the new CLI fixture before build or execution: it omitted
the inquiry contract's required environment conditions. After supplying an
explicit fixture environment, the CLI file passed **2 tests in 8.6 seconds**,
retries disabled. All other files had passed the preceding check. These are
separate receipts, not a claim that the broader 66-file batch was rerun green.
Focused Ruff and `git diff --check` pass.

Live CLI `run` and `continue` now supply HTTP credential descriptors through the
same active-profile config reader, egress parser and `ScopedHttpBroker` as the
host service. The CLI check uses fixture-approved egress and launch contracts,
actual Builder admission, config files, profile/secret scopes under multiplex,
the real HTTP broker and existing stores. Only the executor and outgoing HTTP
transport are supplied. Calls under profile A, then B, then A carry the matching
token. The assertions retain exact interruption rejection, continuation identity,
idempotence and unchanged original evidence, and verify that CLI output and saved
Run evidence/audit contain no token values. A second check confirms malformed live
credential configuration fails for live modes but does not affect numerical or
recorded modes. No credential store, launch-auth fallback or new runner was added.

The container fixture now uses a real registration and verifies physical/logical
Run identity propagation. The testing-Episode fixture now relies on the canonical
runner's file timeout; its numerical threshold and credit assertions are
unchanged. Its functional loop passed in 40.5 seconds in this check. The earlier
unchanged rerun and broad-run timeout remain recorded below.

The guide now documents exact launch approval, retained report/attempt queries,
scoped control history, unsupported executable child-result substitution, the
owning-Duet service required for fresh refiner experiments, and existing HTTP
credential configuration. These changes do not establish native confinement,
live-model experimental design, a real-model scheduling answer or autonomous
repair. The two native `PrivatePIDs` failures from the broad run remain unresolved;
live acceptance still requires its actual human-approved workflows and launches.

### Broad compatibility check after campaign routing, 2026-10-03

The canonical runner finished **444 passed, 4 failed, 2 skipped across 66 files
in 1003.2 seconds**, with Python sources frozen, retries disabled and 12 workers.
It covered `tests/episode_runtime/`, `tests/episode_builder/`,
`tests/iterative_episode_refiner/`, `tests/method_loop/`, reasoning selection,
ordinary-host testing launch, repeatable Episode calls, egress allowlist contracts,
launch setup and CLI continuation. Nested loopback continuation passed, including
the comparison against uninterrupted refinement. Scoped execution, unit execution,
campaign-source routing, records and shared refiner experiments also passed.

The four failures are retained explicitly:

- The container argument fixture supplies a `SimpleNamespace` missing the new
  logical Run identity fields. Production argument generation requires the real
  registration; the fixture needs correction.
- Native continuation and native reasoning-worker checks both fail before worker
  inspection: this host rejects the required `PrivatePIDs=yes` systemd setting.
  Confinement was not relaxed and these are not passes.
- The scripted testing-Episode integration hit its own 60-second `wait_for`
  deadline while awaiting the host learning broker. The output establishes a
  timeout, not its cause or an infinite loop. An **unchanged** focused canonical
  rerun then passed **1 test in 27.6 seconds**, retries disabled. This supports
  a load-sensitive timing diagnosis; the failed journal was not retained, so
  contention is not proven. It is not grounds to change the numerical stopping
  rule. The fixture now relies on the canonical runner's existing file timeout
  instead of a separate 60-second deadline on the functional loop.

The container live-image test and optional live-model acceptance test skipped;
neither provides native or live reasoning evidence. The passing tests retain
their supplied-response/in-process/loopback limitations. This is a compatibility
receipt, not successful whole-system or real-model acceptance. No testing or
continuation rule was changed during the run.

### Campaign source routing and authorized discovery verified, 2026-10-03

The final focused canonical run passed **6 tests across five files in 137.3
seconds**, with Python sources frozen and retries disabled:
`test_campaign_source_experiments.py`, `test_worker_access.py`,
`test_campaign_measurements.py`, `test_numerical_execution.py` and
`records/test_continued_history.py`. Focused Ruff and `git diff --check` pass.

Both editable-instrument and read-only-reference cases use actual approved
fixture builds, campaign assignment admission, an authenticated model-response
event for the supplied experiment proposal, the common ExperimentService,
generated stock reasoning source, and the existing in-process LinkedExecutor.
No execution occurs before the Episode proposal. Wrong candidate, build and
measure references fail both assignment validation and shared preview. The
source's empty failed attempt returns integer zero credit, and the parent-owned
exact-value criterion passes without granting parent acceptance. Repeating the
experiment does not execute it twice. Source identity and namespaced instrument
files remain distinct from the primary target.

An independently fixture-approved Testing Episode session follows preview,
run, inventory and report queries for its exact assigned experiment. The tester,
campaign and executable have different owners. Unassigned experiment inventory
and direct foreign-Run browsing are rejected. Numerical replay uses the exact
source recording (including that same recording as parent context) and exposes
its inventory. Recorded-response execution explicitly diverges because the
stock reasoning prompt contains Run-specific provenance; it never rewrites the
prompt or calls the live transport. The original audit and campaign state remain
unchanged. Retained report pagination across an interrupted/continued experiment
also passes through the existing worker-interface test.

The preceding corrective run passed **11 tests and failed 2 across seven files
in 140.4 seconds**. Its source executions succeeded, but the new fixture supplied
floating-point `0.0` to an exact JSON predicate whose observed credit was integer
`0`. The fixture now uses the actual integer representation; the predicate and
yield rules were not relaxed. That run also passed the existing direct/independent
checker, measure-control, execution-history and continued-history tests.

These receipts complete task 1's shared refiner-routing work. They use supplied
choices and model answers, fixture approvals and in-process execution. The
auxiliary source fixture uses a **0.9** continuation threshold for this mechanical
check, not the shipped **0.01** live-acceptance configuration. They do not establish
autonomous experimental design, behavioral repair, real-model reasoning, native
confinement or final whole-system compatibility. Tasks 3, 4 and 5 remain open.

### Campaign instrument/reference experiments: first integration check, 2026-10-03

The canonical five-file run finished with **8 passed and 3 failed in 104.5
seconds**, with Python sources frozen and retries disabled. Existing target and
independent-checker experiments, grounded measure controls and execution history
passed. An ordinary campaign measurement correctly rejected an unadmitted check,
but the new source resolver misclassified that rejection as a control-context
error. Both new auxiliary-source cases stopped at a test fixture's nonexistent
campaign field before execution. Those failures are being corrected; this run
does not verify the new source routes.

Read-only review also found worker inventory queries using the executable owner
where the experiment owner was required, and report queries using the testing
Episode owner where the measurement owner was required. Both corrections must
retain exact experiment-access checks; general cross-owner browsing is forbidden.

### Later-unit learning and numerical history, 2026-10-03

The canonical run passed **41 tests across seven files in 304.2 seconds**, with
Python sources frozen and retries disabled. Files: `test_later_unit.py`,
`test_epistemic_learning.py`, `test_learning_continuation.py`,
`testing/test_unit_execution.py`, `testing/test_numerical_execution.py`,
`testing/test_reconstruction_source.py` and
`tests/method_loop/test_episode_tree_recursion.py`.

The new experiment test uses the real Builder, common ExperimentService,
generated stock reasoning Episode, linker, ledger and stores, with supplied
model replies and an in-process executor. It runs an original Episode, captures
its second unit, and executes only that unit under a new experiment identity.
Exactly two new model calls select and execute the unit. Its prior lesson and
evidence identities survive; operative scope/equivalence move to the new
invocation. Inherited credit is explicit and the repeated failure earns zero.
The original audit is unchanged, repeating the experiment adds no events, and
the public store validator rejects forged historical-credit reset and state
discard. Numerical replay of the new experiment primes the inherited observation
history and reproduces the recorded controller decision without calls or credit.

The existing nested first-unit scope, learning continuation, source-admission,
numerical and method-loop checks also pass. This is not native confinement or
live-model reasoning evidence, and does not prove arbitrary Python restoration,
changed-build transfer, continued/scoped source reuse or historical refiner forks.

Subsequent review found that direct generic-executor callers could bypass the
shared service's source-shape check. The same checker now runs during package
preparation; a new assertion probes a forged source-admission receipt. Numerical
preview also now exposes inherited-history references/counts. The focused
canonical rerun passed **8 tests across four files in 33.1 seconds**, with
Python sources frozen and retries disabled: later-unit execution, reconstruction
source admission, experiment planning and numerical execution. It verifies those
final additions. Focused Ruff and `git diff --check` also passed. These receipts
do not close task 1 or the overall goal.

### Unit starting-prefix discovery, 2026-10-03

The canonical run passed **4 tests across two files in 266.9 seconds**, with
Python sources frozen and retries disabled. The record test discovers first-unit
and later-unit starting-prefix references without loading the Run audit, retains
exact-prefix pagination, and reports a gap for missing predecessor units. The
generated nested-Episode test confirms that verified CLI/worker boundary capture
derives the same references as indexed inventory. First-unit execution still
uses the shared service and loop; later-unit execution is still refused rather
than reset to fresh state.

This proves selector agreement and preserves existing unit-scope behavior; it
does **not** prove later-unit state restoration. The generated-code test uses
in-process execution and supplied model responses, not native confinement or
live reasoning. A read-only review found no access expansion and identified the
documented limits for incomplete history and parents in earlier physical attempts.
Focused Ruff checks passed. The machine discovery description was then updated
to name the new selector without changing execution availability.

### Scope discovery terminology checks, 2026-10-03

The focused canonical run of experiment planning and recording recovery passed
**3 tests across two files in 7.6 seconds**, with retries disabled. The discovery
and preview descriptions now distinguish a new saved-input experiment from
continuing an unchanged interrupted execution. This was a vocabulary correction,
not implementation or proof of arbitrary checkpoint restoration.

### Nested reconstruction matches uninterrupted refinement, 2026-10-03

The corrective canonical run reported **69 passed, 4 failed across eleven files
in 751.2 seconds**, with Python sources frozen and retries disabled. The complete
nested comparison passed: the actual generated Parts → Designer → Implementer
loops ran once uninterrupted and once interrupted after the Implementer's final
host reply, before its return to the waiting Designer. The shared reconstruction
gate matched the saved prefix and restored the host session. Both executions
produced matching terminal disposition, normalized controller history, operation
counts and unit counts. The resumed case retained the original audit, returned
the child once, and repeated no model choice or source edit.

This is **loopback worker transport with supplied decisions, target observations
and process authority**, not native confinement or live-model reasoning. The
source change is a comment; no behavioral repair is claimed. It establishes
nested restoration mechanics, not general autonomous refinement.

The CLI continuation and continued-history checks passed, including exact
reference validation, idempotent dispatch, retained reports and explicit
per-attempt inventory. Both direct and independently built checker experiments
passed; the latter continues its interrupted checker without rerunning the
target. The stock testing-loop check, existing execution-history checks and
57 allocation cases also passed.

Two failures were stale fixture expectations: the measurement test expected the
older ownership error wording, and the worker test omitted the now-required
attempt selection from continued inventory. After correcting those fixtures,
their focused canonical rerun passed **2 tests across two files in 39.9 seconds**,
with retries disabled. The real worker protocol fixture now consumes the
advertised inventory query for its selected physical attempt and rejects unowned
continuation; process attestation and target results are still supplied. The
other two failures are native launch checks,
both rejected before activation by systemd 255's unsupported `PrivatePIDs`.
They remain failures, not skips or passing isolation evidence. The existing
container backend cannot be used here until a runtime is configured.

Focused Ruff checks over the shared testing/record packages, refinement package,
new transport/control components and their tests passed. Whole-system acceptance
and compatibility remain incomplete.

### Continuation interface failures and nested baseline, 2026-10-03

The next canonical run, with Python sources frozen and retries disabled,
reported **11 passed, 8 failed across ten files in 393.0 seconds**.
Five failures shared one defect: two new per-attempt report ID prefixes exceeded
the existing 32-character opaque-kind limit. The centralized record identity
function now uses shorter namespaces for those new kinds; existing record IDs
are unchanged. This was not five separate execution or authorization defects.

Two native tests failed before worker activation because the systemd launcher
serialized an unbounded CPU quota as `CPUQuota=infinity`. It now uses the empty
assignment specified by [systemd's resource-control contract](https://github.com/systemd/systemd/blob/main/man/systemd.resource-control.xml).
The existing allocation invariant also checks finite-quota preservation and the
different CPU versus memory/task unbounded encodings.

The compact parent-report tests passed. The actual nested, supplied-decision
baseline reached `succeeded`, including parent acceptance, before the comparison
fixture failed by reading the child-only `states` field from the root result.
That assertion now checks the root's actual `report_id` and `disposition`.
The interrupted half was not reached; this is still not restored-loop proof.

The corrective run (reported above) reached
a separate environment limitation: this host has systemd 255, which rejects
`PrivatePIDs=yes`; that isolation setting was [added in systemd 257](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml).
Read-only discovery found no Docker-compatible CLI for the existing alternative
backend. Native execution is not demonstrated, and the isolation requirement has
not been removed. Container setup requires the operator's direction.

### Shared continuation admission and nested-return failure, 2026-10-03

With Python edits frozen, the canonical runner reported **9 passed, 1 failed
across six files in 197.8 seconds**, with retries disabled. Shared execution,
current continuation authority, measurement, direct/independent-checker refinement
experiments and owning-Duet refinement-job tests passed. Their supplied outputs
and in-process execution do not establish live reasoning or native confinement.

The new nested continuation test failed in its uninterrupted baseline: returning
an attained Implementer to its Designer made the host reply exceed the default
1 MiB protocol limit. Thus this run proves no nested restoration. Parent context
now uses a deterministic report overview with exact evidence references rather
than embedding duplicated full observations; the full typed report remains in
shared history. Verification of that correction is pending.

Read-only host checks found a running user systemd manager and a valid effective
resource allocation. The existing confined-worker test then **failed before
launch** in 8.3 seconds because its caller omitted the required `http_broker`.
That fixture call is corrected; this failed run is not confinement evidence.

The CLI/Episode continuation operation and retained per-attempt measurement
reports have since been connected. Their new service/CLI tests remain pending.

### Reconstruction admission and cross-attempt learning, 2026-10-03

A frozen-source canonical run with retries disabled reported **53 passed,
1 failed and 1 collection error across eight files in 342.3 seconds**.
The failure found a missing `continuation_admission` parameter on the concrete
executor method (it had only been added to the protocol). The collection error
was an imported `testing_learning_contract` helper picked up as a test. Both
are corrected. The focused identity, source-admission and reconstruction rerun
passed **14 tests across three files in 53.8 seconds**, with retries disabled.

The three learning-continuation cases passed against real Run storage and
host admission. They retain original evidence/credit across multiple physical
attempts, reject a forged reset or dropped prior state at public publication,
and complete an interrupted ledger commit exactly once. These are ledger checks;
an incomplete host exchange is still unsupported for worker reconstruction.

The extended unit-scope check passed. A resumed testing invocation retains its
owned experiment, history and recording/boundary permissions under the logical
Run identity; a distinct execution does not inherit them, and a completed
invocation loses active caller access. Caller-start boundaries are supplied.

Four intended source-admission cases passed for actual admitted reasoning,
testing and refinement packages and rejected non-stock code. No generated
module is activated on the host. Eight reconstruction checks passed, including
the executor's new host gate over all recorded channels, one durable activation
receipt and re-interruption without copying history. Source/authority facts in
that gate fixture are supplied; it is not a native executor or nested-coroutine
continuation receipt. The existing learning, broker and three host-restoration
checks also passed. Service/CLI continuation and the real nested return remain
unfinished.

### Continuation authority and original-response provenance, 2026-10-03

The next frozen-source check reported **6 passed, 1 failed across three files
in 69.6 seconds**. The failure was a new test reading the database-only
`revoked_at` name from the public approval API, which exposes `revoked`. After
correcting that assertion, the focused open-child case passed in **19.2 seconds**.

The test commits a model response through the real broker, interrupts before
proposal admission, restores host state, and authenticates the proposal against
the exact predecessor event. The original physical Run/event remains its
provenance; the new journal stays empty and no model call or credit is copied.
Malformed proposal JSON still receives rejection/zero progress.

It then uses the existing Duet note, refinement request and approval APIs in
the isolated test store to approve a real implementation successor. The campaign
head is unchanged and the prior approval remains unrevoked, but restoration
rejects its no-longer-current authority. Target and refiner authority checks run
inside the restore transaction and still need rechecking at future activation.
Other identity, refiner-job/numerical and prepared/closed-unit restoration checks
passed. This adds authority/provenance evidence, not a live continuation receipt.

### Host restoration and independently measured schedules, 2026-10-03

A frozen-source canonical run with retries disabled reported **19 passed,
0 failed, 1 skipped across seven files in 84.6 seconds**. The earlier three
fixture failures are corrected: identical claims remain idempotent, a different
executor cannot take the claim, generated modules are released between simulated
process instances, and the numerical decoder receives valid opaque result IDs.

Three new checks drive real refinement host operations through the common broker
and Run journal. They restore a prepared child, a waiting parent with an open
child unit, and a waiting parent after the child's unit receipt. Exact assignments,
goals, handoffs, earlier candidate references and operation ordinal survive; the
original audit and campaign head are unchanged. A later legitimate campaign
change rejects the saved state instead of silently using the newer head. Worker
boundaries and choices are supplied: these are host-restoration checks, not resumed
coroutines, full child-return coverage, native confinement or live reasoning.

Two scheduling-measure checks use the existing criterion registry and shared
measurement service. The single-sourced exhaustive oracle accepts distinct feasible
optima; infeasible schedules with a correct-looking claimed minimum, feasible
nonoptimal schedules, wrong completion times, malformed types and duplicate jobs
fail. Mislabeled controls and caller-supplied optima are rejected. Prose does not
determine the verdict and remains inspectable evidence. The durable result tests
use supplied outputs, not model-produced schedules.

The eight reconstruction checks, refiner-job/numerical integration and negative
decoder check, shared measurement check and offline scheduling oracle also passed.
The old live acceptance test was skipped because no opt-in socket was supplied;
it would not prove native transport even if enabled, so it is not the pending
shared-interface live acceptance demonstration.

A separate read-only audit of the current default host stores found no admitted
build manifests, Run registrations, testing criteria or approved launch selections
for the benchmark/tester. Existing workflow approvals concern other tasks. The
designated launch JSON alone does not grant authority to build or launch new
acceptance workflows; exact workflow and launch approval are still required.

### Shared execution, numerical replay and host allocation, 2026-10-03

A frozen-source canonical run with retries disabled reported **151 passed,
3 failed across 14 files in 377.7 seconds**. Shared scoped/nested and unit
execution, direct/checker refinement experiments, grounded checker controls,
execution history, all eight reconstruction checks, staged imports and the
existing HTTP loop passed. The refiner-job integration now also recomputes its
recorded numerical decisions through the shared service, with no additional
model calls, campaign mutations or credit. Independent publication checks reject
changed prior-opportunity evidence.

The three failures are in new fixtures: expecting an identical executor claim
to conflict (the store intentionally makes it idempotent), loading the same
generated module names twice in one interpreter, and a non-opaque numerical
result ID that fails before the intended decoder check. Their corrections need
a rerun; no production guard was relaxed.

The generic executor's 57 allocation checks passed. Read-only discovery on this
host now succeeds. The earlier diagnosis below was incomplete: CPU controls are
missing below a non-delegating ancestor, not only at the cgroup root. The reader
validates controller/delegation metadata and uses observed ancestor settings;
it neither guesses limits nor treats unreadable or contradictory metadata as
unlimited. This establishes resource discovery, not a successful confined launch.

These remain mechanical/in-process receipts. They do not establish live reasoning,
native confinement or resumed nested execution.

### Owning-Duet refiner-job integration, 2026-10-03

A focused canonical run with frozen Python and retries disabled passed **one
test in 39.3 seconds**. It exercised the shared ExperimentSpec/service path,
actual generated refiner code, a local deterministic HTTP provider and the
existing in-process executor fixture. The host bound the campaign's owning Duet
configuration, kept that exact route when the supplied agent's current settings
changed, and did not use a Target Workflow launch configuration. Rejected-choice feedback
reached the second request. Cancellation remained cancelled/unmeasured with no
completed-build claim. Repeating the same experiment reused its result; a changed
experiment could not silently restart that used campaign. Durable binding data
excluded the fixture credential.

The previous run's 30-second provider wait failed; only the diagnostic wait was
changed before this successful rerun. Its original cause is not established as
a production defect. A subsequent event-based, longer operational test wait and
the queued pre-dispatch/history corrections still require their next check.
The bound agent is supplied, not a fully initialized conversational AIAgent.
This proves that integration path, not live reasoning, native confinement or
successful autonomous refinement. Task 1 still includes refiner numerical replay.

### Reconstruction verification and campaign-fixture migration, 2026-10-03

The canonical runner with Python sources frozen and `--file-retries 0 --tb=short`
reported **21 passed, 1 failed** across seven files in 119.9 seconds:

- Seven reconstruction checks passed using real protocol frames, shared brokers
  and a claimed RunStore, with supplied nested boundary records and host/model
  answers. Exact replies from all five channels were recovered in global worker
  order. Changed request identities, reordered calls and wrong-child calls failed
  closed. A missing committed response or still-active Run could not be replaced
  by an earlier prefix. Exhaustion did not authorize a new action; verification
  left the original journal unchanged and invoked no transports or admissions.
- All ten existing campaign-state/publication-integrity checks passed after their
  fixture was migrated to genuinely admitted target/refiner builds. They retain
  concurrent-head rejection, audited retry, zero credit for unmeasured edits and
  revisits, forbidden Designer/Implementer child creation, and rejection of forged
  completion. No production admission constraint was weakened.
- Direct/checker refinement experiments (two), grounded checker controls (one)
  and staged imports (one) passed again.
- The new Duet-configured refiner-job experiment failed waiting for its local
  provider event. This receipt does not establish that adapter's execution; the
  test is being corrected to expose an early task error rather than mask it with
  the wait assertion, followed by diagnosis of the actual failure.

The reconstruction cursor is a necessary verifier, not a live continuation path.
These supplied-response and in-process tests do not demonstrate live reasoning,
native confinement, restored coroutine state, or authorization to resume arbitrary
generated code. The full continuation and live acceptance requirements remain open.

### Host-state recording and checker controls, 2026-10-03

Three further frozen-source canonical runs used `--file-retries 0 --tb=short`:

- **36 passed, 2 failed** across nine files in 342.2 seconds. Scoped/nested and
  unit execution, direct and independent-checker refinement experiments, shared
  history, scoped reports and staged imports passed. The refiner integration
  verified that the common journal retains host-only call bindings, open-unit
  references and campaign head alongside replies, without placing that state
  in worker-visible results. The failures were a duplicate fixture request ID
  and missing independent publication validation for newly supported control
  evidence; neither was fixed by weakening its guard.
- **23 passed, 1 setup error** across three files in 30.8 seconds after those
  corrections. All-channel recording integrity and exact legacy selector
  compatibility passed. The actual generated checker processed known negative
  and positive inputs through the shared harness. One validated control earned
  one distinct fact without admitting the measure; the second completed the
  all-controls gate, without double-counting admission. Repeated requests added
  no Run or credit. A forged control fact key was rejected at publication with
  the campaign head unchanged. Parent history exposed these as checker-adequacy
  evidence, not repaired-candidate verdicts.
- **5 passed, 4 setup errors** across two existing campaign-state/integrity files
  in 6.0 seconds. Adding the old fixture's missing `evidence_kind` exposed its
  deeper invalid input: it uses a generic host blob where campaign admission
  requires a real BuildReceipt. These compatibility checks have not passed;
  their fixture is being migrated to admitted inputs. Production admission was
  not bypassed.

The first failure above used deterministic `OpaqueId.mint` twice with the same
fixture input; including the request ordinal corrected the fixture. Duplicate
request rejection remains active. The control-credit fix independently derives
permitted fact keys from admitted, scoped control observations at publication;
it does not trust the producer's claimed key or numerical credit.

These results are mechanical/in-process evidence, not live model reasoning,
native confinement or coherent nested continuation. Host-state capture is only
one prerequisite for reconstructing an interrupted worker and its waiting parents.
No continuation operation is advertised as available.

### Live Run prerequisite inspected, 2026-10-03

The designated Target Workflow launch file is readable and the user systemd manager reports
`running`. The existing runner's `ExecutorResources.from_host_effective_allocation`
still raises `RunExecutionError: cannot read host cpu.max`. Inspection found that
its ancestor scan attempts resource controls at `/sys/fs/cgroup` itself; this
host has them on `user.slice` but not on that root. The kernel documents
`cpu.max`, `memory.max` and `pids.max` as non-root cgroup interfaces
([cgroup-v2 documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html)).
The existing container resolver found no Docker-compatible CLI. This is a
specific live-run prerequisite to address through the existing generic runner,
not permission to invent resource limits, weaken attestation or substitute an
in-process acceptance run. No cgroup configuration, executor allocation code,
container installation or credential file was changed by this inspection.

### Shared response durability verified, 2026-10-03

With Python edits frozen, the canonical runner passed **8 tests across 5 files**
in 31.1 seconds using `--file-retries 0 --tb=short`:

- Model request conversion and durable response publication (3): the real host
  channel's writer observes an already committed exact reply. A disconnection
  after commit leaves that reply intact and allows interrupted finalization.
- HTTP exchange through real worker/host pipes (1).
- Recorded external-response dispatch and divergence checks (2).
- Interrupted recording publication (1).
- Approved worker access to the shared experiment service through real pipes (1).

Launch/attestation and model responses are fixtures. These checks do not prove
native confinement, live reasoning, or nested continuation. New all-channel
recording, refiner host-state and measure-control integration checks are being
run separately; this receipt does not claim their results.

### Checker connection and merged-API corrections verified, 2026-10-03

Two subsequent frozen-source canonical runs used `--file-retries 0 --tb=short`:

- **16 passed, 1 failed** across eight files in 188.5 seconds. Both direct and
  independent-checker refinement cases passed. Scoped/nested execution, selected
  unit execution, shared dispatch, model-request conversion, learning-broker
  boundaries and reasoning selection passed. The remaining regression-history
  failure exposed candidate admission using the Builder's removed `call_options`.
- **4 passed, 1 skipped** across three files in 56.7 seconds after candidate
  admission adopted the existing Builder's separate planner/emitter options.
  Cross-child regression history, repeatable-call materialization and the
  in-process generic reasoning workflow passed. The isolated reasoning workflow
  was skipped; it is not confinement evidence.

The checker case executes an admitted deterministic child through the shared
service and existing in-process linker. It compares supplied scheduling answers
with the independently enumerated optimum: the wrong answer fails despite a
forged target pass flag, the correct answer passes despite a target fail flag,
and missing input is unmeasured with no checker Run. The parent receives typed
measured failure and checker evidence distinct from target evidence. Repeating
the request reuses its existing dispatch. Compact history preserves the checker
relationship, explicit fresh-entry scope limits and target-owned launch approval.

This establishes the independent-checker connection, not live problem-solving,
native confinement, autonomous code repair, checker construction or coherent
recovery. The fixture supplies target answers and refiner/model responses. All
five failures from the broader run below have now passed their focused reruns;
that is not a claim that the repository's full suite ran or that later code has
been verified. Targeted Ruff and `git diff --check` also passed.

### Broader post-merge compatibility checks, 2026-10-03

With edits frozen, the canonical runner reported **32 passed, 5 failed** across
21 files in 94.0 seconds, with retries disabled. Passing paths include setup,
host testing launch, worker testing access, the supplied-response testing Episode,
direct refiner experiments, campaign measurement, component execution, recorded
and numerical replay, shared history and scoped reports.

Four failures came from remaining fixture migration omissions: a nested source
constructor did not forward its declared slots (affecting both scoped and unit
tests), the regression fixture still used old launch fields, and a broker request
omitted its model slot. These are corrected for the next run.

The independent checker executed but failed when its evidence returned to the
refiner: registration equality compared frozen tuple-valued arrays with thawed
list-valued arrays. The adapter now compares canonical JSON, preserving exact
content checks. Verification of that correction is pending. The live reasoning
acceptance and coherent nested recovery requirements remain unfulfilled.

### First post-merge compatibility checks, 2026-10-03

The canonical runner with retries disabled passed **6 tests and failed 1** across
four files in 50.9 seconds, with Python edits frozen throughout execution:

- Three launch-setup checks passed: project credential separation, private files,
  and real host/CLI enforcement of exact current human launch approval. A changed
  model slot requires new approval; registration does not grant it.
- The host-to-testing-Episode integration passed using explicit model slots and
  approved target/tester launches. This executes the generated testing Episode
  and shared service, with supplied model responses and target output.
- The staged-import check and direct refiner experiment check passed.
- The independent-checker case reached generated child execution, then failed
  because the fixture passed a non-opaque result identity to `CreditObservation`.
  The fixture identity has been corrected without changing numerical validation;
  this receipt does not claim the corrected checker passed.

An earlier setup-only invocation collected no tests: it ran during an incomplete
cross-file slot migration and found a missing required `model_type` in the
refinement library binding. The frozen invocation above includes that correction.
Remaining harness fixtures are being migrated to the same explicit-slot and
approval APIs. These checks do not establish live reasoning, native confinement,
autonomous repair, or coherent interruption recovery.

### Latest OpenChia merge retained with in-progress work, 2026-10-03

Merged `openchia/main` at `637ea47fbd` (PR #34, approved launch slots) into this
branch with merge commit `684ce78bc9`. No push was performed. The complete
pre-update working tree, including untracked files, is retained in stash
`2aea2018eb18ddfa1902156787be62cb560c09f9` and the stable local Git reference
`refs/checkpoints/unified-harness-before-pr34`.

After reapplication, all 127 saved files were present. 115 were byte-identical,
including all 68 untracked files; the remaining 12 combined the upstream changes
with our work. Conflict resolution retained the shared-testing source hooks,
generalized fixture emission and explicit Duet/refiner-versus-target routing
documentation alongside PR #34's required model slots and launch approval.
The upstream launch format was not reverted to the old bindings/session-auth
format. No credential files or other checkout were modified.

Ancestry, clean conflict-marker/whitespace checks, compilation of the affected
Python merge files, and targeted lint passed. Behavioral tests have not been
rerun after this update. Task 5 must align the harness's old launch/setup and
library-call adapters with the newly required slot APIs; the earlier receipts
do not establish compatibility with this merged state. This remains within the
existing task 5, not a new numbered task.

### Checker integration: fixture admission failures, 2026-10-03

Source edits were frozen during both canonical runner invocations, with retries
disabled. Neither run reached checker execution:

- **3 passed, 1 failed** across three files in 37.3 seconds. The direct experiment,
  staged-import and admitted cross-child regression checks passed, including the
  task-2 failure-report helper extraction. The checker fixture emitted invalid
  Python for an empty component tuple and failed Builder admission.
- **7 passed, 1 failed** across three files in 33.6 seconds. The direct experiment,
  staged imports and all five execution-history checks passed. After fixing the
  tuple, the checker fixture reached source admission but was rejected for direct
  `load` calls bypassing declared collaborators.

The new compact checker-intent projection and actual checker-computation assertions
are present, but that path has not passed. Passing history tests in the second run
establish compatibility of the existing ordinary/refinement intent views, not the
new checker path. No admission check was relaxed. Task 1 remains incomplete.

### Shared record interface completed (task 2), 2026-10-03

The canonical runner with retries disabled passed the focused checks in stages:

- **13 passed, 1 failed** across five files in 19.8 seconds: the five execution
  history tests, three Run-record tests, four scoped-report tests and one staged
  import test passed. The new admitted-regression test failed because its fixture
  inherited the wrong child bindings for the Designer role.
- **4 passed, 1 failed** across two files in 14.6 seconds: report checks, including
  unresolved-conflict priority, passed. Corrected role bindings let the regression
  test reach source admission; its edited fixture source was rejected.
- **1 passed** in 22.6 seconds:
  `tests/episode_runtime/records/test_refinement_regression.py`. The fixture now
  preserves the exact host-owned declaration suffix when editing source and
  binds each new child assignment to the current candidate. Admission rules were
  not relaxed. A subsequent extraction of failure-report formatting into a test
  helper did not change the passing path; the subsequent checker-integration
  invocation above reran it successfully.

The admitted-regression check builds the approved target/refiner, admits a
Designer and three Implementer assignments, admits their candidate revisions,
and measures each through the common experiment service. Real observation
admission detects the opposing result cycle: pass/fail, fail/pass, pass/fail.
The parent's shared history preserves all three candidates, child identities and
original outcomes; the default context includes unresolved conflicts. History
queries run with full campaign enumeration and Run audit reconstruction disabled
by the test. The scope/projection checks additionally verify child filtering and
that newer resolved incidents do not displace unresolved conflicts.

Recording discovery checks establish exact-prefix and invocation filtering,
callable inventory requests, pagination, private-content exclusion, and visible
missing-source limitations. These views use the existing indexes and stores;
there is no new record database or replay mechanism.

Limits: the regression check drives host APIs directly and supplies target
outputs through the existing result-only executor. The source edits are fixture
revisions, not demonstrated behavioral repairs. This verifies admission and the
shared record interface, not model reasoning, stock-refiner autonomous paging,
real checker acquisition, native confinement, or coherent recovery. Task 2 is
complete at that interface scope. Tasks **1, 3, 4 and 5** remain open.

### Parallel integration checks: incomplete, 2026-10-03

Both implementation agents paused Python edits during these checks. The
canonical `scripts/run_tests.sh` runner used the isolated test interpreter and
`--file-retries 0 --tb=short`.

- `tests/episode_runtime/testing/test_refinement_experiments.py`: **1 passed,
  1 failed** in 26.6 seconds. The direct target-output case passed. The
  independent-checker case failed while building its fixture, before checker
  execution: `root_launch_payload_not_empty`. The Builder requires an empty
  root request contract, while the proposed checker fixture declared a target
  answer as a root input. This is not evidence that checker execution works.
- `tests/episode_runtime/records/test_execution_history.py`,
  `tests/episode_runtime/records/test_run_records.py`, and
  `tests/iterative_episode_refiner/test_reports.py`: **10 passed, 1 failed**
  across three files in 10.9 seconds. The new recording-discovery test passed
  an `OpaqueId` object to `save_recording`, whose existing API expects its string
  value, and failed before reaching its assertions. The other history, inventory
  and scoped report checks passed.

The passing direct refiner case uses generated refiner code and authenticated
supplied model responses. Target returns are supplied; the proposed checker
case computes its oracle in the fixture executor rather than executing generated
checker code. Neither establishes live reasoning or native confinement. The
report tests seed campaign records and establish projections, not an admitted
cross-child repair cycle. The complete goal and all five remaining tasks are
still open. Later edits require their own verification.

### Actual nested refiner baseline and shared history, 2026-10-03

Canonical runner, retries disabled: **9 passed across 4 files** in 128.7 seconds:
`tests/episode_runtime/testing/test_refinement_execution.py`,
`tests/episode_runtime/testing/test_scoped_execution.py`,
`tests/episode_runtime/records/test_execution_history.py`, and
`tests/iterative_episode_refiner/test_reports.py`.
Ruff on this change's code and `git diff --check` passed.
A separate canonical run passed **2 tests across 2 files** in 23.9 seconds:
`tests/episode_runtime/testing/test_worker_access.py` and
`tests/episode_runtime/test_staged_closure_imports.py`. These retain their stated
transport/import scope; they are not a native confined refiner demonstration.

The new refiner check builds an approved target and the complete fixed refiner
workflow through the real Builder, prepares a campaign from the published
materialization handoff, and executes generated Parts and Verify Episodes.
It uses the shared Run dispatch, actual method loop, protocol-framed requests,
production host-exchange function, actual campaign admission, and shared history.
No campaign index, observation, or host credit is pre-filled for this check.

The verifier's static passes reach Parts' next model context with the original
candidate and evidence references. Missing behavioral coverage remains an
explicit decision, not a verified build. A supplied invalid model proposal is
authenticated against the active Run's committed response, rejected, and earns
zero realized yield. The test caller cancels at the next model request; the Run,
refiner result and shared execution history all retain cancellation. This is
neither numerical completion nor continuation/recovery coverage.

The actual path first failed at these integration defects, fixed before the
passing run:

- Plain reference data with a `schema_id` was mistaken for a typed envelope.
- Shared dispatch rejected a campaign naming a separately approved refiner in
  another Duet. Dispatch and history now verify the exact linked approval/build
  or Run registration; unrelated target data and changed builds are refused.
- The `call` response field collided with the host method's Python argument.
- An unresolved source constructed an unsupported `SourceEnd("incomplete")`.
  It now exhausts normally while retaining the host's unresolved disposition.
- Proposal authentication required terminal audit evidence while its own Run
  was still active. It now uses the existing verified committed-prefix reader;
  final candidate acceptance still requires terminal execution evidence.

Limits: Builder and runtime model responses are supplied; generated code runs
in-process using the existing integration fixture with supplied confinement
attestation. This does not prove native worker confinement, live reasoning,
successful implementation repair, or complete common experiment-spec support.
Refiner evaluation requests still need the shared experiment-spec/measurement
adapters. All five remaining task IDs (1, 2, 4, 5, 6) remain open.

### First-unit selection through the shared interface, 2026-10-03

Canonical runner, retries disabled: **4 passed across 4 files** in 155.5 seconds:
`test_unit_execution.py`, `test_scoped_execution.py`, `test_worker_access.py`, and
`test_testing_episode.py` under `tests/episode_runtime/testing/`.

The unit check executes generated nested Episodes through the common experiment
service, linker, method loop and Run store. It obtains an exact unit boundary
with `openchia test boundary --unit-id`, runs only the entry's first unit,
and checks the actual committed events. A parent unit runs its declared children
while its own controller still says to continue; no parent Episode completion
or final result is published. A later-unit request and a changed unit label are
refused before dispatch. Repeating the same experiment launches no new Run.

The expanded check also builds an approved testing contract and verifies its
host-session boundary operation returns the same references as the CLI. The
reuse grant covers only the selected recording prefix, not the whole Run.
Supplying both an Episode ID and a unit ID is rejected. Recorded execution of
the selected leaf exposes its Run-dependent prompt mismatch as invalid, reuses
no response, and makes no live model call.

The expanded rerun initially had **one failure and one collection error** in
the added fixture: missing required environment conditions and an imported
function accidentally collected as a test. Both were corrected. The final
focused rerun passed **1 test** in 121.6 seconds. Experiment-planning checks
(2 tests) and staged-worker imports (1 test) passed in the preceding run.
Ruff on the changed code and `git diff --check` passed.

Limits: model outputs and confinement attestation are fixtures. The access
check constructs a real approved host session but supplies its caller-start
event; it does not execute a testing Episode making the new unit-selection
request through a confined worker. Existing worker-access coverage exercises
the common channel with other operations. This receipt establishes neither
live reasoning nor OS confinement, later-unit restoration, complete refiner
integration, or goal completion.

### Indexed refinement history, 2026-10-03

Canonical runner, retries disabled: **9 passed across 4 files** in 30.4 seconds:
`tests/iterative_episode_refiner/test_reports.py` (4),
`tests/episode_runtime/records/test_execution_history.py` (3),
`tests/episode_runtime/testing/test_worker_access.py` (1), and
`tests/episode_runtime/testing/test_measurements.py` (1).
Ruff on the changed history, runtime-context, CLI and report-test files passed;
`git diff --check` passed.

Real-store history checks refuse full campaign enumeration and audit reads.
They page admitted index entries through `ExperimentService.history`, the CLI,
and the host-assigned query used by refiner context. They preserve old outcomes,
reject cross-assignment cursors and changed-head pagination, and reject a
generic testing worker's attempt to select another refinement assignment.
Parents see both sides of a seeded cross-child conflict; a child receives only
its assigned requirement references and an explicit withheld-reference count.
Own/direct-child reports remain distinct from current campaign state.

The campaign index and conflict are explicitly seeded fixtures. This does not
demonstrate that a live refiner caused or repaired the regression, or that an
actual refiner worker paged its context. The existing worker-access check covers
the generic testing transport with supplied target output, not that refiner
execution. No live reasoning, confinement or complete Task 2 claim follows.

After including the moved outcome schema and its base record model in the
existing frozen measurement-implementation identity, and rejecting unstructured
refiner history queries, the final focused canonical rerun passed **6 tests
across 3 files** in 14.0 seconds: the four report/history checks,
`test_measurements.py`, and `test_staged_closure_imports.py`. The latter imports
the actual staged worker in an isolated Python subprocess and stops at `--help`;
it does not run a confined Episode. Ruff and `git diff --check` passed.

### Shared refiner result projection, 2026-10-03

Canonical runner, retries disabled: **6 passed across 3 files** in 12.8 seconds:
`tests/iterative_episode_refiner/test_reports.py` (2),
`tests/episode_runtime/records/test_run_records.py` (3), and
`tests/episode_runtime/testing/test_measurements.py` (1).
Ruff on the changed report, shared-outcome and predicate-consumer files passed;
`git diff --check` passed.

The report checks use actual DuetStore/CampaignView reads and typed stored
records. They explicitly seed the campaign index: they test read-only reporting,
not campaign admission or execution. Parent and child projections retain the
same original expected/observed result and tested candidate. The current view
can be stale or contradicted while the historical outcome remains a pass;
missing current evidence remains unresolved and does not delete history.
Unrelated sibling observations are absent from child context. Experimental
measurements use the same outcome schema, and their existing independent-value
comparison checks still pass.

This completes the tested result-field projection within work item 2, not item 2
as a whole. Shared indexed refinement-result/regression discovery, complete
refiner experiment submission, remaining scopes/adapters, coherent nested
continuation, and live acceptance remain unverified or unfinished. No live model,
candidate execution, confinement, or new credit-admission claim follows from
these six checks.

### Development verification, 2026-10-02

`scripts/run_tests.sh tests/episode_runtime/testing/test_experiment_planning.py
--file-retries 0`: **2 passed**. Uses actual approval, Builder admission,
BuildStore and DuetStore; includes the installed command dispatcher and exact
scope/identity checks. Builder replies are deterministic fixtures. No confined
candidate execution or live model reasoning is demonstrated by this result.

Lint passed for the new testing package/CLI/tests and the touched refiner
evidence reader and CLI dispatcher. `git diff --check` passed.

The compatibility probe also ran `test_campaign_state.py` and
`test_control_integrity.py`: **5 passed, 4 fixture-setup errors**. Their unchanged
`CampaignFixture` creates check records without the required `evidence_kind`
field. They fail before reaching the extracted shared reference reader. These
draft refiner tests are not a passing validation receipt; their fixtures and
behavioral coverage must be brought into the unified acceptance work. No
production admission check was weakened to make them pass.

### Shared dispatch and launch setup verification, 2026-10-02

The canonical runner passed **7 targeted checks** across
`testing/test_experiment_planning.py`, `testing/test_shared_execution.py`,
`test_model_request_thaw.py`, and `test_executor_http_loop.py`. They exercise
actual approval, BuildStore/DuetStore/RunStore and request/response recording,
reject an unapproved recursive model path, and preserve an interrupted dispatch
without relaunch. The dispatch fixture intentionally fails before execution;
the HTTP fixture uses a protocol-speaking subprocess with inert attestation and
a canned network response. These are not live reasoning/confinement proofs.

`tests/openchia_cli/test_episode_launch_setup.py`: **2 passed**. Uses actual
files, the ordinary launch resolver and structured CLI. A→B→A project resolution
retains distinct credentials and model settings without changing `os.environ`;
public outputs contain no test credential values, existing setups are preserved,
and POSIX directory/file permissions are checked. No model service is contacted.

Live confined execution remains unverified. A current read-only resource probe
fails with `RunExecutionError: cannot read host cpu.max`: the process's reported
cgroup has no visible `cpu.max` file. Running the same probe in a fresh transient
user-systemd unit has the same failure. No confinement check was bypassed and no
host configuration was changed to produce a green receipt. This does not block
the remaining harness implementation work.

### Recorded and numerical modes verification, 2026-10-03

Canonical runner: **120 passed across 10 files** (`tests/episode_runtime/testing/`,
`test_staged_closure_imports.py`, `test_http_broker.py`, `test_http_protocol.py`,
`test_model_request_thaw.py`, `test_executor_http_loop.py`, and
`tests/openchia_cli/test_episode_launch_setup.py`). No retries were enabled.

`test_recorded_execution.py` exercises the shared dispatch service, real brokers,
protocol frames and stores. It saves a recording through the CLI, removes the
live credential, reuses matching responses, preserves their provenance, rejects
changed requests/environment/child paths, and distinguishes a new live call from
saved root inputs. The executor fixture only exchanges messages and interrupts;
it does not run Target Workflow code. The model transport is canned, and the HTTP
response is a real policy denial rather than a live network response.

`test_numerical_execution.py` runs actual learning-ledger commits against an
approved build: zero-yield failure, an admitted lesson, and a duplicate. The CLI
recomputes and compares their numerical history using the existing controller,
returns the same persisted result on repetition, and leaves the source journal
unchanged. An exact invocation selection works; a wrong invocation and an empty
committed prefix are refused. The source Run remains `interrupted`. Its executor
uses inert attestation and does not execute generated Episode code. This proves
the numerical/evidence path, not live reasoning or confinement.

The shared dispatch check also rejects a caller-supplied recorded broker before
publishing a dispatch, preventing reused HTTP responses from being mislabeled
as a live-mode experiment. Its focused two-test file passed after that guard
was added. These checks are not substitutes for the full goal's live acceptance
requirements. Narrower code execution, worker access, measurement/acceptance,
cross-child regression and coherent recovery still require implementation and
their own truthful receipts.

Final focused rerun: **8 passed across all 5 harness test files**. This includes
an interruption between the terminal journal event and terminal-artifact
publication. The existing `RunStore.complete_terminal_publication` completes
that publication idempotently; the saved recording identity stays unchanged
while evidence availability becomes true. The source remains interrupted, not
successfully completed. This is publication recovery, not nested execution
continuation. Ruff and `git diff --check` also passed.

### Measurement and comparison verification, 2026-10-03

The canonical runner passed **122 checks across 12 files**, with retries disabled:
all six files in `tests/episode_runtime/testing/`, the staged-closure, HTTP broker,
HTTP protocol, model-request recording and executor HTTP-loop files listed above,
and launch setup. Ruff and `git diff --check` passed.

`test_measurements.py` uses the independent scheduling enumerator to supply a
reference optimum, then exercises CLI criterion registration, the shared service,
RunStore evidence, typed measurement, `results`, and `compare`. Correct, incorrect,
and wrong-type control values are distinguished. Changed prediction text cannot
weaken a criterion. Interrupted execution and a mismatched environment cannot
produce a pass. A stale implementation identity is refused. Repeated requests
reuse the same measurement without another execution or progress admission.

**Evidence limit:** its executor publishes supplied typed results using inert
attestation; it does not execute the candidate or call a model. The exhaustive
solver supplies reference data, not an Episode-produced answer. This receipt
validates the measurement/comparison path, not the required demonstration that
a real testing Episode finds a broken candidate, observes a repair, and chooses
a justified follow-up through the confined host/worker service. That demonstration,
worker access, remaining scopes, campaign measurement/report integration and
coherent nested continuation remain unfinished.

### Testing access and Episode-loop verification, 2026-10-03

The canonical runner completed **241 passed, 3 skipped across 32 files**, with
retries disabled: `tests/episode_runtime`, `tests/episode_builder`, and
`tests/openchia_cli/test_episode_launch_setup.py`. Ruff and `git diff --check`
passed. The skips include confined/live execution; this is not a live acceptance
receipt. Older runtime tests needed relative-import corrections and one missing
required HTTP-broker argument to exercise their unchanged assertions under the
canonical runner.

`test_worker_access.py` exercises actual host/worker protocol pipes and the shared
experiment service. Exact approval is preserved; changed criteria and unassigned
result access are rejected. Launch attestation is inert and target output is
supplied. It proves transport/access behavior, not confinement.

`test_testing_episode.py` materializes the new library reference and executes its
real linked Episode loop with scripted model responses. The shared harness measures
a supplied incorrect scheduling minimum against an independently enumerated optimum.
The Episode requests that experiment, sees the measured failure and selects a
follow-up inspection. An invented pass is rejected for zero credit; an exact
measured-failure finding is admitted. Rewording the question and prediction launches
a new experiment but earns no duplicate finding. Repeated inspection also earns
zero credit. The existing controller, not the script, resolves continuation, and
the final result preserves the candidate failure without granting parent acceptance.

This mechanical loop fixture explicitly uses a continuation threshold of **0.5**;
the reference Episode still ships **0.01**. No duration or call-count claim for
the default configuration follows from this receipt. Target outputs and model
decisions are fixtures; the test does not prove that a live model designed the
experiment or solved the scheduling problem. Normal conversational testing setup,
remaining execution scopes, full campaign/parent integration, coherent nested
recovery, and the goal's live acceptance demonstrations remain required.

### Selected-invocation execution verification, 2026-10-03

`test_scoped_execution.py` materializes and runs an actual generated
root → group → leaf workflow, then uses the shared CLI/service to run only the
leaf and only the group-with-leaf. The committed invocation records contain
exactly the selected Episodes, with the original ancestry retained. Saved goal
view tampering and omission of an executable child are rejected before dispatch.
The shared path check rejects requests addressing an omitted ancestor. A boundary
can be captured from a selected Run without inventing parent execution events.

The same check refuses whole-workflow playback from a narrower recording.
Recorded execution of the reasoning leaf explicitly diverges because its prompt
contains new invocation-local learning identities: no response is reused and no
live model call occurs. This is rejection evidence, not a claim that these
Run-specific prompts can be replayed successfully.

The compatibility run over `tests/episode_runtime`, `tests/episode_builder`,
`tests/method_loop`, and launch setup produced **244 passed, 3 skipped**, and one
failure in the new in-process replay fixture. After preserving the host broker's
error independently of the worker adapter's exception wrapping, the focused
canonical rerun of `test_scoped_execution.py` and `test_experiment_planning.py`
passed **3 checks**, with retries disabled. Ruff and `git diff --check` passed.

These executions use real generated source, typed handoffs, host learning,
brokers and durable stores, but a scripted external model and inert execution
attestation. They do not prove model reasoning, independently correct task
answers, or process confinement. The loop fixture uses an explicit **0.9**
continuation threshold, not the reference's **0.01**. Changed shared-state
restoration, component/unit/refinement scopes, recorded child substitution,
normal conversational testing setup and live acceptance remain unfinished.

### Ordinary-host testing launch verification, 2026-10-03

The canonical runner passed **253 checks, with 3 skips across 36 files**, with
retries disabled: the complete runtime, builder and method-loop directories,
launch setup, OpenChia CLI command checks, and the new
`tests/agent/test_episode_testing_launch.py`. Ruff and `git diff --check` passed.
The skips still include live/confined execution; this is not its acceptance
receipt.

The new check uses two ordinary `OpenChiaHost` Duets in one isolated workspace.
It configures `/launch` through the existing host method, submits real
Architectures, requires human approval, and builds actual source. The testing
workflow's ordinary `/run` enters the shared dispatcher, receives its scoped
testing session, executes the target's generated Episode through that same
dispatcher, and measures its result. The testing Episode observes a pass and
selects a follow-up inspection. The final measurement retains
`acceptance.admitted: false`; the outer ordinary Run remains unmeasured as a
candidate. An unapproved launch and a replaced configuration hash are refused.

The target criterion in this check concerns **host-governed completion**, not
the correctness of a reasoning answer. Model decisions are scripted and execution
attestation is inert. Both loops use an explicit **0.9** continuation threshold.
Thus this proves the normal approval/build/launch connection and nested service
integration, not live reasoning, independent task correctness, default-threshold
performance or operating-system confinement.

The earlier empty-capability/ordinary-launch gap is now closed for explicitly
approved testing contracts. Full component/unit/refinement scopes, campaign
measurement and parent-report integration, coherent recovery, HTTP credential
setup, and the goal's live acceptance demonstrations remain required.

### Registered-component execution verification, 2026-10-03

Final canonical verification: **255 passed, 3 skipped across 37 files**, with
retries disabled, covering `tests/episode_runtime`, `tests/episode_builder`,
`tests/method_loop`, the ordinary-host testing launch, launch setup and CLI
command checks. Ruff and `git diff --check` passed. The initial compatibility
run exposed the missing staged module and the old component-boundary fixture;
both were corrected before this final run.

`tests/episode_runtime/testing/test_component_execution.py` uses the common
experiment service, actual admitted generated module design, registered
functions, worker linker, protocol frames, host return validation, and existing
stores. It selects a function owned by the middle node of a root → group → leaf
workflow. The actual continuation function is exercised on both sides of its
frozen threshold, and the actual result schema is exercised with malformed
input. The registered measurement distinguishes the observed outcomes.

The recorded evidence contains one component observation and no Episode/unit
execution or learning events. Repeated experiment requests return the existing
evidence without a second dispatch. Saved-input and recorded-mode reruns preserve
the exact call; changed recorded inputs, replacement controller parameters,
out-of-scope child addresses, and a fabricated Episode-completion field are
rejected. These pure functions make no external calls, so this receipt does not
claim external-response playback was exercised by them.

The staging check now launches the real bootstrap's help path in a separate
isolated Python process with the verified runtime package and standard library
only. It caught missing worker-scope modules, which were added to the existing
runtime manifest. This is a real import check, not a source-text pattern check;
it still stops before installing OS confinement or executing a Run.

The component behavioral checks use the existing in-process executor fixture
and inert confinement attestation. The numerical fixture's binding is **0.9**,
not the reference default **0.01**; expected decisions are derived from the
actual frozen binding. This receipt is not live reasoning acceptance or proof
of native confinement. Additional typed component adapters, declared-unit and
refinement-job execution, campaign/parent-report integration, coherent nested
continuation, HTTP credential setup and live acceptance remain unfinished.

### Shared record-storage consolidation, 2026-10-03

The canonical runner passed **15 tests across 11 files**, retries disabled:
`tests/episode_runtime/testing` and
`tests/agent/test_episode_testing_launch.py`. Ruff and `git diff --check` passed.
These are the existing integration checks of actual stores, approval/build,
shared dispatch, measurement, numerical and recorded modes, worker access and
linked Episode execution. Their scripted/inert execution limits described above
still apply; no new live acceptance claim is made.

Lifecycle record names, identity keys, envelopes and digest checks now have one
owner (then `episode_runtime/testing/records.py`, now
`episode_runtime/records/experiments.py`). Dispatch transactions continue to
use the existing atomic artifact/event publication; all existing record IDs and
hash conventions are retained. The old reference module and scattered storage
helpers were moved, with consumers updated rather than compatibility aliases.
The current guide is now separate from these historical receipts.

This verifies storage consolidation, not the complete shared record interface.
Maintained high-level views/indexes, browsing past tests and replay availability,
shared refiner result projections and coherent nested continuation are still
unfinished. The uncompleted unit-scope work has no direct acceptance coverage
from this run.

### Maintained Run records and indexed discovery, 2026-10-03

The canonical runner passed **257 tests, 3 skipped across 38 files**, retries
disabled: `tests/episode_runtime`, `tests/episode_builder`, `tests/method_loop`,
`tests/agent/test_episode_testing_launch.py`, and the launch setup and CLI command
checks. This includes the new Run record checks and history consumers. After
adding per-experiment recording pagination, a focused canonical run passed
**3 tests across 3 files**: `test_measurements.py`, `test_worker_access.py` and
`test_numerical_execution.py`. Ruff on the changed record/history files and
`git diff --check` passed. The first focused run failed because the supplied-result
fixture omitted the required `episode_id=None` on its added Run-start event;
this was corrected before the passing focused run.

RunStore now maintains a compact typed record as registration, events and
terminal evidence commit. Tests inject interrupted view publication after the
authoritative event is durable, verify that inspection reports the stale prefix,
and rebuild the derived view without changing execution evidence or status.
An interruption remains an interruption. Missing terminal-evidence publication
remains visible rather than being treated as successful completion.

CLI and approved worker history use the same indexed catalog. Tests browse
experiments, measured pass/fail/error outcomes and exact recording references
while full Run audit reads are deliberately forbidden. Saved recording pages
have callable next-page queries; cursors from another experiment and requests
from another owner are rejected. The real protocol subprocess checks that a
later invocation cannot list the earlier invocation's experiments or recording
selectors, while its own authorized experiment remains discoverable.

These checks establish record publication, bounded discovery, ownership and
CLI/worker integration. Supplied results and inert confinement attestation are
still used where documented in those fixtures. They do not demonstrate a live
model solving the scheduling problem or native confinement. Full invocation/unit
inventories, common refiner results/history, coherent nested continuation and
the remaining acceptance demonstrations are still unfinished.
