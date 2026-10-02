# OpenChia Review — Part 02: The Episode Creation Path

**Scope:** design/contract layer (`agent/duet_*.py`, `agent/episode_*.py`), build layer
(`episode_builder/`, ~8.7k LOC), refinement (`iterative_episode_refiner/`, ~3.8k LOC),
and the seven reusable component packages.

**Method:** read the real code at `/Users/me/Development/OpenChia` on `main` @ `b56a3e4498`.
Worktrees under `.claude/worktrees/` were excluded. No source file was modified.

**Headline:** the contract layer is unusually well designed — genuinely immutable value
types, content-addressed identity, a thorough re-verification path on approval, and a
static admission pass that is far stricter than most codegen systems bother with. The
problems are all *around* it: (1) ~18k LOC of the most authority-critical code in the
project has effectively zero direct test coverage, and the tests that covered its
predecessor were deleted wholesale in the refactor that created it; (2) the "registered
library catalog" the architecture document describes does not exist — it is a hand-edited
tuple literal; (3) the same authority-critical validation is implemented twice, in the
Duet and again in the planner; (4) validation error reporting to the human and to the
Duet LLM is structurally lossy — only one deficit survives per code+path, and the
anchor for any unanchored failure is the literal string `"goal"`.

---

## 1. What it does

### 1.1 Data structures and their lifecycle

The creation path moves one design through five representations. Each is a frozen
dataclass that validates in `__post_init__`, serializes through `as_record()`, and
re-parses through a strict `from_record()` that rejects unknown *and* missing keys.

| Stage | Type | Defined at | Owner |
|---|---|---|---|
| Model-facing blueprint | plain JSON dict | schema: `agent/episode_blueprints.py:473`, `:539` | Duet LLM / human |
| Validated design | `EpisodeWorkflowSpec` → `EpisodeDesignSpec` → `EpisodeCreationSpec` | `agent/episode_contract_models.py:905`, `:826`, `:650` | host |
| Durable draft revision | `workflow_draft_record(...)` dict | `agent/episode_blueprints.py:306` | Duet store |
| Frozen approval | `FrozenDuetWorkflow` + `DuetApproval` + `WorkflowAdmissionAuthority` | `agent/duet_contracts.py:484`, `:288`, `:371` | Duet store |
| Build input → output | `ApprovedBuildRequest` → `WorkflowMaterializationPlan` → `EmittedEpisodeModule` → `BuildAdmissionReport` → `BuildManifest` → `BuildReceipt` | `episode_builder/_contract_chain.py`, `_contract_plan.py`, `_contract_base.py` | Build store |

Two identity primitives thread through all of it, both in
`agent/episode_contract_models.py`:

- `OpaqueId` (`:237`) — `<kind>_<32..64 lowercase hex>`, minted by
  `OpaqueId.mint(kind, material)` (`:254`) as `kind_sha256(material)`. The docstring at
  `:239-244` states the real reason for the shape: it prevents a model-authored sentence
  from masquerading as an ID on the child-to-parent channel.
- `Sha256Digest` (`:267`) — `sha256:<64 hex>`, with `of_record()` (`:283`) hashing the
  canonical JSON of a record.

Content-addressing is used as an integrity mechanism, not decoration: an artifact's ID is
recomputed from its own fields on read and compared
(`agent/duet_service.py:436-449` for approvals, `:504-525` for frozen workflows,
`agent/duet_contracts.py:476-481` for the admission authority).

### 1.2 Conversation → validated Architecture revision

1. The Duet LLM is handed `EPISODE_WORKFLOW_BLUEPRINT_SCHEMA`
   (`agent/episode_blueprints.py:539`) as the JSON schema of the
   `episode_architecture_submit` tool (`tools/duet_tool.py:42,56`). The schema's
   `numeric_control` branch is *generated* from the live registries: `_selection_schema()`
   (`agent/episode_blueprints.py:102`) emits a `oneOf` over every admissible rarefaction /
   continuation function, pinning `library`/`function_id`/`interface`/`definition_id` as
   single-value enums and splicing in the function-owned `parameter_schema`
   (`:116-121`). The model therefore cannot name a function that is not registered.
2. The tool call lands in `_episode_architecture_submit`
   (`agent/inline_tool_executors.py:285`) → `openchia_host.submit_episode_architecture`
   (bound at `agent/openchia_host.py:267`) → `DuetService.record_initial_workflow_draft`
   (`agent/duet_service.py:751`).
3. That method takes `self._workflow_draft_lock` (`:774`), refuses if a refinement
   decision is already pending (`:776-780`), refuses unless the state is `DESIGNING` or
   `AWAITING_WORKFLOW_APPROVAL` (`:781-787`), then calls `_record_initial_draft` (`:799`).
4. `_record_initial_draft` performs compare-and-swap on the previous draft's
   `(artifact_id, content_hash, revision)` triple (`:817-844`) — a concurrent edit raises
   `DuetConflictError` rather than merging.
5. `validate_duet_workflow` (`:304`) is the admission gate. It
   (a) parses through `workflow_spec_from_blueprint` (`agent/episode_blueprints.py:264`),
   which in turn runs every node through `creation_spec_from_blueprint` (`:220`) and
   `admit_numerical_control` (`:184`);
   (b) requires exactly one root (`duet_service.py:343-349`);
   (c) checks each Episode's capabilities against the host ceiling (`:354-362`) and
   against its parent's set (`:377-392`);
   (d) rejects any deliverable that is not `TYPED_STATUS` (`:363-376`);
   (e) checks every egress rule's host and credential against the operator ceiling
   (`_egress_ceiling_deficits`, `:101`);
   (f) resolves any `episode_reference` against the Episode library (`:393-405`).
6. Result: `(workflow | None, tuple[ContractDeficit, ...])`. The draft is persisted
   either way, with `ready = not deficits` (`agent/episode_blueprints.py:332`), and the
   Duet state advances to `AWAITING_WORKFLOW_APPROVAL` only on a clean validation
   (`duet_service.py:873-877`). Every revision is appended, never overwritten — the
   revision counter is `prior + 1` (`:860`) and the write is a single
   `put_artifacts_with_transition` (`:878`) carrying the expected prior artifact identity
   *and* the expected state *and* the expected authority head.

Normalization detail worth noting: on a clean validation the stored blueprint is
*re-projected* from the parsed spec (`workflow_blueprint_from_spec(workflow)`, `:850`)
rather than stored as submitted, so the durable artifact is canonical. On a failed
validation the raw submission is stored instead (`:848`).

### 1.3 Approval freezes it

`approve_current_workflow` (`agent/duet_service.py:955`):

- requires state `AWAITING_WORKFLOW_APPROVAL` (`:963`);
- requires the named source draft to still be the *latest* draft and to match the
  caller's hash (`:965-980`) — otherwise `StaleDuetApprovalError`;
- **re-validates from scratch** (`:981-986`); any deficit aborts with
  `WorkflowAdmissionError`;
- snapshots the host ceiling into a `WorkflowAdmissionAuthority` artifact (`:1017`);
- mints `FrozenDuetWorkflow` whose `artifact_id` is `content_id("workflow", ...)` over
  the identity record (`:1018-1049`), binding duet, revision, workflow hash, authority
  hash, source draft identity+hash, and refinement lineage;
- mints `DuetApproval` whose `approval_id` is `content_id("approval", ...)` over
  duet + human authority + kind + artifact + content hash + revision + predecessor
  (`_approval`, `:925`);
- commits approval + both artifacts in one `commit_approval` call (`:1063`) guarded by
  expected latest-artifact identity and expected state.

