# 06 — Documentation and Specifications

Review dimension: **Documentation and specifications**
Repo: `/Users/me/Development/OpenChia` @ `b56a3e4498` (branch `main`)
Date: 2026-10-02

---

## Answers to the two questions asked

**"Is everything documented?"** — No. The *narrative* is documented unusually well
for a project this young: the top-level prose (`README.md`,
`OPENCHIA_ARCHITECTURE.md`, `docs/openchia/duet_owned_episode_design.md`) is
dense, precise, internally consistent, and its `Source map` is **100% accurate**
(all 20 referenced paths exist). But it is incomplete in two directions:
(a) the two newest subsystems — host-brokered HTTP egress and the container
execution backend — are missing entirely from the architecture doc; and
(b) **38% docstring coverage** across the 41k-line OpenChia layer, with the
contract modules — the files that *are* the de facto specification — among the
worst-covered.

**"Do we have specs?"** — **No, not in any machine-checkable sense.** Of the six
spec artifacts a system with "exact artifact + content hash" authority semantics
needs, **zero** exist as versioned, external, machine-readable documents. The
project *used* to have four JSON Schemas (`schemas/openchia/*.schema.json`);
they were deleted in the 113-file refactor (`5baa5a3b7d`) and never replaced.
What remains are hand-rolled frozen dataclasses with hand-written validators —
executable and genuinely strict, but with **no version field, no migration path,
no external artifact, and no conformance suite**. The spec is the code, and the
code is not labelled.

---

## Severity-ranked findings

### S1 — CRITICAL: the content-hash authority chain has no schema version

`EpisodeWorkflowSpec.workflow_hash()` and `EpisodeCreationSpec.spec_hash()`
(`agent/episode_contract_models.py:944`, `:762`) are the hashes that human
approval binds to. Deserialization is strict-closed — `_keys()` rejects any
record whose key set is not exactly the expected set
(`agent/episode_contract_models.py:948-958`). There is **no `schema_version`,
`format_version`, or `artifact_version` field anywhere in the OpenChia layer**:

```
$ grep -rn "schema_version|SCHEMA_VERSION|format_version|artifact_version" \
    agent/duet_*.py agent/episode_*.py episode_builder episode_runtime \
    iterative_episode_refiner method_loop
(only hits: episode_runtime/landlock.py:22-23 — LANDLOCK_ABI_VERSION, unrelated)
```

And `agent/duet_store.py` sets `PRAGMA foreign_keys` and `PRAGMA journal_mode`
but **never `PRAGMA user_version`** — there is no schema-migration hook in the
store that owns approvals and authority events.

Consequences, all silent:
- Adding one field to `EpisodeDesignSpec` makes **every previously persisted
  Architecture artifact unloadable** with a bare `ValueError` from `_keys()`.
- The same logical design hashes differently before and after any field change,
  so **every prior human approval silently becomes unverifiable** — the exact
  failure mode the authority model exists to prevent.
- Nothing in the code or docs tells a contributor that changing a contract
  dataclass is a breaking format change.

This is the single highest-value fix in this dimension.

### S2 — CRITICAL: the four JSON Schemas were deleted and never replaced

Commit `5baa5a3b7d` ("Build the Duet-owned Episode foundation", 113 files,
+8,828/−18,613) removed the project's entire machine-checkable spec layer:

| Deleted path | Size |
|---|---|
| `schemas/openchia/generic_creator_instance_v1.schema.json` | 4,666 B |
| `schemas/openchia/evidence_gate_manifest_v1.schema.json` | 1,843 B |
| `schemas/openchia/creator_context_v1.schema.json` | 1,720 B |
| `schemas/openchia/creator_fault_v1.schema.json` | 1,486 B |
| `GENERIC_NESTED_CREATORS_ARCHITECTURE.md` | 8,090 B |
| `docs/openchia/generic_nested_creators.md` | 6,335 B |
| `docs/openchia/structured_creator_context.md` | 4,275 B |
| `docs/openchia/recursive_creator_threat_model.md` | 3,624 B |
| `docs/openchia/generic_creator_v1_migration.md` | — |
| `docs/openchia/generic_nested_creators_change_report.md` | — |

The `schemas/` directory no longer exists. The only remaining `.schema.json`
files in the repo are inherited Hermes telemetry schemas
(`openchia_cli/observability/schemas/hermes.shared_metrics.v{1,2}.schema.json`).

