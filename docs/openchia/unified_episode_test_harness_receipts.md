# Episode testing harness: verification receipts

Return to the [current guide](unified_episode_test_harness_design.md).
These chronological receipts preserve what each run did and did not establish.
They do not replace the goal's end-to-end acceptance requirements.

**2026-10-03 checkpoint clarification:** "Target Workflow" now names the scoped
workflow being built and tested, distinct from the refiner and from a candidate
revision. The revised [ADR 0005](../adr/0005-target-workflow-execution-backends.md)
supports container and systemd execution, replacing the earlier container-only
decision. At that checkpoint, the systemd failures remained unresolved; the
decision itself did not establish successful execution through either backend.
No new behavioral tests or live Runs were performed for this terminology/save
checkpoint, and these earlier receipts do not verify the newly named head.

### Source-admission visibility correction, 2026-10-04 17:23 UTC: prepared, not live-validated

The same successor Run's replacement Implementer repeats the baseline failure.
Event 136 shows `baseline_required: true` and an empty `source_admissions` list.
Event 140 returns `launch_input_invalid` for the missing materialized root;
its event hash is
`sha256:6a81749201e3454d4de0c23c66775837a46fff3876149cb64019cbfbb5667bf8`.
Verify had already recorded source admission
`refinement_9412ebfee76478960f644953abc8454cc9942ca34f35388e5669662a08467869`,
with a rejected Builder receipt for the exact same candidate, harness and
capability. It was omitted solely because acceptance and local repair name
different measures. Designer response 182 again proposes static-first repair;
the model cannot override the host's mandatory-baseline branch with prose.

In the development checkout, `instrument_builds.relevant_sources` now selects
source admissions by exact current candidate and authorized harness/capability
references. `runtime.snapshot` supplies the current assignment's bindings for
its measure and purpose. A known rejected source can therefore reach the
existing repair branch. Test results, acceptance and credit remain separate;
no new runner, stored record, migration or admission bypass was introduced.
This addresses the hidden rejection, not every unavailable-baseline case.

Both changed Python files parse and `git diff --check` passes. No tests or new
live jobs were run. The live checkout remains unchanged and the owner remains
active; this correction has no live execution claim. No Target Workflow Run or
acceptance pass has occurred.

Read-only continuation preparation subsequently compared the existing runtime
manifest with both checkouts using `inspect_runtime_source_manifest`. The live
checkout matches; the development checkout differs only at pinned worker file
`function_library/record_conditions.py`. Neither baseline-fix file belongs to
the worker manifest. Using the complete development checkout would therefore
violate exact continuation, while preparing only the host fix on the original
runtime can retain the saved worker identity. No identity check was weakened,
current process stopped, or new continuation attempted.

At 17:31 UTC, isolated preparation produced
`1aab50878e3e0e087f3f20094c1d28c291a26e60`: the original runtime plus only the
two host-side changes. The existing manifest inspector finds no worker-byte
differences, and `admit_reconstruction_source` accepts all eight original refiner
modules against the actual saved registration/package. This is read-only source
compatibility evidence, not a new Run, prefix reconstruction or permission to
continue an active worker. The current live process remains untouched.

### Live source-repair handoff, 2026-10-04 17:17 UTC: baseline evaluation prevents editing

In the same successor Run, Designer response 72 proposed a concrete source-repair
plan. Host response 74 assigned Implementer
`refinement_invocation_c82189dc4b47656d946ece1e2e976819993d9e9d838ebe6d9d84db1c2ce2a009`.
Its mandatory baseline evaluation at 84 returned at 85 with `proceed: false`:
`launch_input_invalid`, "the candidate has no materialized root launch interface".
Evaluation record
`refinement_c5f4e8d3cdf0dd332ba35208fa87989d09903b8a22fb3e231c4719ba9014f302`
names the unchanged candidate and local measure. The child returned
`needs_parent_decision` with zero yield, without a model editing call.

The subsequent Verify child used the same evaluation service for the acceptance
measure. It recorded blocked source admission and missing behavioral coverage,
not a pass. Designer request 126 contains both children's original decision
records and the blocked Builder receipt. Response 127 proposes a replacement
Implementer plan with the same local measure and the prior assignment in
`supersedes_assignment_refs`. The owner process remains live; no source edit,
Target Workflow Run or acceptance has occurred.

Read-only tracing identifies two relevant boundaries: evaluation plans group
static and execution checks under their shared binding, then check the candidate
root interface before source admission; `relevant_sources` filters admission
history by measure reference, so an acceptance-measure source rejection is not
visible through the local measure. This is a system-level repair-path issue to
resolve, not evidence that the scheduling task is impossible. The live loop has
not been stopped or patched, and these observations do not establish a fix.

### Live Measure admission, 2026-10-04 17:11 UTC: controls pass and Designer resumes

Successor Run `run_008d375611c64c57edfacec3913c172094ce2b07e1a2a95389bcbc734534a45f`
continued automatically. Question response 30 judged all five check-design
criteria satisfied, while retaining its stated limitations. Measure response 51
selected that exact `reviewed_definition_ref`, without rewriting its expectations.
Host event 55 records admitted measure
`refinement_9fa97053b772331595105166bf3dc58bc7ece4e5e3f394a313ddffabe35c8e73`.
Its 33 executable control results all match: 13 expected passes and 20 expected
failures. The admission has 24 check references and twelve measurement fact keys.
Event 55's hash is
`sha256:ccd072ce011b4759bde1e699d39f1c3efcb8d1775ccecbfe287fcf86c8dd6454`.

The independent review alone earned zero. After host admission, unit event 58
records credit changing from 0 to 12, realized yield 12, twelve semantic fact
keys, and `attained` for this Measure assignment. Its event hash is
`sha256:b94517d683ccf7252cfe94ee691393d86ef7186c9d855da1dbb097e58d0cbf96`.
The child returned through the ordinary report path. Designer request 71 then
received the admitted measure and resumed its source-repair assignment; request
hash `sha256:e94a162e7e86558a97e8f05cec311656e7d2a0b85085135312fbea6deab79ed9`.

This is real model-designed measure admission through the shared host path,
not operator-supplied repair or model-awarded credit. Its control observations
validate the measuring mechanism; they are not Target Workflow execution
evidence. The retained format and explanation limitations still apply. No
Target Workflow experiment or behavioral acceptance is established. No new
test suite, replacement Run, pinned-source edit or manual stage dispatch was
performed. At 17:11 UTC the exact owning process remained live with incoming
data on Designer's model call.

### Live Measure repair, 2026-10-04 17:05 UTC: valid design reaches separate review

The same successor Run
`run_008d375611c64c57edfacec3913c172094ce2b07e1a2a95389bcbc734534a45f`
committed response 15 with valid JSON: 154,207 characters and twelve cases,
response hash
`sha256:20fd9b35849d5d114b9266dc88e192db01311d354bc1a98c0cff34889813052a`.
Host response 17 returned `proceed: true` and assigned Question invocation
`refinement_invocation_56702568c17ddcc3468802d09d79759d1eab926eb3ac2ea176bbc929e7521336`.
Event 29 requests its independent review of definition
`refinement_20222c7321570268a75705b43682dcdffdc235cb1a7d4909a7da5a0440c7f750`,
with request hash
`sha256:e916f48c4220f9c21cb4cfb06b8812948becffb8387cc127502dd99aef1c64f5`.

The model removed the every-answer optimality condition and explicitly records
the remaining inability to check later answers' encoded field formats without
overconstraining them. Other limitations include unexecuted branches and the
unchecked mathematical validity of explanation prose. Listing limitations does
not make the check adequate; the separate review is still pending.

The exact owner process remains live. Its review-call connection had received
116,258 bytes, with incoming data 1,075 milliseconds before observation. This
shows transport activity, not an admitted result. No new job, manual check repair,
stage dispatch, test suite or pinned-source edit was performed. There is no
admitted measure or Target Workflow experiment at this observation. The repeated
JSON failures ended in this iteration; behavioral acceptance remains open.

### Live Measure inspection, 2026-10-04 16:54 UTC: response received, revision still unusable

Successor Run `run_008d375611c64c57edfacec3913c172094ce2b07e1a2a95389bcbc734534a45f`
committed its reissued model response at event 4, response hash
`sha256:39b8b17f47165b447950b53ff1353d8d7543792f636403751b2ceb6c2d0ddd02`.
The response has 63,662 characters and invalid JSON at character 9,509.
OpenChia rejected it for zero yield and automatically requested another Measure
iteration at event 14; the next context retains the actual response and exact
parse error. No manual stage dispatch, candidate edit or replacement Run was
used. No measure admission or Target Workflow execution occurred.

Direct inspection of the supplied assignment, original check, independent
review, revisions and host admission code shows:

- All twelve behavioral requirements are assigned together, and admission
  requires the proposal's requirement set to match exactly.
- The independent review identified real gaps, including mismatched request
  hashes, stale receipt selection and missing transition-to-yield linkage.
  The revised output attempts to correct these; rejection is not evidence that
  the model ignored the review.
- Six predecessor revisions (events 799, 810, 821, 832, 843 and 854) and this
  response all fail JSON parsing. The loop has not produced a usable revision.
- The latest response explicitly uses the optimality checker on every retained
  answer to check field encoding, acknowledging a stronger condition than the
  frozen first-answer acceptance measure.

The development checkout now adds `parse_json` to the existing pure record
condition language, exposed through registered predicate provenance, with no
new runner or criterion. Missing data remains inconclusive; malformed or
nonfinite JSON fails. This allows separate representation and correctness
checks in subsequent executions. It does not fix proposal syntax or split the
assignment, is not hot-applied to this Run, and has no live validation claim.
No additional behavioral tests were run for this preparation.
Python syntax, JSON document parsing and whitespace checks pass. PR #36 was
merged and fast-forwarded into the development branch at `2516a9c792`; the live
checkout and its frozen model binding remain unchanged.

### Live build continuation, 2026-10-04 16:46 UTC: exact Measure request resumed

The same `continue_build()` call progressed to native successor Run
`run_008d375611c64c57edfacec3913c172094ce2b07e1a2a95389bcbc734534a45f`.
Its `run_reconstructed` event 2 records 479 matched worker frames, zero remaining
frames, no divergence and the original root → Designer → Measure stack. Source
and current authority were checked, including that the previous executor was
stopped. The subsequent `model_requested` event reuses the exact interrupted
request ID and hash
`sha256:52aa9c2cb75fbc2286a5caea6554dbb01f6ce9ed45f1a850f315da1a25b9f604`.
No completed historical model calls were resubmitted to reach this point.

Read-only connection observations show incoming bytes increasing from 130,590
to 139,941 over approximately fourteen seconds, then to 609,134 at 16:46:46 UTC.
This is actual transport activity, not inference from a pending-request record.
The new Run has no completed model response or Target Workflow experiment at
this observation. Reaching the interrupted call demonstrates real nested
continuation; it does not establish an admitted measure, accepted repair,
absence of later duplicate credit, or scheduling acceptance. The pinned source
is unchanged; subsequent PR #35 audit-read optimization and PR #36 review
corrections are not part of this running execution.

### Live build continuation, 2026-10-04 16:33 UTC: preparation in progress

The ordinary `OpenChiaHost.continue_build()` entry was invoked once for the saved
job and experiment below, using pinned source
`b6ae19fe9625c70d65df72003c003d744404ff8c`. No fresh Builder attempt or campaign
was manually substituted. Its owner process remains active. The existing
RunStore has completed the predecessor's terminal-evidence publication:
`run_evidence_7d1dfe3f5dd7c24b844dd1c0faa74b132c9635d2ff1e141a1244205baeea1fd0`,
hash `sha256:94692e0bff312657ad558a9319df2f4f90332b1e38f7cc341c848f5365e8469b`.
The compact `openchia test run-record` view is now current and still records
866 events, 48 model requests, 47 responses and `cancelled`, with the same
terminal event/hash. No successor worker is registered at this observation.

This establishes interrupted terminal-publication recovery, not successful
execution continuation, Target Workflow correctness or acceptance. The host
includes the reviewed health transport, but restores the original model binding
without adding its new default policy; this historical execution has probes
disabled. Live health recovery remains unverified. The running checkout is not
being edited. The five CLI JSON input readers were separately corrected in the
development checkout for UTF-8 BOM compatibility; the repository Windows-footgun
check passes, with no additional behavioral suite run.

### Live one-start retry with rejected-output feedback and event comparisons, 2026-10-04 UTC: operator-cancelled

Latest status: the user requested stopping the unanswered model call 48.
Cancellation was requested at 16:01:40 UTC. The Run committed `cancelled` at
event 865: 866 events, 48 model requests and 47 responses. The exact systemd
worker was stopped and verified inactive. Caller cleanup did not finish
normally; SIGTERM was required and the caller exited 143. A finalized build-job
result was not confirmed. No replacement had started at cancellation, and there is no acceptance
pass. Separate continuation and health-recovery work does not retroactively
change this evidence. The following records describe the attempt before that
cancellation.

One normal `OpenChiaHost.start_build` started
`build_request_f909ff82826ee4882064ba7b425d83278be6ca9aafc6d6e5bd38a45ad9f0613d`
after the preceding Run was terminal, its worker inactive and caller cleanup
finished. Attempt
`build_attempt_b13c99713da8d9ef939a4ab98b981e508edd809d7ab5781e6528941f3dd11362`
produced receipt
`build_receipt_32331f0147a3d66bc89752be5e0424ae48d31f3f505fc23c6b796511fb928428`,
with two findings, zero Episodes planned and zero modules emitted. The findings
are `planning_failed` (`prompt_specs[0].response_contract must be non-empty text`)
and `missing_module`. Committed model-call evidence
`build_model_call_1043fdc99e1ed22fe015a7b187cddaa07fcd7889d34046ce6c2a77f48f1c71ad`
retains the unadmitted response: both prompt response contracts are JSON-schema
objects, not the strings required by plan admission. This is a plan-format
failure, not a scheduling correctness verdict. The materialized specification is
`materialized_specification_cb245a4678041ace3674f3f268364e0224cf6ef8e42aa12d7f017171731b790b`,
the baseline is
`refinement_baseline_f9dc85a7e79b057856499bf1d5407110885d7e75070d7b793a65977856bbdf71`,
and the campaign is
`refinement_7f96d6eaf134da9704798cb07ca0f684196274d961dd01e15a3e2ea96526e8ab`.
Experiment
`experiment_950c8e594e46e7e5896a8f80b1ffe20a6d68d864315af6835733651f5f11bc43`
owns native Run
`run_358b0b188f2732c49a60c6d304d8309705e611b325cd6c822d0ad771a1347edf`.
The same normal start automatically progressed into refinement. Its first
observation had 38 events and one model request awaiting a response. Subsequent
check-design response 53 contained 49,474 characters and failed JSON parsing at
character 15,403 (line 1, column 15,404); host 55 rejected it. Contexts 55, 60 and
62 now contain `rejected_proposal.raw_response` with exactly 49,474 characters,
`admitted: false`, and the parse error. Automatic repair response 64 produced
valid JSON: 113,212 characters, twelve cases and nine `parent_path` operands.
Host 66 accepted the proposal and automatically assigned separate Question
reviewer
`refinement_invocation_d66390fe6669e1291e5b8d9dc50f1c4112b4943621795a069263cab6f6437292`
to definition
`refinement_2b489ceec16f7d044c121c86486ac7e2ce7d213471c4ea289f2df595e8328c7b`.
Independent review response 79 rejected substantive cross-record, provenance
and coverage gaps. The control-polarity review criterion passed; that is not an
executed positive-control pass. This demonstrates automatic repair into a valid,
separately reviewable proposal, not validation, measure admission or scheduling
success. Measure 100 returned an acceptance-grounding need. Root 121 assigned
Designer actual implementation across all sixteen requirements. Designer 136
requested local Measure checks for all twelve behavioral requirements. Local
design 151 contained 110,564 characters; independent review 166 marked all five
criteria false. Measure 187 returned a local grounding prerequisite, forwarded
by Designer 208. Root 252 assigned a successor Designer with both prior
prerequisite references. Designer 267 then explicitly assigned eleven uncovered
local requirements, carrying the review findings: selection/result joins, all
frontier answers, the stop bound `<= 0.01`, exact `HostReceipt`, and proper
provenance/capability coverage. Schedule correctness remains independent.
The successor Measure then produced four consecutive malformed responses:

| Response event | Characters | JSON error character | Rejection event | Credit |
| --- | ---: | ---: | --- | ---: |
| 282 | 96,379 | 44,074 | 284 | 0 |
| 293 | 87,089 | 37,665 | 295 | 0 |
| 304 | 95,332 | 40,788 | 306 | 0 |
| 315 | 94,627 | 56,338 | 317 | 0 |

