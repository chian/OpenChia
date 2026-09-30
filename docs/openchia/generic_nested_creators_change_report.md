# Generic nested Creators: change report

## Scope and files

- Architecture and threat model:
  `GENERIC_NESTED_CREATORS_ARCHITECTURE.md`,
  `docs/openchia/recursive_creator_threat_model.md`.
- Schemas and migration:
  `agent/generic_creator_models.py`, `agent/generic_creator_store.py`,
  `schemas/openchia/*.schema.json`,
  `docs/openchia/generic_creator_v1_migration.md`.
- Exact Creator handoff:
  `agent/episode_contract_models.py`, `agent/duet_service.py`,
  `agent/creator_design_session.py`, `tools/duet_tool.py`, and
  `docs/openchia/structured_creator_context.md`.
- Templates and execution:
  `agent/generic_creator_templates.py`, `agent/generic_creator_runtime.py`.
- Evidence/credit:
  `agent/episode_contract_models.py`, `agent/episode_progress_adapters.py`.
- Isolation and agent construction:
  `agent/openchia_execution_boundary.py`, `agent/openchia_agents.py`,
  `agent/tool_executor.py`, `agent/inline_tool_executors.py`.
- Interactive reliability and controls:
  `agent/chat_completion_helpers.py`, `agent/openchia_host.py`, and
  `hermes_cli/openchia_cli.py`.
- Examples and operations:
  `examples/generic_creators/*.json`,
  `docs/openchia/generic_nested_creators.md`.
- Tests:
  `tests/agent/generic_creator_fixtures.py` and the six new
  `test_generic_creator_*`, `test_evidence_gate_progress_adapter.py`, and
  `test_openchia_execution_boundary.py` files.

## Behavior added

The change adds strict v1 instance, evidence-gate, fault, repair, and platform
patch records; seven task-independent Creator roles; an authority tree with
capability/depth/aggregate-budget enforcement; a separate artifact/evidence
work graph; resumable worklists; rarefaction decisions; integration fault
routing and bounded repairs; independent qualification; content-addressed
artifacts with namespace compare-and-swap; and host-only
`evidence_gate_score_v1` progress.

Generic agent factories attach an execution boundary after plugin argument
rewrites and before dispatch. File mutations are confined to explicit roots;
source, executable, and control-plane database paths are protected. Traversal,
symlink, nested-mount, and hard-link aliases are rejected. Shell, code, and
process capabilities fail closed unless an isolated executor attests the full
mechanical boundary. Platform changes are durable proposal artifacts only.

Creator commissions no longer use a free-form instruction string. The Duet
commits complete structured documents as immutable context artifacts, the
contract carries their exact IDs and hashes, required reads are host-recorded,
and the frozen workflow records the consumed references. Purpose/required
metadata is hash-bound, lineage checks deny sibling-branch reads, and raw
secrets are rejected without rejecting legitimate policy fields such as
`token_budget`.

`openchia_scope` exposes host-derived callable tools, child-assignable
capabilities, recursion permission, bounds, role ownership, and prohibitions.
Control-plane tools are removed from the child capability catalog at both CLI
discovery and host construction. `/stop` is available on the OpenChia surface,
and active contract/workflow critics are registered beneath their parent so a
hard stop reaches their model requests. Known Codex reasoning-model streams now
receive a 120-second implicit event-gap floor; explicit operator overrides still
win.

## Test results

- Pre-change relevant baseline: **104 passed, 0 failed**.
- Final affected suite: **154 passed, 0 failed** in 16 files, including generic
  Creator models/runtime/store, context admission and lineage, evidence-gate
  scoring, execution-boundary adversarial tests, Duet/Creator tools, CLI stop,
  Codex TTFB/event-idle policy, and retry interruption.
- Independent authenticated Codex smoke call: `MODEL_OK` in 5.3 seconds.
- Ruff on every touched Python and test file: passed.
- `git diff --check`: passed.
- Repository-wide type checking retains a large pre-existing diagnostic
  baseline and is not claimed clean.

## Compatibility

The free-form Creator instruction field is intentionally unsupported. Old
Creator drafts/contracts must be recreated with structured context artifacts;
there is no automatic prose conversion. Approval invalidation, ordinary
non-Creator task Episodes, and the outer `root_episode_progress` contract remain
unchanged. The SQLite migration is additive and idempotent. Generic admission
is opt-in through `GenericCreatorEngine`; `recursive_creators_enabled` is the
rollout flag. Existing hosts do not instantiate it automatically.

## Unresolved security and operational concerns

This repository does not supply a new container/runtime sandbox. Consequently,
effectful recursive task capabilities remain disabled unless an operator
provides a real isolated executor. Its attestation is only valid if every tool
is actually routed through the claimed mount and process namespaces. Privileged
host administrators, kernel compromise, SQLite availability, and compromise of
external evidence adapters/providers remain outside the Episode boundary.

## Manual deployment

Do not deploy into a running process. A human should stop OpenChia, back up the
database plus WAL/SHM files, review the commit, run the documented tests, apply
the additive migration on a database copy, configure policy and canonical
workspace/protected roots, configure and audit an isolated executor only if
needed, and then start a new frozen host. Platform-patch artifacts require a
separate human-reviewed commit and another stopped-host rollout.
