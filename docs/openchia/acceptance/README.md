# Scheduling acceptance — Measure admitted; Target Workflow acceptance pending

Latest status, 2026-10-04 17:11 UTC: the normal `OpenChiaHost.continue_build()`
entry has started successor Run
`run_008d375611c64c57edfacec3913c172094ce2b07e1a2a95389bcbc734534a45f`
for the same saved job and experiment. Event 2 records 479 matched worker frames,
zero remaining frames and no divergence, with the original root → Designer →
Measure stack restored. Event 3 reissues the exact unanswered Measure request:
its request hash matches the predecessor's pending request. Event 4 now contains
the completed 63,662-character model response. It is malformed JSON at character
9,509, in the nested event-provenance condition, and was rejected for zero credit.
This is the seventh consecutive malformed revision after the same independent
review. Event 14 is OpenChia's automatic next Measure request, carrying the exact
rejected response and parse error. Response 15 then produced valid JSON: 154,207
characters and twelve cases. Host response 17 authorized a separate Question
reviewer; response 30 judged all five design criteria satisfied. Measure response
51 selected that exact reviewed definition. Host event 55 records admission:
all 33 executable controls matched their expected outcomes (13 positive and
20 negative). Event 58 records twelve newly credited measurement facts and
Measure's `attained` return. Event 71 is Designer's next model request to resume
source repair, carrying the admitted measure. All of these transitions occurred
inside the same OpenChia job without manual stage dispatch. This establishes
measure construction, review, control execution and host admission, not an
executed or accepted Target Workflow. The same owner remains live.

Follow-up at 17:17 UTC: Designer's plan reached Implementer, but its required
baseline evaluation returned `launch_input_invalid`: the candidate has no
materialized root launch interface. Implementer returned without a model edit.
The independent Verify child recorded the rejected source and missing acceptance
coverage. Designer received both exact decisions and proposed a replacement
Implementer plan in response 127. The job remains active. The evaluation
preflight and source-admission visibility need examination; no repair to the
harness or candidate has been applied to the running checkout.

Follow-up at 17:23 UTC: the replacement Implementer repeated the same failure
at event 140. Its context at 136 had `baseline_required: true` and no visible
source admissions, although Verify had already recorded a rejected build of
the same candidate with the same harness and capability. The development
checkout now shares that source-admission evidence across measures under those
exact identities. It does not share test verdicts or credit. Python syntax and
whitespace checks pass; the correction is not live-validated or applied to this
Run. Designer response 182 proposes another static-first implementation plan;
no model editing call, changed candidate or Target Workflow Run is established.

Continuation also completed the cancelled Run's missing terminal-evidence
publication, preserving its 866 events and `cancelled` status. The pinned host
source is `b6ae19fe9625c70d65df72003c003d744404ff8c`; later audit-read and
health-transport revisions are not applied to this running checkout. The saved
model binding predates health policies, so exact restoration leaves probing
disabled for this continuation.

Reading the actual prompt and output shows that the parent assigned all twelve
behavioral requirements together; check-design admission requires exactly that
set. The input is 391,195 characters across its system/user messages, not a
measured token count. The revisions address real review findings (request hashes,
final-receipt selection and admitted-transition linkage), but regenerate the
whole check bundle. The malformed revision applied the optimality predicate to
every retained answer to check JSON field encoding, expressly acknowledging that
this is stricter than the frozen first-answer correctness criterion. Valid
response 15 removes that stronger condition and explicitly retains the gap in
checking later answers' encoded field formats. It also retains the limitation
that the predicate does not certify the explanation's mathematical validity. These are
system-interface findings, not evidence that the Target Workflow has failed its
scheduling task. Generic JSON decoding has now been prepared in the development
checkout's shared record-condition predicate so representation and correctness
can be tested separately. It is not active in this Run, does not repair malformed
proposal JSON, and does not solve the broad assignment/revision problem.

Predecessor status: the user requested cancellation after model call 48
remained unanswered. The Run is durably `cancelled` at event 865 (866 events;
48 model requests, 47 responses). The exact systemd worker is inactive. Caller
cleanup did not finish normally; after stopping that worker, the caller required
SIGTERM and exited 143. A finalized build-job result is not confirmed. No
replacement had started at cancellation. Continuation and model-call health
recovery are separate changes; neither is demonstrated by the cancelled Run.
There is no acceptance pass.

