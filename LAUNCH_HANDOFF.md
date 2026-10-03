# Default launch handoff

The launch configuration extends the existing format with an explicit Codex-login
reference. Shared function-level model slots and human launch-file approval are
pending code work.

## Files and invocation

- Launch: `/home/chia/repos/OpenChia-iterative-refiner/launch_default.json`
- Workflow credentials: `/home/chia/repos/OpenChia-iterative-refiner/.env.launch_default`
- Branch: `feat/approved-launch-slots`

```text
/launch load /home/chia/repos/OpenChia-iterative-refiner/launch_default.json
/launch preview
```

The launcher reads `WORKFLOW_CODEX_AUTH_FILE` only from `.env.launch_default`.
That variable explicitly names `/home/chia/.codex/auth.json`, the current Codex
ChatGPT login. `inherit_env` is empty and every model route uses
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
The default and both Builder roles select `sol_medium`. No 900k suffix is used.
The non-reasoning options request `enabled=false, effort=none`; provider acceptance
has not been live-verified. There are no configured fallback routes.

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
The other five route options have not been live-tested.

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
