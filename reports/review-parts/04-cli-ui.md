# 04 — UI/CLI layer: can presentation be separated from domain?

Reviewer dimension: the UI/CLI seam. Target question: *"Can we split the code into
distinct parts, e.g. UI/CLI, episode creation and episode execution?"*

**Verdict in one line:** for the UI/CLI seam the answer is **yes, and most of the
work is already done**. The OpenChia domain emits essentially **zero** presentation,
and `agent/openchia_host.OpenChiaHost` is already a real facade. What blocks a clean
split today is not coupling in the domain — it is (a) the 244k LOC of inherited Hermes
CLI that `./openchia` still drags in and still exposes, (b) a handful of
domain-policy decisions that were placed in the CLI class, and (c) duplicated
command handlers between foreground and background Duets.

---

## 1. WHAT IT DOES — keystroke to domain action

### Entry

| Launcher | File | Target |
|---|---|---|
| `./openchia` | `/Users/me/Development/OpenChia/openchia` | `openchia_cli.openchia_main:main` |
| `./hermes` | `/Users/me/Development/OpenChia/hermes` | `openchia_cli.main:main` |

`openchia_main.main()` (`openchia_cli/openchia_main.py:67-88`) does only four things:
rejects `-z/--oneshot/--tui/--tui-native` (`:71-77`), **force-injects `--cli`** into
`sys.argv` so the TypeScript TUI can never be selected (`:81-82`), then calls the
*inherited Hermes* `run_with_chat_cli_main()` with a chat-class override
(`:83-88`). The override seam is a `contextvars.ContextVar` pair in
`openchia_cli/main.py:780-805`, consumed by `cmd_chat` at `openchia_cli/main.py:1919-1923`.

So OpenChia's entire product-level divergence from Hermes is *one injected class*:
`openchia_cli.duet_cli.OpenChiaCLI`, constructed through `cli.main(cli_class=...)`
(`openchia_cli/openchia_main.py:28-32`; validated at `cli.py:1535-1537`).

### Class stack

```
OpenChiaCLI                       openchia_cli/duet_cli.py:33-37      (700 LOC)
├── OpenChiaCommandMixin          openchia_cli/openchia_commands.py:137  (401 LOC)
├── OpenChiaBackgroundDuetsMixin  openchia_cli/openchia_background.py:38 (813 LOC)
└── OpenChiaCLIBase               cli.py:883  (+17 inherited Hermes mixins)
```

### Trace: `/approve`

1. Keystroke lands in prompt_toolkit. Two possible dispatchers:
   - idle REPL → `cli_tui_runtime_mixin.py:126-133` `_tui_run_slash_input` → `self.process_command(...)`
   - agent busy → `duet_cli.py:633-671` `_tui_enter_inline_command` → `self.process_command(text)` (`:662`)
2. `OpenChiaCommandMixin.process_command` (`openchia_commands.py:386-398`) looks up
   the **OpenChia-owned** table `_openchia_command_dispatch` (`:140-151`). Anything
   not in that table and not in `OpenChiaCLI._inherited_commands`
   (`duet_cli.py:64-91`) is rejected with *"outside the OpenChia Duet/Episode
   surface"* (`:392-397`). Everything else falls through to
   `OpenChiaCLIBase.process_command` (`cli.py:1182-1217`).
3. `_handle_openchia_approve` (`openchia_commands.py:309-323`).
4. `self._episode_host()` → `duet_cli.py:375-376` → `_ensure_openchia_host()`
   (`duet_cli.py:209-218`) lazily constructs `OpenChiaHost(home=..., session_id=...,
   available_tool_names=..., agent_kwargs_factory=..., run_executor_factory=...)`.
5. `OpenChiaHost.approve_current()` — `agent/openchia_host.py:521-563`. Reads
   `self.service.duet_status(...)`, branches on `DuetDesignState`, calls
   `DuetService.approve_current_workflow` (`agent/duet_service.py:955`) or
   `approve_current_implementation_refinement` (`agent/duet_service.py:1112`),
   returns a `HumanActionReceipt` dataclass (`openchia_host.py:121-125`).
