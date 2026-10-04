# Refiner guidance catalog

Initial content for Goal 5, 2026-10-02. These are selectable instruction and
example artifacts for the proposed IterativeEpisodeRefiner. This directory does
not register new Episodes, install agent skills, resolve catalogs at runtime, or
provide authority to execute anything. Selection, authenticated source resolution,
frozen-input wiring and behavioral validation remain implementation work.

**Target Workflow** names the scoped Episode workflow being built, refined and
tested. The IterativeEpisodeRefiner works on it; a **candidate revision** is one
exact implementation state. Use those terms in guidance and selected prompts.

## Browse narrowly, then read completely

The [root index](index.json) contains subject cards only. Each subject has its own
`index.json` containing item cards and separate `instructions/` and `examples/`
bodies. A numerical-controller assignment can list only
`numerical_controller/index.json`; it need not scan calculation or simulation.
`general/` is an explicit optional selection, not a mandatory context dump.

1. The caller names the guidance need, role, task conditions and allowed catalog
   revision. Select the relevant subject index or indexes.
2. Browse compact cards. `use_when`, roles and topic matches are routing hints,
   not proof of applicability or admission. Check `do_not_use_when` and provenance.
3. Select exact items and read their complete bodies. There is no partial-reading
   interface for instructions. The parent need not receive every body the searcher
   examines; it receives the selected references and supported applicability.
4. Before a child starts, the host must pin both the card and body, and relevant
   source-inventory records, in the assignment's approved instruction package.
   A later retrieval is typed reference data, never a system-prompt replacement.

The card and body form **one versioned item**. The card is authoritative for its
selection metadata; the body for the detailed guidance. An edit to either requires
a new item version once published. Resolve the pair by a pinned catalog revision
and content hashes before use; `guidance_id`/`version` alone are not authentication.
Do not follow a body's cross-reference as an automatic inclusion. A caller selects
and admits additional guidance explicitly.

## Item cards

| Field | Meaning |
| --- | --- |
| `guidance_id`, `version` | Stable logical identity and positive integer content version |
| `title` | Short name for a parent choosing guidance |
| `kind` | `principle`, `role_instruction`, `specialty_instruction`, `worked_example`, or `check_pattern`; this also states the level of guidance |
| `subject`, `roles` | Directory subject and intended refiner roles; neither grants capabilities |
| `description` | One-sentence contribution, not the entire instruction body |
| `use_when`, `do_not_use_when` | Inclusion and exclusion conditions to examine |
| `body_path` | Complete Markdown body, relative to this subject directory |
| `source_refs` | Keys into the [source inventory](sources.json), with exact source identities |
| `validation_status` | Evidence category below; never a blanket quality score |

Subject indexes repeat no instruction bodies. They contain only these cards.
The root index knows subject paths, not every item. This keeps lists independent
and lets a parent combine, for example, `reasoning` and `measurement` without
loading all other specialties. The source inventory is provenance data; resolve
only the records referenced by selected cards when building a child package.

Validation categories:

- `design_guidance`: derived from the refiner design; its role flow is proposed,
  not an implemented/refiner-tested path.
- `source_inspected`: grounded in the named repository definitions by static
  inspection; no new execution claim.
- `recorded_live_case`: an existing receipt records a live answer; the body states
  configuration and execution limits. This is not a newly reproduced receipt.
- `illustrative_unexecuted`: an authored worked example or check pattern. Its
  expected relation may be inspectable, but no automated or live validation is
  claimed for it.

No tests or live model calls were run to create this catalog. In particular,
there is no dedicated calculation or simulation Episode in the inspected library
catalog. Those examples demonstrate possible task contracts, not shipped coverage.

## How guidance affects design

The parent still supplies the goal, local measurement and acceptance contracts.
Guidance suggests designs, discriminating checks and evidence to seek; it cannot
change approved requirements, make an unsupported claim true, allocate credit,
expand a child's authority or authorize Designer-to-Designer recursion.

The common and role items explain how to work. Specialty instructions explain
what to examine for a type of problem. Examples contain a concrete task, a good
design, separate local/parent judgments, bad alternatives, and limits. They are
not templates to copy uncritically into every assignment.

Selected example answers belong in **design support**, not in a blinded acceptance
run of that same problem. Exposing the scheduling solution to the solver would
invalidate a claim that it independently solved the benchmark.

For each selection, the future FindDesignSupport result must retain the caller's
need, exact selected item/source refs, applicable conditions, unmet prerequisites,
conflicting or rejected matches, and uncovered needs. A supported closure of that
need can be progress; a larger list of retrieved documents is not.

## Initial coverage

- `general`: common constraints, Designer ownership, unfamiliar-task fallback,
  and focused library search.
- `goal_contract`: translate the target requirement into faithful part assignments.
- `numerical_controller`: credit, rarefaction and continuation as one coupled design.
- `reasoning`: supported claims and a recorded scheduling answer.
- `calculation`: exact quantities, aggregation and independent arithmetic checks.
- `simulation`: model semantics, deterministic controls and stochastic evidence limits.
- `measurement`: construct adequate measures and challenge misleading passes.
- `composition`: typed handoffs, same-candidate integration and repair-cycle routing.

Use the [design v3](../../docs/openchia/iterative_episode_refiner_episodes.md)
as the higher-level design contract. Relative source paths in `sources.json` are
repository-root paths, not paths beneath this catalog.