Each following context contains the exact latest rejected `raw_response` and
parser error. These four consecutive format repairs did not succeed. Measure
326 returned the same local grounding need, forwarded by Designer 347. Root 391
assigned Designer all sixteen requirements with the explicit instruction to
implement rather than merely restate a plan. Designer 406 emitted a 16,682-character
plan, rejected at 408: "implementation measure has unresolved requirement coverage."
Designer 417 requested Measure for all twelve behavioral requirements; Measure
432 immediately returned the same need. These records show a recurrent
prerequisite/assignment loop; they do not establish its exact root cause.
At that point, no further design review or admission had occurred.

Root 497 proposed replacing Designer, but host 499 rejected it: "only the
assigning owner may route a returned prerequisite." Root 508 removed
`prerequisite_refs`, and host 510 accepted a replacement Designer with the same
sixteen requirements. Designer 523 requested Measure for all twelve behavioral
requirements, also without `prerequisite_refs`. Measure 538 produced 46,530
characters of malformed JSON, rejected at 540 with "Expecting property name
enclosed in double quotes" at character 42,273. Response 549 was also malformed:
46,921 characters, with its JSON error at character 42,252.
These records do not by themselves establish that history was dropped or explain
the root cause of the recurring loop.

Response 560 was a valid 47,301-character `check_design`, accepted as a proposal
at 562. Independent review 575 rejected four criteria, identifying stopping
consistency, mixed `learning_opened` records, later-answer and provenance gaps.
The control-polarity review criterion passed, not executable controls. Measure
then directly revised the design: response 596 was a valid 59,680-character
`check_design`, accepted as a proposal at 598 and sent to a new independent
reviewer. Review 611 rejected four criteria; control polarities were true as a
review criterion, not passed executable controls. Requiring every frontier
answer to be optimal exceeded the original formatting-only requirement for later
answers. Other findings were missing event-sequence ordering, existential evidence
checks admitting contradictory extra evidence, and inheritance/durability claims
beyond the observable records.

Measure directly revised again. Response 632 proposed a 62,724-character design
with explicit sequence ordering, exact evidence arrays, no every-answer optimality
requirement, and an explicit inability to parse later JSON-valued strings. Host
634 accepted it as a proposal for independent review. Review 647 rejected four
criteria, with `limitations_are_explicit: true`; that favorable review criterion
is not executed validation. Measure 668 requested the same grounding need,
forwarded by Designer 689. Root verification returned `needs_parent_decision`.

Parts 733 superseded the previous Designer with the same broad sixteen
contribution requirements and requested source repair rather than measure
redesign, but supplied `prerequisite_refs: []`. Designer 748 again assigned all
twelve behavioral requirements to Measure with `prerequisite_refs: []`; host
750 accepted the assignment. These events show a repeated unresolved prerequisite
loop, not accepted progress. Event 761 confirms that `response.context.check_design`
contained zero definitions and zero reviews, despite the repeated twelve-requirement
scope following review 647. It still contained four available predicates and three
execution bindings. This establishes absence of that specific check-design/review
context, not absence of all other history or an exact root cause.

Design 763 contained 99,720 characters. Review 778 marked
`original_requirement_preserved: true` and the other four criteria false, citing
missing `request_hash` / same-Episode joins, selection of any receipt rather than
the final receipt, extra altered openings and malformed later answers. Six
subsequent malformed repairs were rejected:

| Response event | Characters | JSON error character |
| --- | ---: | ---: |
| 799 | 66,107 | 7,596 |
| 810 | 61,798 | 7,356 |
| 821 | 63,527 | 8,514 |
| 832 | 61,566 | 10,222 |
| 843 | 62,802 | 10,164 |
| 854 | 64,198 | 10,257 |

None of these proposal acceptances establishes an admitted measure or Target
Workflow acceptance. Four files have untested changes only in the separate repair
checkout: `function_library/record_conditions.py` adds generic `parse_json`;
`function_library/refinement_contract.py` and
`iterative_episode_refiner/runtime_proposals.py` clarify immediate child contribution
versus whole-parent acceptance and coherent measurement requests;
`iterative_episode_refiner/measure_design.py` prepares typed `prior_review_findings`
from existing campaign records and committed child reports under the same Parts
owner, authority, purpose and exact requirement set. It is bounded to eight
original review entries with `omitted_count` and definition/predicate/binding
references, not full control fixtures or an LLM summary. Historical judgments
are not current authority or admission. These changes alter no gate, credit or
criterion, are not integrated into main, and are not active or demonstrated
in this Run.

Context 49 advertises `parent_path` in `record_conditions` definition
`function_a52ff12d36e4940e7d6f6ce9e8d9bb9b69c9e938b836e0d82d39cd85e86e74be`.
The repaired proposal uses the operand, but this is not yet an executed predicate
or cross-event relationship check. The prior counted checkpoint had 611 events,
33 model requests and 32 responses. Before cancellation, the Run reached event
864 with 48 requests, 47 responses and call 48 pending. There was no admitted
measure, source repair or Target Workflow experiment.
No acceptance is established.

At 2026-10-04 14:04:55 UTC, the Run was still at event 864 with call 48 pending.
Read-only inspection of host PID 2798348, thread 2808522, showed kernel stack
frames `sk_wait_data`, `tcp_recvmsg` and `sock_read_iter`. Its only established
TCP connection's received-byte count stayed at 7,366,322 while `lastrcv` reached
1,778,719 ms, about thirty minutes. This confirms a wait for network data at
that observation, not a host database lock. The pinned
`agent/episode_launch_transport.py` has no fallback deadline when
`request.timeout` is `None`. The remote cause is not established. This was a
pending call, not a terminal failure or acceptance result. No cancellation,
restart, source edit or extra test was performed for this observation.

The approved Target Workflow, launch and Duet configuration are
unchanged, with no manual candidate edits, check expectations or threshold changes.

Both preceding generic corrections applied to this job.
`evaluation_experiments.feedback` exposes the actual rejected `raw_response`
as unadmitted data, and `record_conditions` adds a `parent_path` comparison
operand for event relationships. Neither correction was part of the preceding
cancelled Run. Ruff and whitespace checks preceded the real cycle; no fixture tests
establish these observations. Executed event comparisons and acceptance remain
unproven.

### Live one-start retry retaining check-review evidence, 2026-10-04 UTC: cancelled

A new complete `OpenChiaHost.start_build` was launched after the preceding job
ended naturally, for
`build_request_44c60f4b7983c56b0d8e1aee74e7fba31ee462705326648a6070b4479b134e15`.
Attempt
`build_attempt_054472b185f3b54421953b3af31a3d1261c5989c122fd6de7f44ac3090b8df64`
produced initial receipt
`build_receipt_3c6393feb2404111cc2954a883c45bcf63bddfffaba2fb13be3530a72db152b3`,
with two blocking findings and zero Episodes planned or modules emitted. Exact
finding diagnoses are not yet recorded here. The materialized specification is
`materialized_specification_3dc5914d3612b39b880af7d31f67fe9a6bee38d056c55a13e29ca5b3e72a3597`,
the baseline is
`refinement_baseline_4f28f352444bb8be45a3f611eb286d185c88b81d228f68fa30c7ddfa6c57b87e`,
and the campaign is
`refinement_657cfae61b8ef5dd7f33068ebe702d997c761cb0bca7aa09cd31e0b86946c185`.
Experiment
`experiment_4542ebb056bd78dd38ff7bae2a63ecbed24eb0fceb419b7a268eb437ead0c696`
owns native Run
`run_d4fb3c68de969ebf3665a095e7db80871f4bdd40c2f40a1cf008fc7d9c4cc440`.
The ordinary one-start build progressed automatically into refinement. The first
observation retained 38 events, two invocations started, one completed, two units
and one model request awaiting a response. Subsequent response 68 contained
46,020 characters of malformed JSON; host response 70 returned the exact parse
error at character 17,585 and the loop retried automatically. Response 79 was a
valid 41,842-character, twelve-case `check_design`, assigned to independent
Question at 81. Review 94 rejected all five criteria with eight counterexamples.
Revision 115 contained 55,157 characters and failed JSON parsing at character
20,790; host 117 returned that exact error. Automatic retry 126 requested a
grounding prerequisite, which Designer 147 forwarded.

Designer contexts 138 and 143, and root Parts contexts 159 and 182, each contain
one `prior_check_reviews` entry. Following parent assignment 191 and Designer
prerequisite 206, successor Measure contexts 217 and 219 each contain one full
prior check definition and its matching review. This verifies full-definition
propagation across the parent handoff, not merely an owner-review projection.
These communication observations do not establish accepted refinement progress,
check admission or resolution.

The same prerequisite then recurred. Measure 221 returned it and Designer 242
forwarded it. Parts 286 requested concrete implementation; Designer plan 301 was
rejected at 303: "implementation measure has unresolved requirement coverage."
Designer 312 assigned all twelve requirements to Measure. Its grounded
schedule-only proposal 327 was rejected at 329: "measure proposal changes the
parent's requested judgment." Measure 338 returned the same need, forwarded by
Designer 359. Parts 403 assigned Measure directly for all twelve requirements;
Measure 418 returned that need again. Parts 439 reassigned all sixteen requirements
to Designer. Plan 454 was rejected at 456 for the same unresolved measurement
coverage.

The operator explicitly cancelled the owning caller after these repeated
failures, to apply two prepared generic corrections. Review required cross-event
joins that this Run's condition language could not express. Rejected proposals
also omitted the actual output from the next repair context. This was not
spontaneous termination, successful refinement or normal yield-based return.
The native Run records `cancelled`, with 471 events, fourteen invocations started,
twelve completed, 23 model requests, 23 responses and 26 completed units.
These are event counts, not a count of successful model generations. There were
zero candidate source changes and zero Target Workflow experiments. There is
no accepted repair, admitted check or acceptance pass. The monitor exited 0;
the owning caller subsequently finished cleanup with exit 130. Durable result
`experiment_build_job_result_9645cb5765dcf29fd42cb4de180807eb3dffde71850948ff6d54c8bbc2dfec41`
records build-job state `cancelled`.
The previously demonstrated static source repair belongs to an older Run, not
this repeated-prerequisite loop.

The current changes in `measure_needs.py` and `measure_design.py` preserve exact
check definitions and prior review findings through prerequisite provenance.
`llm_call_library/calls.py` retains malformed-container JSON errors instead of
treating a container key as a scalar response. Only Ruff and whitespace checks
preceded this real cycle; no fixture tests establish these observations.
Additional rejected-output feedback and a `parent_path` operand were prepared
only in a separate repair checkout, then applied after native termination,
worker inactivity and caller cleanup. They were not part of this cancelled Run.
The approved Target Workflow, launch and owning Duet model
configuration are unchanged. No individual stage is launched by the operator
and no earlier frozen Run is modified.

### Live one-start retry with exact-edit diagnostics, 2026-10-04 UTC: failed naturally

After the preceding job's cancellation cleanup finished, the ordinary
`OpenChiaHost.start_build` entry was called once for
`build_request_5d4dfc269a03557e03b9d133b17030361ecfc94ba660a7ce5c9e7c8b57661b82`.
Attempt
`build_attempt_6b2e7c50b7dd635e0ee73fb9f6b7d78a9a4c642ea1c61b439198fb1db3d2dfeb`
produced blocked receipt
`build_receipt_a5cf3a034f570dfdd2cf287653275cba54b36d2e723ce77a3661c9516a3f1de6`:
the goal's response contract was not non-empty text and its module was missing,
with zero Episodes planned or modules emitted. OpenChia automatically entered
refinement. The materialized specification is
`materialized_specification_d211ec48cfff285110ab7baff8a9c41958cc78006aa14d21fd3af7534b3d7520`,
the baseline is
`refinement_baseline_019aeb7530d5a40e6cc1e0fd6b22b621efb3c5dedba0e41992c3500f80ba28db`,
and the campaign is
`refinement_c94af9af54af1a809debdf84227da10e2f5f9f25cbbab10ac5eeb007ced0b157`.
Experiment
`experiment_19d3ec114f1a81a9bc61bd0c33997ebc13245f54cbfd25072da7e22d4ef5cf9f`
owns native Run
`run_54f753918b59985e8e813c1c70c176407402541608671d66b28f3c9b47536e31`.
Root response 38 assigned Designer, accepted at 40. Designer response 53
requested Measure for twelve behavioral requirements, accepted at 55. Measure
definition 68 received separate review 83 rejecting five criteria. Revision 104
was malformed JSON; Measure 115 then requested grounding. Designer 136 forwarded
that exact prerequisite, accepted at 138, and returned `needs_parent_decision`
at 140. Root 180 assigned a successor Designer; Designer 195 requested another
Measure, whose response 210 returned the same need. Designer 231 forwarded it.
This demonstrates exact prerequisite propagation, not resolution. The Run
subsequently ended naturally, not through an operator stop. Terminal event 305
records `run_failed` / `LaunchModelError`. The final `model_launch_call` receipt
on `duet_8b48507b29a3ff275ed1084632cd7f80a78388dce2eeae549af8c1f49e914c72`
records `error_type: RemoteProtocolError`, `failure_category: timeout`,
`http_status: null`, `retryable: true`, and elapsed time 246.66655 seconds.
The native audit has 306 events, eleven invocations started, eight completed,
fifteen units, fourteen model requests and thirteen responses. The caller
exited 0, but the build's final state was `host_error`. No Implementer,
Target Workflow experiment, accepted repair or acceptance pass occurred.
The approved Target Workflow, launch and owning Duet's
`gpt-5.6-sol-900k` / `xhigh` route are unchanged. No individual stage was launched
by the operator.

Source is `9b5d11574a` plus the changes in
[setup_inputs.json](acceptance/setup_inputs.json). The latest change in
`materialization_edits.py` reports the first exact-before mismatch. It changes
no criterion, control or comparison rule, supplies no candidate repair or task
answer, and did not alter an earlier frozen Run. No tests were run for it;
this attempt did not establish repair or behavioral acceptance.

### Live one-start retry with exact observation schemas, 2026-10-04 UTC: cancelled

The ordinary `OpenChiaHost.start_build` entry was called once for
`build_request_1e10de051dbb0065aba05bbd1f4e47b7554bdbdea6c31a60b27f704a1f1da72b`.
Initial attempt
`build_attempt_c0439a8cb587835a7bb4dcf8583aecf0a5ea2f5d6b92b47c9a7405cb53c4f523`
produced blocked receipt
`build_receipt_d11e33951f223bb91a1657b0699c5057605f8b3a6517fd05479f62996353f6d4`:
the goal's `prompt_specs[0].response_contract` was not non-empty text, and its
module was missing. No Episode was planned or emitted. OpenChia automatically
transitioned into refinement without a second start. The baseline is
`refinement_baseline_5644461aba0f75ad9cf457b310fc99f9f1cc1a32fd5fc6a252e21c96ab4121d6`,
the campaign is
`refinement_d97a64c4815974cdae0f6528040721ebaea96344bdafecad0c89bdf111cf14bf`,
and experiment
`experiment_b198903b85e9d173331a04cf668e140ed6cd0f5e2d08673a6b15d1bba2afd3b7`
owns native Run
`run_d2c7d6667c1d34664cef783f6127803114823e928ad60115621d24776e52306b`.
No individual stage was launched by the operator. The approved Target Workflow and launch are
unchanged; the refiner retains its owning Duet's `gpt-5.6-sol-900k` / `xhigh` route.

Root response 38 proposed an invalid cross-role succession, rejected at 40.
Corrected response 49 received a scoped Designer at 51. Designer plan 64 was
accepted at 66 and called Implementer. Response 86 authored source and a new
node plan, committed by the host at 88; source admission at 90 rejected
`module_exports_incomplete` and `request_payload_binding_mismatch`.

Implementer responses 99, 110, 121, 132 and 143 then failed exact-before
validation at host responses 101, 112, 123, 134 and 145. The only mismatching
paths were `/prompt_specs/0/prompt_template` and `/prompt_specs/1/prompt_template`:
stored literal backslash-n versus newline characters in the model's copied
value. Its context supplied the exact current value in `permitted_detail_edits`,
but the rejection gave only a generic stale-before message. These repeated
errors do not establish that legal repair was unavailable.