6. Back in the CLI: the receipt is **formatted** into prose at
   `openchia_commands.py:316-319`, printed via `self._print_openchia` →
   `rich.markup.escape` → `_console_print` (`duet_cli.py:372-373`), then
   `_refresh_openchia()` invalidates the status cache (`duet_cli.py:367-370`).

### Trace: `/run`

1-2 identical. 3. `_handle_openchia_run` (`openchia_commands.py:280-288`) consults a
*second* dispatch table `_run_command_dispatch` (`:152-156`) → `_run_start`
(`:236-248`) / `_run_show_status` (`:250-260`) / `_run_show_evidence` (`:262-278`).
4. `OpenChiaHost.start_run()` — `agent/openchia_host.py:1448-1530`: takes the build
lock, resolves `_runnable_build_context()`, builds a `RunRegistration`, constructs
`ScopedModelBroker` / `ScopedHttpBroker`, and spawns a worker thread running
`executor.execute(...)` on a private event loop (`:1503-1517`).
5. Return value is a plain `dict`; the CLI formats it at `openchia_commands.py:242-245`.
`/run status` and `/logs` just `json.dumps(..., indent=2)` the host dict
(`openchia_commands.py:256-258`, `:301-304`).

### Where is the seam today?

**The seam is `OpenChiaHost`'s public method surface** —
`agent/openchia_host.py:304-1877`: `architecture_snapshot`,
`episode_workspace_snapshot`, `read_episode_workspace`, `record_workspace_note`,
`record_global_instruction`, `record_architecture_revision`,
`submit_episode_architecture`, `request_episode_refinement`, `approve_current`,
`decline_current_refinement`, `start_build`, `cancel_build`, `build_status`,
`build_receipt`, `start_run`, `cancel_run`, `run_status`, `run_evidence`,
`run_audit_log`, `status`, `has_active_work`, `bind_duet`, `close`.

Every method returns a JSON-safe `dict` or a frozen dataclass. **No method returns
rendered text, colour, or a widget.** That is a genuinely good facade and it is the
single most important fact in this review.

---

## 2. SEPARABILITY — does domain code emit presentation?

I grepped `agent/openchia_host.py`, `agent/duet_service.py`, `agent/duet_store.py`,
`agent/duet_contracts.py`, `agent/openchia_agents.py`, `episode_builder/`,
`episode_runtime/`, `iterative_episode_refiner/`, `episode_library/` for
`print(` / `rich.` / `console.` / `Console(` / `click.echo` / `input(` / ANSI escapes
/ `colorama` / `prompt_toolkit` / `sys.stdout` / `sys.stderr`.

**Result: one hit, and it is a false positive.**

| Hit | Verdict |
|---|---|
| `episode_runtime/container_executor.py:113` `print(json.dumps({...}))` | Inside a **triple-quoted Python source string** that is injected into the container to report runtime identity back over a pipe. Not host presentation. Not a blocker. |

Logging is also near-absent in the domain: a single `logger.warning` in
`agent/openchia_host.py:100-105`. No other `logger.` call in `openchia_host.py`,
`duet_service.py`, `episode_builder/`, `episode_runtime/`, or
`iterative_episode_refiner/`.

**There are no presentation blockers in the OpenChia domain.** Prose only ever leaves
the domain as *exception messages* (e.g. `openchia_host.py:1453-1455`,
`duet_contracts.DuetProtocolError` at `openchia_host.py:529-531`, `:563`), which the
CLI catches and renders (`openchia_commands.py:320-321`). That is an acceptable
contract, though see F-6.

### But the coupling runs the other way: CLI → domain, and domain → CLI config

