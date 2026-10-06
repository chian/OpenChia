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

The refiner's declared measurement input also includes `iteration_history`:
`completed_units` and chronological `units` for **every completed unit in that
Episode invocation**, plus all recorded `proposals` and their host rejection
reasons. Each unit contains evaluation results, open decisions, ordinal,
candidate-change flag, realized yield, and disposition. The projection reads
existing unit receipts and authenticated proposal artifacts scoped to the
logical Episode identity, retaining history across continuation. A recorded
proposal is not proof of admission or a successful repair; its measured outcome
remains separate. Proposal and unit sequences are kept separately: the stored
proposal artifacts do not carry unit identities, so the projection does not
invent those associations or assume one proposal per unit.
There is no last-N cutoff, invented effort classification, or model summary.
Earlier failed attempts remain visible even when the latest feedback changes.
Whole audit envelopes and past input contexts are not copied into the history.
Proposal text is historical data, not instructions or authority.

This is the Episode's own working history. It does not change how its children
synthesize reports, which reports the method delivers, or what it returns to its
parent. Replacing the latest child report must not hide repeated zero-yield
decisions in the parent's own history.
The refiner completes design, implementation and validation internally. Its
prompts distinguish explicit required outcomes from implementation choices left
open: preserve the former, develop and test the latter. Missing details are work
to resolve, not a requirement to seek another Duet approval. Builder checks are
automatic host validation, not a conversation or separate design authority.
Parts may combine coupled work or stage actual dependencies, but static admission
never substitutes for working behavior. A Designer develops alternatives and
uses its permitted measurement children; an existing returned measurement need
goes to its internal parent when resolving it requires a wider scope. Prompts
must not invent child capabilities or promise unavailable external interactions.

## Materialization

### Implementer's coding capability

For a production refiner Run, an Implementer `change` request invokes OpenChia's
existing Codex app-server session rather than asking a single completion to
serialize all source files. The host resolves the exact active invocation from
the broker-stamped Episode path. It stages the authorized candidate source,
assignment, measured history and typed Episode input in a managed workspace.
The coding agent can read, create, edit and run diagnostic commands there.
It can create missing initial implementation; it does not require preexisting code.

Implementer's complete working context is saved as a `coding_assignment` artifact
and staged in `.openchia-assignment.json`. The worker carries its exact reference,
not another inline copy of the source, plans and complete iteration history.
The coding transport checks the reference against the active campaign,
invocation, unit and candidate before opening that assignment. This delivery
preserves all working information without making its growth consume the Run's
per-frame transport limit. Other Episodes retain their declared model inputs;
parent/child reports retain their separate synthesis boundary.
Model-call failures stop before proposal submission and retain their original
diagnostic; an absent response cannot become a fabricated empty proposal.

Actual file differences and `.openchia-plan-edits.json` become the ordinary
typed change proposal. The coding agent's final prose is retained as evidence,
not substituted for the change set or a parent report. Source admission and
local measurements run through the existing host path after that proposal;
independent parent acceptance, credit, rarefaction and continuation are unchanged.
Diagnostic commands inside the coding session do not certify acceptance.

This workspace belongs to Implementer. Its sandbox configures the coding tools,
not the Target Workflow's execution environment. Implementer receives the
available runtime, installation authority and saved preparation findings, and
can edit its assigned `.openchia-environment.json` with the candidate source.
The shared environment service resolves packages through the selected execution
backend and retains the exact lock with the admitted build. Diagnostics,
independent validation and subsequent Runs use that saved recipe and lock, not
packages installed incidentally in the coding session. Preparation failures
remain typed working feedback; setup itself earns no correctness credit.
Parent reports include environment findings only when requested by their
report contract. See [Target Workflow environments](target_workflow_environment.md).
The assignment/change/report contract is shared across Codex and Claude Code
adapters; their OS-specific sandbox verification remains separate.

Coding activity, native thread identity and turn results use the existing
campaign artifact store and model-call events. The ordinary Run model response
still authenticates the proposal. There is no coding-specific replay runner.
See [ADR 0009](../adr/0009-implementer-uses-an-existing-coding-agent.md).

### Shared authoring contract

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
