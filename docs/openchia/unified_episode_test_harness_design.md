# Unified Episode testing harness: implementation map

Status: active implementation. This is not an acceptance receipt. The complete
[goal](unified_episode_test_harness_goal.md) remains the completion contract.

**Build ownership correction (2026-10-03):** the user explicitly requires
OpenChia to own build → refine → validate after one start. This supersedes the
goal file's earlier normal-build activation restriction; see
[ADR 0007](../adr/0007-build-owns-iterative-finalization.md). `start_build`
now hands either a partial failed build or a materialized build to the existing
refiner through `ExperimentService`. The same job owns cancellation, and only
the host's verified-build result permits success. This integration is work
toward Task 4, not a replacement for its live repair/acceptance requirement.
Historical checkpoint statements below describe the code and evidence then.

Normal-build measurement preparation now has a frozen source grant as well as
the Builder's static checks. `function_library/refinement_grounding.py` uses the
existing `FunctionLibrary` to register exact requirement-grounding functions;
`iterative_episode_refiner/measure_preparation.py` projects their evidence into
the existing grounded-case schema before the campaign is frozen. Sources receive
the original approved workflow and requirement, never candidate answers. The
Measure child selects cases in its existing `measure_grounding` context and
uses the existing proposal/admission/control path. Availability alone installs
no check and earns no credit. There is no additional runner or replay interface.

The initial source covers only the exact seven-job scheduling goal, using the
independent solver in `function_library/scheduling_benchmark.py`. A changed goal,
environment or unsupported routing yields no match. Other requirements stay
unresolved. This does not replace independent checker construction for unfamiliar
tasks, make static checks behavioral, or prove the full normal-build cycle.
Parent acceptance of newly admitted measures and remaining requirement coverage
are still unfinished parts of that cycle.

**Terminology and execution decision (2026-10-03):** the workflow being built,
refined and tested is the **Target Workflow**; `candidate_ref` identifies an
exact candidate revision. The refiner is separate.
[ADR 0005](../adr/0005-target-workflow-execution-backends.md) supports container
and systemd execution, with containers as the default and no silent fallback.
The default change is pending. [ADR 0006](../adr/0006-support-systemd-255.md)
adds systemd 255 support. The approved AppArmor setup now works; native service,
reasoning-worker, single-Episode and nested-refiner continuation checks pass.
Installation and doctor check actual namespace setup; see the
[systemd setup guide](systemd_setup.md).
The [receipt log](unified_episode_test_harness_receipts.md) preserves both the
earlier failures and the successful focused checks. The compatibility and setup
changes belong to the PR #33 checkpoint; see the
[checkpoint](iterative_episode_refiner_checkpoint.md).

## Required launch configuration for this development session

User-designated on 2026-10-03:
`/home/chia/repos/OpenChia-iterative-refiner/launch_default.json`.
Use this existing file for testing the **Target Workflow**, not for
launching the IterativeEpisodeRefiner. Continue implementation in
`/home/chia/repos/OpenChia`; the configuration's location does not move the
working checkout. Credentials remain outside the repo. The committed launch
support has been integrated here, but this session still selects the original
user-designated file above.