The operator sent SIGINT to the exact owning API caller, PID 2790520 with process
creation time 1791095628.4, validated against launcher PID 2790769 and the exact
audited systemd unit. Its cleanup invoked `host.close`. The native Run is durably
`cancelled` with 155 events, four invocations started, one completed, ten completed
units, ten model requests and nine responses. No Target Workflow experiment or
accepted repair occurred. Caller cleanup finished with exit 130, and durable
build-job result
`experiment_build_job_result_bc1b03f930ab407e1262f9e20243c92af63882d3814a99b49511182ea43fbc86`
records `state: cancelled` and `error: null`. Both native cancellation and job
finalization are recorded. This is not an acceptance pass or yield-based return.

Source is `9b5d11574a` plus the production changes listed in
[setup_inputs.json](acceptance/setup_inputs.json). The correction exposes exact
learning/model observation schemas and receipt result paths. Designer and nested
Parts can forward an exact returned child measurement prerequisite through the
existing `propose_measure` operation and parent report; host and store independently
validate that relationship. This adds no new credit or stopping rule and does not
change an earlier frozen Run. This attempt did not establish live acceptance of
those corrections. After native cancellation, a generic first-mismatch diagnostic
in `materialization_edits.py` was prepared for the next job. Exact-before checks
and acceptance criteria remain unchanged; no candidate patch, model response or
task answer was supplied by the operator. No tests establish the new diagnostic's
behavior; its live validation remains pending.

### Live one-start reviewed-design and coverage loop, 2026-10-04 UTC: cancelled

`build_request_456490d761a714253bcfabd601527fa2f957683c50800806976168e6fe5c97cd`
automatically entered native Run
`run_02fc56cd8e6a9ab4307626bdaa61c8ad25a477142c9a06412e0c883e22139d62`
through experiment
`experiment_b2b1b071eb21919e90bc454570cc9fd763c17650559d6f63d8153f6c2ca7bff7`.
Its initial Builder receipt is
`build_receipt_b170490c8fdc412ee053f5ce8f88586dde2b4591cc582c11b774e7e7a49d3cd6`.
The model authored a concrete measure design at response 53. Separate review at
68 rejected incorrect event, result and route paths. Later plans still lacked
coverage; Measure returned `grounding_required`, and a Question request lacked
parent decision criteria. The model repeated these routes, although narrower
Measure assignments remained legal. The evidence does not establish that every
legal route was exhausted or impossible.

The operator sent SIGINT to the exact owning API caller, invoking its normal
`host.close` cancellation cleanup. The native Run ended `cancelled` with 264
events, seven invocations started, five completed, 16 completed units, 16 model
requests and 15 responses. There were no Target Workflow experiments, Implementer
invocations or source edits. A read through the existing experiment records API
confirms build-job result
`experiment_build_job_result_34bc3c45b31d513af5146966bfed6a9cc45d6b310e0a4f9f031f72e4b5386dd3`
with content hash
`sha256:55cf361a9c3adb2fa81f1a8774fe9a3016221ca6eed9bcfad25b207ee5d7135c`:
state and refinement disposition are `cancelled`, `error` is null, and
`verified_build` is null. This is an operator-cancelled live attempt, not a
spontaneous failure, normal yield-based return or acceptance pass. No fixture
tests, model replies, candidate repairs or target answers were supplied for it.

### Live one-start source repair and measurement loop, 2026-10-04 UTC: cancelled

`build_request_035fb766dab32f472c6362d9c0662a2e9160c7b98275e037e32ef22088a61176`
used the corrected normal-build plan-edit policy. Builder admitted its node plan
and emitted one module, but receipt
`build_receipt_6eb917a56de2c1de51d81c10dc7e49681c9f1e047acbef1ef71da45166f4e887`
reported `implementation_module_dynamic`: a function implementation's module
name was not a literal. OpenChia entered native Run
`run_95413180114272f4be3a401b2bb8fc68d6f5e6a1d71bc9ab88b74f4850caa653`
through experiment
`experiment_47df5f43ae21e964ea07f03ba8d2c582cda35a7c220766dd998d0db699c1bea7`.

The nested Parts → Designer → Implementer loop performed the actual source
repair without an operator-supplied patch. Response 108 replaced the dynamic
module expressions with literal declarations. Host response 112 admitted the
source, 114 recorded Implementer attainment, 135 recorded independent static
verification, 143 recorded Designer attainment, and 170 recorded enclosing Parts
attainment. This establishes the real static repair loop, not behavioral acceptance
or a solved scheduling Run. The separate parent verifier retained twelve
behavioral coverage gaps.

Three Measure children returned the same `grounding_required` need at responses
223, 292 and 328 without proposing a check. The recorded system instructions
unconditionally directed return for missing grounding, but later permitted
reviewed check construction. The host API did support that construction; missing
prewritten cases did not establish that the route was unavailable. Ordinary
Question and cross-role replacement attempts were separately rejected. This is
an observed repeated-return loop with conflicting guidance, not proof that every
legal route was impossible.

The operator cancelled this attempt through the exact owning API caller's
`OpenChiaHost.close` cleanup before applying the guidance correction. The native
Run ended `cancelled`, with 347 events, fifteen model request/response events,
eleven invocations started and 21 units completed. No Target Workflow experiment
was requested and no behavioral pass occurred. The owning build job subsequently
recorded `build_host_failure` with `ProcessLookupError` during cancellation cleanup,
not a successful build result. The native Run's cancellation record remains intact;
the exact cleanup race has not been diagnosed. The correction distinguishes
missing prewritten cases from missing evidence/authority, retaining independent
review, executable controls, and unresolved-prerequisite reporting. Only Ruff
and whitespace checks were run for the correction; the next normal live job
must establish its behavior.

### Live one-start retry with shared execution observations, 2026-10-04 UTC: cancelled

The ordinary `OpenChiaHost.start_build` entry started
`build_request_ffe29aa6a0e5493391f6881537af9bfdaca023e0a3588ba3b77af3b121e273a3`.
It uses the same approved Target Workflow and launch, with the owning Duet's
`gpt-5.6-sol-900k` / `xhigh` configuration. This attempt is not an acceptance
pass. No operator supplied a candidate repair, answer, check design or model response.

Native Run `run_63b71197c62147612cf587e1553b1f9ee67d2e6beaa0a5ebfc6e175f3712ece1`
reached Designer and Implementer. The first source candidate did not clear the
invalid node-plan binding or missing-module findings and earned zero progress.
The coding child then identified that its `permitted_detail_edits` was empty.
The frozen normal-build policy omitted `materialization_edit_targets`, so the
existing node-plan repair operation was unavailable even to the parent. Three
Question requests were rejected because this campaign also had no ordinary
investigation decision definitions; that route could not create editing authority.

After confirming the missing host policy, the operator interrupted the exact
owning API caller, whose cleanup invokes `OpenChiaHost.cancel_build`. The native
Run recorded `cancelled`, with 238 events, fifteen model request/response events,
nine invocations started and eleven completed units. Cancellation response
events are not fifteen successful model generations. No Target Workflow Run
or accepted build occurred. The original audit is retained; cancellation is not
yield-based completion. The correction grants only the exact existing
`node_plan` targets from the approved materialized specification when preparing
a new normal-build campaign, including nodes whose initial planning failed.
Frozen contracts, topology, capabilities and acceptance remain unchanged.

Source is `9b5d11574a` plus the current working changes. The shared harness now
offers `/verified_run` observations resolved from the exact registration,
terminal evidence and committed event chain. Experiment measurement and campaign
admission use the same resolver; parent reports retain a hash-bound projection
reference instead of raw logs. The same catalog is available through `describe`
and Measure context. Unknown observation roots are rejected before review.
The registered `record_conditions_v1` predicate permits structural checks and
relationships over these actual records, and delegates existing task predicates.
Missing observation data remains inconclusive. Reviewed-design authority no
longer removes the existing missing-grounding request to the parent.

The correction passed syntax compilation and Ruff, not behavioral acceptance.
No fixture or unit tests were run. Its live validation is this ordinary build
cycle; the earlier failed attempt remains independent evidence below.

### Live one-start check-design loop, 2026-10-03–04 UTC: failed

The normal build entry started
`build_request_e9da37ab659fd8b8e008e7dcfd4c93fbbf2e80d4a5c19ac6e3809af8e970628e`.
Its initial Builder receipt reports an invalid pre-emission generated binding
and a missing module. OpenChia automatically entered refinement through
`experiment_be754f815691e4959a2d998a9e5701992cdfce1c47a59a661c42363963b1b47a`
and native systemd Run
`run_fcb9d467c5e088ba3a5b479ff3ac1172902cd499bc041ef4419fab8e57856c94`.
The Measure assignment uses the authorized adequacy measure after correcting
the assignment validation and guidance described below.

At 234 committed events the Run had thirteen model requests, twelve responses,
eight invocations started, five returned, and no experiment requests. Four separately
reviewed check designs were rejected; another response was invalid JSON and
earned no credit. The designs relied on proposed host trace fields
that the bound harness does not produce; adding a prose observation schema did
not implement those projections. The actual campaign measurement adapter reads
the committed typed terminal result. Check-design context does not expose that
observation contract, and design admission does not reject incompatible paths
before review. This is a system defect, not a defect the Target Workflow's
Implementer can repair within its assigned source scope.

No coding child, repaired candidate, Target Workflow validation Run, or accepted
build has been demonstrated by this attempt. No fixture tests or supplied
model responses were run for this receipt. The active workflow and its frozen
criteria have not been edited to make the check proposals pass.

After confirming that its frozen harness could not supply the required execution
observations, the exact worker service was operationally stopped. The host
finished its outstanding model call and finalized the Run as `failed`, with
236 committed events and thirteen model responses. The build ended `host_error`
with `ConnectionResetError: Connection lost` following that operator stop; this
is not evidence of a spontaneous transport failure or successful completion.
The host correction was prepared in a
separate repair worktree, without changing this Run's source during execution:
the existing shared reader supplies verified registration and committed events,
checks select implemented observation roots, and missing grounding remains a
reportable prerequisite even when check design is authorized. No Target Workflow
candidate, model reply, or acceptance criterion was supplied by the operator.

An intervening one-start attempt,
`build_request_8d509acd7a93053826f1dc9405f47b402f7f198d3206188bb44fe4c2a3a7d76a`,
ended naturally when its first refiner model call raised `APIError` with no HTTP
status. Its Run is
`run_cab0e4ae18c7cc53025fff49d053597fc669177dde08a07f6a831bfcee75dc44`.
It was not cancelled and is not an acceptance pass. Shared transport diagnostics
now retain a safe failure category and retryability without storing provider
response bodies or credentials; the exact cause of that earlier API error is
not established.

### Real one-start retry after proposal-reference feedback correction, 2026-10-03

The ordinary `OpenChiaHost.start_build` entry started
`build_request_3c01f105f7aa51a7c7e002a72abe187a1a21a6697bfbb8da903655db15322758`.
Source is `9b5d11574a` plus working changes in
`iterative_episode_refiner/runtime.py`, `runtime_proposals.py`, and
`function_library/refinement_contract.py`. These changes return typed feedback
for nonexistent proposal references, handle an absent optional review reference,
and clarify the prerequisite-reference field. It used the real model through OpenChia's one-start
cycle, not supplied answers or manually launched repair stages.

That attempt subsequently repeated proposals under a wrong, immutable Measure
assignment: its local measure was the implementation measure, not the authorized
adequacy measure. The exact worker service was operationally stopped before
retrying with corrected assignment admission and guidance. Run
`run_596361a5c6f1ab308d34240fe593c920a38516a4582727dd6b12b96cb200ee04`
finalized as `failed`, with 88 events and `ConnectionResetError: Connection lost`.
That transport error followed the operator stop; it is not evidence of a
spontaneous transport failure or successful completion. The original records
remain intact.

At the user's direction, the supplied-response compatibility run below was
stopped and no replacement fixture run was started. The runner exited **130**;
`test_nested_continuation.py` was cancelled by SIGTERM after **896.2 seconds**.
It did **not** pass. The already completed campaign-state (9), control-integrity
(2), and report (4) checks retain their individual results, but this is not a
green four-file suite. The earlier native nested passing receipt remains
historical evidence for its recorded source, not a pass for this interrupted run.

### Live one-start attempt after reviewed check design, 2026-10-03

The ordinary build entry was called once from clean source `9b5d11574a`:
`build_request_78eb8b0305fce395434d831032dc96076f04d3b75b5558161efa7c52d9f6dce3`.
The initial receipt
`build_receipt_360b511ab39616b8e50021e1527827bc82eef47c29b37aec0df114938c748752`
reported two deficits. OpenChia automatically entered native systemd refinement
through experiment
`experiment_9ae0b68ab813466009c5bc7e0be8b81490c2dd153be587cc6363c77b4a00efdb`
and Run
`run_61500857c8403c83f063af07b95e6385a374e716fa8e04de62ffee43c4392e3a`.
Its campaign artifact is
`refinement_9daea6e8b0bdd79cfb2b0e2f2896edc7436733422c571b394844a69ac675f055`.

The job ended in `host_error` with
`DuetNotFoundError: no admitted measure_need with that key`; the Run terminal
status is `failed`. The model supplied a non-prerequisite artifact in
`prerequisite_refs`. Host validation raised an unhandled lookup error instead
of returning proposal feedback. The terminal index records 41 events, two
invocations started and one completed, two completed units, and one model
request/response. This is not yield-based completion or acceptance.
The owning Duet was fully
initialized with its configured `gpt-5.6-sol-900k` / `xhigh` route, separate from
the approved Target Workflow launch. No operator repaired the candidate or
manually launched refinement. No accepted repair, Target Workflow Run or verified
build is established. The failed job is preserved in the same stores and the
[setup record](acceptance/setup_inputs.json).

### First-time check design, separate review and executed controls, 2026-10-03

The user confirmed parent-designed expectations under the initial job grant,
subject to separate review and executable controls. Measure now creates an
immutable definition, delegates review to its existing Question child, receives
the typed report, and submits the exact reviewed definition to ordinary measure
admission. The host reconstructs cases and runs the shared control predicates.
No additional runner, replay mechanism or per-iteration human approval is added.

`scripts/run_tests.sh tests/iterative_episode_refiner/test_reviewed_check_design.py`
passed **2 tests in 27.6 seconds**, retries disabled. Actual campaign stores,
child assignment/return, publication checks, numerical credit, and exhaustive
scheduling controls execute. A valid reviewed check is admitted; a falsely
labeled satisfactory control fails despite favorable review. Missing/unreturned
reviews and altered projections are rejected. Review alone yields zero; admitted
adequacy reaches the parent without declaring the Target Workflow correct.

The model choices and initial Builder responses are supplied. This is not live
reasoning or native-confinement acceptance. The first invocation failed fixture
collection (missing imported `run_store`); it was corrected before the passing run.
This route uses registered predicates, not newly generated executable checkers.

The final focused run on the implementation committed as `9b5d11574a` passed
**5 tests across two files in 65.7 seconds**, retries disabled:
`tests/iterative_episode_refiner/test_reviewed_check_design.py` (2), and
`tests/episode_runtime/testing/test_registered_measure_preparation.py` (3).
The latter preserves registered-grounding applicability and ordinary admission
alongside the new route. An earlier separate run also passed
`test_measure_control_experiments.py` (1). These are distinct runs, not a claim
that the whole suite passed on this head. Ruff and `git diff --check` passed.

The four-file compatibility run started on the same source was subsequently
stopped as recorded above. Before interruption it passed `test_campaign_state.py`
(9), `test_control_integrity.py` (2), and `test_reports.py` (4). The native nested
case uses supplied model decisions and target outputs; it was interrupted without
a pass and cannot establish live reasoning or behavioral repair.

### Live missing-measure finding and fixed-controller correction, 2026-10-03

The one-start Run from `7222da1a21` below progressed beyond its initial Verify
child. Its root Parts corrected the rejected full-scope subdivision and called
a narrower Parts child, which entered Designer. At Run event 77, admission
rejected the design with `implementation measure has unresolved requirement
coverage`. Designer then called EstablishMeasure for `stopping`, `epistemic`,
`progress`, `unit` and `numeric_control`.

The committed prerequisite
`refinement_d04b5c5b3ff01a37a0f45ee76145d708057baef9403394e9ecec6ead2826d4d7`
records `grounding_required` for those fields and no instrument-building reference.
Inspection of the exact campaign policy confirms three grounded cases (the
scheduling goal at three purposes), zero instrument-building routes and zero
acquisition routes. This is a missing normal-build capability, not evidence
that further model retries can obtain the required checks. Existing construction
primitives require a supplied specification; this job did not provide one.

