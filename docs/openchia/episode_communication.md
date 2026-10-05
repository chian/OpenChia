# Episode communication

Each parent asks for the information needed to make its next decision. Its child
returns a synthesis organized around the requested measurements. This keeps the
parent focused on findings instead of reconstructing the child's investigation.
The same rule applies at every nesting depth and to repeatable calls. The root
has no upward reporting obligation; it still owns its children's contracts.

## Ownership

- The parent declares the child's goal, measurements, and requested information
  before launch. Ordinary continuation retains those measurement obligations.
- The binding implements task-specific synthesis, including applicability,
  meaningful changes, blockers, and limitations. Its numerical credit projection
  is a separate function, retaining the identities required for accounting.
- The method loop admits and delivers the synthesis. The stored child report,
  execution history, artifact references and provenance are audit material, not
  a second parent-input channel. Short aliases for hashes are not findings.
- Useful task addresses, such as a requirement location or a file to modify,
  belong in a return when the parent actually acts on them.

## Shared interfaces

`method_loop.ReportContract` contains `decision`, `measurements`, and
`information`. `measurements` describes the requested judgments in meaningful
terms; executable scoring still belongs to the selected numerical components.
`information` maps required return field names to their decision-relevant
meaning. Domain-specific admission belongs to the binding.

Every invocation by an active parent carries `EpisodeRequest.report_contract`.
Both the child wrapper and Episode entry reject a missing contract before child
execution. A top-level request may omit it. An isolated selected-Episode check
has no executing ancestor to report to; retained ancestry describes its scope,
not an active parent invocation. Restoring a recorded request preserves its exact
reporting contract. Children launched by that selected Episode use the normal
mandatory boundary.

`ChildEpisodeUnit(child, receive_result, synthesize_report)` uses separate
callbacks for credit and communication:

- `receive_result(result, completion, request)` admits correlation and projects
  numerical credit on the parent's scale.
- `synthesize_report(result, completion, request)` returns precisely the
  information fields requested by `request.report_contract`.

The method admits the synthesis as a `ParentReport`. This class is the compact
return to a parent, not the refiner's stored `parent_report` audit record.
Unknown or missing fields are rejected. Request/result records declare their
audit identities through `ClosedRecord.audit_identifiers()`; those exact values
are rejected in report keys and values, including nested values and text. This
is rejection, not masking or a hash-pattern substitution.

The method records reports even when an acquisition unit runs multiple children.
The binding selects the reports relevant to the next decision from
`view.child_reports` or, within a compound acquisition, `ctx.child_reports`.
`model_inputs(declared_inputs, reports=selected_reports)` accepts only reports
admitted for that parent and owns the `child_reports` field in the delivered
input. It also checks declared inputs against the known child audit identities.
Completed history is not automatically appended.

The refiner's declared measurement input also includes `iteration_history`: the
number of completed units and the last eight units' ordinal, candidate-change
flag, realized yield, and disposition. These values come from committed unit
receipts, not model summaries. This window limits context, not execution.
Replacing the latest child report must not hide repeated zero-yield decisions.
Parts can separate a static construction prerequisite, judged by the existing
Builder checks, from later behavioral work. The original behavioral requirements
remain unresolved and protected; a static repair never grants whole-workflow
acceptance. A Designer unable to establish its assigned local measure returns
that need to Parts rather than repeatedly requesting unchanged observations.

## Materialization

The refiner's Designer and Implementer receive Builder's existing
`required_module_contract` and per-node `structural_binding_contract` as typed
working input. There is one authoring contract for initial construction and
repair, not a second undocumented module format. It includes public imports,
constructor signatures, required exports, and exact request-admission rules.
When a node plan is missing, an Implementer can submit a plan-only candidate
change; the following iteration receives the host-derived plan identities before
writing source. The ordinary host admission and local checks evaluate each
change. A Question child is not a general repository reader and cannot supply
missing authoring APIs by rephrasing an unavailable investigation request.

Each concrete child slot selects `component.report_S`, with interface
`episode.report_synthesis`. Its request projection constructs the reporting
contract; its report function explains how evidence becomes the requested
findings. Repeatable calls explicitly select `synthesize_report`, materialized
as `component.repeatable_S_synthesize_report`.