The deletion is *defensible* — the "creator" concept was genuinely replaced by
the Duet/Episode model, so those specific schemas were obsolete. What is not
defensible is that **the practice went with them**. `jsonschema` is used
elsewhere in the tree (`tools/tool_search_validation.py`,
`tools/delegation_output_schema.py`, `agent/plugin_llm.py`) but is **not even a
declared dependency in `pyproject.toml`**, and is used nowhere in the OpenChia
layer. Note also the lost `recursive_creator_threat_model.md` — the fork now has
**no threat model document at all** for the OpenChia execution boundary
(`SECURITY.md` is pure pre-fork Hermes; see S5).

### S3 — HIGH: `OPENCHIA_ARCHITECTURE.md` omits two whole subsystems

The architecture doc's `Source map` is accurate as far as it goes — I verified
every one of its 20 paths and **all exist**. But measured against the code:

```
egress / http mentions in OPENCHIA_ARCHITECTURE.md:        0
"container" mentions:                                      0
"systemd" mentions:                                        0
egress / http mentions in duet_owned_episode_design.md:    0
```

Missing from the source map entirely:
`episode_runtime/http_broker.py` (22 KB), `episode_runtime/container_executor.py`
(30 KB), `http_call_library/`, `question_table_goal_library/`.

The doc says only that "the host launches it through the system service
boundary" (`OPENCHIA_ARCHITECTURE.md:163`) — which described reality before the
container backend landed. `README.md` *does* document both backends and egress
(lines 123-156, added `2026-10-02`), so the drift is one-directional: the newest
work updated the user-facing README and shipped ADR 0002, but the two
architecture documents were not touched. `docs/openchia/duet_owned_episode_design.md`
(last touched `2026-10-01`) still says only "a typed broker mediates allowed
model calls" — the HTTP broker is a second, differently-shaped broker it does
not mention.

### S4 — HIGH: the static-admission rule set is not enumerable or typed

`episode_builder/admission.py` is the gate that decides whether generated source
may ever run. Its outcome is a `BuildDeficit` whose `code` field is a **bare
`str`** (`episode_builder/_contract_base.py:287-294`), not an enum:

```python
@dataclass(frozen=True)
class BuildDeficit:
    code: str          # <- free-form; validated only as "a token"
    field_path: str
    detail: str
    episode_local_id: Optional[str] = None
    blocking: bool = True
```

There is **no enum class** in `admission.py`, `inspection.py`, or
`_contract_base.py`. I recovered the rule set by grepping literals — **29
distinct codes** across `episode_builder/`:

```
build_cancelled                       module_emission_failed
builder_signature_invalid             module_exports_incomplete
child_interface_mismatch              module_state_mutation_forbidden
child_plan_unavailable                module_syntax_invalid
concrete_child_imported               node_plan_invalid
design_choice_unresolved              numeric_control_invalid
directive_plan_scope_exceeded         planning_failed
directive_source_scope_exceeded       predecessor_numeric_binding_mismatch
directive_source_scope_missing        reference_unavailable
directive_source_target_missing       root_builder_on_child
edge_child_unavailable                topology_divergence
edge_payload_mismatch                 unchanged_module_unavailable
edge_reused                           host_declaration_invalid
edge_unplanned                        host_declaration_overridden
goal_view_mutable
```

None of these 29 codes appears in any document. Because `code` is `str`, a typo
produces a *new* admission code silently, and no test or type checker can
notice. The actual enforcement constants — `_ALLOWED_IMPORT_ROOTS`,
`_FORBIDDEN_CALL_NAMES`, `_FORBIDDEN_CALL_ATTRIBUTES`, `_FORBIDDEN_ATTRIBUTES`,
`_INTERNAL_IMPLEMENTATION_ROOTS` (`admission.py:67-151`) — are private
frozensets with no documented rationale for any individual entry. The README's
one-line summary ("checks syntax, closed imports, direct-effect restrictions,
literal prompts, capabilities, result channels, bindings, and source hashes",
`OPENCHIA_ARCHITECTURE.md:103-105`) is prose, not a checkable list.

### S5 — HIGH: SOUL.md makes the Duet self-identify as "Hermes Agent"

`SOUL.md` is identity slot #1, loaded into the live system prompt
(`agent/prompt_builder.py:1591-1606`). Both the repo's `SOUL.md:1` and the
installed default (`openchia_cli/default_soul.py:10` and `:44`) begin:

