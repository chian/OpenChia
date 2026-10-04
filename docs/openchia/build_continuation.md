# Continuing an interrupted build job

In the original Duet, use `/build continue`; use `/build status` to inspect it.
For an already open background Duet, use `/bg DUET_ID build continue`.
`/build` still starts a new job. Continuing preserves completed work and does not
create a replacement for an already worked refinement campaign.

The host selects the saved job under the current exact workflow approval,
restores its original Duet model binding with current owning-Duet credentials,
and resolves the original approved Target Workflow launch configuration. The
refiner's route and the Target Workflow's launch remain separate. Stored route
policies are preserved, including absence of a newer recovery policy.

The existing shared experiment service verifies the previous executor is stopped.
If a terminal event committed before its audit/evidence publication finished, the
existing RunStore completes that publication. It then starts one linked physical
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

Job results are append-only per physical attempt. A continued success must still
produce the same independently verified build receipt; continuation itself does
not discharge requirements, assign credit, or weaken acceptance.

## Supported boundaries and current limits

- A stopped refiner with a completed serial exchange history, or a single final
  unanswered model request, can continue through the normal build command.
- Exact admitted source, worker runtime, inputs, approvals, model binding and
  campaign state must remain available. Changed code/contracts are not hidden
  inside the same execution.
- Unanswered host mutations or HTTP requests require durable receipt reconciliation;
  they are rejected rather than blindly repeated. Concurrent exchange histories
  and non-reference generated wrappers remain unsupported by reconstruction.
- A hard crash without a committed terminal event is not inferred to be an
  interruption merely from elapsed time. A live or unverifiable old executor
  cannot be continued.
- Initial Builder interruption is supported for new jobs with recorded process
  ownership and model binding, using its existing call evidence. Refiner setup
  can reuse a completed shipped-program build and idempotent campaign preparation.
  A partial shipped-program build without a terminal receipt remains unsupported.
- A final Run whose refiner result was already committed can finish publishing
  its build result without another Run. A completed Run lacking that refiner
  result still needs terminal host-state reconciliation.

## Implementation map

`agent/openchia_build_continue.py` restores job ownership/configuration;
`agent/openchia_build_job.py` remains the lifecycle/final acceptance owner.
`ExperimentService.continue_interrupted` and `continue_run` own shared Run
recovery/admission. `testing/reconstruction*.py` verify the existing journal.
`runtime_state.py` restores nested refinement host state. No second runner or
response ledger is introduced.

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
is not assumed safe. Legacy Builder jobs without recorded ownership/binding
cannot be continued across this boundary. This restriction does not apply to a
legacy refiner whose existing Run attestation and experiment already bind them.

Static syntax and diff checks are not live acceptance. The existing interrupted
real build is the acceptance subject; its continuation outcome must be recorded
separately after the normal public command is exercised.
