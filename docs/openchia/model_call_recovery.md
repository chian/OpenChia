# Model-call health and recovery

Design decision: [ADR 0008 — Retry silent LLM calls after a successful parallel
health probe](../adr/0008-retry-silent-llm-calls-after-parallel-health-probes.md).

Builder, IterativeEpisodeRefiner and Target Workflow model calls share the
existing pinned transport. Recovery stays inside one logical model call; it
does not restart the workflow or grant Episode credit. The refiner still uses
its owning Duet's model configuration. Target Workflow Builder and test Runs
still use the approved launch configuration.

## What happens during a long wait

1. OpenChia records dispatch and response headers through supported HTTP event
   hooks, plus existing stream-progress callbacks where the wire adapter supplies
   them. Non-streaming calls have only the coarser dispatch/header signals; the
   transport does not wrap or replace HTTP response streams. It does not label a
   silent request queued or computing without server evidence.
2. After the source's inactivity interval, it leaves that request in place and
   starts one small side call using the same endpoint, model and credential.
   The probe contains no workflow prompt, user data or tool access.
3. A failed, empty, cancelled or timed-out probe preserves the original call.
   The probe has its own total deadline, independent of the original wait.
   Repeated probes become less frequent, up to 16 times the configured interval.
4. Original response activity cancels the probe or pending replacement decision.
5. A successful probe can justify a replacement only when the frozen source
   policy permits it and the original remains silent through a further grace
   interval. An already-completed original wins over a replacement.
6. A replacement abandons only that physical attempt. It keeps the logical call,
   model, endpoint and credentials. Only the selected attempt can return a result
   to the Episode broker. Probe responses and late abandoned responses cannot
   become Episode results or credit.

A healthy side call is **heuristic evidence**, not proof that the first request
failed. The side call may use a different server worker or queue priority, and a
large original prompt may legitimately take longer. Closing our connection does
not prove that the server cancelled its work; replacement may duplicate billing
or computation. Recovery receipts state these uncertainties explicitly.

The algorithm requires no provider-specific queue status, resumption, capability
discovery or submission-deduplication API. A provider request ID is recorded when
present for correlation, not treated as a polling capability.

## Defaults and saved source settings

Every newly resolved source uses the same operational default, regardless of
provider, endpoint, model, local/remote deployment or queue implementation:

```yaml
mode: retry_on_healthy_probe
idle_seconds: 900
probe_timeout_seconds: 60
probe_interval_seconds: 300
recovery_grace_seconds: 60
max_replacements: 1
```

Pending or inconclusive probes preserve the original call on every source.
Users may select `mode: preserve` when even a healthy side call must never
justify replacing the original. `mode: disabled` disables probes and
replacements entirely. There are no built-in vendor exceptions or capabilities.

Save exceptions once in the active profile's `config.yaml`, using the existing
config editor/commands. No new per-iteration dialog is required:

```yaml
model_call_recovery:
  sources:
    - provider: custom
      base_url: http://localhost:8000/v1
      policy:
        mode: preserve
    - provider: custom
      base_url: https://models.example.org/v1
      model: my-reasoning-model
      policy:
        idle_seconds: 1800
        mode: retry_on_healthy_probe
```

Matches use exact provider and endpoint, optionally narrowed to a model. A
model-specific entry overrides a source-wide entry. Duplicate source keys and
invalid policies fail configuration resolution visibly. An optional `recovery`
object on a Target Workflow launch route overrides its profile source settings.

Effective policy is frozen into each **new** launch/binding record and is shown
in launch preview or the Duet binding. Launch approval therefore includes it.
Editing defaults never changes an active binding. A restored historical binding
without a recovery field retains its original behavior; continuation must not
silently insert new defaults. This is separate from the build/refiner continue
feature, which resumes the durable workflow rather than an HTTP connection.

The inactivity interval is not a computation deadline. Response activity resets
it; there is no total wall-clock limit on the original request from this policy.
The probe's small requested output limit is translated by the selected adapter;
some adapters omit unsupported token-limit fields. Its separate deadline is the
host's waiting limit, not a guarantee about remote cancellation or maximum cost.

Exhausting the replacement limit is an **operational error**, never a successful
Episode completion or a numerical continuation decision.

## Audit and implementation

The existing `model_launch_call` records retain one logical `call_id`, route
provenance, physical-attempt number and probe ID. States distinguish activity,
probe success/failure/deadline, original preservation, grace, attempted recovery,
client cleanup and recovery exhaustion. Records contain timestamps and typed
diagnostics, never raw provider errors, credentials or streamed model text.

`/launch calls` and the existing event readers expose these records; there is no
parallel recovery database. Activity records are throttled, not per-token audit
entries. Transport activity is not durable reasoning progress.

Implementation lives in `agent/model_call_recovery.py` and
`agent/model_call_recovery_policy.py`, called by `invoke_pinned_route` in
`agent/episode_launch_transport.py`. Recovery remains at that call boundary.
The public `auxiliary_client.run_cancellable_provider_call` entry owns cancellation
registration through the existing provider fence; transport code never inspects
its private thread-local decision object. The supplied shutdown operation applies
only to the attempt-owned client and cannot be overwritten by an adapter's
stream-close hook.

The fence wraps the entire physical `_invoke`, including client construction.
Preflight cancellation therefore creates no HTTP client. An unconditional outer
`finally` closes the SDK client, or the raw HTTP client if SDK construction fails,
on the same provider thread that uses it. Cancellation can request socket shutdown
from the waiting thread but never transfers descriptor-close ownership. Unconfirmed
cleanup is reported rather than equating coroutine cancellation with server
cancellation. Context-preserving daemon ownership avoids hanging process exit on
an abandoned call in asyncio's default executor.

Validation status: syntax and static checks only during implementation. No
live provider acceptance or recovery success is claimed by this document.