| # | Issue | Evidence |
|---|---|---|
| **B-1** | **Domain imports the CLI package.** `OpenChiaHost` reads the operator egress ceiling by importing `openchia_cli.config`. This makes `agent/openchia_host.py` un-importable without the 244k-LOC CLI package on the path, and inverts the dependency direction for the one piece of configuration the host needs. | `agent/openchia_host.py:95-98` |
| **B-2** | **Run-executor backend selection lives in the CLI class**, and derives the staging repository root from the *CLI module's* file location. Execution policy (systemd vs container, image choice) is a domain concern; `parents[1]` of `openchia_cli/duet_cli.py` happening to be the repo root is incidental. | `duet_cli.py:200-207`, consumed at `openchia_host.py:1352` via `_run_executor_factory` |
| **B-3** | **Agent construction parameters (≈30 provider/runtime knobs) are assembled in the CLI** and handed to the domain as an opaque `agent_kwargs_factory` callable. The host then calls it (`openchia_host.py:254-258`) and passes the result to `run_agent.AIAgent` (`agent/openchia_agents.py:159-168`). This is a legitimate inversion seam, but the *shape* of the dict is an undocumented contract spanning the boundary. | `duet_cli.py:146-193`, `openchia_host.py:137`, `openchia_agents.py:159-168` |
| **B-4** | **Domain contracts are re-declared in the CLI package.** `WorkspaceTarget` (`openchia_episode_views.py:72-162`) and `WorkspaceNote` (`:165-232`) are UI-side mirrors of `RefinementTarget` / `DuetWorkspaceNote` from `iterative_episode_refiner/contracts.py` (`:416`). They round-trip through the real contract in `__post_init__` to prove identity (`views.py:89-97`, `:180-190`) — careful work, but it means a *CLI* module owns a persisted-record shape. | `openchia_cli/openchia_episode_views.py:72-232` |
| **B-5** | **Note idempotency-key lifecycle lives in a prompt_toolkit button handler.** `_save_note` mints `workspace_note_{uuid4}`, caches it per target so a retry reuses the key, and validates the host's echo (`target_id`, `body`) before accepting it. That is transactional domain logic executing on the UI thread. | `openchia_episode_editor.py:623-695`, esp. `:650-676` |

None of B-1..B-5 is a *hard* blocker. B-1 and B-2 are each a ~20-line fix.

---

## 3. THE TWO ENTRY POINTS — `./openchia` vs `./hermes`

### How much is shared?

**Effectively everything.** `./openchia` does not have its own argument parser, its
own subcommand set, or its own startup path. It calls Hermes' `main()`
(`openchia_cli/main.py:802`) after injecting `--cli` and one chat class.

Measured:

| Scope | Files | LOC |
|---|---:|---:|
| `openchia_cli/` total | 611 | 247,936 |
| OpenChia-specific files in it (`openchia_main`, `openchia_commands`, `openchia_background`, `openchia_episode_editor`, `openchia_episode_views`, `duet_cli`) | 6 | **4,349** |
| Inherited Hermes remainder | 605 | **243,587 (98.2%)** |

### Is OpenChia a mode of Hermes, or a distinct product?

**Today it is a mode of Hermes, and the product boundary leaks.** Verified by running
it:

```
$ ./openchia status
┌─────────────────────────────────────────────────────────┐
│                 ☤ Hermes Agent Status                  │
└─────────────────────────────────────────────────────────┘
```

Because `openchia_main` only blocks four flags and `--cli` is a valid *top-level*
flag (`openchia_cli/_parser.py:210`), the entire inherited subcommand tree is
reachable from the `openchia` binary. `_BUILTIN_SUBCOMMANDS`
(`openchia_cli/main.py:2894-2917`) lists **~75** of them: `gateway`, `cron`,
`dashboard`, `kanban`, `whatsapp`, `slack`, `pets`, `skin`, `vault`, `proxy`,
`desktop`, `webhook`, `moa`, `curator`, `journey`, `memory-graph`, `learning`, …
None are documented in `OPENCHIA_HELP` (`openchia_main.py:8-25`) or in
`README.md`, and the parser identifies itself as `prog="hermes"`
(`_parser.py:352-354`).

### How much of the inherited surface is dead weight?