> "You are Hermes Agent, built by Nous Research."

So the conversational half of the Duet introduces itself as the upstream
product. This is a documentation artifact with a direct user-visible effect, and
it is the clearest evidence that the fork's doc layer was never swept.

The same is true of the whole untranslated-and-translated periphery:

| File | Size | OpenChia | Duet | Episode | Hermes | Last touched |
|---|---|---|---|---|---|---|
| `README.es.md` | 16 KB | 0 | 0 | 0 | 56 | 2026-09-24 |
| `README.zh-CN.md` | 11 KB | 0 | 0 | 0 | 54 | 2026-09-24 |
| `README.ur-pk.md` | 23 KB | 0 | 0 | 0 | 52 | 2026-09-24 |
| `SECURITY.md` | 16 KB | 0 | 0 | 0 | 24 | 2026-08-20 |
| `SECURITY.es.md` | 19 KB | 0 | 0 | 0 | 25 | 2026-08-20 |
| `CONTRIBUTING.es.md` | 29 KB | 1 | 0 | 0 | 41 | 2026-10-01 |
| `SOUL.md` | 667 B | 0 | 0 | 0 | 1 | 2026-08-30 |

All three translated READMEs still open with `<img src="assets/banner.png"
alt="Hermes Agent">` and describe a product that no longer exists at this path.
`SECURITY.md` — the document that should describe the sandbox, the broker
boundary, the egress ceiling, and the approval model — predates the entire
OpenChia layer and mentions none of it.

### S6 — HIGH: no spec for the broker/worker wire protocol

`episode_runtime/protocol.py` (25 KB, 734 lines) defines a length-prefixed
binary framing (`struct.Struct(">I")`) with 6 host frame types and 5 worker
frame types, plus a phase machine. It has:

- **no protocol version constant** (`grep "VERSION|protocol_version" → nothing`)
- **no external spec document** — no mention in any `.md` file
- **21% docstring coverage** (4 of 19 public API items)
- the frame types exist as `str` enums (`HostFrameType`, `WorkerFrameType`,
  `CancelKind`), which is the one good part — those *are* enumerable

An unversioned wire protocol between a host and an isolated worker, where the
worker runs from a content-addressed closure staged separately from the host, is
a format-skew hazard: nothing detects a host and a staged worker built from
different protocol revisions.

### S7 — MEDIUM: no spec for the Run evidence/audit record format

`episode_runtime/audit_contracts.py` (21 KB, 535 lines) defines exactly three
public classes — `RunAuditChunk`, `RunAuditLog`, `RunEvidence` — at **21%
docstring coverage** (3 of 14 API items). The docs reference audit records only
as prose:

- `OPENCHIA_ARCHITECTURE.md:168-170`: "chunked audit manifests are content-bound
  durable records"
- `duet_owned_episode_design.md:112-114`: "Run records contain typed inputs,
  measurements, transitions, errors, terminal results, and log artifacts"

There is no field list, no chunking/manifest format, no hash-binding rule
written down. This matters more than usual because the refiner consumes this
format as *untrusted* input — the trust boundary is only as good as the parse,
and the parse is 535 undocumented lines.

### S8 — MEDIUM: 38% docstring coverage across the OpenChia layer

Measured with an AST walk over public (non-`_`) classes and functions, excluding
nested-in-private scopes, over the OpenChia layer only (`agent/{duet,episode,openchia}_*.py`
plus the 11 OpenChia packages — 41,964 lines total):

| package | files | lines | mod% | cls% | fn% | **all%** | API items |
|---|---:|---:|---:|---:|---:|---:|---:|
| `agent/` (openchia only) | 8 | 6,720 | 100 | 73 | 33 | **42** | 145 |
| `episode_builder` | 12 | 8,696 | 100 | 90 | **17** | **36** | 120 |
| `episode_runtime` | 18 | 11,093 | 100 | 72 | 29 | **43** | 194 |
| `iterative_episode_refiner` | 4 | 3,850 | 100 | 73 | **15** | **25** | 88 |
| `method_loop` | 5 | 2,376 | 100 | 100 | **13** | **42** | 100 |
| `episode_library` | 12 | 2,653 | 100 | 67 | **6** | **14** | 21 |
| `function_library` | 3 | 631 | 100 | 88 | 5 | 29 | 28 |
| `llm_call_library` | 5 | 871 | 100 | 50 | 50 | 50 | 28 |
| `handoff_library` | 4 | 828 | 100 | 100 | 22 | 53 | 15 |
| `numeric_control_library` | 5 | 2,137 | 100 | 44 | 16 | **22** | 67 |
| `http_call_library` | 5 | 609 | 100 | 75 | 67 | **71** | 17 |
| `question_table_goal_library` | 3 | 500 | 100 | 60 | 20 | 40 | 10 |
| **TOTAL** | | **~41k** | **100** | **74** | **25** | **38** | **833** |

