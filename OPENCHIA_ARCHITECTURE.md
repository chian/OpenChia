# OpenChia architecture

OpenChia has one human-facing design authority and three separate execution
boundaries.

```text
human <----> restricted conversational LLM
                    |
                   Duet
                    |
          Workflow Architecture
                    |
          exact human approval
                    |
             EpisodeBuilder
        plan -> emit -> inspect
                    |
       Materialized Specification
                    |
           explicit human Run
                    |
          isolated Episode tree
                    |
          validated audit records
                    |
       IterativeEpisodeRefiner
                    |
        successor proposal to Duet
                    |
          exact human approval
```

The Duet is the human, a search-capable conversational LLM, and the host
protocol that joins them. It owns the complete Workflow Architecture. The host
owns mechanical admission, exact-artifact persistence, and enforcement of the
human approval boundary. EpisodeBuilder implements an approval.
IterativeEpisodeRefiner organizes change requests against an approved baseline.
Neither subsystem is an Agent or an Episode, and neither can approve its own
output.

## Workflow Architecture

The Architecture is the authoritative design input. It declares the complete
nested tree and gives every Episode a durable local identity. Each Episode
declares:

- its goal, repeated unit, result, and deliverable boundary;
- its numeric credit/progress semantics;
- exact registered rarefaction and continuation function identities with
  validated arguments;
- its capabilities;
- its typed parent-to-child request and child-to-parent result projections;
- its child slots and position in the tree; and
- an optional immutable reference to a library Episode.

The Architecture carries the human-readable explanation of continuation and
the executable numerical selections separately. The exact function pointer is
`library`, `function_id`, `interface`, and `definition_id`; its arguments are
part of the approved value. The host derives the available catalog and argument
contracts from the registered libraries. Reference Episodes can guide a design,
but they do not supply omitted authority.

The Duet may search for design context. Its model-facing tools can read and
propose design artifacts; they cannot edit source, approve a proposal, build a
package, or start a Run. Every conversational proposal and direct human edit
appends a revision to the same durable Architecture history.

The host admits a revision only when its complete contract, topology,
capability inheritance, registered function selections, handoffs, and optional
reference identities are internally consistent. Admission validates what the
Duet supplied; it does not invent missing design intent.

## Approval

Approval names one exact Architecture artifact, content hash, authority head,
and human action. Any intervening revision makes that approval target stale.
Successful approval freezes and seals the exact artifact. The conversational
LLM, EpisodeBuilder, Run worker, and IterativeEpisodeRefiner have no approval
path.

An approved Architecture is not a build. A build is not a Run. Each transition
requires its own explicit human command.

## EpisodeBuilder

EpisodeBuilder consumes only the exact frozen approval. It works leaf first:

1. Validate the approval and persist its immutable build input.
2. Derive a code plan without changing topology, capabilities, handoffs,
   deliverables, result channels, or numerical selections.
3. Emit one task-specific Python module per Episode.
4. Append a host-owned literal declaration tying each module to the approved
   Episode, exact plan, registered functions, result identities, and edges.
5. Compile and inspect the complete source package without importing it.
6. Persist the plan, sources, findings, manifest, and terminal receipt.

Structural facts come from the host and approved Architecture, not from the
planning model. A planner may write task-specific functions and prompts, but
its return must reproduce every frozen numerical function record exactly.
Mismatch or ambiguity blocks the build rather than silently rewriting the
design.

Static admission checks syntax, closed imports, direct-effect restrictions,
literal prompts, capabilities, result channels, bindings, and source hashes.
A materialized build receipt with its manifest means that exact source was
materialized from the exact approval and passed static admission. Blocked and
cancelled receipts preserve the terminal build attempt without claiming
admission. No build receipt is runtime evidence.

## Materialized Specification

The Materialized Specification is the readable, source-linked projection of an
immutable build. It includes the workflow overview and, for every Episode, the
frozen contract, plan, loop bindings, prompts, child slots, handoffs, admitted
source symbols, findings, and stable hashes.

It is intentionally distinct from the Workflow Architecture. The Architecture
states what the Duet and human approved; the Materialized Specification states
how one build implemented it. They share stable Episode identities and appear
as separate views in one Workspace.

## Workspace and notes

`/episode` opens the Workspace. Arrow and tab navigation move between the two
views, the Episode tree, and individual parts. Each view keeps its own stable
diff baseline and highlights changed parts. Notes target an exact layer,
Episode identity, part key, JSON pointer, baseline artifact, and content hash.

