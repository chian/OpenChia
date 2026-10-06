# Refiner terminal viewer validation

Validated on Linux on 2026-10-06 in the isolated
`feat/refiner-terminal-viewer` worktree, based on `1335acc6ad`.
The worktree has its own PM-built `.venv` with the dev/test dependency groups;
tests use temporary authority and Run stores. No dependency declarations changed.

For the pull request, the viewer commit was rebased onto OpenChia `main` at
`c361b32c69`, excluding the unpublished Refiner development commits. The same
26 tests passed again on that base (71.0 seconds, retries disabled).
The Windows footgun scan also passed after making JSON reads BOM-tolerant;
both Run history tests passed again with BOM-prefixed registration coverage.

Launch this implementation without restarting the existing OpenChia CLI:

```sh
/home/chia/repos/OpenChia-refiner-viewer/.venv/bin/openchia refiner
```

Add `--home /path/to/profile` to select an explicit profile. The original
`/home/chia/repos/OpenChia` checkout remains unchanged. Existing-file edits in
the viewer worktree comprise 13 lines of command registration and dispatch.
Execution, admission, numerical control, persistence schemas, and active
contracts are unchanged.

## Automated checks

```sh
HERMES_PYTHON=/home/chia/repos/OpenChia-refiner-viewer/.venv/bin/python \
  scripts/run_tests.sh tests/openchia_cli/inspector \
  tests/openchia_cli/test_openchia_cli_commands.py --file-retries 0 -q -j 2
.venv/bin/ruff check openchia_cli/inspector openchia_cli/refiner_command.py \
  tests/openchia_cli/inspector
git diff --check
```

Result: **26 passed, 0 failed**, across four files, with retries disabled
(67.2 seconds). Ruff and whitespace checks passed.

The suite covers:

| Path | Demonstrated behavior |
|---|---|
| Real Builder/campaign admission and persisted commits | Nested assignments, waiting parents, candidate revision changes, zero-yield iterations, and exact detail/JSON agreement |
| Historical reconstruction | Earlier candidates and evidence remain frozen; future artifacts are unavailable; copying a displayed timestamp selects the same transition |
| Replacement transition fixtures | Returned and superseded remain distinct; a replacement retains its own identity and predecessor reference without appearing in earlier history |
| Actual RunStore journals | Interruption and continuation retain distinct Run identities; historical events exclude later terminal results and use recorded campaign anchors |
| Concurrent database publication | A writer commits while a read snapshot is open; the old snapshot stays consistent and the next snapshot sees the commit; SQL writes through the observer are rejected |
| Profile scope | A → B → A under multiplex reads the bound profile, even when the process environment points elsewhere |
| Actual prompt-toolkit input loop | Following, branch filtering, focus, history stepping, reference navigation, scroll/cursor retention, and closing; an in-flight refresh cannot replace an inspected reference's context |
| Empty historical state | Returning to step zero clears later assignment details |
| Shell/slash entry points | JSON and plain output use the same projection; `/refiner` dispatch creates no host |

Replacement transitions are published as typed journal fixtures to test the
reader; they do not claim to validate replacement admission. No test makes a
live model call.

## Existing-record demonstration

The standalone executable attached read-only to the existing campaign ending
`26627725487c` in a 132 × 36 terminal. It displayed the nested Parts assignments
at step 2943, held history, stepped backward, opened the separate Target Workflow
summary, returned to an empty step-zero tree, and resumed live following.
Ctrl-C exited only the viewer.

Through the same shell entry, campaign step 2940 reconstructed 181 assignments.
Selecting its displayed timestamp produced the same tree and candidate identity;
assignment details linked to distinct Target Workflow and candidate projections.

For Run `run_c74206b432ca8fa47d027cd44c7b757e141eee977808bd4e3c1e809e308d4683`,
event 100 exposed exactly events 0–100 and reconstructed campaign step 2525
with 153 assignments. The viewer explicitly reported that the most recent
campaign anchor was event 99.

## Data limitations

The viewer reports persisted observations, not process liveness or unrecorded
in-memory activity. Run journals have no wall-clock event timestamps, so a
campaign time cursor cannot establish an exact Run prefix. Historical Run
references show known registration data and state this gap; selecting a Run
event uses its explicit campaign anchor. Missing artifacts and invalid history
produce observation errors rather than substituted current data.

Usage, keys, machine commands, and module boundaries are in
[the viewer guide](refiner_terminal_viewer.md).