The development job was cancelled before source changes. Durable job and Run
records both confirm `cancelled`, `verified_build` is null, and the final Run
index records 123 events, five invocations started, two completed, six completed
units and seven model requests with six responses. No candidate source edit,
Target Workflow Run, accepted repair or final acceptance is established. No
operator supplied missing measures or manually launched a next stage.

The live output also confused the composer with the continuation predicate.
Admission already required exact composer/credit identities, but planning did
not supply those host-owned facts. Builder planning and scoped refiner repair
now install the same authoritative bindings through `plan_choices`; their
contexts expose them. Task-specific choices remain model-owned. Saved-plan
checks still reject changed fixed bindings instead of repairing them during
validation. The Measure prompt also no longer offers `approved_review`, which
the current admission route cannot accept.

The new Builder regression was reproduced red (**1 failed in 2.7 seconds**).
After correction, the canonical runner passed **3 tests across 3 files in
4.8 seconds**, retries disabled: `test_fixed_numeric_bindings.py`,
`test_refinement_plan_resolution.py` and `test_reference_context.py` under
`tests/episode_builder`. A second focused run passed **6 tests across 2 files
in 30.1 seconds**: binding-contract matching and plan feedback. These use
supplied model responses and check construction/admission behavior, not live
reasoning or measurement construction. The missing normal-build measurement
route remains unresolved; these corrections do not establish acceptance.

Repeatable-call materialization and reasoning-workflow checks also passed:
**4 tests across 2 files in 189.6 seconds**, retries disabled. This includes
the real systemd reasoning worker with supplied model responses, in addition
to in-process execution. Across these three focused runs, **13 tests passed**.
Ruff, JSON parsing of the setup record and `git diff --check` pass. No new live
model build was started after discovering the missing measurement route.

### Live one-start retry after host feedback correction, 2026-10-03

Clean source `7222da1a21` started the ordinary build entry once:
`build_request_2f512662e164f8a9f46cad98a884254b94180cefd01c0450fe767be405855f32`.
The actual owning Duet route is unchanged, separate from the approved Target
Workflow launch. The initial receipt
`build_receipt_83028c19946fe7e368664b00a71a06ceffcac62d8800b3b48511739d9d786846`
reports an invalid pre-emission generated-function identifier, missing source
and a mismatched numerical composer binding. It emitted no module.

OpenChia automatically continued into native systemd refiner Run
`run_11c36b0e256340542a5ed70b287e99e90d04b933b2b6a13c224c4ff70c866d89`, through
`experiment_c25d2a8b6bd00b97ef9ab4782cc8f570a38763ec6b765db41e1aeac3d6bfb1a3`.
At this observation the initial Verify child has returned and the parent has
issued its first live model request. The job is live, not accepted or complete.
No candidate edits, supplied model responses or manual stage starts were used.
`acceptance/setup_inputs.json` identifies this attempt separately from the
cancelled predecessor. This receipt proves the repeated automatic handoff,
not source repair or target correctness.

### Live Designer feedback defect and cancellation, 2026-10-03

The one-start job below reached its Designer after the Parts Episode corrected
an invalid assignment-reference proposal through the normal loop. The Designer
then proposed two plans. Each covered all 16 assigned contribution keys and
included one extra, preservation-only key. Both were rejected with "plan must
cover the assigned contribution," although neither omitted a contribution key.
The missing/extra distinction matters to the next repair decision.

The operator cancelled the whole job before changing host code. The durable
job result records `cancelled` and no verified build. No operator changed the
candidate, waived admission, or manually launched another stage. This proves
automatic handoff and feedback-driven proposal correction, not source repair
or independently accepted target behavior.

The focused regression reproduced the misleading error before the fix:
**2 failed in 23.1 seconds**, with retries disabled. The fix retains exact-key
equality but reports both missing and unexpected keys. Proposal guidance also
shows complete artifact-reference objects instead of suggesting ID strings.
The canonical post-fix run passed **13 tests across three files in 67.9 seconds**,
retries disabled: `test_plan_feedback.py`, `test_campaign_state.py` and
`test_control_integrity.py` under `tests/iterative_episode_refiner`. Corrected
plans admit without changing candidate code or earning credit from plan admission
alone. These are host feedback/admission checks, not live acceptance. Ruff and
`git diff --check` pass.

### Ordinary launch compatibility after automatic refinement, 2026-10-03

The old launch fixture failed on the current tree (**1 failed in 2.9 seconds**)
because it supplied no owning Duet binding and expected `/build` to finish at
`materialized`. It now binds a distinct supplied refiner route, starts the normal
build, waits for the real refiner call, and explicitly cancels the job. The
cancelled job retains admitted source; the subsequent explicit `/run` tests
launch approval, nested experimental dispatch and host measurement as before.
Both target and tester builds take this route. No production preflight, refiner
handoff or final-acceptance check was bypassed or weakened.

The focused canonical run passed **1 test in 91.9 seconds**, retries disabled.
The final combined run with `tests/agent/test_build_refinement_job.py` passed
**3 tests across two files in 107.5 seconds**, also without retries. The existing
native failed-build handoff/cancellation case remains green. Ruff and
`git diff --check` pass. Model choices and in-process confinement
attestation remain fixtures. This proves compatibility of explicit `/run` with
admitted source from a cancelled build, not successful whole-build refinement.

### Live one-start build reaches the native refiner, 2026-10-03

From clean source commit `899ff4a220`, the ordinary `OpenChiaHost.start_build`
entry started build request
`build_request_c83fa094bd72734af5604677e45dd990212511f6c0e2a5ba4c9a2e8257e2a722`.
The owning Duet is a fully initialized `AIAgent`, bound through `bind_duet`,
using the existing conversational configuration (`gpt-5.6-sol-900k`, `xhigh`).
The Target Workflow and its Builder retain their separately approved launch.
Only the build start and status inspection were operator calls; no operator
launched the refiner, supplied a model answer, or edited the candidate.

The real initial Builder response failed planning: generated binding 5 did not
use the required pre-emission `generated` identifier. The retained receipt is
`build_receipt_69fc4b020becd3ddba3484324e9208dc560002fa17c10295e36cf0d55e426bad`,
with zero emitted modules. OpenChia automatically advanced the same job to
refinement and started native systemd Run
`run_e0a83dce815f8e0bbd664236b1d10c8d9466b4a054bf3528c183838c5ff44b38`
through experiment
`experiment_142e3745046a5c506369045ba4e43323bf4723ea6edbb605590fbb9521fd9d32`.
The committed Run prefix shows the initial verification child completing and
the parent issuing its first live model request. At this observation the job
is still running; no repaired or independently accepted build is claimed.

An earlier invocation in this session passed the reasoning configuration helper
arguments incorrectly. It was cancelled before refiner execution, preserving
`build_request_cc7421893aa9af574d0d4d7ea679876b031e7e0f0cade0c3ee1fc8edd5329e0b`
as a cancelled job. That operator setup error is not acceptance evidence. The
corrected invocation above preserves the actual Duet reasoning configuration.

### Admitted checks reach parent validation, 2026-10-03

The canonical runner passed **9 tests across five files in 123.5 seconds**,
retries disabled: `test_registered_measure_preparation.py`,
`test_campaign_measurements.py`, `test_measure_control_experiments.py`,
`test_refinement_experiments.py` under `tests/episode_runtime/testing`, and
`tests/agent/test_build_refinement_job.py`.

Normal-build campaigns now declare local and acceptance measure groups before
refinement starts. Admission retains the original check and projects it into
the matching group with the same predicate, controls, execution binding, guards
and evidence. Parent validation discovers those checks through the existing
evaluation resolver and shared experiment service. It rejects omission of a
new mandatory check; earlier requests retain their original exact check sets.
Grouping earns no additional adequacy credit. Final provenance follows the used
checks back to the original measure admission and its controls and limitations.

The new integration case uses independently derived scheduling controls and
supplied target answers. The common measurement service reports the correct
answer as passing and an infeasible answer as failing under the parent's group.
Neither measurement grants parent acceptance by itself. This is measurement
integration, not execution of the supplied answers by a candidate or live repair.
The existing native handoff/cancellation limits below still apply.

An initial focused run failed because group bindings were mixed into the source
measure's binding list. The existing record validator rejected that mismatch.
The fix preserves that validator and derives group bindings from the admitted
projected checks. Focused reruns passed **3 tests in 39.0 seconds**, then **3 in
42.9 seconds** after adding the shared-service measurement case.

Remaining gaps include measurement coverage beyond the exact scheduling goal,
live autonomous repair/acceptance through one start, and the older launch-fixture
compatibility failure. This receipt does not establish whole-build acceptance.

### Registered task grounding and Measure-to-parent return, 2026-10-03

The canonical runner passed **7 tests across four files in 77.2 seconds**, retries
disabled: `tests/episode_runtime/testing/test_registered_measure_preparation.py`,
`test_measure_control_experiments.py`, `test_scheduling_measure.py` in that same
directory, and `tests/agent/test_build_refinement_job.py`. Ruff and
`git diff --check` also pass. No live model call was made for this receipt.

The new integration test approves/builds the scheduling fixture, prepares the
campaign through the normal preparation code, and gets its measurement cases
from the registered source and original requirements. It does not supply the
expected optimum or controls. The independent exhaustive solver supplies those;
Measure uses the existing proposal/admission route and common control judgments.
A forged expected-answer case is rejected with no checks or facts admitted.
The valid case distinguishes positive, infeasible, suboptimal and empty-answer
controls. Its typed return gives the parent a useful new measurement decision,
not whole-build acceptance. A second case changes the approved worker count:
the familiar benchmark ID alone does not make the source applicable.

The parent-return regression was reproduced by restoring the old `_fact_keys`
call: **1 failed, 1 deselected in 13.4 seconds**, with a missing `proposal`
argument while closing the parent unit. Restoring the fix gives the passing
combined result above. The initial focused run passed **2 tests in 24.5 seconds**.

The existing independent-checker controls and supplied-answer scheduling tests
remain green. Normal-build failed-attempt handoff/cancellation still passes
through the real systemd worker, and materialized-build handoff passes in-process.
Those use supplied model responses. The new measurement test exercises host
admission, parent return and credit, not autonomous reasoning or target execution.

**Still unverified/incomplete:** whole-build adoption of newly admitted measures,
measurement coverage beyond the supported scheduling goal, and live autonomous
repair through one start. The older launch-fixture compatibility failure below
has not been retested or fixed by this change. The goal is not complete.

### Normal build → refiner handoff and cancellation, 2026-10-03

The canonical runner passed **12 tests across four files in 67.7 seconds**, with
retries disabled: `tests/agent/test_build_refinement_job.py`,
`tests/episode_builder/test_reference_context.py`,
`tests/episode_runtime/testing/test_refinement_job_experiments.py`, and
`tests/openchia_cli/test_openchia_cli_commands.py`.

The normal entry is called once. A rejected initial Builder output enters the
real refiner in a native systemd worker, uses its owning Duet's route rather than
the Target Workflow launch, and stays in the same active build job. Cancellation
retains the original failed receipt and the cancelled refiner evidence, verifies
the exact worker stopped, and survives reopening the host. No second human
approval is added. A separately materialized initial build enters the same
refiner path in-process. Both use supplied model responses and cancel at the
first refiner request; neither demonstrates a behavioral repair or acceptance.

Builder reference evidence now contains the registered function implementations
in both planning and emission context, bound to the plan's evidence hash. Its
regression failed before the fix and passes. The fixed refiner adapters use
ordinary Builder source admission; no model response is fabricated in production.

A separate implementation-plan regression failed on a stale
`design_choice_unresolved` finding, then passed (**1 test in 2.7 seconds**).
Revised node choices replace only that node's old implementation uncertainties;
current unresolved choices and authority restrictions remain. The original plan
is immutable and host-derived channel identities remain mandatory.

The older `tests/agent/test_episode_testing_launch.py` currently fails (**1
failed in 3.0 seconds**): its one-shot host fixture has no owning Duet model
binding. It must be updated to exercise the new full lifecycle once behavioral
measure setup is connected; skipping refinement or borrowing the target launch
would not be a valid fix. The broad suite is not claimed green.

Earlier runs of the new handoff test failed on test setup/inspection mistakes:
an empty learning environment, a string passed instead of an OpaqueId, and a
missing executor argument to the stopped-worker check. The passing run above
includes their corrections. These receipts do not establish a green broad
compatibility suite or the full goal.

**Remaining completion gap:** the normal-build campaign still needs the parent's
task-specific behavioral measure setup. Static checks cannot discharge the
original behavioral requirements. Live automatic repair/acceptance remains Task
4; [ADR 0007](../adr/0007-build-owns-iterative-finalization.md) requires the system
to own that work without a manual restart at the Builder/refiner boundary.

### Approved live build: first attempt blocked, 2026-10-03

The human approved the exact scheduling Target Workflow and designated launch
configuration. The ordinary `OpenChiaHost`/`DuetService` APIs recorded the draft,
workflow approval, launch selection and launch approval in a new private workspace
at `/home/chia/repos/OpenChia-acceptance-0RN3r9BH`. No fixture approvals, supplied
model responses or replacement Builder were used. The shared `register-launch`
CLI verified the existing approval and stored its public configuration reference.
Exact IDs are in [the setup record](acceptance/setup_inputs.json).

`OpenChiaHost.start_build` invoked the real model on the approved `reasoning`
slot: `sol_medium`, `gpt-5.6-sol`, medium effort. Its single planning call
succeeded in **168.578 seconds**. The Builder then returned a **blocked** receipt,
with zero planned nodes and zero emitted modules:

- A generated component used an invented `function_...` identifier rather than
  the required pre-emission literal `generated`.
- The model left `result_channel_names` unresolved because the reference did
  not expose its credit schema's exact channels.
- No module was emitted, so whole-build admission also reported `missing_module`.

The saved prompt confirms a concrete context gap: the reference contained its
design module and function metadata, but `pinned_source_files` was empty and
the implementation of `reasoning_credit_schema` was absent. That registered
function actually returns one column; the model proposed four category names.
This is not a missing user choice about the scheduling problem. The separate
invented binding identifier also violated an explicit planning rule. Neither
finding has been silently repaired or waived.

The failed receipt is
`build_receipt_2edf155b421f3efcb8e6dd3f181a023b39534f803143284a1bb77dc2986ce8ea`;
the corresponding model evidence is
`build_model_call_bc445ccfbd1e441d4140a9fe0619a12ca855bddd02843f66a1ebfdd2573b3f6b`.
The ordinary Builder also published its immutable materialization handoff and
refinement baseline. These preserve the failure for subsequent refinement.
The build launched from commit `4213967c09` with a clean checkout; subsequent
changes in this step are setup/receipt documentation only.

The independent solver separately derived optimum 14 and a feasible witness.
Its checker accepted that control and rejected an infeasible schedule claiming
14 and a feasible delayed schedule completing at 15. This prepares measurement
grounding; no criterion was registered against the unadmitted build. These are
not candidate executions or evidence of successful reasoning/repair.

**Task 4 remains open.** No Target Workflow worker or testing Episode has run,
and no repaired build exists. No frozen design, threshold, production source or
admission rule was changed to turn this failure into a pass.

### Native nested continuation: passing shared-service comparison, 2026-10-03

The final canonical run of
`tests/iterative_episode_refiner/test_nested_continuation.py` passed
**1 test in 844.7 seconds**, one worker, retries disabled, with the runner's
operational file timeout set to 1800 seconds. No Episode controller or semantic
stopping threshold changed. This completes task 3's native nested-continuation
verification, not task 4's live reasoning acceptance.

The test executes `Parts → Designer → Implementer` in real confined systemd
workers through `ExperimentService.run` and `continue_run`. It cancels the first
physical Run after Implementer's final unit reply is durable but before the host
accepts the child return. The old worker is verified stopped. Continuation keeps
the logical identity, uses a new executor identity, and checks current authority
both before launch and after reconstruction. Only physical startup events may
precede the reconstruction gate; no old model call, edit, target check or credit
admission is repeated.

The resumed child returns once. Repeating the continuation request returns the
existing Run without another call, edit or credit update. The resumed and
uninterrupted cases have equal terminal disposition, normalized numerical
history, campaign operations, model-call counts, target-check counts and unique
unit counts. Both end with disposition `attained` under the fixture's contract.
During this run, the shared `run-record` CLI also exposed the cancelled original
and succeeded continuation with current indexes: seven original model responses
and two new responses after continuation, not nine repeated responses.

**Evidence limit:** Builder/model decisions and Target Workflow observations are
supplied. The applied source change is a comment, not a behavioral repair. This
proves native refiner execution and continuation through the common service; it
does not prove live-model experimental design, target correctness or autonomous
repair. Those remain task 4. The nine focused passes below plus this final pass
resolve the known failures; the entire 64-file suite was not rerun green.