The resulting invariant is strong: an approval names one content hash, and
`FrozenDuetWorkflow.__post_init__` refuses to construct if
`workflow_hash != workflow.workflow_hash` (`agent/duet_contracts.py:517-518`). Any later
revision produces a different hash, so a stale approval cannot authorize it.

`verify_workflow_approval` (`:468`) is the re-read path, and it is the strongest code in
the subsystem. It re-derives both content IDs, re-checks the approval→frozen→source-draft
→authority chain link by link (`:488-619`), **re-parses the stored blueprint and compares
the reconstructed workflow record against the frozen one** (`:561-570`), and re-applies
the capability and egress ceilings to the frozen workflow (`:620-643`). Nothing is
trusted because it was written once.

### 1.4 Approval → emitted, statically admitted package

`EpisodeBuilder.build` (`episode_builder/service.py:527`) is the pipeline:

1. `put_build_request` (`:537`) persists the exact approved input; a fresh `BuildAttempt`
   with a 32-byte nonce and the materializer model identity is persisted (`:538-543`).
2. `EpisodeMaterializationPlanner.plan` (`:578`) derives a leaf-first
   `WorkflowMaterializationPlan`. Structural facts are host-derived; the planning model
   contributes implementation detail and prompts. `_architecture_numeric_bindings`
   (`planner.py:357`) re-resolves the frozen numeric selections from the registries
   itself, and `_numeric_bindings_match` (`:440`) requires the model's returned bindings
   to canonically equal them. Any mismatch becomes a `BuildDeficit`, never a rewrite.
3. If `not plan.ready` the build terminates as `blocked` (`service.py:658-677`).
4. Leaf-first emission (`:692`). Nodes marked `unchanged` reuse the predecessor module
   byte-for-byte (`:709-732`); others go to `EpisodeModuleEmitter.emit` (`:762`).
5. `build_module_declaration` (`episode_builder/declaration.py`) appends a host-owned
   literal declaration binding the module to the approved contract, plan, functions,
   result identities and edges.
6. `EpisodeBuildAdmission.admit_outcome` (`admission.py:708`) runs static admission.
7. Manifest + receipt persisted via `_persist_receipt` (`service.py:419`).

### 1.5 What "static admission" actually checks

Package level, `episode_builder/admission.py:729-877`:

- the plan still validates against the request and attempt (`:731`);
- exactly one module per frozen Episode — duplicates (`:746`), unplanned (`:756`),
  missing (`:765`), module-without-plan (`:792`), module-name mismatch (`:802`);
- for `unchanged` nodes, the source hash must equal the predecessor manifest entry,
  else `unchanged_module_diverged` (`:825-839`);
- each admitted Episode gets a content-addressed `episode_id` minted from
  `{workflow_hash, local_id, node_plan_hash, module_name, source_hash}` (`:844-857`).

Per-module, `_inspect_source` (`admission.py:361-639`), **by `compile()` + `ast.parse()`,
never by import**:

| Check | Code | Line |
|---|---|---|
| syntax | `module_syntax_error` | `:385` |
| no executable top-level statements | `module_top_level_effect` | `:394` |
| all 9 required value exports present | `module_exports_incomplete` | `:402` |
| no required export assigned twice | `module_exports_reassigned` | `:409` |
| `build_controller_factory` / `build_episode` (+ root-only `build_goal_state`, `scope_goal_state`) exist with exact parameter lists | `builder_signature_invalid` | `:425-443` |
| children do not export root-only builders | `root_builder_on_child` | `:444-451` |
| no `global` / `nonlocal` | `module_state_mutation_forbidden` | `:452-458` |
| no mutation of module-level values (method call or attribute/subscript store/del) | `module_state_mutation_forbidden` | `:459-498` |
| root `scope_goal_state` returns an immutable goal view | `goal_view_mutable` | `:499-506` |
| every `generated` binding has a matching top-level function | `generated_function_missing` | `:508-518` |
| every `edge.*.receive_result` binding calls `handoff_library.admit_child_result` | `child_result_correlation_missing` | `:520-536` |
| embedded host declaration is a literal and canonically equals the host-computed one | `host_declaration_invalid` / `host_declaration_mismatch` | `:538-548` |
| `PROMPTS`, `EXECUTION_CAPABILITY_NAMES`, `RESULT_CHANNEL_NAMES`, `RESULT_CHANNEL_IDS` are literals canonically equal to the plan | `module_literal_invalid` / `module_literal_mismatch` | `:550-567` |
| closed import set — no relative imports, roots restricted to the 24-entry `_ALLOWED_IMPORT_ROOTS` (`:67`) | `relative_import_forbidden` / `module_import_forbidden` | `:569-583` |
| reference Episodes may not be imported concretely (only `episode_library.models`) | `reference_episode_imported` | `:584-590` |
| generated sibling modules may not be imported (runtime linker supplies children) | `concrete_episode_imported` | `:591-596` |
| no introspection attributes (`__globals__`, `__subclasses__`, …) | `python_introspection_forbidden` | `:598-604` |
| no direct-effect calls (`eval`, `exec`, `open`, `system`, `popen`, `urlopen`, `write_text`, …) | `direct_effect_forbidden` | `:605-613` |
| `FunctionImplementation.module` is a literal naming this module or an admitted internal library | `implementation_module_dynamic` / `implementation_module_forbidden` | `:614-638` |

This is a genuinely strong static gate, and the architecture document's claim that it
covers "syntax, closed imports, direct-effect restrictions, literal prompts,
capabilities, result channels, bindings, and source hashes"
(`OPENCHIA_ARCHITECTURE.md:103-104`) is accurate.

---

## 2. Severity-ranked findings

### F1 — The entire creation path has no tests; its predecessor's tests were deleted wholesale
**Severity: Critical**

Exactly four test files in the repository import anything from the creation path, and all
four test contract edges rather than the subsystems:

```
tests/agent/test_egress_allowlist_contract.py
tests/episode_runtime/test_egress_contracts.py
tests/episode_runtime/test_executor_http_loop.py
tests/episode_runtime/test_http_call_library.py
```

With `testpaths = ["tests"]` (`pyproject.toml:881-882`), the following have **zero**
direct test coverage:

| Package / module | LOC | Tests |
|---|---|---|
| `episode_builder/` | 8,696 | 0 |
| `iterative_episode_refiner/` | 3,850 | 0 |
| `agent/duet_service.py` | 1,297 | 0 |
| `agent/duet_store.py` | 1,120 | 0 |
| `episode_library/` | 2,653 | 0 |
| `numeric_control_library/` | 2,137 | 0 |
| `function_library/` | 631 | 0 |
| `handoff_library/` | 828 | 0 |
| `llm_call_library/` | 871 | 0 |
| `question_table_goal_library/` | 500 | 0 |
| **Total** | **~22,600** | **0** |

This is not an oversight of omission — the coverage was deleted. Git evidence:

- `5baa5a3b7d` "Build the Duet-owned Episode foundation" (2026-10-01):
  **4,428 test lines deleted, 126 added**. Removed `tests/agent/test_duet_protocol.py`
  (660), `test_episode_contracts.py` (436), `test_openchia_host.py` (521),
  `tests/tools/test_duet_tools.py` (291), `test_workflow_runtime.py` (236),
  `tests/hermes_cli/test_openchia_episode_editor.py` (215),
  `test_episode_blueprints.py` (100), plus the `creator_*` / `generic_creator_*` suites.
  The same commit *added* `episode_library/` (2,653 LOC) and `function_library/`
  (631 LOC) with no tests.
- `c2baf8b871` "Build the OpenChia workflow materialization MVP" (2026-10-01):
  **29,432 lines added, 6 test lines added, 692 test lines deleted.** This commit
  introduced all of `episode_builder/` and `iterative_episode_refiner/`.

