# Refiner terminal viewer

The viewer observes persisted OpenChia work. It does not instantiate a host,
start model calls, grant approval, edit a candidate, or control an execution.
It is a separate CLI surface, unrelated to `/episode`.

## Launch

```sh
openchia refiner
openchia refiner --home /path/to/profile
python -m openchia_cli.refiner_command --home /path/to/profile
```

Inside a newly started OpenChia CLI, `/refiner` opens the same viewer for the
owning profile and current Duet. `/refiner --help` lists the shell options.
The CLI hands terminal input to the viewer and restores its prompt on exit,
including when a Duet turn is running in the background.
The standalone entry can observe a build already running in another terminal;
the build's CLI does not need a restart. The default profile is resolved through
`get_hermes_home()` at command time. An explicit `--home` selects another store
without changing the calling process's profile.

The default campaign is the most recently created one in the selected
profile/Duet. The viewer reports recorded states, not process liveness. Select
another campaign explicitly when observing older ongoing work.

## Interactive navigation

The left pane shows nested Refiner assignments; the right pane shows the
selected assignment's goal and detailed evidence. The active recorded branch
is initially expanded, with prior branches hidden for a compact overview.
Press `a` to include returned and superseded work. Counts are completed iterations, not completion
percentages. Long goals remain fully available in the summary and assignment
sections; hide details or focus a subtree for more tree width.

| Control | Action |
|---|---|
| Up / Down | Select an assignment; turn off automatic selection following |
| Right / Left | Expand / collapse, or return to the parent |
| Enter | Focus details; on a reference, follow it |
| Tab | Move between visible panes and the command field |
| Space | Show or hide details |
| `n` / `p` | Next / previous detail section |
| `z` / `u` | Focus selected subtree / enclosing subtree |
| `f` | Toggle following the active recorded assignment |
| `a` | Toggle active branches / all branches, including returned and superseded work |
| `h` | Hold the current position in history |
| `[` / `]` | Previous / next campaign step or selected Run event |
| `l` | Return to live campaign observation |
| Backspace | Return from a reference or catalog |
| Escape | Return to tree; from tree, close the viewer |
| `q` / `:quit` | Close the viewer and return to the calling terminal |
| Ctrl-C | Close the viewer, leaving execution alone |
| `:` | Enter an inspector command |

Inspector commands:

```text
:campaigns
:campaign CAMPAIGN_ID
:runs
:run RUN_ID
:at COMMIT_STEP
:time 2026-10-06T16:30:00Z
:event EVENT_NUMBER
:node INVOCATION_ID
:live
:help
:quit
```

The campaign catalog has selectable references. Run references open recorded
Run details; `:run ID` selects that Run's event timeline and holds its latest
recorded event until you navigate. Opening a reference
holds the captured context until you return, so refreshing cannot retarget
the evidence you are reading. Selection, expansion, and detail scroll/cursor
positions survive refresh. Live campaign observation checks for publications every
three seconds and reuses the current projection when nothing changed. Navigation
coalesces rapid key presses into the latest selection; details already opened at
the same observation boundary are reused. History refreshes when you navigate.
These are display controls, not
pause/resume controls for the build.

## Shell and coding-agent access

Every shell response uses the same projections as the interactive viewer.
Use stable full identities from the JSON or plain tree output.

```sh
openchia refiner list --json
openchia refiner tree --campaign CAMPAIGN_ID --json
openchia refiner show --campaign CAMPAIGN_ID --node INVOCATION_ID --json
openchia refiner show --node INVOCATION_ID --section assignment --plain
openchia refiner show --node INVOCATION_ID --section checks --json
openchia refiner history --campaign CAMPAIGN_ID --json
openchia refiner tree --campaign CAMPAIGN_ID --at 120 --plain
openchia refiner show --campaign CAMPAIGN_ID --at 120 --node INVOCATION_ID --json
openchia refiner tree --at-time 2026-10-06T16:30:00Z --json
openchia refiner runs --campaign CAMPAIGN_ID --json
openchia refiner history --run RUN_ID --json
openchia refiner show --run RUN_ID --event 100 --reference run:RUN_ID --json
openchia refiner show --campaign CAMPAIGN_ID --at 120 --reference artifact:ARTIFACT_ID --json
```

