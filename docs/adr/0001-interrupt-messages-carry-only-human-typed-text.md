# ADR 0001: Interrupt messages carry only human-typed text

Status: Accepted

Implementation: not yet landed; follow-up implementation pending.

## Context

The interrupt message field can currently carry system-generated text. The turn finalizer copies that field into the turn result, and the CLI and gateway consumers can then replay it as the user's next prompt. A system control event consequently becomes apparent user input.

The gateway partially guards its consumer with `_is_control_interrupt_message()`, which compares exact lowercase strings against `_CONTROL_INTERRUPT_MESSAGES`. This convention is already incomplete: `Execution timed out (inactivity)` is listed, while `Cron job timed out (inactivity)` is not. The CLI consumer has no corresponding guard.

The interrupt-control boundary already records provenance. `interrupt_issuer(agent)` returns `None` for a human stop and a producer slug for a system stop. Provenance therefore expresses the distinction directly without interpreting message text.

## Decision

The decision has two parts.

First, the interrupt message field contains only text a human actually typed.
The legitimate producers are the paths that carry such text directly:

- the CLI keyboard path — `_chat_monitor_agent_thread` reads the interrupt
  queue and calls `agent.interrupt(interrupt_msg)`
  (`openchia_cli/cli_chat_turn_mixin.py:438`)
- the gateway inbound paths, where a user messages a running session —
  `gateway/run_inbound.py:716` and `gateway/run_busy.py:679`
- the gateway pending-event drain and voice barge-in —
  `gateway/run_turn.py:3336`

All of these already classify as `_REASON_NEW_MESSAGE`. Every other interrupt
producer passes no message: a button press, a watchdog, a signal and a
cancelled task all carry zero user text, so none has text to replay.

Second, replay prevention is enforced at each consumer using interrupt provenance rather than message matching. `turn_finalizer.py` carries `interrupt_issuer(agent)` into the turn result. Both the CLI and gateway consumers inspect that value before deciding whether any interrupt text can become a subsequent user turn.

## Consequences

- `turn_finalizer.py` sets `result["interrupt_issuer"] = interrupt_issuer(agent)` before the following `clear_interrupt()` call, because clearing the interrupt also wipes `_tool_interrupt_reason`.
- Both consumers refuse to requeue an interrupt message when `interrupt_issuer` is non-`None`; they surface the stop to the user instead.
- The CLI gives `_show_interrupt_marker` a separate system-interrupt branch that names the issuer rather than deriving the display from `pending_message`.
- The gateway replaces its current `logger.info()`-only handling with a user-facing stop notice.
- `_CONTROL_INTERRUPT_MESSAGES` and `_is_control_interrupt_message()` are deleted.
- Any future `request_hard_interrupt()` caller is covered by the provenance rule without adding another string or call-site exception.

### Soft interrupts need explicit provenance before the guard can be trusted

`InterruptControlMixin.interrupt()` derives provenance differently for soft
interrupts: with `hard_cancel=False`, the mere presence of a message yields
`_REASON_NEW_MESSAGE`, which `USER_INTERRUPT_REASONS` treats as human, so
`interrupt_issuer()` returns `None`. The inference is circular — it concludes
the text is human because the text exists — and the consumer guard cannot
distinguish these cases.

The following producers pass system text through that path and are therefore
misreported as human stops:

- `agent/tool_executor.py:1336` and `:1747` — `"keyboard interrupt"` on Ctrl+C
- `agent/tool_executor.py:973` — `"terminal batch tool did not complete"`
- `openchia_cli/cli_shutdown.py:202` — the shutdown reason slug, de-underscored
- `agent/terminal_approval_batch.py:306` — `str(exc)`, an exception message
- `cron/scheduler.py:1920` — `"Cron fire claim ownership was lost"`
- `gateway/platforms/api_server.py:3759` — `"SSE client disconnected"` /
  `"SSE task cancelled"`

Ctrl+C is the clearest case: a human act carrying no typed text, which today
injects the literal string `"keyboard interrupt"` as the next prompt.

Each must supply a `tool_reason` or drop its message argument. Until then the
provenance guard covers hard interrupts only, and this family is unaffected by
it. This is producer-side work, but bounded and enumerable rather than a
standing obligation on every future caller.

### Producer-side work: human-initiated stops

Three human-initiated stops currently pass invented boilerplate even though the human typed nothing:

- `POST /v1/runs/{run_id}/stop` in `gateway/platforms/api_server_runs.py:1270`
- `interrupt_subagent()` in `tools/delegate_tool_registry.py:102`
- the `subagent.interrupt` RPC in `tui_gateway/methods_subagents.py:99`

These stops are correctly attributed as human: `interrupt_issuer()` returns `None`. The consumer provenance guard therefore will not, and should not, catch their boilerplate. Each producer must drop its message argument while retaining its human attribution.

## Alternatives considered

### Enforce the rule only at producers

Rejected. There are approximately twelve producer call sites, every site would need to preserve the rule indefinitely, and a new caller could silently reintroduce the bug.

### Keep the string denylist

Rejected. The cron inactivity message already demonstrates that the denylist is incomplete. Rewording any system message also defeats exact matching without causing a relevant test to fail.