**Why it matters.** This subsystem's entire value proposition is that the human approval
boundary cannot be bypassed. The invariants that enforce it — content-ID recomputation,
CAS on the authority head, state-machine gating, re-validation at approval, the 24 static
admission checks — are all unverified. Several concrete defects below (F4, F5) are exactly
the kind a single test would have caught. A silent regression here does not crash; it
quietly admits something the human did not approve.

**Fix.** Before any further feature work, add:
`tests/agent/test_duet_service.py` (state machine, CAS conflicts, stale approval,
re-validation at approval, `verify_workflow_approval` tamper cases — flip each stored
field and assert `DuetProtocolError`); `tests/episode_builder/test_admission.py` (one
negative case per deficit code in the table in §1.5 — ~24 cases, and the code list makes
this close to mechanical); `tests/episode_builder/test_service_terminal_states.py`
(blocked / failed / cancelled / materialized receipts);
`tests/function_library/test_admit_arguments.py`;
`tests/episode_library/test_catalog.py` (the `validate_topology()` at
`episode_library/catalog.py:26` already runs at import — assert it, plus duplicate/unknown
interface rejection). The old deleted suites are recoverable from `5baa5a3b7d^` as a
starting point for the Duet protocol tests.

---

### F2 — The "registered function catalog" is a hand-maintained tuple literal, not a registry
**Severity: High**

`OPENCHIA_ARCHITECTURE.md:59-61` states: *"The host derives the available catalog and
argument contracts from the registered libraries."* It does not.

`episode_builder/planner.py:322-346`:

```python
def _library_functions() -> tuple[LibraryFunction, ...]:
    return (
        ADMIT_PARENT_REQUEST, ADMIT_CHILD_RESULT, ADMIT_DUET_LAUNCH_REQUEST,
        COMPOSE_INCIDENCE_CONTROLLER, MARGINAL_DOMINATED_HYPERVOLUME,
        *continuation_function_library.functions(),
        *rarefaction_function_library.functions(),
        STRUCTURED_JSON_COMPLETION, PROBABILITY_JUDGMENT, PROBABILITY_VECTOR_JUDGMENT,
        HTTP_REQUEST, HTTP_JSON,
        OPEN_QUESTION_TABLE_GOAL, RESTORE_QUESTION_TABLE_GOAL,
        SCOPE_QUESTION_TABLE_GOAL, PROJECT_GOAL_PROMPT,
        CHECKPOINT_QUESTION_TABLE_GOAL, RESULT_COLUMN_SCHEMA, PROPOSE_TABLE_RESULTS,
        PROJECT_DIRECT_EVIDENCE_CANDIDATES, PROJECT_BEST_GUESS_EVIDENCE_CANDIDATES,
        PROJECT_ACCEPTED_IDENTITY_CHANNELS,
    )
```

21 functions, hand-enumerated, imported from 6 packages (`planner.py:21-49`). Supporting
facts:

- `FunctionLibrary` (`function_library/registry.py:8`) exists and is capable
  (`register` `:60`, `resolve` `:82`, `functions()` `:88`, `evaluation_report` `:94`,
  plus admission-scenario evaluation `_evaluate` `:25`).
- Only **four** instances of it exist, all inside `numeric_control_library`, each holding
  exactly **one** function: `rarefaction.py:493`, `controller.py:314`,
  `continuation.py:108`, `credit_assignment.py:961`.
- Two of those four are write-only. A repo-wide grep shows
  `controller_function_library` and `credit_function_library` are referenced only at
  their definition, their single `register()` call, and their `__all__` entry
  (`controller.py:314,315,358`; `credit_assignment.py:961,962,1022`). Nothing ever
  queries them — `planner.py:327-328` reaches past them to the bare
  `COMPOSE_INCIDENCE_CONTROLLER` / `MARGINAL_DOMINATED_HYPERVOLUME` constants.
- `llm_call_library`, `handoff_library`, `http_call_library` and
  `question_table_goal_library` have no registry at all. Their definitions are bare
  module constants (`llm_call_library/definitions.py:13,48,83`;
  `handoff_library/definitions.py:8,34,61`; `http_call_library/definitions.py:14,66`;
  `question_table_goal_library/definitions.py:58,82-176`) resolved purely by Python import.

**Why it matters.** Adding a function to any library is invisible to the planner and the
Duet unless a developer also edits `planner.py`. The failure is silent — the function
simply never appears in `materializer_function_catalog()` (`planner.py:349`) and therefore
can never be selected. There is no test that the catalog is complete, and
`_BASE_BINDING_ROLES` (`planner.py:452`) is a second hand-maintained list with the same
property.

**Fix.** Add a single `function_library/catalog.py` modelled exactly on
`episode_library/catalog.py:15-26` — the one place in the project that gets this right
(singleton, loop-register, `validate_topology()` at import). Give `FunctionLibrary` a
`by_interface(...)` / `by_role(...)` accessor, have each library package register its own
definitions into that singleton at import, collapse the four one-function
`numeric_control_library` registries into it, and reduce `_library_functions()` to
`catalog.functions()`. Add an import-time completeness assertion so a definition that is
not registered fails loudly.

---

### F3 — The same authority-critical function-selection admission is implemented twice
**Severity: High**

`agent/episode_blueprints.py:137-198` (`_admit_selection` / `admit_numerical_control`) and
`episode_builder/planner.py:357-437` (`_architecture_numeric_bindings.binding`) are
independent implementations of the same logic:

| Step | Duet side | Planner side |
|---|---|---|
| find function by `definition_id` in the library tuple | `episode_blueprints.py:143-150` | `planner.py:370-377` |
| build `{library, function_id, interface, definition_id}` expected pointer | `:156` (via `_selection_record`, `:93`) | `:382-387` |
| compare against the selection's own pointer | `:157-167` | `:388-397` |
| `function.admit_arguments(selection.arguments)` | `:169` | `:407` |
| require an `evaluation_report` for rarefaction | `:175-181` | `:398-406` |

They differ only in role naming (`"rarefaction"` vs `"controller.rarefaction"`) and error
type (`EpisodeContractError` with a `field_path` tuple vs `BuildDeficit`). A third,
partial copy of the "pointer must match the definition" idea lives in the generated
schema's single-value enums (`episode_blueprints.py:116-119`).

There is also a timing divergence: `_RAREFACTION_FUNCTIONS` and `_CONTINUATION_FUNCTIONS`
are frozen at **import time** as module constants (`episode_blueprints.py:126-134`), while
the planner calls `rarefaction_function_library.functions()` live each time
(`planner.py:363`, `:427`).

**Why it matters.** This is the check that enforces "function selections are approved
data, not planner choices" (`docs/openchia/duet_owned_episode_design.md:39-43`). If the
two copies drift, the Duet admits a selection the Builder blocks, or — worse — the
Builder accepts something the Duet would have rejected.

**Fix.** Extract one `admit_function_selection(selection, *, catalog, role) -> LibraryFunction`
into `function_library/` that raises a single structured error, and have both callers
adapt that error into their own deficit type. Pair with F2 so both read the same catalog
at the same time.

---

### F4 — Deficit de-duplication silently discards all but one offending Episode
**Severity: High (correctness bug)**

`agent/duet_service.py:406-409`:

```python
unique = {
    (item.code, item.field_path, item.blocking): item for item in deficits
}
return workflow, tuple(unique[key] for key in sorted(unique))
```

The de-duplication key omits `detail` and there is no episode identifier on
`ContractDeficit` at all (`agent/duet_contracts.py:258-277`: `code`, `field_path`,
`blocking`, `detail`). But the per-Episode deficits produced in the loop above all share a
fixed `(code, field_path, blocking)`:

