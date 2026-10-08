# Implementer's coding workspace

This environment belongs to Code Implementer or a scoped Code Parts invocation.
It contains the candidate source and
the admitted assignment so a coding agent can inspect, create, edit and run
diagnostic commands. It is **not the Target Workflow's execution environment**.
The latter depends on the particular workflow. Implementer now authors its
saved recipe through the separate [Target Workflow environment path](target_workflow_environment.md);
the coding sandbox still does not become that environment.

OpenChia captures actual file differences as Code Implementer proposals.
The existing host admission, shared validation harness, parent reports, credit
and rarefaction decide whether those proposals constitute progress. A coding
agent's final prose or successful command is not acceptance.

## Source and materialization specialists

Designer owns the general approach and chooses among four peer specialists:
Code Implementer, MaterializationImplementer, Measure and Verify. Its unit may
record or revise the approach and commission the selected child; there is no
automatic implementation/verification sequence or `implementation_role` field.
`implementer` creates or repairs assigned source files; `materialization_implementer`
authors assigned Materialization Spec targets through a structured model response.
The latter is a registered `MaterializationImplementer` Episode using the same
local-measurement loop, credit and rarefaction as source implementation. It has no
native coding session, shell, or file-edit tools.

Each specialist owns its task-specific Parts binding. Code Parts has source
tools; Materialization Parts has the plan API; Measure Parts authors checking
components; Verification Parts evaluates established checks. Each Parts binding
can recurse to smaller work of the same specialization. The supported child
scope narrows requirements, source paths or materialization targets. A lone
requirement with no smaller editable grant is direct work, not a case-only child
assignment that the current schema cannot represent.

Assignments carry two distinct grants: `writable_paths` and
`materialization_targets`. Designer and each specialization delegate subsets of
their own grants. Code Implementer and Code Parts receive only source paths;
MaterializationImplementer and Materialization Parts receive only plan targets.
Designer's `intended_change_scope` and
`intended_materialization_targets` additionally bound the selected specialist's
revision. Host admission rejects mixed authority and wrong-kind submissions.
The structured API accepts exact `{json_pointer, before, after}` operations;
existing Builder validators preserve the approved architecture and derive plan
identities. Coupled interface/caller changes must also remain within the granted
materialization scope. A missing node plan can be filled for an already-approved
Episode. Candidate source is unchanged by that transaction; subsequent source
admission attaches the current host-owned declarations.

Code Implementer or Code Parts writes `.openchia-implementation.json` with
`findings`, a list of `{requirement, blocker, needed_change}` records, a declared
`child` assignment (with an optional supported `conflict`), or a
`return_prerequisite` proposal. Child/return proposals cannot accompany source
edits in the same captured response. MaterializationImplementer returns the same
findings alongside its plan operations. Findings alone may be recorded without
inventing a candidate change or positive credit. The latest submitted snapshot
is available in the parent's requested `open_decisions` report section when the
child returns normally. It does not request a mid-loop parent intervention or
change numerical stopping. Diagnostic claims remain distinct from measurements.
Question and Support are callable by every role, including every Parts and
helper role. Their actual instruments remain preauthorized investigation
observations and explicitly assigned check review, not arbitrary accepted
answers or unrestricted searches. Children inherit a narrowed grant, fixed
measurement, relevant history and the parent's requested return.

Filesystem confinement still belongs to the native coding backend. These host
checks control what becomes an authoritative revision; a writable scratch file
does not confer permission to edit the Materialization Spec. The Refiner starts
directly from approved Target Workflow Architecture, with existing work when
available. MaterializationImplementer fills missing node plans through the same
validators used for revisions; Code Implementer creates missing source files.
There is no prerequisite Target Workflow Builder pass or receipt. Source admission
records a receipt when candidate code is checked. Existing campaign assignments
and materialized refiner role graphs require a fresh build for the new contract.