The shape is consistent and diagnostic: **module docstrings 100%, class
docstrings 74%, function docstrings 25%.** Someone wrote a one-line summary at
the top of every file and on most dataclasses, then stopped. The behaviour —
what the functions actually *do*, and the invariants they assume — is undocumented.

Worst-documented *important* modules (≥10 public API items, sorted by coverage):

| cov | documented | lines | module |
|---:|---:|---:|---|
| **0%** | 0/11 | 108 | `episode_library/registry.py` |
| 10% | 2/20 | 359 | `numeric_control_library/controller.py` |
| 18% | 2/11 | 120 | `method_loop/runtime.py` |
| 19% | 4/21 | 1,181 | `episode_builder/_contract_chain.py` |
| 20% | 8/41 | 873 | `iterative_episode_refiner/contracts.py` |
| 20% | 4/20 | 1,336 | `iterative_episode_refiner/service.py` |
| 21% | 6/29 | 639 | `agent/duet_contracts.py` |
| 21% | 4/19 | 734 | **`episode_runtime/protocol.py`** |
| 21% | 3/14 | 535 | **`episode_runtime/audit_contracts.py`** |
| 25% | 10/40 | 1,026 | `numeric_control_library/credit_assignment.py` |
| 28% | 7/25 | 1,120 | `agent/duet_store.py` |
| 28% | 13/46 | 1,751 | **`episode_runtime/contracts.py`** |
| 29% | 4/14 | 1,297 | `agent/duet_service.py` |
| 38% | 15/39 | 988 | **`agent/episode_contract_models.py`** |

Note the pattern: **the five files that constitute the de facto specification**
(`episode_contract_models.py`, `episode_runtime/contracts.py`, `protocol.py`,
`audit_contracts.py`, `iterative_episode_refiner/contracts.py`) average **~27%**.
When the code *is* the spec, this is the spec's completeness.

Two bright spots worth preserving as the house style: `http_call_library/`
(71%) and `agent/openchia_host.py` (73%, 22/30, 1,883 lines) — both recent work.
`numeric_control_library/controller.py` at **10%** is the most alarming single
entry: it implements the continuation verdict that governs whether an Episode
continues, i.e. the system's core control decision.

### S9 — MEDIUM: `AGENTS.md` and `CONTRIBUTING.md` are accreted, not maintained

**`CONTRIBUTING.md` (53 KB, ~1,020 lines) is wholly inherited Hermes.** It is
titled "Contributing to Hermes Agent", and contains:

```
Episode:   0 occurrences
Duet:      1 occurrence
OpenChia:  3 occurrences
Hermes:   61 occurrences (15 capitalized + 46 lowercase)
```

Its 30 section headings cover adding a tool, adding a skill, adding a skin,
memory providers as plugins, third-party integrations as plugins, cross-platform
compat, dependency pinning. **Not one line covers the OpenChia layer** — no
guidance on contract models, admission rules, library registration, the Duet
store, or the approval boundary. Its only recent edit (`2026-10-01`) was the
mechanical `hermes_cli` → `openchia_cli` rename. This is accretion: 53 KB that a
new contributor to the actual product gets no value from.

**`AGENTS.md` (37 KB) is better but structurally stale.** It is still titled
"Hermes Agent - Development Guide". Its routing table and project structure are
*mostly* verifiable — I checked every referenced path:

- All 12 nested `AGENTS.md` files in the routing table exist ✓
- `gateway/platforms/ADDING_A_PLATFORM.md` exists ✓
- `website/docs/user-guide/multi-profile-gateways.md` exists ✓
- `docs/adr/README.md` exists ✓
- **`main.py` does NOT exist** (routing table row 2 lists `cli.py`,
  `openchia_cli/`, `main.py`) ✗

Three real problems:

1. **The routing table has no row for the OpenChia layer.** 41k lines across
   `episode_builder/`, `episode_runtime/`, `iterative_episode_refiner/`,
   `method_loop/`, `agent/duet_*`, and the six `*_library/` packages have **zero
   contributor routing**, and none of those directories has its own `AGENTS.md`.
