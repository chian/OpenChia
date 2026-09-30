# OpenChia

OpenChia is a terminal environment for building persistent, nested Episode
workflows through a human–LLM Duet.

```text
[DUET] -- approved contract --> [CREATOR]
   ^                                |
   | closed progress                | frozen design
   +---------------------------- [RUN]
                          typed measures + log
```

The Duet is the human, a restricted conversational LLM, and the host protocol
that joins them. Together they specify a Creator Episode. The Creator repeatedly
designs a complete nested workflow, launches one frozen design through a child
Run Episode, inspects the persisted Run log and typed measurements, and uses
host-computed credit to decide whether another design experiment is warranted.

Ordinary task Episodes have a fixed goal, repeated unit, numerical progress
measure, progress-based stopping criteria, declared result, and an explicit
capability set. They cannot create more Episodes unless their immutable
contract declares them to be Creator Episodes.

## Start

From this checkout:

```bash
source ./activate
openchia
```

On first launch, OpenChia asks you to select an inference provider if one is not
already configured.

## Work with the Duet

Describe the outcome you want conversationally. The Duet can search for context
and propose Creator configuration fields, but it cannot approve its own contract
or execute the task directly.

The Duet follows a bundled design-coaching guide rather than a fixed interview
script. It can answer conceptual questions, follow useful tangents, recommend
defaults, and challenge weak assumptions while the host maintains a durable
ledger of confirmed, proposed, mixed, and unresolved contract fields.

The terminal keeps the active state and the most important configuration values
visible. Use these controls while specifying the Episode:

```text
/episode                         show the full configuration and provenance
/episode edit                    navigate and edit the Episode section tree
/episode set FIELD JSON_VALUE    set a field or dotted path
/episode unset FIELD             remove a field or dotted path
/episode capabilities            list capabilities Episodes may be assigned
/duet                            show Duet, Creator, and Run state
/creator                         show live Creator stages or failure diagnostics
/review                          run or show the advisory shadow contract review
/approve                         approve the ready contract or measured workflow
```

Direct edits are recorded as human-authored draft revisions and pass through the
same schema, capability, and contract validation as conversational proposals.
The editor presents Episodes as a nested, clickable tree. Expand an Episode,
choose a bounded section such as Goal, Planning, Task, Credit assignment, or
Rarefaction, and edit only that section in the focused pane. Mouse navigation and
the arrow keys are both supported. Missing values are marked with `!` and appear
as `<OPENCHIA: value required>` in their focused section.

After contract approval, the conversational LLM submits the exact approved
artifact to the host. The Creator then runs design experiments in the
background. Before freezing each proposed workflow, the Creator can ask
independent, tool-free critics to inspect contract alignment, measurement and
evidence, iteration and recovery, capability safety, and task-specific risks.
Their findings are advisory, but the exact candidate hash must be reviewed before
submission; a post-review edit must be reviewed again. Only host-measured Run
evidence contributes method credit. During that work, the status panel shows the
current structured stage without exposing private model reasoning:

```text
/guide TEXT    queue guidance for the next Creator boundary
/pause         stop at the next Creator boundary
/cancel        cancel at the next Creator boundary
/creator       show recent stages, exact failure code, owner, and next action
/retry         queue a live-boundary retry or restart a retryable failed Creator
/logs          list persisted Run Episode logs
```

Creator tool validation failures preserve their structured reason, message, and
deficits. A schema-invalid workflow is reported as a Creator-owned design failure,
not a generic runtime error. Platform-owned faults remain non-retryable until the
runtime is fixed.

When a measured workflow awaits adoption, `/approve` approves and launches that
exact frozen workflow.

## Architecture and boundaries

- The Duet LLM has search and typed Duet protocol operations only.
- A Creator Episode specializes in designing and evaluating nested Episode
  workflows.
- A task Episode executes its immutable contract and has no creation authority.
- A nested Creator is possible only when its containing workflow explicitly
  defines its contract, evidence requirements, credit assignment, and return
  projection.
- Child-to-parent communication is typed. Raw task prose and Run log contents do
  not become parent instructions.
- Every Creator experiment persists its Run log before its measured candidate is
  admitted.
- Human approval is exact-artifact and exact-hash based.

See [OPENCHIA_ARCHITECTURE.md](OPENCHIA_ARCHITECTURE.md) for the executable
contracts and ownership boundaries.

## Development checks

Use the repository runner:

```bash
scripts/run_tests.sh \
  tests/agent/test_duet_protocol.py \
  tests/agent/test_creator_episode.py \
  tests/agent/test_episode_contracts.py \
  tests/agent/test_task_episode.py \
  tests/agent/test_workflow_runtime.py \
  tests/method_loop/
```

## Lineage and license

OpenChia uses the terminal, provider, and tool runtime originally developed in
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent). The
Episode method loop derives from nano-graphrag. Attribution and license details
are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [LICENSE](LICENSE), and
[method_loop/LICENSE](method_loop/LICENSE).