### Focused continuation rerun, 2026-10-03

The six-file canonical rerun finished **9 passed, 1 failed in 719.0 seconds**,
two workers with retries disabled. Reasoning execution passed both in-process
and confined cases (**217.8 seconds** for that file), along with confined
single-Episode continuation, execution admission, refiner-job routing and CLI
continuation. No Episode stopping threshold changed.

The remaining nested test reached the real executor's continuation preflight,
past the corrected frozen-starting-state lookup. Its own inspection callback
then incorrectly tried to read an unpublished Run's journal. The executor
deliberately authorizes before publishing the new registration, then authorizes
again after worker reconstruction. The assertion was changed to distinguish
those two stages, and the interrupted case moved before the uninterrupted
comparison.

The next one-file run **failed in 266.0 seconds** at the second stage: the
callback still incorrectly required an empty journal, overlooking the native
executor's `runtime_ready` and `run_started` events. It reached that stage
without repeating campaign effects or model calls, but did not admit new work.
After reviewing the executor and reconstruction sequence, the callback now
allows only those physical-startup events before activation. The final audit
check locates the single `run_reconstructed` event after startup instead of
assuming it is the journal's first event. It still forbids new Episode work
before authorization and checks unchanged original evidence, campaign effects,
model calls and target executions. Native nested recovery was not yet a passing
claim at that point; the subsequent passing comparison is recorded above.

### Compatibility after native setup, 2026-10-03

The canonical check finished **343 passed, 1 failed, 2 skipped across 64 files
in 883.9 seconds**, with three workers, retries disabled and runtime sources
unchanged throughout. It covered runtime, Builder, refiner and method-loop tests,
reasoning selection, repeatable calls, ordinary testing launch, launch setup and
CLI continuation. The nested continuation comparison ran separately below.

The sole failure was the confined reasoning fixture's separate **180-second
`wait_for`**. The trace shows it handling a learning `select` request at unit
ordinal 18 when cancelled; it is not a launch or AppArmor refusal. Native
single-Episode continuation and service lifecycle checks passed in this batch.
The optional live-model and live-container cases skipped. This is not a
whole-system acceptance pass, and the timeout is not attributed conclusively to
load or to a specific storage cost.

The reasoning fixture now relies on the canonical runner's operational file
timeout instead of its own additional deadline. Its frozen continuation threshold
remains **0.1**, not the reference/live-benchmark default **0.01**; these timings
are not performance evidence for the default. The nested-continuation lookup
described below is also corrected. The subsequent focused result is recorded
above; the Episode controllers and their thresholds are unchanged. Focused
Ruff and `git diff --check` pass.

### Native nested continuation: first shared-service run, 2026-10-03

The nested comparison now calls `ExperimentService.run` and `continue_run`
through the actual systemd executor, worker pipes and current-authority gate.
The former test-only loopback/reconstruction driver is removed. Refiner model
choices and Target Workflow observations remain supplied fixtures; the source
change is a comment, not a demonstrated behavioral repair.

The first canonical check, one worker with retries disabled, **failed after
694.5 seconds**. Uninterrupted `Parts → Designer → Implementer` execution passed
its assertions. The interrupted case durably closed Implementer's unit, stopped
the physical worker and retained the waiting parents. The common service then
refused continuation before launching a replacement worker: `execution.py`
looked for `plan.subject.starting_state`, whereas the frozen preview stores it
under `plan.scope.starting_state`. This is a continuation defect, not an
AppArmor failure or a passing recovery receipt. Task 3 remains open.

### Approved AppArmor setup and installation diagnostic, 2026-10-03

The operator approved the executable-specific exception. The reviewed
`scripts/apparmor/openchia-systemd-executor` was installed as root-owned mode
0644 at `/etc/apparmor.d/openchia-systemd-executor` and loaded with
`apparmor_parser`. AppArmor remains enabled and
`kernel.apparmor_restrict_unprivileged_userns` remains **1**. The exception
applies to all services using `/usr/lib/systemd/systemd-executor`, not only
OpenChia. No systemd upgrade, global AppArmor disablement or replacement
executor was used. Setup and reversible removal are documented in
[the systemd setup guide](systemd_setup.md).

The real diagnostic returns `ready` on systemd **255.4-1ubuntu8.17**, having
observed distinct mount and network namespaces. Source installation (including
unattended installation) and `hermes doctor` invoke the same diagnostic. It does
not run an Episode or access model credentials, and never installs security
policy automatically, including under `doctor --fix`.

The four-file canonical CLI check, three workers with retries disabled, passed
**21 tests in 7.3 seconds**: diagnostic behavior (3), source completion (6),
doctor exit status (7), and source-update compatibility (5). The diagnostic test
executes the real namespace probe; the refusal cases also cover systemd accepting
properties without creating the namespaces. The install-path assertion confirms
unattended installation invokes the check without requesting policy changes.

After the policy was installed, a three-file native/runtime check first returned
**4 passed, 2 failed in 54.2 seconds**. Native service inspection and descendant
termination passed, but the full worker exposed a pre-existing startup race:
the host rejected an inactive unit before its first invocation. Correcting that
race exposed a second issue in the previously unexercised worker path: importing
library definitions did not preload their lazily referenced implementations
before Landlock. The next two-file check returned **1 passed, 2 failed in
56.8 seconds**, with that explicit loader error. The loader now preloads selected
definitions from verified library exports, without executing generated code
before confinement. The executor also inspects the actual network namespace
instead of trusting the requested property.

The final three-file canonical runtime check passed **6 tests in 198.8 seconds**,
three workers and retries disabled:

- Native service lifecycle and backend attestation: **3 passed** (default and
  explicit resource settings, actual namespace/mount inspection, whole-job stop).
- Confined interrupted continuation: **1 passed**. Two distinct real systemd
  workers preserve the committed model replies and positive credit, verify the
  first worker is stopped, reconstruct through the shared gate, then return
  normally without repeating calls or awarding the same credit twice.
- Reasoning workflow: **2 passed**, one in-process and one real confined worker.
  The native case uses actual host/worker messages and host model audit events,
  including rejection and repair of malformed responses.

Builder/model answers in these runtime checks are supplied fixtures; this is
not the live-model scheduling benchmark. The continuation case is one inquiry
Episode, not the remaining native nested-refiner acceptance. Live container
execution, live-model experimental design and independently checked reasoning
acceptance remain unverified. Focused Ruff and `git diff --check` pass.

### Systemd 255 compatibility work, 2026-10-03

[ADR 0006](../adr/0006-support-systemd-255.md) records the approved compatibility
decision. The current worktree removes the unsupported `PrivatePIDs` request and
mandatory private-PID attestation for systemd only; the container requirement is
unchanged. Direct host cgroup-allocation discovery is removed. Explicit resource
settings and whole-service stop behavior use systemd's existing interfaces.

The canonical two-file check, two workers and retries disabled, returned
**17 passed, 2 failed, 1 skipped in 2.8 seconds**. Container checks passed
**16**, with their live-daemon case skipped. The attestation invariant passed,
including rejection of weakened container isolation and of missing other
systemd isolation facts. Both real-systemd service cases failed before the helper
program started. The test covers default and explicit resource settings, actual
mount inspection, and termination of the service and its child; those native
claims therefore remain **unverified**, not passing.

The service journal reports `226/NAMESPACE` and failure to establish mount
namespacing. The matching kernel audit records AppArmor denying `sys_admin`
inside `unprivileged_userns` for `/usr/lib/systemd/systemd-executor`. The network
namespace request was also skipped by systemd for lack of privilege. This is
distinct from the earlier unknown-property rejection. An explicit `PrivateUsers`
diagnostic encountered the same denial; no additional namespace mechanism is
being added to the worker.

A separate four-file canonical check, three workers and retries disabled, passed
**15 tests in 15.6 seconds**: continuation identity (2), worker stderr diagnostics
(2), executor HTTP protocol loop (1), and egress contracts (10). The HTTP-loop
test uses real pipes and stores but a supplied worker/inspection; it does not
prove native confinement. Focused Ruff and `git diff --check` pass.

The obsolete synthetic cgroup-hierarchy tests were replaced with the real-service
and backend-attestation checks in `test_systemd_executor.py`; their old source is
recoverable from Git. At this point no host security policy had been changed and
operator approval for a launcher-specific AppArmor exception was outstanding.
Full native worker continuation and live model-directed acceptance had not been
rerun on that edit. The later approved setup is recorded above.

### CLI HTTP credentials and compatibility corrections, 2026-10-03

The five-file canonical check finished **69 passed, 1 failed, 1 skipped in
60.7 seconds**, with Python sources frozen, three workers and retries disabled.
It covered CLI continuation, container arguments, the testing-Episode loop,
non-native reasoning execution and the 50 egress-contract checks. The already
diagnosed native reasoning test was explicitly deselected; the live container
test skipped without its configured image. Neither is counted as a pass.

The sole failure was in the new CLI fixture before build or execution: it omitted
the inquiry contract's required environment conditions. After supplying an
explicit fixture environment, the CLI file passed **2 tests in 8.6 seconds**,
retries disabled. All other files had passed the preceding check. These are
separate receipts, not a claim that the broader 66-file batch was rerun green.
Focused Ruff and `git diff --check` pass.

Live CLI `run` and `continue` now supply HTTP credential descriptors through the
same active-profile config reader, egress parser and `ScopedHttpBroker` as the
host service. The CLI check uses fixture-approved egress and launch contracts,
actual Builder admission, config files, profile/secret scopes under multiplex,
the real HTTP broker and existing stores. Only the executor and outgoing HTTP
transport are supplied. Calls under profile A, then B, then A carry the matching
token. The assertions retain exact interruption rejection, continuation identity,
idempotence and unchanged original evidence, and verify that CLI output and saved
Run evidence/audit contain no token values. A second check confirms malformed live
credential configuration fails for live modes but does not affect numerical or
recorded modes. No credential store, launch-auth fallback or new runner was added.

The container fixture now uses a real registration and verifies physical/logical
Run identity propagation. The testing-Episode fixture now relies on the canonical
runner's file timeout; its numerical threshold and credit assertions are
unchanged. Its functional loop passed in 40.5 seconds in this check. The earlier
unchanged rerun and broad-run timeout remain recorded below.

The guide now documents exact launch approval, retained report/attempt queries,
scoped control history, unsupported executable child-result substitution, the
owning-Duet service required for fresh refiner experiments, and existing HTTP
credential configuration. These changes do not establish native confinement,
live-model experimental design, a real-model scheduling answer or autonomous
repair. The two native `PrivatePIDs` failures from the broad run remain unresolved;
live acceptance still requires its actual human-approved workflows and launches.

### Broad compatibility check after campaign routing, 2026-10-03

The canonical runner finished **444 passed, 4 failed, 2 skipped across 66 files
in 1003.2 seconds**, with Python sources frozen, retries disabled and 12 workers.
It covered `tests/episode_runtime/`, `tests/episode_builder/`,
`tests/iterative_episode_refiner/`, `tests/method_loop/`, reasoning selection,
ordinary-host testing launch, repeatable Episode calls, egress allowlist contracts,
launch setup and CLI continuation. Nested loopback continuation passed, including
the comparison against uninterrupted refinement. Scoped execution, unit execution,
campaign-source routing, records and shared refiner experiments also passed.

The four failures are retained explicitly:

- The container argument fixture supplies a `SimpleNamespace` missing the new
  logical Run identity fields. Production argument generation requires the real
  registration; the fixture needs correction.
- Native continuation and native reasoning-worker checks both fail before worker
  inspection: this host rejects the required `PrivatePIDs=yes` systemd setting.
  Confinement was not relaxed and these are not passes.
- The scripted testing-Episode integration hit its own 60-second `wait_for`
  deadline while awaiting the host learning broker. The output establishes a
  timeout, not its cause or an infinite loop. An **unchanged** focused canonical
  rerun then passed **1 test in 27.6 seconds**, retries disabled. This supports
  a load-sensitive timing diagnosis; the failed journal was not retained, so
  contention is not proven. It is not grounds to change the numerical stopping
  rule. The fixture now relies on the canonical runner's existing file timeout
  instead of a separate 60-second deadline on the functional loop.

The container live-image test and optional live-model acceptance test skipped;
neither provides native or live reasoning evidence. The passing tests retain
their supplied-response/in-process/loopback limitations. This is a compatibility
receipt, not successful whole-system or real-model acceptance. No testing or
continuation rule was changed during the run.

### Campaign source routing and authorized discovery verified, 2026-10-03

The final focused canonical run passed **6 tests across five files in 137.3
seconds**, with Python sources frozen and retries disabled:
`test_campaign_source_experiments.py`, `test_worker_access.py`,
`test_campaign_measurements.py`, `test_numerical_execution.py` and
`records/test_continued_history.py`. Focused Ruff and `git diff --check` pass.

Both editable-instrument and read-only-reference cases use actual approved
fixture builds, campaign assignment admission, an authenticated model-response
event for the supplied experiment proposal, the common ExperimentService,
generated stock reasoning source, and the existing in-process LinkedExecutor.
No execution occurs before the Episode proposal. Wrong candidate, build and
measure references fail both assignment validation and shared preview. The
source's empty failed attempt returns integer zero credit, and the parent-owned
exact-value criterion passes without granting parent acceptance. Repeating the
experiment does not execute it twice. Source identity and namespaced instrument
files remain distinct from the primary target.

An independently fixture-approved Testing Episode session follows preview,
run, inventory and report queries for its exact assigned experiment. The tester,
campaign and executable have different owners. Unassigned experiment inventory
and direct foreign-Run browsing are rejected. Numerical replay uses the exact
source recording (including that same recording as parent context) and exposes
its inventory. Recorded-response execution explicitly diverges because the
stock reasoning prompt contains Run-specific provenance; it never rewrites the
prompt or calls the live transport. The original audit and campaign state remain
unchanged. Retained report pagination across an interrupted/continued experiment
also passes through the existing worker-interface test.

The preceding corrective run passed **11 tests and failed 2 across seven files
in 140.4 seconds**. Its source executions succeeded, but the new fixture supplied
floating-point `0.0` to an exact JSON predicate whose observed credit was integer
`0`. The fixture now uses the actual integer representation; the predicate and
yield rules were not relaxed. That run also passed the existing direct/independent
checker, measure-control, execution-history and continued-history tests.

These receipts complete task 1's shared refiner-routing work. They use supplied
choices and model answers, fixture approvals and in-process execution. The
auxiliary source fixture uses a **0.9** continuation threshold for this mechanical
check, not the shipped **0.01** live-acceptance configuration. They do not establish
autonomous experimental design, behavioral repair, real-model reasoning, native
confinement or final whole-system compatibility. Tasks 3, 4 and 5 remain open.

### Campaign instrument/reference experiments: first integration check, 2026-10-03

The canonical five-file run finished with **8 passed and 3 failed in 104.5
seconds**, with Python sources frozen and retries disabled. Existing target and
independent-checker experiments, grounded measure controls and execution history
passed. An ordinary campaign measurement correctly rejected an unadmitted check,
but the new source resolver misclassified that rejection as a control-context
error. Both new auxiliary-source cases stopped at a test fixture's nonexistent
campaign field before execution. Those failures are being corrected; this run
does not verify the new source routes.

Read-only review also found worker inventory queries using the executable owner
where the experiment owner was required, and report queries using the testing
Episode owner where the measurement owner was required. Both corrections must
retain exact experiment-access checks; general cross-owner browsing is forbidden.

### Later-unit learning and numerical history, 2026-10-03

The canonical run passed **41 tests across seven files in 304.2 seconds**, with
Python sources frozen and retries disabled. Files: `test_later_unit.py`,
`test_epistemic_learning.py`, `test_learning_continuation.py`,
`testing/test_unit_execution.py`, `testing/test_numerical_execution.py`,
`testing/test_reconstruction_source.py` and
`tests/method_loop/test_episode_tree_recursion.py`.

The new experiment test uses the real Builder, common ExperimentService,
generated stock reasoning Episode, linker, ledger and stores, with supplied
model replies and an in-process executor. It runs an original Episode, captures
its second unit, and executes only that unit under a new experiment identity.
Exactly two new model calls select and execute the unit. Its prior lesson and
evidence identities survive; operative scope/equivalence move to the new
invocation. Inherited credit is explicit and the repeated failure earns zero.
The original audit is unchanged, repeating the experiment adds no events, and
the public store validator rejects forged historical-credit reset and state
discard. Numerical replay of the new experiment primes the inherited observation
history and reproduces the recorded controller decision without calls or credit.