Implementer receives its assigned, executable local checking programs under
`.openchia-local-checks/`. The `local_check_programs` section of its working
assignment identifies the program files, entrypoints, exact candidate
materialization, case inputs, requirement locations and result predicates.
The host uses the same evaluation resolver as actual measurement and stores
each program once across its cases. These are protected diagnostic references:
editing or deleting one rejects the captured proposal. Independent acceptance
instruments and control fixtures are not included. Host evaluation continues
to execute the immutable reviewed originals; workspace copies and local
diagnostics grant no measurement credit.

## Focused implementation goal

Make Implementer's coding workspace operational using a repository-shipped
OpenChia coding-agent launcher and private configuration, with workspace
confinement intact and no changes to the user's personal Codex settings.
Native sandbox prerequisites require explicit installation instructions and
administrator-controlled setup, not automatic machine-policy changes by the
coding agent or launcher. Preserve backend-independent assignments and results. Prove
that the real coding agent can create, run, resume and revise a program whose
answer passes an independent check through OpenChia's existing integration.

Completion requires all of the following:

- The launcher and sandbox defaults are checked into this repository. Another
  user of the repository gets the same launch behavior without manually editing
  global configuration or shell startup files.
- OpenChia's Codex launches, configuration migration and session resumption use
  OpenChia-owned state. Implementer retains private per-context state. Neither
  an inherited `CODEX_HOME` nor the personal `~/.codex/config.toml` supplies or
  receives OpenChia's permission changes.
- `CODEX_HOME` is set only in the launched process's environment. The user's
  personal Codex sessions can retain full permissions while OpenChia's coding
  sessions remain sandboxed. Configuration separation alone is not a sandbox.
- Host prerequisites are documented separately from launching. On 2026-10-05
  the user accepted the Ubuntu AppArmor prerequisite for now, provided explicit
  installation instructions ship with it. The launcher does not install host
  packages/profiles, change sysctls, migrate global Codex settings or switch to
  unrestricted execution. A startup failure reports the missing prerequisite.
- The existing native coding runtime is reused. The owning Duet still supplies
  the model, effort and credential; the common coding interface continues to
  support Codex and Claude Code without changing Episode control or acceptance.
- Verification distinguishes configuration isolation from actual coding ability:
  global settings remain unchanged, and a real Codex coding session creates,
  executes, resumes and revises source that passes an independent answer check.
  Earlier passes before the private-launch correction do not establish this
  corrected path. Current verification records its host prerequisites; unrun
  checks remain explicitly unverified.

Reuse the shared test runner; do not add a separate replay mechanism. Target
Workflow environment preparation was excluded from this focused coding-launch
goal and is now addressed separately in [ADR 0010](../adr/0010-target-workflow-environments-follow-candidate-revisions.md).
This goal does not claim
full build/refine/Target Workflow acceptance or a live Claude Code result.

## Coding backends

`agent/refinement_coding.py` supplies a common session/result interface and
selects an implemented adapter for the owning Duet's pinned route. Native
authentication, session persistence, sandbox configuration and event translation
belong in the adapter. `agent/transports/refinement_codex.py` uses the existing
Codex app-server session. `agent/transports/refinement_claude.py` uses Claude
Code's streaming CLI. The Claude adapter is implemented but has not been
live-validated. Neither is silently substituted for the other. The Episode
repair loop and host admission are not specific to either backend.

The current Codex adapter uses the owning Duet's model, effort and explicit
credential. `model.codex_bin` selects the installed executable through the
existing configuration mechanism. Private native state lives beside the managed
coding workspaces, outside the source imported as a proposal. Session identity,
native evidence and activity are recorded in the shared campaign store.
No extra replay system is introduced.

## OpenChia-owned Codex launch

`scripts/openchia-codex` is the repository launcher. It passes arguments to the
installed Codex executable selected by OpenChia's existing `model.codex_bin`
setting. Its default configuration lives in
`openchia_cli/codex_runtime_home.py`; runtime configuration and native state live
under `<active OpenChia profile>/codex`, not the user's personal Codex home.
The app-server and migration use the same location rule. Implementer supplies
its own per-context state directory through that same launch implementation.
Migrated OpenChia tool callbacks also bind to the owning profile, including when
one host process serves multiple profiles; they do not use its launch profile.
Offline model discovery and the optional compaction evaluation's Codex launch
and rollout lookup use the same private-home resolver.

