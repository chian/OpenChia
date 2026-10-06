# Reproducible Target Workflow environments

Implementer's coding workspace and the Target Workflow's environment are
different. Implementer edits code and a saved environment recipe. OpenChia
prepares the declared dependencies through the existing execution backend;
independent validation and later Runs do not inherit the coding session.

See [ADR 0010](../adr/0010-target-workflow-environments-follow-candidate-revisions.md),
[coding workspace setup](implementer_coding_workspace.md) and
[model launch configuration](episode_launch_configuration.md). Environment
preparation changes neither the owning Duet's model route nor the Target
Workflow's approved launch configuration.

## Contract and completion criteria

1. Implementer receives runtime identity, available base libraries, package
   management, managed workspace paths, installation permissions and the
   assignment's environment requirements as typed context.
2. Dependency declarations and setup instructions are candidate files. Edits
   use the same writable-path authority and revision history as source edits.
   The host records resolved versions with the candidate's admitted build.
3. Coding diagnostics, independent validation and ordinary Runs use
   `EnvironmentPreparationService`. The selected systemd or container executor
   performs preparation; there is no host-side pip fallback.
4. Preparation writes only managed output/cache plus backend-private temporary
   storage. Installation access does not grant Run access. Personal settings and
   OpenChia's own installed dependencies are not modified.
5. Failure yields typed stage/error information and references to full persisted
   logs. Those findings return through existing refinement feedback and parent
   reports. Successful preparation alone does not satisfy a behavior check.
6. Completion needs real evidence: a dependency absent from the base runtime,
   an Implementer-authored recipe, independently prepared successful execution,
   and a broken recipe corrected and successfully prepared fresh. Isolated
   contract tests do not establish this complete outcome.

## The candidate recipe

Each source-workflow scope exposes `.openchia-environment.json` in its existing
candidate path map. For example, this is a recipe format illustration, not a
validated library workflow:

```json
{
  "schema_version": 1,
  "python": "3.14",
  "dependencies": ["packaging>=25,<26"],
  "import_roots": ["packaging"],
  "setup_instructions": "Use the declared package for version parsing."
}
```

Use the Python version in the supplied environment context, not this example's
version. The recipe cannot install a different interpreter. Requirements must
be bounded public-registry specifications. `import_roots` names imports allowed
in generated source; the prepared closure also contains any installed transitive
imports. The host rejects collisions with standard-library or OpenChia modules.
Setup instructions explain intent and remain data; they are not executed as
shell scripts or trusted prompt instructions.

Candidate source projection validates the file. Invalid JSON or unsupported
requirements produce ordinary candidate findings, not a coding-session repair
performed by the host. The host-owned `TARGET_ENVIRONMENT_LOCK.json` records
the resolved `uv.lock`, recipe hash and runtime hash. Implementer does not
fabricate that resolution. BuildManifest binds both records to admitted source.

BuildManifest now requires exact `environment_recipe` and `environment_lock`
fields, both `null` when there is no recipe. Older manifests lacking these fields
are not accepted. Rebuild those artifacts using the current Builder; this change
does not migrate historical builds or add a backward-compatibility reader.
Likewise, an interrupted Run retains its frozen runtime and environment identity;
current code cannot silently substitute for an unavailable older runtime.

## One preparation path

`episode_runtime/target_environment_preparation.py` owns preparation records and
publication. Its `describe()` supplies the explicit starting context;
`prepare(recipe, duet_id=..., candidate_ref=..., resolved_lock=..., fresh=...)`
returns structured results; `prepare_manifest(manifest, duet_id=..., fresh=...)`
prepares an already admitted build and requires its saved resolution.

`pm/prepared_project.py` runs inside the selected backend. It uses PM's verified
tool selection and existing environment operations to resolve, create, install
and inspect the environment. It reads package metadata without importing
dependency code. The host constructs its command; model-authored shell scripts
are not an installation API.

Prepared immutable files live at:

```text
<RunStore>/target_environments/<environment_id>/
  TARGET_ENVIRONMENT.json
  site-packages/
```

The record binds recipe, lock and runtime hashes, exact distribution versions,
import roots and every installed file hash. The selected runtime identity
includes the staged worker source and interpreter, not merely `python --version`.
Missing cached files require fresh preparation; changed files fail verification.
Reusing a directory just because a package imports is not sufficient.

