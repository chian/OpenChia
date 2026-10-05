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

Make Implementer's coding workspace operational with confinement intact, preserve
backend-independent assignments and results, and verify real source creation,
execution, resumption and revision against an independent answer check. Reuse
the existing coding runtime and shared test runner. This work excludes Target
Workflow environment preparation and does not complete the broader end-to-end
build/refine/Target Workflow acceptance goal.

## Coding backends

`agent/refinement_coding.py` supplies a common session/result interface and
selects an implemented adapter for the owning Duet's pinned route. Native
authentication, session persistence, sandbox configuration and event translation
belong in the adapter. The current implementation is
`agent/transports/refinement_codex.py`, using the existing Codex app-server
session. Claude Code support requires another adapter and verification; it is
not implemented or silently substituted for Codex. The Episode repair loop and
host admission are not specific to either backend.

The current Codex adapter uses the owning Duet's model, effort and explicit
credential. `model.codex_bin` selects the installed executable through the
existing configuration mechanism. Private native state lives beside the managed
coding workspaces, outside the source imported as a proposal. Session identity,
native evidence and activity are recorded in the shared campaign store.
No extra replay system is introduced.

## Linux / Ubuntu sandbox prerequisites

The Codex adapter uses workspace-write confinement with command network access
disabled. Bubblewrap must be able to construct that sandbox. Test its startup
without making a model call, from a disposable coding workspace:

```bash
codex sandbox -c 'sandbox_mode="workspace-write"' \
  -c 'sandbox_workspace_write.network_access=false' /bin/true
```

On Ubuntu 24.04, a failure such as
`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted` can be an
AppArmor denial. Confirm against the kernel audit; do not interpret this as a
provider API error or a rejected implementation. Ubuntu's packaged
`bwrap-userns-restrict` profile allows bubblewrap's namespace setup while
retaining capability restrictions on its child commands.

An operator can install the profile following the
[official Codex sandbox prerequisites](https://learn.chatgpt.com/docs/sandboxing#prerequisites):

```bash
sudo apt install bubblewrap apparmor-profiles apparmor-utils
sudo install -m 0644 \
  /usr/share/apparmor/extra-profiles/bwrap-userns-restrict \
  /etc/apparmor.d/bwrap-userns-restrict
sudo apparmor_parser -r /etc/apparmor.d/bwrap-userns-restrict
```

Inspect package changes and any existing destination profile before replacing
local policy. This is explicit machine setup, not an automatic action of an
Episode. Do not disable AppArmor globally or switch the coding agent to
unrestricted execution. The profile applies to `/usr/bin/bwrap` on the machine;
it does not select or provision an environment for a Target Workflow.

For the 2026-10-05 development verification, bubblewrap was already installed.
To avoid unrelated AppArmor upgrades, only the profile was extracted from the
APT-verified Ubuntu `apparmor-profiles` package
`4.0.1really4.0.1-0ubuntu0.24.04.8`, installed at the path above, and loaded.
`kernel.apparmor_restrict_unprivileged_userns` remained `1`.

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

In production, ordinary Run continuation reuses committed responses and resumes
unfinished coding state only after its prior owner has stopped. A changed
backend, model binding or instruction prefix opens a new native context.
Authoritative candidate revisions and measurements remain in the shared stores.
See [continuation](build_continuation.md) and [ADR 0009](../adr/0009-implementer-uses-an-existing-coding-agent.md).
