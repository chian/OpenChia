# Recursive Creator threat model

## Protected assets

The protected control plane comprises the active host and launcher, loaded
Creator engine, Python executable, contract and approval ledgers, capability
policy, evidence acceptance and credit logic, runtime identity, and accepted
artifacts. Credentials and raw secrets are excluded from generic shared state.

## Adversaries and failures

A model-controlled Episode or compromised task input may attempt to mint
authority, alter success criteria, claim evidence, spend an ancestor's budget,
overwrite a sibling, reopen unrelated work, write or patch host source, exploit
path aliases, signal or replace host processes, substitute a modified scoring
engine, or cause a proposed platform patch to be loaded by the active host.
Concurrency, interruption, stale writes, and provider failures are also treated
as hostile conditions even when accidental.

## Enforced controls

- Strict schemas reject unknown security fields; deterministic JSON and SHA-256
  hashes bind instances, manifests, artifacts, faults, and patch proposals.
- The authority tree gives each child exactly one owner. Capability grants are
  subsets, budgets are reserved, aggregate depth/descendants are bounded,
  unused budget is returned, and cancellation/invalidation cascades.
- The work graph uses immutable artifacts, compare-and-swap namespace heads,
  producer attribution, append-only evidence/fault audit records, and explicit
  integration edges. A repair is a bounded delta to its recorded owner and
  preserves accepted evidence.
- Gate acceptance is host-only. Manifest weakening or success-criteria changes
  require a new approval. Resource exhaustion is blocked state, never success.
- Runtime identity is captured at admission and checked while running and at
  completion/qualification. A mismatch invalidates the tree.
- File mutation checks reject lexical traversal, canonical escape, symlinks,
  protected roots, nested mounts, and hard-linked files. Shell/code/process
  authority fails closed without a mechanically isolated executor attestation.
- The generic agent factory attaches the boundary after capability filtering;
  dispatch checks it after plugin argument rewrites and before execution.
- `openchia_scope` is derived from the installed host allowlist and immutable
  admitted contract. Protocol/control-plane tools are removed from the child
  capability catalog both during CLI discovery and again at host construction.
  Conversation text cannot expand either set.
- Contract and workflow critics are registered as interruptible children of
  the Duet or Creator while active. A hard stop propagates into their provider
  requests, and the host closes and unregisters them on every exit path.
- Platform patches are proposal artifacts only and require stopped-host human
  review, tests, migration notes, and a new frozen runtime identity.

## Residual operational risks

An attestation is trustworthy only if the operator's executor actually creates
the claimed mount/process namespaces and routes every effectful tool through
them. This change deliberately does not enable local shell/code/process access
for recursive Creators. SQLite availability and host filesystem integrity
remain operator responsibilities. A privileged host administrator or kernel
compromise is outside the Episode boundary. External evidence adapters and
remote providers must be separately authenticated and audited; their outputs
remain uncredited until host acceptance.
