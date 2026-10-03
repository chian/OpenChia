# Scheduling benchmark launch handoff

Restored from the earlier session record after accidental deletion during cleanup.
The launch configuration uses the currently implemented PR32 format. Shared
function-level model slots and human launch-file approval are pending code work.

## Files and invocation

- Launch: `/home/chia/repos/OpenChia-iterative-refiner/launch.scheduling-benchmark.json`
- Workflow credentials: `/home/chia/repos/OpenChia-iterative-refiner/.env.scheduling-benchmark`
- Branch: `feat/approved-launch-slots`

```text
/launch load /home/chia/repos/OpenChia-iterative-refiner/launch.scheduling-benchmark.json
/launch preview
```

The launcher reads `WORKFLOW_CODEX_ACCESS_TOKEN` only from the named workflow
credential file. `inherit_env` is empty and every model route uses `auth.kind=env`.
The configuration does not borrow session credentials or discover another account.
Credential values are excluded from Git and from this document.

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

Credential presence is not evidence of validity, available quota, or model
entitlement. No successful live request has verified these routes. The operator
has warned that some existing credentials have exhausted quota.

The deleted workflow file contained a one-time copy of the Codex access token from
`/home/chia/.hermes/auth.json` and a Firecrawl key from
`/home/chia/repos/nano-graphrag/.env`. These are recovery sources, not launch-time
sources. The recovered workflow file must be refreshed explicitly when needed.
No SERP key was found during the earlier inspection. Firecrawl is not connected
to the current launch schema; the initial scheduling benchmark needs only model
access.

The previous execution-backend check selected `systemd`, then failed with
`RunExecutionError: cannot read host cpu.max`. Full confinement preflight did
not pass. That result has not been rechecked after cleanup; credentials alone
do not resolve it. No execution-boundary workaround has been applied.