2. **The `Project Structure` tree is selectively incomplete.** It lists
   `method_loop/`, `episode_library/`, and `numeric_control_library/` but omits
   `episode_builder/`, `episode_runtime/`, `iterative_episode_refiner/`,
   `function_library/`, `llm_call_library/`, `handoff_library/`,
   `http_call_library/`, and `question_table_goal_library/`.
3. **A stale hard number.** It claims "~39k tests / ~3.7k files, Sep 2026";
   actual count is **5,335 test files** — off by 44%. Exactly the hazard its own
   preamble warns about ("Counts shift constantly; the filesystem is canonical").

The irony is sharp: `AGENTS.md` contains the rule *"Moving a symbol means fixing
its docs in the same PR: grep `website/docs`, `skills/`, and every `AGENTS.md`
for the old `path.py` + symbol (23 doc files went stale after the refactor)."*
That rule was not applied to the OpenChia fork itself.

### S10 — MEDIUM: ADR 0001 is "Accepted" but unimplemented, with no tracking

`docs/adr/0001-interrupt-messages-carry-only-human-typed-text.md` reads:

```
Status: Accepted
Implementation: not yet landed; follow-up implementation pending.
```

I verified it is still unimplemented — the exact string-matching convention the
ADR decided to replace is live:

```
gateway/run.py:2775      _CONTROL_INTERRUPT_MESSAGES = frozenset({
gateway/run.py:2782      def _is_control_interrupt_message(message) -> bool:
gateway/run_turn.py:3674     if _is_control_interrupt_message(interrupt_message):
```

The ADR's own cited incompleteness also persists: `"Cron job timed out
(inactivity)"` has **0 occurrences** in `gateway/`, confirming it is still
missing from `_CONTROL_INTERRUPT_MESSAGES` as the ADR noted.

To the ADR's credit, all four of its code citations are precise — I checked
`openchia_cli/cli_chat_turn_mixin.py:438`, `gateway/run_inbound.py:716`,
`gateway/run_busy.py:679`, `gateway/run_turn.py:3336` and every line matches the
described `interrupt(...)` call. The problem is process: "Accepted but not
landed" is a status with no owner, no issue link, and no expiry. The ADR README
defines only three statuses (`Proposed` / `Accepted` / `Superseded`), which
cannot express "decided but outstanding".

### S11 — LOW: undocumented environment variables and commands

`OPENCHIA_CONTAINER_CLI` (`episode_runtime/container_executor.py:138`) is a real
`os.environ.get` read and is documented **nowhere** — not in `README.md`, not in
`.env.example`, not in `cli-config.yaml.example`. Only its sibling vars
`OPENCHIA_RUN_EXECUTOR` and `OPENCHIA_CONTAINER_IMAGE` made it into
`README.md:140-143`.

`/steer` and `/btw` are dispatched for OpenChia sessions
(`openchia_cli/cli_tui_mixin.py:899`, `:1562`; usage string at
`cli_loops_mixin.py:417`) but appear in **neither** `_openchia_commands`
**nor** `_inherited_commands` in `openchia_cli/duet_cli.py:51-89`, so they are
absent from `/help`. `/exit` is in `_inherited_commands` but missing from the
`_HELP_TEXT` canonical list (`openchia_cli/openchia_commands.py:40`, which ends
at `/quit`).

### S12 — LOW / positive: README's slash-command list is accurate

Verified against both the dispatch table
(`openchia_cli/openchia_commands.py:141-156`) and the in-app help text
(`openchia_cli/openchia_commands.py:9-41`). All 11 documented commands
(`/episode`, `/duet`, `/queue`, `/bg`, `/approve`, `/decline`, `/build`, `/run`,
`/logs`, `/stop`, `/help`) are implemented; `/episode edit|diff` and
`/run ""|status|evidence` subcommands match `_run_command_dispatch` exactly. No
documented-but-missing command. The only gap is the reverse direction (S11).

### S13 — LOW / positive: the egress config example is exemplary

`cli-config.yaml.example:1805-1828` documents the `openchia.egress` block —
`allowed_hosts`, `credentials.<name>.{kind,path,header,scheme}`, defaults, and
the closed-by-default rule. I diffed it against `load_egress_config`
(`episode_runtime/http_broker.py:117-180`) and **every key, default, and
constraint matches**, including `kind: bearer_token_file` as the only supported
kind and `Bearer` / `Authorization` defaults.