Before a live Target Workflow test, load this configuration with `/launch load` and
check `/launch preview`; the human must approve its exact hash with
`/launch approve HASH`. Resolve its target model routes through the existing
launch path; do not invent replacement settings or silently use the
conversational model. Its Builder slots do not authorize using it to build
or run the refiner itself. The IterativeEpisodeRefiner uses the Duet's
model/provider configuration for its own reasoning and reasoning children, not
a separate refiner launch file. When the
refiner requests a Target Workflow test, the Target Workflow Run uses the Target Workflow launch
configuration; this must not change the model configuration of the Duet or
the refiner. Target readiness is not proof of refiner readiness.
The [canonical routing contract](episode_launch_configuration.md#duet-refiner-and-target-model-boundary)
defines this boundary. `OpenChiaHost.refinement_experiment_service` now binds
the owning Duet's concrete route for refiner-job experiments. Supplied-agent,
local-provider integration coverage verifies separation from target routing;
fully initialized conversational-agent and live-model acceptance remain unverified.
Native nested execution now passes with supplied model decisions.
If the configuration cannot be resolved, stop at that boundary and report why.
File existence alone does not establish readiness. Earlier scripted fixtures
remain mechanical checks, not evidence of live Episode building or reasoning.

## Shared Run and test records

### Task status

Task **4** remains. Tasks 1, 2, 3 and the compatibility/documentation checkpoint
in task 5 are complete at the scopes described below. Live model-directed testing
and actual repair are not established; the overall goal remains open. IDs are
retained for tracking. Task 4's eventual result must be added to the same receipts.

- **Task 1: Finish connecting the refiner's tests to the shared harness — complete.** Direct
  target-output checks now use an Episode-proposed experiment specification and
  the common experiment service. Independently built checking Episodes now
  execute through that service and return measured outcomes to the parent;
  verification uses supplied target answers and in-process execution, not live
  reasoning or confinement. Grounded measure-control experiments now use the
  same service and are verified with an actual deterministic checker: partial
  evidence earns only distinct admitted facts; full measure admission still
  requires all controls. Refiner-job experiments now use the common specification
  and exact owning-Duet model binding. A focused integration check passed with
  actual generated refiner code and a local deterministic HTTP provider; its
  supplied agent binding and in-process executor are not live reasoning or
  confinement proof. Refiner numerical replay now passed its shared-service
  integration check: exact committed decisions are recomputed without model calls
  or campaign mutations. Its negative snapshot-decoder check also passes after
  correcting the fixture's opaque result ID. Scope and
  numerical-replay support are part of this task, not separate runners or tasks.
  First-unit selection is connected. Later-unit stock reasoning execution and
  numerical replay of its inherited history pass in-process checks, including
  preparation-boundary rejection of a forged admission receipt and explicit
  preview provenance. Arbitrary sources and historical refiner-state forks remain
  unsupported; task 3's same-execution continuation does not supply those new
  experiments. These unsupported extensions are not additional required tasks.
  Checks of editable instruments and approved reference workflows now also
  require Episode-authored experiments through the same adapter; their direct
  execution fallback is removed. Both source cases pass integration checks,
  including exact source/criterion binding, shared measured return, authorized
  worker inventory/report queries, numerical reuse and explicit recorded-request
  divergence without live fallback. Native proof and compatibility are recorded
  separately under tasks 3 and 5; live acceptance remains task 4.
- **Task 2: Shared access to Run and test records — complete.** Indexed history,
  exact-prefix recording previews, executable inventory queries, scoped original
  outcomes and unresolved-conflict context are implemented. A test drives actual
  source-change, experiment and observation admission across three child
  assignments; the parent sees the opposing result cycle without reading the
  Run audit. Execution outputs in this test are supplied, not derived from the
  edited source. Live reasoning and autonomous repair are not claimed.
- **Task 3: Finish resuming interrupted nested work — complete.** Saved-input
  execution is not its substitute. The shared journal
  now records all five exchange channels, with replies committed before worker
  publication. Refiner replies also retain host-only active/prepared call state,
  open-unit references and the exact campaign head. A common reconstruction
  verifier now matches all five channels and nested boundaries in global order,
  rejects divergence or incomplete exchanges, and stops at the saved boundary
  without authorizing live work. Its eight mechanical checks pass. Host session
  restoration now reads only the committed journal, restores admitted calls and
  prepared children without repeating campaign mutations, and rejects a changed
  campaign head. Three checks cover prepared-child, open-child-unit and closed
  child-unit boundaries. The existing executor now has a host reconstruction
  gate, with current-authority and stopped-worker checks before new work. Its
  shared continuation admission checks pass. The service and CLI now expose
  exact-reference continuation; the CLI and continued-history checks pass.
  The nested-return comparison now passes through the common experiment service
  and actual systemd workers, replacing the loopback driver. It interrupts after
  Implementer's committed final unit reply, verifies the old worker is stopped,
  reconstructs waiting parents under current authority, and accepts the child
  return once. Resumed and uninterrupted results match disposition, normalized
  controller history and operation counts. Repeating the continuation request
  does not repeat calls, edits, target checks or credit. The final native check
  passed in 844.7 seconds; earlier failures and their fixes remain in the receipts.
  Model decisions and target observations are supplied, and the source edit is
  a comment: this is native continuation proof, not live reasoning or repair.
  Native single-Episode continuation also passes. The container backend still
  has no installed runtime on this host.
- **Task 4: Demonstrate the complete system on a real reasoning problem.** Live model-directed,
  independently checked acceptance remains open. The human approved the scheduling
  target and launch. Its first real Builder call completed, but the plan was
  blocked by an invalid generated-function identifier and unresolved credit
  channels. The saved prompt confirms missing reference implementation context.
  The failed materialization handoff is retained; no Target Workflow Run or
  autonomous repair has occurred. See the latest receipt and setup record.
- **Task 5: Check compatibility and finish documentation — checkpoint complete.**
  PR #34 is merged and its explicit approved model-slot APIs are integrated.
  The latest 64-file check returned 343 passed, one test-specific timeout and
  two skips. The affected reasoning fixture then passed both cases after removing
  its duplicate operational timeout, without changing its numerical controller.
  The six-file rerun returned nine passes and a nested-test assertion failure;
  correcting that test's distinction between prelaunch, startup and reconstruction
  produced the final native nested pass above. These are separate receipts, not
  a claim that the full batch was rerun green. Installer/doctor checks passed
  21 tests, including the actual namespace probe. The docs record the supported
  scope, model-routing boundary, setup, commands, code map and limitations.
  Earlier failures are retained in the receipt log. This checkpoint saves the
  current work to existing PR #33; the PR stays draft pending task 4. There is
  no live-model acceptance claim and no normal-build refiner activation.

### Record ownership

Running, inspecting and replaying an Episode must use the same records. A shared
executor alone does not satisfy this requirement. Neither an Episode nor a human
should need to find scattered artifacts, reorganize them, read implementation
files, or replay the audit to discover what happened and what can be tried next.

The shared record package is `episode_runtime/records/`, below both ordinary
execution and testing/replay. Its `experiments.py` owns lifecycle record names, identity
keys, store envelopes and digest verification, including the access grants used
by worker callers. It uses the existing DuetStore; dispatch still commits its
artifact and event atomically through that store. Existing IDs and evidence are
preserved. Domain modules retain their body validation and judgment rules.
`runs.py` and `facts.py` define compact typed Run/event facts; `index.py` maintains
them transactionally at source commit; `catalog.py` serves bounded history and
experiment overviews; `inventory.py` pages exact invocation/unit facts.
`outcomes.py` defines the requirement result used by experiments and refiner
reports; `refinement.py` pages admitted observations, reports and conflicts from
the existing campaign index. Refiner execution is connected to this interface;
native nested continuation is verified with supplied decisions; live-refinement
verification remains unfinished.

The record system must distinguish these linked facts without asking callers to
assemble them:

| Record/view | Required high-level information |
| --- | --- |
| Execution | Exact code/build, inputs and starting state, environment/configuration, authority, selected scope, parent/child identities, mode, status and evidence references |
| Experiment | Question and rationale, assigned requirements/measures, expected and falsifying outcomes, candidate identity, linked executions and previous experiments |
| Result | Expected versus observed requirement outcomes, limitations, unresolved questions, comparisons/regressions, and separate acceptance/progress decisions |
| Reusable state | Exact recording prefix or coherent checkpoint, covered invocations/units, available observations/responses, missing data, supported operations and compatibility requirements |

High-level views must be maintained as their source facts commit, with indexed
lookup by owner, candidate, requirement, experiment, execution and parent. They
must name the committed source revision/prefix they describe. Interrupted
publication must be visibly incomplete, not a stale view presented as current.
Normal history, status and replay-discovery queries must not rescan and decode
the full Run journal. Detailed audit verification and evidence retrieval remain
explicit drill-down operations. No second copy of the raw audit is introduced.

Typed machine records are canonical. Human tables/text and bounded Episode
context are deterministic projections of those records, not LLM summaries or
independently maintained alternatives. Read access does not grant execution or
replay authority. Secrets and unrelated child histories stay outside default
views. Changing a candidate, criterion, input or control creates a linked new
experiment, never an edited historical result.

The shared service must expose simple calls for history, an experiment's complete
high-level record, replay availability, preview, execution, results and comparison.
CLI and worker operations must delegate to these calls, with worker scope enforced
before retrieval. Discovery must expose enough information to choose a follow-up:
past outcomes and limitations, comparable regressions, exact reusable state,
supported replay scopes/modes, required inputs and actionable incompatibilities.
It reports evidence and choices; the testing Episode decides what is worth trying.
The presence of a recording alone must never be labeled replay-ready or resumable.

The history query lists past experiments, measured outcomes,
saved recording references and reuse constraints. Invocation/unit inventory is
available through the same service. Refiner parent reports and child context now
include the common expected-versus-observed result. Indexed refiner history is
available through the shared service and CLI; supplied-response execution verifies
that the generated refiner receives baseline history. The same default history
includes unresolved conflict outcomes grouped by tested candidate and child.
Coherent checkpoint continuation belongs to task 3, and live model-directed use
to task 4. A reuse lead always needs the exact experiment preview; it is not a
promise that a replay will match. New execution adapters must project their
records through these views, not introduce role-specific history formats.

Code navigation is by responsibility:

| Change | Owner |
| --- | --- |
| Record identity, persistence envelope, common reference verification | `episode_runtime/records/experiments.py` |
| Compact Run facts and incremental publication | `episode_runtime/records/runs.py`, `index.py`; `RunStore` calls the index at registration, event and evidence commit |
| Indexed invocation/unit inventory and prefix selection | `episode_runtime/records/facts.py`, `inventory.py`; one query behind `RunStore.read_inventory`, `ExperimentService.inventory`, CLI and worker requests |
| Indexed history and high-level views | `episode_runtime/records/catalog.py`; `ExperimentService.history` for both CLI and worker access |
| Assigned refinement observations, reports and conflicts | `episode_runtime/records/refinement.py`; existing campaign index and the same CLI/service history operation; refiner context binds the host-selected invocation |
| Request shape and caller-visible vocabulary | `schema.py`, `contracts.py` |
| Scope, inputs and dependency resolution | `planning.py`, `boundaries.py`, `components.py`, `inputs.py` |
| Saved learning for a new later-unit experiment | `episode_runtime/learning_baseline.py`; source admission in `testing/reconstruction_source.py`, existing ledger/store validation and linker unit acquisition |
| Experiment lifecycle and shared Run dispatch | `service.py`, `execution.py` |
| Recording interpretation and replay semantics | `recordings.py`, `playback.py`, `numerical.py` |
| Typed requirement outcomes shared with refinement | `episode_runtime/records/outcomes.py`; refiner `reports.check_result` projects existing observations into that format |
| Measures and comparison | `criteria.py`, `measurements.py`, `judgments.py`, `comparison.py` |
| Worker access and CLI rendering | `session.py`, `openchia_cli/episode_test_command.py` |
| Exact human launch approval shared by Duet and harness | `agent/episode_launch_host.py::resolve_approved_launch`; setup and registration do not mint approval |

The existing BuildStore owns admitted source; RunStore owns runtime audit and
terminal evidence; DuetStore owns experiment records and references. These are
storage authorities, not three competing interfaces the caller must understand.
Historical test receipts live in the [receipt log](unified_episode_test_harness_receipts.md),
not among the current operating instructions below.

### Inspect history and reusable state

```bash
openchia test history --duet-store /path/to/duet.db --duet-id DUET_ID \
  --run-store /path/to/run-store --limit 20
openchia test history --duet-store /path/to/duet.db --duet-id DUET_ID \
  --run-store /path/to/run-store --limit 20 --after NEXT_CURSOR
openchia test history --duet-store /path/to/duet.db --duet-id DUET_ID \
  --run-store /path/to/run-store --experiment-id EXPERIMENT_ID --limit 20
openchia test history --duet-store /path/to/duet.db --duet-id DUET_ID \
  --run-store /path/to/run-store --kind executions --limit 20
openchia test run-record --run-store /path/to/run-store --run-id RUN_ID
```

The testing Episode calls the same history service using
`{"operation":"history","payload":{"query":{"limit":20}}}`. Pass the returned
`next_query` unchanged as the next `payload.query`; a null value ends that page
sequence. Set `query.experiment_id` to
page one experiment's saved recording selectors; each nested recording list
supplies its exact `query` and, when needed, `next_query`. An experiment's
`reports_query` selects its retained measurement reports, including earlier
interrupted attempts, using `experiment_collection: "reports"`. For recordings,
`attempt_run_id` selects an exact physical attempt; omitting it selects the latest
attempt. Pass these returned query objects unchanged to the worker's history
operation, or save them as JSON and use CLI `history --query FILE` with the same
store and owner arguments. The simpler recording selection also accepts
`--experiment-id`, `--limit` and `--after`. Do not combine `--query` with individual
history filters. A cursor cannot switch to another experiment's recordings.
Numerical comparisons do not
grant browsing rights over their source Run merely by referencing its evidence.
Worker visibility is restricted
to the current invocation's experiments and explicitly assigned recording
references. Owner filters are supplied by the host, not by the worker payload.
Sibling histories are not exposed merely because they share a candidate. Local
CLI `kind: executions` queries can inspect the selected Duet's shared executions;
that is not a worker operation. Refiner workers use their assignment-bound
history below, not arbitrary Duet execution queries.

History includes the question, rationale, exact candidate/scope/mode, expected
and observed requirement outcomes, unresolved questions, maintained execution
status, saved recording references and reuse constraints. It does not retrieve
prompts or full audit histories. Standard worker-call authority validation still
uses the existing runtime checks; this query does not bypass that boundary.
Use the row's `experiment_id` with `results --experiment-id EXPERIMENT_ID` to
inspect its measurement; `results` does not accept a measurement artifact ID.
Use `inventory` to find recorded invocations and units, `recording` for detailed
recording inspection, and a complete next experiment with `preview` before reuse.
These detailed verification operations can read the audit; history does not.

Each saved recording choice includes up to three indexed invocation previews,
its exact prefix and selection, an `inventory_request`, and, if needed, a
`next_inventory_request`. A testing worker can send these request objects as
the `inventory` payload under its existing grant. Zero explicitly selected
Episodes means `all_invocations_at_prefix`, not an empty recording. A missing
source Run leaves the selector visible with `restore_source_run`; a missing or
stale index requests explicit refresh. Neither condition triggers an audit scan
or silently labels the recording replay-ready.

### Refiner test and regression history

Use the same history command, selecting an existing campaign and assignment:

```bash
openchia test history --duet-store /absolute/path/duet.sqlite \
  --duet-id DUET_ID --run-store /absolute/path/runs \
  --kind refinement --campaign-id CAMPAIGN_ID --invocation-id INVOCATION_ID \
  --refinement-collection observations --limit 20
```

`refinement_collection` accepts `observations`, `reports`, `conflicts`, or `controls`.
Observations are restricted to the assignment's requirements. Reports include
only the assignment's own and direct children's original reports. Conflict
records expose the responsible parent and original outcomes grouped by tested
candidate and child invocation, within the assignment's requirements. Controls
show measure-validation experiments grounded in those same assigned requirements;
their outcomes do not establish target acceptance or complete measure adequacy.
Current applicability remains separate from the historical outcome. Withheld references
are counted without exposing their contents. A parent covering both requirements
can see both sides of a cross-child regression. These queries do not admit
results or grant execution. JSON queries can narrow observations/conflicts/controls by
`requirement_key`, and conflicts by `conflict_status` (`suspected`,
`decision_required`, or `resolved`). Omitted status means all retained incidents.

Every page returns the exact campaign head, current candidate and `next_query`.
Save that query as JSON and pass it unchanged:

```bash
openchia test history --duet-store /absolute/path/duet.sqlite \
  --duet-id DUET_ID --run-store /absolute/path/runs --query /absolute/path/next-query.json
```

If the campaign commits another change between pages, the query is rejected
with instructions to start a fresh history query. A cursor cannot silently
switch assignments or collections. Historical report termination and check
results remain historical; current applicability is separately identified.

Refiner context includes `context.test_history`, initially the first observation
page plus bounded `controls` and `conflicts` pages. The conflict page contains
up to three `decision_required` incidents. Newer resolved incidents cannot displace
unresolved cycles from that page. Its existing `context` operation accepts optional `test_history_query`
containing a returned query or collection/limit choices. The host binds campaign
and invocation from the actual calling assignment and rejects substitution.
This calls the same history implementation as the CLI. Generic testing workers
cannot select another refinement assignment through their ordinary `history`
operation. The host query and CLI have focused real-store coverage. An in-process
execution of the actual approved refiner verifies that baseline observations
reach its next model context; its runtime model response is supplied by the test,
so this does not demonstrate live reasoning about those observations.
An admission-backed integration check additionally establishes that opposing
child results reach these indexed views with their original candidates and
observations; its target execution outputs are supplied. The stock refiner gets
the default compact page automatically. Autonomous paging of older history by
that stock refiner has not been demonstrated; callable query access alone is not
such a demonstration.

These are two authority bindings to the same record interface: the generic
testing Episode's approved experiment access, and the refiner's current
assignment. A discovery link usable by the local host is not automatically
callable by either worker. Refiner history requests cannot replace their bound
campaign or invocation, or switch to unrestricted execution history.

`RunStore.read_run_record(run_id)` reads the same compact JSON used by `run-record`.
It shows code/build and registration identities, authority, compact scope, activity
counts, exact observed event position, terminal status and evidence reference.
It never converts an interruption into completion or claims process liveness.
This record is also maintained for ordinary and refiner Runs using RunStore.

Run views live in the existing RunStore's `records/<run_id>.sqlite3`. This is a
derived index, not an independent evidence store. It replaces the prototype's
separate compact JSON view. SQLite supplies atomic summary/fact publication and
indexed prefix/owner lookup; separate mutable files could not supply that shared
transaction. The original journal and evidence artifacts remain authoritative.
Source events commit first, and a view names its precise committed prefix. A query checks for
the next event file and evidence publication without walking the history. Its
`index_status` distinguishes `current`, `behind`, `unavailable` and
`publication_pending`. Evidence validation still reads the authoritative audit.

For an older Run without a view, or interrupted view publication, use:

```bash
openchia test run-record --run-store /path/to/run-store --run-id RUN_ID --refresh
```

This explicitly verifies source history and rebuilds the same derived view.
It does **not** execute, replay, continue, award credit, or finalize the Run.
An incomplete terminal-evidence publication remains a separate visible state.
DuetStore's indexed artifact pages provide bounded chronological lookup for
experiment, invocation-owner and recording-selector history; no new authoritative
store or duplicate raw-response log is introduced. The Run-local index holds
event identities, compact structural facts and counters—not prompt/response
bodies, request payloads, controller state or child prose. An interrupted index
transaction rolls back the summary and its new facts together. Initial index
setup precedes registration publication, so its failure cannot orphan an
unclaimed registration.

### Browse invocation and unit scopes

```bash
openchia test inventory --run-store /path/to/run-store --run-id RUN_ID
openchia test inventory --run-store /path/to/run-store --run-id RUN_ID \
  --kind units --episode-id EPISODE_ID
openchia test inventory --run-store /path/to/run-store \
  --duet-store /path/to/duet.db --duet-id DUET_ID --recording-id RECORDING_ARTIFACT_ID
```

Use `--experiment-id` in place of `--recording-id` to inspect the experiment's
execution. A numerical experiment selects only its exact input recording.
An Episode uses the same service, for example:

```json
{"operation":"inventory","payload":{"source":{"kind":"experiment","experiment_id":"EXPERIMENT_ID"},"query":{"kind":"invocations","limit":20}}}
```

For a saved recording, source is `{"kind":"recording","recording_ref":REF}`.
Workers can inspect only their owned experiments and explicitly assigned or
authorized recording references; they cannot supply an arbitrary Run ID.
The saved selector restricts both invocations and audit prefix. Query fields
cannot widen those restrictions.

After continuation, an experiment has multiple physical attempts. Inventory
without an explicit prefix returns `selection_status: "required"` and an
`attempts` list, not a silently combined history. Choose an attempt and send its
`inventory_requests.invocations` or `inventory_requests.units` unchanged as the
next `inventory` payload. These ready-to-use requests pin `query.through_event_ref`
to that attempt's exact Run/event/hash. For CLI use, save the chosen request's
`query` object in `attempt-query.json`:

```bash
openchia test inventory --experiment-id EXPERIMENT_ID \
  --duet-store /path/to/duet.db --duet-id DUET_ID \
  --run-store /path/to/run-store --query attempt-query.json
```

The result declares `coverage: "physical_attempt_only"`. A resumed attempt does
not fabricate inherited Episode starts. Its empty invocation list or local counts
are not the logical invocation's full history; use the same `episode_id` with
the advertised later-attempt unit query to inspect newly completed units.

Invocation rows include the exact path, entry evidence reference, request hash,
entry-state availability, unit/external-call counts and recorded completion facts.
Unit rows include exact `UnitRef`, label, observation reference and availability
of controller/goal observations. Counts use indexed cumulative ordinals at the
selected prefix, not reconstructed event histories. Later activity is omitted.
Missing or malformed source fields remain unavailable; they are not invented.
None of these facts proves a correct answer or host-admitted progress.

Pass a returned `next_query` unchanged for another page. For CLI use, save it as
JSON and pass `--query FILE`; alternatively use the printed `after` and
`through_event_ref` through their corresponding flags. The prefix stays fixed
even while execution continues. A stale/missing index returns no inventory and
explicitly requests `run-record --refresh`; ordinary discovery never rebuilds it.
Scope selection still needs `boundary` and exact experiment `preview`. This is
not coherent nested-state restoration or a claim that every listed unit can
already be executed independently.

## One system, three separate judgments

The testing Episode supplies the question, rationale, predictions, falsifiers,
requirements, measures, scope and mode. The host resolves that request against
the exact candidate and admitted authority. Executing the experiment then yields
three distinct facts: the candidate's measured behavior, what that experiment
established within its boundaries, and any new host-admitted progress. None is
substituted for another. Predictions are not editable acceptance predicates.

The implementation lives under `episode_runtime/testing/`, with CLI rendering
under `openchia_cli/`. It extends the existing runtime package and stores; it
does not add another execution process, authoritative store, function registry, controller
or core model tool. Role-specific refiner code keeps its assignment/acceptance
authority, but delegates experimental execution to this shared service.

| Responsibility | Existing owner / integration point |
| --- | --- |
| Experimental intent and discoverable vocabulary | `episode_runtime.testing.contracts`, `.schema` |
| Exact source and boundary preview | `.planning`, `.candidates`; `BuildStore.inspection_inputs_for_receipt`, `WorkflowMaterializationPlan.all_edges`; refinement candidate source projection |
| Selected invocation execution | `.boundaries` derives saved context from the verified recording; `episode_runtime.scoped.RunScope` binds it into the existing registration; linker and `method_loop.Context` enter at the original nested path without executing ancestors |
| New typed checker entry | `.boundaries.fresh_entry_scope` derives a new initial-state context from the frozen checker definition; `FreshEntryScope` enters only its already-approved child/subtree through the same worker/linker |
| Bound-component execution | `.testing.components` resolves the exact role and call inputs; `episode_runtime.components.ComponentScope` is frozen in the same Run registration; linker invokes the registered implementation inside the ordinary worker without starting an Episode |
| Shared records and reference verification | `episode_runtime.records.experiments`, also used by `iterative_episode_refiner.evidence.EvidenceReader`; unchanged existing store identities |
| Human and agent CLI | `openchia_cli.episode_test_command`; installed `openchia test` dispatch |
| Launch setup | `openchia_cli.episode_launch_setup`; produces the existing `/launch` format and a separate private credential file |
| Target model roles, endpoints and credentials | `agent.episode_launch`, `.episode_launch_transport`, `.episode_launch_host`; Target Workflow test configuration must not replace the refiner's Duet configuration |
| External HTTP credentials | Existing profile config via `episode_runtime.http_broker.load_egress_config`; `ScopedHttpBroker` enforces approved rules for both host and CLI execution |
| Refiner reasoning model | `agent.duet_episode_transport`, `OpenChiaHost.refinement_experiment_service`; binds the owning Duet's resolved model/provider route, never the Target Workflow launch; supplied-agent/local-provider integration verified |
| Real execution and confinement | `episode_runtime.executor`, `.worker`, `.linker`; same admitted package and attested Run boundary |
| Shared Run dispatch and status | `episode_runtime.testing.execution.RunExecution`, used by `.service.ExperimentService` and refiner execution; `register_build` reuses exact admitted registration |
| Ordinary human `/run` | `OpenChiaHost.start_run` records `.testing.launches` intent and uses `RunExecution`; the resolved model-launch event binds the exact configuration and registration |
| Refiner candidate, instrument and reference experiments | `iterative_episode_refiner.evaluation_experiments` supplies assigned sources and checks model proposals, then calls `ExperimentService`; `testing.campaign_criteria` reads the original admitted check; `.campaign_subjects` resolves exact auxiliary source bindings and their campaign ownership |
| Refiner measure-control experiments | `iterative_episode_refiner.measure_experiments` supplies independently grounded cases for Episode selection; `.testing.control_subjects` validates their checker dependencies through the same service; campaign admission still judges adequacy |
| Declared measurement dependencies | `.testing.instruments` binds the independently approved checker to the exact experiment and successful target evidence; executes with `RunExecution`, shared recordings and playback; supplied-answer in-process integration verified |
| In-Episode experiment requests | `function_library.testing.EXPERIMENT_REQUEST`, runtime experiment frames, `.testing.session.ExperimentSession`; delegates to the same `ExperimentService` |
| Approved testing access | Optional `EpisodeCreationSpec.testing` / `TestingContract`, retained by the existing blueprint/approval/build path; requires the assignable `episode_testing` capability |
| Testing Episode | `episode_library.testing`, `function_library.testing_source.TestingSource`; chooses service operations inside the existing reasoning loop |
| Experimental learning | `.testing.learning.measured_sources`, `function_library.testing_admission`; projects committed host measurements and admits exact, deduplicated findings through `LearningLedger` |
| Evidence and recordings | `.recordings` projects existing verified `RunStore` events; `episode_runtime.exchanges` records all five request/reply channels; existing `BuildStore` and `DuetStore` hold references |
| Exact response playback | `.playback.RecordingCursor`; the ordinary `ScopedModelBroker` and `ScopedHttpBroker` consume it without a live transport |
| Interrupted-prefix verification | `.reconstruction.ReconstructionCursor`; global exact worker-frame matching over the same recording, no live fallback or continuation authorization |
| Reconstruction admission | `.reconstruction_source.admit_reconstruction_source` checks generated wrapper bytes; `.reconstruction_host.HostReconstruction` gates the existing executor, preserving original replies and evidence |
| Numerical experiments | `.numerical` projects committed learning observations through `LearningLedger._controller`; `.refinement_numerical` recomputes committed refiner decisions through the existing `recompute_numerical_step`; neither admits new evidence or credit |
| Experimental measurements | `.criteria`, `.judgments`, `.measurements`; existing `refinement_checks` predicates; `.implementation` reuses runtime source identity |
| Outcome comparisons | `.comparison`; exact requirement/measure references and explicit context differences, not an LLM summary |
| Host progress and parent acceptance | Existing learning/refinement admission functions; a harness measurement does not grant either |
| Nested iteration and continuation | Existing `method_loop` and numerical controller; no harness semantic budget |
| Cross-child regression | Existing campaign requirement/candidate history, projected at the owning parent scope |

## Scope resolution

A local Episode template ID is not a nested invocation ID. Nested work needs its
actual path, request, parent goal projection and applicable shared state. A
component probe needs its exact bound function definition and inputs. A unit
probe needs its unit boundary. Full-workflow scope explicitly names all admitted
templates. Repeatable calls are graph edges; recursive calls do not create new
design nodes. Scope preview traverses those edges without silently adding nodes.

A selected group must be connected from its entry. Outgoing edges are shown even
when their child lies outside the selected group. Executable scope must include
its declared children. Substituting recorded child returns during execution is
not supported: preview reports an execution-route gap instead of expanding the
scope or silently executing omitted children. Numerical mode uses
`boundary.children: "reuse"` to recompute control from admitted observations;
it does not execute the parent or children. Reused observations are not evidence
of a new execution of those implementations or external services.

Missing artifacts, parent context, invocation identity, recording or launch data
produce structured gaps with the input path and remedy. `resolved: true` is only
a boundary preview: it is neither execution authority nor a behavioral pass.

### Executing a selected invocation

Use `inventory` to discover the source Run's invocation IDs and paths, then capture
the selected invocation's committed entry context:

```bash
openchia test boundary --run-store /path/to/run-store --run-id SOURCE_RUN_ID \
  --duet-store /path/to/duet.db --episode-id SELECTED_EPISODE_ID
```

The response contains `parent_context_ref`, `recording_ref`, `invocation_path`,
and `initial_state_reproducible`. In a complete experiment specification, set:

- `scope.kind` to `episode` or `nested`, and its entry and included local IDs to
  exactly the code you intend to execute;
- `scope.invocation_path` and `boundary.parent_context_ref` to the returned values;
- `boundary.children` to `execute`, explicitly including all callable descendants;
- `start.kind` to `saved_inputs`, `start.artifact_ref` to the returned recording
  reference, and `start.input_payload` to `{}`;
- `mode` to `live_saved` with a live launch, or `recorded` with a matching
  `recording_ref` and no requirement for live credentials.

Preview with all three stores before running. The source Run, entry request,
parent goal, scoped goal view, state identity and recording prefix are verified
against the existing journal. The current implementation reconstructs the exact
initial GoalState using the source launch, then checks its identity and goal view.
It refuses a boundary reached after state mutation; a restorable checkpoint is
still needed for that case. Changes to ancestor modules or the shared initializer
also require a matching new boundary. No fresh-state substitution is performed.

Execution uses the ordinary worker and linker. The saved ancestry stays in the
invocation path; only the outer Run key and handoff correlation addresses are
rebound. Ancestor Episodes and their controllers do not execute. The host rejects
requests outside the selected subtree, and the result carries its exact execution
scope. A recording from this narrower execution cannot supply whole-workflow
playback or establish that the omitted ancestors work.

Testing Episodes use the same operation through
`{"operation": "boundary", "payload": {"experiment_id": "...", "episode_id": "..."}}`
after running their own authorized experiment. This grants access to that saved
context, not to unrelated experiments or broader execution authority.

### Supplying a new typed input to a checker

A checker receiving target output cannot put that data into an ordinary workflow
root: Builder admission requires the root's launch payload to be empty. Its frozen
definition instead names an already-approved non-root `entry_local_id` and
`entry_context: "declared_goal_initial_state"`, together with exact target-result
field mappings. A definition that omits this entry receives an actionable preview
error, not a relaxation of the root contract.

The host derives a fresh typed request, its concrete declared ancestry and the
included subtree. It binds these and the target evidence into the Run's existing
execution scope with `boundary.origin: "fresh_typed_entry"`. This is a new test
context, not recovered parent execution. The normal root initializer and state
scoper run inside the execution boundary; ancestor Episodes and their controllers
do not. Their declared goals provide explicit test context, not evidence of goals
selected by an actual parent Run. Missing parent-produced state is not recovered
or guessed. This is not interrupted-work continuation (task 3).

Checker execution uses the same `RunExecution`, recording and playback facilities
as the target. The compact execution-history view exposes `boundary_origin`,
`boundary_ref` and these limitations without including raw input payloads. Its
intent names `parent_experiment_id`, `instrument_id`, `experiment_ref` and
`target_execution_ref`. The experiment's target verdict is not copied onto the
checker Run as a verdict about the checker implementation. Checker adequacy still
requires independently grounded controls.

An in-process integration test executes the admitted checker child: a supplied
wrong answer fails, a supplied correct answer passes, and missing input remains
unmeasured without launching the checker. Target-authored pass/fail flags cannot
replace the checker verdict. The result reaches the refiner parent's typed
history with checker evidence kept distinct from target evidence. This does not
establish live reasoning, native confinement or automatic checker construction;
see the [receipts](unified_episode_test_harness_receipts.md).

### Executing one declared unit

Discover the exact unit with `inventory --kind units`. Use its `unit_id`, not
just its label:

```bash
openchia test boundary --run-store /path/to/run-store --run-id SOURCE_RUN_ID \
  --duet-store /path/to/duet.db --unit-id SELECTED_UNIT_ID
```

Testing Episodes use the existing operation with
`{"operation": "boundary", "payload": {"experiment_id": "...", "unit_id": "..."}}`.
Exactly one selector (`episode_id` or `unit_id`) is required. Both interfaces
return the same `parent_context_ref`, `recording_ref`, `invocation_path`, exact
`unit_ref`, and `unit_label`. The worker receives reuse access only to that
recording prefix, not to later responses from its containing Run.

Unit inventory and boundary capture also expose `reconstruction_prefix`: an
exact event reference before the selected unit's source selection (the invocation
start for unit zero, or the preceding unit's completion). `event_ref` in inventory
still names the selected unit's **completed observation**; these references have
different purposes. The indexed view locates the prefix without reading the audit;
capture independently derives the same reference from the verified journal.
Missing predecessor units or a missing invocation start in a continued physical
attempt produce an explicit gap. This selector is not a restored snapshot:
`restoration_verified` remains false, and locating it does not authorize execution.
`located` verifies neither the entire prior unit history nor exchange completeness.
A newly started child in a continued attempt can have a local prefix while its
parent context remains unavailable to capture in that attempt. Baseline admission
must resolve those dependencies explicitly; discovery does not fabricate them.

Set `scope.kind: "unit"`, use the returned `unit_label` and `invocation_path`,
and supply the returned context and recording as for selected invocation
execution above. Include every callable child of the selected entry. The unit
may execute its declared children; its ancestors do not execute. The current
route supports the first unit of an invocation when its initial GoalState can
be reproduced. The later-unit route below passed its in-process execution,
preparation-boundary and preview checks. Unsupported source/state combinations
produce a preview gap, not a rerun of earlier units or substitution of fresh state.

The same Episode acquisition code commits the unit's actual observation and
controller decision. `typed_status.unit_result` reports those values even if
the controller says to continue. Finishing this scoped experiment does not
publish a containing-Episode completion or call its final-result function.
The Run's success means the selected observation was obtained, not that the
Episode's goal was completed or its candidate accepted.

The source recording ends at the selected unit event. For recorded mode, use
that exact returned `recording_ref`; a different prefix is refused. External
requests must still match exactly, including identity-bearing prompt content.
There is no live fallback. This is a new experiment from saved initial inputs,
not continuation of an interrupted execution.

#### Later-unit saved learning (task 1)

The initial saved-state route targets the exact stock reasoning
source, immutable reasoning GoalState and host-receipt controller, verified
against admitted source. The source retrieves its state from the host each unit;
there is no independent Python cursor to replay for this family. The new
experiment keeps its own logical identity and uses the existing saved-entry
linker, worker and one-unit acquisition. It does not borrow `resume_from`, which
authorizes only continuation of the unchanged original execution.

`episode_runtime/learning_baseline.py` derives a provenance-linked learning
baseline from the preceding closed-unit boundary in the existing Run journal.
It validates the committed unit/learning history, approved evidence and exact
source/build/runtime. It projects Episode-local scope and equivalence into the
new invocation while retaining original record IDs and evidence references.
Both the host ledger and public store validator derive that baseline; supplied
checkpoint contents are not trusted. No new store or replay runner is introduced.
The ordinary package-preparation boundary independently repeats the source-shape
check and compares its receipt, including for direct generic-executor callers.

Choose `mode: "live_saved"` with the captured later-unit boundary. Preview exposes
the resolved `learning_baseline`: original registration and prefix references,
completed-unit count, last controller receipt and source-shape admission. The
typed unit input distinguishes `reused_learning.inherited_credit` from
`new_yield_from_import: 0`. Prior observations prime the existing controller;
they are not erased or converted wholesale into excluded baseline knowledge.
The new unit's measurement separately records inherited credit and realized
yield. Numerical replay of this experiment also primes the inherited observations
and reports `reused_unit_count` with their original provenance.

Only after that baseline is admitted may the linker restore the stock receipt
controller and execute the selected later unit, with no earlier model calls,
edits or unit events republished. This initial route requires a child-free stock
reasoning entry, Episode-local stock epistemic functions and an original terminal
whole-Run source. Recorded mode does not rewrite identity-bearing prompts for it.
Continued/scoped source attempts, arbitrary Python state, changed-code state
transfer and writable forks of historical refiner campaigns are not supported
by this admission rule. Such requests fail preview explicitly. Historical
campaign forks remain distinct from same-campaign interruption continuation.

### Executing one registered component

Component scope tests a function bound into an admitted candidate, not an
arbitrary import and not the surrounding Episode. Select the owning local ID,
exact `component_definition_id`, and the binding role. The same function may
have different configurations at different roles; a definition ID alone does
not select those configurations. Every scope preview lists the entry's
`available_component_bindings`, so discovery does not require reading code.
Component preview also exposes the selected binding's frozen arguments,
input/output description, and structured call signature.

For example, the scope and start portions of a complete experiment can be:

```json
{
  "scope": {
    "kind": "component",
    "entry_local_id": "group",
    "included_local_ids": ["group"],
    "component_definition_id": "EXACT_DEFINITION_ID_FROM_CANDIDATE",
    "unit_label": null,
    "invocation_path": []
  },
  "boundary": {"parent_context_ref": null, "children": "none"},
  "start": {
    "kind": "fresh",
    "artifact_ref": null,
    "input_payload": {
      "binding_role": "controller.continuation",
      "adapter": "numeric_band",
      "inputs": {
        "projected_credit": {
          "value": 0.005,
          "lower": 0.005,
          "upper": 0.005,
          "uncertainty_alpha": 0.0,
          "status": "ready"
        }
      }
    }
  }
}
```

The `numeric_band` adapter reconstructs the existing `NumericBand` value and
supplies `parameters` exclusively from the candidate's frozen continuation
binding. The experiment cannot substitute a more convenient threshold.
`json_keywords` passes explicit JSON keyword inputs to a binding with empty
configuration; it does not construct arbitrary Python objects or inject host
capabilities. Other configured or non-JSON interfaces still require typed
adapters. Unsupported call signatures/configuration produce a preview gap.

Use the same `openchia test preview`, `run`, `results`, `recording` and `compare`
commands as for broader execution. The Run still admits the exact source
package and uses the ordinary worker, confinement and brokers. Module admission
occurs, but no Episode source loop, controller loop, ancestor or child runs.
Its structural address identifies the owning binding for broker restrictions;
it is not evidence that those ancestor Episodes executed.

The return contains `component_result.status` (`returned` or `raised`), `value`
and `error`, with no `workflow_result` or Episode `completion`. A function
exception can be the expected observation when testing input rejection; the
frozen criterion determines whether that observation passes. An unrepresentable
object return is an execution error, never a made-up summary of that object.
No component observation admits learning or earns controller credit.

To repeat the exact inputs, save its component Run recording and set
`start.kind: saved_inputs`, `start.artifact_ref` to that selector, and
`start.input_payload: {}`. Use `live_saved` to recompute external calls or
`recorded` with a matching `recording_ref` to reuse external responses. A
workflow recording is not a substitute for a component's call inputs. Changed
binding/configuration or call inputs cannot consume the old recording. Pure
functions have zero external exchanges, so their recorded-mode rerun proves
input/context matching, not actual external-response reuse.

## Modes, persistence and recovery

All modes share the same experiment contract and indexed history interface.
Numerical overviews link their source recording and recomputation report;
execution overviews retain execution status and separate measured outcomes. Numerical replay only
recomputes registered numerical control from saved observations. Recorded mode
runs code with exact matching external responses and never falls back to live.
Live-saved mode distinguishes saved inputs from a complete checkpoint; fresh
mode does not claim resumed state. Experiment identity binds expectations and
references before execution; changed code, inputs or controls create a fork.

The runtime records worker-visible model, HTTP, learning, refinement and
experiment exchanges, invocation inputs, and projected unit controller inputs. Host-added credentials
are not copied into those records. `read_recording` validates hashes, request/
response identity and Episode paths, and supports an exact committed prefix and
explicit invocation selection. An unfinished exchange or legacy hash-only
record produces a gap, not a reconstructed response. `read_committed_prefix`
does not weaken the existing terminal-only `read_audit_log` contract.

Recording inspection, whole-workflow and selected-invocation external-response
playback, and numerical comparison of host-admitted epistemic observations and
refiner decisions are implemented. Numerical replay supports exact Episode
invocations, selected nested groups, workflow scope and refiner-job histories.
Refiner replay uses the recorded credit snapshot and prior remaining-opportunity
bound, never today's campaign state. Older decisions missing that bound are
unavailable. Other controller families and component/unit numerical projections
remain unsupported. Replay requires the recording's exact admitted build and
environment; counterfactual controller settings in a changed build are unsupported.
Numerical results identify both the source runtime and the current calculation's
runtime/source hashes, and compare each recorded step against the recomputation.
They report `evaluated`, not Episode completion or candidate acceptance.

Playback matches the exact admitted request, structural invocation path and
per-invocation exchange order across both model and HTTP calls. Only the outer
Run key is rebound, explicitly in provenance. Child keys and prompt text are not
rewritten: a prompt containing a changed Run ID will diverge. Source/target root
inputs, model configuration, environment, egress policy and frame limits must
match. Recorded mode does not resolve credentials or construct live transports.
A mismatch fails explicitly; no old response is substituted for a new request.
Each reused response links the source journal's request and response events.

Saved-input execution starts a **new** Run using the saved recording's exact
root input payload; it makes new external calls. It does not restore an
interrupted invocation. A recording selector freezes its journal prefix rather
than copying responses into another database. Numerical replay reads the same
selector, reuses admitted observations, and leaves the source journal unchanged.

Some controller input types project as `unprojected_type`, not restorable data.
`Episode.resume_units` rebuilds controller inputs
only. It does **not** restore pending children, source state, shared goal state,
or host admission sessions. Do not present it as nested recovery. The shared
reconstruction path below must validate all required state or return an explicit
unsupported result. Target/checker/refiner-specific replay loops are not allowed.

### Interrupted nested execution: implementation and task 3 verification

Continuation must preserve a waiting parent's actual child call, not just its
credit total. The refiner's admitted calls, prepared children, open unit and
operation ordinal now have committed host-only snapshots alongside their
replies. Saving external model replies alone cannot restore that state.

Use the shared recording and existing Episode loops to reconstruct the saved
execution prefix. During reconstruction, return the exact committed responses
without repeating model calls, HTTP calls, edits, experiments or credit
admissions. The ordinary loop then reconstructs its local state and its waiting
parent/child stack. This is a distinct operation from recorded-response testing:
recorded testing starts a new experiment and recomputes host judgments.

The required boundaries are:

- Preserve logical Episode, unit, request and goal identities. A resumed physical
  worker has its own authenticated Run attempt and terminal evidence; it must
  not rewrite old IDs inside prompts or parent requests.
- Record model, HTTP, learning, refinement and experiment request/reply pairs
  in the existing Run journal. Commit a response before publishing it to the
  worker. Communication records do not replace admitted learning or campaign
  evidence and confer no additional credit.
- Preserve host session metadata as typed, evidence-linked state, with the
  exact campaign and contract head. Restore it without replaying host mutations.
  Learning history retains original event references instead of copying old
  credit into a new Run as new progress.
- Match the global semantic sequence, including nested Episode boundaries,
  then check the reconstructed active stack, controller states, goal state,
  host session and durable heads before enabling any new action. An exhausted
  list of saved model replies is not sufficient to authorize live work.
- Verify that the old worker has stopped and admit only one continuation of
  the selected boundary. Repeating the same continuation request returns its
  existing dispatch/result.
- Initially admit only inspected source/controller/goal-state combinations
  that can be reconstructed this way. Generated overrides, unrecorded state,
  unresolved requests, pending child experiments, changed contracts or code,
  and changed campaign heads produce explicit unsupported results. An Episode
  name or import allowlist is not a reconstruction guarantee.

The required demonstration interrupts `Parts → Designer → Implementer` after
a committed unit receipt but before the child returns. Continuing must produce
the same typed parent result and numerical history as uninterrupted execution,
with no repeated historical calls, edits, tests or credit. Divergent requests
must fail before any live operation. Shared exchange recording, host-state
restoration, source admission and the existing executor's reconstruction gate
are implemented. The complete nested-return comparison now passes through the
common service and real confined systemd workers, as does single-Episode
continuation. The service and CLI expose the same continuation operation.
Task 3 is complete. Decisions and target observations are supplied; the native
test does not establish live-model reasoning or behavioral repair.

`episode_runtime/testing/reconstruction.py` reads the complete interrupted Run
through the same recording projection. Its cursor checks exact worker requests
(including their original IDs), Episode starts, unit records and Episode returns
in one global sequence. It returns only the original committed reply, never
calls a broker and never publishes admissions or credit. Reaching the end raises
an explicit boundary condition on the next action; it does not switch to live
execution. Missing replies reject the whole reconstruction instead of selecting
an earlier convenient prefix. Host metadata remains separate from worker replies.

The shared continuation operation uses source admission that checks the actual
generated bytes against a narrow stock-wrapper language for reasoning, testing
and refinement. It pins the reference implementation's runtime manifest and
rejects generated helpers, subclasses, overrides and top-level effects. Binding
metadata alone is insufficient. The ordinary linked loop reconstructs its local
state from identical input and committed replies, with every semantic frame
checked in order; no Python object deserialization or second loop is introduced.

`HostReconstruction` consumes historical frames before the existing executor's
normal dispatch. It never re-invokes their brokers. At the boundary it requires
current host authorization, verifies the previous executor is stopped, rechecks
the restored campaign/session, and records `run_reconstructed` in the same Run
journal. Its distinct host origin avoids colliding with protocol sender sequence
numbers. Old calls and credit are not republished. Process inspection fails closed
when the original backend cannot establish that the predecessor is stopped.
The public execution service supplies this admission through `continue_run`.
`openchia test continue` and the testing Episode's `continue` operation call that
same service. A request names an existing experiment and exact `resume_from`
reference (Run ID, registration hash and final terminal event ID/hash), not a
new candidate or a new experiment specification. Current target or checker
attempts appear in status, while prior evidence and measurement reports remain
immutable. Repeating an already-dispatched continuation does not launch again.
CLI admission and idempotent continuation checks pass with supplied execution.
The native nested comparison separately verifies the same service with actual
worker claims, stopped-process checks and reconstruction before new work.

Use the current interrupted target's or declared checker's `resume_from` object
from `status` as the contents of `interruption.json`, unchanged:

```sh
openchia test continue --experiment-id EXPERIMENT_ID \
  --resume-from interruption.json --duet-store /path/to/duet.db \
  --build-store /path/to/build-store --run-store /path/to/run-store
```

The testing Episode uses `{"operation":"continue","payload":{"experiment_id":
"EXPERIMENT_ID","resume_from":{...}}}` through its existing approved transport.
`describe.worker_payload_schemas.continue` defines the exact reference fields.
This operation creates a new physical attempt of the same logical execution,
not a new experiment. It cannot accept edited source or weakened expectations.
It currently rejects recorded-mode continuation, incomplete exchanges and
non-stock generated execution logic. A plain CLI cannot reconstruct the
refiner's owning Duet model binding: refinement jobs use the owning host's
`refinement_experiment_service`, never the target's launch file.

This host binding is also required for a **fresh** refiner-job experiment, not
only continuation. With the owning Duet already bound to `host` and its existing
target-evaluation service in `evaluations`:

```python
service = host.refinement_experiment_service(
    refiner_build_receipt_id=refiner_build_receipt_id,
    evaluations=evaluations,
)
plan = service.preview(spec)
result = await service.run(spec)
```

The specification uses `scope.kind: "refinement"`, the exact admitted **refiner**
build for both candidate and build references, the prepared pristine
`campaign_ref`, and `service.duet_binding.reference` for `launch_ref`. Fresh
execution uses `mode: "live_fresh"`, `start.kind: "fresh"`, and the complete
approved refiner workflow. A worked campaign requires same-experiment
continuation or a separately prepared campaign; a fresh experiment cannot reset
its history. The ordinary CLI cannot supply the live owning-Duet binding or
target-evaluation service and reports the missing context. It does not substitute
the Target Workflow launch file. This factory does not approve a design or activate the
refiner for ordinary builds.

The registration now separates physical process-attempt IDs from logical Run
identity. An optional `InterruptedRunRef` binds the previous registration and its
exact final interruption event. The Run store rejects changed code, inputs,
authority, scope or runtime identity. Existing registrations without that field
retain their original serialized identity. Protocol authentication and confinement
remain physical; Episode paths and model/HTTP request IDs remain logical. The
ordinary executor rejects a resumed registration without host continuation
admission. Both identity checks previously passed after
correcting their fixtures; they exercise real stores, generated linking and
worker request framing, not a resumed process.

`iterative_episode_refiner.runtime_state.restore_session` now reads the last
committed host snapshot through the shared reconstruction reader. It validates
the predecessor Run, campaign contract, current target/refiner approval heads
and exact campaign head, then rebinds
existing assignments, paths, inherited goals and typed child requests. It retains
the parent's open unit and earlier candidate reference while a child runs, and
retains closed-unit candidate context. Prepared children remain unentered.
Restoration does not replay edits, re-admit evidence, publish credit or authorize
worker execution. Three broker/store tests verify these boundaries and rejection
of later campaign changes. The finished-child return now passes in the complete
native nested comparison: the child returns once and the resumed result matches
uninterrupted execution. Native single-Episode continuation also passes.

`RunStore.read_execution_prefix` is the shared exact-lineage reader. It follows
only authenticated interrupted-Run predecessors and retains each original
event's physical Run, hash and sequence. A response committed before interruption
can therefore support a later proposal without being copied or treated as a new
model call. This reader grants no cross-workflow evidence access and does not
itself authorize continued execution. Learning now reads this exact ancestry
for state and credit while retaining each physical attempt's own event sequence.
The store independently derives ancestry when checking a new credit event.
Testing access and history remain owned by the original logical invocation;
changing physical attempts does not erase permissions or grant unrelated access.

New saved recording selectors carry `projection_version: 2`. Their projection
includes all five channels and optional host session state. Older four-field
selectors retain their exact v1 identity through the same reader; discovery
explicitly states that they omit host exchanges. Ordinary recorded execution
still reuses only model/HTTP responses and reports host exchanges as non-reused.
It does not restore the saved host state or execute a continuation.

## Current usable interface

```bash
openchia test describe
openchia test setup-launch --directory /path/to/new/private-launch
openchia test setup-launch --directory /path/to/another/new/private-launch \
  --from /path/to/existing/launch.json
openchia test register-launch --file /path/to/private-launch/launch.json \
  --duet-store /path/to/duet.db --duet-id DUET_ID
openchia test register-measure --file criterion.json \
  --duet-store /path/to/duet.db --duet-id DUET_ID --build-store /path/to/build-store
openchia test validate --spec experiment.json
openchia test preview --spec experiment.json \
  --duet-store /path/to/duet.db --build-store /path/to/build-store \
  --run-store /path/to/run-store
openchia test run --spec experiment.json --duet-store /path/to/duet.db \
  --build-store /path/to/build-store --run-store /path/to/run-store
openchia test status --experiment-id EXPERIMENT_ID \
  --duet-store /path/to/duet.db --run-store /path/to/run-store
openchia test status --run-id RUN_ID \
  --duet-store /path/to/duet.db --run-store /path/to/run-store
openchia test results --experiment-id EXPERIMENT_ID \
  --duet-store /path/to/duet.db --run-store /path/to/run-store
openchia test compare --before EARLIER_EXPERIMENT_ID --after LATER_EXPERIMENT_ID \
  --duet-store /path/to/duet.db
openchia test recording --run-store /path/to/run-store --run-id RUN_ID
openchia test recording --run-store /path/to/run-store --run-id RUN_ID \
  --save --duet-store /path/to/duet.db
```

Interactive setup asks for named model routes, exact served models, endpoints,
API modes, project-defined function model slots, and Builder planning/emission
slots. It prompts keys without echo,
uses a new private directory and mode-0600 files, and refuses to overwrite an
existing setup. `--from` is the unattended structured path and preserves explicit
credential references; add `--prompt-credentials` to enter keys into a new private
file. Secrets never appear in command arguments, public configuration or the
receipt. Setup neither activates a chat selection, grants approval, nor calls a
model. Use ordinary `/launch load FILE`, inspect `/launch preview`, then approve
the exact configuration with `/launch approve HASH`. Harness `register-launch`
requires that existing approval in the owning Duet; it cannot grant approval.
Execution records retain `launch_approval_ref` to identify the approval used.
For the
refinement workflow this setup configures the Target Workflow's test Runs, not
the refiner. The refiner's reasoning uses the owning Duet's configuration.
Failed resolution can leave the new private directory/credential file for
inspection, but does not publish a usable launch selection.

External HTTP credentials are separate from model-launch credentials. They use
the active profile's existing `config.yaml` settings, for example:

```yaml
openchia:
  egress:
    allowed_hosts: [api.example.org]
    credentials:
      research_service:
        kind: bearer_token_file
        path: /absolute/private/path/research-service-token
        header: Authorization
        scheme: Bearer
```

Keep the token value in the private file, not YAML, command arguments, launch
settings or experiment records. The approved Episode's egress rule must name
that credential and permit the particular host, method and path. Configuration
does not add worker capabilities or widen the frozen rule. The host and CLI
use the same `load_egress_config` parser and `ScopedHttpBroker`; no harness
credential store is introduced. CLI live `run` and `continue` receive the active
profile's configured credential descriptors; the broker reads a token only for
an authorized request. Numerical and recorded modes do not resolve live HTTP
credentials. `setup-launch` remains a model-routing wizard, not an HTTP-key wizard.

`describe` supplies the input JSON schema and each mode's reuse and limitations.
`validate` checks intent and identity; `preview` resolves existing artifacts and
the admitted graph without executing generated code or starting a model call.
Neither command establishes candidate correctness. `run` currently connects
fresh, recorded-response and saved-root-input whole-workflow execution, selected
Episode/nested execution from reproducible saved entry context, and numerical
comparison over supported recorded invocation histories. Other routes
return explicit gaps **before** execution backend setup. Numerical `preview`
also needs `--run-store` to resolve the exact recorded invocations, unit references
and unobserved templates; metadata does not silently imply those templates ran.
Execution success remains `candidate_verdict: unmeasured` unless an eligible
registered criterion measures its typed return. A criterion pass is still not
independent parent acceptance. This is not a live behavioral receipt.

Refiner target, independent checker, adequacy-control and refiner-workflow Runs
now enter the same `RunExecution` service. Each dispatch re-derives registration
from its admitted build, checks the original non-revoked approvals, and binds
the exact committed intent. A repeated Run dispatch cannot relaunch an unfinished
Run. Its status is explicitly `terminal_evidence_unavailable`, not "running" or
"completed". Inspection by `--run-id` also covers those refiner executions.
The refiner's existing assignment/check/observation records still own acceptance
and credit. `records.experiments.read_run_intent` permits an exact campaign-linked
Run when the independently approved refiner belongs to another Duet. It checks
the frozen workflow approval and manifest; a checker/control intent must bind
the exact Run registration. It does not allow general cross-Duet artifact reads.
History uses that same relationship. The refiner's shared dispatch also verifies
its supplied host session against the registration and campaign intent.

The actual baseline loop has in-process coverage through generated refiner
modules, the existing method loop, framed host exchanges and admitted campaign
operations. It passes static observations up to Parts while retaining missing
behavioral coverage, rejects a supplied invalid proposal for zero credit, and
preserves caller cancellation. Direct target-output checks also have the common
experiment connection described below, including independently built checking
Episodes. Measure-control adapters now have mechanical integration coverage;
live reasoning remains incomplete. Admitted cross-child result cycles
are visible through shared history; autonomous code repair remains unverified.
No claim of end-to-end refiner acceptance is made.

For target, instrument-build and reference-workflow checks, `evaluate` first admits the selected candidate source
through the Builder and supplies the testing Episode with exact request, build,
check, input, environment and target-launch references. The Episode proposes a
complete `ExperimentSpec`: question, rationale, scope, mode, expected and
falsifying outcomes. The host authenticates that proposal against the existing
model-response event, checks its assignment, and returns the common preview.

An instrument experiment projects only its authorized namespaced candidate files;
a reference experiment uses the exact independent approved build. Both retain
the campaign revision as `candidate_ref`. Preview identifies the source kind and
source-owning Duet. Dispatch, measurement and experiment history belong to the
campaign; executable registration, audit and recordings belong to the source
Duet. The exact experiment link permits inspection of that Run, not general
access to the source owner's other work. No host-chosen execution fallback remains.
It does not generate predictions or change the parent's criterion.

The next `evaluate` request names that proposal. `ExperimentService` freezes the
specification and dispatch registration before the Run, executes through
`RunExecution`, and produces a shared measurement. Applicable whole-workflow live
results can then enter the existing campaign observation admission; narrower or
replayed results remain diagnostic. The optional `evaluation_run.experiment_ref`
links campaign judgment to the exact shared dispatch. Admission verifies the Run,
candidate, campaign, environment, mode and assigned checks. Old records retain
their hashes and need no migration. Parent reports recover original predictions
and falsifiers from this reference; they do not invent them after observing output.
The child's next context reads shared measurements by reference, including
diagnostic results that did not create a campaign observation.

The host supplies `RefinementEvaluations.target_launch_ref` from the built
target's registered configuration. A missing selection is reported, not replaced
by the refiner's Duet broker. Refiner-job experiments separately use the owning
Duet binding described above. Their mechanical integration checks do not activate
automatic build finalization or prove live model-directed refinement.

Refiner parent `determinations` and child `check_states` include `test_result`
when a recorded observation exists. Its `outcome` uses the same
`RequirementOutcome` schema as experimental measurements. It carries the
requirement catalog reference and requirement key, measure, expected value,
observed value and exact observation reference. The surrounding result names
the tested candidate, request, criterion, execution and limitation references.
These are projections of existing immutable records, not a second result store.

Routine `child_reports` and `predecessor_reports` in model-facing context use
`reports.report_overview`: original report reference, candidate, unresolved
requirements, per-check status/evidence references and parent decision facts.
They do not repeat complete observed payloads or preservation rows. Full typed
determination outcomes remain available through the same scoped history query
(`refinement_collection: "reports"`). No model-written summary replaces evidence.

The surrounding determination's `outcome` (or child check's `status`) describes
current applicability; `test_result.outcome.status` describes the original test.
For example, a historical pass can have current status `stale` after a candidate
edit, or `contradicted` after conflicting evidence. It does not resolve the
parent's current requirement. Missing observations yield `test_result: null`.
Existing evaluations that recorded no separate prediction/falsifier expose
null values and an explicit limitation; new experimental specifications still
require both statements. No prediction is reconstructed from an observed answer.