Implementer receives the prepared interpreter and diagnostic findings through
its existing coding context. Its diagnostic results are working evidence, not
independent acceptance. A coding backend must be able to execute the selected
prepared interpreter; a container's Linux interpreter is not automatically a
host-executable program on macOS or Windows. That cross-backend diagnostic case
must not be treated as verified by native Linux tests.

The shared test harness prepares dependencies before Run registration and
dispatch. Ordinary `/run` prepares in its existing background worker, outside
the UI locks. Preparation failure is reported as a host/preparation failure,
not a successful Target Workflow or an incomplete Run with invented evidence.
Continuation verifies the same saved prepared identity through the shared
execution path; it does not re-resolve dependencies to newer versions.

## Installation and execution authority

Preparation and execution have different permissions:

| Operation | Authority |
| --- | --- |
| Resolve and install dependencies | Host-constructed PM command; managed writable output/cache; explicit installation-network setting |
| Import and use dependencies in a Run | Exact hash-bound tree mounted read-only; worker filesystem/syscall policy installed before import |
| Model and external HTTP calls | Existing host brokers and approved launch/egress contracts, unchanged |
| Change code or recipe | Existing scoped candidate proposal and admission |
| Accept behavior or award credit | Existing measures, independent parent acceptance and numerical controller |

The first implementation uses anonymous public PyPI only. No private-registry
credential references are supported yet, and ambient tokens, home configuration
or proxy settings are not copied into PM. An authenticated package source needs
a future explicit approved credential-reference policy; it must not be enabled
by copying the Duet or coding agent's environment.

Only wheels are installed. Source builds, editable installs, startup hooks and
OS package installation are not supported. Native wheels still have to work
inside the existing confinement; unavailable shared libraries produce import
diagnostics. No automatic host security changes or unrestricted fallback occur.

## Feedback, records and credit

Preparation results contain status, typed diagnostics, full-log references,
the resolved lock and prepared identity when successful. Complete stdout and
stderr are separate content-addressed Builder blobs. Environment preparation
and resolution records use the existing Duet artifact store, not another
database or replay journal.

`iterative_episode_refiner/candidate_environment.py` binds these records to
candidate, source-workflow scope, invocation and unit. Its finding projection
includes the diagnostic, resolved distributions and evidence references in the
Episode's own working history. Failures during initial preparation, restoration
of a dispatched Run, and preparation of an independent checker also survive the
shared experiment-result handoff. Findings distinguish the Target Workflow
from its measurement environment. Parent reports include requested findings,
not raw command streams or audit identities. Malformed recipes and failed
preparation therefore inform the next Episode action through the same loop as
source and behavior failures.

Preparation failure before a worker starts does not invent terminal Run evidence
or a failed behavior measurement. The existing execution owner is released;
the same unclaimed dispatch can be retried through ordinary execution admission.
A checker setup failure leaves the candidate unmeasured and does not cache a
permanent checker verdict or require rerunning its successful Target Workflow.

Neither installation success nor a coding-agent assertion awards credit. The
existing measurement and acceptance mechanisms determine whether the resulting
candidate meets its assigned requirements. No new stopping rule, retry budget,
Episode topology or replay mechanism is introduced.

## Verification status

On the native Linux development host, focused checks exercised actual systemd
preparation with explicit-only environment variables, writable managed output,
read-only inputs, nonzero exit propagation and complete stdout/stderr capture.
Actual worker filters permitted dependency imports and resource reads while
denying writes/process/network operations. Namespace child imports, import
deferral, tamper rejection and the source-only staged worker import also passed.
These are backend and integrity checks, not proof of a reasoning agent solving
a dependency-bearing Target Workflow.

Existing zero-dependency reasoning workflow and learning-broker checks passed.
The ordinary launch integration also passed with real approval, materialization,
generated Episodes and shared harness, using an in-process executor and supplied
model responses. It verifies the background Run lifecycle, not dependency-bearing
live reasoning or OS confinement.
The native service/container contract suite passed; its actual container check
was skipped because the container daemon was unavailable. No macOS, Windows,
or container dependency Run is claimed here.

The focused candidate/environment suite passed all 10 cases. The shared
preparation-failure suite passed all three cases, including recovery without
duplicating an already successful target and correct attribution of a continued
checker's failure. Two real-store status tests passed after closing and reopening
the Duet. These are integration/invariant checks, not live reasoning evidence.

