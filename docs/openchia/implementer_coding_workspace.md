# Implementer's coding workspace

This environment belongs to Implementer. It contains the candidate source and
the admitted assignment so a coding agent can inspect, create, edit and run
diagnostic commands. It is **not the Target Workflow's execution environment**.
The latter depends on the particular workflow and is not configured here.

OpenChia captures actual file differences and permitted plan edits as proposals.
The existing host admission, shared validation harness, parent reports, credit
and rarefaction decide whether those proposals constitute progress. A coding
agent's final prose or successful command is not acceptance.

## Focused implementation goal

Make Implementer's coding workspace operational using a repository-shipped
OpenChia coding-agent launcher and private configuration, with workspace
confinement intact and no changes to the user's personal Codex settings or
machine policy. Preserve backend-independent assignments and results. Prove
that the real coding agent can create, run, resume and revise a program whose
answer passes an independent check through OpenChia's existing integration.

Completion requires all of the following:

- The launcher and sandbox defaults are checked into this repository. Another
  user of the repository gets the same launch behavior without manually editing
  global configuration or shell startup files.
- OpenChia's Codex launches, configuration migration and session resumption use
  OpenChia-owned state. Implementer retains private per-context state. Neither
  an inherited `CODEX_HOME` nor the personal `~/.codex/config.toml` supplies or
  receives OpenChia's permission changes.
- `CODEX_HOME` is set only in the launched process's environment. The user's
  personal Codex sessions can retain full permissions while OpenChia's coding
  sessions remain sandboxed. Configuration separation alone is not a sandbox.
- No host package installation, AppArmor change, sysctl change, global Codex
  migration or switch to unrestricted execution is used to obtain a passing
  result. A launch failure is reported accurately, not worked around by changing
  the user's machine.
- The existing native coding runtime is reused. The owning Duet still supplies
  the model, effort and credential; the common coding interface continues to
  support Codex and Claude Code without changing Episode control or acceptance.
- Verification distinguishes configuration isolation from actual coding ability:
  global settings remain unchanged, and a real Codex coding session creates,
  executes, resumes and revises source that passes an independent answer check.
  A prior pass obtained after a machine-wide workaround does not establish this
  corrected launch path. Unrun checks remain explicitly unverified.

Reuse the shared test runner; do not add a separate replay mechanism. Target
Workflow environment preparation remains excluded. This goal does not claim
full build/refine/Target Workflow acceptance or a live Claude Code result.

## Coding backends

`agent/refinement_coding.py` supplies a common session/result interface and
selects an implemented adapter for the owning Duet's pinned route. Native
authentication, session persistence, sandbox configuration and event translation
belong in the adapter. `agent/transports/refinement_codex.py` uses the existing
Codex app-server session. `agent/transports/refinement_claude.py` uses Claude
Code's streaming CLI. The Claude adapter is implemented but has not been
live-validated. Neither is silently substituted for the other. The Episode
repair loop and host admission are not specific to either backend.

The current Codex adapter uses the owning Duet's model, effort and explicit
credential. `model.codex_bin` selects the installed executable through the
existing configuration mechanism. Private native state lives beside the managed
coding workspaces, outside the source imported as a proposal. Session identity,
native evidence and activity are recorded in the shared campaign store.
No extra replay system is introduced.

## OpenChia-owned Codex launch

`scripts/openchia-codex` is the repository launcher. It passes arguments to the
installed Codex executable selected by OpenChia's existing `model.codex_bin`
setting. Its default configuration lives in
`openchia_cli/codex_runtime_home.py`; runtime configuration and native state live
under `<active OpenChia profile>/codex`, not the user's personal Codex home.
The app-server and migration use the same location rule. Implementer supplies
its own per-context state directory through that same launch implementation.
Migrated OpenChia tool callbacks also bind to the owning profile, including when
one host process serves multiple profiles; they do not use its launch profile.
Offline model discovery and the optional compaction evaluation's Codex launch
and rollout lookup use the same private-home resolver.

