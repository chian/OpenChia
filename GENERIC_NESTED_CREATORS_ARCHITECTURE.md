# Generic nested Creator architecture

## Baseline inventory

OpenChia already has one authority-bearing Episode framework. This extension
uses it rather than adding a parallel agent hierarchy.

- `agent/episode_contract_models.py` owns strict, immutable task and Creator
  contracts. Unknown fields are rejected, JSON is canonicalized, and contract
  and workflow identities are SHA-256 content hashes.
- `agent/duet_service.py` owns admission. It binds frozen contract and workflow
  artifacts to exact human approvals, rejects capability escalation, validates
  recursive-Creator permission and depth, and admits nested Creators only from
  their parent's latest frozen workflow design.
- `method_loop/episode.py`, `agent/creator_episode.py`,
  `agent/creator_runtime.py`, and `agent/workflow_runtime.py` own launching and
  nesting. `EpisodeTree` validates topology and depth; the Creator controller
  stops on host-measured success, stagnation, or a proposal bound. Duet
  boundary messages provide pause/cancel behavior between Creator units.
- `agent/openchia_agents.py` replaces each agent's advertised tools with an
  exact capability allowlist. Ordinary task Episodes cannot create Episodes.
- `agent/episode_progress_adapters.py` and the measured-outcome models own
  progress arithmetic. `agent/duet_service.py` accepts credit evidence only
  when it was registered by the configured source, and the existing
  `root_episode_progress` measurement remains the interactive Creator's
  normalized root signal.
- `agent/duet_store.py` is the durable SQLite authority ledger. Drafts,
  artifacts, approvals, evidence, launches, and events are canonical JSON and
  append-oriented; artifact IDs and hashes are deterministic.
- The inherited mutation tools are `write_file`, `patch`, `terminal`,
  `execute_code`, and `process_manage`. File tools have sensitive-path,
  symlink, device, approval, and stale-write guards, while terminal/code tools
  block known host lifecycle operations. They do **not** provide a general
  per-Episode filesystem or process sandbox. `execute_code` explicitly
  documents that its default project mode is not an isolation jail, and
  `process_manage` resolves a supplied session ID before checking no OpenChia
  Creator ownership boundary.

Pre-change baseline (2026-09-29): 124 tests passed in 12 relevant test files
using `scripts/run_tests.sh`; zero failures.

## Coherent extension

The generic framework is a typed control-plane layer on the existing Creator
runtime:

1. A strict, versioned `GenericCreatorInstanceSpec` selects one registered
   template and declares its authority parent, immutable success references,
   work-graph inputs, evidence gates, capabilities, namespace, budgets,
   cancellation, retry, and fault ownership.
2. A durable generic-Creator store extends the existing Duet SQLite database.
   It records instance state, budget reservations, content-addressed artifacts,
   compare-and-swap namespace heads, gate manifests and acceptances, work
   items, typed faults and repair requests, runtime identities, and an
   append-only audit log.
3. A single `GenericCreatorEngine` interprets registered template identifiers.
   Template handlers are task-independent host state machines. They do not
   contain genome, provider, workflow-language, or workspace-specific names.
4. The authority tree is persisted independently from the work graph. Child
   admission reserves budgets from its one parent, intersects capabilities,
   checks aggregate descendant/depth limits, and captures the active runtime
   identity. Completion returns unused reservations. Cancellation or runtime
   invalidation propagates down the authority tree.
5. Work-graph edges connect content-addressed artifacts and gates. Integration
   faults point back to an owning instance and produce bounded delta repair
   requests. Reopening preserves accepted artifacts and evidence and schedules
   affected integration edges for regression testing.
6. `evidence_gate_score_v1` is host-only. A frozen gate manifest plus
   host-accepted evidence determines the weighted required-gate score. Model
   assertions, skipped/blocked gates, duplicate evidence, and unchecked remote
   work receive no credit.
7. Existing Creator contracts, ordinary Episodes, exact approval invalidation,
   and `root_episode_progress` remain unchanged. Generic instances are an
   additive schema and runtime path.

## Threat model and security boundary

Recursive Creators amplify authority: a compromised child could otherwise
mint descendants, consume the ancestor's budget, rewrite shared artifacts,
claim unchecked evidence, modify the running host, or signal host processes.
The trusted computing base is the active host/launcher, contract and approval
ledger, capability dispatcher, progress/evidence implementation, loaded
generic-Creator engine, and SQLite authority store.

The extension enforces these rules mechanically:

- Security-relevant schemas reject unknown fields. Children receive only an
  equal or narrower capability set and reserved sub-budgets. They cannot write
  parent contracts, success criteria, approvals, evidence policy, or weights.
- Namespace writes are compare-and-swap operations over content hashes.
  Artifacts are immutable, producer-attributed records; secret-shaped fields
  and raw secret values are rejected rather than persisted;
  merges are explicit artifacts. Evidence and faults are append-only.
- Each admission records a deterministic runtime identity. Progress,
  completion, and qualification recheck it. A mismatch invalidates the run and
  cancels descendants; a resource cap is never mapped to success.
- Direct file mutations are allowed only beneath canonical explicit workspace
  roots. Traversal, symlink escapes, nested mount points, hard-link aliases,
  and protected host/runtime roots are rejected before dispatch.
- Local `terminal`, `execute_code`, and `process_manage` are not accepted as an
  isolation boundary. Generic recursive instances may receive them only when
  the host supplies an attested isolated executor with filesystem namespace,
  process namespace, and per-instance ownership enforcement. Otherwise
  admission fails closed. Merely naming a Docker or sandbox mode is not an
  attestation.
- Platform changes are emitted only as content-addressed patch proposals with
  tests, migration notes, affected boundaries, and an expected next runtime
  identity. The active host never applies or hot-loads them.
- Credentials and raw secrets are excluded from generic shared state. Task
  specifications may name secret requirements but authentication remains an
  external human/control-plane operation.

This fail-closed restriction is the smallest coherent extension because the
current local terminal implementation cannot mechanically prevent arbitrary
filesystem access or Unix signals. Pretending its command-pattern guards are a
sandbox would violate the requested self-modification guarantee.

## Rollout and compatibility

The database migration is additive and idempotent. Existing rows and schema
versions remain readable. Generic Creator admission is explicit; current Duet,
Creator, Run, and ordinary task paths do not opt into it automatically. An
operator must configure an isolated executor before assigning effectful shell,
code, or process capabilities to a recursive generic instance. No migration
restarts or mutates a running host.