| Subsystem | Size | OpenChia references | Reachable from `./openchia`? |
|---|---:|---|---|
| `openchia_cli/web_routers/` | 26 f / 15,066 L | none | yes (`dashboard`, `serve`) |
| `openchia_cli/dashboard_auth/` | 15 f / 2,581 L | none | yes |
| `openchia_cli/observability/` | 7 f / 2,959 L | none | yes |
| `openchia_cli/proxy/` | 8 f / 777 L | none | yes (`proxy`) |
| `openchia_cli/subcommands/` | 65 f / 4,311 L | none | yes |
| `openchia_cli/local_runtime/` | 18 f / 4,018 L | none | yes |
| `openchia_cli/gateway.py` + siblings | 5,714 L (facade alone) | none | yes (`gateway`) |
| `openchia_cli/kanban*.py` | 10+ modules | none | yes (`kanban`) |
| `gateway/` (messaging) | 175 f / 94,347 L | none | yes |
| `tui_gateway/` | 98 f / 40,357 L | **zero** OpenChia-product refs (only `openchia_cli.*` import paths from the rename) | no — `openchia_main.py:81-82` forces `--cli` |
| `web/src/` (React dashboard) | 189 f / 57,604 L | **zero** | yes via `dashboard` |
| `ui-tui/src/` (TypeScript TUI) | 317 f / 66,793 L | **zero** | no — blocked at `openchia_main.py:71-77` |

I grepped `tui_gateway/`, `web/src/`, `ui-tui/src/` for any mention of OpenChia,
Duet, Episode, approve/build/run-as-OpenChia: **no product-level hits at all**. Every
`openchia` string in `tui_gateway/` is a renamed import path (`openchia_cli.config`,
`openchia_cli.profiles`, …).

**Conclusion:** `tui_gateway/`, `ui-tui/`, and `web/` are 164k lines of UI that
OpenChia deliberately cannot reach and does not depend on. They are pure dead weight
*for this product* — but note they are live for the `hermes` entry point, so they
cannot simply be deleted while both products ship from one tree.

---

## 4. THE WORKSPACE UI — `/episode`

### Structure

| File | Role | LOC | prompt_toolkit? |
|---|---|---:|---|
| `openchia_cli/openchia_episode_views.py` | View models — tree building, part projection, change marking, note/target records | 1,229 | **no** (verified: zero `prompt_toolkit`/`rich` imports) |
| `openchia_cli/openchia_episode_editor.py` | Widgets, fragments, key bindings, focus, the `Application` | 1,114 | yes |

That split is real and worth keeping. `openchia_episode_views.py` is testable
headlessly today.

### Is view state separated from model state?

**Partially — and the boundary is drawn in the wrong place.**

- Expansion state (`expanded_episode_ids`) lives in the **view model**:
  `openchia_episode_views.py:319`, mutated by `toggle()` (`:382`), consumed by
  `visible_entries()` (`:369`), and seeded with the roots on load (`:356-359`).
- Selection, detail page, scroll positions, note drafts, note cursors, and retry keys
  live in the **widget class**: `openchia_episode_editor.py:156-167`
  (`selected_keys`, `detail_page_indices`, `detail_positions`, `note_drafts`,
  `note_attempts`, `note_cursors`).

So two kinds of pure UI state are split across two modules with no stated rule. A
headless test of "expand node, select part 3, page to code" has to drive both.

- The **edit buffer** is also split: text lives in `self.detail_area` (a prompt_toolkit
  `TextArea`), and `_commit_detail_edit` (`editor.py:464-503`) parses it with
  `json.loads` then pushes it into the view model via
  `WorkflowArchitectureViewModel.apply_part` (`views.py:879`). Dirty tracking is a
  canonical-JSON comparison in the view model (`views.py:556-558`). That part is clean.

### Is diff/baseline logic in the UI layer?

**No — this is handled correctly.** The actual diff is computed in the domain:

- `_projection_changes` — `iterative_episode_refiner/workspace.py:539-600`
- `architecture_projection_changes` — `:603-609`
- `materialized_projection_changes` — `:612-618`
- `RefinementWorkspace.context()` assembles `changed_paths`,
  `architecture_changes`, `materialized_changed_paths`, `materialized_changes` into
  the snapshot dict at `:1178-1259`.
- Baseline resolution is also domain-side: `current_baseline` (`:964`),
  `_carried_baseline` (`:973`), `_baseline_predecessor` (`:1012`),
  `baseline_for_authority_head` (`:933`).

