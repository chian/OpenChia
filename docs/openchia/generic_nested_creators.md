# Generic nested Creators

Generic nested Creators are an opt-in control-plane extension to the existing
OpenChia Creator/Run/task Episode architecture. They are not a second agent
framework. A `GenericCreatorInstanceSpec` selects one registered role, fixes
its authority and budgets, and identifies a frozen evidence-gate manifest.

## Registered roles

- `plan_context_creator` validates planning inputs and materializes a versioned
  work graph without changing immutable parent criteria.
- `worklist_factory_creator` durably tracks bounded build/test items. An item
  becomes accepted only when its content-addressed artifact and every required
  independent check are present.
- `agent_loop_designer_creator` returns a typed attempt-observe-revise contract,
  conformance tests, recovery behavior, and terminal results.
- `integration_handoff_creator` owns integration edges, reproducible faults,
  bounded repairs, and required regression retests.
- `rarefaction_portfolio_creator` produces deterministic next-work or stop
  decisions from unique accepted yield, cost, uncertainty, and unblock value.
- `qualification_release_creator` independently verifies artifact hashes,
  required gates, and integration edges. It emits typed faults; it cannot waive
  gates.
- `generic_orchestrator_creator` composes those roles under one authority tree
  and returns the host-recognized normalized progress signal.

The role inputs and result envelopes are registered in
`agent/generic_creator_templates.py`. Domain terminology belongs in a task
specification, never in the registry or engine.

Every host-bound Duet and Creator can call `openchia_scope` to inspect its
actual role boundary. The response distinguishes tools callable by that model
from capabilities it may assign to children and includes recursion and resource
bounds from the frozen contract. This host-derived record takes precedence over
conversation text. A Duet admits the root Creator; a Creator proposes the
descendant work graph; only the host admits and launches descendants.

## Admission and execution

1. Parse the JSON record with `GenericCreatorInstanceSpec.from_record` and run
   `validate_template_spec`.
2. Construct `GenericCreatorStore` on the stopped environment's Duet database.
   Its v1 migration is additive and idempotent.
3. Construct `GenericCreatorEngine` with a frozen host policy and source root.
4. Admit the root, then admit children only through `admit_child`. The engine
   checks host policy, parent permission, capability subset, namespace,
   aggregate descendants, depth, artifacts, and reserved budgets.
5. Build an `OpenChiaExecutionBoundary` with
   `GenericCreatorEngine.execution_boundary`, then build executing agents with
   the generic agent factories. The engine-built boundary automatically
   protects source, executable, SQLite database, WAL, and SHM paths before
   effect-capable tools can dispatch.
6. Register a revision-1 `EvidenceGateManifest` under an external approval.
   Only host evidence adapters may call `accept_gate_evidence`.
7. Use `materialize_template_result`, integration acceptance, typed fault and
   repair methods, then `qualify_release`. Call `complete` only after the
   required score reaches the instance target.

`evidence_gate_score_v1` computes the accepted weight divided by total required
weight. Optional gates do not change the denominator. Blocked, skipped,
asserted, duplicate, dependency-blocked, or unchecked remote results score
zero. Child evidence is advisory until the parent/host accepts it.

This internal score does not replace the existing outer Creator contract. A
generic orchestrator launched through the established host must still expose
`root_episode_progress`, normalized to `[0, 1]`, and that outer measurement
remains backed by `run_episode_host` evidence. Ordinary Creator and task
Episodes continue to use their existing adapters unchanged.

## Isolation and platform patches

File writes and patches are limited to explicit canonical workspace roots.
Traversal, symlink escape, nested mounts, hard-link aliases, and protected
runtime paths are rejected before dispatch. Terminal, code, and process tools
are unavailable to recursive Creators unless the host supplies an attestation
for real filesystem isolation, process namespaces, process ownership, and a
read-only host runtime. `process_manage` additionally needs an Episode-owned
session ID.

This repository does not pretend the local terminal backend is a sandbox. If
no isolated executor is configured, admission of those capabilities fails.
Platform changes are stored as content-addressed `PlatformPatchProposal`
artifacts. A running Episode never applies or hot-loads one.

Complex commissions use the lossless artifact manifest described in
[structured Creator context](structured_creator_context.md). Generic instance
specifications, gate manifests, interface contracts, work graphs, and task
policies remain separate content-addressed artifacts; a model-written summary
is never a substitute for a declared input artifact.

## Migration and rollback

The migration creates only `generic_*` tables and a migration marker. Existing
Creator contracts remain schema v4; ordinary task Episodes and
`root_episode_progress` retain their current behavior. Rollout can therefore
remain disabled simply by not constructing `GenericCreatorEngine` and not
admitting generic specs.

To deploy, stop the OpenChia host, back up the SQLite database, review and apply
the commit, run the affected tests, configure workspace/protected roots and an
isolated executor if needed, then start a new host process. Never load these
modules into an already-running host. To roll back, stop the host and return to
the prior code version; the unused additive tables may remain in place.

The examples in `examples/generic_creators` are non-production. In particular,
the genome-annotation example prohibits real BV-BRC submissions and keeps
authentication human-supplied and secret-redacted.
