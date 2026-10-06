# Continuing interrupted Duet-owned work

In the original Duet, use `/build continue`; use `/build status` to inspect it.
Use `/build continue BUILD_REQUEST_ID` to select an earlier saved job explicitly.
For an ordinary Target Workflow Run, use `/run continue` and `/run status`.
For an already open background Duet, use `/bg DUET_ID build continue`.
Reopening a saved background Duet restores its own model route, not the foreground
Duet's current route. Credentials are resolved from current provider configuration;
they are not stored in the session. Invalid saved configuration is reported without
rewriting the session. `/run status` and background listings distinguish active
continuation, resumable interruption and unknown ownership.
`/build` still starts a new job. Continuing preserves completed work and does not
create a replacement for an already worked refinement campaign.

The host selects the saved job under the current exact workflow approval,
binds future refiner calls to the owning Duet's current model and reasoning settings,
and resolves the original approved Target Workflow launch configuration. The
refiner's route and the Target Workflow's launch remain separate. `/model` and
`/reasoning` changes take effect on an explicit continuation, not mid-Run. The
new physical attempt stores its actual `duet_model_binding_ref`; the experiment,
completed responses and their original model records are unchanged. This is
provenance, not another approval stage. With unchanged model settings, credentials
are refreshed while the saved recovery policy is preserved, including its absence.
Each new Builder successor launch records the current host commit, dirty state,
client package versions and transport source hashes. Only the approved routing
configuration is reused, never the predecessor's host-environment attestation.
The successor launch ID is deterministic for retry-safe publication.

The shared execution service verifies that the previous execution owner released
its exact lease (or its PID and creation time are no longer live), and that the
previous confined executor is stopped. Keeping the same CLI open is supported.
If a terminal event committed before its audit/evidence publication finished, the
existing RunStore completes that publication. If both processes died before a
terminal event, RunStore records an interruption with that ownership evidence.
An unclaimed dispatch resumes its exact registration: the executor never sent
START. A claimed interruption starts one linked physical
attempt of the same logical execution using the existing confined executor.
The original Run remains cancelled/interrupted, never relabelled completed.

During reconstruction every recorded worker request and nested Episode boundary
must match exactly. Completed model and host responses come from the verified
Run journal, not new model calls or repeated mutations. The host restores the
last committed nested call state and checks the campaign head before admitting
new work. A final unanswered model request may be submitted again only after
the saved prefix matches and current authority is rechecked. The provider may
have processed that abandoned request; only its new committed response can
affect OpenChia state. Provider-side exactly-once billing is not promised.

Implementer coding turns use that same model-response boundary. A completed
response replays its captured proposal without running the coding tools again.
An unanswered coding request retains its unadmitted workspace edits and native
thread reference in the shared campaign artifacts. Continuation checks the old
coding subprocess identity before reusing the workspace and resumes the existing
Codex thread. A changed Duet binding or instruction prefix opens a new native
context. Explicit cancellation joins the coding operation and closes its process
tree before publishing the Run terminal; a live or unverifiable old coding
process is never treated as safe to overwrite. These records grant no admission
or credit: the proposal must still pass the normal checks.

Job results are append-only per physical attempt. A continued success must still
produce the same independently verified build receipt; continuation itself does
not discharge requirements, assign credit, or weaken acceptance.
Cancellation before the first Run dispatch publishes a job result without inventing
a Run ID or per-Run result. The continuation request records its requester; only
the execution service's fenced lease establishes ownership of the successor Run.

## Supported boundaries and current limits

- Stopped Builder, refiner, and ordinary Target Workflow jobs use their normal
  public continue commands. Empty worker prefixes and missing terminal/result
  publication use the same shared ownership, execution and RunStore APIs.
- Exact admitted source, worker runtime, inputs, approvals and
  campaign state must remain available. The host can be updated while the worker
  still executes its original hash-verified staged runtime. Every recorded frame
  must match before new work; incompatible protocol or host state fails closed.
  Changed worker code/contracts are not hidden inside the same execution.
  A new physical refiner attempt can select the
  owning Duet's current model binding; the selected binding is fixed for that
  attempt. Fresh launches still require their original selected binding.
- `invalid` is not an interruption. Continuation does not repair an invalid
  request or invent producer evidence. A narrow historical exception allows a
  host-recorded `LaunchModelError` ending at an unanswered model request to
  continue without rewriting its old `failed` terminal record. Ordinary failed
  executions cannot be continued. Such a defect must be fixed in the owning implementation and admitted
  as a new execution when its frozen source changes.
- Local Refiner changes and their host reply/state receipt share one Duet
  transaction. Reconstruction uses that receipt if the Run response is missing.
  With no receipt, the saved campaign head must still match before the exact
  request can run. Local source admission uses deterministic, idempotent Builder
  identities; committed receipts are reused. Nested validation Runs remain
  outside this transaction and reconcile through their own shared dispatches.
  Source admission still holds the Duet write transaction during local validation,
  hashing and package publication. This preserves the existing reply/state crash
  boundary but can delay status reads and contend with another process's writer.
  Shortening that transaction is deferred, not claimed solved by continuation.
