# OpenChia Review — Part 05: Test Coverage and Test Quality

**Date:** 2026-10-02
**Scope:** test coverage and test quality for the **OpenChia layer only** (not inherited hermes-agent tests)
**Repo:** `/Users/me/Development/OpenChia` @ `b56a3e4498` (main)
**Platform:** macOS (darwin 25.6.0), Python 3.14.7, tests run via `scripts/run_tests.sh`

---

## 1. Executive answer: "are major components tested?"

**No. Most are not.**

Of ~43,000 lines of OpenChia-layer source across 22 modules/packages, there are **13 test files, ~2,580 lines of test code, 97 test functions (219 parametrized cases)**. That is a ~6% test-to-source line ratio, and it is not evenly spread: essentially all of it sits on one recently-added feature (the HTTP broker / egress allowlist, PR #11) plus the Run executor.

The breakdown:

- **3 components are genuinely tested**: `episode_runtime`'s HTTP/egress surface, `http_call_library`, and the container Run executor.
- **4 components are thinly tested** — they get incidental coverage because one egress test happens to import them: `agent/duet_service.py`, `agent/duet_store.py`, `agent/duet_contracts.py`, `agent/episode_blueprints.py`, plus `method_loop` (3 tests for 2,376 lines).
- **15 components are untested** — zero tests import them at all: `agent/openchia_host.py` (1,883 lines), `agent/episode_contract_models.py` (988), the whole of `episode_builder/` (8,696), the whole of `iterative_episode_refiner/` (3,850), five of the seven library packages, and the entire OpenChia CLI surface (~4,200 lines).

This is not a slow accumulation of debt. **It is a regression**: two commits in the last two weeks deleted 121 OpenChia test functions (~4,800 lines) and added zero replacements. Details in §4.

---

## 2. Measured test results (real runs, not estimates)

All runs via `scripts/run_tests.sh` (per-file subprocess isolation, `TZ=UTC`, `PYTHONHASHSEED=0`, hermetic `env -i`).

### 2.1 OpenChia-layer suites — **clean**

```
$ ./scripts/run_tests.sh tests/episode_runtime/ tests/method_loop/ tests/agent/test_egress_allowlist_contract.py

Discovered 12 test files (~94 tests); running with -j 10
=== Summary: 12 files, 219 tests passed, 0 failed (100% complete) in 9.8s (10 workers) ===
```

| File | Tests |
|---|---:|
| `tests/episode_runtime/test_http_protocol.py` | 70 |
| `tests/agent/test_egress_allowlist_contract.py` | 50 |
| `tests/episode_runtime/test_http_broker.py` | 37 |
| `tests/episode_runtime/test_http_call_library.py` | 17 |
| `tests/episode_runtime/test_container_executor.py` | 17 |
| `tests/episode_runtime/test_egress_contracts.py` | 10 |
| `tests/episode_runtime/test_seccomp_machine.py` | 6 |
| `tests/episode_runtime/test_interpreter_path.py` | 4 |
| `tests/episode_runtime/test_supplied_interpreter_identity.py` | 3 |
| `tests/method_loop/test_episode_tree_recursion.py` | 3 |
| `tests/episode_runtime/test_executor_http_loop.py` | 1 |
| `tests/episode_runtime/test_staged_closure_imports.py` | 1 |
| **Total** | **219** |

`tests/episode_runtime/` alone = **166 tests**, confirming the project note exactly.

Everything the OpenChia layer actually tests passes on macOS. Nothing here is environment-skipped except one test (`test_live_image_interpreter_identity_is_stable_and_pinned`, gated on a reachable Linux container daemon).

### 2.2 `tests/agent/` — **9 failures, matches the project note**

```
=== Summary: 932 files, 10002 tests passed, 9 failed, 59 skipped (100% complete) in 803.9s (10 workers) ===
```

Stable across two independent full runs (9 failures both times, same 5 files). Root causes:

| Test | n | Root cause | OpenChia-caused? |
|---|---:|---|---|
| `test_memory_provider_init.py::test_core_tool_names_rejected_from_memory_routing_table` | 1 | asserts `delegate_task` is absent from the memory routing table; `MemoryManager.has_tool('delegate_task')` returns True | **Likely yes** — see below |
| `test_run_agent.py::...::test_agent_runtime_tools_emit_once_per_executor_path[delegate_task-tool_args13]` | 1 | asserts agent-runtime tools stay inline; `delegate_task` escapes to `model_tools.handle_function_call` | **Likely yes** — see below |
| `test_verification_continuation_budget.py` (3 tests) | 3 | off-by-one: got `max_iterations_reached(2/1)`, expected `(1/1)` | Inherited behaviour drift |
| `test_compaction_prompt_rebuild.py` (3 tests) | 3 | workspace-snapshot path assertion: prompt contains `/private/var/tmp/...` (macOS `/var`→`/private/var` symlink), test expects `/var/tmp/...`; one also sees `Status: 1 untracked` vs `clean` | **macOS environment** |
| `test_auxiliary_explicit_cancellation.py::test_cancelled_codex_orphan_timeout_preserves_cached_shared_client` | 1 | `_SilentOwnerStream.closed.is_set()` is True; asserted False. Timing/race on orphan-timeout cancellation | Inherited, timing-sensitive |

**The two `delegate_task` failures deserve attention.** The OpenChia layer retired the delegation toolset (`toolsets.py:476 RETIRED_TOOLSETS = frozenset({"delegation"})`, introduced across `5baa5a3b7d` / `c2baf8b871`, patched again in `ea11e64fe5`). Both failing test files are pure inherited hermes tests — `git log` shows they were only ever touched by the mechanical `93b7fcd854 Rename CLI namespace to openchia_cli`, never adapted. `ea11e64fe5` added two narrow tests for the retirement (`tests/tools/test_retired_toolsets.py`, 3 tests) but left these two inherited assertions red. They look like unrepaired fallout from an OpenChia change, not inherited breakage. Worth confirming against an unmodified upstream base before closing.

### 2.3 `tests/openchia_cli/` — **125 failures, not 11. The project note is wrong by an order of magnitude.**

```
=== Summary: 1385 files, 12991 tests passed, 125 failed, 413 skipped (100% complete) in 966.0s (10 workers) ===
=== 36 files with test failures (125 tests failed) ===
=== 4 files where all tests passed but pytest exited non-zero ===
=== 12 files where no tests ran (collection/import error, timeout before collection) ===
```

A first full run of the same suite minutes earlier reported **130 failures across 37 files** — see §6.3 on flakiness.

**None of these 125 failures are OpenChia-layer tests.** `tests/openchia_cli/` is the inherited `tests/hermes_cli/` directory renamed by `93b7fcd854`; its 1,385 files test the hermes CLI, updater, installer, plugin system and gateway. The OpenChia CLI modules have exactly one test file between them (§3).

Dominant failure classes, by evidence from the run log:

| Class | Evidence | Verdict |
|---|---|---|
| Test-harness home-I/O guard tripping | 250 occurrences of `TEST BUG: file I/O against the REAL hermes home: /Users/me/.hermes/installs/.../openchia_cli/main.py` (`tests/home_io_guard.py:118`) | **Environment.** This workstation has a real `~/.hermes` install; updater/venv tests probe it. Drives the large clusters: `test_update_target_identity.py` (31), `test_update_products.py` (12), `test_update_autostash.py` (8), `test_update_parked_branch_guard.py` (7), `test_update_fleet_restart_pending.py` (7), `test_web_server_profile_unification.py` (7), `test_update_completion_process.py` (6), `test_web_memory_provider_setup_install.py` (6) |
| Live-system-guard harness bug | 29 × `TypeError: expected str, bytes or os.PathLike object, not NoneType` at `tokens = [os.fsdecode(t) for t in cmd]` — the guard's own argv classifier, not product code | **Test infrastructure bug** |
| Per-file timeout | `test_gateway_service.py` hit the 300s file timeout at 26% (111 tests, 300.2s) — slowest file in the suite | **Environment / timeout budget** |
| Collection / import errors | 12 files ran zero tests (`test_venv_sync_currency.py` → 2 errors, plus 11 plugin/doctor/gateway files) | Mixed |
| Genuine assertion failures | remainder of the 207 `AssertionError`s | Inherited drift |

**Conclusion for §2.3:** the "20 known pre-existing failures (agent x9, openchia_cli x11)" figure in the project notes is accurate for `tests/agent` and badly stale for `tests/openchia_cli`. The real local number is 125–130, overwhelmingly environment-dependent inherited tests. This matters because **the suite does not currently give a clean signal** — a real OpenChia regression landing in `tests/openchia_cli` would be invisible in the noise.

---

## 3. Coverage map, component by component

"Dedicated" = a test file whose purpose is that component. "Incidental" = the component is imported only to construct a value for a test of something else.

| Component | LOC | `raise` guards | Dedicated test files | Tests | Verdict |
|---|---:|---:|---|---:|---|
| `agent/duet_service.py` | 1,297 | 67 | 0 | incidental (1 file) | **Thinly tested** |
| `agent/duet_store.py` | 1,120 | 41 | 0 | incidental (1 file) | **Thinly tested** |
| `agent/duet_contracts.py` | 639 | 37 | 0 | incidental (2 files) | **Thinly tested** |
| `agent/openchia_host.py` | 1,883 | 55 | 0 | **0** | **UNTESTED** |
| `agent/episode_contract_models.py` | 988 | 74 | 0 | **0** | **UNTESTED** |
| `agent/episode_blueprints.py` | 595 | 12 | 0 | ~5 via egress test | **Thinly tested** |
| `agent/episode_contracts.py` | 6 (re-export shim) | — | — | imported by 7 files | n/a |
| `agent/openchia_agents.py` | 192 | — | 0 | **0** | **UNTESTED** (2 tests deleted) |
| `tools/duet_tool.py` | 214 | — | 0 | **0** | **UNTESTED** (8 tests deleted) |
| `episode_builder/` | 8,696 | 447 | 0 | 2 incidental symbol imports | **UNTESTED** |
| &nbsp;&nbsp;`planner.py` | 1,485 | | | 1 call (`materializer_function_catalog`) | untested |
| &nbsp;&nbsp;`_contract_chain.py` | 1,181 | | | 1 symbol (`ApprovedBuildRequest`) | untested |
| &nbsp;&nbsp;`service.py` / `inspection.py` / `store.py` / `admission.py` / `emitter.py` | 4,639 | | | **0** | untested |
| `episode_runtime/` | 11,093 | 699 | 10 | **166** | **Partially tested** |
| &nbsp;&nbsp;`http_broker.py` (638) / `http_contracts.py` (351) | 989 | | 2 | ~107 | **tested, well** |
| &nbsp;&nbsp;`container_executor.py` (776) | 776 | | 1 | 17 | **tested** |
| &nbsp;&nbsp;`protocol.py` (734) | 734 | | 1 (shared) | partial | thinly tested |
| &nbsp;&nbsp;`contracts.py` (1,751) / `identity.py` (730) / `seccomp.py` (328) | 2,809 | | shared | partial | thinly tested |
| &nbsp;&nbsp;`executor.py` (1,507) | 1,507 | | 1 | 1 (happy-path loop) | **thinly tested** |
| &nbsp;&nbsp;`linker.py` (1,090) | 1,090 | | 0 | 1 static lint | **UNTESTED** |
| &nbsp;&nbsp;`store.py` (810) | 810 | | 0 | **0** | **UNTESTED** |
| &nbsp;&nbsp;`bootstrap.py` (562) / `audit_contracts.py` (535) / `worker.py` (466) / `landlock.py` (269) / `broker.py` (193) | 2,025 | | 0 | **0** | **UNTESTED** |
| `iterative_episode_refiner/` | 3,850 | 173 | 0 | **0** | **UNTESTED** |
| `method_loop/` | 2,376 | 145 | 1 | 3 | **Thinly tested** |
| `episode_library/` | 2,653 | 25 | 0 | **0** | **UNTESTED** |
| `function_library/` | 631 | 63 | 0 | 1 incidental symbol | **UNTESTED** |
| `llm_call_library/` | 871 | 31 | 0 | **0** | **UNTESTED** |
| `handoff_library/` | 828 | 48 | 0 | 2 incidental symbols | **UNTESTED** |
| `numeric_control_library/` | 2,137 | 92 | 0 | **0** | **UNTESTED** |
| `http_call_library/` | 609 | 20 | 1 | 17 | **Tested** |
| `question_table_goal_library/` | 500 | 15 | 0 | **0** | **UNTESTED** |
| `openchia_cli/openchia_episode_editor.py` | 1,114 | 10 | 0 | **0** | **UNTESTED** (5 tests deleted) |
| `openchia_cli/openchia_episode_views.py` | 1,229 | 45 | 0 | **0** | **UNTESTED** |
| `openchia_cli/openchia_background.py` | 813 | — | 0 | **0** | **UNTESTED** |
| `openchia_cli/openchia_commands.py` | 377 | — | 0 | **0** | **UNTESTED** |
| `openchia_cli/duet_cli.py` | 700 | — | 1 | 2 | **Thinly tested** |
| `openchia_cli/openchia_main.py` | 77 | — | 0 | 1 string assertion in `test_packaging_metadata.py` | **UNTESTED** |

**Verification method.** Per-component importer map produced with:

```
grep -rlE "(^|[^a-zA-Z_.])(from|import) +<package>[ .]" tests/ --include='*.py'
```

Results (exhaustive, no test file outside this list touches the OpenChia layer):

```
iterative_episode_refiner        (none)
episode_library                  (none)
llm_call_library                 (none)
numeric_control_library          (none)
question_table_goal_library      (none)
agent.openchia_host              (none)
agent.episode_contract_models    (none)
openchia_cli.openchia_episode_editor  (none)
openchia_cli.openchia_episode_views   (none)
episode_builder                  tests/agent/test_egress_allowlist_contract.py
                                 tests/episode_runtime/test_http_call_library.py
agent.duet_service               tests/agent/test_egress_allowlist_contract.py
agent.duet_store                 tests/agent/test_egress_allowlist_contract.py
agent.episode_blueprints         tests/agent/test_egress_allowlist_contract.py
function_library                 tests/episode_runtime/test_http_call_library.py
handoff_library                  tests/episode_runtime/test_egress_contracts.py
                                 tests/episode_runtime/test_executor_http_loop.py
method_loop                      tests/method_loop/test_episode_tree_recursion.py
                                 tests/episode_runtime/test_http_protocol.py
```

Note how narrow the "incidental" column is. `episode_builder/` is 8,696 lines and the only two things any test touches are the dataclass `ApprovedBuildRequest` and one call to `materializer_function_catalog()`. `function_library/` is imported solely for the `LibraryFunction` type; `handoff_library/` solely for `DuetLaunchRequest`. None of these constitute coverage of the component's responsibilities.

---

## 4. The deleted tests: coverage was **lost, not restored**

The project note is correct and understates the scale. **Two** commits deleted OpenChia tests, not one, and neither added a single replacement test file (`git show --diff-filter=A --name-only <sha> -- tests/` returns empty for both).

### `5baa5a3b7d` "Build the Duet-owned Episode foundation" — 15 files, 95 tests, 4,137 lines

| Deleted file | Tests | Lines | Target still exists? |
|---|---:|---:|---|
| `tests/agent/test_duet_protocol.py` | 15 | 660 | yes — `duet_service.py` grew to 1,297 |
| `tests/agent/test_generic_creator_runtime.py` | 15 | 415 | yes (renamed surface) |
| `tests/agent/test_openchia_host.py` | 12 | 521 | yes — `openchia_host.py` grew to 1,883 |
| `tests/agent/test_generic_creator_models.py` | 8 | 108 | yes |
| `tests/agent/test_generic_creator_store.py` | 8 | 154 | yes — `duet_store.py` |
| `tests/tools/test_duet_tools.py` | 8 | 291 | yes — `tools/duet_tool.py` (214 lines) |
| `tests/agent/test_creator_episode.py` | 6 | 676 | yes |
| `tests/agent/test_episode_contracts.py` | 6 | 436 | yes |
| `tests/openchia_cli/test_openchia_episode_editor.py` | 5 | 215 | yes — editor grew to 1,114 |
| `tests/agent/test_episode_blueprints.py` | 3 | 100 | yes — 595 lines |
| `tests/agent/test_generic_creator_examples.py` | 3 | 43 | yes |
| `tests/agent/test_task_episode.py` | 3 | 115 | yes |
| `tests/agent/test_workflow_runtime.py` | 2 | 236 | yes |
| `tests/agent/test_evidence_gate_progress_adapter.py` | 1 | 31 | yes |
| `tests/agent/generic_creator_fixtures.py` | (fixtures) | 136 | — |

### `c2baf8b871` "Build the OpenChia workflow materialization MVP" — 3 files, 26 tests, 661 lines

| Deleted file | Tests | Lines | Target still exists? |
|---|---:|---:|---|
| `tests/openchia_cli/test_openchia_cli.py` | 13 | 345 | yes — `duet_cli.py` (700 lines) |
| `tests/agent/test_openchia_execution_boundary.py` | 11 | 187 | **no** — `agent/openchia_execution_boundary.py` was removed in the same commit |
| `tests/agent/test_openchia_agents.py` | 2 | 129 | yes — `openchia_agents.py` (192 lines) |

### Net

- **121 test functions / ~4,800 lines deleted.**
- **One** deletion is legitimate: `test_openchia_execution_boundary.py` went with its module.
- The other **110 tests covered code that still exists and in most cases grew substantially** in the very same commit. `openchia_host.py` went from a small module to 1,883 lines while its 12 tests were deleted. `openchia_episode_editor.py` was rewritten (+1,579/−…) while its 5 tests were deleted.
- **Zero** replacement tests were added by either commit.
- Nothing has restored them since. All 18 paths are confirmed `ABSENT` at HEAD.

The only tests added anywhere in the OpenChia layer after these deletions are the HTTP-broker/egress suite (PR #11, `69aaa5ad5b`), the container executor (`4b5f0e1eee`), the interpreter-path fix (`8ada84de7e`), and three small regression tests (`9d3e682753`, `de74019c78`, `ea11e64fe5`). Those are genuine new work on new features — they do not backfill any of the deleted coverage.

---

## 5. Critical untested paths — safety claims with no negative test

Method: for each safety claim in `OPENCHIA_ARCHITECTURE.md`, locate the enforcing code, then ask **"is there a test that fails if I delete the guard?"**

| # | Safety claim (source) | Enforcing code | Negative test exists? | Severity |
|---|---|---|---|---|
| 1 | Generated Episode modules may not call `eval`/`exec`/`__import__`/`os.system`/`open`/`rmtree`/… | `episode_builder/admission.py` (913 lines, ~35 rejection paths) | **NO — none at all** | **CRITICAL** |
| 2 | "The worker verifies that closure before importing application code" (§Isolated Run) | `episode_runtime/linker.py:635-694` digest comparison | **NO** | **CRITICAL** |
| 3 | "Generated source and Run audit content enter the refinement context only as **untrusted** reference data. They cannot select tools, alter authority, approve a change, or address another baseline." (§Iterative refinement) | `iterative_episode_refiner/` (3,850 lines) | **NO — zero tests in the package** | **CRITICAL** |
| 4 | "A terminal acknowledgement is accepted only in the terminal protocol phase. Partial publication cannot become a successful Run receipt." | `episode_runtime/store.py:576` `RunStoreConflict("Run event chain is already terminal")` | **NO** — `store.py` has no test file | **HIGH** |
| 5 | Approval / CAS staleness: ~25 `"... is stale"` guards binding approvals, authority heads, plan predecessors, manifests, receipts | `episode_builder/_contract_chain.py` (×10), `_contract_base.py` (×5), `inspection.py` (×4), `store.py`, `agent/openchia_host.py` (×5) | **NO** for all of them | **HIGH** |
| 6 | Isolation policy actually applied to the Run | `episode_runtime/executor.py:925-946` (runtime-identity + receipt executor-id checks); `landlock.py`; `seccomp.py` | **PARTIAL** — see below | **MEDIUM** |
| 7 | "Raw task prose, source contents, and log text never become upward instructions" (§Task Episodes) | `numeric_control_library/credit_assignment.py`, `method_loop/` | **NO** — `numeric_control_library` untested | **HIGH** |
| 8 | "Raw model output never substitutes for a persisted artifact or human approval" (§Persistence ownership) | `agent/duet_store.py` atomic authority writes, `episode_builder/store.py` | **NO** | **HIGH** |
| 9 | HTTP egress allowlist admission | `episode_runtime/http_broker.py`, `http_contracts.py`, `agent/episode_contracts.py` | **YES — thoroughly** | ✅ |
| 10 | Container isolation facts (ro-mount, netns, no-new-privs, label, quota) | `episode_runtime/container_executor.py` `_inspect` | **PARTIAL (3 of 5)** | **MEDIUM** |

### 5.1 Finding T-1 (CRITICAL): the code-execution admission gate has zero tests

`episode_builder/admission.py` is the gate that AST-inspects **LLM-generated Episode module source** before it is staged into the sandbox. Its rejection vocabulary, extracted from the source, includes:

```
module_syntax_error            module_top_level_effect        module_exports_incomplete
module_exports_reassigned      module_import_forbidden        relative_import_forbidden
module_state_mutation_forbidden  direct_effect_forbidden      python_introspection_forbidden
implementation_module_forbidden  implementation_module_dynamic  concrete_episode_imported
reference_episode_imported     module_name_mismatch           module_literal_mismatch
module_literal_invalid         host_declaration_mismatch      host_declaration_invalid
builder_signature_invalid      generated_function_missing     goal_view_mutable
root_builder_on_child          child_result_correlation_missing  unplanned_module
module_without_plan            missing_module                 duplicate_module
unchanged_module_diverged      plan_mismatch
```

and the denied-name sets it screens for:

```
eval  exec  compile  __import__  __subclasses__  __globals__  __code__  __class__
__dict__  __loader__  __spec__  __builtins__  globals  locals  vars  breakpoint
input  open  system  popen  fork  spawn  urlopen  load  write_text  write_bytes
rmtree  rmdir  unlink  import_module
```

**Not one of these ~29 rejection codes has a test.** If `_inspect_source` were replaced with `return ()` tomorrow, the entire test suite would still pass green. This is the single highest-severity finding in this review: the gate that stops model-authored code from escaping the sandbox is completely unverified.

### 5.2 Finding T-2 (CRITICAL): closure verification has no mismatch test

`episode_runtime/linker.py:635-694` is the only thing standing between the staged closure and a tampered one:

```python
or digest_record(manifest.as_record()) != registration.manifest_hash
...
digest = Sha256Digest.of_bytes(source)
if (digest != manifest.module_hashes_by_local_id[node.local_id]
    or digest != report.module_source_hashes[node.local_id]):
```

The only test in the vicinity is `tests/episode_runtime/test_staged_closure_imports.py` (1 test), and it does something different: it statically lints `_SELECTED_LOCAL_SOURCES` to check that staged `episode_runtime/*` modules don't `from .x import` an unstaged sibling. Useful, but:
- it never calls `prepare_source_package`,
- it never feeds a mismatched digest,
- its regex `^from \.(\w+) import` misses `from . import x`, `import episode_runtime.x`, and multi-line/parenthesised imports.

**No test fails if the digest comparison is deleted.**

### 5.3 Finding T-3 (CRITICAL): the "audit content is untrusted" claim is entirely unverified

`iterative_episode_refiner/` is 3,850 lines with 173 `raise` guards and **zero tests**. The architecture doc makes the strongest trust claim in the system about exactly this subsystem (§Iterative refinement, lines 184-190): generated source and Run audit content "cannot select tools, alter authority, approve a change, or address another baseline."

There is no test that a crafted audit chunk or generated source string fails to do any of those four things. For a prompt-injection boundary, this is the test you most need and the one that does not exist.

### 5.4 Finding T-4 (HIGH): no tests for `episode_runtime/store.py`

810 lines, including the terminal-phase guard (`RunStoreConflict("Run event chain is already terminal")`) that backs the "partial publication cannot become a successful Run receipt" claim. `RunStore` is instantiated in two tests (`test_container_executor.py`, `test_executor_http_loop.py`) purely as happy-path plumbing. No test appends after terminal, replays a chunk, or publishes partially.

### 5.5 Finding T-5 (MEDIUM): isolation receipts are self-reported, and 2 of 5 breakage cases don't assert rejection

`episode_runtime/executor.py:925-946` validates the worker's READY frame: runtime identity must match, and both the landlock and seccomp receipts must name the same `executor_instance_id`. There is no negative test for either check (a worker naming another runtime, or a receipt naming another executor, or a missing receipt key).

Structurally, the receipts are **worker self-attestations** — the host trusts the worker's word that it entered its policies. `seccomp.py:204` does bind `policy_hash == seccomp_policy_hash(self.machine)` in `__post_init__`, but `machine` is itself worker-reported. `landlock.py` (269 lines) has no tests at all; `landlock` appears in exactly one test file and only as a value a **fake** worker constructs.

Separately, `test_inspection_rejects_a_container_that_breaks_the_policy` is a good parametrized negative test for 5 breakages — but for 2 of them it does not assert rejection:

```python
if breakage in ("network", "no-nnp"):
    # these produce facts whose isolation booleans are False; the attestation contract rejects them
    facts = asyncio.run(executor._inspect(identity, launcher, mounts))
    assert not (facts.network_namespace_isolated and facts.no_new_privs)
else:
    with pytest.raises(RunExecutionError):
        ...
```

For `network` and `no-nnp` the test asserts an **intermediate boolean**, and the comment asserts the rejection in prose. If the attestation contract stopped rejecting a non-isolated network namespace, this test would still pass. Those are the two most security-relevant breakages in the list.

### 5.6 What *is* properly protected

Credit where due. The egress/HTTP surface is the one area with real adversarial testing, and it is good:

- `test_http_broker.py` — 37 cases: path-prefix segment-boundary table (`/ragstack/api` must not match `/ragstack/apix`), unmatched host/method/node **denied without dialing** (asserts the transport was never called), per-rule-and-node budgets that count failures, oversize handling including base64 growth past the frame, and three separate credential-leak tests (`test_credential_reaches_only_the_outgoing_request`, `test_transport_error_reason_never_echoes_the_token`, `test_unusable_credentials_are_denied_without_revealing_contents`).
- `test_egress_allowlist_contract.py` — 50 cases: `test_default_service_admits_no_egress` (deny-by-default), `test_host_outside_the_ceiling_is_a_detailed_deficit`, `test_unknown_credential_is_a_detailed_deficit`, `test_spec_and_workflow_hashes_cover_the_allowlist` (the allowlist is inside the approved hash).
- `test_http_protocol.py` — 70 cases: `test_http_frames_are_sender_bound`, `test_admit_http_request_rejects_every_host_owned_header` (parametrized over the whole forbidden set), `test_admit_http_request_requires_exact_keys`.
- `test_egress_contracts.py` — `test_tampered_egress_policy_record_is_stale`. **This is the one CAS-staleness negative test in the entire OpenChia layer.**

This suite is the template. Every other safety claim should be tested the way this one is.

---

## 6. Test quality

### 6.1 Strengths

- **Low mocking, correctly placed.** Across the 13 OpenChia test files, mock/monkeypatch usage is concentrated in exactly the two places where real behaviour is unreachable in a unit test: the container daemon (`test_container_executor.py`, 23 hits) and the HTTP transport (2 hits). `test_egress_contracts.py`, `test_http_call_library.py`, `test_egress_allowlist_contract.py`, `test_method_loop/*` and `test_supplied_interpreter_identity.py` use **zero** mocks — they drive real contract objects.
- **Honest docstrings about what is faked.** `test_executor_http_loop.py` opens with: *"Only launch and inspection are stubbed; the frame loop, the broker, and the RunStore event chain are the production code. The host transport is a fake: no network."* That is exactly the disclosure a reviewer needs.
- **Real tables, not single happy paths.** The path-prefix boundary table, the forbidden-header parametrization over the whole set, and the 5-way container-breakage parametrization are good adversarial design.
- **Assertions on canonical form, not just values.** `_call()` in `test_http_broker.py` asserts `admit_http_response(response) == response` on every single call — the response is required to already be canonical. Cheap, and catches a whole class of drift.

### 6.2 Weaknesses

1. **Private-API coupling in `test_container_executor.py`.** Tests call `executor._inspect`, `executor._probe`, `executor._inspect_container`, `executor._identity_arguments()`, and one constructs the object with `ContainerRunExecutor.__new__(ContainerRunExecutor)` to bypass `__init__`. These will break on refactor without indicating a real regression. Partly unavoidable for sandbox internals, but `__new__`-bypass is a smell.
2. **Assertions on intermediate state instead of the protection** — §5.5, the `network` / `no-nnp` cases.
3. **Canned fixtures that encode the daemon's answer.** `_canned_inspect` / `_canned_probe` return hand-written docker-inspect JSON. If the real daemon's output shape drifts (a known hazard — the scratchpad already records "runc shares→weight mapping is version-dependent"), every test still passes. The one test that would catch it, `test_live_image_interpreter_identity_is_stable_and_pinned`, is skipped on macOS and on any machine without a Linux container daemon. On this reviewer's machine it did not run.
4. **One happy-path integration test doing a lot of load-bearing work.** `test_executor_http_loop.py` is a single test covering the full INITIALIZE→READY→START→HTTP_REQUEST→HTTP_RESPONSE→TERMINAL→TERMINAL_ACK sequence. It is a good test, but it is the *only* exercise of `executor.py` (1,507 lines) and the only exercise of the frame loop end to end. Every failure mode of that sequence — wrong frame order, terminal before start, ack outside the terminal phase, worker dying mid-frame, oversize frame — is untested.
5. **Deleted coverage not replaced with anything equivalent.** §4. The 12 deleted `test_openchia_host.py` tests and 15 deleted `test_duet_protocol.py` tests covered the Duet state machine and host coordination; the surviving incidental coverage from `test_egress_allowlist_contract.py` exercises one path through `DuetService`/`DuetStore` (workflow admission authority for egress) and nothing else — not state transitions, not `_require_state_transition`, not the optimistic-revision conflict path (`duet_store.py:43 "An immutable identity or optimistic revision conflicted"`).

### 6.3 Flakiness

Two full `tests/openchia_cli/` runs, same tree, same machine, ~15 minutes apart:

| Run | Failures | Files |
|---|---:|---:|
| 1 | 130 | 37 |
| 2 | 125 | 36 |

Deltas: `test_sessions_held_store_gate.py` 4 → 1, `test_sessions_set_journal_mode.py` 2 → 0. Both SQLite session-store tests — classic lock/journal-mode timing flakes under `-j 10`. `tests/agent/` by contrast was byte-stable at 9 failures across both runs.

The OpenChia-layer suites (219 tests) were stable and fast (9.8s wall) across every run.

### 6.4 Environment dependence

- **Skipped on macOS:** `test_live_image_interpreter_identity_is_stable_and_pinned` (needs a reachable Linux container daemon reporting `OSType=linux`).
- **Not exercised on macOS by design:** the systemd Run executor path. `executor_selection.py:21` picks `systemd` only when `sys.platform.startswith("linux") and /usr/bin/systemd-run` exists; here it resolves to `container`. `episode_runtime/executor.py` (1,507 lines, the systemd executor) is covered by exactly one shape assertion, `test_systemd_executor_still_satisfies_the_protocol`, which checks protocol conformance and never launches anything. **The systemd executor is effectively untested on any platform in this suite.**
- `landlock` and `seccomp` are Linux kernel features; the macOS run exercises only their hashing/normalization logic (`test_seccomp_machine.py`, 6 cases), never enforcement.
- The `tests/openchia_cli/` noise (§2.3) is driven by this machine having a real `~/.hermes` install.

---

## 7. Gaps and priorities

Prioritized by (severity of the unprotected claim) × (likelihood the guard silently breaks).

### P0 — safety claims with no negative test

1. **`tests/episode_builder/test_admission.py`** — one negative test per rejection code in `admission.py`. At minimum the sandbox-escape set: a module that calls `eval`, one that calls `exec`, one that calls `__import__`, one reaching `__subclasses__`/`__globals__`, one calling `os.system`/`popen`/`fork`/`spawn`, one calling `open`/`write_text`/`rmtree`/`unlink`, one with a top-level effect, one with a forbidden/relative import, one mutating module state. Each must assert the specific deficit code and field path, so the test pins *which* guard fired. **Without this, the sandbox gate is unverified.**
2. **`tests/episode_runtime/test_linker_closure.py`** — `prepare_source_package` must reject: a module whose source digest ≠ its manifest hash; a manifest whose `digest_record` ≠ `registration.manifest_hash`; a mismatched authority-head or workflow-approval digest; a module present on disk but absent from the manifest.
3. **`tests/iterative_episode_refiner/test_untrusted_context.py`** — the four prohibitions from the architecture doc, each as a test: audit/generated-source content cannot (a) select a tool, (b) alter authority, (c) approve a change, (d) address another baseline. Feed adversarial strings (instruction-shaped text, a forged approval id, a foreign baseline hash) and assert each is inert.
4. **`tests/episode_runtime/test_run_store.py`** — append-after-terminal raises `RunStoreConflict`; partial publication cannot produce a successful receipt; chunk replay/ordering; audit manifest integrity.

### P1 — restore the deleted coverage for code that still exists

5. **`tests/agent/test_openchia_host.py`** (1,883 lines, 55 guards, 0 tests). Recover the deleted file from `git show 5baa5a3b7d^:tests/agent/test_openchia_host.py` as a starting point and retarget it at the current surface. Same for `test_duet_protocol.py` (15 tests) → Duet state machine and `_require_state_transition`.
6. **CAS / staleness negative tests** across `_contract_chain.py`, `_contract_base.py`, `inspection.py`, `openchia_host.py`. `test_tampered_egress_policy_record_is_stale` is the pattern — generalize it: for each `"... is stale"` guard, mutate one field of the record and assert the guard fires.
7. **`tests/agent/test_duet_store.py`** — optimistic-revision conflict (`duet_store.py:43`), the atomic authority write, and every illegal entry in `_ALLOWED_STATE_TRANSITIONS`.
8. **`tests/openchia_cli/test_openchia_episode_editor.py`** and `test_openchia_episode_views.py` — 2,343 lines of human-facing approval/review UI with zero tests. The editor is where a human approves a build; a rendering bug here is a safety bug.

### P2 — close the structural holes

9. **Protocol phase-ordering negative tests** — terminal before start, ack outside the terminal phase, out-of-order frames, oversize frame, worker death mid-frame. Extend `test_executor_http_loop.py`'s harness, which already has the machinery.
10. **Isolation receipt negative tests** — worker READY naming another runtime; receipt naming another executor; missing receipt keys. Three cheap tests against `executor.py:925-946`.
11. **Fix `test_inspection_rejects_a_container_that_breaks_the_policy`** so the `network` and `no-nnp` branches assert `pytest.raises(RunExecutionError)` like the other three, rather than asserting an intermediate boolean.
12. **`numeric_control_library/` tests** (2,137 lines, 0 tests) — credit assignment, rarefaction, continuation, and specifically the "raw prose never becomes an upward instruction" boundary.
13. **`llm_call_library/`, `episode_library/`, `question_table_goal_library/`, `function_library/`, `handoff_library/`** — 5,483 lines, zero dedicated tests. At minimum contract round-trip + argument-admission tests, mirroring `test_http_call_library.py`, which is the right shape and already exists as a model.
14. **`tools/duet_tool.py`** and **`agent/openchia_agents.py`** — restore the 10 deleted tests.

### P3 — restore signal

15. **Triage `tests/openchia_cli/`.** 125–130 failures means the suite cannot detect a regression. Either fix the home-I/O-guard violations (250 hits — they are real test bugs: tests probing `~/.hermes` instead of an isolated `HERMES_HOME`), or quarantine the environment-dependent updater/installer files behind a marker so the remainder gives a clean signal.
16. **Fix the live-system-guard harness bug** — `tokens = [os.fsdecode(t) for t in cmd]` raises `TypeError` on a `None` element in argv (29 occurrences). The guard already handles `cmd is None`; it needs to handle `None` *within* the sequence.
17. **De-flake the SQLite session-store tests** (`test_sessions_held_store_gate.py`, `test_sessions_set_journal_mode.py`) — ~5 tests varying run to run under `-j 10`.
18. **Raise or split the 300s file timeout for `test_gateway_service.py`** (111 tests, times out at 26%).
19. **Resolve the two `delegate_task` failures** — confirm against an unmodified upstream base whether they are OpenChia-caused fallout from the delegation-toolset retirement (the evidence says yes), and either fix the routing or update the inherited assertions.
20. **Get the systemd Run executor under test on Linux CI.** 1,507 lines currently covered by one shape assertion.

---

## 8. Appendix: commands used

```bash
# Coverage map (exhaustive per-component importer search)
grep -rlE "(^|[^a-zA-Z_.])(from|import) +<package>[ .]" tests/ --include='*.py'

# Deleted-test accounting
git log --diff-filter=D --name-only --oneline --since="2026-09-01" -- 'tests/*'
git show <sha>^:<path> | grep -cE '^\s*(async )?def test_'
git show --diff-filter=A --name-only <sha> -- 'tests/'   # empty for both deleting commits

# Test runs
./scripts/run_tests.sh tests/episode_runtime/ tests/method_loop/ \
                       tests/agent/test_egress_allowlist_contract.py
./scripts/run_tests.sh tests/agent/
./scripts/run_tests.sh tests/openchia_cli/
```

<!-- no-tmp: ok — historical log paths quoted from a review session, not guidance -->
Raw logs: `/tmp/agent_full.log`, `/tmp/cli_full.log`.
No source file, test file, or configuration was modified in the course of this review.