Attempt history, 2026-10-04: one normal `OpenChiaHost.start_build` started
`build_request_f909ff82826ee4882064ba7b425d83278be6ca9aafc6d6e5bd38a45ad9f0613d`
after the preceding Run and caller cleanup finished. Builder reported two
findings, with zero Episodes planned or modules emitted: `planning_failed`
because `prompt_specs[0].response_contract` was an object instead of nonempty
text, and `missing_module`. The committed model response contains JSON-schema
objects in both prompt response-contract fields; this is a plan-format failure,
not evidence that the approved scheduling problem lacks a solution. The same
start automatically entered native Run
`run_358b0b188f2732c49a60c6d304d8309705e611b325cd6c822d0ad771a1347edf`.
It entered refinement. A 49,474-character check-design response failed JSON parsing;
the following repair context contains that exact rejected output, marked
`admitted: false`, and the parse error. Automatic repair response 64 produced
valid JSON with twelve cases and nine `parent_path` operands. Host 66 accepted
the proposal and assigned a separate Question reviewer. Review 79 rejected
cross-record, provenance and coverage gaps; its control-polarity criterion
passed, not executable controls. Measure returned a grounding need. The root
then assigned Designer implementation across all sixteen requirements; Designer
requested local Measure checks for all twelve behavioral requirements. Review
166 rejected all five criteria in the next local design. Its grounding need
returned through Designer to the root, which assigned a successor carrying both
prior prerequisites. Designer 267 then requested eleven uncovered local checks
with the review findings, keeping schedule correctness independent. Its next
four responses were malformed JSON and rejected for zero credit despite exact
rejected-output feedback. The same grounding need returned to the parent. An
explicit implementation assignment produced another plan, rejected for unresolved
measurement coverage; the next Measure returned the same need again. A replacement
Designer request was rejected for prerequisite-routing authority, then accepted
after `prerequisite_refs` were removed. The replacement requested another Measure,
whose first two responses were malformed JSON. Response 560 reached independent
review, which rejected four criteria. Measure then directly revised it into
valid proposal 596; review 611 again rejected four criteria. Measure then proposed
design 632 with sequence ordering, exact evidence arrays and no every-answer
optimality requirement, while explicitly lacking a check for later JSON-valued
strings. Review 647 rejected four criteria; only explicit limitations received
a favorable criterion result. The same grounding need returned through Designer,
and root verification reported `needs_parent_decision`. Parts then assigned a
replacement Designer the same broad sixteen requirements with a source-repair
instruction; Designer again requested Measure for all twelve behavioral
requirements. Both assignments had empty `prerequisite_refs`. Event 761 confirms
that this repeated scope's check-design context contained zero definitions and
zero reviews; it does not establish that all other history was absent. Design
763 reached review, which rejected four criteria. Six subsequent repair responses
were malformed and rejected. Before cancellation, the Run reached event 864 with
48 requests, 47 responses and call 48 pending. This was unresolved iteration,
not accepted progress.
At 2026-10-04 14:04:55 UTC, read-only inspection confirmed the model-call thread
was waiting for network data, not a host database lock, with no incoming bytes for
about thirty minutes. The pinned transport has no fallback deadline when
`request.timeout` is `None`. At that observation the call was pending; no
cancellation, restart, source edit or extra test had yet been performed.
The subsequent cancellation is recorded above. No measure was admitted, source repaired, or Target
Workflow experiment run; there is no acceptance pass. Generic `parse_json` and
guidance separating immediate child contribution from whole-parent acceptance,
and bounded, scoped retrieval of prior review findings were initially prepared
across four files in a separate repair checkout. Historical findings are not current
admission. The JSON-decoding addition is now also in the development checkout;
the other three changes remain unintegrated. None is active or demonstrated in
this Run; no gate, credit or criterion in the Run is changed.
The approved Target Workflow and model configuration are unchanged. No candidate
edits, check expectations or thresholds were supplied manually. Only Ruff and
whitespace checks preceded the new real cycle; no tests were run.

The preceding complete `OpenChiaHost.start_build` was launched
for `build_request_44c60f4b7983c56b0d8e1aee74e7fba31ee462705326648a6070b4479b134e15`
after the preceding job ended naturally. The Builder reported two blocking
findings, with zero Episodes planned or modules emitted; their exact diagnoses
are not yet recorded here. OpenChia automatically entered native refinement Run
`run_d4fb3c68de969ebf3665a095e7db80871f4bdd40c2f40a1cf008fc7d9c4cc440`.
It is now operator-cancelled. Two malformed definitions received exact JSON error feedback
and automatic retries; a valid twelve-case definition reached independent review,
which rejected all five criteria with eight counterexamples. Measure then
requested grounding. The forwarded prerequisite retained its prior review in
both Designer and root Parts context. A successor Measure then received the full
prior check definition and matching review, not merely a review projection.
This demonstrates precise parse feedback and complete check-review handoff,
not accepted refinement progress. The Run subsequently repeated the same
measurement prerequisite through several assignments. An implementation plan
failed for unresolved measurement coverage; a schedule-only measure was rejected
because it changed the parent's requested judgment. Designer plan 454 was again
rejected at 456 for unresolved coverage. The operator explicitly cancelled the
owning caller to apply two generic corrections: support for the cross-event joins
required by review, and inclusion of rejected output in the next repair context.
Those corrections were prepared in a separate repair checkout and applied only
after this Run became terminal and its worker became inactive; they were not
part of this Run.

