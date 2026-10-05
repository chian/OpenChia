# ADR 0009: Implementer uses an existing coding agent for codebase work

Status: Accepted

Date: 2026-10-05

## Context

Implementer currently asks a language model to return complete source files in
JSON. The host applies those proposals and runs local checks. This permits
iteration but does not give the model a working codebase, file-editing tools or
the ability to inspect command results during an implementation attempt. A
missing initial implementation is a normal input, not a reason to block repair.

OpenChia already supplies coding-agent integrations, including a Codex app-server
client and session adapter. OpenChia should reuse those capabilities rather than
build another coding-agent tool loop. The observed interrupted HTTP response is
not proof of a transport defect or proof that this change fixes that failure.

## Decision

**Implementer uses an established coding agent to create and refine the Target
Workflow's implementation. OpenChia remains the Episode controller.**

The parent supplies the design, required behavior, editable scope, local measures
and requested return. The coding agent receives the candidate workspace and can
read files, create missing implementation, edit existing code and inspect command
results. One coding turn produces a candidate proposal, not an accepted result.
Existing code is not a prerequisite; missing plans and source can be implemented
in successive Episode units.

The integration reuses the existing model-request and response boundary. The
host captures actual workspace differences and permitted plan edits as the
ordinary typed change proposal. It records coding activity and provenance in the
existing stores. The normal proposal-admission, candidate-revision and unified
validation paths then apply. There is no second replay journal, test runner,
credit system or repair controller.

OpenChia continues to own:

- Exact parent/child assignments and report contracts.
- Admission of scoped changes against the current candidate.
- Local validation and independent parent acceptance through the shared harness.
- Credit, rarefaction and numerical continuation.
- Whole-job cancellation, API-error interruption and explicit continuation.

The coding agent's final message, tool activity and successful exit are evidence
of work, not progress credit or Episode completion. Its diagnostic commands do
not replace the assigned independent acceptance checks. A coding turn may use
multiple model/tool interactions; it does not create new Episode topology or
specialist-created Designers.

### Coding backend and environment boundaries

The workspace belongs to **Implementer**, not to the Target Workflow it is
editing. Its coding tools and sandbox are prerequisites of the refiner's coding
capability. They do not select, create or describe the Target Workflow's eventual
execution environment. That environment depends on the particular workflow;
giving Implementer tools to prepare it is separate, later work.

The Implementer contract is coding-backend-independent: assignment, workspace,
candidate changes, diagnostics, interruption and continuation have the same
meaning whether the coding capability uses Codex or Claude Code. Backend-specific
authentication, command sandboxing and native session protocols belong in
adapters. The initial implementation supports Codex only; this decision does
not claim an implemented or validated Claude Code adapter. Neither backend may
award Episode credit or replace host validation.

The coding agent uses the owning Duet's pinned model configuration and explicit
host-held credential, not the Target Workflow launch configuration or an ambient
coding-agent account. Its filesystem write authority is limited to a managed
candidate workspace. It cannot edit OpenChia, the authoritative ledger, frozen
criteria or approval records. Routine in-scope edits do not ask for another
human approval; requests to expand authority are not silently accepted.

Reuse the existing coding session and its continuation facilities. Preserve
working context across implementation units while refreshing the candidate and
measured feedback. Durable candidate state and the shared Run journal remain
authoritative; a private coding transcript cannot award credit or replace them.

## Consequences and verification

This is an integration change, not a prompt-only change. The initial adapter uses
the existing Codex app-server client/session. Unsupported model routes must be
reported explicitly, never silently changed to another provider or account.

Verify actual file creation and revision, host rejection of out-of-scope changes,
unchanged measurement/continuation ownership, cancellation, and resumption using
the existing harness. Distinguish deterministic integration checks from a live
coding-agent run. Neither establishes full Target Workflow success without its
independent acceptance result.

This extends [ADR 0007](0007-build-owns-iterative-finalization.md); it does not
replace the approved Parts → Designer → Implementer nesting or the isolated
execution boundary for Target Workflow Runs.

## Implementation

- `iterative_episode_refiner/coding.py` connects the shared model broker to the
  exact host-admitted Implementer invocation and records coding evidence.
- `iterative_episode_refiner/coding_workspace.py` stages and captures scoped files.
- `agent/refinement_coding.py` defines the shared coding-session contract,
  result, instructions and adapter selection.
- `agent/transports/refinement_codex.py` configures the existing
  `agent/transports/codex_app_server_session.py` and translates native activity
  into common coding events/results; it does not implement a new model/tool loop.
- `episode_runtime/testing_harness/service.py` installs this transport for
  Duet-bound refiner Runs. Target Workflow transports are unchanged.

Explicit credentials use the documented
[externally managed ChatGPT token handoff](https://learn.chatgpt.com/docs/app-server#3c-log-in-with-externally-managed-chatgpt-tokens-chatgptauthtokens).
The native model endpoint must equal the Duet endpoint, not the standard API
endpoint merely because Codex names its provider `openai`.

## Verification status (2026-10-05)

Deterministic checks exercise actual workspace differences, the ordinary scoped
broker and candidate admission, zero credit for an unmeasured edit, and
cancellation/resumption of unfinished work. The coding actions in those checks
are supplied test actions; they do not prove model coding ability.

The opt-in live test in `tests/iterative_episode_refiner/test_live_coding.py`
asks the real coding agent to create, execute, and revise a scheduling solver;
an independent host oracle checks its answer. With Codex 0.160.0 and the owning
Duet's `gpt-5.6-sol` / high route, authentication and a model turn succeeded, but
command execution failed with `bwrap: loopback: Failed RTM_NEWADDR: Operation
not permitted`. No source edit or correct answer was produced. The installed
Codex also refused its legacy sandbox path for this filesystem restriction.
Kernel audit then identified AppArmor's `unprivileged_userns` profile denying
bubblewrap's namespace capabilities. Loading Ubuntu's packaged
`bwrap-userns-restrict` profile fixed command startup without disabling the
global restriction. The profile permits bubblewrap to construct the sandbox
and denies capabilities to its children. No Target Workflow configuration changed.

The same live test subsequently **passed** in 187 seconds: actual source creation,
successful solver execution, native-session resumption, actual source revision,
and independent host-oracle acceptance after both versions. A separate native
sandbox check confirmed workspace writes succeed while writes outside the
workspace and network connections fail. This proves the coding capability,
not the complete build/refine/Target Workflow sequence. No full Target Workflow
success is claimed.

After isolating Codex-specific setup/events behind the shared coding interface,
the live check passed again in 174 seconds. Both revisions produced the optimal
makespan `14`, independently checked by the host; the resumed thread ID was
`01a10d40-c018-7f12-960c-391445170757`. The local JUnit receipt is
`/var/tmp/openchia-coding-live-receipt.nkVC63/junit.xml`, SHA-256
`cf46eef10a6a19eecaab2cf71277bccf97add5e0de7bc4d1374ea44b13a203ae`.
The receipt includes commands, native turn IDs and the checked answers. Focused
workspace/broker/session checks also passed (62 tests). These counts are not a
replacement for the live result.

The deployment must support Codex's workspace-write sandbox. Do not substitute
unrestricted execution or report a sandbox failure as validated implementation.
The adapter does not install host security policy automatically. See
[Implementer coding workspace setup](../openchia/implementer_coding_workspace.md)
for prerequisites and the explicit host setup. Target Workflow environment
preparation remains separate.