The launcher removes inherited `CODEX_*` variables from the child environment,
then sets the child's private `CODEX_HOME`. Parent thread IDs and permission
settings are not forwarded, and the parent environment is unchanged. It
initializes a missing private configuration from the checked-in workspace
permission default.
Existing private settings are preserved. No personal Codex configuration,
credentials or transcripts are automatically copied into the private home.
Implementer continues to receive its credential from the owning Duet. Standalone
use can authenticate separately with `scripts/openchia-codex login`.

Do not run global configuration migrations or install machine security profiles
as a repair for this integration. A native sandbox startup failure must be
reported separately from model/API errors and unsuccessful implementation work.
It must not silently select unrestricted execution. No Target Workflow
environment is configured by this launcher.

## Verification and continuation

Use the existing test runner for the opt-in real coding check:

```bash
scripts/run_tests.sh tests/iterative_episode_refiner/test_live_coding.py \
  -j 1 --file-timeout 1200 -- \
  --live-coding-profile=/absolute/path/to/the/owning/profile \
  --live-coding-binding=EXACT_SAVED_DUET_BINDING_ID -q -rP
```

This reads the selected saved model binding and credential without changing the
profile. The real coding agent must create and execute a scheduling solver, then
resume and revise it. An independent host oracle checks each result. Candidate
files and native state stay in the test runner's temporary workspace. Standard
pytest `--junitxml=PATH -o junit_logging=all` can retain the test receipt,
including commands and checked answers. This is capability verification, not
full Target Workflow acceptance.

Configuration-isolation checks exercise A → B → A profile switching, migration,
session ownership and the repository launcher. These are separate from actual
coding ability. The initial private-launch check on 2026-10-05 reached Codex
0.160.0, but both CLI and app-server command execution failed with
`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. The legacy
sandbox option also refused filesystem-restricted execution.

The user subsequently requested restoration of the missing host configuration.
Only `/etc/apparmor.d/bwrap-userns-restrict` was restored from Ubuntu's packaged
profile and loaded. This is a **machine-wide prerequisite**, not repository
configuration or a change performed by the launcher. No package was installed,
the global user-namespace restriction remained enabled, and the personal Codex
configuration was unchanged. Through the existing app-server with private
`:workspace` defaults, workspace writes and Python execution then succeeded;
writes outside the workspace (outside `/tmp`) and network socket creation failed.

On that repaired host the real private-launch coding check **passed** in 170.5
seconds, using the saved Duet binding for `gpt-5.6-sol` with high effort. Codex
created and executed `solve.py`, then resumed thread
`01a10e27-8cfe-7833-9bab-c432611806d4`, revised its validation code and executed it
again. Both answers passed the independent host oracle with optimal makespan
`14`. There was no manually supplied answer or workspace repair. The local
receipt is `/var/tmp/openchia-private-coding-receipt.fjdLmj/junit.xml`, SHA-256
`518f21e0b444e37ad9742cc4c72edb05391827428d9837b6a3f6ec68760704e1`.

This proves coding and native resumption on the repaired host. It **does not
prove the unchanged-host/no-machine-wide-workaround completion condition above**.
That condition remains unverified; the earlier or current live result must not
be presented as satisfying it. No full Target Workflow or live Claude Code
acceptance is claimed.

The launcher test runs the real Python entry point and child process. Direct
execution through its standard repository `_hermes-python` shebang also passed:
`./scripts/openchia-codex --version` exited 0 with `codex-cli 0.160.0` and created
the private workspace-default configuration under the owning OpenChia profile.
The normal runtime-only PM activation refreshed the repository-managed
dependencies and activation stamps; no activation state was fabricated. This
is user-owned dependency setup, not a system package installation. The personal
Codex configuration, shell startup file, AppArmor profile and global namespace
setting were unchanged by this check.

In production, ordinary Run continuation reuses committed responses and resumes
unfinished coding state only after its prior owner has stopped. A changed
backend, model binding or instruction prefix opens a new native context.
Authoritative candidate revisions and measurements remain in the shared stores.
See [continuation](build_continuation.md) and [ADR 0009](../adr/0009-implementer-uses-an-existing-coding-agent.md).