The native audit records `cancelled`, with 471 events, fourteen invocations
started, twelve completed, 23 model requests, 23 responses and 26 completed
units. There were no candidate source changes, admitted check, Target Workflow
experiment or acceptance pass. This was not spontaneous termination or normal
completion. Host cleanup finished with caller exit 130, and the durable
build-job result records `cancelled`. The static source repair below belongs to
an older Run.
Only Ruff and whitespace checks preceded this
real cycle; no fixture tests establish these claims.
Source and unchanged Duet/Target Workflow launch settings are recorded in
[setup_inputs.json](setup_inputs.json).

The preceding ordinary build entry was called once for
`build_request_5d4dfc269a03557e03b9d133b17030361ecfc94ba660a7ce5c9e7c8b57661b82`
after the preceding job's cancellation cleanup finished. Builder was blocked
by the missing non-empty goal response contract and missing module, with zero
Episodes planned or modules emitted. OpenChia automatically entered refinement.
In native Run
`run_54f753918b59985e8e813c1c70c176407402541608671d66b28f3c9b47536e31`,
the root assigned Designer, which called Measure for twelve behavioral
requirements. Separate review rejected five criteria in its first definition;
the revision was malformed JSON. Measure then requested grounding, and Designer
successfully forwarded that exact prerequisite to its parent. A successor
Designer and Measure returned the same need. The Run then ended naturally:
event 305 recorded `run_failed` / `LaunchModelError`. The final provider receipt
records `RemoteProtocolError`, categorized as a retryable timeout with no HTTP
status, after 246.66655 seconds. This was not an operator stop. The native audit
contains 306 events, eleven invocations started, eight completed, fifteen units,
fourteen model requests and thirteen responses. The caller exited 0 while the
build reported `host_error`; process exit alone is not build success. Exact
prerequisite propagation was demonstrated, not resolution. No Implementer,
Target Workflow experiment, accepted repair or acceptance pass occurred.

The preceding attempt used the same ordinary build entry,
called once for
`build_request_1e10de051dbb0065aba05bbd1f4e47b7554bdbdea6c31a60b27f704a1f1da72b`
after correcting the observation catalog and child-prerequisite forwarding
described below. The initial Builder attempt was blocked: the goal's
`prompt_specs[0].response_contract` was not non-empty text, and its module was
missing; no Episode was planned or emitted. OpenChia automatically transitioned
to refinement without a second start. Native Run
`run_d2c7d6667c1d34664cef783f6127803114823e928ad60115621d24776e52306b`
was operator-cancelled after five consecutive exact-before edit rejections.
Its source is `9b5d11574a` plus the production changes retained in its historical
[setup record](setup_inputs.json). Validation proceeds through the real
OpenChia cycle only; the supplied-response compatibility run was stopped without
a passing nested result. No candidate answer or repair was supplied by the
operator, and this Run's frozen contract was not changed.

The refiner corrected an invalid cross-role request and reached Designer and
Implementer. Implementer response 86 authored source and a new node plan, committed
by the host at 88; source admission at 90 rejected `module_exports_incomplete` and
`request_payload_binding_mismatch`. The next five edits failed the exact-before
comparison. Their only mismatches were `/prompt_specs/0/prompt_template` and
`/prompt_specs/1/prompt_template`: stored literal backslash-n versus newline
characters in the model's copied value. The exact current value was available
in `permitted_detail_edits`, but feedback named no mismatching path. A legal
repair remained available; this was not an impossible assignment.

The operator sent SIGINT to the exact owning API caller, invoking `host.close`.
The native Run durably recorded `cancelled`: 155 events, four invocations started,
one completed, ten completed units, ten model requests and nine responses.
There were no Target Workflow experiments or accepted repair. Host cleanup
finished with caller exit 130. The durable `build_job_result` is `cancelled`
with `error: null`; the native cancellation and job finalization are both
recorded. The next correction gives generic first-mismatch diagnostics
without relaxing the exact-before check or criteria, and without supplying a
candidate patch or task answer. Its live behavior remains unverified.

The preceding `456490d7...` job reached real check design: model response 53
proposed a concrete measure, and the separate reviewer at 68 rejected incorrect
event, result and route paths. Later plans still lacked measurement coverage;
Measure returned `grounding_required`, and a Question request lacked its parent
decision criteria. The model repeated these routes, although narrower Measure
assignments remained legal. This is not evidence that all routes were impossible.
No Implementer, source edit or Target Workflow experiment occurred.