The UI only consumes the result: `duet_cli.py:522-530` reads the snapshot keys,
`views.py:546` stores `changed_paths` as a frozenset, and `_part_changed`
(`views.py:572-578`, `:1013-1020`) does prefix matching to decide whether to mark a
row. `/episode diff` renders the domain-computed change list as text in
`duet_cli.py:467-484` / `:588-615`. **Correct layering.**

### Other editor observations

- `_EpisodeWorkspace` is a ~1,000-line class doing five jobs: navigation state,
  widget construction (`editor.py:186-307`), fragment rendering (`:720-882`),
  key bindings (`:922-1038`), and host I/O (`:623-695`). Splitting it into
  `WorkspaceController` (state + host calls) / `WorkspaceLayout` (widgets) /
  `WorkspaceKeys` is the obvious decomposition.
- `_save_note` performs a **synchronous host write inside a button handler**
  (`editor.py:657-661`). The whole workspace is launched off the UI thread
  (`duet_cli.py:646-652`, `run_in_terminal(..., in_executor=True)`), so this does not
  freeze the main app, but it does block the workspace's own event loop on a SQLite
  write with no progress indication.
- The architecture-edit handshake is well designed and worth preserving as the model
  for the whole seam: the UI never writes host state; it returns
  `EpisodeWorkspaceResult` carrying `expected_architecture_{artifact_id,content_hash,revision}`
  (`editor.py:77-93`) and the host does its own compare-and-swap
  (`duet_cli.py:549-572` → `openchia_host.record_architecture_revision`, `:472`).

---

## 5. SEVERITY-RANKED FINDINGS

### HIGH

**F-1 — `./openchia` exposes the entire Hermes product surface and brands itself as Hermes.**
`openchia_main.py:67-88` blocks four flags and nothing else. `./openchia status`
prints "Hermes Agent Status"; `./openchia gateway`, `./openchia dashboard`,
`./openchia kanban`, `./openchia whatsapp` all work. ~75 subcommands
(`openchia_cli/main.py:2894-2917`) are reachable, zero are documented
(`openchia_main.py:8-25`, `README.md`). This is the single biggest obstacle to
calling OpenChia a separable product: there is no enumerated OpenChia CLI contract,
only an exclusion list.

**F-2 — Domain imports the CLI package.** `agent/openchia_host.py:95-98` does
`from openchia_cli.config import load_config_readonly`. An `openchia_domain` package
cannot be extracted or unit-tested standalone until this is inverted (pass the egress
config in through `OpenChiaHost.__init__`, as `agent_kwargs_factory` and
`run_executor_factory` already are).

**F-3 — Near-zero test coverage of the OpenChia CLI/UI layer.** Of 5,335 test files in
`tests/`, exactly **one** exercises the OpenChia command surface
(`tests/openchia_cli/test_openchia_cli_commands.py`, 31 lines, asserting only that
`/exit` is allowed and `/tools` is not). There are **no** tests for
`openchia_episode_views.py` (1,229 LOC of pure, trivially testable projection logic),
`openchia_episode_editor.py`, `openchia_background.py`, or the `OpenChiaHost` facade.
`tests/episode_runtime/` (11 files) is the only meaningfully covered OpenChia
subsystem. A split is low-risk *structurally* but has no regression net.

### MEDIUM

**F-4 — Foreground and background command handlers are duplicated ~1:1.**
`/approve` (`openchia_commands.py:309-323`) vs `/bg ID approve`
(`openchia_background.py:487-506`); `/decline` (`:325-337`) vs `:508-524`;
`/build` (`:204-234`) vs `:526-551`; `/run` (`:236-288`) vs `:553-577`; plus
`evidence` (`:655`), `logs` (`:668`), `status` (`:432`). Each pair differs only in
which `OpenChiaHost` it calls and a `"Background Duet {id} "` prefix. ~250 LOC of
avoidable duplication. Notably `/episode` is **not** duplicated —
`_open_episode_workspace(host=...)` (`duet_cli.py:511-518`) and
`_show_episode_changes(host=...)` (`:588-592`) already take the host as a parameter
and `_background_action_episode` reuses them (`openchia_background.py:454-484`). That
proves the de-duplication pattern works; it just was not applied to the other eight
commands.