The full repository suite has not passed or been claimed. Two additional suites
encountered fixture/API drift already present at base `ca429c1a36`:
`test_campaign_source_experiments.py` calls `_inherited_draft` without its required
session/report arguments, and `test_shared_execution.py` uses a repeatable-call
fixture missing `authority_attenuation`. The corresponding files and definitions
are unchanged by this work; those unrelated repairs remain outside this goal.

### Live environment acceptance — 2026-10-05

The opt-in live suite passed **2 tests, 0 failed, in 362.4 seconds** on native
Linux/systemd, using the owning Duet's saved `gpt-5.6-sol` / high-effort binding.
The base interpreter could not import `humanize`. The real coding agent created
source that calls `humanize.intcomma` on each input and returns the installed
package's `__version__`; it did not hardcode the expected output.

- **Missing recipe:** Implementer authored the code and recipe. Normal candidate
  admission retained the host-resolved lock. A separate RunStore prepared a
  fresh environment from that exact lock and the native Target Workflow Run
  passed the independent answer check.
- **Broken recipe:** the starting fixture required nonexistent
  `humanize==0.0.0`. Actual package resolution produced `ResolutionConflict`.
  Its concrete diagnostic and complete log references reached Implementer's
  assignment file. The real coding agent repaired the recipe; the corrected
  candidate passed fresh preparation and independent native execution.

Both returned `{"formatted":["1,234,567","-9,876,543","0"],"dependency_version":"4.16.0"}`.
The host verified the strings against the independent criterion and the version
against the resolved distribution. Both results have `execution_status=succeeded`
and `candidate_verdict=pass`. Fresh preparation had `cache_reused=false`, a
different diagnostic interpreter path and an identical saved lock. Dependencies
were not imported into the OpenChia host.

The shared artifact store contains the complete receipts as
`experiment.target_environment_acceptance.v1`, including candidate, admitted
build, authentic coding response, preparation, fresh preparation and measurement
references. Local artifacts live under
`/var/tmp/openchia-target-environment-live.V7Mi8K/pytest/`:

| Case directory | Acceptance artifact | Native Run |
| --- | --- | --- |
| `test_live_implementer_environm0` | `experiment_data_bbc0c3977e060538ec8aeb0d26cc8c5b5765b6edc0364c68b16daed2c3653d08` | `run_5894ade04f5db0d93572e234ffbf3c686db7d1da0d87227503aa2618e349b1ae` |
| `test_live_implementer_environm1` | `experiment_data_0a9cb9681605bd7e8c819a169c81b6a9eb0911749d20b73452b6d9753eae434a` | `run_ce56aed5bfbd386f9990e80cb461c9f9464f7870cd40c8b395139a5b6c04c2e8` |

Each case's `duet.db` contains its acceptance artifact; native evidence is under
`independent-runs/evidence/`. Acceptance content hashes are respectively
`sha256:db0a67ea31cc5951c69a19f89c3ed764cc2bd180a740a4aaef9783aa860c3895`
and `sha256:5434325eeefc22afe63acc86afb483606c2fa9235487c09fd2fec7fd931076ad`.
The broken-recipe stderr is retained as Builder blob
`sha256:9199616c83dd59a71de34c2d797ff7dcab9915b44928edaf55c3f51ad5ed396a`.

Reproduce through the existing harness, with its test interpreter and an
installed PM-managed `uv` available:

```bash
HERMES_RUN_E2E=1 scripts/run_tests.sh \
  tests/iterative_episode_refiner/test_live_target_environment.py \
  -j 1 --file-timeout 3600 -- \
  --live-coding-profile=/absolute/path/to/owning/profile \
  --live-coding-binding=EXACT_SAVED_DUET_BINDING_ID -q -s
```

This establishes the environment goal, not autonomous Parts/Designer behavior
or an entire Duet-to-build acceptance. The initial approved incomplete scaffold,
assignment and known-answer criterion are fixtures. The disposable PM tool
records are fixture facts over real `uv` bytes, not proof of production installer
attestation. Coding, dependency resolution, admission, native execution and
measurement are real. No candidate repair or expected model response was
injected by the test driver. The earlier attempt in
`/var/tmp/openchia-target-environment-live.OwvwxT/` remains recorded as failed:
production edits during its lifetime mixed imported code versions at final
measurement. The successful rerun above used frozen source throughout.