The launcher removes inherited `CODEX_*` variables from the child environment,
then sets the child's private `CODEX_HOME`. Parent thread IDs and permission
settings are not forwarded, and the parent environment is unchanged. It
initializes a missing private configuration from the checked-in workspace
permission default.
Existing private settings are preserved. No personal Codex configuration,
credentials or transcripts are automatically copied into the private home.
Implementer continues to receive its credential from the owning Duet. Standalone
use can authenticate separately with `scripts/openchia-codex login`.

Do not run global configuration migrations or automatically install machine
security profiles as a repair. A native sandbox startup failure must be
reported separately from model/API errors and unsuccessful implementation work.
It must not silently select unrestricted execution. No Target Workflow
environment is configured by this launcher.

## Native sandbox prerequisites

OpenChia uses the coding runtime's native sandbox, not a portable AppArmor
wrapper. The private configuration, scoped workspace and host acceptance rules
remain the same; the OS enforcement mechanism differs.

| Codex host | Native mechanism | OpenChia verification |
| --- | --- | --- |
| Linux | Bubblewrap and seccomp; some distributions also require an AppArmor policy permitting namespace setup | Live coding and confinement checks passed on Ubuntu 24.04 with the prerequisite below |
| macOS | Seatbelt through `sandbox-exec`; no AppArmor or bubblewrap | Not yet verified on macOS |
| Native Windows | Codex's Windows sandbox; the stronger `elevated` mode requires administrator-approved setup | Not yet verified on Windows |
| WSL2 | Linux sandbox and the Linux distribution's prerequisites; not the native Windows sandbox | Not yet verified in WSL2 |

