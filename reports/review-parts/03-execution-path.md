# OpenChia review — Part 3: the Episode execution path

Scope: `episode_runtime/` (18 files, ~11k LOC), `method_loop/` (5 files, ~2.4k LOC),
`http_call_library/`, and the Run-coordination half of `agent/openchia_host.py`.
Read against `OPENCHIA_ARCHITECTURE.md` ("Isolated Run"), `README.md` ("Run execution
backends", "External requests from a Run"), and
`docs/adr/0002-run-http-requests-are-host-brokered.md`.

All claims below are backed by file:line evidence. Two findings are supported by
executed reproductions (noted inline). No source file was modified.

---

## 1. What the execution path actually does

### 1.1 Registration

`/run` is gated by `OpenChiaHost._runnable_build_context()`
(`agent/openchia_host.py:1225-1286`). It requires a `SEALED` Duet state, a completed
materialized baseline, re-reads the full build chain from the Build store with
`verify_source_package=True`, re-resolves the *current* build authorization
(`agent/duet_service.py` via `resolve_current_build_authorization`), and requires the
build's frozen approval, authority approval, workflow approval and admission authority
to be **identical objects** to what authority says today
(`agent/openchia_host.py:1267-1283`). A stale approval therefore cannot be run.

`RunRegistration.from_admitted_build` (`episode_runtime/contracts.py:940-1036`) binds
every upstream identity and hash (authority, approvals, workflow, build request /
attempt / receipt / manifest), the Duet launch request, the runtime identity, the
runtime policy, and — new in PR #11 — `egress_policy`, derived from the frozen
Architecture as `{episode.local_id: episode.contract.egress_allowlist}`
(`contracts.py:1031-1035`). The registration's `run_id` and `registration_hash` are
derived from that whole record, so the Run id *is* the content identity of its
authority. It also refuses anything but `typed_status` deliverables
(`contracts.py:994-1004`).

The registration is published first, exactly once, by content-exclusive link
(`episode_runtime/store.py:257-264`, `:194-237`).

### 1.2 Staging the content-addressed closure

`inspect_runtime_identity` → `materialize_runtime_source_package`
(`episode_runtime/identity.py:679-694`, `:430-532`) copies a fixed set of local sources
into `<run store>/runtime_sources/<manifest_id>/`:

- a hand-listed set of 20 modules, `_SELECTED_LOCAL_SOURCES`
  (`identity.py:48-69`), plus
- every `.py` under the seven `ADMITTED_LOCAL_ROOTS` (`identity.py:32-40`:
  `function_library`, `handoff_library`, `http_call_library`, `llm_call_library`,
  `method_loop`, `numeric_control_library`, `question_table_goal_library`), plus
- a canonical `runtime_source_manifest.json` carrying every file hash, the
  worker entrypoint, the synthetic package list, and the *interpreter identity*
  (every stdlib file hash, the executable hash, shared libraries).

Staging re-hashes each file as it copies and fails if it changed mid-copy
(`identity.py:478-485`), makes the tree read-only (`identity.py:393-407`), publishes by
`os.rename` + directory `fsync` (`identity.py:510-523`), and re-verifies afterwards
(`identity.py:526-531`). The directory name *is* the manifest id
(`identity.py:606`). `episode_runtime/http_broker.py` is deliberately absent from the
staged set — it is the only module that reads credential files and dials the network
(`http_broker.py:3-11`).

### 1.3 Launch

Both backends launch the same argv shape (`executor.py:1295-1342`,
`container_executor.py:451-512`):

```
<!-- no-tmp: ok — quoted worker argv; the path is inside the sandbox -->
<python> -I -S -B -X pycache_prefix=/tmp/openchia-disabled-pycache -c <bootstrap source>
         --bootstrap-package <ro mount> --bootstrap-manifest-id … --bootstrap-manifest-hash …
         --run-id … --registration-hash … --manifest-id … --max-frame-bytes …
         --source-package <ro mount> --runtime-source-package <ro mount>
```

The bootstrap *source text* is read from the already-verified staged package and passed
as a literal `-c` argument (`identity.py:652-676`) — the worker never imports its own
bootstrap from a path. systemd additionally prefixes `/usr/bin/env -i`
(`executor.py:1312-1313`), so the worker environment is empty; the container inherits
only the image's `ENV` (no `--env` is passed).

### 1.4 Bootstrap closure verification (pre-import)

`episode_runtime/bootstrap.py` is stdlib-only and does, in order:

1. `_load_manifest` — reads `runtime_source_manifest.json`, requires canonical JSON,
   recomputes `manifest_id`/`content_hash`, compares both to the argv values, and
   requires the directory name to equal the manifest id (`bootstrap.py:239-298`).
2. `_verify_package` — walks the package rejecting symlinks and `__pycache__`, requires
   the file set to equal the manifest exactly, and re-hashes every file
   (`bootstrap.py:301-312`, `:110-157`).
3. `_verify_interpreter` — compares implementation/version/cache tag, hashes
   `/proc/self/exe`, enumerates and hashes **every** stdlib file (symlinks hashed as
   `stdlib-symlink\0<target>\0<payload>`), and hashes the interpreter shared libraries
   (`bootstrap.py:329-367`).
4. Replaces `sys.path` with exactly `[package, stdlib, stdlib/lib-dynload]` and
   `sys.meta_path` with `[BuiltinImporter, FrozenImporter, _ClosedImportFinder]`
   (`bootstrap.py:542-553`).
5. Installs synthetic namespace packages for `agent`, `episode_builder`,
   `episode_library`, `episode_runtime`, `iterative_episode_refiner` with
   `__file__ = None` (`bootstrap.py:459-475`) — which is why the host-only
   `episode_runtime/__init__.py` (it imports `http_broker`) is never executed.
6. `from episode_runtime.worker import main`.

`_ClosedImportFinder.find_spec` resolves through `PathFinder`, then rejects any origin
not in the staged-local or stdlib hash maps (`bootstrap.py:438-444`), and rewraps every
`.py` with `_SourceOnlyLoader`, which **re-hashes the file at import time** and refuses
bytecode writes (`bootstrap.py:370-400`).

### 1.5 Policy entry, then activation

`episode_runtime/worker.py:331-356` is the critical ordering:

```
initialize frame → RunRegistration.from_record
verify_runtime_identity(...)                     # re-verify the whole staged closure
prepare_source_package(registration, …)          # read + AST-parse + compile + preload imports
apply_seccomp_policy(...)                        # worker.py:348
apply_landlock_abi7(...)                         # worker.py:352
prepared.activate()                              # worker.py:356 — first execution of generated code
```

`prepare_source_package` (`linker.py:582-713`) independently re-validates the *build*
package: it loads the five metadata records, cross-validates
plan↔request↔report↔manifest, requires `report.admitted`, and requires **every**
registration hash to match (`linker.py:631-648`). Each generated module's bytes are
hashed against both the build manifest and the static-admission report
(`linker.py:659-667`), parsed, compiled with `dont_inherit=True`, checked for
cross-imports between generated modules (`linker.py:682-683`), and its declared imports
are pre-loaded while the filesystem is still reachable (`linker.py:685-689`). The final
file-set equality check rejects any unexpected file (`linker.py:699-704`).

`activate()` (`linker.py:381-432`) then `exec`s each module with a builtins namespace
whose `__import__` only returns already-resident, statically declared modules
(`linker.py:285-315`), and `_validate_activated_module` (`linker.py:443-579`) re-checks
every export against the plan: required symbols, exact runtime ABI signatures, BINDING
vs the frozen contract, the Architecture-owned rarefaction/continuation function
identities *and arguments* (`linker.py:528-546`), PROMPTS / capability names / result
channels as exact literals, payload contracts, and the host declaration.

`link()` (`linker.py:822-1078`) builds the `method_loop` tree: one `Grain` per node,
child edges from the plan, a `_GoalViewRegistry` that forbids two views for one path,
and `_InstrumentedEpisode`, which sets the episode-id and episode-path ContextVars and
emits `EPISODE_STARTED` / `EPISODE_COMPLETED` / `UNIT_COMPLETED` events
(`linker.py:739-784`, `:1019-1035`).

### 1.6 The typed broker interface

The worker installs two ContextVar-scoped transports *around* the run task
(`worker.py:384-387`). `llm_call_library` falls back to a host transport when no scope
is set; `http_call_library` has **no fallback** and raises `HttpTransportUnavailable`
(`http_call_library/transport.py:139-150`). Both cross the pipe as typed frames.

`model_request_id` / `http_request_id` are content ids over
`(run_id, registration_hash, episode_id, per-kind ordinal, request_hash)`
(`worker.py:177-188`, `:214-223`) with separate counters, exactly as ADR 0002 specifies.

### 1.7 Terminal results and chunked audit

`RunStore.finalize_run` (`store.py:590-641`) appends the terminal event under the claim
lock, then `_publish_terminal_artifacts_locked` (`store.py:485-551`) publishes, in
order: every audit chunk → the audit-log manifest → the evidence record. Evidence is
last, so a crash mid-publication leaves **no** evidence file and
`read_evidence` raises `RunStoreNotFound`; `complete_terminal_publication`
(`store.py:643-654`) can idempotently finish. `read_evidence` re-walks the chunk chain
backwards from the head, re-reads every chunk, and requires
`audit_log.validate_chunks(chunks) == events` against the append-only event files
(`store.py:725-756`). **The ADR/architecture claim that "partial publication cannot
become a successful Run receipt" is implemented correctly.**

---

## 2. Verified-true claims

Recorded so the findings list is read in proportion.

| Claim | Verdict | Evidence |
|---|---|---|
| Landlock ABI 7, empty ruleset, no allow rules, `PR_SET_NO_NEW_PRIVS` first | True | `landlock.py:186-256`; FS bits 0-15, net bits 0-1, scoped bits 0-1 (`:25-30`) |
| systemd `PrivateNetwork=yes`, `ProtectSystem=strict`, `PrivatePIDs`, `ProcSubset=pid`, `NoNewPrivileges`, `RestrictAddressFamilies=AF_UNIX` | True and *verified live* via `systemctl show` | `executor.py:357-390`, `:409-429`, `:675-692` |
| container `--network none --read-only --cap-drop ALL --security-opt no-new-privileges` | True, and each is re-read back from `docker inspect` + an in-container probe | `container_executor.py:190-199`, `:619-662` |
| read-only mounts are verified, not just requested | True — systemd parses `/proc/<pid>/mountinfo` and compares `st_dev`/`st_ino` of source vs the projected target (`executor.py:528-570`); the container checks both the probe's mount table and `docker inspect` `RW:false` (`container_executor.py:604-618`) |
| worker policies installed *before* generated code runs | True | `worker.py:348-356` |
| source-only import loader re-hashes at import time | True | `bootstrap.py:383-397` |
| no credentials in the generated package | True — `http_broker.py` is not in `_SELECTED_LOCAL_SOURCES` (`identity.py:48-69`); `request_hash` is taken before the header is added (`executor.py:800` vs `http_broker.py:526`) |
| `HTTP_REQUESTED` / `HTTP_RESPONDED` / `MODEL_*` are not worker-emittable | True | `executor.py:1009-1065` restricts worker events to three kinds; `protocol.py:443-444` rejects terminal kinds |
| terminal ack only in the terminal phase | True on both sides | worker `protocol.py`/`worker.py:264-268`; host sends `TERMINAL_ACK` only on the `WorkerFrameType.TERMINAL` branch (`executor.py:1079-1095`) |
| episode_path must hash to episode_id | True, enforced in the decoder itself | `protocol.py:411-415`, `:147-161` |
| redirects not followed | True | `http_broker.py:242-246` (`follow_redirects=False`), `:579-580` returns 3xx with headers and no body |
| `method_loop` nano-graphrag attribution | Present | `method_loop/LICENSE`, `THIRD_PARTY_NOTICES.md:7-12` |

---

## 3. Findings, severity-ranked

### H1 — The host rejects **every** `model_request`: frozen frame bodies are tuples, `admit_model_request` requires a `list`

**Severity: High (functional break of the core broker path).**

**Evidence**

- `protocol.py:92-114` `_freeze_json` converts every JSON array to a **tuple**.
- `protocol.py:207` freezes the whole decoded frame; `protocol.py:395`
  (`MODEL_REQUEST` branch) re-freezes `record["request"]` and stores the frozen mapping
  on `ProtocolFrame.body`.
- `broker.py:77`: `if not isinstance(messages, list) or len(messages) != 2: raise
  ModelBrokerError("model request needs one system and one user message")`.
- `executor.py:1017`: `request = admit_model_request(frame.body["request"])` — the
  frozen body, unthawed.
- `executor.py:1032`: `await model_broker(frame.body["request"])` →
  `ScopedModelBroker.__call__` → `admit_model_request` again (`broker.py:176`).

**Reproduction (executed against this checkout, through the real encoder/decoder):**

```
decoded messages type: <class 'tuple'>
HOST ADMISSION FAILS: model request needs one system and one user message
```

**Why it matters.** `ModelBrokerError` is caught by `executor.py:1124`
(`except BaseException`), which cancels the worker and finalizes the Run `FAILED`. Any
Episode that makes a single model call therefore cannot produce a successful Run — the
primary purpose of the broker. This is the *same* frozen/typed-record defect the project
already hit for `INITIALIZE`/`START`; those two were patched by thawing
(`protocol.py:264-266`, `:288-290`) but `model_request` was not.

It survives because there is **no test for the model leg of the host loop**:
`tests/episode_runtime/` contains `test_executor_http_loop.py` (a full frame round trip
for HTTP) but nothing equivalent for models; the only reference to the model broker is
`tests/episode_runtime/test_executor_http_loop.py:272`, an `_unused_model_transport`
that asserts it is never called.

**Suggested fix.** Thaw at the decoder, consistently with `INITIALIZE`/`START`:
in `protocol.py:387-402` return `admit_model_request(_thaw_json(record["request"]))`'s
canonical record (mirroring the `http_request` branch at `:403-427`, which already
normalizes through `admit_http_request`). Then `executor.py:1017/1032` should admit
once and pass the typed `ModelTransportRequest` to the broker rather than re-admitting
the raw body. Add a `test_executor_model_loop.py` mirroring the HTTP one.

**Related latent instances of the same class** (currently guarded only by convention, each
one thaw away from the same failure):

- `episode_runtime/contracts.py:66-69` `_array` is list-only and is reached from
  `RunRegistration.from_record` → `_egress_policy_from_record` (`contracts.py:1437`)
  and `InspectedExecutorAttestation.from_record` (`contracts.py:1441-1446`).
- `agent/episode_contract_models.py` `EpisodeEgressRule.from_record` requires
  `methods` to be a `list`.
- The only thing preventing these from firing is the comment at `protocol.py:264`
  ("Frames arrive frozen (arrays as tuples); the contract parsers want plain JSON")
  plus the fact that `_validate_body` re-emits `registration.as_record()` /
  `attestation.as_record()` (plain dicts) at `protocol.py:276-299`.
  Recommend making `_array`/`_record` accept any non-`str` sequence, or thawing once at
  `_parse_canonical`, so correctness does not depend on each call site remembering.

---

### H2 — seccomp is an **allow-by-default denylist**, and the aarch64 table is materially weaker than x86_64

**Severity: High (claimed vs implemented isolation gap).**

**Evidence**

- `seccomp.py:170`: `"default_action": "allow"`; `seccomp.py:297`:
  `_SockFilter(_BPF_RET_K, 0, 0, _SECCOMP_RET_ALLOW)` as the trailing rule.
- Tables: `seccomp.py:40-86` (x86_64, 43 syscalls), `:87-114` (aarch64, 25 syscalls),
  aliased for `arm64` at `:115`.

**Gap A — architecture asymmetry.** The aarch64 table omits syscalls the x86_64 table
denies: `mknodat` (33), `mkdirat` (34), `truncate` (45), `ftruncate` (46), `fchmod`
(52), `fchown` (55). It also has no analogue of `creat`, `fork`/`vfork` (arm64 has
none), `rename`/`mkdir`/`rmdir`/`link`/`unlink`/`symlink`/`chmod`/`chown`/`lchown`
(arm64 genuinely lacks these — fine), but the six listed above **do** exist on arm64 and
are simply missing. aarch64 is the *default macOS / Apple-Silicon container path* per
`README.md` ("Run execution backends"), i.e. the weaker policy is the one most
developers run. The policy hash differs per machine
(`seccomp.py:164-182`) so the asymmetry is recorded, but the README presents the two
backends as "the same worker" with "the same protocol and evidence chain".

**Gap B — omissions on both architectures.** Neither table denies
`io_uring_setup` (425) / `io_uring_enter` / `io_uring_register`, `memfd_create` (319),
`open_by_handle_at` (304) / `name_to_handle_at` (303), the new mount API
(`open_tree` 428, `move_mount` 429, `fsopen` 430, `fsconfig` 431, `fsmount` 432,
`fspick` 433), `unshare`, `setns`, `process_vm_readv`/`process_vm_writev`, or
`pidfd_open`/`pidfd_getfd`. `io_uring` in particular is the classic denylist bypass: an
io_uring ring can submit `IORING_OP_OPENAT`, `IORING_OP_SOCKET` and `IORING_OP_CONNECT`
without ever issuing the denied syscall numbers. Landlock and `--network none` still
cover most of the resulting damage, but the *seccomp* boundary as documented does not.

**Gap C — x32 ABI.** On x86_64 the filter checks `arch == AUDIT_ARCH_X86_64`
(`seccomp.py:280`) and then compares the raw syscall number. x32 processes report the
same audit arch with `__X32_SYSCALL_BIT` (0x40000000) set, so `socket` arrives as
`0x40000029` and matches nothing. The standard mitigation (reject any
`nr >= 0x40000000`) is absent. Low exploitability on modern distros (x32 is usually
compiled out) but it is a known hole in a hand-written BPF filter.

**Why it matters.** `OPENCHIA_ARCHITECTURE.md` and `README.md` present the syscall
policy as a boundary. An allow-by-default filter with two different, hand-maintained
tables cannot be reasoned about as one; the arm64 one is quietly the weakest link.

**Suggested fix.** (a) At minimum, bring the aarch64 table to parity and add
`io_uring_setup`, `memfd_create`, `open_by_handle_at`, `unshare`, `setns`, the mount
API, and `process_vm_*` to both; add the x32 guard. (b) Better: invert to
`default_action: errno_eperm` with an explicit allowlist of the ~40 syscalls the worker
actually needs after activation (its syscall set is tiny and fixed: `read`, `write`,
`epoll_*`, `futex`, `mmap`/`munmap`/`brk`, `rt_sigaction`, `exit_group`, …). (c) Until
then, amend README/ARCHITECTURE to state that seccomp is a denylist, not a sandbox
boundary, and that the primary filesystem boundary is Landlock.

---

### H3 — Egress attribution uses the **grain name** as the Episode `local_id`; the invariant that makes ADR D6 true is unenforced

**Severity: High (latent; the stated guarantee has no enforcement).**

**Evidence**

- ADR 0002 D6: "the host … takes the grain name of the last path element as the node
  `local_id` whose rules apply. The worker cannot borrow another node's allowlist by
  naming it."
- `executor.py:798`: `local_id = body["episode_path"][-1]["grain"]`.
- `http_broker.py:436`: `for rule in self.policy.get(local_id, ())` — the policy is
  keyed by the **Architecture `local_id`** (`contracts.py:1031-1035`).
- The two coincide only because the planner sets them equal:
  `episode_builder/planner.py:1287`: `grain_name=node.local_id`.
- `WorkflowMaterializationPlan.__post_init__` enforces **`local_id` uniqueness**
  (`episode_builder/_contract_chain.py:582-583`) but says nothing about `grain_name`.
  `NodeMaterializationPlan` validates `grain_name` only as a token
  (`_contract_plan.py:205`). `linker.py:502` checks `binding.grain_name ==
  node.grain_name`, never `== node.local_id`.
- The runtime path is built from grain *names*, not local ids:
  `linker.py:873` (`Grain(name=activated.binding.grain_name, …)`),
  `linker.py:968`, `:1003-1008`.
- Library reference designs already use non-local_id grain names
  (`episode_library/page.py:387` `grain_name="page"`,
  `episode_library/search_strategy.py:107` `grain_name="strategy"`, etc.).

**Why it matters.** Today this is correct and fails *closed* (a mismatch yields
`denied`). But the only thing standing between the current behaviour and a node
inheriting a sibling's allowlist is one line in a planner that is free to change — and
if two nodes ever share a grain name, the lookup silently widens rather than narrows.
A security property asserted in an ADR should not rest on an undocumented coupling in a
different subsystem.

**Suggested fix.** Either (a) assert `node.grain_name == node.local_id` in
`NodeMaterializationPlan.__post_init__` and in
`RunRegistration.from_admitted_build`, with a comment pointing at ADR D6; or
(b) better, carry an explicit `grain_name → local_id` map in the registration
(it is already hashed into `semantic_record`) and have `_broker_http_request` resolve
through it, rejecting an unmapped grain as a protocol violation.

---

### M1 — The operator egress ceiling is not a request-time gate, and is a process-start snapshot; the README says otherwise

**Severity: Medium.**

**Evidence**

- `README.md`: "The host admits it against the approved rules **and the operator's
  `openchia.egress` ceiling in `config.yaml`**, injects the named credential itself…"
- `ScopedHttpBroker.__init__` takes `policy`, `credentials`, `transport`,
  `max_frame_bytes` — **no allowed-hosts set** (`http_broker.py:397-422`).
  `_match` (`:427-444`) checks the approved rule only.
- `agent/openchia_host.py:1488-1492` constructs it with
  `policy=registration.egress_policy, credentials=self.egress_credentials` — the
  ceiling (`self.egress_hosts`) is not passed.
- The ceiling *is* re-checked, but coarsely and earlier:
  `agent/duet_service.py:699-705` requires `authority.egress_hosts ⊆
  self.allowed_egress_hosts` when `/run` resolves the current build authorization.
- `self.egress_hosts` is read **once**, at `OpenChiaHost.__init__`
  (`agent/openchia_host.py:179`), so narrowing `config.yaml` has no effect until the
  process restarts.
- Credentials *are* implicitly ceilinged: an unknown credential name yields `denied`
  (`http_broker.py:508-517`). Hosts are not.

**Why it matters.** ADR 0002 claims "two independent gates". In practice there is one
gate at authority-resolution time against a stale snapshot, and none at request time.
An operator who removes a host from `allowed_hosts` to stop traffic will see no effect
on a running session.

**Suggested fix.** Pass `allowed_hosts` into `ScopedHttpBroker` and deny any request
whose rule host is outside it, with reason `egress_host_not_allowed`. Re-read
`_operator_egress_ceiling()` at `start_run()` instead of at host construction. Or
amend the README to describe the ceiling as approval-time only.

---

### M2 — Landlock ABI is pinned with `!=`, so any future kernel breaks every Run

**Severity: Medium (availability).**

`landlock.py:214-219`:

```python
actual_abi = _query_abi(libc)
if actual_abi != LANDLOCK_ABI_VERSION:
    raise LandlockError(f"executor requires Landlock ABI {LANDLOCK_ABI_VERSION}, kernel reported {actual_abi}")
```

The handled-rights masks (`:25-30`) are *lower bounds* — a kernel reporting ABI 8 still
honours bits 0-15 — but the worker refuses it. The container backend pulls a moving
base image and runs on a moving Docker Desktop / Rancher Desktop VM kernel
(`container_executor.py:62`, README "needs a Linux kernel with Landlock ABI 7
(6.15+)"), so this will break by itself on a routine kernel bump. The failure also
surfaces badly — see M3. `RuntimePolicy` repeats the exact pin
(`contracts.py:413-414`).

**Suggested fix.** `if actual_abi < LANDLOCK_ABI_VERSION: raise`, and record the
observed ABI alongside the pinned one in the receipt so the evidence stays exact
without forbidding newer kernels.

---

### M3 — Worker stderr is discarded in all four launch/inspection paths

**Severity: Medium (diagnosability; every pre-READY failure is opaque).**

`stderr=asyncio.subprocess.DEVNULL` at `executor.py:398`, `executor.py:1435`,
`container_executor.py:324`, `container_executor.py:525`.

`worker.main` writes its one-line diagnosis to stderr
(`worker.py:456-459`): `isolated worker failed: <Type>: <message>`. Every
bootstrap failure (`BootstrapError`: manifest mismatch, stdlib drift, unmanifested
file), every `LandlockError` / `SeccompError`, and every `RuntimeLinkError` before the
READY frame travels on that channel — and is thrown away. The host instead reports
`ProtocolError("worker protocol stream ended inside a frame")` or
`RunExecutionError("transient service exited before inspection")`
(`executor.py:206-207`, `:620`). The resulting Run evidence carries only that generic
string (`executor.py:1134-1145`).

**Suggested fix.** Capture stderr to a bounded ring buffer and attach the tail to the
host-origin failure `typed_status` (and to `RunExecutionError`). It is untrusted text,
so truncate and strip control characters as `_failure_status` already does.

---

### M4 — No wall-clock bound anywhere in the execution path

**Severity: Medium.**

- `_inspect_executor` polls `systemctl show` in `while True` with a 50 ms sleep and no
  deadline (`executor.py:618-630`); the only exit is the launcher dying.
  `ContainerRunExecutor._inspect` is identical (`container_executor.py:571-584`).
- The host protocol loop is `while True: frame = await channel.receive()`
  (`executor.py:1014-1015`) with no idle timeout.
- The generic Episode loop is `while True` driven solely by the source and the
  controller's `stop` (`method_loop/episode.py:1286-1308`, `:1321-1350`).
- `RuntimePolicy` states this is deliberate: "this policy intentionally contains no
  elapsed-time or iteration decision" (`contracts.py:392-394`).

The design intent (budgets are isolation bounds, not stopping rules) is respectable,
but the consequence is that a non-terminating generated controller hangs the host Run
thread until a human types `/stop`. The cgroup ceilings bound CPU and memory, not time.

**Suggested fix.** Add a bounded deadline to the two inspection loops (a Run that is
not running after N seconds is a launch failure, not an infinite wait) and an optional
operator-configured Run wall-clock ceiling that emits `CancelKind.HOST_SHUTDOWN` — an
isolation bound, not a stopping rule, in the same spirit as `max_frame_bytes`.

---

### M5 — `append_event` is O(n²): the entire event chain is re-read and re-validated on every append

**Severity: Medium (performance; it bites exactly the workload the ADR was written for).**

`RunStore.append_event` (`store.py:553-588`) per event:
`read_registration` + `read_claim` (two full JSON reads with contract re-validation and
`attestation.validate_against`), then `_load_event_chain_locked` (`store.py:334-376`),
which reads *every* prior event file, re-parses it, rebuilds each `RunEvent` (each of
which recomputes its content id and hash), and re-checks the linkage.

`_build_audit_chunks` (`store.py:435-483`) is the same shape at finalization: for each
event it `materialize`s a candidate chunk over all pending events and canonically
serializes it to measure size — quadratic in the chunk's event count.

The motivating workload in ADR 0002 is "hundreds of read-only HTTP calls per
collection", and each call produces two events plus per-unit `UNIT_COMPLETED` events.
At 5 000 events the store performs ~12.5 M event parses and hash recomputations.

**Suggested fix.** Cache the validated chain head in the `RunStore` instance under the
claim lock (sequence, last `event_hash`, registration/attestation objects), re-reading
from disk only when the lock is first acquired or on a mismatch. For chunking, track the
running serialized length incrementally instead of re-serializing the candidate.

---

### M6 — Test coverage is lopsided: the leg with a round-trip test works, the one without it is broken

**Severity: Medium (process).**

`tests/episode_runtime/` contains `test_executor_http_loop.py` (a real
encoder/decoder/worker-stub round trip through `_RunExecutorBase.execute`) but no
equivalent for the model path — which is precisely where H1 lives.

`tests/episode_runtime/test_staged_closure_imports.py:17,19-27` only matches
`^from \.(\w+) import` inside `episode_runtime/`. It does **not** cover:

- absolute sibling imports, which is the form `worker.py` actually uses
  (`worker.py:26-58`: `from episode_runtime.broker import …`);
- imports of the other staged packages (`agent.*`, `episode_builder.*`,
  `episode_library.*`, `handoff_library`, `method_loop`, `llm_call_library`,
  `http_call_library`);
- transitive closure inside those packages.

I computed the real AST closure from `episode_runtime.worker` over all staged files:
one unstaged local module is reachable — `llm_call_library/transport.py:126` imports
`agent.auxiliary_client`, which is not in `_SELECTED_LOCAL_SOURCES` (see L5). Otherwise
the closure *is* closed.

**Suggested fix.** Replace the regex test with the AST closure walk (it is ~40 lines
and found a real hit). Add a model-request round-trip test mirroring the HTTP one.

---

### M7 — The attestation validates the worker's seccomp policy against the **host's** architecture

**Severity: Medium.**

`contracts.py:1181-1182`:

```python
if self.seccomp_receipt.policy_hash != seccomp_policy_hash():
    raise ValueError("executor installed another seccomp policy")
```

`seccomp_policy_hash()` with no argument calls `_machine()`
(`seccomp.py:157-161`), i.e. `platform.machine()` of the **host** process. For the
container backend the worker's architecture is the *image's*. The `normalize_machine`
aliasing (`seccomp.py:138-154`) makes the common macOS case work, but an emulated or
cross-platform image (`--platform linux/amd64` on Apple Silicon, qemu-binfmt on CI)
makes the host hash a policy the worker did not install, and the claim is rejected with
a misleading message. `RuntimePolicy.seccomp_policy_hash` has the same host-derived
default (`contracts.py:403`).

Related inconsistency: `landlock._SUPPORTED_MACHINES` lists `i386/i486/i586/i686` and
`riscv64` (`landlock.py:36-47`) but `seccomp._AUDIT_ARCH` only knows x86_64/aarch64
(`seccomp.py:34-38`). On such a host `RuntimePolicy()` raises `SeccompError` from a
field default factory before `/run` can even register — an obscure failure mode.

**Suggested fix.** Derive the expected seccomp machine from the executor
(`ContainerRuntime` already knows the image), pass it explicitly to
`seccomp_policy_hash(machine)` in `RuntimePolicy` and in
`InspectedExecutorAttestation.__post_init__`, and make the two supported-machine sets
agree.

---

### M8 — The per-rule budget is consumed before the request is attempted

**Severity: Medium (low impact, surprising semantics).**

`http_broker.py:492-503` increments `self._counts[key]` immediately after the budget
check, *before* reading the credential (`:507-528`) or dialling (`:541-549`). A rule
whose token file is missing therefore burns its whole `max_requests` budget on
`denied` responses that never left the host, and the Episode sees budget exhaustion
instead of the real cause.

**Suggested fix.** Increment after the credential resolves (i.e. immediately before
`await self.transport(...)`), or count attempts and non-attempts separately in the
`denied` reason text.

---

### M9 — `_RunExecutorBase` leaks systemd specifics; the `RunExecutor` Protocol is declared but never used

**Severity: Medium (design/maintenance).**

The split is genuinely good in its main dimension — the whole protocol, event chain,
attestation, cancellation and finalization live once in
`_RunExecutorBase.execute` (`executor.py:845-1152`), and the two backends differ only
in `_identity_arguments` / `_launch_identity` / `_runtime_mounts` / `_launch` /
`_inspect` / `_stop_exact` (`executor.py:740-779`). But:

- `_RunExecutorBase` lives in `executor.py`, the systemd module, and
  `container_executor.py:46-53` imports six private names from it
  (`_ExecutorFacts`, `_LaunchIdentity`, `_RunExecutorBase`, `_launch_identity`,
  `ExecutorResources`, `RunExecutionError`). The shared base should be its own module.
- `_ExecutorFacts` is a systemd vocabulary (`unit_name`, `invocation_id`,
  `cgroup_path`, `leader_start_time_ticks`) that the container backend has to
  impersonate: `invocation_id=container_id` (`container_executor.py:637`) and
  `unit_name=<container name>`. `InspectedExecutorAttestation` then branches on
  `executor_kind` to pick a 32-hex vs 64-hex regex (`contracts.py:1198-1209`) — the
  abstraction leak surfaces all the way into the contract.
- `launch_description` is always built with a systemd-style 32-hex nonce even for
  containers (`executor.py:330-338`, validated at `contracts.py:1210-1226`).
- `_RunExecutorBase` declares `run_store: RunStore` / `repository_root: Path` as bare
  class annotations (`executor.py:737-738`); it is not a dataclass, so these are
  documentation only and each subclass re-declares and re-validates them
  (`executor.py:1160-1161`, `container_executor.py:386-387`).
- `RunExecutor` is `@runtime_checkable` (`executor.py:704-725`) but no call site ever
  does `isinstance(x, RunExecutor)`; `OpenChiaHost` accepts any callable factory
  (`agent/openchia_host.py:159-161`). `python_executable` is typed
  `Path | PurePosixPath` purely so the container backend fits.
- `_ExecutorFacts` performs **no validation**: the container path feeds it
  `str(probe.get("boot_id", ""))`, `str(probe.get("cgroup_path", ""))` and
  `int(probe.get("leader_start_time_ticks", 0))` straight from untrusted probe JSON
  (`container_executor.py:639-642`). An empty `boot_id` or a non-numeric tick value
  produces either a silently degenerate `executor_instance_id` or a raw
  `ValueError`/`TypeError` out of `int()`.

**Suggested fix.** Move `_RunExecutorBase`, `_ExecutorFacts`, `_LaunchIdentity` and
`ExecutorResources` into `episode_runtime/_executor_base.py`; rename the facts fields to
backend-neutral terms (`instance_name`, `instance_id`); validate `_ExecutorFacts` in
`__post_init__` (non-empty boot id, positive tick count, absolute cgroup path); and
either assert `isinstance(executor, RunExecutor)` in
`OpenChiaHost._runtime_executor()` or drop `@runtime_checkable`.

---

### L1 — Any lazy stdlib import after seccomp fails opaquely

seccomp denies `openat`/`openat2`/`open` (`seccomp.py:41,71,85,112`) and Landlock denies
all path access, both installed before `activate()` (`worker.py:348-356`). The only
pre-loading is of the generated modules' *statically declared* imports
(`linker.py:685-689`) and `FunctionImplementation` modules (`:686-689`). Any stdlib
module first touched at runtime — a rarely-used `encodings` codec, `concurrent.futures`
on an `asyncio.to_thread`, `linecache` during traceback formatting — will hit
`_read_regular`'s `os.open` (`bootstrap.py:88`) and fail with
`BootstrapError("cannot open exact import source …")`, which surfaces as a generic
`failed` terminal status.

*Fix:* pre-import a fixed warm set in the worker before `apply_seccomp_policy`, and
document that an Episode must not import lazily.

---

### L2 — Undocumented public surface

`episode_runtime/__init__.py` has a one-line docstring and a flat, unsorted `__all__` of
~130 names (`__init__.py:150-268`) re-exporting almost every internal contract,
including host-only machinery (`ScopedHttpBroker`, `CredentialSpec`,
`HttpxHostTransport`, `SystemdRunExecutor`, `ContainerRunExecutor`) alongside
worker-only machinery. Importing the package pulls in `container_executor` →
`subprocess`/`shutil` and `http_broker` → credential handling, even for a caller that
only wants a contract type.

Names that are public in their module's `__all__` but missing from the package export:
`current_runtime_episode_path` (`linker.py:1088`), `episode_id_for_path`
(`protocol.py:733`), `http_request_record` / `http_response_record` /
`http_transport_response` / `MAX_HTTP_TIMEOUT_SECONDS` (`http_contracts.py:337-351`),
`http_response_bytes` (`http_broker.py:636`), `interpreter_runtime_from_inspection`
(`identity.py:720`).

*Fix:* split the export surface into `episode_runtime` (contracts + worker) and
`episode_runtime.host` (executors + brokers), sort `__all__`, and give the module
docstring the same three-paragraph treatment the individual modules already have.

---

### L3 — Duplicated logic in the execution path

- `_HostChannel` (`executor.py:154-208`) and `_ProtocolChannel`
  (`worker.py:76-137`) duplicate frame length reading, the `expected`/`_sent_sequence`
  bookkeeping, and the encode-then-immediately-re-decode round trip
  (`executor.py:175-186` vs `worker.py:119-137`). Both also keep a `_sent_sequence`
  that shadows the encoder's own `_next_sequence` (`protocol.py:645`), and
  `FrameEncoder.write` (`protocol.py:664-688`) is a third copy of the same write loop
  that neither uses.
- Every frame is JSON-parsed and fully contract-validated **twice** on send: once by
  `encode_frame` → `ProtocolFrame.__post_init__`, then again by the immediate
  `decode_frame` (`executor.py:176-181`, `worker.py:121-127`).
- `admit_http_request` runs **three times** per request: in the decoder
  (`protocol.py:417`), in `match_rule` (`http_broker.py:453`), and in
  `ScopedHttpBroker.__call__` (`http_broker.py:480`).
  `admit_model_request` runs twice (`executor.py:1017`, `broker.py:176`).
- `RunStore.read_evidence` (`store.py:725-756`) and `read_audit_log`
  (`store.py:758-792`) are ~30 near-identical lines; the second should call the first.
- `_thaw_json` / `_freeze_json` are copy-pasted into at least six modules:
  `episode_runtime/protocol.py:164`, `episode_runtime/contracts.py:124-141`,
  `episode_builder/_contract_base.py:99`, `function_library/models.py:57`,
  `agent/episode_contract_models.py:216`, `method_loop/binding.py:53`,
  `method_loop/episode.py:108`. They have *subtly different* semantics (some raise on
  non-JSON, some stringify), which is how H1 became possible.
- `method_loop/episode.py` maintains a full sync/async duplicate pair
  (`run`/`run_async` `:1066-1095`, `_run_loop`/`_run_loop_async` `:1282-1350`,
  `_stop_end`/`_stop_end_async` `:1250-1281`, `ChildEpisodeUnit._finish`/`_finish_async`
  `:1377-1420`). The **sync half is dead code in the isolated runtime** —
  `_InstrumentedEpisode.run` raises `RuntimeLinkError("isolated runtime Episodes must
  run asynchronously")` (`linker.py:757-759`).
- `bootstrap.py` deliberately re-implements `identity.py`'s walking/hashing/interpreter
  logic because it must stay stdlib-only (`bootstrap.py:1-6`, `:315-318`). That
  duplication is justified, but it is ~200 lines that must be kept byte-compatible by
  hand; the only guard is `tests/episode_runtime/test_supplied_interpreter_identity.py`.
  Worth an explicit cross-reference comment in both files and a test that asserts
  `bootstrap._inspect_interpreter_record()` and
  `identity.inspect_interpreter_runtime()` agree on this interpreter.

---

### L4 — Swallowed exceptions and lost error detail

- `agent/openchia_host.py:96-106`: `except Exception` around the whole egress-config
  load, logged at WARNING, result `(), {}`. A typo in `config.yaml` silently disables
  all egress for the session; the Run then reports `denied: no egress rule admits …`,
  which points at the contract rather than the config.
- `executor.py:623-625` / `container_executor.py:576-578`: `except RunExecutionError:
  await asyncio.sleep(0.05); continue` — every inspection error during startup is
  swallowed into a retry; the last error is never reported if the loop later fails for
  another reason.
- `executor.py:1108-1109` and `:1132-1133`: `except BaseException: sender_sequence =
  channel.next_sender_sequence` — the failure to deliver the CANCEL frame is discarded
  entirely, including `KeyboardInterrupt`/`SystemExit`.
- `executor.py:1121-1122` and `:1147-1148`: `except RunStoreConflict: pass` — if
  finalization conflicts the Run ends with no evidence and no record of why.
- `_stop_exact` (`executor.py:1344-1397`, `container_executor.py:683-720`) runs in a
  `finally` (`executor.py:1150-1152`); its own `RunExecutionError`s will replace the
  original exception being propagated.
- `http_broker._admitted_headers:204-223` silently `continue`s past any header that is
  malformed, over-long, or not in the allowlist — correct behaviour, but the evidence
  record gives no hint that headers were dropped.
- `container_executor.py:641`: `int(probe.get("leader_start_time_ticks", 0))` raises a
  bare `ValueError`/`TypeError` rather than a `RunExecutionError` on malformed probe
  output.
- `linker.py:348-352`: `_json_value` turns an unprojectable object into
  `{"unprojected_type": "<module>.<qualname>"}` and carries on — the audit record
  silently loses the value. Reasonable, but undocumented in the evidence schema.

---

### L5 — One staged module reaches an unstaged local module on its fallback path

`llm_call_library/transport.py:126` imports `agent.auxiliary_client` inside
`_host_transport`, which is the fallback used when no model transport scope is set
(`transport.py:155-162`). `agent/auxiliary_client.py` is **not** in
`_SELECTED_LOCAL_SOURCES`. Inside the worker this fails closed (the synthetic `agent`
namespace has no such submodule, and `_ClosedImportFinder` would reject it anyway), but
only because `worker.py:384` always installs the scope. `http_call_library` is the
better model: it has no fallback at all (`http_call_library/transport.py:139-150`).

*Fix:* give `llm_call_library` the same no-fallback shape, or keep the fallback behind
an explicit `install_host_fallback()` the host opts into, so the staged module has no
reference to an unstaged one.

---

### L6 — `ProtocolFrame.__post_init__` builds a throwaway binding with the default frame size

`protocol.py:507-511` constructs `ProtocolBinding(run_id, registration_hash,
manifest_id)` — dropping the caller's `max_frame_bytes` and silently using
`DEFAULT_MAX_FRAME_BYTES`. It is currently harmless (`_validate_body` never reads
`max_frame_bytes`) but it is a trap: any future size-dependent body validation would
check the wrong bound, and if `ProtocolBinding`'s lower bound ever rose above the
default the constructor would start raising inside `__post_init__`.

---

### L7 — Container runtime discovery and caching

- `_RUNTIME_CACHE` is a module-global keyed by `(cli, image)` and never invalidated
  (`container_executor.py:723, :745-749`). A long-lived host keeps using a stale image
  digest and a stale `daemon_cpus`/`daemon_memory_bytes` after a re-pull or a VM resize
  — even though the docstring says the allocation is "re-read for every Run" (only
  `default_resources()` is recomputed, from the cached numbers).
- `find_container_cli` honours `OPENCHIA_CONTAINER_CLI` (`container_executor.py:138`)
  and will execute any executable path it names. Local-only, but it is the one
  unauthenticated input to the "launch through the system service boundary" claim.
- `inspect_container_runtime` reads the bootstrap from the **live checkout**
  (`container_executor.py:292`) rather than from a staged copy, to capture the image's
  interpreter identity. The identity is self-consistent (the same code verifies it
  later) but it means the interpreter identity baked into the registration originates
  from mutable bytes. This does not weaken the "mutable checkout is not an *execution*
  dependency" claim — the Run executes only staged bytes — but it is worth stating
  explicitly that closure verification proves *immutability during a Run*, not integrity
  against a tampered checkout.

---

### L8 — `_read_credential` omits `O_NOFOLLOW`

`http_broker.py:333`: `os.open(spec.path, os.O_RDONLY | os.O_NONBLOCK)`. Every other
sensitive read in this subsystem uses `O_RDONLY | O_NOFOLLOW`
(`bootstrap.py:88`, `identity.py:93`, `linker.py:159`, `store.py:153`,
`executor.py:213`). The path is operator-configured so the risk is low, but the
inconsistency should be deliberate or removed. (`O_NONBLOCK` + the `S_ISREG` check at
`:340` correctly handles a FIFO.)

---

### L9 — Declared Episode capabilities are structurally unusable at runtime

`worker.py:380` calls `activated.link(event_sink=…, collaborators={})`, and
`link()` requires `set(collaborators) == {every capability_name in the plan}`
(`linker.py:833-839`). Any workflow that declares a capability therefore dies at link
time with "runtime collaborators must exactly cover admitted capabilities". This is
consistent with `OpenChiaHost(allowed_episode_capabilities=())`
(`agent/openchia_host.py:182`) and with the architecture's "the generated package does
not receive general host tools", so it is closed by design — but
`OPENCHIA_ARCHITECTURE.md` lists capabilities as a first-class Episode property without
noting that the current runtime admits exactly zero of them.

---

### L10 — `http_response_bytes` under-reports in evidence

`http_broker.py:614-622` returns `0` when the response record has no body — which is
every `denied`, `transport_error`, and `oversize` outcome. The `HTTP_RESPONDED` event
therefore records `response_bytes: 0` for an oversize response that was in fact larger
than the cap (`executor.py:840`). The field name invites the opposite reading.

---

## 4. Answers to the specific questions

**Is the closure verification sound — can a mutable checkout influence execution?**
During a Run, no. The staged package is content-addressed, named by its manifest id,
made read-only, bind-mounted `ro`, re-verified by the host before launch
(`executor.py:865-874`), re-verified byte-for-byte by the bootstrap
(`bootstrap.py:301-312`), and re-verified *again* per file at import time
(`bootstrap.py:383-397`). `sys.path` and `sys.meta_path` are replaced wholesale
(`bootstrap.py:542-553`), the interpreter runs `-I -S` with `env -i`, and the build
package is separately hash-bound to the registration (`linker.py:631-667`). The
checkout's bytes enter only at *staging* time, under hash-stability checks
(`identity.py:478-485`). The honest framing: this proves immutability and
reproducibility of one Run, not integrity of the checkout the operator starts from
(see L7).

**Is the "source-only closed import finder" actually closed?**
Yes, with one caveat. I computed the full AST import closure from
`episode_runtime.worker` across all staged files: every reachable local module is staged
except `agent.auxiliary_client`, reached only from `llm_call_library`'s host-fallback
branch, which cannot run inside the worker (L5). The finder admits only
built-in/frozen modules, staged local files, and hashed stdlib files
(`bootstrap.py:420-456`); namespace packages are checked for root escape
(`bootstrap.py:426-436`); after seccomp installs, no new file can be opened at all.

**Is the broker state machine well-defined?**
Yes for sequencing. Frame types are sender-partitioned (`protocol.py:68-71`,
`:497-499`), sequences must be contiguous per sender (`protocol.py:569-572`,
`FrameDecoder:703-711`), and the phases are enforced positionally: `INITIALIZE`→`READY`
(`worker.py:331-333`, `executor.py:922-924`), `READY`→`START`
(`worker.py:366-368`), then the steady-state loop. `TERMINAL_ACK` is rejected before
the worker has sent `TERMINAL` (`worker.py:265-268`) and the host only sends it from the
`TERMINAL` branch (`executor.py:1079-1095`). The weakness is not the state machine but
its *payloads* — H1.

**Can partial publication become a successful Run receipt?**
No. Evidence is published last and `read_evidence` re-derives the whole chain
(§1.7). The host additionally re-reads durable evidence and compares it to the
executor's return value (`agent/openchia_host.py:1543-1552`).

---

## 5. Priority order for remediation

1. **H1** — one-line decoder fix plus a model round-trip test; without it the model
   broker does not work at all.
2. **H2** — seccomp parity and the io_uring/mount-API/x32 gaps, or an honest README.
3. **H3** — enforce or remove the grain-name/local_id coupling behind ADR D6.
4. **M3**, **M2** — capture worker stderr and relax the Landlock pin; together these
   turn the two most likely operational failures from opaque into diagnosable.
5. **M1** — make the operator ceiling a request-time gate, or correct the README.
6. **M5**, **M4** — store performance and bounded waits before the first long Run.
7. **M9**, **L3** — the structural clean-ups; worth doing while the two executors are
   still young enough to refactor cheaply.