This is the one place in the repo where a config surface is fully and accurately
documented — and it is the newest code. Use it as the template.

---

## Spec gap analysis — the scorecard

| # | Spec needed | Exists? | Authoritative? | Code validated against it? |
|---|---|---|---|---|
| 1 | Workflow Architecture format | **Partial — code only.** `agent/episode_contract_models.py` dataclasses with `as_record`/`from_record`/`to_json`/`from_json`/`workflow_hash` | **De facto yes** (strict closed-key validation via `_keys()`) — but unversioned, internal, 38% documented | Self-validating; **no external spec, no conformance corpus, no round-trip golden fixtures** |
| 2 | Materialized Specification format | **No.** Prose only (`OPENCHIA_ARCHITECTURE.md:110-120`). Structure lives implicitly in `episode_builder/store.py` + `iterative_episode_refiner/workspace.py` | Descriptive prose | No |
| 3 | Broker/worker wire protocol | **No.** `episode_runtime/protocol.py` (734 lines) is the only artifact; **no version constant**, no doc | Code only; 21% documented | Self-validating; no cross-version check |
| 4 | Run evidence/audit record | **No.** 3 classes in `audit_contracts.py` (535 lines, 21% documented); prose at `duet_owned_episode_design.md:112-114` | Code only | No external validation of the untrusted-input boundary |
| 5 | Registered-function pointer contract (`library`/`function_id`/`interface`/`definition_id`) | **No.** `EpisodeFunctionSelectionSpec` (`episode_contract_models.py:289`) + `LibraryFunction` (`function_library/models.py:334`). The four-part pointer is named in **exactly one sentence of prose** (`OPENCHIA_ARCHITECTURE.md:58`) | Code only | Regex-shaped (`^function_[0-9a-f]{64}$`); **no interface-compatibility spec at all** |
| 6 | Static-admission rule set | **No.** 29 free-form `str` codes recovered only by grep; no enum, no list, no doc | Prose summary only (`OPENCHIA_ARCHITECTURE.md:103-105`) | **Not even type-checked** — `BuildDeficit.code: str` |