- `capability_escalation` / `"execution_capability_names"` (`:357-362`) — and this one
  carries no `detail` at all, so even the single surviving deficit cannot say which
  Episode failed;
- `deliverable_not_runnable` / `"deliverable"` (`:367-376`) — detail embeds
  `item.local_id`;
- `capability_inheritance_violation` / `"execution_capability_names"` (`:383-392`) —
  detail embeds `item.local_id`;
- `unknown_episode_reference` / `"episode_reference"` (`:400-405`) — detail embeds
  `item.local_id`.

If three Episodes have a non-runnable deliverable, the human and the Duet LLM see exactly
one, naming whichever Episode happened to be last in dict-insertion order. They fix it,
resubmit, and get the next one. A 10-Episode workflow with a systematic error becomes 10
round trips.

**Why it matters.** Also note `capability_escalation` at `:357` and
`capability_inheritance_violation` at `:383` share `field_path="execution_capability_names"`
but differ in `code`, so they survive each other — the collapse is strictly within a code.
That makes the bug intermittent and easy to miss.

**Fix.** Add `episode_local_id: Optional[str]` to `ContractDeficit` (mirroring
`BuildDeficit`, `episode_builder/_contract_base.py:293`), include it in the dedup key, and
populate it at all four sites. Minimal alternative: include `detail` in the key.

---

### F5 — Unanchored validation failures are reported against the literal field `goal`
**Severity: High**

`ContractDeficit.field_path` is a **required, non-empty, dotted-lowercase string**
(`agent/duet_contracts.py:30`: `_FIELD_PATH = ^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$`,
enforced at `:273-274`). There is no way to express "the document as a whole". So
`duet_service.py` uses `"goal"` as the sentinel in three places:

- `:313` — *"Episode workflow must be a JSON object"* → `field_path="goal"`
- `:320-324` — any `EpisodeContractError` with an empty `field_path`, and every plain
  `TypeError`/`ValueError` from parsing → `field_path="goal"`
- `:349` — `single_root_required` → `field_path="goal"`

`goal` is a real, editable field of every Episode contract
(`episode_contract_models.py:654`). A Duet LLM told "your `goal` field has a deficit" when
the actual problem is that the workflow has two roots will edit the goal text. The
Workspace note system binds notes to an exact part key and JSON pointer
(`OPENCHIA_ARCHITECTURE.md:126-127`), so this mis-anchoring propagates into the UI.

Compare `BuildDeficit` (`episode_builder/_contract_base.py:287`), which was given a
deliberately wider grammar (`_FIELD_PATH` at `:16` admits `[` and `]`, 512 chars) *and* a
separate `episode_local_id` field. The builder-side deficit model is strictly more capable
than the Duet-side one that the human actually reads.

Verified:

```
'episodes[3].contract.goal'  ContractDeficit=False   BuildDeficit=True
'goal'                       ContractDeficit=True    BuildDeficit=True
```

**Fix.** Allow a sentinel such as `"workflow"` (already valid under the current regex and
not a real field name) or permit the empty string for document-level deficits, and use it
at `:313`, `:324`, `:349`.

---

### F6 — Node-level contract errors lose their Episode index, and the workaround is a re-validation hack that swallows exceptions
**Severity: High**

`contract_field` (`agent/episode_contract_models.py:145-159`) is a well-designed
error-anchoring context manager: it composes nested scopes outer-to-inner into an exact
`field_path` tuple. But it is applied inconsistently, and the one place it matters most is
missing.

Where it is used: `EpisodeCreationSpec.__post_init__` (`:667-738`),
`EpisodeEgressRule.__post_init__` (`:542-589`), parts of `from_record` (`:790-807`).

Where it is **not** used:
- `EpisodeFunctionSelectionSpec.__post_init__` (`:298-315`) — raises bare `ValueError`
- `EpisodeNumericalControlSpec.__post_init__` (`:350-358`) — bare
- `EpisodeDeliverableContract.__post_init__` (`:397-425`) — bare
- `EpisodeDesignSpec.__post_init__` (`:835-866`) — bare
- `EpisodeWorkflowSpec.__post_init__` (`:910-933`) — bare, and critically
- `workflow_spec_from_blueprint` (`agent/episode_blueprints.py:274-298`) loops
  `for index, raw_node in enumerate(raw_episodes)` and calls
  `creation_spec_from_blueprint(node["contract"])` at `:295` **without wrapping it in any
  index-bearing scope**.

Consequence: a failure in Episode #7's `goal` surfaces as `field_path=("goal",)`,
indistinguishable from a failure in Episode #0's. And it could not be fixed by simply
adding a scope, because `ContractDeficit`'s regex rejects `episodes[7].…` (see F5).

The project has already felt this pain and worked around it for exactly one field.
`_egress_rule_invalid_detail` (`agent/duet_service.py:78-98`):

```python
for node in episodes:
    ...
    try:
        creation_spec_from_blueprint(node.get("contract"))
    except EpisodeContractError as node_exc:
        if node_exc.field_path[:1] == ("egress_allowlist",):
            local_id = node.get("local_id")
            if isinstance(local_id, str):
                return f"{local_id}: {node_exc}"
    except (TypeError, ValueError):
        continue
```

This **re-runs the entire per-node validation** to recover information the first pass
threw away, works only for `egress_allowlist`, and at `:96-97` swallows `TypeError` and
`ValueError` with a bare `continue` — the exact swallowed-validation-error pattern the
project has a history of. It is reached from `:325-334`.

**Fix.** (1) Widen `_FIELD_PATH` in `duet_contracts.py:30` to admit `[`/`]` — align it
with `_contract_base.py:16`. (2) Wrap the node loop in
`with contract_field(f"episodes[{index}]"):` at `episode_blueprints.py:291-298`. (3) Apply
`contract_field` in the five `__post_init__` methods listed above. (4) Delete
`_egress_rule_invalid_detail` entirely — once (1)–(3) land, the first-pass error already
names the node.

---

### F7 — Validation stops at the first structural error
**Severity: Medium**

`validate_duet_workflow` (`agent/duet_service.py:317-341`) returns a **single-element**
tuple and `workflow=None` for any parse failure. Because `workflow_spec_from_blueprint`
raises on the first bad node, a blueprint with five malformed Episodes produces one
deficit, five times in a row.

The semantic checks below it (`:342-405`) do accumulate — the design intent is clearly
"collect everything" — but the structural layer short-circuits, and F4 then collapses what
the semantic layer did collect.

