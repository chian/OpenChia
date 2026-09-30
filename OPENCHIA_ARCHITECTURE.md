# OpenChia Episode architecture

OpenChia replaces unconstrained agent delegation with explicit, measured
Episodes. The human-facing authority is the **Duet**: a human, a restricted
conversational LLM, and the host protocol that joins them. The Duet is not an
Episode. It commissions a task-specific Creator Episode only after the human
has approved an exact frozen contract.

There is no persistent head Episode. Ordinary user conversation belongs to the
Duet. Repeated task execution belongs to Episodes.

## Duet authority

The three parts of a Duet have different jobs:

- The human supplies intent, corrections, guidance, and approvals.
- The conversational LLM searches, synthesizes, proposes contract fields, and
  submits exact host-recorded artifact IDs.
- The host validates schemas and capabilities, mints identities, persists
  revisions, applies numerical rules, and launches approved work.

The Duet LLM has read-only search plus the typed Duet protocol. It has no
terminal, file editing, code execution, plugin management, tool discovery, or
delegation surface. Its final `episode_creator` call contains only the frozen
Creator contract artifact ID, exact content hash, and exact human approval ID.
The host reloads all content; a later draft revision invalidates the approval.
Admission alone is not reported as success: the bound task-specific launcher
must accept the Creator identity and return a closed execution receipt. The
launcher is idempotent on that identity so an exact tool-call retry cannot
start a duplicate Creator loop.

The conversational role is governed by the bundled `agent/duet_coaching.md`
guide. It describes design dimensions and interviewing behavior without fixing
their conversational order. The model-facing `duet_status` projection includes
the materialized draft, per-field provenance and disposition, typed open
questions, and unconfirmed proposal paths, so conversational flexibility does
not require relying on model memory alone.

Once a contract is complete, `duet_contract_review` can run one stateless,
tool-free semantic critic against that exact contract hash. The critic is
advisory: it cannot patch, approve, or launch work, and a changed draft makes
the prior review stale.

Human answers, guidance, decisions, and approvals enter through trusted host
operations. The LLM may submit their opaque artifact IDs but cannot invent
their contents or authority.

Self-driven episode creation is deliberately a later mode. The current policy
contains only gates the host enforces; it does not expose dormant “autonomy”
flags that suggest approval, evidence, or uncertainty rules which do not yet
exist.

## Schema translation

Models edit blueprints, not internal records. A blueprint describes the goal,
loop unit, result, progress semantics, stopping criteria, capabilities,
deliverable, safety bounds, and workflow topology. The host then:

- rejects unknown or missing fields;
- mints opaque metric and artifact identities;
- supplies schema versions and capability inheritance;
- derives `can_create_episodes` from the presence of a complete Creator
  contract rather than accepting a model assertion;
- validates registered numerical progress adapters; and
- freezes the translated contract and its hash.

This keeps ergonomic model JSON separate from authority-bearing runtime JSON.

## Creator Episodes

A Creator Episode is the Duet's internal task-specific workflow experimenter;
it is not the user-facing design object. The nested Episode workflow is that
object. Creation authority is off by default and exists exactly when the
internal Episode has an approved `EpisodeCreatorContract`.

Every complete workflow body crossing the review or submission boundary is
first appended to the `episode_workflow_draft` ledger with its canonical
content hash and exact structured blueprint. This write happens before schema,
admission, or critic checks. A rejected review or failed design cycle therefore
annotates or supersedes a durable Episode workflow draft; it can never leave
only a hash, summary, critic finding, or internal Creator failure behind.
`workflow_design`, review, Run, evidence, and approval artifacts refer to this
primary design object and do not replace it. `/episode` reads this ledger.
The Duet's status projection carries only the latest artifact reference;
`episode_workflow_read` verifies Duet ownership and the hash before returning
the exact structured body on demand. This keeps recovery lossless without
injecting a large workflow into every status response.

One Creator unit is one complete experiment:

1. inspect prior typed Run outcomes and, when useful, their scoped logs;
2. draft one complete nested workflow blueprint;
3. request independent advisory review lenses and revise when their findings
   are sound;
4. submit the complete blueprint and let the host translate, validate, and
   freeze the workflow;
5. launch one child Run Episode for that exact artifact and hash;
6. receive the Run log reference plus typed goal information; and
7. let the numerical Creator controller measure improvement and decide whether
   to continue.