**F-5 — Three parallel, hand-maintained command tables that can drift.**
`_HELP_TEXT` prose (`openchia_commands.py:9-41`), `_openchia_commands` dict used for
the palette and the availability gate (`duet_cli.py:51-63`), and
`_openchia_command_dispatch` (`openchia_commands.py:140-151`). They already disagree:
`/queue` appears in the first two but **not** in the dispatch table, because it is
actually an inherited Hermes command (`cli_loops_mixin.py:284-413`) advertised as an
OpenChia control. This also sidesteps the documented house rule — `openchia_cli/AGENTS.md:42-60`
says `COMMAND_REGISTRY` in `openchia_cli/commands.py` is "the single source" and
"there is no `elif` ladder — do not add one"; OpenChia introduced a second registry
in front of it.

**F-6 — Three OpenChia commands collide with inherited Hermes commands of the same
name and different meaning.** `openchia_cli/commands.py:92` defines `/stop` = "Kill
all running background processes"; `:96` `/approve` = "Approve a pending dangerous
command"; `:102` `/bg` = "Run a prompt in a separate background session". OpenChia
redefines all three. It works only because `OpenChiaCommandMixin.process_command`
intercepts first (`openchia_commands.py:386-391`). But inherited machinery still
resolves these names against the *Hermes* registry — e.g.
`_should_handle_background_command_inline` (`cli_info_mixin.py:459-463`) decides
busy-time inline dispatch for `/bg` from `CommandDef.busy_policy`, and
`cli_tui_mixin.py:896-900` builds the busy-state placeholder from the same registry.
OpenChia's semantics depend on inherited metadata it does not own.

**F-7 — `_EpisodeWorkspace` is a 1,000-line god object mixing UI state, widgets,
rendering, key bindings, and host writes.** `openchia_episode_editor.py:96-1069`.
See §4.

**F-8 — Execution-backend policy lives in the CLI.** `_strict_run_executor_factory`
(`duet_cli.py:200-207`) chooses systemd-vs-container and derives the staging root
from `Path(openchia_cli/duet_cli.py).parents[1]`. Belongs next to
`episode_runtime/executor_selection.py:27-39`, with the repo root passed in
explicitly.

### LOW

**F-9 — Dead `hermes_cli/` skeleton left by the rename.** `hermes_cli/` contains six
empty directories (`dashboard_auth/`, `local_runtime/`, `observability/`, `proxy/`,
`subcommands/`, `web_routers/`), zero files, and is untracked by git
(`git ls-files hermes_cli` is empty). Pure residue of the `hermes_cli` →
`openchia_cli` rename. Delete.

**F-10 — Stale worktrees shadow the current tree.** `.claude/worktrees/exe-path/`,
`.claude/worktrees/container-executor/` still contain the pre-rename `hermes_cli/`
layout including `hermes_cli/openchia_cli.py` (the old name of `duet_cli.py`). These
pollute every repo-wide grep and will mislead future readers.

**F-11 — `openchia_cli/AGENTS.md` (284 lines) documents only the inherited Hermes
CLI.** It never mentions `duet_cli.py`, `openchia_commands.py`,
`openchia_episode_editor.py`, `openchia_episode_views.py`, `openchia_background.py`,
or the fact that `OpenChiaCommandMixin` front-runs `COMMAND_REGISTRY`. Its opening
line describes `cli.py` + `openchia_cli/` as "CLI, slash commands, config, skins,
updater, profiles" — accurate for Hermes, silent about the actual product. Meanwhile
`AGENTS.md:12-21` and `OPENCHIA_ARCHITECTURE.md:203-217` carry the OpenChia story.
The per-directory doc nearest the OpenChia CLI code is the one that does not describe it.

