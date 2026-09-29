# Generic nested Creators: change report

## Scope and files

- Architecture and threat model:
  `GENERIC_NESTED_CREATORS_ARCHITECTURE.md`,
  `docs/openchia/recursive_creator_threat_model.md`.
- Schemas and migration:
  `agent/generic_creator_models.py`, `agent/generic_creator_store.py`,
  `schemas/openchia/*.schema.json`,
  `docs/openchia/generic_creator_v1_migration.md`.
- Templates and execution:
  `agent/generic_creator_templates.py`, `agent/generic_creator_runtime.py`.
- Evidence/credit:
  `agent/episode_contract_models.py`, `agent/episode_progress_adapters.py`.
- Isolation and agent construction:
  `agent/openchia_execution_boundary.py`, `agent/openchia_agents.py`,
  `agent/tool_executor.py`.
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

## Test results

- Pre-change relevant baseline: **124 passed, 0 failed** in 12 files.
- New focused Creator/security suite: **60 passed, 0 failed** in 6 files.
- Affected OpenChia/tool suite excluding the known baseline failure:
  **193 passed, 0 failed** in 20 files.
- Expanded run including `test_run_agent.py`: **473 passed, 1 failed**. The
  failure is
  `TestAgentRuntimePostHookOwnershipSync::...delegate_task-tool_args13`.
  A detached, untouched `43ca5aa613` worktree reproduced the same filtered
  result (**13 passed, 1 failed**), so it is not introduced by this change.
- Ruff on all touched Python and test files: passed.
- Ty on the five new implementation modules: passed. Repository-wide checks
  on legacy touched modules retain pre-existing diagnostics and are not claimed
  clean.

## Compatibility

Existing schema-v4 Creator contracts, approval invalidation, Duet state,
ordinary task Episodes, and the outer `root_episode_progress` contract remain
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