**Score: 0 of 6 machine-checkable. 1 of 6 (#1) genuinely authoritative-as-code.**

The architectural choice to use frozen dataclasses with hand-written `__post_init__`
validators instead of pydantic is reasonable and the implementation is unusually
disciplined (strict closed key sets, `sort_keys=True` canonical JSON, regex-shaped
IDs, `MappingProxyType` immutability). **The problem is not the technique — it is
that the result is unlabelled, unversioned, and unexported.** No pydantic appears
anywhere in the OpenChia layer, so the usual "models are the schema, export
`model_json_schema()`" escape hatch is also unavailable.

---

## Documentation inventory

### Tier 1 — OpenChia-native, current, high quality (~29 KB)

| File | Size | Audience | Assessment |
|---|---|---|---|
| `README.md` | 7.4 KB | user | Current (2026-10-02). Accurate command list, both executor backends, egress section. Best doc in the repo. |
| `OPENCHIA_ARCHITECTURE.md` | 11 KB | contributor / architect | Source map 100% accurate; prose precise. **Missing egress + container backend entirely (S3).** |
| `docs/openchia/duet_owned_episode_design.md` | 170 lines | contributor | Deep on the materialization/refinement boundary. Missing HTTP broker (S3). |
| `agent/duet_coaching.md` | 55 lines | **LLM agent** (loaded into the live prompt at `agent/prompt_builder.py:197`) | The only genuinely LLM-facing OpenChia doc. Concise, current, and the right idea. |
| `docs/adr/{README,0001,0002}.md` | 3 files | contributor | Good format; too few (S14). ADR 0001 unimplemented (S10). |
| `cli-config.yaml.example` § OpenChia egress | ~24 lines | operator | Exemplary — fully matches code (S13). |
| `THIRD_PARTY_NOTICES.md` | 1.7 KB | legal | Current (2026-10-01). |

### Tier 2 — inherited Hermes, partially swept (~90 KB)

| File | Size | Status |
|---|---|---|
| `AGENTS.md` | 37 KB | Title + 90% content still Hermes. Routing table verified accurate *for Hermes dirs*; **no OpenChia routing** (S9). One dead path (`main.py`), one stale count. |
| `CONTRIBUTING.md` | 53 KB | Wholly Hermes. 0 mentions of Episode (S9). |

### Tier 3 — inherited Hermes, untouched since before the fork (~86 KB + 8.3 MB)

`README.es.md`, `README.zh-CN.md`, `README.ur-pk.md`, `CONTRIBUTING.es.md`,
`SECURITY.md`, `SECURITY.es.md`, `SOUL.md` — all describe Hermes Agent, zero
OpenChia content (S5).

Plus **`website/`** — a 449-file, 8.3 MB Docusaurus site of which only **3 files
mention OpenChia**. It is the largest documentation corpus in the repo by two
orders of magnitude and is ~100% about a different product. `AGENTS.md` actively
routes contributors into it ("Long-form background lives in
`website/docs/developer-guide/`").

### Tier 4 — deleted, not replaced

The 10 files in S2 — including the project's only threat model and its only
JSON Schemas.

---

## ADR practice (S14 — HIGH)

Two ADRs exist. Both concern *narrow, recent* decisions (interrupt provenance;
host-brokered HTTP). **Every foundational decision in the system is unrecorded.**
In rough priority order, the decisions embedded in code with no written rationale:

1. **Why approval binds a content hash rather than a revision ID** — the single
   load-bearing choice of the whole authority model. Consequences (stale
   approval on any intervening revision; rehash-on-field-change, S1) are
   unanalysed in writing.
2. **Why hand-rolled frozen dataclasses instead of pydantic / JSON Schema** —
   and what replaced the deleted `schemas/openchia/` practice. This is the
   decision that produced S1, S2, and the whole spec gap. Reversing the S2
   deletion needs this written down first.
3. **Why the "creator" model was replaced by Duet/Episode** — a 113-file,
   −21k-line refactor (`5baa5a3b7d`) with no recorded rationale and no migration
   note (the migration doc was itself deleted).
4. **Why the static-admission allowlist is import-root-based** — why
   `_ALLOWED_IMPORT_ROOTS` rather than a capability or module-graph model, and
   what the threat model is for each `_FORBIDDEN_*` entry (S4). Replaces the
   deleted `recursive_creator_threat_model.md`.
5. **Why the run closure is content-addressed and source-only** — why a staged
   closure + closed import finder rather than running the checkout; what the
   interpreter-identity verification defends against.
6. **Why two executor backends with one protocol** — the systemd/container
   split, the Landlock ABI 7 floor, and what equivalence is claimed between
   backends (currently only in `README.md` prose).
7. **Why generated source is never imported by the host** — compile-and-inspect
   rather than import, and what that buys.
8. **Why credit is non-additive across the tree** — "parents do not sum child
   hypervolumes" (`OPENCHIA_ARCHITECTURE.md:150-151`) is stated as fact with no
   justification; it is the core numerical-semantics decision.
9. **Why Run audit content is untrusted reference data** — the refiner's trust
   boundary, stated in three documents, justified in none.
10. **Why the human prompt after materialization becomes two candidates** — the
    dual-layer disambiguation design (`OPENCHIA_ARCHITECTURE.md:134-139`) is
    unusual and unexplained.

Also recommend a process fix: the ADR README's three statuses cannot express
ADR 0001's actual state. Add **`Accepted (implementation pending)`** with a
required owner/issue field, or demote 0001 to `Proposed`.

---

## Recommended doc/spec set, in priority order

### P0 — stop the authority chain from silently breaking

1. **Add `schema_version` to every hashed record type** and
   `PRAGMA user_version` + a migration hook to all three stores
   (`agent/duet_store.py`, `episode_builder/store.py`,
   `episode_runtime/store.py`). Make the version part of the hashed payload so a
   format change is *visible* rather than silently invalidating. *(fixes S1)*
2. **`docs/openchia/spec/workflow-architecture.md` + a generated JSON Schema.**
   Restore `schemas/openchia/`. Emit the schema from the dataclasses with a
   small generator script, commit the output, and add a CI check that the
   committed schema matches regeneration. Add `jsonschema` to
   `pyproject.toml`. *(fixes S2 + spec #1)*
3. **A golden-corpus round-trip conformance test.** Commit N frozen
   Architecture JSON artifacts with their expected `workflow_hash`; assert
   `from_json → as_record → to_json` is byte-identical and the hash is stable.
   This turns S1 from invisible to a red build.

### P1 — specify the boundaries that carry untrusted data

4. **`docs/openchia/spec/wire-protocol.md`** — frame grammar, the 11 frame
   types, the phase machine, size limits, and a `PROTOCOL_VERSION` constant
   negotiated in the `initialize`/`ready` handshake. *(fixes S6 + spec #3)*
5. **`docs/openchia/spec/run-evidence.md`** — the audit chunk/log/evidence
   record schemas, chunking and manifest rules, and the hash-binding chain from
   Run → build → package → runtime identity. *(fixes S7 + spec #4)*
6. **`docs/openchia/spec/static-admission.md`** — convert `BuildDeficit.code`
   from `str` to an enum of the 29 codes, and publish the table with one row per
   rule: code, what it checks, why, and whether it is blocking. Document each
   `_ALLOWED_IMPORT_ROOTS` / `_FORBIDDEN_*` entry's rationale. *(fixes S4 + spec #6)*
7. **`SECURITY.md` rewrite** (or `docs/openchia/threat-model.md`) — replacing
   the deleted `recursive_creator_threat_model.md`. Cover the sandbox, the two
   broker boundaries, the egress ceiling, the approval boundary, and the
   untrusted-audit-input boundary. *(fixes part of S5 + S2)*

### P2 — close doc/code drift

8. **Update `OPENCHIA_ARCHITECTURE.md`**: add an "Egress" section and an
   "Execution backends" section; add `http_broker.py`, `container_executor.py`,
   `http_call_library/`, `question_table_goal_library/` to the Source map. Same
   for `duet_owned_episode_design.md`. *(fixes S3)*
9. **Rewrite `SOUL.md` and `openchia_cli/default_soul.py`** so the Duet
   identifies as OpenChia. *(fixes the user-visible half of S5)*
10. **`docs/openchia/spec/registered-functions.md`** — the
    `library`/`function_id`/`interface`/`definition_id` pointer, ID derivation,
    interface-compatibility rules, and how a library registers. *(spec #5)*
11. **`docs/openchia/spec/materialized-specification.md`** — the part keys, JSON
    pointer scheme that notes bind to, and the hash set. *(spec #2)*

### P3 — contributor surface and hygiene

12. **Add `AGENTS.md` to `episode_builder/`, `episode_runtime/`,
    `iterative_episode_refiner/`, and `method_loop/`**, and add routing-table
    rows for all of them plus `agent/duet_*` and the six `*_library/` packages.
    Fix the `main.py` row and the stale test count. *(fixes S9 parts 1-3)*
13. **Replace `CONTRIBUTING.md`** with a short OpenChia-specific guide (how to
    add a library function, change a contract model — *and its schema version* —
    add an admission rule, write an ADR), linking to the Hermes guide for
    inherited subsystems. 53 KB → ~8 KB. *(fixes S9)*
14. **Write ADRs 0003-0012** from the list above; start with #1 (content-hash
    approval) and #2 (dataclasses-not-schemas), since P0 depends on #2 being
    settled. Add the `Accepted (implementation pending)` status and give ADR
    0001 an owner. *(fixes S14 + S10)*
15. **Raise docstring coverage on the five de facto spec modules to ≥80%**
    (currently ~27%), and add a CI floor so it cannot regress. Prioritize
    `numeric_control_library/controller.py` (10%) and
    `episode_library/registry.py` (0%). *(fixes S8)*
16. **Decide about `website/`** — 8.3 MB / 449 files describing a different
    product, which `AGENTS.md` actively routes contributors into. Either fork the
    developer-guide section or remove the routing and label it "upstream Hermes
    reference". Also: delete or retranslate the three stale READMEs and the two
    `.es` docs rather than shipping them as-is. *(fixes S5)*
17. **Document `OPENCHIA_CONTAINER_CLI`**; add `/steer`, `/btw`, `/exit` to
    `_HELP_TEXT`. *(fixes S11)*

---

## Method note

Every claim above was verified against the filesystem or git history at
`b56a3e4498`. Path existence was checked with a loop over the 20 `Source map`
entries and the 14 `AGENTS.md`-referenced paths. Docstring coverage was measured
<!-- no-tmp: ok — historical throwaway script path quoted from a review session, not guidance -->
with a throwaway AST script at `/tmp/dsc.py` (not added to the repo). Deleted
files were recovered via `git log --diff-filter=D` and sized with
`git show <commit>^:<path>`. No source file was modified.