`recording` returns metadata by default; `--episode-id` selects exact invocations,
and `--include-content` explicitly includes prompts, responses and typed data.
`--save` returns a `recording_ref` for subsequent specifications. Starting from
the original complete specification, use these mode-specific fields:

| Mode | Start | Additional choices |
| --- | --- | --- |
| `recorded` | Original `fresh` inputs, or `saved_inputs` referencing the saved recording | Set `recording_ref`; retain exact context; `launch_ref: null` reuses the recorded configuration without requiring credentials |
| `live_saved` | `saved_inputs`, `artifact_ref` = saved recording, `input_payload: {}` | Set a registered live `launch_ref`; external calls are new |
| `numerical` | `saved_inputs`, `artifact_ref` = `recording_ref`, `input_payload: {}` | Set `boundary.children: "reuse"`; use workflow scope or an exact recorded invocation/group; `launch_ref: null` is allowed |

The question, rationale, requirements, predictions and falsifiers remain required
in every mode. Changing them creates a new experiment identity, never an edit to
earlier criteria. Numerical reports include recorded/recomputed steps, but leave
candidate verdict and testing progress unassigned. Registered-predicate outcome
comparison, direct admitted campaign checks, independent-checker execution
and grounded measure-control experiments are connected. Their mechanical checks
do not establish live reasoning. Coherent nested continuation remains open
pending its complete demonstration.

