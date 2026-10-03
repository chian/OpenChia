# Default launch handoff

The launch configuration supplies shared function-level model slots and an
explicit Codex-login reference. The human approves resolved settings before
Builder or Run starts.

## Scope clarification — 2026-10-03

This file configures testing of the **Target Workflow**, not the
IterativeEpisodeRefiner. The refiner and its reasoning children use the owning
Duet's model/provider configuration; no separate refiner launch file is needed.
Calling a Target Workflow test through the harness must not switch the refiner's model.
The Builder roles below remain target Builder settings, not refiner settings.
See the [routing boundary](docs/openchia/episode_launch_configuration.md#duet-refiner-and-target-model-boundary).

The launch-support commits were integrated into the harness checkout as
`6cbd04f3e8` and `1e42fee1c9`. That checkout still uses the original absolute
launch path below; it does not have a copied credential file. Resolution there
passed without a model call. This is not a refiner execution receipt.

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

### PR review verification

Session `20261003_033740_938924` exercised the review fixes through the real
Duet and CLI with project-defined slots `big` and `small`:

- Duet persisted a proposal with `big → sol_medium`, `small → luna_none`,
  Builder planning on `big`, and emission on `small`.
- Applying it over an old-format file first returned the explicit `--replace`
  instruction and left the destination unchanged. The confirmed replacement
  succeeded. The event recorded the prior content hash; an old-file marker
  was absent from the event records.
- The reasoning library's selection and execution slot arguments were detected
  as dependencies even with an empty `prompt_specs` list. Real structured-JSON
  calls using those library options crossed worker serialization and the broker,
  succeeded on `small` and `big`, and recorded their respective routes.
- Actual Builder construction selected planning `big` and emission `small`;
  the materializer identity recorded them separately. Real structured-JSON
  calls using each stage's options succeeded with those slots.
- Missing prompt slots, missing library slot arguments, and a required slot
  absent from the launch each produced an explicit diagnostic. An environment
  reference in a public model field was rejected by launch validation.
- Reopening in another process retained the approval and both custom slots.
  Applying over that valid current-format file worked without `--replace`,
  required a new approval, and accepted it.

These calls verify slot plumbing, not the reasoning loop, complete Builder
materialization, or confined workflow execution. Existing fixture callers were
updated for the explicit slot arguments; no new mock test suite was added or
used as validation.

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

2026-10-03 correction: that systemd result records the previous backend choice,
not the required Target Workflow execution path. [ADR 0005](docs/adr/0005-target-workflow-runs-use-containers.md)
selects containers on Linux/macOS and container-only acceptance. Implementing
that selection and configuring the existing container executor remain pending;
systemd repairs are not acceptance prerequisites.
