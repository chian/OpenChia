# OpenChia

OpenChia is a terminal environment for building persistent, nested Episode
workflows through a human–LLM Duet.

```text
[DUET DESIGN] -- exact approval --> [FROZEN DESIGN] --> [EPISODE BUILDER] --> [RUN]
      |                                      |
      +------- persistent Episode tree ------+
```

The Duet is the human, a restricted conversational LLM, and the host protocol
that joins them. Together they design and persist the actual nested Episode
workflow. Exact human approval freezes that design. EpisodeBuilder must
materialize and validate explicit task-specific Episode modules before launch.

Ordinary task Episodes have a fixed goal, repeated unit, numerical progress
measure, progress-based stopping criteria, declared result, and an explicit
capability set. Their nested children are fully declared in the frozen workflow.

## Start

From this checkout:

```bash
source ./activate
openchia
```

On first launch, OpenChia asks you to select an inference provider if one is not
already configured.

## Work with the Duet

Describe the outcome you want conversationally. The Duet can search for context,
propose the actual Episode topology and contracts, and persist complete workflow
revisions, but it cannot approve or execute the task directly.

The Duet follows a bundled design-coaching guide rather than a fixed interview
script. It can answer conceptual questions, follow useful tangents, recommend
defaults, and challenge weak assumptions while the host maintains a durable
ledger of confirmed, proposed, mixed, and unresolved contract fields.

The terminal keeps the active state and the most important configuration values
visible. Use these controls while specifying the Episode:

```text
/episode                         show the full configuration and provenance
/episode edit                    navigate and edit the Episode section tree
/episode diff                    show exact changes since the last view
/duet                            show design and Run state
/review                          explicitly run independent Episode-design critics
/approve                         approve and freeze the exact ready design
```

Direct edits are recorded as human-authored draft revisions and pass through the
same schema, capability, and contract validation as conversational proposals.
The editor presents Episodes as a nested, clickable tree. Expand an Episode,
choose a section such as Goal, Planning, Task, or Rarefaction, and edit only
that section in the focused pane. Mouse navigation and
the arrow keys are both supported. Missing values are marked with `!` and appear
as `<OPENCHIA: value required>` in their focused section.

Saving a conversational or editor revision runs deterministic schema, topology,
capability, and Episode-library-reference checks only. It does not build or
execute Episodes. `/review` is the sole critic entry point; it fans out
the independent, tool-free lenses against the exact current design. Findings are
advisory. A later edit makes that review stale but does not rerun it.

```text
/episode edit  make a point edit without spawning model workers
/review        explicitly run the five semantic critic lenses
/approve       approve and freeze the exact design
/logs          list persisted Run Episode logs
```

Human approval binds the exact workflow and authority hashes. The host freezes
the approved design and seals it. Launch fails closed until EpisodeBuilder has
materialized executable Episode modules from that frozen artifact; no launch or
runtime row is created by the design host.

## Architecture and boundaries

- The Duet LLM owns the design conversation and persistent Episode workflow.
- Critics are inaccessible to models and run only from trusted `/review`.
- EpisodeBuilder materializes task-specific Episode modules from the exact
  Duet-approved design before launch.
- Every built Episode explicitly binds its own loop functions, credit,
  continuation, child slots, and handoffs.
- Child-to-parent communication is typed. Raw task prose and Run log contents do
  not become parent instructions.
- Human approval is exact-artifact and exact-hash based.

See [OPENCHIA_ARCHITECTURE.md](OPENCHIA_ARCHITECTURE.md) for the executable
contracts and ownership boundaries, and
[Duet-owned Episode design](docs/openchia/duet_owned_episode_design.md) for the
review and launch call graph.

## Development checks

Use the repository runner:

```bash
scripts/run_tests.sh \
  tests/agent/test_episode_contracts.py \
  tests/agent/test_openchia_execution_boundary.py \
  tests/hermes_cli/test_openchia_cli.py \
  tests/method_loop/
```

## Lineage and license

OpenChia uses the terminal, provider, and tool runtime originally developed in
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent). The
Episode method loop derives from nano-graphrag. Attribution and license details
are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [LICENSE](LICENSE), and
[method_loop/LICENSE](method_loop/LICENSE).
