# Structured Creator context

Creator commissions use a versioned `design_context` manifest whose entries
reference immutable structured artifacts by ID and SHA-256 digest. There is no
free-form instruction-string alternative.

## Information flow

1. The Duet commits complete structured documents with
   `creator_context_artifact`. Typical kinds are `task_specification`,
   `work_graph`, `interface_contract`, `evidence_manifest`, `safety_policy`,
   `decision_ledger`, `reference`, and `example`.
2. The host canonicalizes the document, rejects secret-shaped keys and raw
   secret-shaped values,
   stores it immutably, and returns its ID, digest, kind, schema version,
   purpose, and required flag.
3. Each explicit Creator Episode contract carries only those exact references
   in its `design_context` manifest. One required artifact is the entry point.
4. Admission verifies existence, Duet ownership, producer ancestry, metadata,
   hashes, and byte budgets. Missing or stale context is a blocking contract
   deficit.
5. The Duet reads whole artifacts with `creator_context_read` while designing.
   There is no offset, pagination, or model-generated summary in the
   authoritative path.
6. Approval freezes the exact referenced artifacts with the workflow. The host
   delivers them only if execution reaches that Creator node; no second model
   reconstructs or summarizes the design.
7. A Creator may commit new structured artifacts for nested Creator contracts.
   Descendants may consume Duet-owned artifacts and artifacts produced in their
   authority lineage, but not unrelated branch artifacts.

`duet_status` exposes artifact metadata so an interrupted Duet can recover the
exact document with `creator_context_read`. It does not repeat all artifact
content on every turn. It also exposes `creator_context_policy`: an empty
artifact list is valid for workflows containing only ordinary task Episodes.
Context is required only for an explicit Creator node. Workflow, approval, and
prior Creator-contract artifacts are not interchangeable with context receipts.

## Role and capability scope

`openchia_scope` is the authoritative, read-only introspection channel for both
the Duet and Creator. Its record is assembled by the host from the installed
tool allowlist and immutable admitted contract; the model does not author it.
It deliberately reports two different sets:

- `callable_tool_names` are operations that role may invoke immediately;
- `assignable_child_capability_names` are the ceiling from which a Creator may
  grant a subset to child Episodes.

The Duet coaches the human, preserves context, and designs the descendant
Episode tree. It may persist revisions but cannot review, approve, or launch
them. Human `/approve` lets the host freeze and launch that exact tree directly.
An explicit Creator node may construct descendants only within inherited
capabilities, recursion permission, and safety bounds.
Neither prompt text nor a context artifact can expand either role's authority.

## Bounds

Bounds remain necessary because artifacts enter durable state and model
context. They apply to structured documents rather than to the complexity of
the overall workflow:

- at most 64 references per manifest;
- at most 128 KiB of canonical JSON per artifact;
- at most 512 KiB across one manifest.

Large systems should split information at ownership and handoff boundaries.
Child Episodes receive the exact subset declared for their scope instead of a
summary of the parent commission.

## Authority and migration

Human approval binds the exact workflow hash, which transitively binds every
explicit Creator contract and every referenced artifact hash. Context artifacts
cannot grant capabilities, change success criteria, modify approval state, or
carry raw credentials. Summaries may be produced for display, but they have no
authority and cannot satisfy a required context reference.

Pre-structured Creator contracts are intentionally unsupported. Recreate them
by committing their complete design information as one or more structured
artifacts and constructing a new `design_context`. The host performs no
automatic prose-to-structure conversion because that would reintroduce the
lossy summarization problem this channel removes.
