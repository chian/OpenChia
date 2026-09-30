# Duet-owned Episode design

## Ownership boundary

The Duet is the only model role that participates in ordinary interactive
workflow design. It persists the complete nested Episode blueprint through
`episode_workflow_update`. The update is guarded by the current content hash
and appends an immutable `episode_workflow_draft` revision.

Saving a revision performs deterministic checks only:

- blueprint schema and progress-adapter validation;
- single-root topology and parent relationships;
- capability subset enforcement;
- recursive-Creator authority and depth checks;
- context-artifact ownership and hash checks; and
- declared safety-depth enforcement.

It does not call another model and does not execute any Episode node.

## Explicit review

Semantic critics are reachable only from the trusted `/review` command. The
command snapshots the exact current authority hash and workflow hash, runs the
five isolated critic lenses concurrently, and stores their advisory findings.
The result is cached for those exact hashes. Any workflow or authority edit
makes it stale without automatically rerunning it.

The Duet and Creator tool surfaces contain no contract-review or
workflow-review operation. OpenChia also disables the general automatic
background-review facility for these roles.

## Approval and construction

`/approve` revalidates the current authority and workflow, records exact human
approvals, admits an internal root Creator/build identity, freezes the approved
workflow under that authority, materializes stable Episode identities and
parent edges, and starts the Run. The root Creator/build step does not use a
designer model and cannot alter the workflow.

Task agents are created lazily only after this launch boundary when execution
reaches their fixed Episode nodes. An explicitly designed recursive Creator
node may construct descendants during the Run, but it inherits the approved
capability, context, budget, and depth bounds and has no critic tool.

Launch status is a durable stage stream, not a single success/failure bit. The
host records queued, constructing, completed, and failed events. A failure
record retains the exact exception message, likely owner, workflow identity,
and suggested next action so an operator can distinguish a platform repair from
a design revision.

## Call graph

```text
Human <-> Duet model
             |
             +-- episode_workflow_update
             |      `-- deterministic host checks only
             |
Human /review
             `-- five isolated critic lenses (explicit and advisory)

Human /approve
             `-- internal Creator/build (no designer model)
                    `-- approved Run
                           `-- one task agent per reached Episode node
```

## Pre-beta transition

Older conversational workflow strings and automatic-review artifacts are not
promoted into new design revisions. One narrow host migration does allow an
existing Duet to reopen: it atomically removes the retired
`duet_contract_review` and `episode_creator` capabilities, adds
`episode_workflow_update`, rebinds the policy identity, and records an audit
event. It never restores the retired tools or converts old prose into a workflow.
Existing run/evidence ledgers remain auditable.
