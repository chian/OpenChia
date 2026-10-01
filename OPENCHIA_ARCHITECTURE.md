# OpenChia architecture

OpenChia makes the human and conversational LLM one design authority: the
Duet. The Duet owns the conversation, gathers context through search, and
persists the complete nested Episode workflow. The host owns validation,
approval, and immutable design storage. EpisodeBuilder is the separate
materialization boundary required before launch and execution.

```text
human <-> conversational LLM
              |
              v
            Duet
              |
      persisted workflow revisions
              |
       exact human approval
              |
              v
       frozen Episode design
              |
              v
        EpisodeBuilder
              |
              v
             Run
```

## Duet-owned design

The workflow artifact is the design. It declares every Episode's goal, repeated
unit, result, measured numeric credit/progress, numerical continuation
semantics, deliverable, capabilities, optional Episode-library reference, and
place in the tree. A conversational proposal and a direct human edit both
append a revision to the same durable artifact history.

The host validates each proposed revision mechanically. Validation covers the
workflow schema, tree topology, Episode-library identities, capability
inheritance, and required fields. It does not claim that design text is
executable. Validation does not add design intent or silently repair a contract.

The Duet may use web search to establish design context. It cannot execute task
tools, change OpenChia's code, approve its own workflow, or launch a Run.

## Approval and launch

Approval names one exact workflow artifact and content hash. The host rejects
approval when the artifact is incomplete, changed, or not owned by the active
Duet. A successful approval freezes and seals the design. Launch remains
closed until EpisodeBuilder has materialized and validated explicit
task-specific Episode modules from that frozen artifact.

EpisodeBuilder implements the design; it does not own or revise it. The frozen
Duet artifact remains the authority for what must be built.

## Task Episodes

Every runnable node is a task-specific Episode module. Its binding declares:

- the goal and one repeatable unit;
- the typed result and materialization location;
- a credit assignment that produces the numerical progress signal;
- a paired-incidence estimator and numerical continuation function;
- the tools available to that Episode; and
- its child slots and typed parent/child handoffs.

A built Episode can enter only child slots named by the frozen tree. Runtime
nesting therefore follows the approved topology rather than model
improvisation.

## Progress and rarefaction

Credit assignment turns accepted task state into the Episode's declared
numerical progress. Rarefaction consumes the resulting numeric paired-incidence
history and estimates the value of continuing. Its decision is numerical and
reproducible from recorded measurements. EpisodeBuilder binds each function
and its parameters explicitly from the corresponding libraries.

Target attainment and rarefaction are distinct. A target can close a completed
goal; rarefaction can close an open-ended search when the estimated remaining
marginal yield, including its uncertainty, reaches its declared resolution.

## Typed upward communication

An Episode returns a closed `ChildResult` containing logical identities by
declared result channel plus only the artifact IDs, numeric measurements,
closed states, and flags admitted for that edge. Method completion is a
separate closed runtime record. Task prose and log contents are not an
instruction channel. A parent receives only its declared projection and
recomputes progress on its own scale.

## Run logs

Each built workflow must produce durable Run logs. Logs contain unit records,
measurements, transitions, failures, and terminal results. Log references are
paths issued by the host and are never treated as model instructions. The
status surface exposes those references so the human can inspect a Run without
injecting its contents into another Episode.

## Human interaction

`/episode` reads the current persisted workflow while the conversational LLM is
working. `/episode diff` compares the current revision with the last revision
viewed by that session. `/episode edit` is available whenever the workflow is
not frozen and writes a human-authored revision through the same validation
path. `/review` invokes independent, tool-free critics on the exact current
artifact. `/approve` approves, freezes, and seals only a ready artifact.

## Persistence boundaries

The Duet store owns conversations, workflow revisions, human answers,
approvals, and events. A later built runtime owns execution logs and typed
Episode results. Artifact hashes bind records across those stores. Raw model
text never substitutes for a persisted artifact or stable identity.

## Source map

- `agent/duet_service.py` owns Duet workflow transitions and validation.
- `agent/duet_store.py` owns durable Duet artifacts, approvals, and events.
- `agent/openchia_host.py` binds the Duet service to review and exact human
  approval.
- `agent/episode_contract_models.py` defines immutable Episode contracts.
- `agent/episode_blueprints.py` parses and validates workflow artifacts.
- `episode_library/` owns durable reference Episode designs.
- `function_library/`, `llm_call_library/`, and `handoff_library/` own reusable
  binding components.
- `numeric_control_library/` owns credit assignment, identity-free
  rarefaction, numerical continuation, and their explicit controller
  composition.
- `method_loop/` owns the generic Episode loop, tree, identity, and routing.
- `hermes_cli/openchia_episode_editor.py` presents the persisted workflow for
  reading, diffing, and direct human edits.

The detailed call graph is in
[`docs/openchia/duet_owned_episode_design.md`](docs/openchia/duet_owned_episode_design.md).