## Frozen measurements and comparisons

`candidate_ref` must be the actual `build_receipt_ref`, or a typed refinement
candidate whose projected source and plan exactly match that admitted build.
An arbitrary data artifact labeled "candidate" is rejected. Hash equality of
a prose label is not evidence about which source ran.

`describe` includes `criterion_schema` and the existing registered
`observation_predicates` (exact definition IDs and argument schemas). An operator
prepares a criterion before dispatch using `register-measure`. Its JSON contains:

- `schema_version: 1`, the exact `build_receipt_ref` and `environment_ref`;
- `requirement_key`, `description`, the full experiment `scope`,
  `accepted_modes`, and the exact root `input_payload`;
- a `predicate` selection copied from the registered catalog;
- `observation_path` (JSON pointer relative to the Run's `typed_status`),
  `expected_value`, and nonempty `positive_controls` and `negative_controls`;
- `grounding_refs` and explicit `limitations`.

For example, when a typed result has a `minimum_completion` field, the scheduling
benchmark's scalar criterion can use `/minimum_completion`, expected value `14`,
positive controls `[14]`, and negative controls `[13, 15, "14"]`, with the existing
`refinement_checks.exact_value_v1` predicate. The reference optimum comes from
independent exhaustive enumeration, not the tested model's explanation. This
**only tests the reported number**: it does not check schedule feasibility or
the optimality argument. Those require their own adequate measurements. Choose
the pointer for the actual typed return; do not assume this illustrative field
exists in every Episode result.

Registration returns `requirement_ref` and `measure_ref`. Put those exact references
into an experiment's `requirements`, alongside its predicted `expected` and
`falsifying` text. Predictions are separate from the criterion's `expected_value`.
The criterion freezes its scope, inputs, environment, accepted modes, predicate,
control results, and host implementation identity. Source changes require a new
criterion/experiment; they cannot silently change a previous judgment. The
predicate is shared with the refiner's existing observation path. Campaign
grounding/assignment authority is not replaced by operator configuration.

Preview shows criterion eligibility. A different scope, mode, environment or
input produces an explicit non-applicable measurement, not a widened claim.
Unavailable independent-checker adapters stay unmeasured. Registration validates
that the predicate distinguishes the declared controls; it does **not** certify
the truth or completeness of operator-supplied grounding, and it grants no
execution, child-creation, credit, or parent-acceptance authority.

Terminal reports preserve expected versus observed values and evidence links.
Interrupted/failed execution is a measurement error, not proof of behavioral
failure; missing typed output is inconclusive. A known criterion failure produces
`candidate_verdict: fail`; all required criteria must pass for `pass`. Mixed
inconclusive/unavailable results remain unmeasured. Repeating `run` retrieves the
same report, or finishes measurement after a completed execution; it does not
launch a second Run. `results` is read-only. CLI `run`/`results` returns exit code
2 for a measured failure as well as execution unavailability/errors.

`compare` reads two immutable reports in the same Duet. It lists requirement-level
outcomes and evidence references. Pass→fail and fail→pass are reported as a
regression or resolved failure only when the exact criterion, scope, boundaries,
mode, environment, launch settings and semantic launch inputs are comparable.
Different contexts and missing/non-decisive measurements remain inspectable but
do not establish either claim. Comparison is not causal attribution to a code
change and awards no progress. Cross-child campaign conflicts instead come from
the existing admission rules and appear in the shared refinement-history view.
Reading or comparing those records does not admit a new conflict or award credit.

## In-Episode access

The registered `testing.experiment_request_v1` function carries requests through
the existing confined worker protocol. Selecting this function in a Builder plan
does **not** grant permission. The human-approved Episode contract must contain
`execution_capability_names: ["episode_testing"]` and a `testing` object with:

- `targets`: named exact candidate/build, environment, launch, and optional
  campaign references; assigned requirement/measure pairs; initially permitted
  recording and parent-context references;
- `scope_kinds`: the execution scopes this Episode may request;
- `modes`: the modes this Episode may request.

`openchia test describe` exposes `testing_access_schema`, the experiment schema,
and `worker_payload_schemas`. The ordinary blueprint conversion preserves this
optional contract in both directions, so approval and staged source identity
bind it. Existing contracts omit the field and retain their previous identity.
The Duet admission authority must permit the named capability; the worker cannot
add it or edit a target/criterion after approval.

The ordinary conversational host now offers `episode_testing` as an assignable
capability. This is not automatic permission: the capability and exact testing
contract still have to be present in the Architecture the human approves. To use
the reference, prepare the target/measure references through the shared CLI,
select `reasoning.testing` in the testing workflow, and include that access
contract in its editable Architecture. The following example launches a
standalone testing Episode, **not** the IterativeEpisodeRefiner. Its own launch
settings and the target `launch_ref` in its approved testing contract are
separate. The refiner instead uses the Duet's configuration. Inspect the
standalone testing Architecture before the normal commands:

```text
/approve
/launch load /absolute/path/to/testing-workflow-launch/launch.json
/launch preview
/launch approve HASH
/build
/build status
/run
/run status
```

Ordinary `/run` now enters the shared dispatcher as well. Its intent binds the
Run registration hash to the exact resolved model-launch event/configuration.
Approval, current authority head, admitted build and source package are checked
before execution. The dispatcher supplies testing access only when the frozen
workflow contains it; neither the model nor generated code constructs its own
host session. The existing worker, cancellation path and evidence persistence
remain in use. This does not activate automatic refinement or build finalization.

An ordinary `/run` is not itself an experimental specification. Shared status
therefore leaves its candidate verdict unmeasured. Nested experiments carry
their own questions, criteria, context and measurements. Ordinary launch intent
does not invent an experimental environment snapshot: recordings lacking that
frozen comparison context still cannot supply recorded-mode execution.

The common `RunExecution` path creates the scoped host session from the exact
admitted build. The host resolves each caller through the approved concrete and
repeatable call graph, checks its active recorded invocation, and enforces that
invocation's approved access. A worker may choose a subset of assigned criteria
for a narrower question; its result covers that subset, not the parent's whole
acceptance contract. Different criteria, candidates, environments, launch
settings, scopes, modes or parent context outside the grant are refused.

Inside admitted Episode code, the interface is:

```python
from function_library.testing import experiment_request

description = await experiment_request(operation="describe", payload={})
plan = await experiment_request(operation="preview", payload={"spec": experiment_spec})
result = await experiment_request(operation="run", payload={"spec": experiment_spec})
```

The testing Episode supplies `experiment_spec` based on its question and evidence;
these calls do not prescribe a testing sequence. `status`/`results` take an
`experiment_id`; `compare` takes `before` and `after` experiment IDs; `recording`
takes an `experiment_id` and returns an immutable recording selector and metadata.
All reach the same service/functions as the CLI. No worker-side process launcher,
store path, model credential, arbitrary artifact reader, or measure-registration
operation is exposed.

An invocation may inspect only experiments it requested under its grant. Saving
one of those experiments' recordings makes that exact selector available to its
later authorized experiments; it does not admit unrelated recordings. Request
and response records enter the testing Run's audit, with responses committed
before publication. The existing dispatch identity prevents duplicate target
execution. These operations themselves assign no credit or completion decision.

Current limits: generic testing access covers explicitly listed candidate builds.
The separate refiner assignment binding connects direct target-output experiments
and independent-checker experiments, and projects their outcomes into parent/child
reports. Grounded measure-validation experiments use the same service and admit
distinct control facts; the measure itself requires all declared controls.
Live model-directed use of replay discovery and cross-child regression evidence
remains unverified. Recorded-mode execution of a **testing workflow itself**
is explicitly refused until nested experiment
responses can be replayed coherently; it must never silently launch live nested
experiments. Recorded-mode requests for an ordinary target remain supported.

### Testing Episode and credit

`reasoning.testing` is now a library reference with a Builder-readable source.
Its ordinary reasoning source chooses `history`, `inventory`, `preview`, `run`,
`continue`, `results`, `status`, `compare`, `recording`, or `boundary`; there is no fixed
preview/run/retry sequence. Each
selection carries the operation's typed payload. A `run` payload is the full
experiment specification, including question, rationale, predictions, falsifiers,
scope, mode and assigned criterion references. The preceding response and admitted
findings are available to the next selection. System prompts remain fixed.
`continue` uses an exact interruption reference returned by status or history;
changed source, inputs or criteria require a new experiment instead. Existing
materialized contracts are not changed by adding this action to the library.

The materialized contract needs both `testing` access and the frozen epistemic
policy returned by `episode_library.testing.testing_learning_contract`. The
worker supplies only its admitted `episode_testing` collaborator. The existing
host checks the calling invocation's grant on every operation.

Completed experiment responses are recorded before the worker receives them.
`LearningLedger` projects their decisive host-measured outcomes into immutable,
provenance-linked evidence for the same testing invocation. The model may propose
a finding, but its typed measurement must equal that evidence exactly. The host
supplies the operative assertion and its limits; free-form answer criteria cannot
replace the assigned measurement. Unmeasured, interrupted and inconclusive outcomes
do not become resolved requirements. Nor can human-approved prose masquerade as a
host experiment result by choosing an evidence-kind label.

Equivalence is keyed by candidate, assigned requirement/measure, tested scope,
environment/model context, evidence mode, and observed pass/fail status—not by
prediction wording, model confidence, experiment ID or Run ID. Another result
value with the same criterion verdict earns no additional finding. Live-fresh and
live-saved executions of the same measured subject are equivalent. Pass and fail
records state what was *observed*; neither asserts universal correctness. Contrary
observations remain visible rather than overwriting one another.

The existing registered yield function values a newly admitted finding; the
existing credit/rarefaction/continuation controller decides whether the Episode
continues. An informative measured failure can therefore advance knowledge without
making the candidate pass. Repeated readings, reworded experiments and unsupported
claims earn zero incremental yield. The final typed result exposes established
findings, limitations and unresolved questions, and explicitly grants no parent
acceptance. Comparison remains inspectable evidence. The refiner's existing
campaign owns cross-child conflict admission; shared history projects admitted
conflicts at assignment scope. The admitted opposing-result cycle is verified
with supplied execution outputs; live interpretation and repair remain unverified.

The current loop check uses scripted model responses and supplied target output.
It does not yet establish autonomous experimental design or live task reasoning.

## Remaining completion evidence

Task **4** remains, as defined at the top of this guide. Task 1's refiner-job
and numerical-replay integration and negative
decoder check now pass; stock later-unit saved learning passed in-process
execution, numerical comparison, preparation and preview checks. Instrument-build
and reference-workflow experiments now pass the shared-service and authorized
worker-discovery checks, completing task 1's routing work.
Historical refiner-state forks are an unsupported extension, distinct from
task 3's now-verified same-execution native nested continuation. Task 5's
compatibility/documentation checkpoint is complete. Task 4 requires the real,
independently checked live acceptance demonstration and its honest receipt.

Launch setup, approved target configuration and the owning-Duet refiner-job
binding are implemented. Supplied-agent/local-provider and in-process checks
verify the binding and direct/checker/control integration, not live reasoning
or native confinement. Preserve those evidence limits until the corresponding
whole-system acceptance demonstrations pass.

The [scheduling acceptance setup](acceptance/README.md) records the approved
target blueprint, real blocked-build receipt and unresolved tester references.
It uses the real `reasoning` model slot and shipped `0.01` continuation threshold.
Its measure checks schedule feasibility and independently enumerated optimality.
Target workflow and launch approvals are recorded; the first live Builder attempt
was blocked before emission. No Target Workflow Run was created. The target
still needs an admitted build, and the tester needs its own approved workflow,
build and launch. Its access contract cannot be finalized until the real target
and criterion references exist.

Development results and their evidence limits are kept in the
[verification receipts](unified_episode_test_harness_receipts.md), separate from
this current operating/design guide. Earlier receipts describe earlier code;
they are not an acceptance claim for later changes.