- Learning commits retain their existing request/ordinal idempotency. Experiment
  requests use their existing immutable intents and dispatches. An unanswered
  HTTP operation is **not** blindly repeated: its external outcome requires
  reconciliation. Concurrent exchange histories remain unsupported by the
  serial Episode reconstruction contract.
- Whole-Run reconstruction supports admitted generated Target Workflow code,
  not only stock reference wrappers. It regenerates inside the ordinary confined
  worker, never on the host, and must match every saved protocol frame. Trace
  divergence fails closed; unrecorded nondeterminism is not restored. Starting a
  separate experiment at a later unit still requires its stricter source gate.
- A live or unverifiable old executor cannot be continued. Elapsed time is not
  evidence of process death. Legacy terminal Runs without host ownership events
  still use their exact stopped-worker attestation; new Runs additionally record
and fence the host lease. Historical missing ownership cannot be reconstructed.
- Initial Builder interruption is supported for new jobs with recorded process
  ownership and model binding, using its existing call evidence. Refiner setup
  can reuse a completed shipped-program build and idempotent campaign preparation.
  A partial shipped-program build uses a linked single-use request and the same
  deterministic materializer. Completed receipt and campaign preparation are
  reused. Builder successor links, ownership and exact launch snapshot now
  publish in one Duet transaction.
- A final Run whose refiner result was already committed can finish publishing
  its build result without another Run. A completed Run lacking that refiner
  result restores the recorded terminal host state and republishes the normal
  independently checked result without another Run.

## Implementation map

### API errors stop the owning job

A failed Builder, refiner or Target Workflow model API request stops the active
job. It does not trigger a fallback route, another component, a repair iteration,
or an automatic continuation. Rejected JSON or an inadequate *returned answer*
remains ordinary refinement feedback and can be iterated.

Builder call evidence is committed before the failure propagates; no failed
Builder receipt is handed to the refiner as if the API outage were a code defect.
The normal Builder continuation adapter reuses completed responses and retries
the unanswered request. Runs record `interrupted` with
`stop_reason: model_api_error`; nested validation failure propagates to the owning
refiner and build. `/launch calls` retains the provider diagnostics. The stopped
experiment remains inspectable without silently rerunning it.

An explicit parent continuation can resume a child that was already interrupted.
If that new attempt gets another API error, it stops again; no same-invocation
retry is performed. Health probes during a still-pending silent call remain the
separate [health mechanism](model_call_recovery.md), not error-result retries.

### Code ownership

`agent/openchia_build_continue.py` restores job ownership/configuration;
`agent/openchia_build_job.py` remains the lifecycle/final acceptance owner.
`ExperimentService.continue_interrupted` and `continue_run` own shared Run
recovery/admission. `testing/reconstruction*.py` verify the existing journal.
`runtime_state.py` restores nested refinement host state. No second runner or
response ledger is introduced.

`testing/recovery.py` owns process/lease recovery for ordinary Runs and experiments.
`records/host_operations.py` stores only the host transaction's completion receipt
in the existing shared artifact registry. `DuetStore.transaction` uses nested
savepoints, so existing campaign admissions and that receipt commit together.
An uncaught exception or cancellation rolls back the outer transaction, including
successful nested writes. If the caller catches an inner exception, only that
savepoint is rolled back and the outer transaction may continue and commit.
The common exchange path joins local writer threads before terminal cancellation;
network/nested execution remains cancellable through the existing executor.

Terminal history is verified once per named predecessor during a continuation
operation, then shared across preparation, reconstruction and ancestor reads.
`RunStore.terminal_snapshot_scope(run_ids)` bounds this reuse to explicit Run IDs
and the owning operation; nested host calls and `asyncio.to_thread` share it.
`read_terminal_snapshot` returns immutable evidence and events together. Reuse
checks the registration, claim and evidence identities again but does not reread
every historical event/chunk. The snapshot is discarded when the operation exits.
Current approval, campaign and active-prefix reads are never cached.

For a fresh independent integrity audit, call
`RunStore.verify_terminal_snapshot(run_id)`: it always rereads and verifies all
event files and terminal audit chunks, even inside a snapshot scope. An integrity
failure invalidates that scope's retained snapshot. `refresh_run_record` uses
this fresh path. Ordinary status inspection has its own short-lived scope;
high-frequency monitoring can use the existing maintained `read_run_record`
view, which is not a substitute for independent evidence verification.

