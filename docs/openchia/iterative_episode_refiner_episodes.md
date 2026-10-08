# IterativeEpisodeRefiner: approved Episode design

Designer owns the general approach. MaterializationImplementer, Code Implementer,
Measure and Verify are four peer specialists below Designer. Each specialist has
its own task-specific Parts Episode for smaller decisions. Question and Support
are read-only leaf Episodes callable from Designer, all four specialists and
every Parts Episode.

This document states the approved design and its code contracts. It does not
claim live validation of an unexecuted revision. The previous Parts-root design
is replaced; there is no compatibility path retaining that ownership.

## Complete ownership and capability diagram

~~~text
Duet-approved Target Workflow Architecture
└── Designer — chooses and revises the general approach
    ├── MaterializationImplementer — owns Materialization Spec changes
    │   └── Materialization Parts
    │       └── smaller Materialization Parts …
    ├── Code Implementer — owns source implementation
    │   └── Code Parts
    │       └── smaller Code Parts …
    ├── Measure — owns the reusable composite checking function
    │   └── Measure Parts
    │       └── smaller Measure Parts …
    └── Verify — owns independent acceptance evaluation
        └── Verification Parts
            └── smaller Verification Parts …

Shared leaf capabilities for Designer, specialists and Parts:
├── Question — search/read evidence to resolve a scoped uncertainty;
│              includes independent checking-program review
└── Support  — find reusable documentation, functions, reference Episodes
               and examples; assess applicability and limitations
~~~

The diagram declares ownership and allowed calls, not an execution schedule.
Designer reasons from the approved goal, current artifacts, measurements, prior
attempts and returned findings. Missing materialization is evidence available to
that reasoning. A prompt does not prescribe "materialize, then code," and the
host does not automatically select the next specialist.

Designer can assign a specialist the whole workflow or a particular part.
Decomposition takes place inside that specialist's responsibility. Parts does
not sit above Designer or above its specialist, and it cannot invoke another
specialty to acquire that specialty's authority.

Question and Support have their own goals, loops, measurements and numerical
stopping rules. They are leaves: their declared read-only research operations
perform search and retrieval within their own loop, and they have no children.
Question resolves a specific uncertainty; Support finds practical material the
caller can reuse. Existing preauthorized observations and independent check
reviews remain available alongside research. A preconfigured check is not a
prerequisite for investigating an ordinary question or guidance gap.

Research results are evidence, not instructions to the caller. Help does not
bypass authority or establish acceptance merely because a helper agrees.

## What each Episode owns

| Episode | Work and available operations | Responsibility retained by its owner |
| --- | --- | --- |
| Designer | Record the general approach; commission the four specialists; investigate uncertainties; use applicable support | Whole-workflow requirements and coordination across specialties |
| MaterializationImplementer | Author or revise plans through the structured materialization API; use Materialization Parts | Consistency across the commissioned Materialization Spec |
| Code Implementer | Create or repair source through the scoped coding workspace; use Code Parts | The assembled implementation under the chosen approach |
| Measure | Author checks, obtain independent review, execute adequacy controls, combine components | One reusable composite checking function for its commission |
| Verify | Execute established checks, investigate their evidence, use Verification Parts | Independent acceptance coverage, failures and limitations |
| Question | Search/read external sources, documentation and library references; use authorized observations or perform independent check review | The supported answer requested by its caller |
| Support | Search/read documentation, reusable functions, reference Episodes and examples | Applicability, limitations and missing coverage for its caller |

A specialist can perform its own scoped work. Calling Parts is useful when smaller
decisions or contributions help achieve the assignment; delegation is not an
obligatory extra wrapper.

Designer chooses its approach and contribution in one measured unit. Its
`plan` is null or contains `approach_key`, `requirement_mapping`,
`intended_change_scope`, `intended_materialization_targets` and
`dependency_effects`; `child` names the selected contribution and `conflict`
is null or an applicable coordination record. The optional plan records an
approach without dictating which peer runs next. Null retains the current
approach or permits investigation/measurement before one is established.
Approach prose alone does not create an extra numerical observation. The chosen
child supplies the substantive contribution in that unit.

Verify likewise selects direct evaluation or a scoped child. The existence of
a Verify binding does not create a mandatory automatic verification call after
every source edit. Final readiness still requires actual evidence for all
mandatory requirements on the exact final candidate.

## Task-specific Parts, not one generic delegator

The four Parts bindings share the method loop, persistence and numerical
machinery. They have different task instructions, permitted instruments,
measurement meaning and returned contributions.

| Parts binding | A part can be | Direct work | Progress evidence |
| --- | --- | --- | --- |
| `materialization_parts` | An interface, state design, binding or coupled specification decision | Scoped structured Materialization Spec edits | Measured satisfaction of assigned plan requirements while preserving dependencies |
| `code_parts` | A behavioral contribution across functions or modules | Scoped source implementation and its authorized environment recipe | Improvement under assigned checks with preservation requirements retained |
| `measure_parts` | A requirement's cases or a checking component | Checking-code authoring, independent review and executed adequacy controls | Newly adequate requirement components under the unchanged adequacy rule |
| `verification_parts` | A smaller requirement scope | Execute established checks and examine exact-candidate evidence | Newly established valid determinations, including failures |