**F-12 — `contextvars` as the product-override mechanism.** `_CHAT_CLI_MAIN` /
`_CHAT_FIRST_RUN_SETUP` (`openchia_cli/main.py:780-805`) are process-global
context variables set around a single `main()` call. It works, and it is honestly
documented as "the supported entry seam" (`:788-793`), but it is an implicit
dependency: nothing in the type system says `cmd_chat` may launch a different product.

---

## 6. CONCRETE SPLIT PROPOSAL

### Target layout

```
openchia_domain/              # NEW package — pure, importable without any CLI
  host.py                     ← agent/openchia_host.py           (1,883)
  duet/contracts.py           ← agent/duet_contracts.py            (639)
  duet/service.py             ← agent/duet_service.py            (1,297)
  duet/store.py               ← agent/duet_store.py              (1,120)
  duet/agents.py              ← agent/openchia_agents.py           (192)
  episode/contracts.py        ← agent/episode_contract_models.py   (988)
  config.py                   ← NEW: EgressConfig dataclass (fixes F-2)
  executors.py                ← NEW: run-executor resolution (fixes F-8)

episode_builder/              # UNCHANGED — already clean, already standalone
iterative_episode_refiner/    # UNCHANGED — owns diff + baseline, correctly
episode_runtime/              # UNCHANGED — already clean, has the only real tests

openchia_ui/                  # NEW package — all presentation
  entry.py                    ← openchia_cli/openchia_main.py        (92)
  app.py                      ← openchia_cli/duet_cli.py            (700)
  commands.py                 ← openchia_cli/openchia_commands.py   (401)
  background.py               ← openchia_cli/openchia_background.py (813)
  workspace/models.py         ← openchia_cli/openchia_episode_views.py  (1,229)
  workspace/controller.py     ← NEW: state + host I/O split out of the editor
  workspace/layout.py         ← widgets from openchia_episode_editor.py
  workspace/keys.py           ← key bindings from openchia_episode_editor.py

openchia_cli/                 # stays = the inherited Hermes CLI, renamed back
                              #   to hermes_cli or left as-is; openchia_ui
                              #   depends on it, never the reverse
```

### Interfaces that must be introduced

1. **`EgressConfig`** (`openchia_domain/config.py`) — a dataclass the caller builds.
   `OpenChiaHost.__init__` gains an `egress: EgressConfig` parameter; delete
   `openchia_host.py:86-106`. The CLI builds it from `openchia_cli.config`. **Fixes F-2.**
2. **`RunExecutorPolicy`** (`openchia_domain/executors.py`) — moves
   `duet_cli.py:200-207` next to `episode_runtime/executor_selection.py`, taking
   `repository_root` explicitly instead of deriving it from a CLI module's `__file__`.
   **Fixes F-8.**
3. **`AgentRuntimeSpec`** — a typed dataclass replacing the untyped ~30-key dict
   produced by `duet_cli.py:146-193` and consumed at `openchia_agents.py:159-168`.
   Documents the one remaining CLI→domain contract. **Addresses B-3.**
4. **`DuetCommands`** — one host-parameterised command object:
   `DuetCommands(host).approve() -> HumanActionReceipt`, `.build()`, `.run()`,
   `.decline()`, `.logs(run_id)`. Foreground and `/bg` both construct one. **Fixes F-4.**
5. **`CommandSpec` registry** — a single table of `(name, handler, help, args_hint)`
   from which `_HELP_TEXT`, `_openchia_commands`, `_openchia_command_dispatch`, and
   the palette are all *derived*. **Fixes F-5**, and matches the documented house rule.
6. **Explicit OpenChia subcommand allowlist** in `openchia_ui/entry.py`: replace the
   four-flag denylist (`openchia_main.py:71-77`) with a positive list of subcommands
   OpenChia supports, and set `prog="openchia"`. **Fixes F-1.**

### Order of operations

