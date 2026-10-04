# Continuing an interrupted build job

In the original Duet, use `/build continue`; use `/build status` to inspect it.
For an already open background Duet, use `/bg DUET_ID build continue`.
`/build` still starts a new job. Continuing does not rebuild the Target Workflow
or create a replacement refinement campaign.

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
- Initial Builder interruption before the saved refiner handoff is a separate
  remaining part of this implementation. This command currently reports that
  boundary explicitly; it does not claim arbitrary-quit coverage.

## Implementation map

`agent/openchia_build_continue.py` restores job ownership/configuration;
`agent/openchia_build_job.py` remains the lifecycle/final acceptance owner.
`ExperimentService.continue_interrupted` and `continue_run` own shared Run
recovery/admission. `testing/reconstruction*.py` verify the existing journal.
`runtime_state.py` restores nested refinement host state. No second runner or
response ledger is introduced.

Static syntax and diff checks are not live acceptance. The existing interrupted
real build is the acceptance subject; its continuation outcome must be recorded
separately after the normal public command is exercised.
