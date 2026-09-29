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

The terminal keeps the active state and the most important configuration values
visible. Use these controls while specifying the Episode:

```text
/episode                         show the full configuration and provenance
/episode edit                    edit the complete configuration as JSON
/episode set FIELD JSON_VALUE    set a field or dotted path
/episode unset FIELD             remove a field or dotted path
/episode capabilities            list capabilities Episodes may be assigned
/duet                            show Duet, Creator, and Run state
/approve                         approve the ready contract or measured workflow
```

Direct edits are recorded as human-authored draft revisions and pass through the
same schema, capability, and contract validation as conversational proposals.
Missing values appear in the editor as `<OPENCHIA: value required>`. Replace a
placeholder with a JSON value or leave it unchanged to keep that field missing.

After contract approval, the conversational LLM submits the exact approved
artifact to the host. The Creator then runs design experiments in the
background. During that work:

```text
/guide TEXT    queue guidance for the next Creator boundary
/pause         stop at the next Creator boundary
/cancel        cancel at the next Creator boundary
/retry         request another design attempt at the next boundary
/logs          list persisted Run Episode logs
```

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
