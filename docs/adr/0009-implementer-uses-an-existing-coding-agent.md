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
adapters. Codex and Claude Code adapters are implemented; Claude Code has not
been live-validated. Neither backend may award Episode credit or replace host
validation.

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

### Private native configuration

The repository ships `scripts/openchia-codex` and its sandbox defaults.
Standalone launches, app-server launches and configuration migration share
`openchia_cli/codex_runtime_home.py`. They use the active OpenChia profile's
private Codex home; Implementer supplies a separate home per coding context.
Resumption uses that same private home. Existing personal transcripts and
settings are not automatically imported or used as a fallback.

`CODEX_HOME` is set only in the child environment, after inherited `CODEX_*`
thread and permission settings have been removed from that environment. The
parent environment and personal Codex files are not changed. The user's own
Codex sessions may retain full permissions while OpenChia's sessions remain
sandboxed. Private configuration is not itself a filesystem sandbox.

The launcher and coding agent do not install host packages/security profiles,
change AppArmor/sysctl settings, or substitute unrestricted execution.
Report a sandbox startup failure separately from model or implementation
failure. Administrator-controlled native sandbox setup is a separate, explicitly
documented prerequisite, not a hidden repair inside a coding run.

### Native sandbox prerequisites (2026-10-05 amendment)

The user accepted Ubuntu's packaged bubblewrap AppArmor profile for now,
conditional on installation support or explicit installation instructions. We
choose explicit instructions, not automatic privileged installation. This
supersedes the original unchanged-host acceptance condition; it does not
retroactively authorize the earlier intervention or change private-config rules.

Delegate OS enforcement to the existing coding runtime: Codex uses bubblewrap
and seccomp on Linux, Seatbelt on macOS, and its native Windows sandbox on
Windows. AppArmor is a Linux prerequisite where required, not a cross-platform
OpenChia dependency. Native Windows' stronger sandbox requires its own
administrator-approved setup; do not imply that a weaker fallback is equivalent.
Only Ubuntu has been verified here. Other OS integrations and live Claude Code
remain unverified, with no new containers or Target Workflow environment changes.

The [workspace setup guide](../openchia/implementer_coding_workspace.md#native-sandbox-prerequisites)
contains platform references and explicit Ubuntu installation instructions. They
use the distribution's profile, preserve existing policy, avoid installing
unrelated profiles and do not disable AppArmor or the namespace restriction.

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

## Earlier verification (2026-10-05; before private-launch correction)

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

The AppArmor installation above was an inappropriate machine-wide intervention,
and was subsequently undone. Those historical passes do **not** establish that
the corrected repository-owned launcher works on the unchanged host.

## Private-launch verification (2026-10-05)

Configuration checks pass, including profile isolation and preservation of the
personal Codex configuration. Initially the corrected private launcher reached
Codex 0.160.0 but native commands failed with the bubblewrap error above; the
legacy sandbox also refused filesystem-restricted execution.

After the user explicitly requested restoring the missing host setup,
`/etc/apparmor.d/bwrap-userns-restrict` was restored from Ubuntu's packaged
profile and loaded. This machine-wide prerequisite restoration is separate from
the repository launcher; it is not an automatic installation or fallback.
The private app-server then permitted workspace writes/Python execution and
denied outside-workspace writes and network sockets under its workspace policy.

The corrected launch path's real coding check passed in 170.5 seconds on this
repaired host: creation, execution, native-thread resumption, source revision,
and independent host-oracle acceptance after both versions. Both answers had
optimal makespan `14`. The thread was
`01a10e27-8cfe-7833-9bab-c432611806d4`; the local receipt is
`/var/tmp/openchia-private-coding-receipt.fjdLmj/junit.xml`, SHA-256
`518f21e0b444e37ad9742cc4c72edb05391827428d9837b6a3f6ec68760704e1`.
The personal Codex configuration and global namespace restriction were unchanged
during verification. This does not prove operation without the restored host
profile. It did not satisfy the original unchanged-host acceptance condition;
it satisfies the amended focused goal now that the user has accepted the
prerequisite with explicit installation instructions.

The standalone executable launcher also passed `./scripts/openchia-codex
--version` through the existing repository bootstrap, exiting 0 with Codex
0.160.0. Normal runtime-only PM activation refreshed user-owned dependency state;
it did not change personal Codex settings, shell startup files or host security
policy. The private workspace-default configuration was created as intended.

The deployment must support Codex's workspace sandbox. Do not substitute
unrestricted execution or report a sandbox failure as validated implementation.
See
[Implementer coding workspace setup](../openchia/implementer_coding_workspace.md)
for the repository launcher and verification procedure. Target Workflow environment
preparation remains separate.