Browsing and notes remain available during a Duet turn. Direct replacement of
the Architecture is available when that Duet turn is idle. Notes are persisted
before the conversational model receives their IDs; the model reads the exact
stored text rather than a paraphrase.

An ordinary human prompt after materialization is atomically preserved as two
candidates over the same words: one at the workflow-semantics layer and one at
the materialization-implementation layer. The Duet resolves the intended layer
and proposes the corresponding change. The unchanged layer is not rebuilt by
association: only explicitly targeted Episodes, or every Episode for an exact
global directive, enter a successor build.

## Task Episodes and numerical closure

Every materialized task Episode explicitly binds its own loop pieces. Credit
assignment owns stable result identities, normalization, and marginal dominated
hypervolume. Rarefaction receives only the resulting numeric paired-incidence
history. The registered continuation function receives the projected
marginal-credit band and its approved arguments. Its numerical verdict governs
whether the Episode continues or works back up the tree.

A parent receives distinct child identities by declared result channel and
recomputes progress on its own scale. It does not sum child hypervolumes. Raw
task prose, source contents, and log text never become upward instructions.

## Isolated Run

`/run` registers one admitted build and stages a content-addressed runtime
closure. The closure includes the exact generated package, every local runtime
module it can import, and an interpreter/standard-library identity. The worker
verifies that closure before importing application code and uses a source-only
closed import finder so the mutable checkout is not an execution dependency.

The worker enters its filesystem and syscall policies before generated module
activation. The host launches it through the system service boundary with
explicit source and runtime mounts. Model calls cross a typed broker interface;
the generated package does not receive general host tools or credentials.

Run registration, claim, terminal state, results, and chunked audit manifests
are content-bound durable records. A terminal acknowledgement is accepted only
in the terminal protocol phase. Partial publication cannot become a successful
Run receipt.

The current MVP admits a closed typed terminal outcome and audit evidence. It
does not treat runtime success as proof that a scientific or task result is
correct; those meanings belong to the Episode's declared result and credit.

## Iterative refinement

IterativeEpisodeRefiner is a modular subsystem between inspection and the next
Duet proposal. It pins one approved Architecture, one admitted Materialized
Specification, exact human notes, and validated terminal Run evidence when such
evidence exists. Refinement may begin before a Run when the human is responding
to static materialization details.

Generated source and Run audit content enter the refinement context only as
untrusted reference data. They cannot select tools, alter authority, approve a
change, or address another baseline. The refiner records target coverage and a
semantic or implementation change proposal. The Duet presents the successor;
the human approves or declines it. Approval records the exact successor
authority and refinement lineage rather than mutating the prior build. The
human's later `/build` action creates the fresh build request.

## Persistence ownership

- The Duet store owns conversations, Architecture revisions, human answers,
  notes, proposals, approvals, refinement lineage, and authority events.
- The Build store owns exact approved inputs, plans, generated source blobs,
  static-admission findings, manifests, and receipts.
- The Run store owns runtime closure identities, registrations, claims,
  terminal results, and chunked audit manifests.
- Stable artifact hashes bind records between stores. Raw model output never
  substitutes for a persisted artifact or human approval.

## Source map

- `agent/duet_service.py` owns Duet Architecture transitions and approval
  preparation.
- `agent/duet_store.py` owns durable Duet artifacts and atomic authority writes.
- `agent/openchia_host.py` coordinates human actions, background builds, Runs,
  and subsystem boundaries.
- `agent/episode_contract_models.py` and `agent/episode_blueprints.py` define and
  admit immutable Architecture values.
- `episode_library/` owns reusable reference Episode designs.
- `episode_builder/` owns approved-input validation, planning, emission, static
  admission, immutable source packages, and build receipts.
- `episode_runtime/` owns closure identity, the broker protocol, isolated
  activation, Run storage, results, and audits.
- `iterative_episode_refiner/` owns pinned baselines, exact notes, target
  coverage, change proposals, and Workspace projection.
- `function_library/`, `llm_call_library/`, `handoff_library/`, and
  `numeric_control_library/` own reusable declared components.
- `method_loop/` owns the generic Episode loop, nesting, runtime identity, and
  routing.
- `openchia_cli/openchia_episode_editor.py` and
  `openchia_cli/openchia_episode_views.py` render the dual-view Workspace.

The detailed materialization and refinement boundary is in
[`docs/openchia/duet_owned_episode_design.md`](docs/openchia/duet_owned_episode_design.md).