Each Parts Episode may perform the scoped contribution directly or invoke a
smaller instance of the same Parts specialization. It cannot substitute a
different specialty. The current persisted scope is requirements, source paths
and materialization targets. A child must narrow one of those real dimensions.
There is no separate case-slice assignment field. With a single requirement and
no smaller editable target, the Episode performs its direct work instead of
proposing a prose-only subdivision. Cases can still be authored or evaluated
inside that work; they are not independently addressable child scopes yet.
Merely repeating the enclosing assignment creates no new progress.

Concrete operations remain possible at the bottom of the tree. Code Parts uses
the coding function; it does not need another Code Implementer Episode beneath
it. Materialization Parts uses the structured editing API. Measure Parts uses
its checking workspace and adequacy functions. Verification Parts invokes the
established checking/execution functions.

An unresolved cross-specialty need returns through normal parent reporting.
The specialist assesses it and returns the relevant finding to Designer, which
can commission the appropriate peer. The child does not ask its parent to
change an active grant mid-unit or obtain that grant through a helper.

## The parent-to-child assignment

Every assignment carries enough task information to make the child's
specialization concrete:

- Purpose, rationale and the contribution needed within the enclosing approach.
- Requirements and relevant artifacts, including the exact current candidate.
- Editable targets, dependency and preservation obligations.
- Current evidence, prior attempts and unresolved questions relevant to that work.
- A fixed measurement basis and numerical control for the child's assignment.
- A parent-authored return contract naming the next decision and needed findings.

The child proposal envelope contains `child: assignment`. The assignment declares
`role`, `goal`, `requirements`, `writable_paths`,
`materialization_targets`, `return_contract`, `measure_request`,
`replace_previous` and `prerequisites`. Unneeded grants are empty.
Designer additionally declares the optional approach described above. A supported
conflict can name the affected requirements at a coordinating owner.

The parent supplies task instructions within the declared role. This is not
capability creation: an assignment can narrow its parent's grant, and prose
cannot extend it. A new child inherits relevant history and obligations;
a different invocation identity does not erase unsuccessful attempts or
make old evidence fresh.

Question and Support receive the same disciplined assignment. Their context is
the information needed for the particular question or guidance gap, rather than
the caller's entire transcript. Independent check review includes the actual
checking source, fixtures, original requirements and available observations.
Their read-only capabilities are declared by their bindings; the parent supplies
the question, relevant scope and desired findings rather than inventing a tool
grant in prose. They cannot launch another Episode or edit the Target Workflow.

Each leaf research proposal selects one declared operation:
`web_search` or `library_search` with `arguments.query`, `read_url` with
`arguments.url`, `read_library` with a returned catalog `arguments.source_id`,
or `read_candidate` with `arguments.local_id` and `arguments.section`.
The latter reads one approved Target Workflow Episode's `architecture`,
`materialization`, or `source` from the current candidate. The leaf receives a
compact `research.candidate_catalog` listing approved Episode IDs and whether
their plans and source exist. It can inspect sibling interfaces when relevant to
the caller's question. This is a campaign-local read capability, separate from
the empty write grants: neither arbitrary store IDs nor filesystem paths are
accepted. Exact retrieved sections become candidate-qualified source evidence;
an absent plan or source is reported as unavailable.
These operations retrieve evidence; a later `finding` proposal supplies
per-requirement `state`, `answer`, `applicability`, `limitations` and inspected
`source_ids`. Question uses `answered`, `refuted` or `unresolved`; Support uses
`applicable`, `inapplicable` or `unresolved`. Failed retrieval is a limitation,
not evidence that the researched claim is false. Independent checking-program
review retains its separate `check_review` proposal.

## Measures, credit and rarefaction

Measure owns one composite checking function for its commission. It can author
components directly or commission Measure Parts. Adequate components remain
available while other components are unfinished. Every requirement retains its
separate outcomes; one unresolved case does not erase the adequate work.

Measure Parts can compose admitted components for its assigned scope and return
that work. Only the owning Measure publishes the whole reusable composite.
`compose_components=true` assembles returned admitted work; it does not invent
new cases or award adequacy without their recorded review and controls.

Other Episodes reuse their assigned fixed checking function. Selecting a smaller
part does not redesign the measure. The parent explicitly commissions changes
when the evidence identifies missing or inadequate checking capability.
A newly admitted measure is evaluated on the baseline candidate before repair
credit is attributed under it.

Implementation units sample available unobserved local checks before proposing
a change, preserving pre-edit evidence for credit accounting. An unavailable or
unrunnable observation remains recorded as such while scoped repair can proceed.
Direct `evaluate=true` also lets an implementation Episode choose observation
without submitting an edit.

