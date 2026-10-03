# Default launch handoff

The launch configuration supplies shared function-level model slots and an
explicit Codex-login reference. The human approves resolved settings before
Builder or Run starts.

## Files and invocation

- Launch: `/home/chia/repos/OpenChia-iterative-refiner/launch_default.json`
- Workflow credentials: `/home/chia/repos/OpenChia-iterative-refiner/.env.launch_default`
- Branch: `feat/approved-launch-slots`

```text
/launch load /home/chia/repos/OpenChia-iterative-refiner/launch_default.json
/launch preview
/launch approve HASH_FROM_PREVIEW
```

The launcher reads `WORKFLOW_CODEX_AUTH_FILE` only from `.env.launch_default`.
That variable explicitly names `/home/chia/.codex/auth.json`, the current Codex
ChatGPT login. The process environment is not consulted; every model route uses
`auth.kind=codex_login`. The account's OAuth access token is read from that exact
file at launch; no Platform API key or OpenChia credential pool is used.
Credential values are excluded from Git and from this document.

Codex owns refresh of the selected login. Each new launch reads its current
access token; an in-flight launch keeps its snapshot. OpenChia never writes to
the Codex login file or uses its refresh token. An expired token requires that
login to be refreshed in Codex, followed by a new launch.

## Model options

| Routes | Model | Effort |
| --- | --- | --- |
| sol_medium / sol_none | gpt-5.6-sol | medium / none |
| terra_medium / terra_none | gpt-5.6-terra | medium / none |
| luna_medium / luna_none | gpt-5.6-luna | medium / none |

All routes use `https://chatgpt.com/backend-api/codex` with `codex_responses`.
The `reasoning` slot selects `sol_medium`, `fast` selects `luna_none`, and
`non_reasoning` selects `sol_none`. Both Builder stages use `reasoning`.
No 900k suffix is used.
The non-reasoning options request `enabled=false, effort=none`; `sol_none` and
`luna_none` have succeeded in live calls. There are no configured fallback routes.

## Credential and execution status

Live verification on 2026-10-03 used the actual `read_launch_spec` →
`resolve_launch` → `LaunchModelTransport` path with this file:

- Default `sol_medium` route: succeeded; `gpt-5.6-sol` returned `OK` in 2.128 seconds.
- All six routes resolved to the current access token from the explicitly named
  Codex login file. No session-runtime credential was supplied to the resolver.
- The public launch record contained no access-token value.
- The Codex login file was byte-for-byte unchanged after the call.

This confirms a successful subscription-backed request on the default model,
not a remaining-quota balance or entitlement to every other listed model.
The later checks below also verified `sol_none` and `luna_none`; the Terra
routes and `luna_medium` remain untested.

Live Duet/CLI checks on the same date used the existing checkout-local profile
at `.hermes`, with session `20261003_022450_e4153a`:

- Duet asked for launch settings, saved a proposal through its actual tool,
  and returned the human apply/preview/approve commands.
- `/launch apply` saved the proposal. Launch preparation rejected both missing
  approval and a wrong approval hash, with zero launch model calls recorded.
- `/launch approve` persisted; reopening the CLI in another process retained
  the approval.
- Two `structured_json_completion` calls passed through the worker wire record,
  `ScopedModelBroker`, and real Codex transport under one Episode path. The
  `reasoning` and `non_reasoning` slots selected `sol_medium` and `sol_none`,
  respectively; both returned the requested calculation correctly. Receipts
  recorded separate slots and effective medium/none reasoning settings.
- A changed slot assignment required fresh approval. The existing launch kept
  `reasoning → sol_medium`; the newly approved launch used `reasoning → sol_none`.
  Further real requests succeeded on `luna_none` and the changed `sol_none` route.
- An ambient `WORKFLOW_CODEX_AUTH_FILE` with no declared `.env` source was
  rejected. The real calls left the selected Codex login file unchanged, and
  the public configuration contained no access token.

Session `20261003_022707_046ef9` started with an ordinary oscillator workflow
design request, without a launch-setup instruction. Duet read its status and
asked whether to load or prepare a project launch file during that first turn.

These checks exercised conversational setup, the CLI approval path, persistence,
and real model routing. They did not materialize or execute a complete workflow.
Local sessions and credentials are ignored runtime state, not PR contents.

The workflow `.env` also contains a copied Firecrawl key, whose validity and quota
are unverified. That copied key came from `/home/chia/repos/nano-graphrag/.env`;
the launcher does not read that other workflow's file.
No SERP key was found during the earlier inspection. Firecrawl is not connected
to the current launch schema. External service credentials are needed only for
workflows that use those services.

The previous execution-backend check selected `systemd`, then failed with
`RunExecutionError: cannot read host cpu.max`. Full confinement preflight did
not pass. That result has not been rechecked after cleanup; credentials alone
do not resolve it. No execution-boundary workaround has been applied.