The operator cancelled the exact owning API caller through SIGINT and its normal
`host.close` cleanup. Native Run
`run_02fc56cd8e6a9ab4307626bdaa61c8ad25a477142c9a06412e0c883e22139d62`
ended `cancelled` with 264 events, seven invocations started, five completed,
16 completed units, 16 model requests and 15 responses. The existing records API
confirms a durable build-job result of `cancelled`, with `error: null` and no
verified build. This was an operator cancellation, not spontaneous failure,
normal completion or acceptance. Exact references are in the setup record and
[receipt log](../unified_episode_test_harness_receipts.md).

The earlier `035fb766...` job demonstrated an actual autonomous source repair.
Its initial receipt
`build_receipt_6eb917a56de2c1de51d81c10dc7e49681c9f1e047acbef1ef71da45166f4e887`
reported a dynamic `FunctionImplementation.module` declaration. In native Run
`run_95413180114272f4be3a401b2bb8fc68d6f5e6a1d71bc9ab88b74f4850caa653`,
model response 108 supplied the source repair, host response 112 admitted it,
and response 114 recorded Implementer attainment. Independent static verification
followed at 135, Designer attainment at 143, and enclosing Parts attainment at
170. No operator supplied the patch. This proves the static repair loop, not
correct scheduling behavior: no Target Workflow experiment occurred.

Measure responses 223, 292 and 328 returned `grounding_required` without trying
the authorized reviewed-design route. Its instructions unconditionally required
that return for missing grounding while also permitting check construction.
The operator cancelled the exact owning API caller through SIGINT and its normal
`host.close` / `cancel_build` cleanup before applying the guidance correction.
The native Run is durably `cancelled` with 347 events, eleven invocations started
and 21 completed units. Its fifteen model request/response events are not a
count of successful generations. Host cleanup subsequently logged
`build_host_failure` / `ProcessLookupError`; no build-job result was published.
The cleanup race remains undiagnosed, so this is not a clean job-cancellation
receipt or an acceptance pass. The native cancellation evidence remains intact.

The earlier `ffe29aa6...` job's initial Builder receipt
`build_receipt_11adf93b59457a7fa4d069fe0696d92a18b27b0a04e8794168ab50f9c4be0c6a`
reported two deficits: the generated goal binding did not use the required
pre-emission `definition_id: "generated"`, and its module was missing. No node
was planned or emitted. OpenChia automatically entered native refiner Run
`run_63b71197c62147612cf587e1553b1f9ee67d2e6beaa0a5ebfc6e175f3712ece1`.
After baseline evaluation and a `grounding_required` return, the parent continued
through nested Parts to Designer and Implementer. The first source candidate
failed admission on the original node-plan error. The frozen normal-build policy
omitted `materialization_edit_targets`; neither a source-only edit nor ancestor
reassignment could repair the missing node plan. Three Question requests were
also rejected because ordinary investigation definitions were unavailable.

After confirming that host policy gap, the operator sent SIGINT to the exact
owning API caller. Its normal cleanup called `host.close` / `cancel_build`.
Both the Run and build-job result are durably `cancelled`, with no build error
or verified build; the caller exited 130. The Run retained 238 events, nine
invocations started and eleven completed units. Its fifteen model request/response
events include cancellation responses and are not fifteen successful generations.
No Target Workflow validation Run or accepted repair occurred. This was an
operator cancellation to correct the system, not spontaneous failure or normal
completion. Exact attempt, campaign and experiment references are preserved in
the setup record.

The preceding job,
`build_request_e9da37ab659fd8b8e008e7dcfd4c93fbbf2e80d4a5c19ac6e3809af8e970628e`,
automatically reached live check design and separate review. Its Measure child
needed checks for 12 contract fields, but the bound harness exposed only terminal
answer data. The child proposed nonexistent `host_measurement_v1` through
`host_measurement_v5` fields; four reviews rejected its designs. After confirming
the host observation defect, the operator stopped that exact worker so it could
be corrected. The job ended `host_error`, and Run
`run_fcb9d467c5e088ba3a5b479ff3ac1172902cd499bc041ef4419fab8e57856c94`
ended `failed`, with 236 events and 13 model responses. Its `ConnectionResetError`
followed the operator stop; it was not a spontaneous transport failure. No
Implementer, Target Workflow validation Run or candidate repair occurred.

Two earlier attempts are also preserved. The `3c01f105...` job admitted the
initial module and entered refinement automatically, but assigned Measure the
wrong immutable local metric. Its exact worker was stopped to fix assignment
admission; the Run ended `failed` with 88 events. The intervening `8d509acd...`
job ended naturally on a provider `APIError`, without an operator stop or an
established provider root cause. Neither is an acceptance pass. Full identities
and observed limits are retained in the setup record and
[receipt log](../unified_episode_test_harness_receipts.md).