The initial Builder stage uses `agent/openchia_build_recovery.py` to read the
existing `BuildCallEvidenceRecorder` records. A successor request/attempt is linked
through the shared record registry; its previous attempt and cancelled receipt
remain unchanged. Exact completed responses are fed through the normal planner,
emitter and admission functions. Missing responses are requested live only after
the saved response prefix is matched. Divergence is an error, not live fallback.
`build_model_response_reused` events identify source evidence without inventing
new provider calls. An already finished Builder receipt skips planning/emission
and proceeds to the ordinary refiner handoff.

New jobs record the owning process's PID **and creation time** and the frozen
owning-Duet binding before starting their thread. A Builder with no terminal
receipt is discoverable in `/build status`. Continuation requires its previous
owner to be stopped or its job finalization to have committed; unknown liveness
is not assumed safe. A second CLI reports `building` when the exact recorded
owner is live, `ownership_unknown` when it cannot verify the owner, and
`interrupted` only after it verifies the owner stopped without finalization.
A committed `build_finished`/`build_host_failure` supplies its actual terminal
state. Failure to start a fresh or continued Builder thread also publishes
`build_host_failure` with the exact owner, request and error, so the same open
CLI can continue it instead of mistaking its still-live process for an active
Builder. This is process/finalization evidence, not a claim that the Builder is
making progress. Legacy Builder jobs without recorded ownership/binding
cannot be continued across this boundary. This restriction does not apply to a
legacy refiner whose existing Run attestation and experiment already bind them.

## Recorded live evidence and remaining validation

The normal `OpenChiaHost.continue_build()` call at pinned source
`b6ae19fe9625c70d65df72003c003d744404ff8c` completed missing terminal publication
and started successor Run
`run_008d375611c64c57edfacec3913c172094ce2b07e1a2a95389bcbc734534a45f`.
It reconstructed 479 worker frames with no divergence, restored the nested
root → Designer → Measure stack, and reissued the exact pending request. Its
response committed at event 4; the host rejected malformed JSON for zero yield
and automatically requested the next Measure iteration at event 14.

That first checkout includes the initial continuation commit `daeaa271d3`, not
the later Builder, snapshot or lifecycle corrections.

A second normal `continue_build()` call at pinned source
`e807de71018e6c5469cccc2f2eb1d6b7e1c716c8` started
`run_b13f71313a8bf041d41992874ee795bdbd5c8d0cbb3604025c5897c91ccfe4db`.
Event 2 records 672 matched worker frames, zero remaining frames and no
divergence. Event 3 dispatches the exact pending `propose` request from the
cancelled predecessor's event 346. Event 4 records `invalid`:
`proposal is not this Episode's committed model response`.

The predecessor already contained an empty `raw_response` and a producer ID
with no corresponding committed model response. This is a refiner failed-call
handling defect, not provenance lost during continuation: `propose` checked
only for `None`, while the failed completion result defaults to an empty string.
The host rejected the restored request, with no admitted proposal, no credit,
and no campaign-head change. The invalid Run and both cancelled predecessors
remain unchanged. PR #33 owns that refiner defect; PR #35 does not weaken
producer verification or add an exception for continuing invalid Runs.

The second pinned source includes lifecycle work through `ca611ab4e9` and
repeated-cancellation joining `446e6cc019`, with the original worker source
closure preserved byte-for-byte. Later response-disconnect handling
`283847eac4` and UI notification lock-order correction `766f65c033` have static
checks only. The live executions establish nested reconstruction, pending model
and host-request dispatch, and preservation of admission checks. They do not
exercise every Builder/public Run recovery boundary or establish successful
refinement or Target Workflow acceptance. These live receipts predate the focused
review-follow-up checks below.
The [shared chronological receipts](unified_episode_test_harness_receipts.md)
retain these observations and limits.

## Scoped review follow-up verification

The focused follow-up passed **36 tests across 11 files**, with no skips, through
`scripts/run_tests.sh` using the isolated test environment. Coverage includes:

- The four displaced refinement evaluation files now use `RefinementSession.exchange`,
  including experiment dispatch and repeated-request checks. This exposed and fixed
  a deterministic candidate-admission nonce that incorrectly included its ID prefix.
- Real SQLite nested rollback/commit invariants, claim-before-attempt recovery,
  current launch provenance and cancellation-result publication.
- Real background `AIAgent` construction and saved-route reopening, malformed
  configuration reporting, and foreground/background continuation status rendering.
  The constructor check also covers removal of the unsupported `auth_mode` and
  `cache_scope` constructor arguments present before this PR.
- Both matching and divergent reconstruction through actual Linux systemd-confined
  workers. Fault injection changes one in-memory replay response; the resulting
  mismatched worker request is rejected as `invalid` before activation, a new model
  call or credit. Original audit and evidence remain unchanged.

These are continuation infrastructure checks, not another live reasoning acceptance
run. Supplied model responses in the harness do not establish refinement quality.
Other OS validation, transaction-duration redesign and PR #33's refinement acceptance
remain outside this follow-up. Ruff and whitespace checks passed for the changed set.