Builder instructions specify both the purpose and delivery of the synthesis.
Constructor admission checks the actual required `ChildEpisodeUnit` arguments.
The refiner uses the same method boundary; its report fields and measurement
interpretation are binding-specific.

## Verification boundary

Exact-field and known-identity checks enforce structural properties. They do not
prove that prose is useful, that a binding has correctly summarized an outcome,
or that arbitrary generated code always uses the intended input path. Those
claims require inspection of the real synthesis and final model input during
live nested execution, with distinct parent requests and their next decisions.

The real Builder admitted all eight refiner modules with zero deficits in receipt
`build_receipt_c2b5ac269b81c60ea4199038234760cedc3850155581d81227eb8b2d16ca7ae7`.
Fresh execution
`run_d932cc6e9d6bc7b6827854724b348b25d7e673243d96cf4a7a2e36adee8caa77`
delivered a Verify report to Parts through the shared method boundary. Event
37 contains that report in Parts' next model request; event 52 records its later
Designer selection. This establishes one return/next-decision path, not yet the
full distinct-contract acceptance criterion. Artifacts are in the existing
acceptance profile at
`/home/chia/repos/OpenChia-acceptance-0RN3r9BH/home/openchia/`.

That experiment was cancelled after it exposed an ambiguous measurement-request
instruction: `purpose` was described as a judgment but required a literal
category. The revised format names the categories and gives field-specific
rejection feedback. It also identifies returned prerequisite requests separately
from general evaluation gaps. Fresh materialization passed again in receipt
`build_receipt_4acf9a4274579f718a53f89592c7eaf548e1794c8db43c76a5c5f7662855e0d2`.
The corrected live experiment is
`experiment_b5d824ad7dab3e95d5280939bc50323c54db4349b494058042dce4b6eb18822f`,
Run `run_12f3d57808c84d5d59b6ab2e465fd9974095978a52dec5512bcab3624e351845`.
This execution established the distinct-contract reporting criterion:

| Outcome and trace | What it establishes | Scope and limitation |
| --- | --- | --- |
| Event 37: Parts receives Verify's `Independent requirement evaluation`; event 38 selects Designer; event 41 launches it. | A measured return reaches the parent's next decision. | In scope. Five recorded determinations: one pass, one fail, three blocked; twelve requirements remain unmeasured. |
| Event 78: Measure receives Designer's requested adequacy measurement and the `measurement_findings`, `check_review`, and `open_decisions` sections. Event 99 delivers that return to Designer. | A different parent request produces its own measurement heading and exactly its selected sections. | In scope. The child reports a grounding prerequisite, not a successful instrument. |
| Event 100: Designer forwards the prerequisite from that return. Event 143: Parts receives Designer's local-outcome report and its separately requested post-repair Verify report; event 144 makes its next selection. | Contracted findings support decisions across two nesting depths, while local outcomes and independent verification remain separate. | In scope for communication. The subsequent selection does not establish successful target repair. |
| Event 181 records cancellation after the communication observations were collected. The Run evidence has terminal status `cancelled`; its worker unit is gone. | The verification execution has ended and its evidence is durable. | Target completion and resolution of its measurement-coverage gaps remain outside this check. |

The four report projections present in those parent inputs serialize to
8,390, 6,717, 7,715, and 6,214 UTF-8 bytes respectively using Python
`json.dumps(report).encode("utf-8")`. None contains any of the 341 distinct audit
identities collected from the Run's refinement request/response records. This is
an observation about those actual reports, not a general proof that arbitrary
prose is concise, safe, or useful. Declared working inputs such as editable code
still occupy context; their size is separate from the child-report projection.

Event numbers refer to the zero-padded JSON filenames under
`episode_runs/events/<run_id>/` within the acceptance profile above. The terminal
receipt is `episode_runs/evidence/<run_id>.json`. The execution used the real
Builder admission, isolated Run executor, and owning Duet's model calls
(`gpt-5.6-sol`, medium effort), with the existing human-approved launch snapshot.
It used a fresh campaign over the existing target candidate, not replayed model
responses. No claim of full Target Workflow success follows from this check.

No compatibility projection or migration is provided for old communications.