These mechanisms are documented in [Codex security](https://learn.chatgpt.com/docs/agent-approvals-security).
For Windows, follow the [native sandbox setup](https://learn.chatgpt.com/docs/windows/windows-sandbox):
the stronger mode uses lower-privilege sandbox users, filesystem permissions and
firewall rules. "Elevated" describes setup authority, not unrestricted coding
commands. Its weaker mode has different network enforcement; it is not an
equivalent fallback to claim without validation. Windows setup must use
OpenChia's private native configuration, not the user's personal Codex settings.
WSL1 is not supported by current Codex. These are platform plans, not claims that
OpenChia's launch/bootstrap paths have passed on those hosts. Claude Code needs
its own native-backend verification; the Codex table does not validate it.

### Ubuntu 24.04: explicit AppArmor setup

This is an **administrator-run host prerequisite**, accepted for now. Do not
run these commands from an Implementer turn or automatically at launch. They
apply to Ubuntu 24.04 with AppArmor 4 and `/usr/bin/bwrap`, not macOS, native
Windows or every Linux distribution. If bubblewrap/AppArmor are absent, install
them explicitly using the distribution's package manager:

```bash
sudo apt-get update
sudo apt-get install bubblewrap apparmor
```

If the native sandbox already works, no additional profile is needed. When
kernel audit identifies AppArmor denying bubblewrap's namespace setup, obtain
Ubuntu's packaged profile without installing the whole `apparmor-profiles`
package (which would load unrelated profiles):

```bash
# Run in one shell; retain this directory for inspection.
apparmor_stage=$(mktemp -d)
cd "$apparmor_stage"
apt download apparmor-profiles
dpkg-deb --extract ./apparmor-profiles_*.deb extracted
apparmor_source="$apparmor_stage/extracted/usr/share/apparmor/extra-profiles/bwrap-userns-restrict"
less "$apparmor_source"
sudo aa-status
```

Before installing, review existing policy. Stop for administrator review if
`bwrap` or `unpriv_bwrap` is already loaded, if the destination below exists, or
if there are corresponding `disable`/`force-complain` entries or local overrides
(`local/bwrap-userns-restrict`, `local/unpriv_bwrap`) under `/etc/apparmor.d`.
Do not overwrite policy or remove those entries to force a successful launch.
For a first installation with no such conflict:

```bash
(
  set -eu
  test -f "$apparmor_source"
  test ! -e /etc/apparmor.d/bwrap-userns-restrict
  test ! -L /etc/apparmor.d/bwrap-userns-restrict
  sudo install -o root -g root -m 0644 "$apparmor_source" /etc/apparmor.d/bwrap-userns-restrict
  sudo apparmor_parser --add --skip-cache /etc/apparmor.d/bwrap-userns-restrict
)
```

If `--add` fails, setup is incomplete. Inspect the parser error and remove only
the file just created by this first-install block, after confirming it still
matches the extracted source and no administrator has replaced it. Do not leave
a failed installation eligible for boot-time loading or delete existing policy.

For an already installed, reviewed copy, compare it with the extracted source
using `cmp "$apparmor_source" /etc/apparmor.d/bwrap-userns-restrict`. Only if it
is identical and its local overrides/disabled status are understood, reload that
specific policy with
`sudo apparmor_parser --replace --skip-cache /etc/apparmor.d/bwrap-userns-restrict`.
Do not reload unrelated policies or disable the global user-namespace restriction.
The existing enabled AppArmor service loads `/etc/apparmor.d` at boot. A manually
copied extra profile is not automatically refreshed by package upgrades.

This policy affects `/usr/bin/bwrap` machine-wide. It permits sandbox construction
and denies capabilities in children; its packaged comments warn that this can
affect other bubblewrap uses. It does **not** itself define OpenChia's workspace
or network restrictions: Codex's native sandbox supplies those. The verified
package was `apparmor-profiles` version `4.0.1really4.0.1-0ubuntu0.24.04.8`;
profile SHA-256 was
`11d39094f044f0cda0febb3ad517b830301da6b2ce929664af09ee9e4dd264f9`.
Review a different package version rather than assuming it has the same policy.
After setup, use the shared live check below to verify actual coding ability.
This does not configure the Target Workflow's environment.

## Verification and continuation

Use the existing test runner for the opt-in real coding check:

```bash
scripts/run_tests.sh tests/iterative_episode_refiner/test_live_coding.py \
  -j 1 --file-timeout 1200 -- \
  --live-coding-profile=/absolute/path/to/the/owning/profile \
  --live-coding-binding=EXACT_SAVED_DUET_BINDING_ID -q -rP
```

This reads the selected saved model binding and credential without changing the
profile. The real coding agent must create and execute a scheduling solver, then
resume and revise it. An independent host oracle checks each result. Candidate
files and native state stay in the test runner's temporary workspace. Standard
pytest `--junitxml=PATH -o junit_logging=all` can retain the test receipt,
including commands and checked answers. This is capability verification, not
full Target Workflow acceptance.

Configuration-isolation checks exercise A → B → A profile switching, migration,
session ownership and the repository launcher. These are separate from actual
coding ability. The initial private-launch check on 2026-10-05 reached Codex
0.160.0, but both CLI and app-server command execution failed with
`bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted`. The legacy
sandbox option also refused filesystem-restricted execution.

The user subsequently requested restoration of the missing host configuration.
Only `/etc/apparmor.d/bwrap-userns-restrict` was restored from Ubuntu's packaged
profile and loaded. This is a **machine-wide prerequisite**, not repository
configuration or a change performed by the launcher. No package was installed,
the global user-namespace restriction remained enabled, and the personal Codex
configuration was unchanged. Through the existing app-server with private
`:workspace` defaults, workspace writes and Python execution then succeeded;
<!-- no-tmp: ok — names the sandbox's own in-container mount, not host scratch -->
writes outside the workspace (outside `/tmp`) and network socket creation failed.

On that repaired host the real private-launch coding check **passed** in 170.5
seconds, using the saved Duet binding for `gpt-5.6-sol` with high effort. Codex
created and executed `solve.py`, then resumed thread
`01a10e27-8cfe-7833-9bab-c432611806d4`, revised its validation code and executed it
again. Both answers passed the independent host oracle with optimal makespan
`14`. There was no manually supplied answer or workspace repair. The local
receipt is `/var/tmp/openchia-private-coding-receipt.fjdLmj/junit.xml`, SHA-256
`518f21e0b444e37ad9742cc4c72edb05391827428d9837b6a3f6ec68760704e1`.

This proves coding and native resumption with the documented host prerequisite.
It did not satisfy the original unchanged-host condition. On 2026-10-05 the user
accepted this prerequisite for now with explicit installation instructions, so
the result satisfies the revised focused goal. It is not evidence of operation
without that profile. No full Target Workflow or live Claude Code acceptance is
claimed.

The launcher test runs the real Python entry point and child process. Direct
execution through its standard repository `_hermes-python` shebang also passed:
`./scripts/openchia-codex --version` exited 0 with `codex-cli 0.160.0` and created
the private workspace-default configuration under the owning OpenChia profile.
The normal runtime-only PM activation refreshed the repository-managed
dependencies and activation stamps; no activation state was fabricated. This
is user-owned dependency setup, not a system package installation. The personal
Codex configuration, shell startup file, AppArmor profile and global namespace
setting were unchanged by this check.

In production, ordinary Run continuation reuses committed responses and resumes
unfinished coding state only after its prior owner has stopped. A changed
backend, model binding or instruction prefix opens a new native context.
Authoritative candidate revisions and measurements remain in the shared stores.
See [continuation](build_continuation.md) and [ADR 0009](../adr/0009-implementer-uses-an-existing-coding-agent.md).

Captured coding proposals are immutable `refinement.coding_proposal.v1`
artifacts. Model response and proposal control frames carry their references;
source files and control fixtures stay in the store. Proposal admission first
authenticates the committed model response, then resolves the exact artifact
bound to its campaign, invocation, unit, assignment, candidate and coding turn.
The ordinary validators consume the complete captured proposal. Rejection
feedback and within-invocation history resolve the same bytes, while child
reports keep their separate parent-selected format. Transport size limits and
measure adequacy requirements are unchanged.

When independent static verification encounters a rejected candidate with a
blocked mandatory check in its assigned contribution (for example, an absent
emitted module), it returns that exact source-admission receipt to its parent as
`needs_parent_decision`. The parent can commission the missing implementation.
Pass/fail determinations remain recorded; blocked checks for unrelated unfinished
parts do not obstruct an otherwise resolved static judgment. This is a missing-
prerequisite handoff, separate from numerical yield exhaustion or success.

On 2026-10-07, continued Run
`run_cbd0507d71889ef8b3aeba469d014b2e43bbf39d1b87f1336ad258d76f16300c`
matched 628 saved worker frames without divergence. Its first live Verify unit
returned `needs_parent_decision` for two blocked assigned static checks, retained
the source-admission receipt, and earned zero fresh credit. The parent Parts
invocation resumed at campaign sequence 1231. This verifies the blocked-source
handoff, not completion of the repaired workflow or its scientific outputs.

Reasoning calls retain their exact rendered messages in immutable
`refinement.reasoning_prompt.v1` artifacts, linked from the response route to
the original working-context reference, assignment, unit and candidate. During
check review, identical fixture source appears once in an inline
`shared_fixture_sources` catalog. Each fixture keeps its original paths and
references that exact text with `{shared_source: NAME}`. Every control, input,
materialization and rationale is retained. This lossless reasoning view avoids
repeating large helper modules across controls; stored definitions, native coding
workspaces, executable fixtures and parent-selected child reports are unchanged.
The host applies this rendering when resolving the working reference, including
an unanswered review call resumed through normal Run continuation.

## Measure's checking workspace

Measure and Measure Parts use this same native coding transport and owning Duet model
binding to implement task-specific checks. `MeasureWorkspace` stages its parent's
scoped source under `target/` and the original requirements, materialization and
review feedback in `.openchia-assignment.json`. Measure writes its program under
`checker/` and its proposal in `.openchia-measure.json`. Capture rejects target
edits and freezes the actual checker files; it does not create a target revision.

A program has `files` (relative path to source text in the persisted definition)
and `entrypoint` (`module:function`). The native workspace response names the
checker files; the host captures their bytes. The same proposal file can instead
select a declared child. Its checking function receives
`{source_root, materialization, input}` and returns JSON. Each case binds the
result at `/result` to a library predicate and supplies complete satisfactory
and violating fixtures `{files, materialization, input}`, with requirement-based
rationales. Existing predicates over verified Run observations remain available
with `program=null` and `input=null`.

Measure can author a focused subset of its commissioned requirements at a time
or delegate a smaller requirement scope to Measure Parts. Measure Parts retains
the exact commission and adequacy basis and can author checks directly or recurse
to a smaller requirement subset. A single requirement's checking cases are direct
work because the current assignment does not contain a separate case-slice grant.
`check_design.completed_requirements` identifies already adequate components.
Each subsequent proposal pins the exact component admissions it retains in
`components`; later work cannot silently change those references.
`compose_components=true` assembles admitted returned components without a dummy
check. Measure Parts retains scoped adequate work; only its owning Measure
publishes the complete reusable composite. Question's
review assignment covers the requirements of the current component.

Question reviews the exact program, original requirements, expected results,
fixtures and limitations in a separate invocation automatically scheduled by a
`check_design` proposal. For authored programs, both Measure and its Question
reviewer receive `checking_target_materialization`: the actual candidate-plan
value supplied to program execution. This distinguishes the host input shape
from synthetic fixture metadata; a fixture cannot establish that a host field
exists. Additional authority or lifecycle claims still require supported
observations. The reviewer also receives `checking_target_sources`, using the
same scoped candidate-source selection supplied to Measure. This lets it compare
actual candidate code with control implementations instead of inferring their
relationship from fixture names. Source similarity or difference alone does not
establish expected-result independence. Measure and Question receive
execution-binding choices
for that design's requested judgment purpose. Local, acceptance and composition
checks retain their separate purposes through admission and evaluation.
Returned reviews reach Measure at
`episode_request.assignment_context.child_reports[].return.check_review`, with
the report's `open_decisions`. The working-context `review_assigned` flag
identifies a Question review assignment; Measure consumes its child's report.
After that review returns,
Measure submits the frozen definition. The shared testing harness executes its
program against every control using the selected Run backend's isolated process
operation. The instrument declares its own dependencies in
`checker/.openchia-environment.json`, included in `program.files`. The existing
environment service prepares that recipe and records its resolved lock, runtime
and preparation evidence. This allows checking an incomplete target, including
one with a missing or broken environment recipe. Target and fixture environment
files are data under examination, not the checker's dependency declaration.
A checker without a recipe receives the standard library and frozen runtime
libraries. The backend supplies read-only inputs and prepared checker
dependencies, writable scratch and no network or profile credentials. The function
receives neither the expected verdict nor the control polarity. An import error
or process failure is an error, not a successful negative control.

Admission rechecks the reviewed definition and original execution receipts. Both
control polarities must discriminate correctly before checks become operative.
The admission record includes `requirement_results`: one row for every commissioned
requirement, with case-level outcomes, reasons and matched/required control
counts. `pass` means the instrument matched its controls; `fail` means an
executed control returned the wrong polarity; `error` means the checker or its
evidence could not be evaluated; `blocked` means required execution evidence is
unavailable. These are instrument-adequacy results, distinct from the Target
Workflow's measured outcomes. Admission examines the other cases even when one
case fails, retaining completed components in a `partial` admission. Its check
records remain private construction work until the whole commissioned composite
is `admitted`. A proposal with no adequate components is `rejected`. Measure receives
this breakdown in `instrument_admission`; parents requesting
`measurement_findings` or `open_decisions` receive the same requirement-level
diagnostics through their declared return contract. Each requirement whose full
set of cases passes earns one instrument-adequacy achievement, even when other
requirements still need repair. Repeating that achievement during the same
commissioned revision earns no new credit. Publication of the composite waits
for the requested instrument to be ready; target-improvement credit is measured
separately by applying the published function to the Target Workflow.
Each assessment pins its available control evidence in `control_snapshot`.
Revalidation uses those same receipts even after later units execute more
controls. Independent-execution controls publish updated readiness after each
returned experiment, so completed requirements can contribute before all other
controls have run.

An unsuccessful admission supplies Measure with repair feedback for its next
unit. Measure continues under its numerical controller while it revises its
own checks. An explicit prerequisite request returns missing observation or
execution authority to the parent through the existing ownership boundary.

An admitted record also contains `measurement_function`, a serialized
`RequirementMeasure` from `function_library/materialization_progress.py`. It
binds the registered requirement-satisfaction function to the parent's captured
requirement/check mapping, replacing only the explicitly requested requirements.
Unchanged checks retain their original identities and executable bindings.
Reopening that binding preserves its
membership and numerical rule. Calls provide admitted observations for an exact
candidate, an optional declared requirement scope, and the caller's credited and
previously satisfied requirement identities. The result lists individual check
and requirement outcomes, current satisfaction, fresh progress and regressions.
Repeated passing evidence earns no additional progress when the credited
identities are carried forward. Missing observations remain `not_checked`.
Admission re-derives this binding from the reviewed proposal, retained component
admissions and pinned control evidence. A partial or rejected admission carries
diagnostics and no operative measurement function. Retained components preserve
their original executable bindings, review evidence and limitations.
The admission diagnostics use this same requirement aggregation with the
proposed instrument, rather than the Target Workflow, as the evaluated candidate.

A parent selects the composite returned by its explicitly commissioned Measure
child. Its subsequent child assignments freeze that function. Evaluation,
requirement-level credit, and compact outcome reports resolve this same
membership; publication of an unrelated checker does not enlarge it. Measure
and Implementer remain separate children of their coordinating parent.

One fully satisfied requirement is one achievement, regardless of how many
assertions its component checks contain. Unit receipts record the selected
function and numerical lineage. Same-function continuations retain their credit
history; a requested revision starts a separate measurement history and evaluates
the commissioned baseline candidate under the revised function. Baseline passes
are excluded from new implementation credit. Original observations and older
receipts remain available for inspection.

Candidate checks use the same program on the current scoped source and plan;
the entire Target Workflow need not be runnable. Observations enter the existing
measurement ledger, dependency invalidation, parent judgment and numerical credit
path. Coding diagnostics and review prose are not measured success.

Immutable `experiment.checker_inputs.v1` and `experiment.checker_execution.v1`
artifacts retain code, inputs, environment/runtime identity, runner hash, process
status and stdout/stderr blob references. `refinement.checker_result.v1` links
them to the exact invocation/unit and control or candidate/check. Measure receives
current control outcomes and errors in its working context. Final publication
rechecks the original receipts rather than running controls again.

Controls demonstrate discrimination on those examples, not universal correctness.
Checking code uses its own declared dependencies and cannot acquire external
data or model access during execution. Importing target functions in that
environment is a local check; verification of the Target Workflow's own runtime
still uses its declared environment through the shared Run harness. A requirement
needing a different approved instrument or evidence source remains explicit.
Checker source imports stay in the isolated backend, never the host process.

On 2026-10-06, four real systemd-backed instrument executions checked this
environment boundary. An undeclared NumPy import produced a recorded error.
Declaring `numpy>=2.0,<3` in the instrument recipe resolved NumPy 2.5.3 and
allowed the same checker to execute with either a missing or malformed target
recipe. A defective target value produced `false` through the same instrument.
These are environment/execution checks, not Target Workflow acceptance. Their
`experiment.checker_inputs.v1` subjects use
`verification: checker_owned_environment` in the existing authority store.
The successful missing-target-recipe execution is
`experiment_data_abdb33a6572651bf2ef070cd82adf878975fe10e72c04a8769cd9b70f45243f0`;
the defective-input execution is
`experiment_data_be2acbd41f40eef5924efbd7699b8b60df370fa9259f0257f8b61418f0f59bd4`.