Add `--home /path/to/profile` or `--duet DUET_ID` as needed. `view` defaults to
interactive mode only on a terminal; `--plain`, `--json`, or a non-terminal
input prints a snapshot. JSON failures return an `error` and
`kind: observation_unavailable`, with exit status 2. No provider setup is
required. Detail responses include their observation position, and references
carry a domain and identity for subsequent requests.

For repeatable agent inspection, first capture the tree and its campaign step,
then use `--campaign` and `--at` on subsequent requests. A campaign step is a
committed state transition. A live snapshot can also contain recorded activity
after its latest commit; a step-based request intentionally stops at that
commit. Use a timestamp cursor to inspect such inter-commit activity.

## History and evidence semantics

Campaign state is reconstructed from the predecessor-linked immutable commit
chain anchored by the campaign head, including index and candidate changes.
Unattached commit artifacts are not operative history. A missing link, unknown
delta, unsupported schema, or invalid artifact hash produces an explicit
observation error. Historical artifact reads have a fixed publication boundary;
later statuses and later revisions are never substituted.

Detail sections distinguish recorded attempts/proposals from committed
operations and applied changes. A child being returned does not imply that its
requirements passed. An iteration can change code while earning no progress.
Evidence keeps the recorded candidate, request, check, and Run references.

Run event files are read as an immutable, hash-linked published prefix, without
acquiring the execution claim lock. Temporary publication files are ignored.
Continuation registrations retain distinct physical Run identities and their
recorded predecessor links. A malformed or unreadable registration is skipped
with a reported gap, leaving other campaigns and Runs inspectable. Selecting
that Run explicitly reports the unavailable record. SQLite open failures and
malformed stored structures report their source while retaining the last usable
terminal display.

There is no shared timestamp clock across the campaign database and Run
journal. Run events have sequence numbers, not wall-clock timestamps:

- `--at` selects a campaign commit; `--at-time` uses recorded database times.
  Time selection uses the displayed microsecond precision, with publication
  order resolving ties. Use a commit step for an exact transition boundary.
- `--run` with `--event` selects a Run prefix and the last campaign snapshot
  explicitly present in that prefix. The display identifies an older anchor.
- Before any campaign snapshot appears, the Run prefix remains inspectable
  and the campaign tree is explicitly unavailable.
- Following a Run reference from campaign history exposes its known
  registration, with an explicit gap for the unknown event boundary. It never
  supplies today's terminal result as historical evidence.

References to absent external artifacts remain explicit gaps. The viewer does
not rebuild missing data, replay execution, or claim to expose unrecorded
in-memory activity. Database timestamps are recorded wall-clock observations,
not proof of a global ordering between independent stores.

## Module boundaries

All new implementation lives under `openchia_cli`:

| Module | Responsibility |
|---|---|
| `inspector/model.py` | Domain-neutral snapshots, nodes, details, references, display escaping |
| `inspector/navigation.py` | Selection, expansion, subtree focus, active-branch following |
| `inspector/terminal.py` | Shared terminal layout, input, refresh, history/reference navigation |
| `inspector/render.py` | Plain-text rendering of the same projection data |
| `inspector/archive.py` | SQLite read-only connections and immutable artifact reads |
| `inspector/run_reader.py` | Published Run registrations and journal prefixes |
| `inspector/refiner.py` | Campaign discovery, history reconstruction, assignment-tree projection |
| `inspector/refiner_details.py` | Assignment evidence and Target Workflow/candidate/Run drill-down |
| `inspector/refiner_controller.py` | Refiner-specific cursor and navigation commands |
| `refiner_command.py` | Standalone argparse interface and slash-command adapter |

Artifact verification uses a bounded cache keyed by profile-owned artifact
identity; each read still enforces its historical publication cutoff. Cached
queries read only newly published rows and match assignment identities through
JSON fields. Live polling checks the campaign head, artifact ordinal, and Run
registration file metadata before rebuilding a projection. None of these caches
or observation cursors is written into the authority or Run stores.

The only existing code changes are command registration/dispatch in
`openchia_main.py`, `openchia_commands.py`, and `duet_cli.py`. No refiner,
execution, admission, persistence schema, model-tool, or `/episode` code changes
are required. Existing prompt-toolkit dependencies are reused.

See the [validation report](refiner_terminal_viewer_validation.md) for tested
paths, the standalone worktree launch command, and remaining data limitations.