Checking programs derive expected outcomes from requirements and grounded
evidence, not from the candidate being repaired. Independent Question review
and executed positive/negative controls assess their adequacy. Frozen policy,
required interfaces and behavioral execution have different evidence surfaces:
declared policy is not an invented requirement to echo policy in every response.

Each Episode computes its own numerical credit from admitted evidence at its
scope. Parents do not sum child credit totals. Delegation, design prose, patches,
a restored old pass and repeated failed attempts have no inherent fresh credit.
Verification can make progress by establishing a valid failure; favorable
verdicts are not privileged.

The registered rarefaction function consumes numerical credit. Each Episode's
numerical controller governs continuation and return. An unresolved numerical
return is not successful acceptance, and there is no fixed retry-count schedule
for forcing work through the tree.

## Source, materialization and checking permissions

Host enforcement separates artifacts and instruments:

- MaterializationImplementer and Materialization Parts submit structured
  operations against explicitly granted Materialization Spec targets. Source
  is read-only context.
- Code Implementer and Code Parts edit explicitly granted source paths and
  authorized target environment recipes. Materialization and protected checks
  are read-only context.
- Measure and Measure Parts author checking source and fixtures in their
  measurement workspace. Target source and materialization remain read-only.
- Verify and Verification Parts execute the assigned checks and inspect
  evidence. They do not repair the target or alter the checks.
- Question and Support use declared read-only web research and local
  documentation/library lookup operations, plus on-demand reads of approved
  Target Workflow nodes in the current campaign. Their host path has no source or
  Materialization Spec editing operation, shell execution or child launch.
  Findings never confer another role's write access.

These grants are narrowed at every child boundary. Filesystem confinement and
host admission implement them; the LLM is not trusted to enforce its own scope.
The [coding workspace boundary](implementer_coding_workspace.md) documents the
concrete source/materialization separation.

An incomplete candidate need not import, compile or run before it can be
examined as data. Missing plans and source remain explicit recorded facts.
Target execution still goes through ordinary source admission and the isolated
Run boundary.

## Reports, integration and recovery

Every parent defines what it needs back. The child returns compact, synthesized
measurement outcomes and selected findings suited to that decision. Stored
child reports, raw transcripts and automatically expanded artifacts are not
added to the next parent's message. Full provenance remains in the audit store.

For research leaves, retrieved pages, source text and raw operation responses
remain evidence artifacts. The parent receives the selected synthesized findings
through the same method-owned reporting boundary. Exact-field admission and
capability separation constrain what can be transmitted and what a leaf can do.
They do not prove arbitrary natural-language findings are prompt-injection-free.
The caller treats findings as attributed evidence with limitations, while its
approved goal, permissions and judgment contract retain authority.

A specialist integrates Parts contributions over its own assignment. Designer
integrates specialist findings over the whole approved goal. Cross-specialty
dependencies and conflicting repairs are coordinated there. Helpers supply
evidence or guidance, not instructions that silently rewrite an active goal or
judgment contract. See [Episode communication](episode_communication.md).

All work belongs to one campaign with exact candidate, plan, check and
environment identities. Changes invalidate affected evidence; unknown or stale
results stay distinct from failures and passes. Source edits and materialization
edits use revision-checked host transactions. Repeated publication does not mint
fresh credit. Cancellation preserves partial work and an honest terminal state.

Duet approves the Target Workflow Architecture. The Refiner constructs and
refines its Materialization Spec and source directly; no initial Target Workflow
Builder generation pass or receipt is required. Existing supplied candidate work
is retained subject to that approval. EpisodeBuilder provides shared validators
and source admission, not a compulsory initial construction strategy.

The Refiner uses the owning Duet's model/provider configuration. Isolated
Target Workflow evaluations use the Target Workflow's approved launch
configuration. Those are separate scopes; see the
[launch routing contract](episode_launch_configuration.md).

## Code declarations

- `function_library/refinement_contract.py` declares the role-specific goals,
  prompts, children, inputs and measurement meanings. `PARTS_ROLES` links
  specialists to their Parts; `ROLE_SPECIALIZATION` identifies the operation
  family without erasing the concrete role.
- `episode_library/refinement.py` registers Designer as the launch binding and
  each specialist, Parts and helper as its own concrete Episode binding.
- `iterative_episode_refiner/design.py` places the four specialists below
  Designer and Parts below their specialist. Repeatable calls supply same-Parts
  recursion and Question/Support from every non-helper role. Both helper
  declarations have empty child sets and materialize as leaves.
- The existing `method_loop` supplies the Episode loop, parent-owned reporting,
  nesting and numerical routing. Host refiner operations implement the declared
  scoped capabilities through the existing artifact store and execution paths.

A correct implementation must preserve this entire ownership structure,
task-specific direct work, assignment inheritance, Measure's composite ownership
and helper reachability. Changing only the displayed tree or prompt titles
does not implement the design.