Each `workflow_review` lens receives only the frozen Creator contract, proposed
blueprint, host validation facts, and its narrow rubric. Reviewers have no tools
or shared conversation and return typed findings. They do not vote, approve, or
contribute method credit; host-observed Run evidence remains authoritative.

The Creator model uses `workflow_candidate` to submit a design. It cannot
approve or launch the adopted workflow. Invalid proposals may be corrected
inside the same design conversation; only a host-admitted frozen design starts
a Run Episode and consumes a Creator experimental unit.

The Creator controller stops successfully when a complete Run reaches the
approved method-credit threshold. It stops for no progress after the declared
number of consecutive completed Runs fail to improve the best observed credit
by the declared minimum delta. Oscillation between old scores is not progress.
A proposal safety bound reports `bound_hit`; it is not convergence.

Low-credit Runs remain persisted because they are experimental evidence. The
minimum-credit threshold is enforced when the Duet approves a workflow for
adoption, not when the Creator records a failed or partial experiment.

## Run Episodes and mandatory logs

A Run Episode launches the exact frozen nested workflow selected for one
Creator experiment. Before it returns, the host atomically writes the complete
recursive `EpisodeRecord` to the Creator's log store. Its result must contain:

- the frozen design artifact ID, revision, and workflow hash;
- Run and Goal identities;
- terminal reason and consumed units;
- accepted result and evidence identities;
- host-computed measurements and method credit; and
- a `RunLogReference` with artifact ID, absolute location, SHA-256 digest, and
  byte count.

The binding rejects a projector that changes the candidate hash, candidate
artifact, Run identity, Goal identity, unit count, or log reference.

Run logs are immutable experimental data. `creator_log_read` can read only log
references assigned to the active Creator, checks root scope, filename,
length, and digest, and labels the content untrusted. The raw log never enters
the Duet conversation. Only a closed progress envelope containing IDs, enums,
counts, validation codes, accepted evidence IDs, and host credit travels
upward. The envelope is atomically persisted with Creator and Duet state, so
`duet_status` can follow experimental progress without opening a Run log.

## Ordinary task Episodes

An ordinary task Episode receives one immutable contract and an exact
capability set. One Hermes model/tool iteration is one Episode unit. The host
controller observes either registered evidence identities or a persisted
terminal-result artifact, applies the declared numerical rule, and owns the
stop decision.

`episode_progress` accepts registered evidence identities, never a numeric
self-score. A successful task update contains exactly one accepted result
artifact ID. Raw model prose, tool output, exceptions, and source text remain
inside task-private state. The Run log records the complete recursive host
`EpisodeRecord`—Goals, units, typed updates, controller steps, and stop
state—without copying task transcript prose into the parent channel.

A frozen ordinary-task workflow runs declared children in declaration order.
Each child returns a typed `ChildEpisodeUpdate`; only then does the containing
task's Hermes turn begin with those closed updates. Ordinary task Episodes may
execute this predeclared topology but cannot add or redesign it.

## Creator-capable workflow nodes

A Creator may place another Creator Episode in a workflow only when all of the
following are true:

- its own approved contract permits assigning Creator capability;
- the nested Creator has its own complete task-specific Creator contract;
- its assignable capabilities are a subset of the parent Creator's scope;
- the Duet policy permits the resulting Creator depth; and
- the runtime supplies an explicit `CreatorNodeBuilder` for that Creator task.

Creator authority is never inherited from structural depth. The default
ordinary-task workflow runtime therefore fails closed on a Creator-capable node
when no task-specific Creator binding was supplied. That builder must also
supply the explicit `EpisodeTree` matching its additional Creator and Run
grains; the ordinary default tree is not silently widened. A Creator node is a
leaf in the workflow that declares it: its children are the Run Episodes and
candidate workflows created by its own loop, not predeclared task children
smuggled into the parent's workflow.

The host admits that nested Creator from the exact frozen parent design, not
from a second human-approval fiction. Its authority record binds the parent
Creator ID, design artifact ID, local node ID, narrowed contract hash, and the
root human approval chain. Recursive type edges are explicit and structurally
depth-bounded. A nested Creator returns a normal closed `ChildEpisodeUpdate`
plus only the measurements, credit components, and status fields its own
return contract allowed; its Run log remains in its own inspection scope.

## Message boundaries

Creator-to-Duet status is a closed projection. It contains no Creator prose and
no child log content.