| Step | Work | Effort | Risk |
|---|---|---|---|
| 0 | Delete `hermes_cli/` skeleton; prune stale `.claude/worktrees/`. | 10 min | none |
| 1 | **Characterisation tests first** (F-3): headless tests for `openchia_episode_views.py` (pure functions, no I/O — biggest win per hour), then `OpenChiaHost` against a tmp home, then the command dispatch table. | 2–3 days | none |
| 2 | Invert F-2 (`EgressConfig`) and F-8 (`RunExecutorPolicy`). Two small, mechanical changes. After this, `agent/openchia_host.py` imports nothing from any CLI package. | half day | low |
| 3 | Introduce `DuetCommands` (F-4) and the single `CommandSpec` registry (F-5). Delete ~250 duplicated LOC from `openchia_background.py`. | 1–2 days | low |
| 4 | Split `_EpisodeWorkspace` (F-7) into controller / layout / keys. Move B-5 (idempotency keys, host echo validation) into the controller. | 2 days | medium — no test net until step 1 lands |
| 5 | `git mv` the six OpenChia files into `openchia_ui/` and the five domain files into `openchia_domain/`. Update `pyproject.toml:806-854` `packages.find` and `:569-573` `[project.scripts]`. | half day | low |
| 6 | Positive subcommand allowlist + `prog="openchia"` (F-1). Decide product policy: is `openchia gateway` supported or not? | 1 day + a product decision | **this is a product decision, not a refactor** |
| 7 | Rewrite `openchia_cli/AGENTS.md` or add `openchia_ui/AGENTS.md` (F-11). | half day | none |

Total: roughly **1.5–2 engineer-weeks**, of which half is step 1 (tests) and step 6
(product policy).

### What is NOT worth splitting

- **`episode_builder/`, `episode_runtime/`, `iterative_episode_refiner/`.** Already
  separate top-level packages, already presentation-free, already in
  `pyproject.toml` `packages.find`. The requested "episode creation vs episode
  execution" split **already exists** as `episode_builder` vs `episode_runtime`.
  Leave them alone.
- **The 605 inherited Hermes CLI files.** Do not attempt to strip, fork, or prune
  them. They are 243k LOC of upstream code that still needs to merge cleanly from
  `NousResearch/hermes-agent`. Any file you touch becomes a permanent merge conflict.
  The right move is the *allowlist at the entry point* (F-1), which costs ~100 lines
  and achieves the product boundary without touching inherited code.
- **`tui_gateway/`, `ui-tui/`, `web/`.** 164k lines, zero OpenChia awareness, already
  unreachable from `./openchia` (`openchia_main.py:71-82`). They cost nothing at
  runtime and deleting them would break `./hermes`. Leave them; just stop counting
  them as OpenChia's problem.
- **`WorkspaceTarget`/`WorkspaceNote` UI mirrors (B-4).** Tempting to collapse into
  the domain contracts, but the mirrors exist to assert *staleness* at the UI
  boundary (`views.py:96-97`, `:189-190`) — a real safety property. Keep them; move
  the file to `openchia_ui/workspace/models.py` and leave the design as is.
- **The `contextvars` entry seam (F-12).** Ugly but documented, working, and it will
  disappear naturally if step 6 gives OpenChia its own parser.

---

## 7. REDUNDANCY & DOCS SUMMARY (in scope)

| Item | Status |
|---|---|
| `hermes_cli/` — 6 empty dirs, untracked | **delete** (F-9) |
| `.claude/worktrees/{exe-path,container-executor}/` — pre-rename copies with `hermes_cli/openchia_cli.py` | **prune** (F-10) |
| ~250 LOC duplicated between `openchia_commands.py` and `openchia_background.py` | **de-duplicate** (F-4) |
| 3 parallel command tables, already drifted on `/queue` | **derive from one** (F-5) |
| `openchia_cli/AGENTS.md` — 284 lines, no mention of any OpenChia file | **rewrite / add `openchia_ui/AGENTS.md`** (F-11) |
| `README.md` documents 10 slash commands; `/queue` is inherited, not OpenChia-owned | clarify which controls OpenChia owns vs inherits |
| `OPENCHIA_ARCHITECTURE.md:203-217` source map lists `cli.py` + `openchia_cli/` but not `duet_cli.py` / `openchia_episode_*` | add the six OpenChia CLI files to the source map |
| `openchia_main.py:8-25` `OPENCHIA_HELP` omits ~75 reachable subcommands | either block them (F-1) or document them |