The existing nested first-unit scope, learning continuation, source-admission,
numerical and method-loop checks also pass. This is not native confinement or
live-model reasoning evidence, and does not prove arbitrary Python restoration,
changed-build transfer, continued/scoped source reuse or historical refiner forks.

Subsequent review found that direct generic-executor callers could bypass the
shared service's source-shape check. The same checker now runs during package
preparation; a new assertion probes a forged source-admission receipt. Numerical
preview also now exposes inherited-history references/counts. The focused
canonical rerun passed **8 tests across four files in 33.1 seconds**, with
Python sources frozen and retries disabled: later-unit execution, reconstruction
source admission, experiment planning and numerical execution. It verifies those
final additions. Focused Ruff and `git diff --check` also passed. These receipts
do not close task 1 or the overall goal.

### Unit starting-prefix discovery, 2026-10-03

The canonical run passed **4 tests across two files in 266.9 seconds**, with
Python sources frozen and retries disabled. The record test discovers first-unit
and later-unit starting-prefix references without loading the Run audit, retains
exact-prefix pagination, and reports a gap for missing predecessor units. The
generated nested-Episode test confirms that verified CLI/worker boundary capture
derives the same references as indexed inventory. First-unit execution still
uses the shared service and loop; later-unit execution is still refused rather
than reset to fresh state.

This proves selector agreement and preserves existing unit-scope behavior; it
does **not** prove later-unit state restoration. The generated-code test uses
in-process execution and supplied model responses, not native confinement or
live reasoning. A read-only review found no access expansion and identified the
documented limits for incomplete history and parents in earlier physical attempts.
Focused Ruff checks passed. The machine discovery description was then updated
to name the new selector without changing execution availability.

### Scope discovery terminology checks, 2026-10-03

The focused canonical run of experiment planning and recording recovery passed
**3 tests across two files in 7.6 seconds**, with retries disabled. The discovery
and preview descriptions now distinguish a new saved-input experiment from
continuing an unchanged interrupted execution. This was a vocabulary correction,
not implementation or proof of arbitrary checkpoint restoration.

### Nested reconstruction matches uninterrupted refinement, 2026-10-03

The corrective canonical run reported **69 passed, 4 failed across eleven files
in 751.2 seconds**, with Python sources frozen and retries disabled. The complete
nested comparison passed: the actual generated Parts → Designer → Implementer
loops ran once uninterrupted and once interrupted after the Implementer's final
host reply, before its return to the waiting Designer. The shared reconstruction
gate matched the saved prefix and restored the host session. Both executions
produced matching terminal disposition, normalized controller history, operation
counts and unit counts. The resumed case retained the original audit, returned
the child once, and repeated no model choice or source edit.

This is **loopback worker transport with supplied decisions, target observations
and process authority**, not native confinement or live-model reasoning. The
source change is a comment; no behavioral repair is claimed. It establishes
nested restoration mechanics, not general autonomous refinement.

The CLI continuation and continued-history checks passed, including exact
reference validation, idempotent dispatch, retained reports and explicit
per-attempt inventory. Both direct and independently built checker experiments
passed; the latter continues its interrupted checker without rerunning the
target. The stock testing-loop check, existing execution-history checks and
57 allocation cases also passed.

Two failures were stale fixture expectations: the measurement test expected the
older ownership error wording, and the worker test omitted the now-required
attempt selection from continued inventory. After correcting those fixtures,
their focused canonical rerun passed **2 tests across two files in 39.9 seconds**,
with retries disabled. The real worker protocol fixture now consumes the
advertised inventory query for its selected physical attempt and rejects unowned
continuation; process attestation and target results are still supplied. The
other two failures are native launch checks,
both rejected before activation by systemd 255's unsupported `PrivatePIDs`.
They remain failures, not skips or passing isolation evidence. The existing
container backend cannot be used here until a runtime is configured.

Focused Ruff checks over the shared testing/record packages, refinement package,
new transport/control components and their tests passed. Whole-system acceptance
and compatibility remain incomplete.

### Continuation interface failures and nested baseline, 2026-10-03

The next canonical run, with Python sources frozen and retries disabled,
reported **11 passed, 8 failed across ten files in 393.0 seconds**.
Five failures shared one defect: two new per-attempt report ID prefixes exceeded
the existing 32-character opaque-kind limit. The centralized record identity
function now uses shorter namespaces for those new kinds; existing record IDs
are unchanged. This was not five separate execution or authorization defects.