Duet-to-Creator steering is applied only between completed Creator units.
Pause and cancel decisions consume no Creator unit. Human guidance is stored as
a trusted artifact, bound to one Creator and one expected unit boundary, and
resolved only after the corresponding decision is claimed. The conversational
LLM submits only the decision artifact ID.

These are typed authority boundaries, not text masking. Internal Hermes names
are harmless when they are not rendered into the isolated Duet, Creator, or
task prompts and tool schemas.

## Interactive host and terminal surface

`openchia` uses the normal Hermes argument parser and classic terminal run
loop, but selects `OpenChiaCLI` through an explicit CLI-construction hook. The
freshly initialized conversational agent is narrowed to the Duet tool surface
before its first prompt build or model request. Creator and task agents are
separate persistence-isolated instances built from the same resolved provider
route.

The profile-scoped host persists protocol state at
`<HERMES_HOME>/openchia/duet.sqlite3`, Run records beneath
`<HERMES_HOME>/openchia/run_logs/`, and task results as content-addressed Duet
artifacts. Creator execution occurs on a background thread so the human can
continue talking to the Duet and can steer the next experimental boundary.
The terminal panel reads only `duet_status`; it never reads a task transcript
or Run log to summarize progress.

The terminal exposes the current nested Episode workflow directly through
`/episode`; the internal Creator contract is not the editor's root. View and
edit modes use the same expandable Episode tree, with bounded Goal, Planning,
Task, Credit assignment, Rarefaction, authority, and safety sections beneath
each Episode. Each saved edit appends one exact human-authored workflow draft
and runs it through the same schema, capability, and execution validation as a
model proposal. A failed validation leaves that workflow editable. The
OpenChia command palette and completion list expose this Episode surface rather
than inherited delegation and automation commands.

The initial concrete measurement adapter is deliberately mechanical. It
normalizes the frozen workflow root's typed progress value from its declared
baseline and target into `root_episode_progress` in `[0, 1]`. One accepted
`run_episode_host` terminal-update artifact supports that measurement. The
Creator contract still chooses the task-specific root measure and stop rule;
the evaluator does not ask a model to score its own result. Contracts requiring
a different evaluation source fail closed until a corresponding host adapter
exists.

## Identities and relationships

OpenChia keeps authority and topology separate:

- `duet_id` identifies the external human--LLM authority root.
- `designed_by_episode_id` identifies the Creator that declared a workflow
  node.
- `workflow_parent_episode_id` identifies the structural parent that receives
  the node's typed update.

No `head_episode_id` exists.

## Code map

- `method_loop/`: generic Goal, Grain, Episode, nesting, controller routing,
  stable identities, and recursive records.
- `agent/episode_contracts.py`: public contract facade;
  `episode_contract_models.py` and `episode_updates.py` own immutable internal
  models and the closed child-to-parent update respectively.
- `agent/episode_blueprints.py`: strict model-blueprint to internal-contract
  translation.
- `agent/duet_contracts.py`, `duet_store.py`, `duet_service.py`: Duet authority,
  revisions, trusted human artifacts, admissions, evidence, credit, and atomic
  launch.
- `agent/creator_design_session.py`: restricted Creator conversation and
  workflow submission.
- `agent/creator_episode.py`: Creator and Run bindings, numerical design
  controller, and immutable Run logs.
- `agent/creator_runtime.py`: composition of Creator experiments with Duet
  evidence and credit.
- `agent/task_episode.py`: ordinary Hermes-iteration task binding and
  host-owned task controller.
- `agent/workflow_runtime.py`: frozen ordinary-task topology execution.
- `agent/openchia_agents.py`: capability-exact Duet, Creator, and task AIAgent
  construction, including tool-free contract and workflow critics.
- `agent/duet_coaching.md`: flexible human-interview guidance and Episode design
  rubric injected only into the Duet.
- `agent/openchia_host.py`: profile-scoped persistence, human controls,
  background Creator execution, nested Creator wiring, mechanical Run
  evaluation, final workflow launch, and task-result storage.
- `hermes_cli/openchia_cli.py`, `openchia_main.py`: compact status/navigation,
  Duet slash commands, and the installed `openchia` entry point.
- `tools/duet_tool.py`: the typed model-facing protocol schemas.

Provider replacement, transcript replay, presentation generation, and legacy
subagent lifecycle management are outside the Episode method. They are not
silently folded into Creator authority.