**Why it matters.** The architecture explicitly frames deficits as feedback to the Duet
LLM (`ContractDeficit`'s docstring, `duet_contracts.py:259-264`: *"so the Duet LLM can act
on why a field was rejected"*). One-at-a-time feedback multiplies conversational turns and
model cost linearly in the number of errors.

**Fix.** Make `workflow_spec_from_blueprint` collect per-node errors instead of raising on
the first: parse all nodes, gather `(index, local_id, EpisodeContractError)`, and return
them together. Depends on F6 for the anchoring.

---

### F8 — Massive copy-paste inside `episode_builder`: the emitter and the admission gate carry byte-identical AST analysers
**Severity: Medium**

Mechanically verified duplicate top-level definitions within `episode_builder/`:

| Symbol | Copies | Identical? |
|---|---|---|
| `_scope_goal_state_error` | `emitter.py:190-244`, `admission.py:234-298` | **yes** (55 lines; AST-identical, differs only in a set literal's line wrapping) |
| `_function_parameters` | `admission.py:207-218`, `inspection.py:705-716` | yes (12 lines) |
| `_mapping_proxy_call` | `emitter.py:177-187`, `admission.py:221-231` | yes (11 lines) |
| `_BUILD_EPISODE_PARAMETERS` | `emitter.py:49`, `admission.py:54`, `inspection.py:34` | yes (8 lines × 3) |
| `_ROOT_BUILDERS` | `emitter.py:58`, `admission.py:63`, `inspection.py:43` | yes (4 lines × 3) |
| `_BUILD_CONTROLLER_FACTORY_PARAMETERS` | `emitter.py:57`, `admission.py:62`, `inspection.py:42` | yes |
| `_EPISODE_ID` regex | `admission.py:39`, `_contract_base.py:19` | yes |
| `_REQUIRED_VALUES` | `emitter.py:37`, `admission.py:41` | **no** — they differ |
| `_imported_modules` | `emitter.py:247-275`, `admission.py:301-311` | **no** — 29 lines vs 11 |
| `_canonical` | `emitter.py:64`, `admission.py:160`, `planner.py:87` | **no** — three variants |
| `_text` | `inspection.py:84`, `_contract_base.py:36` | no |
| `_binding_record` | `planner.py:124`, `_contract_plan.py:57` | no |

Roughly **180 duplicated lines** inside one package. The already-diverged entries are the
dangerous ones: `_REQUIRED_VALUES` and `_imported_modules` differ between the emitter's
pre-check and the admission gate's authoritative check, which means the emitter can accept
a module that admission rejects (wasting a model call) or — if the divergence ever runs
the other way — pre-validate against a weaker rule.

There is a third divergence *within* `admission.py`: the `mutators` set at `:459-471` has
11 entries (includes `"add"`, `"discard"`) while the copy embedded in
`_scope_goal_state_error` at `:234+` has 9.

**Fix.** Create `episode_builder/_module_ast.py` holding `_BUILD_EPISODE_PARAMETERS`,
`_BUILD_CONTROLLER_FACTORY_PARAMETERS`, `_ROOT_BUILDERS`, `_REQUIRED_VALUES`,
`_function_parameters`, `_mapping_proxy_call`, `_scope_goal_state_error`,
`_imported_modules`, `_assigned_values`, and a single `MUTATOR_METHODS`. Import it from
`emitter.py`, `admission.py`, and `inspection.py`. This is a pure mechanical extraction
with no behaviour change, except that the two diverged pairs must first be reconciled —
and that reconciliation is itself the bug fix.

---

### F9 — Eight independent canonical-JSON implementations
**Severity: Medium**

Content hashes are the integrity backbone of the whole design
(`OPENCHIA_ARCHITECTURE.md:200-201`: *"Stable artifact hashes bind records between
stores"*). The canonical serializer they depend on is written eight times:

| Function | File:line |
|---|---|
| `_dump_json` | `agent/episode_contract_models.py:181` |
| `canonical_json` | `agent/duet_contracts.py:78` |
| `_canonical` | `episode_builder/planner.py:87` |
| `_canonical` | `episode_builder/admission.py:160` |
| `_canonical` | `episode_builder/emitter.py:64` |
| `_canonical` | `episode_library/models.py:25` |
| (inline) | `function_library/models.py:395-404` |
| (inline) | `iterative_episode_refiner/workspace.py:112-118` |

All use `ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")`, but
they differ in their pre-pass: `emitter._canonical` passes the value through unchanged,
`admission._canonical` runs `_plain()` (`:152`), `planner._canonical` runs `_plain_json()`
(`:79`), `duet_contracts.canonical_json` runs `_json_value()` (`:59`, which *rejects*
non-JSON values rather than coercing), and `episode_contract_models._dump_json` does no
pre-pass but relies on `_freeze_json` (`:191`) having run earlier.

There are also two names for one operation: `digest_record` (`duet_contracts.py:615`) and
`Sha256Digest.of_record` (`episode_contract_models.py:283`) compute the same value by
different routes.

The same problem repeats one level up, for the *identity records* themselves. The exact
field sets fed to `content_id("approval", …)` and `content_id("workflow", …)` are written
out twice, in two packages:

| Identity record | Duet side | Builder side |
|---|---|---|
| approval | `agent/duet_service.py:162-184` (`_approval_identity_record`) | `episode_builder/_contract_chain.py:53-70` (`_approval_identity`) |
| frozen workflow | `agent/duet_service.py:187-217` (`_frozen_identity_record`) | `episode_builder/_contract_chain.py:72-94` (`_frozen_workflow_identity`) |

Both pairs enumerate the same 7 and 9 keys respectively, in the same order, with the same
`None`-vs-`.value` handling. These are the hashes that decide whether an approval is
authentic (`duet_service.py:448`) and whether a build request names a real approval. A
field added to `DuetApproval` or `FrozenDuetWorkflow` and wired into only one of the two
produces IDs that no longer agree across the Duet/Build store boundary.

Deep-freeze helpers are likewise triplicated: `_freeze_json` / `_thaw_json` at
`agent/episode_contract_models.py:191,216`, `episode_builder/_contract_base.py:74,99`, and
`function_library/models.py:30,57` — with a fourth variant `_freeze` at
`episode_builder/inspection.py:49`. The `_contract_base` copy uses a hand-rolled NaN/inf
test rather than `math.isfinite`, so its acceptance set is not provably the same as the
other two.

**Why it matters.** A divergence in any pre-pass (e.g. `_plain` stringifies non-string
mapping keys, `_json_value` raises on them) produces a different digest for the same
logical content. Since digests gate approval validity (`duet_service.py:556`) and
unchanged-module reuse (`admission.py:827-830`), a drift here is a silent authority bug,
not a crash.

**Fix.** One `canonical_json(value) -> str` and one `digest(value) -> Sha256Digest` in a
shared module (`agent/episode_contract_models.py` is the natural home since everything
already imports `Sha256Digest` from the `agent.episode_contracts` facade). Delete the
seven others. Keep exactly one normalization policy and document whether non-JSON input
coerces or raises.

---

### F10 — Three parallel deficit models, and the one the human reads is the weakest
**Severity: Medium**

| Type | File:line | Fields | `field_path` grammar |
|---|---|---|---|
| `ContractDeficit` | `agent/duet_contracts.py:258` | code, field_path, blocking, detail? | `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$` — no brackets, no episode ID |
| `BuildDeficit` | `episode_builder/_contract_base.py:287` | code, field_path, detail, **episode_local_id**, blocking | `^[a-z][a-z0-9_.\[\]-]{0,511}$` |
| `ProjectedDeficit` | `episode_builder/inspection.py:238` | origin, BuildDeficit | wraps `BuildDeficit` |

`ContractDeficit` governs the Duet LLM's and the human's view of Architecture problems and
is the least expressive of the three. F4 and F5 are both direct consequences.

**Fix.** Collapse `ContractDeficit` and `BuildDeficit` into one `Deficit` value type with
`code`, `field_path`, `detail`, `episode_local_id`, `blocking`, and keep `ProjectedDeficit`
as the `(origin, deficit)` wrapper. One grammar, one dedup rule.

---

### F11 — `build()` is a 472-line method with 18 near-identical terminal branches
**Severity: Medium**

`EpisodeBuilder.build` spans `episode_builder/service.py:527-998`. It contains **18**
`_persist_receipt(...)` call sites (`:561, 590, 614, 634, 665, 695, 718, 748, 781, 807,
822, 840, 860, 901, 915, 930, 970, 983`), each passing the same 11 keyword arguments with
only `status`, `stage`, `deficits`, and `emitted_modules` varying. The
`cancelled → _terminal_plan → put_plan → _persist_receipt` sequence appears verbatim four
times (`:554-573`, `:583-602`, `:627-646`, and inline variants at `:693-707`, `:829-848`).

That is roughly **230 lines of boilerplate** in a single function, in the component whose
correctness claim is "a materialized receipt means that exact source passed static
admission" (`OPENCHIA_ARCHITECTURE.md:105-107`). Every terminal path is a place where a
wrong `status` or a dropped deficit tuple produces a receipt that overclaims.

**Fix.** Introduce a `_BuildTermination(Exception)` carrying `(status, stage, deficits,
emitted, plan)` and a single `except _BuildTermination` handler that calls
`_persist_receipt` once; or a `_terminate(...)` helper that closes over
`build_request`, `build_attempt`, `progress_callback`, `total`. Either reduces the method
to its actual control flow and makes the terminal-status matrix reviewable.

---

### F12 — `parameter_schema` is advertised to the model as JSON Schema but validated by a shallow subset
**Severity: Medium**

`_selection_schema` (`agent/episode_blueprints.py:102-123`) splices each function's
`provenance["parameter_schema"]` verbatim into the model-facing tool schema (`:120`). The
host-side enforcement is `LibraryFunction.admit_arguments`
(`function_library/models.py:431`) → `_validate_parameter_object` (`:108`) →
`_validate_parameter_value` (`:65`).

That validator supports: `type` (6 primitives), `minimum`/`maximum`/`exclusiveMinimum`/
`exclusiveMaximum`, `enum`, and object-level `properties`/`required`/`additionalProperties`.

It does **not** support: nested object recursion (a `"type": "object"` property is checked
only for being a Mapping — `:76`), array `items` / `minItems` / `maxItems` /
`uniqueItems`, string `pattern` / `minLength` / `maxLength`, `oneOf` / `anyOf` / `allOf`,
`const`, or `$ref`.

Currently latent: all four live `parameter_schema` values are flat and within the
supported subset (`numeric_control_library/rarefaction.py:536-547`,
`continuation.py:131-142`, `http_call_library/definitions.py:49-60`, `:104-112`). But the
moment a library ships a nested or array-shaped parameter, the Duet LLM will be shown a
constraint the host silently does not enforce, and an out-of-contract argument will be
frozen into an approved Architecture.

**Fix.** Either depend on a real JSON Schema validator for `admit_arguments`, or add a
registration-time guard in `FunctionLibrary.register` (`registry.py:60`) that rejects any
`parameter_schema` using an unsupported keyword, so the limitation fails loudly at import
rather than silently at admission.

---

### F13 — Declarative and imperative copies of the same numeric argument constraints
**Severity: Medium**

Each numeric control function states its argument contract twice:

| Constraint | Declarative | Imperative |
|---|---|---|
| `uncertainty_alpha`: exactly this key, `0 < a < 1` | `rarefaction.py:536-547` (`exclusiveMinimum: 0`, `exclusiveMaximum: 1`, `additionalProperties: false`) | `validate_paired_incidence_parameters`, `rarefaction.py:47-59` |
| `max_predicted_marginal_hypervolume`: exactly this key, `0 ≤ t ≤ 1` | `continuation.py:131-142` | `validate_predicted_credit_parameters`, `continuation.py:24-43` |

The declarative copy is checked at Architecture admission (`admit_arguments`); the
imperative copy is checked at runtime (`rarefaction.py:179`, `:286`;
`continuation.py:90`). Nothing tests that they agree. A loosened schema with an unchanged
validator yields an approved Architecture that fails at runtime; the reverse yields a
runtime that accepts what the human never approved.

**Fix.** Generate one from the other, or add a test asserting that for each function the
schema and the validator accept and reject the same boundary values.

---

### F14 — `FunctionLibrary` and `EpisodeLibrary` are parallel registries with no shared abstraction
**Severity: Low–Medium**

`function_library/registry.py:8` and `episode_library/registry.py:10` have the same shape,
written twice:

| Concern | `FunctionLibrary` | `EpisodeLibrary` |
|---|---|---|
| backing dict | `_functions` `:21` | `_by_id`, `_by_name` `:12-13` |
| `register()` with isinstance + duplicate check | `:60-80` | `:15-28` |
| `resolve()` with `KeyError → ValueError` | `:82-86` | `:30-34` |
| sorted listing | `functions()` `:88` | `designs()` `:52` |
| structural validation | `_evaluate` `:25` | `validate_topology` `:92` |

Neither has a base class or Protocol. The ID-derivation pattern is also duplicated:
`LibraryFunction.definition_id` is computed inline at `function_library/models.py:395-409`
as `function_<sha256(canonical(definition_record))>`, while
`EpisodeLibraryDesign.episode_id` is computed at `episode_library/models.py:132-133` as
`episode_<sha256(_canonical(semantic_record()))>` using a factored-out `_canonical`
(`:25`). Same algorithm, different factoring, both reimplementing F9.

Small cross-package helper duplication (verified byte-identical):
- `_text` — `function_library/models.py:24`, `episode_library/models.py:19`,
  `llm_call_library/contracts.py:56`
- `_STABLE_ID` regex + `_stable_id()` — `handoff_library/contracts.py:14,19`,
  `question_table_goal_library/contracts.py:19,23`,
  `numeric_control_library/credit_assignment.py:41,66`. **These three have diverged from
  the authoritative definition:** all three accept `^[a-z][a-z0-9_]{0,31}_[0-9a-f]{24,64}$`,
  while the host's `_OPAQUE_ID` (`agent/episode_contract_models.py:37`) requires
  `{32,64}`. The libraries are strictly more permissive than the minter — a 24-to-31-hex
  ID that `OpaqueId.__post_init__` (`:248-252`) would reject passes library validation.
  Latent today because `OpaqueId.mint` (`:254`) always emits a full 64-hex SHA-256
  digest, but this is precisely the check whose docstring (`:239-244`) says the shape
  exists to stop model-authored prose masquerading as an ID, so the looser copies should
  not be the ones the runtime libraries enforce.
- `_finite()` — `numeric_control_library/credit_assignment.py:44`, `continuation.py:15`,
  `rarefaction.py:38`
- `_ids()` / `_stable_ids()` — `handoff_library/contracts.py:31` vs
  `question_table_goal_library/contracts.py:29`, differing only in `ValueError` vs
  `TypeError` on the tuple check

~100 lines of cross-package duplication, plus ~120 lines of the four-times-repeated
`FunctionLibrary() + register(LibraryFunction(...))` boilerplate inside
`numeric_control_library`.

**The right shared abstraction.** The `LibraryFunction` definition model is *already* the
correct shared abstraction and five of the six function packages use it — that part of the
design is sound and should be stated as such. What is missing is one layer up:

1. A `ComponentRegistry[T]` generic (or simply a shared `_Registry` base) holding the
   dict, the duplicate check, the `resolve`-raises-`ValueError` contract, and the sorted
   listing. `FunctionLibrary` and `EpisodeLibrary` then add only their domain-specific
   validation (`_evaluate`, `validate_topology`).
2. A shared `content_identity(kind, record) -> str` used by both `definition_id` and
   `episode_id` — this is the same primitive as `OpaqueId.mint`
   (`agent/episode_contract_models.py:254`), which already exists and does exactly this.
   Three implementations of one idea.
3. A small `component_validation` module for `_text`, `_stable_id`, `_stable_ids`,
   `_finite` and the `_STABLE_ID` regex, imported by all seven packages.

Caveat on sequencing: the seven packages are deliberately import-isolated because
`_ALLOWED_IMPORT_ROOTS` (`episode_builder/admission.py:67-95`) is the closed import
surface for generated Episode modules, and `_INTERNAL_IMPLEMENTATION_ROOTS` (`:96-106`)
lists which of them a `FunctionImplementation` may name. Any new shared module must either
live inside `function_library/` (already an admitted root) or be added to both frozensets
deliberately. Do not introduce a top-level `common/` without that change.

---

### F15 — Dead code
**Severity: Low**

Verified by repo-wide grep (excluding `.claude/worktrees/`):

| Symbol | File:line | Status |
|---|---|---|
| `_local_identifier` | `agent/episode_contract_models.py:102` | never called; `EpisodeDesignSpec.__post_init__` re-implements it inline twice at `:836-845` and `:848-857` |
| `_number` | `agent/episode_contract_models.py:84` | never called |
| `_non_negative_int` | `agent/episode_contract_models.py:96` | never called |
| `EpisodeBuildAdmission.repository_root` | `episode_builder/admission.py:684-692` | assigned, never read; the `root.is_dir()` check at `:690` is a startup failure mode for no benefit |
| `admit_workflow_modules` | `episode_builder/admission.py:880` | in `__all__`, never called anywhere including tests |
| `admit_workflow_outcome` | `episode_builder/admission.py:894` | in `__all__`, never called anywhere including tests |
| `controller_function_library` | `numeric_control_library/controller.py:314` | only its own `register()` call and `__all__` reference it |
| `credit_function_library` | `numeric_control_library/credit_assignment.py:961` | same |
| `DuetStore.transition_state` | `agent/duet_store.py:244` | definition is the only occurrence; all transitions go through `put_artifacts_with_transition` / `commit_approval` |
| `DuetStore.get_refinement_cycle` | `agent/duet_store.py:591` | definition only; `active_refinement_cycle` is always used instead |
| `DuetStore.latest_approval` | `agent/duet_store.py:1067` | definition only |
| `DuetStore.events` | `agent/duet_store.py:1097` | definition only — the `duet_events` table is written but never read back |
| `EpisodeLibrary.resolve_name` | `episode_library/registry.py:36` | definition only |
| `EpisodeLibrary.compatible_children` | `episode_library/registry.py:55` | definition only |
| `EpisodeLibrary.resolve_function` | `episode_library/registry.py:68` | only caller is itself delegating to `models.py:151` |
| `EpisodeLibrary.validate_attachment` | `episode_library/registry.py:75` | definition only |
| `EpisodeLibrary.catalog_record` | `episode_library/registry.py:89` | definition only |
| `FunctionLibrary.validate_implementation` | `function_library/registry.py:91` | definition only |
| `EpisodeCreationSpec.from_json` | `agent/episode_contract_models.py:822` | in `__all__`, zero callers |
| `EpisodeWorkflowSpec.from_json` | `agent/episode_contract_models.py:961` | in `__all__`, zero callers |
| `DuetMessageKind` | `agent/duet_contracts.py:138` | in `__all__`, zero references outside its own definition |
| `DuetDesignState.WAITING_ON_DUET` | `agent/duet_contracts.py:123` | enum member never read; the literal appears only here |

Note that 7 of the 10 public methods on `EpisodeLibrary` are unreachable, as is the only
non-trivial accessor on `FunctionLibrary` beyond `resolve`/`functions`. That is consistent
with F2 and F14: these registries were designed for a role they were never actually wired
into.

Three `DuetDesignState` members (`REJECTED` `:128`, `CANCELLED` `:129`, `FAILED` `:130`)
are also never referenced via the enum. Unlike the items above these are *probably*
intentional — they are persisted state values a store row could legitimately hold — but no
code can currently produce or consume them, so the state machine's reachable set is
smaller than its declared set and nothing documents the difference.

**Over-exported rather than dead** (used internally, but in `__all__` with zero external
importers — worth narrowing the public surface, not deleting):
`admit_numerical_control` (`agent/episode_blueprints.py:184`, called only at `:240`),
`CREATION_BLUEPRINT_FIELDS` (`:32`, used only at `:43`),
`CapabilityInheritance` (`agent/episode_contract_models.py:224`, used only at `:664`,
`:735`, `:785`).

Also duplicated:

- `_object` / `_exact_fields` / `_plain_json` in `agent/episode_blueprints.py:70-90`
  re-implement `_record` / `_keys` / `_thaw_json` from
  `agent/episode_contract_models.py:53-66, 216`, which that same module already imports
  from.
- `_artifact_spec` is byte-identical (17 lines) in `agent/duet_service.py:143-159` and
  `iterative_episode_refiner/service.py:87-103`.

**Positive:** there are **zero** `TODO` / `FIXME` / `XXX` / `HACK` markers and no
commented-out code blocks anywhere in the ~22.6k LOC in scope.

**Stale references — verified status:**

- `agent/workflow_runtime.py` — **correctly removed** (in `5baa5a3b7d`). The only surviving
  mentions are in `scratchpad.md:9` and `:70`, which describe it as removed. No code or
  test references it. ✅
- The tool rename to `episode_architecture_submit` — **consistently applied** across
  `tools/duet_tool.py:42`, `agent/inline_tool_executors.py:285,559`,
  `agent/duet_contracts.py:151`, `agent/openchia_agents.py:15`, `model_tools.py:619`,
  `toolsets.py:165`, `tools/tool_search.py:42`, `agent/openchia_host.py:267`,
  `agent/prompt_builder.py:184,430`, and the two tests. No stale `workflow_draft_submit` /
  `creator_*` / `generic_creator_*` names remain in code. ✅
- One layering leak: `agent/episode_contracts.py` is the documented public facade
  (`:1-5`) and 30 call sites use it, but `episode_runtime/identity.py` imports
  `agent.episode_contract_models` directly, bypassing it.

---

## 3. Design quality assessment

**Immutability and modelling — strong.** Every contract and value type in scope is
`@dataclass(frozen=True)`. Collections are tuples, not lists. Nested JSON is deep-frozen
through `_freeze_json` (`agent/episode_contract_models.py:191-213`), which returns
`MappingProxyType` for mappings and tuples for sequences and *rejects* anything not
JSON-shaped (`:213`) — so an `EpisodeFunctionSelectionSpec.arguments` cannot be mutated
after construction (`:312-315`). Round-tripping is symmetric: `as_record()` / `from_record()`
on every type, with `_keys` (`:59`) enforcing an exact key set so an unknown key is an
error rather than a silently retained second channel (stated explicitly in the module
docstring at `:9-10`).

**Invariants at construction — strong, and this is the project's best habit.** Validation
lives in `__post_init__`, not in a separate `validate()` that callers might skip. Good
examples: `FrozenDuetWorkflow` refuses to exist if its hash does not match its content
(`duet_contracts.py:517-518`); `WorkflowAdmissionAuthority.from_record` recomputes and
compares its own ID and hash (`:476-481`); `EpisodeDeliverableContract` enforces the
kind↔tool_names correlation both ways (`episode_contract_models.py:422-425`);
`EpisodeWorkflowSpec` checks uniqueness, parent existence, self-parenting, and acyclicity
(`:910-933`); `EpisodeEgressRule` requires `read_only is True` with no override
(`:564-569`).

**Dependency direction — correct, and worth calling out.** `iterative_episode_refiner`
does not import `DuetService`. It declares exactly the three read-only methods it needs as
a `RefinementAuthorityReader` Protocol (`iterative_episode_refiner/service.py:63-84`) and
lets `agent/duet_service.py:46-55` depend on it instead. That is proper dependency
inversion across a subsystem boundary and keeps the "the refiner cannot approve its own
output" invariant (`OPENCHIA_ARCHITECTURE.md:37-39`) structurally enforceable rather than
merely conventional.

**Centralization of validation — mixed, and this is the main structural weakness.** There
are three well-separated *layers* (blueprint → contract → semantic/ceiling), which is
right. But within and across layers the same checks recur: canonical JSON ×8 (F9),
function-selection admission ×2 (F3), AST module analysis ×2 (F8), numeric argument
constraints ×2 (F13), capability/egress ceilings ×2 (`duet_service.py:354-392` producing
deficits vs `:620-643` raising — defensible as defence-in-depth, but note that
`verify_workflow_approval` does *not* re-check the single-root or deliverable rules, so
the two sets have already diverged), identity-record field sets ×2 (F9), and the
non-empty-text guard `_text` **×8**: `agent/episode_contract_models.py:69`,
`agent/duet_contracts.py:38`, `episode_builder/_contract_base.py:36`,
`episode_builder/inspection.py:84`, `iterative_episode_refiner/contracts.py:32`,
`function_library/models.py:24`, `episode_library/models.py:19`,
`llm_call_library/contracts.py:56`. They are not interchangeable — four take a `maximum`
keyword, one takes it positionally, three take none — so the "same" validation silently
applies different length policies depending on which module constructed the value.

**Error reporting — the weakest dimension, and the known history is still visible.** The
mechanism (`EpisodeContractError` + `contract_field`,
`agent/episode_contract_models.py:131-159`) is well designed and well documented. But it
is applied to roughly half the types (F6), its output is lossily narrowed by
`ContractDeficit`'s grammar (F5), the narrowing forced a re-validation workaround that
itself swallows two exception types (`duet_service.py:96-97`, F6), and the deficit set is
then de-duplicated in a way that discards all but one offending Episode (F4). On the
positive side, `_host_detail` (`duet_contracts.py:103-111`) is careful about where detail
text comes from, and the `ContractDeficit` docstring (`:259-264`) is explicit that detail
is host-authored only — never model- or human-supplied. That distinction is correct and
worth preserving through any fix.

---

## 4. Documentation

**Module docstrings: 58/58 — 100%.** Every file in scope has one, and most are genuinely
informative about *why* rather than *what*. Best examples:
`agent/episode_contract_models.py:1-11` (explains why deserializers reject unknown keys),
`OpaqueId:239-244` (explains the anti-prose-injection purpose of the ID shape),
`ContractDeficit:259-264`, `WorkflowAdmissionAuthority:373-380`,
`iterative_episode_refiner/contracts.py:1-8`.

**Public API docstrings: 166/501 — 33%.** Worst offenders are precisely the modules the
architecture leans on hardest:

| Module | Public defs | Documented |
|---|---|---|
| `episode_library/registry.py` | 11 | **0** |
| `function_library/registry.py` | 6 | **0** |
| `numeric_control_library/controller.py` | 19 | 2 (10%) |
| `iterative_episode_refiner/contracts.py` | 41 | 8 (19%) |
| `episode_builder/_contract_chain.py` | 21 | 4 (19%) |
| `agent/duet_contracts.py` | 29 | 6 (20%) |
| `iterative_episode_refiner/service.py` | 20 | 4 (20%) |
| `episode_builder/_contract_base.py` | 21 | 5 (23%) |
| `agent/duet_service.py` | 14 | 4 (28%) |
| `agent/duet_store.py` | 25 | 7 (28%) |

The two registry modules having zero documented methods is the sharpest gap: they are the
abstraction F2 and F14 say should be the centre of the component system.

**Is there a written spec for the Architecture format?** Partially, and it is split in a
way that invites drift.

- A machine-readable JSON Schema exists as a Python dict:
  `EPISODE_WORKFLOW_BLUEPRINT_SCHEMA` (`agent/episode_blueprints.py:539`) composed from
  `EPISODE_CREATION_BLUEPRINT_SCHEMA` (`:473`),
  `EPISODE_NUMERICAL_CONTROL_BLUEPRINT_SCHEMA` (`:370`),
  `EPISODE_DELIVERABLE_BLUEPRINT_SCHEMA` (`:346`),
  `EPISODE_EGRESS_RULE_BLUEPRINT_SCHEMA` (`:396`). Its field `description` strings are
  good prose documentation.
- It is used **only** as the LLM tool schema (`tools/duet_tool.py:7,56,144`). It never
  validates anything host-side. Validation is the independent hand-written code in
  `episode_contract_models.py` / `episode_blueprints.py`.
- The two have already drifted, in both directions:
  - `deliverable.kind` schema enum is `["typed_status"]` (`:353`), but
    `EpisodeDeliverableKind` (`episode_contract_models.py:230`) also has `SHARED_STATE`
    and `EpisodeDeliverableContract.from_record` accepts it — it is rejected two layers
    later as a `deliverable_not_runnable` deficit (`duet_service.py:367`).
  - `execution_capability_names` schema says `"maxItems": 0` (`:520-521`); the validator
    `_name_tuple` (`episode_contract_models.py:112`) imposes no count limit.
  - `local_id` schema is bare `{"type": "string"}` (`:548`) while the validator requires
    `^[a-z][a-z0-9_-]{0,63}$` (`episode_contract_models.py:39`, enforced `:841-845`) — the
    model is given no hint of the real constraint.
  - `episode_reference` schema (`:551-567`) is written inline rather than derived from
    `EpisodeReference`.
- No drift test exists (no test file imports both the schema and the validator for
  comparison).

**`schemas/openchia/` — confirmed absent.** `find`/`ls` show no `schemas/` directory
anywhere in the repository. The only surviving reference is `scratchpad.md:10`
(*"schemas in `schemas/openchia/`"*), which is stale project notes, not a code or build
reference. Nothing imports or reads such a path, so the absence breaks nothing — but the
note should be corrected, and the gap it implies (a versioned, exported Architecture
schema) is real: the authoritative format currently exists only as a Python dict inside
`agent/episode_blueprints.py`, invisible to any non-Python consumer.

**Doc-vs-code accuracy.** `OPENCHIA_ARCHITECTURE.md` and
`docs/openchia/duet_owned_episode_design.md` are accurate about the approval boundary, the
build pipeline, the receipt semantics, and the static-admission surface. The one material
inaccuracy is `OPENCHIA_ARCHITECTURE.md:59-61` — *"The host derives the available catalog
and argument contracts from the registered libraries"* — which F2 shows is not what the
code does. The source map at `:203-224` is otherwise correct.

**Fix.** (1) Export the schema to `schemas/openchia/architecture.schema.json` at build
time from the Python dict, so there is one source and an inspectable artifact; (2) add a
drift test asserting that the schema and the validators agree on the four divergences
listed above; (3) docstring the two registry modules; (4) correct
`OPENCHIA_ARCHITECTURE.md:59-61` or implement F2 so the sentence becomes true;
(5) fix `scratchpad.md:10`.

---

## 5. Recommended order of work

1. **F1** — tests first. Everything below is a refactor of untested code, which is how
   invariants get lost. The per-deficit-code admission suite is close to mechanical.
2. **F4, F5** — two small, self-contained correctness fixes to deficit reporting
   (add `episode_local_id`, widen the field-path grammar).
3. **F6, F7** — anchoring and multi-error collection; deletes
   `_egress_rule_invalid_detail` and its swallowed exceptions.
4. **F9** — one canonical-JSON implementation. Do this before F2/F3/F8 so the extractions
   have a single serializer to depend on.
5. **F8** — mechanical extraction of `episode_builder/_module_ast.py`, reconciling the two
   diverged pairs as part of it.
6. **F2, F3, F14** — the component-registry work, as one coherent change. Mind the
   `_ALLOWED_IMPORT_ROOTS` constraint noted in F14.
7. **F11, F12, F13, F15** — cleanup.
