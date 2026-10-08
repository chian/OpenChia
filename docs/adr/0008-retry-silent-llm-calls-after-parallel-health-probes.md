# ADR 0008: Retry silent LLM calls after a successful parallel health probe

- Status: Accepted
- Date: 2026-10-04
- Scope: Shared host model transport for Builder, IterativeEpisodeRefiner, and Target Workflow calls

## Context

A model request can stop receiving data while its connection remains open.
Waiting indefinitely preserves a legitimately queued request, but cannot recover
an abandoned request. A universal request deadline has the opposite problem:
it can repeatedly cancel slow or queued work and send it to the back of the queue.

OpenChia needs another observation before deciding to retry. That observation
must not require knowledge of the provider's queue, a request-status endpoint,
or provider-specific capabilities. The same mechanism must work through the
existing model transport across services.

## Decision

Use a small, independent model request to check service responsiveness while
the original request remains pending. All providers use the same algorithm and
default policy. There are no built-in vendor-specific retry rules.

1. Track actual response activity on the original request. An inactivity
   interval triggers investigation, not cancellation or a claim that the
   request has failed.
2. Send one bounded health probe using the same endpoint, requested model, and
   credential. Keep the original request running during the probe. The probe
   uses a fixed short prompt, with no workflow content or tool access.
3. If the probe waits, fails, times out, or returns no usable response, preserve
   the original request. Space repeated probes farther apart when they provide
   no new basis for action.
4. If the probe succeeds, wait a further grace interval. New activity or a
   completed response on the original request cancels the replacement decision.
5. If the original remains silent, the configured policy may replace that
   physical request. Resubmit the same logical request through the same route.
   Admit at most one result; a late abandoned response cannot become a second
   Episode result.

The default permits this evidence-based replacement. Users may save overrides
for a chosen source or model, including preserving the original even after a
successful probe. These are explicit user choices, not inferred vendor behavior.
Defaults and settings are documented in
[Model-call health and recovery](../openchia/model_call_recovery.md).

A successful probe is evidence that another request completed, **not proof that
the original request is dead**. The probe may reach another worker or receive
different scheduling treatment; a large original prompt can legitimately need
longer. This uncertainty and the possibility of duplicate remote work remain
visible in the audit.

### Amendment 2026-10-08: retryable failed attempts

A physical attempt whose **connection drops** mid-response with no provider
verdict (e.g. `incomplete chunked read`, a connection reset or read error, and
no HTTP error status) produced no result, so there is no original to preserve. Under `retry_on_healthy_probe` it is replaced through the same
route, after a short backoff, using the same `max_replacements` budget as a
silent-call replacement, and recorded as `recovery_replacement_proposed` with
basis `retryable_transport_failure`. Provider error responses (an HTTP
status such as 503, or an error event in the stream) still fail the call
without a retry, as do `disabled` and `preserve` modes and an exhausted budget.
Observed on ANL Argo: long streamed Refiner calls dropped after 100–165 s and,
without this, stopped the whole build.

## Boundaries

- Implement the decision once in the shared pinned model transport. Builder,
  Refiner, and Target Workflow adapters call it; they do not own separate retry
  loops or health policies.
- Use supported HTTP event hooks and existing adapter progress callbacks for
  activity. Do not replace response streams or couple transport code to private
  auxiliary cancellation decisions. The auxiliary boundary owns its cancellation
  registration; each physical call unconditionally closes its own client.
- Cancel only resources owned by the replaced attempt. Local socket shutdown or
  task cancellation does not prove remote cancellation or eliminate duplicate
  billing. Cleanup must not indefinitely block the owning process's shutdown.
- Record activity, probe outcomes, replacement decisions, and cleanup facts in
  the existing model-call audit. Do not store probe output as workflow evidence
  or insert it into the Episode's conversation.
- Probe cost, retry count, and transport liveness are not reasoning yield or
  credit. Operational recovery limits never mark an Episode complete and never
  replace its registered numerical continuation rule.
- Keep effective settings in new launch/Duet binding records. Continuing an
  existing execution preserves its recorded settings, including the absence of
  this policy in historical records; changing defaults does not silently change
  an active or resumed contract.
- Continuing a build after process interruption is a separate operation. This
  mechanism recovers a pending model call, not a lost workflow or HTTP session.

## Consequences

The mechanism needs zero provider-specific status knowledge. A pending or
inconclusive probe leaves the original queue position intact. A successful probe
supplies an additional reason to retry instead of relying on elapsed time alone.

This does not guarantee detection of every stalled request or preservation of
every legitimate queued request. Continuing response activity can hide a
semantic stall, and a successful short probe can coexist with a healthy but
slow original. Probes also consume service capacity. Saved overrides and explicit
audit evidence make these tradeoffs inspectable without repeated user prompts.

We reject a uniform total request timeout as the sole retry criterion,
provider-name exceptions as part of the algorithm, and treating successful
probes as authoritative knowledge of another request's state.

## Validation status

The implementation has received static review and syntax checks. This ADR does
not claim live recovery validation. Dedicated outage tests are not a prerequisite
for this PR; behavior will be observed on subsequent real Runs, with remaining
limitations recorded honestly.