Previous attempt, 2026-10-03: the ordinary `OpenChiaHost.start_build` entry was
called once from `9b5d11574a`, retaining the owning Duet's `gpt-5.6-sol-900k`
route with `xhigh` effort and the separate approved Target Workflow launch.
The initial Builder receipt had two deficits. OpenChia automatically entered
native refinement; the job then ended with
`DuetNotFoundError: no admitted measure_need with that key`. No accepted repair,
Target Workflow execution or verified build is established by this attempt.
The Run is durably `failed`: an unrelated artifact in `prerequisite_refs`
triggered an unhandled host lookup error instead of proposal feedback. The
system correction is being exercised by the current real job. Exact references are in the
[receipt log](../unified_episode_test_harness_receipts.md#live-one-start-attempt-after-reviewed-check-design-2026-10-03).

Previous attempt, 2026-10-03: the ordinary `OpenChiaHost.start_build` entry was
called once from commit `7222da1a21`, with a fully initialized owning Duet using
its configured `gpt-5.6-sol-900k` route and `xhigh` reasoning effort. The Target
Workflow retains its separate approved launch file. The initial Builder attempt
failed source planning; OpenChia automatically entered the shipped refiner in a
native systemd worker. No operator launched that next stage or repaired its code.
The refiner corrected an invalid subdivision and reached Designer, whose plan
was rejected for incomplete measurement coverage. Designer called EstablishMeasure;
that child returned `grounding_required` for five requested contract fields.
The frozen normal-build policy supplied no applicable construction or acquisition
route. The development run was cancelled before changing the system. Both the
job and native Run record `cancelled`, with no verified build. No accepted repair
or Target Workflow execution is claimed.

The previous job from `899ff4a220` was cancelled to correct a host feedback defect: two Designer plans
covered all assigned contribution keys but included a preservation-only key.
Both received the misleading rejection "plan must cover the assigned contribution."
The cancelled job has no verified build. This is not a completed repair or
acceptance receipt; no operator edited its candidate.
The cancelled jobs are retained in [setup_inputs.json](setup_inputs.json) and
the receipt log. Earlier failed attempts below are historical evidence, not the
latest job's status.

The human approved the exact scheduling Target Workflow and designated launch
configuration on 2026-10-03. Their hashes and actual approval/store references
are recorded in [setup_inputs.json](setup_inputs.json). The ordinary host recorded
the approvals in a separate workspace and started real Builder calls. The testing
Episode is not yet approved. These files describe setup; the authority store,
Builder receipts and Run records are the authoritative evidence. The first build
ended **blocked**, with no emitted module and no Target Workflow Run.
See the [live-build receipt](../unified_episode_test_harness_receipts.md#approved-live-build-first-attempt-blocked-2026-10-03).

The acceptance workspace is `/home/chia/repos/OpenChia-acceptance-0RN3r9BH`.
It is a private record directory, not another code checkout or a custom runner.
Existing user Duets and the secondary checkout are unchanged. The target blueprint
is now approved and must not be silently edited; a changed design needs new approval.

The **Target Workflow** here is the scheduling workflow, not the testing Episode
or IterativeEpisodeRefiner. Each acceptance Run explicitly selects and records
its existing execution backend, with no silent fallback. Container and systemd
execution share this harness and its task criteria; see
[ADR 0005](../../adr/0005-target-workflow-execution-backends.md). The container
default change remains pending. The systemd setup failures are resolved on this
host, and native worker checks pass. Live-model acceptance is not yet established.

- [schedule_target.blueprint.json](schedule_target.blueprint.json) is one complete
  Architecture blueprint for the existing `reasoning.generic` reference.
- [setup_inputs.json](setup_inputs.json) names the real model slots and known
  measurement contract. Its `null` fields are unresolved setup inputs, not valid
  artifact references. This checklist is not an ExperimentSpec or TestingContract.

## What this live study must establish about OpenChia

The scheduling task exercises the system, not a hand-repaired demonstration.
For each failure, inspect the supplied prompt, required return and host check
together. Distinguish a candidate mistake that the existing loop can repair
from missing information or an unavailable operation in that loop. Do not fill
the latter by manually supplying this benchmark's design, code or answers.

Current system-level findings:

- Builder admission requires exact registered controller composer/credit
  bindings, but the planning input did not identify those fixed selections.
  The live attempts produced mismatches, including a parent asking Designer to
  use the continuation predicate as the composer. Builder and scoped refiner
  repair now install the same host-owned selections and expose them in planning
  context. Focused integration checks pass; the live correction is unverified.
- The plan-mapping check required exact contribution keys while its rejection
  did not distinguish omissions from preservation-only extras. This is fixed
  without relaxing the check; live recovery after the fix remains to be observed.
- The cancelled normal-build campaign created 12 contract-coverage requirements in addition
  to five static requirements. Its registered grounding currently covers only
  the scheduling goal, and it supplies no instrument-building or acquisition
  route for the other coverage requirements. EstablishMeasure can compose
  available cases, but could not construct those missing definitions from that
  setup. The deficit was in the system's preparation/construction interface,
  not a request for the operator to pre-author eleven benchmark-specific tests.
- The proposal format advertised `approved_review`, which its admission route
  rejects. The format now lists only the two implemented oracle kinds. This
  removes an unusable oracle kind. The separately implemented reviewed-definition
  route below still admits an ordinary `registered_predicate` measure; it does
  not make `approved_review` an executable oracle.
- The live check-design loop exposed an observation-contract gap: Measure was
  assigned execution requirements while its harness supplied only terminal
  answer fields. A proposed schema could not create the missing host evidence.
  The current correction uses shared `verified_run` records and provenance,
  discoverable supported observation roots, the executable `record_conditions`
  predicate, early selector validation, and a missing-grounding fallback.
  Syntax and Ruff checks alone have been performed for this correction; the
  current real one-start job must establish its behavior. No frozen active Run
  or criterion was rewritten, and no operator supplied the missing test answers.
- The next live attempt reached Implementer but could not repair its missing
  node plan because normal-build preparation omitted the existing detail-edit
  targets. The minimal `build_entry.py` correction derives `node_plan` targets
  from the approved baseline specification, including nodes whose planning
  failed. It grants no frozen-contract, topology or new-node changes. The fix
  was prepared and linted in a separate worktree before the old job was cancelled;
  only the new job receives it. No operator supplied a Target Workflow repair,
  and live acceptance remains unverified.
- The `035fb766...` job independently repaired and statically verified its
  generated source, but three Measure children then repeated the same missing-
  grounding return. The API already allowed reviewed design; conflicting
  instructions told the child to return whenever prewritten grounding was absent.
  The current guidance distinguishes missing prewritten cases from genuinely
  missing evidence or authority and requires considering the reviewed-design
  route. Separate review and executable controls are unchanged. The correction
  was prepared in a separate worktree, then applied after cancellation. Ruff and
  whitespace checks passed; no fixture tests were run. Its behavior remains for
  the new real one-start job to establish.
- The `456490d7...` job used the reviewed-design route, but its first design
  selected incorrect event, result and route paths. The observation catalog now
  describes the actual learning/model record schemas and receipt result paths.
  Designer and nested Parts can forward an exact returned child measurement
  prerequisite through the existing `propose_measure` operation and parent
  report, with independent host and store validation. This does not add a new
  credit or stopping rule. The new real one-start job must establish whether
  these corrections enable progress; no supplied-response tests or manually
  authored candidate repairs establish that claim.

The first-time definition gap now has an implemented route: Measure proposes a
typed check, a separate Question child reviews its requirement interpretation
and controls, and host admission executes those controls before installing any
check. The user approved this policy under the initial job grant. Two integration
cases pass: a real exhaustive scheduling predicate admits a reviewed valid
instrument; a mislabeled positive control is rejected despite favorable review.
Neither drafting nor review earns credit, and neither case claims live model
or native-worker acceptance. New executable checker-code construction is not
established by this route. Later live attempts reached separate check reviews,
but their rejected definitions and host limitations do not establish a completed
check-design/review/control admission or behavioral acceptance. The separate
static source repair described above does not discharge those requirements.

Minimum information to trace across each nested assignment: the original
requirement, contribution and preservation scope, what observation would support
or falsify it, how the measuring instrument is established and checked, and an
available next operation when one of those inputs is missing. Fixed host facts
should not become model-authored guesses. A declared return option must have an
implemented admission route. Rejection must identify the exact missing or
inconsistent part. Use the existing contract, shared harness and records for
these connections; do not introduce another runner or a fixed test sequence.

These are implementation findings, not grounds to waive a requirement or call
an unverified build complete. The preserved cancelled run is evidence of the
gap. A fresh live attempt must use a coherent system correction; manually
authoring its missing tests or executing individual repair stages would not
establish the requested one-start cycle.

## Target design and review choices

The single root `schedule_reasoner` solves the existing seven-job problem with
two workers and one laser. The exact task and constraints appear both in its
goal and its approved evidence. The independent solver's answer is not included.

The repeated unit chooses `solve`, `verify`, or `revise`. It uses the ordinary
reasoning source, host learning admission, result projection and controller.
There are no children, repeatable calls, external HTTP capabilities or testing
capabilities. Lessons remain Episode-local and advisory.

The reference uses `reasoning` for selection and execution. The designated
launch file also offers `fast` and `non_reasoning`; this draft does not select
either. Builder planning and emission use `reasoning`. Confirm those exact
bindings in the materialized specification before execution. Target/tester
launch settings never configure the IterativeEpisodeRefiner, which uses its
owning Duet's configuration.

Numerical control is frozen to the reference's paired-incidence rarefaction
(`uncertainty_alpha: 0.05`) and predicted-credit upper-bound continuation
(`max_predicted_marginal_hypervolume: 0.01`). This is not the older acceptance
run's substituted `0.9` threshold. There is no semantic turn or time budget and
no promised call count; an operational interruption is not normal completion.

Answers have three string-valued fields: `schedule` (JSON-encoded job starts),
`makespan` (integer text), and `optimality_argument`. The registered
`refinement_checks.optimal_resource_schedule_v1` measure checks feasibility,
truthful makespan and optimality by exhaustive enumeration. It accepts different
optimal schedules. Explanation text remains inspectable but is not certified
as a mathematical proof. Target learning credit does not itself establish
correctness.

The proposed measure addresses the **first admitted frontier answer**, using
`/workflow_result/result/admitted_problem_frontier/0/body/fields`. An empty
frontier cannot establish success. This is not an all-frontier check. Changing
the projection or the threshold requires review before approval.

## Local validation only

From the repository's prepared Python environment, this parses the ordinary
blueprint/spec and resolves its reference without opening any stores:

```bash
python -B - <<'PY'
import json
from pathlib import Path
from agent.episode_blueprints import workflow_spec_from_blueprint
from episode_library import episode_library

path = Path("docs/openchia/acceptance/schedule_target.blueprint.json")
workflow = workflow_spec_from_blueprint(json.loads(path.read_text(encoding="utf-8")))
for node in workflow.episodes:
    episode_library.resolve(node.episode_reference.episode_id)
print({"structurally_valid": True, "approval_checked": False,
       "workflow_hash": workflow.workflow_hash.value})
PY
```

This validation does not query approval. It is not Builder admission, correct
reasoning or a live test.
If registered definitions change, resolve and review the draft again; do not
silently substitute new IDs.

## Human setup and approval sequence

1. Select one existing OpenChia home/store set for this acceptance work and record
   its paths in `setup_inputs.json`. Do not silently combine the default home
   with the old worktree-local home. Create a new target Duet rather than
   replacing an unrelated approved workflow, for example with
   `/bg new Prepare the seven-job scheduling acceptance Target Workflow Architecture`.
   Supply the complete blueprint JSON as Architecture input to that Duet;
   naming this file alone is not an import command.
2. Review the exact resulting Architecture with `/bg TARGET_DUET_ID episode`
   (and `episode edit` if needed). The human records the Architecture decision
   with `/bg TARGET_DUET_ID approve`. Do not simulate this step by inserting
   approval records or using test-fixture helpers.
3. Configure that target Duet through the existing commands:

   ```text
   /bg TARGET_DUET_ID launch load /home/chia/repos/OpenChia-iterative-refiner/launch_default.json
   /bg TARGET_DUET_ID launch preview
   /bg TARGET_DUET_ID launch approve HASH_FROM_THIS_PREVIEW
   /bg TARGET_DUET_ID build
   /bg TARGET_DUET_ID build status
   ```

   Launch approval is separate from Architecture approval. The file contains
   routing and credential references; keep credential values out of these
   documents and all child inputs. Continue only after an admitted build exists.
4. Record the actual target Duet, candidate/build receipt and environment
   references. Register its already-approved launch with
   `openchia test register-launch --file /home/chia/repos/OpenChia-iterative-refiner/launch_default.json --duet-store DUET_STORE --duet-id TARGET_DUET_ID`.
   This command does not grant approval. Prepare the criterion from
   `openchia test describe` and the predicate/projection in `setup_inputs.json`.
   Persist its grounding through the existing shared artifact API. Include
   independently derived positive controls and negative controls covering both
   an infeasible schedule claiming the optimum and a feasible nonoptimal one.
   Then use `openchia test register-measure --file CRITERION_JSON --duet-store DUET_STORE --duet-id TARGET_DUET_ID --build-store BUILD_STORE`
   and retain its exact `requirement_ref` and `measure_ref`.
5. Only now prepare the separate Testing Duet's Architecture using
   `reasoning.testing`, with `episode_testing` capability and a frozen
   TestingContract naming the exact target, build, environment, launch and
   requirement/measure references. Let its model choose experiments and
   follow-ups from observed evidence; do not script its answers or choices.
   Freeze its own numerical controller during this later design review.
   Review and approve that Architecture, configure/approve its launch separately
   using the same designated file, and build it. Approving a tester as a
   replacement in the target Duet would stale the target's authority head.
6. After reviewing the tester's admitted materialization, explicitly run it with
   `/bg TESTER_DUET_ID run`. This uses the existing shared service and native Run
   boundary. Inspect results with the shared `openchia test history`, `results`
   and `run-record` commands against the same stores. Do not replace an
   unavailable confined Run with an in-process fixture.

The unresolved tester/access fields are intentional. This target draft alone
does not establish known-broken/correct candidate execution, nested scope
testing, recorded or numerical replay, interruption continuation, or refiner
repair. Those require their own exact inputs and evidence within the existing
harness. Positive/negative predicate controls validate the measuring mechanism;
they do not substitute for actual candidate Runs.

Run the actual task and let observed failures drive refinement. A naturally
failing candidate followed by an independently verified repair satisfies the
fail/pass demonstration; do not script the model's choices or prescribe a
failure-then-success sequence. A first-pass success establishes correctness for
that case, not repair behavior. The iterator may also return unresolved when
useful yield runs out; iteration is not a guarantee of eventual success.

## Acceptance evidence as of 2026-10-04

These are the goal's acceptance requirements, not additional implementation
tasks. The [receipt log](../unified_episode_test_harness_receipts.md) records the
executed checks and their failures; test names alone are not passing evidence.

| Required demonstration | Existing evidence and its limit |
| --- | --- |
| A testing Episode chooses an experiment and a follow-up from evidence | `test_testing_episode.py` executes the real generated loop and host learning, but choices are scripted. Live model-directed experimental design is **not demonstrated**. |
| A broken candidate fails and a correct candidate passes on an examinable task | Live job `035fb766...` repaired its generated module declaration and passed independent static verification. It did not execute a Target Workflow experiment or establish correct scheduling behavior. Historical `test_scheduling_measure.py` results use supplied answers, not candidate executions. Behavioral acceptance remains open. |
| Scoped and broader nested execution establish distinct claims | `test_scoped_execution.py` executes generated nested sources, then selected invocations, rejects omitted children and forbids promotion of narrow recordings to whole-workflow evidence. `test_unit_execution.py` covers declared-unit scope. Execution is in-process with supplied model responses, not native confinement. |
| Numerical, recorded-response and live execution remain distinct; incompatible recordings fail | `test_numerical_execution.py` recomputes actual ledger history without calls or new credit. `test_recorded_execution.py` exercises brokers, frames and stores, including matched reuse and explicit divergence, but its executor emits supplied exchanges. Stock reasoning's Run-specific prompts also correctly diverge on a new Run; they are not silently normalized for replay. |
| Cross-child regression is visible to the responsible parent | `records/test_refinement_regression.py` drives admitted source revisions and contrasting supplied results through the shared service. Indexed parent history exposes the opposing outcomes without reconstructing the audit. It proves history visibility, not that the edited code caused those supplied outcomes. |
| Interruption, continuation and repeats preserve evidence and credit | `test_nested_continuation.py` passes through the shared experiment service and real systemd workers: uninterrupted and resumed nested loops have equal results, controller history and operation counts, without duplicate child returns, calls, edits or credit. Current authority and stopped predecessor checks are real. Model choices and target observations are supplied; the comment-only edit does not demonstrate repair. CLI continuation and native single-Episode continuation also pass. |
| The measure distinguishes known-correct and known-incorrect results | `test_scheduling_measure.py` verifies the registered exhaustive-solver predicate, multiple optimal witnesses, negative controls and rejection of mislabeled controls or a caller-invented optimum. This establishes the fixed benchmark's measuring mechanism, not an LLM's reasoning ability. |

The native setup blocker is resolved on this systemd 255 host. The unsupported
private-PID requirement was removed under ADR 0006; the other isolation checks
remain. The operator-approved AppArmor exception permits namespace setup without
global disablement. Real worker execution, single-Episode and nested-refiner
continuation pass with supplied model replies. No alternate executor was
substituted; the container backend still has no installed runtime. See the [setup guide](../systemd_setup.md)
and [dated receipts](../unified_episode_test_harness_receipts.md).

The store, target approval, launch, environment and historical build references
in `setup_inputs.json` are real. Its `target.build_receipt_ref` retains the first
blocked Builder attempt, not the latest job's state. Later source admission,
including the autonomous source repair and static verification in `035fb766...`,
does not establish behavioral acceptance. No final accepted candidate is recorded. The
independent solver grounding is persisted; the separate tester's criterion
references remain unset. Remaining nulls are unresolved, not invented receipts.
A supported systemd environment is available. The testing Episode still needs
the separate exact Architecture and launch approval described above.