Two native tests failed before worker activation because the systemd launcher
serialized an unbounded CPU quota as `CPUQuota=infinity`. It now uses the empty
assignment specified by [systemd's resource-control contract](https://github.com/systemd/systemd/blob/main/man/systemd.resource-control.xml).
The existing allocation invariant also checks finite-quota preservation and the
different CPU versus memory/task unbounded encodings.

The compact parent-report tests passed. The actual nested, supplied-decision
baseline reached `succeeded`, including parent acceptance, before the comparison
fixture failed by reading the child-only `states` field from the root result.
That assertion now checks the root's actual `report_id` and `disposition`.
The interrupted half was not reached; this is still not restored-loop proof.

The corrective run (reported above) reached
a separate environment limitation: this host has systemd 255, which rejects
`PrivatePIDs=yes`; that isolation setting was [added in systemd 257](https://github.com/systemd/systemd/blob/main/man/systemd.exec.xml).
Read-only discovery found no Docker-compatible CLI for the existing alternative
backend. Native execution is not demonstrated, and the isolation requirement has
not been removed. Container setup requires the operator's direction.

### Shared continuation admission and nested-return failure, 2026-10-03

With Python edits frozen, the canonical runner reported **9 passed, 1 failed
across six files in 197.8 seconds**, with retries disabled. Shared execution,
current continuation authority, measurement, direct/independent-checker refinement
experiments and owning-Duet refinement-job tests passed. Their supplied outputs
and in-process execution do not establish live reasoning or native confinement.

The new nested continuation test failed in its uninterrupted baseline: returning
an attained Implementer to its Designer made the host reply exceed the default
1 MiB protocol limit. Thus this run proves no nested restoration. Parent context
now uses a deterministic report overview with exact evidence references rather
than embedding duplicated full observations; the full typed report remains in
shared history. Verification of that correction is pending.

Read-only host checks found a running user systemd manager and a valid effective
resource allocation. The existing confined-worker test then **failed before
launch** in 8.3 seconds because its caller omitted the required `http_broker`.
That fixture call is corrected; this failed run is not confinement evidence.

The CLI/Episode continuation operation and retained per-attempt measurement
reports have since been connected. Their new service/CLI tests remain pending.

### Reconstruction admission and cross-attempt learning, 2026-10-03

A frozen-source canonical run with retries disabled reported **53 passed,
1 failed and 1 collection error across eight files in 342.3 seconds**.
The failure found a missing `continuation_admission` parameter on the concrete
executor method (it had only been added to the protocol). The collection error
was an imported `testing_learning_contract` helper picked up as a test. Both
are corrected. The focused identity, source-admission and reconstruction rerun
passed **14 tests across three files in 53.8 seconds**, with retries disabled.

The three learning-continuation cases passed against real Run storage and
host admission. They retain original evidence/credit across multiple physical
attempts, reject a forged reset or dropped prior state at public publication,
and complete an interrupted ledger commit exactly once. These are ledger checks;
an incomplete host exchange is still unsupported for worker reconstruction.

The extended unit-scope check passed. A resumed testing invocation retains its
owned experiment, history and recording/boundary permissions under the logical
Run identity; a distinct execution does not inherit them, and a completed
invocation loses active caller access. Caller-start boundaries are supplied.

Four intended source-admission cases passed for actual admitted reasoning,
testing and refinement packages and rejected non-stock code. No generated
module is activated on the host. Eight reconstruction checks passed, including
the executor's new host gate over all recorded channels, one durable activation
receipt and re-interruption without copying history. Source/authority facts in
that gate fixture are supplied; it is not a native executor or nested-coroutine
continuation receipt. The existing learning, broker and three host-restoration
checks also passed. Service/CLI continuation and the real nested return remain
unfinished.

### Continuation authority and original-response provenance, 2026-10-03

The next frozen-source check reported **6 passed, 1 failed across three files
in 69.6 seconds**. The failure was a new test reading the database-only
`revoked_at` name from the public approval API, which exposes `revoked`. After
correcting that assertion, the focused open-child case passed in **19.2 seconds**.

The test commits a model response through the real broker, interrupts before
proposal admission, restores host state, and authenticates the proposal against
the exact predecessor event. The original physical Run/event remains its
provenance; the new journal stays empty and no model call or credit is copied.
Malformed proposal JSON still receives rejection/zero progress.

It then uses the existing Duet note, refinement request and approval APIs in
the isolated test store to approve a real implementation successor. The campaign
head is unchanged and the prior approval remains unrevoked, but restoration
rejects its no-longer-current authority. Target and refiner authority checks run
inside the restore transaction and still need rechecking at future activation.
Other identity, refiner-job/numerical and prepared/closed-unit restoration checks
passed. This adds authority/provenance evidence, not a live continuation receipt.

### Host restoration and independently measured schedules, 2026-10-03

A frozen-source canonical run with retries disabled reported **19 passed,
0 failed, 1 skipped across seven files in 84.6 seconds**. The earlier three
fixture failures are corrected: identical claims remain idempotent, a different
executor cannot take the claim, generated modules are released between simulated
process instances, and the numerical decoder receives valid opaque result IDs.

Three new checks drive real refinement host operations through the common broker
and Run journal. They restore a prepared child, a waiting parent with an open
child unit, and a waiting parent after the child's unit receipt. Exact assignments,
goals, handoffs, earlier candidate references and operation ordinal survive; the
original audit and campaign head are unchanged. A later legitimate campaign
change rejects the saved state instead of silently using the newer head. Worker
boundaries and choices are supplied: these are host-restoration checks, not resumed
coroutines, full child-return coverage, native confinement or live reasoning.

Two scheduling-measure checks use the existing criterion registry and shared
measurement service. The single-sourced exhaustive oracle accepts distinct feasible
optima; infeasible schedules with a correct-looking claimed minimum, feasible
nonoptimal schedules, wrong completion times, malformed types and duplicate jobs
fail. Mislabeled controls and caller-supplied optima are rejected. Prose does not
determine the verdict and remains inspectable evidence. The durable result tests
use supplied outputs, not model-produced schedules.

The eight reconstruction checks, refiner-job/numerical integration and negative
decoder check, shared measurement check and offline scheduling oracle also passed.
The old live acceptance test was skipped because no opt-in socket was supplied;
it would not prove native transport even if enabled, so it is not the pending
shared-interface live acceptance demonstration.

A separate read-only audit of the current default host stores found no admitted
build manifests, Run registrations, testing criteria or approved launch selections
for the benchmark/tester. Existing workflow approvals concern other tasks. The
designated launch JSON alone does not grant authority to build or launch new
acceptance workflows; exact workflow and launch approval are still required.

### Shared execution, numerical replay and host allocation, 2026-10-03

A frozen-source canonical run with retries disabled reported **151 passed,
3 failed across 14 files in 377.7 seconds**. Shared scoped/nested and unit
execution, direct/checker refinement experiments, grounded checker controls,
execution history, all eight reconstruction checks, staged imports and the
existing HTTP loop passed. The refiner-job integration now also recomputes its
recorded numerical decisions through the shared service, with no additional
model calls, campaign mutations or credit. Independent publication checks reject
changed prior-opportunity evidence.

The three failures are in new fixtures: expecting an identical executor claim
to conflict (the store intentionally makes it idempotent), loading the same
generated module names twice in one interpreter, and a non-opaque numerical
result ID that fails before the intended decoder check. Their corrections need
a rerun; no production guard was relaxed.

The generic executor's 57 allocation checks passed. Read-only discovery on this
host now succeeds. The earlier diagnosis below was incomplete: CPU controls are
missing below a non-delegating ancestor, not only at the cgroup root. The reader
validates controller/delegation metadata and uses observed ancestor settings;
it neither guesses limits nor treats unreadable or contradictory metadata as
unlimited. This establishes resource discovery, not a successful confined launch.

These remain mechanical/in-process receipts. They do not establish live reasoning,
native confinement or resumed nested execution.

### Owning-Duet refiner-job integration, 2026-10-03

A focused canonical run with frozen Python and retries disabled passed **one
test in 39.3 seconds**. It exercised the shared ExperimentSpec/service path,
actual generated refiner code, a local deterministic HTTP provider and the
existing in-process executor fixture. The host bound the campaign's owning Duet
configuration, kept that exact route when the supplied agent's current settings
changed, and did not use a Target Workflow launch configuration. Rejected-choice feedback
reached the second request. Cancellation remained cancelled/unmeasured with no
completed-build claim. Repeating the same experiment reused its result; a changed
experiment could not silently restart that used campaign. Durable binding data
excluded the fixture credential.

The previous run's 30-second provider wait failed; only the diagnostic wait was
changed before this successful rerun. Its original cause is not established as
a production defect. A subsequent event-based, longer operational test wait and
the queued pre-dispatch/history corrections still require their next check.
The bound agent is supplied, not a fully initialized conversational AIAgent.
This proves that integration path, not live reasoning, native confinement or
successful autonomous refinement. Task 1 still includes refiner numerical replay.

### Reconstruction verification and campaign-fixture migration, 2026-10-03

The canonical runner with Python sources frozen and `--file-retries 0 --tb=short`
reported **21 passed, 1 failed** across seven files in 119.9 seconds:

- Seven reconstruction checks passed using real protocol frames, shared brokers
  and a claimed RunStore, with supplied nested boundary records and host/model
  answers. Exact replies from all five channels were recovered in global worker
  order. Changed request identities, reordered calls and wrong-child calls failed
  closed. A missing committed response or still-active Run could not be replaced
  by an earlier prefix. Exhaustion did not authorize a new action; verification
  left the original journal unchanged and invoked no transports or admissions.
- All ten existing campaign-state/publication-integrity checks passed after their
  fixture was migrated to genuinely admitted target/refiner builds. They retain
  concurrent-head rejection, audited retry, zero credit for unmeasured edits and
  revisits, forbidden Designer/Implementer child creation, and rejection of forged
  completion. No production admission constraint was weakened.
- Direct/checker refinement experiments (two), grounded checker controls (one)
  and staged imports (one) passed again.
- The new Duet-configured refiner-job experiment failed waiting for its local
  provider event. This receipt does not establish that adapter's execution; the
  test is being corrected to expose an early task error rather than mask it with
  the wait assertion, followed by diagnosis of the actual failure.

The reconstruction cursor is a necessary verifier, not a live continuation path.
These supplied-response and in-process tests do not demonstrate live reasoning,
native confinement, restored coroutine state, or authorization to resume arbitrary
generated code. The full continuation and live acceptance requirements remain open.

### Host-state recording and checker controls, 2026-10-03

Three further frozen-source canonical runs used `--file-retries 0 --tb=short`:

- **36 passed, 2 failed** across nine files in 342.2 seconds. Scoped/nested and
  unit execution, direct and independent-checker refinement experiments, shared
  history, scoped reports and staged imports passed. The refiner integration
  verified that the common journal retains host-only call bindings, open-unit
  references and campaign head alongside replies, without placing that state
  in worker-visible results. The failures were a duplicate fixture request ID
  and missing independent publication validation for newly supported control
  evidence; neither was fixed by weakening its guard.
- **23 passed, 1 setup error** across three files in 30.8 seconds after those
  corrections. All-channel recording integrity and exact legacy selector
  compatibility passed. The actual generated checker processed known negative
  and positive inputs through the shared harness. One validated control earned
  one distinct fact without admitting the measure; the second completed the
  all-controls gate, without double-counting admission. Repeated requests added
  no Run or credit. A forged control fact key was rejected at publication with
  the campaign head unchanged. Parent history exposed these as checker-adequacy
  evidence, not repaired-candidate verdicts.
- **5 passed, 4 setup errors** across two existing campaign-state/integrity files
  in 6.0 seconds. Adding the old fixture's missing `evidence_kind` exposed its
  deeper invalid input: it uses a generic host blob where campaign admission
  requires a real BuildReceipt. These compatibility checks have not passed;
  their fixture is being migrated to admitted inputs. Production admission was
  not bypassed.

The first failure above used deterministic `OpaqueId.mint` twice with the same
fixture input; including the request ordinal corrected the fixture. Duplicate
request rejection remains active. The control-credit fix independently derives
permitted fact keys from admitted, scoped control observations at publication;
it does not trust the producer's claimed key or numerical credit.

These results are mechanical/in-process evidence, not live model reasoning,
native confinement or coherent nested continuation. Host-state capture is only
one prerequisite for reconstructing an interrupted worker and its waiting parents.
No continuation operation is advertised as available.

### Live Run prerequisite inspected, 2026-10-03

The designated Target Workflow launch file is readable and the user systemd manager reports
`running`. The existing runner's `ExecutorResources.from_host_effective_allocation`
still raises `RunExecutionError: cannot read host cpu.max`. Inspection found that
its ancestor scan attempts resource controls at `/sys/fs/cgroup` itself; this
host has them on `user.slice` but not on that root. The kernel documents
`cpu.max`, `memory.max` and `pids.max` as non-root cgroup interfaces
([cgroup-v2 documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html)).
The existing container resolver found no Docker-compatible CLI. This is a
specific live-run prerequisite to address through the existing generic runner,
not permission to invent resource limits, weaken attestation or substitute an
in-process acceptance run. No cgroup configuration, executor allocation code,
container installation or credential file was changed by this inspection.

### Shared response durability verified, 2026-10-03

With Python edits frozen, the canonical runner passed **8 tests across 5 files**
in 31.1 seconds using `--file-retries 0 --tb=short`:

- Model request conversion and durable response publication (3): the real host
  channel's writer observes an already committed exact reply. A disconnection
  after commit leaves that reply intact and allows interrupted finalization.
- HTTP exchange through real worker/host pipes (1).
- Recorded external-response dispatch and divergence checks (2).
- Interrupted recording publication (1).
- Approved worker access to the shared experiment service through real pipes (1).

Launch/attestation and model responses are fixtures. These checks do not prove
native confinement, live reasoning, or nested continuation. New all-channel
recording, refiner host-state and measure-control integration checks are being
run separately; this receipt does not claim their results.

### Checker connection and merged-API corrections verified, 2026-10-03

Two subsequent frozen-source canonical runs used `--file-retries 0 --tb=short`:

- **16 passed, 1 failed** across eight files in 188.5 seconds. Both direct and
  independent-checker refinement cases passed. Scoped/nested execution, selected
  unit execution, shared dispatch, model-request conversion, learning-broker
  boundaries and reasoning selection passed. The remaining regression-history
  failure exposed candidate admission using the Builder's removed `call_options`.
- **4 passed, 1 skipped** across three files in 56.7 seconds after candidate
  admission adopted the existing Builder's separate planner/emitter options.
  Cross-child regression history, repeatable-call materialization and the
  in-process generic reasoning workflow passed. The isolated reasoning workflow
  was skipped; it is not confinement evidence.

The checker case executes an admitted deterministic child through the shared
service and existing in-process linker. It compares supplied scheduling answers
with the independently enumerated optimum: the wrong answer fails despite a
forged target pass flag, the correct answer passes despite a target fail flag,
and missing input is unmeasured with no checker Run. The parent receives typed
measured failure and checker evidence distinct from target evidence. Repeating
the request reuses its existing dispatch. Compact history preserves the checker
relationship, explicit fresh-entry scope limits and target-owned launch approval.

This establishes the independent-checker connection, not live problem-solving,
native confinement, autonomous code repair, checker construction or coherent
recovery. The fixture supplies target answers and refiner/model responses. All
five failures from the broader run below have now passed their focused reruns;
that is not a claim that the repository's full suite ran or that later code has
been verified. Targeted Ruff and `git diff --check` also passed.

### Broader post-merge compatibility checks, 2026-10-03

With edits frozen, the canonical runner reported **32 passed, 5 failed** across
21 files in 94.0 seconds, with retries disabled. Passing paths include setup,
host testing launch, worker testing access, the supplied-response testing Episode,
direct refiner experiments, campaign measurement, component execution, recorded
and numerical replay, shared history and scoped reports.

Four failures came from remaining fixture migration omissions: a nested source
constructor did not forward its declared slots (affecting both scoped and unit
tests), the regression fixture still used old launch fields, and a broker request
omitted its model slot. These are corrected for the next run.

The independent checker executed but failed when its evidence returned to the
refiner: registration equality compared frozen tuple-valued arrays with thawed
list-valued arrays. The adapter now compares canonical JSON, preserving exact
content checks. Verification of that correction is pending. The live reasoning
acceptance and coherent nested recovery requirements remain unfulfilled.

### First post-merge compatibility checks, 2026-10-03

The canonical runner with retries disabled passed **6 tests and failed 1** across
four files in 50.9 seconds, with Python edits frozen throughout execution:

- Three launch-setup checks passed: project credential separation, private files,
  and real host/CLI enforcement of exact current human launch approval. A changed
  model slot requires new approval; registration does not grant it.
- The host-to-testing-Episode integration passed using explicit model slots and
  approved target/tester launches. This executes the generated testing Episode
  and shared service, with supplied model responses and target output.
- The staged-import check and direct refiner experiment check passed.
- The independent-checker case reached generated child execution, then failed
  because the fixture passed a non-opaque result identity to `CreditObservation`.
  The fixture identity has been corrected without changing numerical validation;
  this receipt does not claim the corrected checker passed.

An earlier setup-only invocation collected no tests: it ran during an incomplete
cross-file slot migration and found a missing required `model_type` in the
refinement library binding. The frozen invocation above includes that correction.
Remaining harness fixtures are being migrated to the same explicit-slot and
approval APIs. These checks do not establish live reasoning, native confinement,
autonomous repair, or coherent interruption recovery.

### Latest OpenChia merge retained with in-progress work, 2026-10-03

Merged `openchia/main` at `637ea47fbd` (PR #34, approved launch slots) into this
branch with merge commit `684ce78bc9`. No push was performed. The complete
pre-update working tree, including untracked files, is retained in stash
`2aea2018eb18ddfa1902156787be62cb560c09f9` and the stable local Git reference
`refs/checkpoints/unified-harness-before-pr34`.

After reapplication, all 127 saved files were present. 115 were byte-identical,
including all 68 untracked files; the remaining 12 combined the upstream changes
with our work. Conflict resolution retained the shared-testing source hooks,
generalized fixture emission and explicit Duet/refiner-versus-target routing
documentation alongside PR #34's required model slots and launch approval.
The upstream launch format was not reverted to the old bindings/session-auth
format. No credential files or other checkout were modified.

Ancestry, clean conflict-marker/whitespace checks, compilation of the affected
Python merge files, and targeted lint passed. Behavioral tests have not been
rerun after this update. Task 5 must align the harness's old launch/setup and
library-call adapters with the newly required slot APIs; the earlier receipts
do not establish compatibility with this merged state. This remains within the
existing task 5, not a new numbered task.

### Checker integration: fixture admission failures, 2026-10-03

Source edits were frozen during both canonical runner invocations, with retries
disabled. Neither run reached checker execution:

- **3 passed, 1 failed** across three files in 37.3 seconds. The direct experiment,
  staged-import and admitted cross-child regression checks passed, including the
  task-2 failure-report helper extraction. The checker fixture emitted invalid
  Python for an empty component tuple and failed Builder admission.
- **7 passed, 1 failed** across three files in 33.6 seconds. The direct experiment,
  staged imports and all five execution-history checks passed. After fixing the
  tuple, the checker fixture reached source admission but was rejected for direct
  `load` calls bypassing declared collaborators.

The new compact checker-intent projection and actual checker-computation assertions
are present, but that path has not passed. Passing history tests in the second run
establish compatibility of the existing ordinary/refinement intent views, not the
new checker path. No admission check was relaxed. Task 1 remains incomplete.

### Shared record interface completed (task 2), 2026-10-03

The canonical runner with retries disabled passed the focused checks in stages:

- **13 passed, 1 failed** across five files in 19.8 seconds: the five execution
  history tests, three Run-record tests, four scoped-report tests and one staged
  import test passed. The new admitted-regression test failed because its fixture
  inherited the wrong child bindings for the Designer role.
- **4 passed, 1 failed** across two files in 14.6 seconds: report checks, including
  unresolved-conflict priority, passed. Corrected role bindings let the regression
  test reach source admission; its edited fixture source was rejected.
- **1 passed** in 22.6 seconds:
  `tests/episode_runtime/records/test_refinement_regression.py`. The fixture now
  preserves the exact host-owned declaration suffix when editing source and
  binds each new child assignment to the current candidate. Admission rules were
  not relaxed. A subsequent extraction of failure-report formatting into a test
  helper did not change the passing path; the subsequent checker-integration
  invocation above reran it successfully.

The admitted-regression check builds the approved target/refiner, admits a
Designer and three Implementer assignments, admits their candidate revisions,
and measures each through the common experiment service. Real observation
admission detects the opposing result cycle: pass/fail, fail/pass, pass/fail.
The parent's shared history preserves all three candidates, child identities and
original outcomes; the default context includes unresolved conflicts. History
queries run with full campaign enumeration and Run audit reconstruction disabled
by the test. The scope/projection checks additionally verify child filtering and
that newer resolved incidents do not displace unresolved conflicts.

Recording discovery checks establish exact-prefix and invocation filtering,
callable inventory requests, pagination, private-content exclusion, and visible
missing-source limitations. These views use the existing indexes and stores;
there is no new record database or replay mechanism.

Limits: the regression check drives host APIs directly and supplies target
outputs through the existing result-only executor. The source edits are fixture
revisions, not demonstrated behavioral repairs. This verifies admission and the
shared record interface, not model reasoning, stock-refiner autonomous paging,
real checker acquisition, native confinement, or coherent recovery. Task 2 is
complete at that interface scope. Tasks **1, 3, 4 and 5** remain open.

### Parallel integration checks: incomplete, 2026-10-03

Both implementation agents paused Python edits during these checks. The
canonical `scripts/run_tests.sh` runner used the isolated test interpreter and
`--file-retries 0 --tb=short`.

- `tests/episode_runtime/testing/test_refinement_experiments.py`: **1 passed,
  1 failed** in 26.6 seconds. The direct target-output case passed. The
  independent-checker case failed while building its fixture, before checker
  execution: `root_launch_payload_not_empty`. The Builder requires an empty
  root request contract, while the proposed checker fixture declared a target
  answer as a root input. This is not evidence that checker execution works.
- `tests/episode_runtime/records/test_execution_history.py`,
  `tests/episode_runtime/records/test_run_records.py`, and
  `tests/iterative_episode_refiner/test_reports.py`: **10 passed, 1 failed**
  across three files in 10.9 seconds. The new recording-discovery test passed
  an `OpaqueId` object to `save_recording`, whose existing API expects its string
  value, and failed before reaching its assertions. The other history, inventory
  and scoped report checks passed.

The passing direct refiner case uses generated refiner code and authenticated
supplied model responses. Target returns are supplied; the proposed checker
case computes its oracle in the fixture executor rather than executing generated
checker code. Neither establishes live reasoning or native confinement. The
report tests seed campaign records and establish projections, not an admitted
cross-child repair cycle. The complete goal and all five remaining tasks are
still open. Later edits require their own verification.

### Actual nested refiner baseline and shared history, 2026-10-03

Canonical runner, retries disabled: **9 passed across 4 files** in 128.7 seconds:
`tests/episode_runtime/testing/test_refinement_execution.py`,
`tests/episode_runtime/testing/test_scoped_execution.py`,
`tests/episode_runtime/records/test_execution_history.py`, and
`tests/iterative_episode_refiner/test_reports.py`.
Ruff on this change's code and `git diff --check` passed.
A separate canonical run passed **2 tests across 2 files** in 23.9 seconds:
`tests/episode_runtime/testing/test_worker_access.py` and
`tests/episode_runtime/test_staged_closure_imports.py`. These retain their stated
transport/import scope; they are not a native confined refiner demonstration.

The new refiner check builds an approved target and the complete fixed refiner
workflow through the real Builder, prepares a campaign from the published
materialization handoff, and executes generated Parts and Verify Episodes.
It uses the shared Run dispatch, actual method loop, protocol-framed requests,
production host-exchange function, actual campaign admission, and shared history.
No campaign index, observation, or host credit is pre-filled for this check.

The verifier's static passes reach Parts' next model context with the original
candidate and evidence references. Missing behavioral coverage remains an
explicit decision, not a verified build. A supplied invalid model proposal is
authenticated against the active Run's committed response, rejected, and earns
zero realized yield. The test caller cancels at the next model request; the Run,
refiner result and shared execution history all retain cancellation. This is
neither numerical completion nor continuation/recovery coverage.

The actual path first failed at these integration defects, fixed before the
passing run:

- Plain reference data with a `schema_id` was mistaken for a typed envelope.
- Shared dispatch rejected a campaign naming a separately approved refiner in
  another Duet. Dispatch and history now verify the exact linked approval/build
  or Run registration; unrelated target data and changed builds are refused.
- The `call` response field collided with the host method's Python argument.
- An unresolved source constructed an unsupported `SourceEnd("incomplete")`.
  It now exhausts normally while retaining the host's unresolved disposition.
- Proposal authentication required terminal audit evidence while its own Run
  was still active. It now uses the existing verified committed-prefix reader;
  final candidate acceptance still requires terminal execution evidence.

Limits: Builder and runtime model responses are supplied; generated code runs
in-process using the existing integration fixture with supplied confinement
attestation. This does not prove native worker confinement, live reasoning,
successful implementation repair, or complete common experiment-spec support.
Refiner evaluation requests still need the shared experiment-spec/measurement
adapters. All five remaining task IDs (1, 2, 4, 5, 6) remain open.

### First-unit selection through the shared interface, 2026-10-03

Canonical runner, retries disabled: **4 passed across 4 files** in 155.5 seconds:
`test_unit_execution.py`, `test_scoped_execution.py`, `test_worker_access.py`, and
`test_testing_episode.py` under `tests/episode_runtime/testing/`.

The unit check executes generated nested Episodes through the common experiment
service, linker, method loop and Run store. It obtains an exact unit boundary
with `openchia test boundary --unit-id`, runs only the entry's first unit,
and checks the actual committed events. A parent unit runs its declared children
while its own controller still says to continue; no parent Episode completion
or final result is published. A later-unit request and a changed unit label are
refused before dispatch. Repeating the same experiment launches no new Run.

The expanded check also builds an approved testing contract and verifies its
host-session boundary operation returns the same references as the CLI. The
reuse grant covers only the selected recording prefix, not the whole Run.
Supplying both an Episode ID and a unit ID is rejected. Recorded execution of
the selected leaf exposes its Run-dependent prompt mismatch as invalid, reuses
no response, and makes no live model call.

The expanded rerun initially had **one failure and one collection error** in
the added fixture: missing required environment conditions and an imported
function accidentally collected as a test. Both were corrected. The final
focused rerun passed **1 test** in 121.6 seconds. Experiment-planning checks
(2 tests) and staged-worker imports (1 test) passed in the preceding run.
Ruff on the changed code and `git diff --check` passed.

Limits: model outputs and confinement attestation are fixtures. The access
check constructs a real approved host session but supplies its caller-start
event; it does not execute a testing Episode making the new unit-selection
request through a confined worker. Existing worker-access coverage exercises
the common channel with other operations. This receipt establishes neither
live reasoning nor OS confinement, later-unit restoration, complete refiner
integration, or goal completion.

### Indexed refinement history, 2026-10-03

Canonical runner, retries disabled: **9 passed across 4 files** in 30.4 seconds:
`tests/iterative_episode_refiner/test_reports.py` (4),
`tests/episode_runtime/records/test_execution_history.py` (3),
`tests/episode_runtime/testing/test_worker_access.py` (1), and
`tests/episode_runtime/testing/test_measurements.py` (1).
Ruff on the changed history, runtime-context, CLI and report-test files passed;
`git diff --check` passed.

Real-store history checks refuse full campaign enumeration and audit reads.
They page admitted index entries through `ExperimentService.history`, the CLI,
and the host-assigned query used by refiner context. They preserve old outcomes,
reject cross-assignment cursors and changed-head pagination, and reject a
generic testing worker's attempt to select another refinement assignment.
Parents see both sides of a seeded cross-child conflict; a child receives only
its assigned requirement references and an explicit withheld-reference count.
Own/direct-child reports remain distinct from current campaign state.

The campaign index and conflict are explicitly seeded fixtures. This does not
demonstrate that a live refiner caused or repaired the regression, or that an
actual refiner worker paged its context. The existing worker-access check covers
the generic testing transport with supplied target output, not that refiner
execution. No live reasoning, confinement or complete Task 2 claim follows.

After including the moved outcome schema and its base record model in the
existing frozen measurement-implementation identity, and rejecting unstructured
refiner history queries, the final focused canonical rerun passed **6 tests
across 3 files** in 14.0 seconds: the four report/history checks,
`test_measurements.py`, and `test_staged_closure_imports.py`. The latter imports
the actual staged worker in an isolated Python subprocess and stops at `--help`;
it does not run a confined Episode. Ruff and `git diff --check` passed.

### Shared refiner result projection, 2026-10-03

Canonical runner, retries disabled: **6 passed across 3 files** in 12.8 seconds:
`tests/iterative_episode_refiner/test_reports.py` (2),
`tests/episode_runtime/records/test_run_records.py` (3), and
`tests/episode_runtime/testing/test_measurements.py` (1).
Ruff on the changed report, shared-outcome and predicate-consumer files passed;
`git diff --check` passed.

The report checks use actual DuetStore/CampaignView reads and typed stored
records. They explicitly seed the campaign index: they test read-only reporting,
not campaign admission or execution. Parent and child projections retain the
same original expected/observed result and tested candidate. The current view
can be stale or contradicted while the historical outcome remains a pass;
missing current evidence remains unresolved and does not delete history.
Unrelated sibling observations are absent from child context. Experimental
measurements use the same outcome schema, and their existing independent-value
comparison checks still pass.

This completes the tested result-field projection within work item 2, not item 2
as a whole. Shared indexed refinement-result/regression discovery, complete
refiner experiment submission, remaining scopes/adapters, coherent nested
continuation, and live acceptance remain unverified or unfinished. No live model,
candidate execution, confinement, or new credit-admission claim follows from
these six checks.

### Development verification, 2026-10-02

`scripts/run_tests.sh tests/episode_runtime/testing/test_experiment_planning.py
--file-retries 0`: **2 passed**. Uses actual approval, Builder admission,
BuildStore and DuetStore; includes the installed command dispatcher and exact
scope/identity checks. Builder replies are deterministic fixtures. No confined
candidate execution or live model reasoning is demonstrated by this result.

Lint passed for the new testing package/CLI/tests and the touched refiner
evidence reader and CLI dispatcher. `git diff --check` passed.

The compatibility probe also ran `test_campaign_state.py` and
`test_control_integrity.py`: **5 passed, 4 fixture-setup errors**. Their unchanged
`CampaignFixture` creates check records without the required `evidence_kind`
field. They fail before reaching the extracted shared reference reader. These
draft refiner tests are not a passing validation receipt; their fixtures and
behavioral coverage must be brought into the unified acceptance work. No
production admission check was weakened to make them pass.

### Shared dispatch and launch setup verification, 2026-10-02

The canonical runner passed **7 targeted checks** across
`testing/test_experiment_planning.py`, `testing/test_shared_execution.py`,
`test_model_request_thaw.py`, and `test_executor_http_loop.py`. They exercise
actual approval, BuildStore/DuetStore/RunStore and request/response recording,
reject an unapproved recursive model path, and preserve an interrupted dispatch
without relaunch. The dispatch fixture intentionally fails before execution;
the HTTP fixture uses a protocol-speaking subprocess with inert attestation and
a canned network response. These are not live reasoning/confinement proofs.

`tests/openchia_cli/test_episode_launch_setup.py`: **2 passed**. Uses actual
files, the ordinary launch resolver and structured CLI. A→B→A project resolution
retains distinct credentials and model settings without changing `os.environ`;
public outputs contain no test credential values, existing setups are preserved,
and POSIX directory/file permissions are checked. No model service is contacted.

Live confined execution remains unverified. A current read-only resource probe
fails with `RunExecutionError: cannot read host cpu.max`: the process's reported
cgroup has no visible `cpu.max` file. Running the same probe in a fresh transient
user-systemd unit has the same failure. No confinement check was bypassed and no
host configuration was changed to produce a green receipt. This does not block
the remaining harness implementation work.

### Recorded and numerical modes verification, 2026-10-03

Canonical runner: **120 passed across 10 files** (`tests/episode_runtime/testing/`,
`test_staged_closure_imports.py`, `test_http_broker.py`, `test_http_protocol.py`,
`test_model_request_thaw.py`, `test_executor_http_loop.py`, and
`tests/openchia_cli/test_episode_launch_setup.py`). No retries were enabled.

`test_recorded_execution.py` exercises the shared dispatch service, real brokers,
protocol frames and stores. It saves a recording through the CLI, removes the
live credential, reuses matching responses, preserves their provenance, rejects
changed requests/environment/child paths, and distinguishes a new live call from
saved root inputs. The executor fixture only exchanges messages and interrupts;
it does not run Target Workflow code. The model transport is canned, and the HTTP
response is a real policy denial rather than a live network response.

`test_numerical_execution.py` runs actual learning-ledger commits against an
approved build: zero-yield failure, an admitted lesson, and a duplicate. The CLI
recomputes and compares their numerical history using the existing controller,
returns the same persisted result on repetition, and leaves the source journal
unchanged. An exact invocation selection works; a wrong invocation and an empty
committed prefix are refused. The source Run remains `interrupted`. Its executor
uses inert attestation and does not execute generated Episode code. This proves
the numerical/evidence path, not live reasoning or confinement.

The shared dispatch check also rejects a caller-supplied recorded broker before
publishing a dispatch, preventing reused HTTP responses from being mislabeled
as a live-mode experiment. Its focused two-test file passed after that guard
was added. These checks are not substitutes for the full goal's live acceptance
requirements. Narrower code execution, worker access, measurement/acceptance,
cross-child regression and coherent recovery still require implementation and
their own truthful receipts.

Final focused rerun: **8 passed across all 5 harness test files**. This includes
an interruption between the terminal journal event and terminal-artifact
publication. The existing `RunStore.complete_terminal_publication` completes
that publication idempotently; the saved recording identity stays unchanged
while evidence availability becomes true. The source remains interrupted, not
successfully completed. This is publication recovery, not nested execution
continuation. Ruff and `git diff --check` also passed.

### Measurement and comparison verification, 2026-10-03

The canonical runner passed **122 checks across 12 files**, with retries disabled:
all six files in `tests/episode_runtime/testing/`, the staged-closure, HTTP broker,
HTTP protocol, model-request recording and executor HTTP-loop files listed above,
and launch setup. Ruff and `git diff --check` passed.

`test_measurements.py` uses the independent scheduling enumerator to supply a
reference optimum, then exercises CLI criterion registration, the shared service,
RunStore evidence, typed measurement, `results`, and `compare`. Correct, incorrect,
and wrong-type control values are distinguished. Changed prediction text cannot
weaken a criterion. Interrupted execution and a mismatched environment cannot
produce a pass. A stale implementation identity is refused. Repeated requests
reuse the same measurement without another execution or progress admission.

**Evidence limit:** its executor publishes supplied typed results using inert
attestation; it does not execute the candidate or call a model. The exhaustive
solver supplies reference data, not an Episode-produced answer. This receipt
validates the measurement/comparison path, not the required demonstration that
a real testing Episode finds a broken candidate, observes a repair, and chooses
a justified follow-up through the confined host/worker service. That demonstration,
worker access, remaining scopes, campaign measurement/report integration and
coherent nested continuation remain unfinished.

### Testing access and Episode-loop verification, 2026-10-03

The canonical runner completed **241 passed, 3 skipped across 32 files**, with
retries disabled: `tests/episode_runtime`, `tests/episode_builder`, and
`tests/openchia_cli/test_episode_launch_setup.py`. Ruff and `git diff --check`
passed. The skips include confined/live execution; this is not a live acceptance
receipt. Older runtime tests needed relative-import corrections and one missing
required HTTP-broker argument to exercise their unchanged assertions under the
canonical runner.

`test_worker_access.py` exercises actual host/worker protocol pipes and the shared
experiment service. Exact approval is preserved; changed criteria and unassigned
result access are rejected. Launch attestation is inert and target output is
supplied. It proves transport/access behavior, not confinement.

`test_testing_episode.py` materializes the new library reference and executes its
real linked Episode loop with scripted model responses. The shared harness measures
a supplied incorrect scheduling minimum against an independently enumerated optimum.
The Episode requests that experiment, sees the measured failure and selects a
follow-up inspection. An invented pass is rejected for zero credit; an exact
measured-failure finding is admitted. Rewording the question and prediction launches
a new experiment but earns no duplicate finding. Repeated inspection also earns
zero credit. The existing controller, not the script, resolves continuation, and
the final result preserves the candidate failure without granting parent acceptance.

This mechanical loop fixture explicitly uses a continuation threshold of **0.5**;
the reference Episode still ships **0.01**. No duration or call-count claim for
the default configuration follows from this receipt. Target outputs and model
decisions are fixtures; the test does not prove that a live model designed the
experiment or solved the scheduling problem. Normal conversational testing setup,
remaining execution scopes, full campaign/parent integration, coherent nested
recovery, and the goal's live acceptance demonstrations remain required.

### Selected-invocation execution verification, 2026-10-03

`test_scoped_execution.py` materializes and runs an actual generated
root → group → leaf workflow, then uses the shared CLI/service to run only the
leaf and only the group-with-leaf. The committed invocation records contain
exactly the selected Episodes, with the original ancestry retained. Saved goal
view tampering and omission of an executable child are rejected before dispatch.
The shared path check rejects requests addressing an omitted ancestor. A boundary
can be captured from a selected Run without inventing parent execution events.

The same check refuses whole-workflow playback from a narrower recording.
Recorded execution of the reasoning leaf explicitly diverges because its prompt
contains new invocation-local learning identities: no response is reused and no
live model call occurs. This is rejection evidence, not a claim that these
Run-specific prompts can be replayed successfully.

The compatibility run over `tests/episode_runtime`, `tests/episode_builder`,
`tests/method_loop`, and launch setup produced **244 passed, 3 skipped**, and one
failure in the new in-process replay fixture. After preserving the host broker's
error independently of the worker adapter's exception wrapping, the focused
canonical rerun of `test_scoped_execution.py` and `test_experiment_planning.py`
passed **3 checks**, with retries disabled. Ruff and `git diff --check` passed.

These executions use real generated source, typed handoffs, host learning,
brokers and durable stores, but a scripted external model and inert execution
attestation. They do not prove model reasoning, independently correct task
answers, or process confinement. The loop fixture uses an explicit **0.9**
continuation threshold, not the reference's **0.01**. Changed shared-state
restoration, component/unit/refinement scopes, recorded child substitution,
normal conversational testing setup and live acceptance remain unfinished.

### Ordinary-host testing launch verification, 2026-10-03

The canonical runner passed **253 checks, with 3 skips across 36 files**, with
retries disabled: the complete runtime, builder and method-loop directories,
launch setup, OpenChia CLI command checks, and the new
`tests/agent/test_episode_testing_launch.py`. Ruff and `git diff --check` passed.
The skips still include live/confined execution; this is not its acceptance
receipt.

The new check uses two ordinary `OpenChiaHost` Duets in one isolated workspace.
It configures `/launch` through the existing host method, submits real
Architectures, requires human approval, and builds actual source. The testing
workflow's ordinary `/run` enters the shared dispatcher, receives its scoped
testing session, executes the target's generated Episode through that same
dispatcher, and measures its result. The testing Episode observes a pass and
selects a follow-up inspection. The final measurement retains
`acceptance.admitted: false`; the outer ordinary Run remains unmeasured as a
candidate. An unapproved launch and a replaced configuration hash are refused.

The target criterion in this check concerns **host-governed completion**, not
the correctness of a reasoning answer. Model decisions are scripted and execution
attestation is inert. Both loops use an explicit **0.9** continuation threshold.
Thus this proves the normal approval/build/launch connection and nested service
integration, not live reasoning, independent task correctness, default-threshold
performance or operating-system confinement.

The earlier empty-capability/ordinary-launch gap is now closed for explicitly
approved testing contracts. Full component/unit/refinement scopes, campaign
measurement and parent-report integration, coherent recovery, HTTP credential
setup, and the goal's live acceptance demonstrations remain required.

### Registered-component execution verification, 2026-10-03

Final canonical verification: **255 passed, 3 skipped across 37 files**, with
retries disabled, covering `tests/episode_runtime`, `tests/episode_builder`,
`tests/method_loop`, the ordinary-host testing launch, launch setup and CLI
command checks. Ruff and `git diff --check` passed. The initial compatibility
run exposed the missing staged module and the old component-boundary fixture;
both were corrected before this final run.

`tests/episode_runtime/testing/test_component_execution.py` uses the common
experiment service, actual admitted generated module design, registered
functions, worker linker, protocol frames, host return validation, and existing
stores. It selects a function owned by the middle node of a root → group → leaf
workflow. The actual continuation function is exercised on both sides of its
frozen threshold, and the actual result schema is exercised with malformed
input. The registered measurement distinguishes the observed outcomes.

The recorded evidence contains one component observation and no Episode/unit
execution or learning events. Repeated experiment requests return the existing
evidence without a second dispatch. Saved-input and recorded-mode reruns preserve
the exact call; changed recorded inputs, replacement controller parameters,
out-of-scope child addresses, and a fabricated Episode-completion field are
rejected. These pure functions make no external calls, so this receipt does not
claim external-response playback was exercised by them.

The staging check now launches the real bootstrap's help path in a separate
isolated Python process with the verified runtime package and standard library
only. It caught missing worker-scope modules, which were added to the existing
runtime manifest. This is a real import check, not a source-text pattern check;
it still stops before installing OS confinement or executing a Run.

The component behavioral checks use the existing in-process executor fixture
and inert confinement attestation. The numerical fixture's binding is **0.9**,
not the reference default **0.01**; expected decisions are derived from the
actual frozen binding. This receipt is not live reasoning acceptance or proof
of native confinement. Additional typed component adapters, declared-unit and
refinement-job execution, campaign/parent-report integration, coherent nested
continuation, HTTP credential setup and live acceptance remain unfinished.

### Shared record-storage consolidation, 2026-10-03

The canonical runner passed **15 tests across 11 files**, retries disabled:
`tests/episode_runtime/testing` and
`tests/agent/test_episode_testing_launch.py`. Ruff and `git diff --check` passed.
These are the existing integration checks of actual stores, approval/build,
shared dispatch, measurement, numerical and recorded modes, worker access and
linked Episode execution. Their scripted/inert execution limits described above
still apply; no new live acceptance claim is made.

Lifecycle record names, identity keys, envelopes and digest checks now have one
owner (then `episode_runtime/testing/records.py`, now
`episode_runtime/records/experiments.py`). Dispatch transactions continue to
use the existing atomic artifact/event publication; all existing record IDs and
hash conventions are retained. The old reference module and scattered storage
helpers were moved, with consumers updated rather than compatibility aliases.
The current guide is now separate from these historical receipts.

This verifies storage consolidation, not the complete shared record interface.
Maintained high-level views/indexes, browsing past tests and replay availability,
shared refiner result projections and coherent nested continuation are still
unfinished. The uncompleted unit-scope work has no direct acceptance coverage
from this run.

### Maintained Run records and indexed discovery, 2026-10-03

The canonical runner passed **257 tests, 3 skipped across 38 files**, retries
disabled: `tests/episode_runtime`, `tests/episode_builder`, `tests/method_loop`,
`tests/agent/test_episode_testing_launch.py`, and the launch setup and CLI command
checks. This includes the new Run record checks and history consumers. After
adding per-experiment recording pagination, a focused canonical run passed
**3 tests across 3 files**: `test_measurements.py`, `test_worker_access.py` and
`test_numerical_execution.py`. Ruff on the changed record/history files and
`git diff --check` passed. The first focused run failed because the supplied-result
fixture omitted the required `episode_id=None` on its added Run-start event;
this was corrected before the passing focused run.

RunStore now maintains a compact typed record as registration, events and
terminal evidence commit. Tests inject interrupted view publication after the
authoritative event is durable, verify that inspection reports the stale prefix,
and rebuild the derived view without changing execution evidence or status.
An interruption remains an interruption. Missing terminal-evidence publication
remains visible rather than being treated as successful completion.

CLI and approved worker history use the same indexed catalog. Tests browse
experiments, measured pass/fail/error outcomes and exact recording references
while full Run audit reads are deliberately forbidden. Saved recording pages
have callable next-page queries; cursors from another experiment and requests
from another owner are rejected. The real protocol subprocess checks that a
later invocation cannot list the earlier invocation's experiments or recording
selectors, while its own authorized experiment remains discoverable.

These checks establish record publication, bounded discovery, ownership and
CLI/worker integration. Supplied results and inert confinement attestation are
still used where documented in those fixtures. They do not demonstrate a live
model solving the scheduling problem or native confinement. Full invocation/unit
inventories, common refiner results/history, coherent nested continuation and
the remaining acceptance demonstrations are still unfinished.
