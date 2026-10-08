# Human-directed Target Workflow coding

`/code` opens a saved coding conversation for the current Target Workflow.
The coding assistant has the existing native backend's file-editing and command
tools in a working copy of that workflow. It uses the owning Duet's pinned model,
effort and authentication through the same coding adapter as Implementer.

The input remains available while the assistant works. Each human message is
saved immediately and handled in order at a turn boundary. Sending a message
keeps the current turn running. `/status` shows queued, being-handled, answered,
interrupted, failed and uncertain-delivery messages, plus elapsed time since
backend activity.

## Controls

- `/stop` interrupts the current coding turn and retains edits and queued input.
- `/continue` handles the remaining queue. An interrupted or uncertain-delivery
  message is retained for inspection rather than automatically repeated.
- `/diff` shows a coherent draft after the current turn has finished or stopped.
- `/back` saves the conversation and returns to Duet.
- `/code resume` reopens its saved working copy and native conversation, paused
  for inspection; `/continue` resumes queued work.
- `/handoff` freezes the three design/source layers and the intended changes as
  one proposal. Review with `/episode`, approve with `/approve`, then `/build`.

There is no coding-turn timeout. Stop is an explicit human control. Native
provider failures remain visible and pause message delivery.

## Editing and authority

Opening the conversation requests a stop through the host's existing Target
Workflow cancellation path. The working copy is taken after its writer stops.
Messages can be added during this preparation. A live coding conversation owns
editing; ordinary build and Run commands require it to close or hand off first.
If another OpenChia process still owns execution, preparation reports that the
owner must finish pausing instead of taking its files concurrently.

The working copy contains:

- `architecture.json`: the approved nested Episode design.
- `materialization.json`: implementation choices keyed by stable Episode ID;
  null entries represent missing plans.
- `episodes/<local_id>.py`: available Episode source, with host declarations
  removed and reattached by the normal materializer.
- The Target Workflow environment recipe, when present.
- `change_intent.md`: proposed behavior and the corresponding design changes.
- `.openchia-context.json`: read-only baseline, provenance, model-slot and
  diagnostic context.

Working copies and native conversation state live beneath
`<active profile>/openchia/workflow_edits/<edit_id>/`. The conversation and
delivery records use the existing Duet artifact store. A reopened draft checks
its baseline and predecessor candidate; later autonomous changes require a new
draft so saved work cannot silently overwrite them.

The assistant edits architecture, materialization and source together. Its
intent synthesis remains a proposal grounded in the saved human messages.
The ordinary human approval binds the immutable submitted snapshot; later disk
edits cannot change what `/build` adopts. A rejected submission leaves the
conversation open for correction.

The next Refiner campaign adopts those exact choices and source through the
ordinary plan validators. Its Episodes construct missing parts and obtain source
and package admission as they iterate. Partial work
is retained: raw source and unadmitted choices have submission provenance, and
their diagnostics remain visible. Scoped planning inputs expose unadmitted
choices for the assigned Episode. Human-approved implementation intent enters
the Refiner's requirement catalog alongside approved architecture coverage.
Existing observations remain evidence about their original candidate; the new
revision must establish its own results.

A construction campaign can be opened before it has a source-admission receipt.
After stopping its writer, `/code` checkpoints the actual candidate with the
existing static source checks. The resulting review baseline may be blocked;
the editable snapshot preserves all raw candidate files and plan choices. This
inspection uses the recorded nonsecret launch identity and needs no model call
or credential lookup. It is a handoff for human review, not a prerequisite build
pass before the Refiner starts.

This capability edits the Target Workflow. It does not route instructions into
individual Refiner Episodes or edit OpenChia, Refiner code or personal runtime
configuration. Diagnostic commands are observations, not approval or credit.

## Verification so far

Live CLI checks on 2026-10-06 exercised actual native file inspection, a second
message saved while the first was running, ordered replies, process close and
reopen, retained native conversation context, and visible replies above the
editable input. The display check exposed and corrected a nested-event-loop
stdout issue; the corrected CLI also exited normally.

Before the direct construction entry replaced the separate edited-source path,
an isolated call through that materializer used an unchanged
persisted partial build. It retained three planned Episodes, one source module
and all submitted choices, and returned a blocked receipt with the actual
missing-plan/module/edge findings. No model response or acceptance was mocked.
This checks materialization preservation, not a successful workflow repair.

The complete live edited draft → human approval → revised build → Refiner
pickup sequence, cross-process active-writer transfer, and non-Codex backend
execution remain unverified. The independent orbital-survival experiment has
not been edited or restarted for these checks.
