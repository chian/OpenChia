# IterativeEpisodeRefiner: executable contracts

The current ownership contract follows the
[approved Designer-root design](iterative_episode_refiner_episodes.md).
Designer coordinates four peer specialists, each with its own Parts binding.
Question and Support are callable from every role. The sections below retain
explicitly dated earlier evidence as history; those receipts do not prove the
new topology or grant continuation under its changed role contract.

The [repository mapping](iterative_episode_refiner_integration.md) identifies
existing symbols, required extensions, storage, migration and file ownership.
Proposed record and function names below describe exact responsibilities; reuse
an existing type where the mapping identifies one. Do not create a second registry.

## 1. Fixed decisions

1. Designer owns the general approach and whole-workflow coordination.
2. MaterializationImplementer, Code Implementer, Measure and Verify are peers
   below Designer. Each performs its own work and can delegate a smaller
   contribution to its task-specific Parts binding. Parts recurses only within
   the same specialization.
3. The next contribution is selected from current artifacts, evidence and the
   goal. Recording an approach and executing its selected child share a measured
   unit; the host does not prescribe materialization, implementation or
   verification as an automatic sequence. Each operation still obeys its actual
   data, authority and measurement prerequisites.
4. All loops use host-admitted facts, registered numerical control and durable
   history. A stage does not contain a hidden substantive retry loop.
5. Candidate source and implementation details are editable artifacts. The
   approved purpose, active role contracts, capabilities and measuring rules are
   not editable by a running child.
6. The campaign has one current candidate writer. Candidate changes invalidate
   affected evidence immediately. The selected result can be an earlier candidate.
7. All levels share the campaign's revision, regression and attempt records.
   Models receive scoped projections, not one shared conversation.
8. A raw claim, including a claim of success, a block or a repair cycle, is not an
   authoritative decision. Host checks require the supporting observations.

There are two approvals to distinguish: authority to refine this target, and
approval of the refiner's own executable role graph and capabilities. Approving
this document does not silently manufacture either runtime approval.

Model configuration follows the [Duet/refiner/target boundary](episode_launch_configuration.md#duet-refiner-and-target-model-boundary):
the refiner's reasoning uses the owning Duet's configuration; execution of a
Target Workflow uses that target's launch configuration. Sharing an executor does
not merge these settings. No separate refiner model launch file is required.
The typed `DuetLaunchRequest` and checker/provider `launch_ref` inputs described
below are task-input envelopes, not model/provider configuration. Keep those
input identities distinct from the model configuration recorded for each Run.

## 2. Contract notation and identity

Records are closed: unknown fields are rejected. Arrays are ordered unless the
schema explicitly treats them as sets; canonicalization sorts those sets and
rejects duplicates. No NaN/infinity, arbitrary Python objects or executable text
enter authoritative records. `null` is explicit absence, not a guessed default.

- `Id`, `Hash`: existing OpaqueId/content_id and Sha256Digest conventions.
- `Ref`: `{artifact_id: Id, content_hash: Hash}`; resolve both, not just the ID.
- `FunctionRef`: existing exact library/function/interface/definition_id/arguments
  selection. Names below require registered definitions before materialization;
  this document does not invent their eventual content hashes.
- `EvidenceRef`: `{store_kind, owner_id, record_id, content_hash, observation_path}`.
  `store_kind` is `run_audit`, `build_artifact` or `duet_artifact`. The host resolves
  the original committed record and the schema-admitted observation path. A model
  quotation, URL, child report or file name alone is not evidence.
- `SourceRef`: `{artifact: Ref, json_pointer, semantic_key}` pointing to an exact
  approved requirement, fixture, predicate or library definition.

Every new persisted artifact has a versioned envelope:

```text
Artifact = {
  schema_id, schema_version, artifact_id, content_hash,
  campaign_id, invocation_id | null, logical_unit_id | null,
  producer_ref, evidence_refs[], predecessor_refs[], body
}
```

`producer_ref` identifies an authenticated model response, observed tool/Run event,
human approval, or the registered host function and its inputs. Models cannot
select host provenance. Hash schema identity/version and canonical semantic
content; exclude the ID/hash themselves and storage timestamps. New revisions
create artifacts and relations, not overwritten bodies. Request/audit records
retain the actual Run and call identities even when semantic deduplication uses
a more stable key.

Identity layers must not be collapsed:

| Identity | Lifetime / purpose |
| --- | --- |
| campaign_id | One target approval lineage and refinement history, across worker Runs |
| requirement_key | Original approved behavioral requirement; survives splitting, renaming and reassignment |
| assignment_id | Immutable task contract, including measure and authority |
| invocation_id | Logical execution of that assignment; survives a recovery Run |
| runtime episode_id / run_id | Existing concrete worker execution and path identity |
| logical_unit_id | Invocation plus contiguous semantic unit ordinal |
| operation_id | Unit, declared stage and operation slot; stable across transport retries |
| semantic_fact_key | Meaning of a credit-bearing achievement, independent of call/child/revision labels |

A retry of the same operation with a different payload is a conflict. A revised
proposal is a new recorded attempt, not a replacement for an interrupted request.
Transport frame sequence numbers still start fresh for each actual Run.

## 3. Durable task and candidate records

### 3.1 CampaignContract

Required fields:

```text
target_approval_ref, target_workflow_ref, initial_build_inputs_ref,
initial_materialization_ref, initial_candidate_ref,
refiner_workflow_approval_ref, refiner_manifest_ref,
requirement_catalog_ref, authority_ref, policy_bundle_ref,
environment_ref, guidance_catalog_ref, final_projection_ref
```

The policy bundle fixes schemas, role/action/child bindings, stage graphs,
admission functions, equivalence functions, conflict rules, numerical components,
scope limits and evidence-retention policy. Initial source need not be executable.
Absence of a runnable manifest is an initial finding, not a reason to skip refinement.

The working state names `head_candidate_ref`, `selected_candidate_ref`, active
assignment/invocation refs, pending operations, requirement/check states, conflicts
and admitted lessons. These are projections of committed transitions, not fields
that a worker may set directly.

### 3.2 Requirement

```text
requirement_key, origin_refs[], parent_requirement_keys[], scope_refs[],
behavior_statement, mandatory, acceptance_predicate_ref | null,
grounding_refs[], dependency_keys[], coverage_rule_ref,
required_evidence_classes[], limitation_refs[]
```

Statements explain the task; predicates and grounding determine admissible claims.
Root requirements preserve every mandatory approved deliverable, interface,
invariant and declared behavior. An unformalized requirement remains visible with
an absent predicate; it cannot silently disappear from the final readiness check.

A decomposition must preserve the parent's original requirement keys and coverage
rule. Splitting one condition into ten checks cannot create ten parent achievements.
Newly discovered implementation conditions may refine a root requirement, but
new mandatory product goals require target approval. An uncovered or ambiguous
requirement produces a decision request, not an invented definition of success.

Recursive subdivision currently narrows persisted requirement keys, source paths
or Materialization Spec targets. It does not have a separate case-slice assignment
field. A single requirement with no smaller editable grant is direct work at the
current Episode; describing a narrower case in prose cannot establish a child
scope. Components can still contain many cases and local functions. A future
explicit slice contract would need actual containment, coverage and persistence
before case-only child delegation becomes available. Decomposition earns no credit.

### 3.3 Assignment

```text
assignment_id, parent_assignment_ref | null, coordinating_invocation_id,
role, scope_requirement_keys[], contribution_requirement_keys[],
scope_partition_ref, owned_slice_keys[],
baseline_candidate_ref, goal_record_ref, authority_ref,
input_refs[], preservation_requirement_keys[], dependency_refs[],
local_measure_ref, acceptance_measure_ref, progress_manifest_ref,
allowed_action_classes[], allowed_child_bindings[], instruction_refs[],
history_query_ref, return_projection_ref, control_bundle_ref,
supersedes_assignment_refs[]
```

`role` is one of the eleven concrete roles in §5. Designer is the root.
It creates peer specialist assignments. Each specialist can create its own
Parts assignment; each Parts can create a smaller assignment of that same
specialization. Every role can create Question or Support assignments, including
helpers themselves. Host admission verifies the caller, declared edge, scope
attenuation and fixed measurement. The coordinating invocation is the direct
parent, or the root's own invocation at the root; it is not implicitly a Parts
owner. The parent proposes the assignment under the frozen policy.

The assignment's baseline and criteria never change. Its current candidate
observation may advance through admitted revisions. A materially different goal,
scope, measure or authority requires a successor assignment and explicit closure
of the old one. Relevant history and already credited semantic facts carry over.

Reassignment with equivalent criteria/conditions retains its numerical observation
history as well as its credit keys. A genuinely different admitted criterion or
applicability cohort may require a new estimator state, explicitly linked to the
old one; prior evidence is reclassified by the frozen applicability rule, never
deleted or relabeled as fresh discovery. This occurs at a successor assignment
boundary, not through a worker changing the active controller epoch.

Current model-facing proposals use specification requirement locations and
`replace_previous: true` to replace the latest returned child of the same role
and contribution. The admitted assignment retains the exact predecessor
references internally. These use the existing `assign` operation. Host
admission requires returned direct children with committed parent reports,
unchanged authority, and retained scope, contributions, preservation requirements,
owned slices and protected paths. Ordinary replacement retains the role; the
existing owner-scoped joint-conflict operation remains the separate combining
route. Old assignment/invocation indexes become superseded in the same transaction
that installs the ready successor. Creating the assignment earns no progress.

Replacement measures must already be authorized, including measures admitted in
the predecessor's scope. A changed measure must preserve every old mandatory
typed criterion, guard and established instrument/input binding; it may add
grounded coverage. Changing a measure for the same direct-child contribution and
slices requires an explicit predecessor link, not an unlinked fresh assignment.
This is an exact typed preservation rule, not permission to declare natural-
language criteria equivalent or withdraw inconvenient checks.

`succession.py` projects equivalent predecessor check facts into successor keys
for both credit admission and numerical observation history. Original receipts,
evidence and credit rows remain unchanged. Different roles' credit is not copied,
and this historical projection does not establish current passing check state.
The parent receives the latest contracted child return for each role and
requirement scope, including whether it applies to the current candidate and
whether the child can be replaced. Established local and acceptance measurements
are inherited. Explicit Measure assignments request new grounded coverage by
purpose and original requirement location; ordinary continuation does not choose
measure hashes. The current campaign history/conflict index remains authoritative.
Root replacement and materially
different criteria/authority still require the approval boundary; that successor
handoff is not implemented by this child-assignment path.

For support roles, the local measure is the role-specific evidence gate in §6,
instantiated for the named need; it is not an absent metric. Every role also has
an exact return predicate. Guidance text cannot redefine any of these fields.

### 3.4 DesignPlan

```text
assignment_ref, approach_key, requirement_mapping[], assumption_refs[],
proposed_component_refs[], intended_change_scope[], intended_materialization_targets[], dependency_effects[],
local_measure_ref, acceptance_measure_ref, preservation_measure_refs[],
expected_observation_refs[], falsifying_observation_refs[], open_need_refs[]
```

The host admits an approach as eligible to try when requirement coverage,
authority, interfaces and measure adequacy pass. This is not evidence that the
approach works and earns no credit merely for being admitted. Unresolved needs
that affect coding eligibility must be resolved before coding starts.

For numerical-controller work, the mapping covers credit, rarefaction,
continuation and their composition in the same plan and acceptance contract.
Success of one function does not close that assignment.

### 3.5 Candidate and ChangeSet

```text
Candidate = {
  parent_candidate_ref | null, target_approval_ref, materialization_ref,
  source_manifest_ref, implementation_directive_refs[], change_set_ref | null,
  source_admission_ref | null
}
ChangeSet = {
  assignment_ref, design_plan_ref, expected_head_ref,
  file_operations[], implementation_detail_operations[], rationale_claim_refs[]
}
FileOperation = {kind: add|replace|remove, logical_path, before_hash | null,
                 after_blob_ref | null}
```

Code Implementer/Code Parts propose source changes; MaterializationImplementer/
Materialization Parts propose structured plan changes. Host admission resolves logical paths
inside its authorized candidate, verifies before hashes, forbids symlink/path
escape, rejects protected-check/runtime/credential edits, and checks the current
head by compare-and-swap. Removals preserve prior blobs and are audited.

Implementation-detail operations name exact JSON pointers and before/after values.
Active repairs use the frozen target allowlist and the Builder's plan admission
against the original approved workflow. The legacy semantic-change classifier is
part of the human-authorized successor path, not an automatic plan-edit API.
Changing task meaning, topology or allowed capabilities requires a successor
proposal for the Duet; it cannot mutate the active target contract.

Current code-facing mapping (unexecuted):

- `implementation_detail_operations` contains
  `{json_pointer, before, after}` records. Targets must appear exactly in frozen
  `policy.materialization_edit_targets`. `/episodes/<id>/parts/node_plan/<field>`
  replaces one implementation choice; `/episodes/<id>/parts/node_plan` supplies a
  complete **planner-choice projection**, not a serialized host-owned node record.
  That projection uses the existing Builder input fields and excludes host-added
  repeatable-call bindings. Its before value is supplied in scoped context;
  it is null only when the approved node has no plan yet.
- Permitted fields are interface, result channel names, request/result payload
  contracts, selected bindings, component/prompt specifications, goal-state
  details, derivation basis and parent-owned `child_slots`. An exact target grant
  is still required for each. Contract hashes, workflow topology, capabilities,
  numeric selections, reference identity and repeatable-call authority are not
  editable choices. Changing representations never grants changed task meaning.
- A coordinated batch must preserve the typed graph: child-interface/payload
  changes require matching parent edges. The union of explicitly edited and
  mechanically affected module paths must fit the assignment and admitted design
  plan, excluding protected paths. Missing children are filled within the approved
  workflow; the operation cannot invent child Episodes.
- `episode_builder.plan_choices` is shared with initial planning;
  `iterative_episode_refiner.plan_repair` applies scoped choices and uses the
  existing native checks. Unresolved design choices remain unresolved rather than
  disappearing when mechanical errors are corrected.
- An immutable `materialization` record retains the original baseline, typed
  revised plan and changed targets. Optional `instrument_plans` retains separately
  authorized checker-plan revisions in that same record (see §4.3). It commits
  with the candidate. Original
  materialized specifications/receipts are not overwritten; ordinary source
  admission creates a new receipt for the exact revised candidate. Plan changes
  invalidate prior check dependencies and earn no credit merely for being edits.

Source rejection does not destroy a candidate or end the campaign. It prevents
execution until repaired. Source admission and behavioral verification remain
separate records. Checks/instrument code have separate protected artifacts; they
are not silently part of the target edit scope.

## 4. Measures grounded in the actual task

### 4.1 MeasureContract

```text
measure_id, requirement_keys[], purpose: local|acceptance|adequacy|composition,
oracle_kind: registered_predicate|independent_execution|approved_review,
oracle_ref, input_domain_ref, case_manifest_ref, observation_schema_ref,
decision_function_ref, required_check_keys[], preservation_check_keys[],
progress_milestone_refs[], adequacy_evidence_refs[], dependency_manifest_ref,
uncertainty_policy_ref, independence_policy_ref, applicability_ref
```

A case specifies exact input, independently grounded expected relation/outcome,
its source, relevance to the requirement, and counterexamples it must distinguish.
A progress milestone specifies a discrete threshold in an observable quantity or
a predicate over check results. No scalar supplied by the model is authoritative.
The manifest and milestone predicates are admitted before the affected coding
assignment. Unscheduled checks are unknown, not passing.

The Designer's own parent-assigned acceptance measure and the local measure it
selects for its Implementer are distinct. The design plan fixes the latter before
calling the coder; selecting it does not revise the former. EstablishMeasure
returns a typed instrument proposal to its assigning parent. The report preserves
its original grounding/control references and proposed status until shared host
validation admits it; a returned proposal is not automatically a usable measure.

Every predicate is an exact registered FunctionRef with schema-validated parameters,
or an admitted instrument whose output a registered decision function interprets.
It is not a Python expression or natural-language rule sent for host evaluation.
Semantic equivalence is established through canonical typed keys and admitted
predecessor relations. A model comparison may propose a relation but cannot alone
authorize novelty credit. Ambiguous equivalence remains unresolved rather than
being treated as a new achievement.

Supported grounding has an actual stopping point:

- Existing trusted predicates with documented applicability and negative controls.
- A separately admitted executable reference, exhaustive solver, proof checker,
  fixture oracle or declared statistical procedure, with its own source identity.
- An explicitly authorized human/reviewer determination bound to the exact
  requirement, candidate, evidence and criterion. A model suggestion is not this.

The implemented Measure admission route currently supports only
`registered_predicate` and `independent_execution`. `approved_review` is a
reserved contract alternative, not an available operation; it is not offered
in the model's proposal shape. The normal-build preparation must supply an
applicable grounding source or construction/acquisition route. The presence of
the general schema or a missing-grounding report does not supply that route.

These are not universal truth machines. If none can support the claim, record
`measurement_gap`; do not replace the oracle with model agreement. A counterexample
may conclusively refute a universal claim while a finite passing sample supports
only the stated tested domain. Reports and readiness must retain that distinction.

### 4.2 Admission of a measure

The host checks, in order:

1. The original requirement and approved interpretation are linked; no mandatory
   condition is dropped or changed. Unresolved interpretation requires authority.
2. The oracle's provenance and applicability support the expected result. Expected
   outputs copied from the candidate being repaired are not independent grounding.
3. Inputs, observation extraction, decision predicate and uncertainty treatment are
   exact, runnable when execution is needed, and permitted by capabilities.
4. Adequacy evidence includes known satisfactory and violating controls for each
   discriminating condition, including trivial-output/constant-pass challenges
   where applicable. A mere assertion that such controls exist is insufficient.
5. The instrument's result changes the relevant decision, and its limits match the
   claim. Passing controls is necessary, not proof of general semantic adequacy.
6. Local milestones do not substitute for parent acceptance; preservation checks
   and the parent-owned acceptance instrument are protected from the coder.

The host can verify these explicit relations and trusted determinations. It cannot
prove arbitrary natural-language entailment automatically. A model-authored
requirement interpretation remains proposed until grounded under the selected
policy; missing grounding remains an open requirement.

### 4.3 Instrument-building without self-certification

EstablishMeasure may select or instantiate an admitted instrument and run adequacy
observations. It cannot create an unchecked executable and certify it itself.
When instrument code is needed, it returns `instrument_build_required` with a
grounded input/output/control specification. Its owner returns this cross-specialty
need to Designer, which can commission scoped materialization or source work.
Measure and Measure Parts also have their own checking-code workspace for direct
authored programs, followed by independent review and executed controls; that
route does not require inventing another Target Workflow build.

The instrument-building coder needs an already grounded local measure, such as
independent fixture expectations and protocol checks. If that foundation is also
missing, ResolveQuestion or an authorized human supplies it, or the task returns
a measurement gap. There is no infinite chain of agents certifying each other.

Implemented request boundary: EstablishMeasure can select
`{prerequisite_request: {need_key}}` from its host-projected `measure_needs`.
The host derives missing measurement authority or absent applicable complete
grounding cases from the frozen policy and original requested requirements. It
does not accept an arbitrary model-authored reason to stop. For construction, the
frozen `measure_admission` grant may additionally name `instrument_build_refs`.
Each independently authorized specification supplies:

```text
purpose, requirement_keys[], checker_ref, input_contract_ref, output_contract_ref,
local_measure_ref, acceptance_measure_ref, grounding_refs[],
positive_control_refs[], negative_control_refs[], limitation_refs[],
optional acquisition_refs[]
```

The build request selects that exact task specification. It is not a verdict that
an existing checker is defective, proof of adequacy, or authority to modify its
source. The specification needs both control classes and independent grounding,
either already committed or obtained through its exact frozen acquisition routes
(§4.3.1); an acquisition declaration is not the resulting evidence. All references
are resolved. Unknown requirements, rewritten specifications and
arbitrary cross-scope references are rejected.

The existing `propose_measure` operation records a host-derived
`measure_prerequisite` in the campaign's `measure_need` index. Publication
independently reconstructs the selected request. The ordinary unit close returns
`needs_parent_decision` with its exact record reference; creating the request earns
no credit. The caller receives original policy/specification/evidence references,
not a generated summary. No new worker transport operation or runner is involved.

Assignment proposals may name `prerequisite_refs` from their returned Measure
children. Host admission verifies actual ownership/return, preserves the entire
requested requirement scope, and retains the references in the assigned goal and
existing `input_refs`. Descendants receive `assigned_prerequisites` unchanged.
Those references cannot expand editable paths, replace measures or create a new
child edge. EstablishMeasure still cannot call a Designer. Original inputs remain
available as the owner chooses ordinary preparation or returns missing authority.

Live evidence on 2026-10-03 reached this prerequisite return after a Designer
plan lacked required measurement coverage. The normal-build campaign had no
applicable construction or acquisition route for those requirements, so this
return exposed a system gap; it did not demonstrate autonomous instrument
construction. See the shared harness receipt log.

#### First-time check design in normal builds

The code inspection after that live run identified an earlier missing operation,
not just omitted configuration:

- `measure_needs.build_specification` requires a checker reference, local and
  acceptance measures, and existing controls or exact acquisition routes.
- `instrument_builds.prepare_sources` resolves that checker to an existing
  approved workflow and Builder receipt before adding its source to the campaign.
  This supports repairing an existing checker, including a partial build; it
  does not define a new checker from a requirement.
- `grounding.specification` and `acquired_value` accept expected values and
  controls only from a previously authorized, independently built evidence
  source with a fixed case template. They do not admit a parent's newly reasoned
  test expectations.
- `measures.require_implementation_measure` correctly prevents a coding
  assignment without its local metric, but these preparation restrictions can
  leave no operation that can establish that metric.

The missing step identified then was parent-owned check design and admission
before checker construction: the precise requirement being tested, expected and
falsifying results, justification, observation contract, controls and limitations.
Measure now owns direct authored checking components through its shared coding,
review and isolated-control path; a separate approved checking workflow remains
a distinct construction option.

Decision confirmed by the user: parent-designed expectations may be admitted
under the initial job grant after separate review against the original requirement
and executable positive/negative controls. This is routine refinement, not a
reason to request another human approval or stop the goal.

New normal-build campaigns freeze `measure_admission.reviewed_designs.version=1`.
EstablishMeasure may submit `check_design`: original specification requirement locations, a registered
predicate, expected observations, justified satisfactory/violating controls, an
authorized execution binding, and limitations. The host records an immutable
`measure_definition`, then calls the existing ResolveQuestion child to review it.
The child checks requirement fidelity, observation relevance, expected-result
justification, control polarities and limitations. Its typed `measure_review`
returns through the ordinary parent report. Definition and review earn zero credit.

After that separate child returns, EstablishMeasure explicitly submits its current
design with `submit_reviewed_design: true`. The host resolves the exact immutable
definition and its returned review, then projects the reviewed definition into ordinary
grounded cases and uses the shared predicate/control admission code. Self-review,
unreturned reviews, counterexamples, changed definitions and failing controls
cannot admit a measure. The publication boundary reconstructs the projection;
merely storing a case cannot authorize it. The existing campaign index adds
definition/review collections transactionally; no new store or replay path exists.

Review agreement is not evidence of Target Workflow correctness. Expected values
retain their reasoning/review provenance, and passing finite controls does not
prove general adequacy. Measure and Measure Parts can author executable checking
programs as well as select registered observation predicates. Existing separate
checking-workflow and source-acquisition routes retain their own explicit
authority. Older frozen campaign evidence does not establish the current
Designer-root design's live acceptance.

Source/plan construction mapping (implemented in source, not executed):

- Request authority is not edit authority. The frozen policy must additionally
  include `editable_instrument_refs`, a unique subset of its approved
  `instrument_build_refs`, before preparation adds checker modules to the
  candidate. Each specification names a separately approved checking workflow
  and its original Builder receipt; a partial/rejected receipt is repairable.
  The Target Workflow cannot be its own checking workflow.
- `instrument_builds_ref` optionally freezes the checker baselines, original
  handoffs and module-path mapping in the campaign. Modules live in the existing
  candidate `files` under
  `__refinement_instruments/<spec-artifact-id>/<original-module-path>`. This is
  source separation, not another campaign, scheduler or reasoning-child graph.
  Parents must still assign the paths and distinct grounded local/acceptance
  measures before their Implementer can change anything.
- Checker plan targets use
  `/instrument_builds/<spec-artifact-id>/episodes/<local-id>/parts/node_plan[/<field>]`
  in the same frozen `materialization_edit_targets` list. They need both the exact
  target grant and writable scope for every affected module. Scoped context gives
  each instrument its own `candidate_materialization` projection, original
  approved design, missing nodes, choice shapes and exact before values.
- The same implementation-detail operation and Builder plan validators apply to
  primary and checker plans. An atomic batch can coordinate already-approved
  nodes in either package. Optional `materialization.instrument_plans` maps each
  exact specification ID to `{baseline_ref, plan}`; primary and checker changes
  commit with one candidate revision. Source-only edits retain those plans;
  subsequent plan edits retain untouched packages. Plan changes conservatively
  invalidate check state, and shared cycle comparison includes checker plans.
- Local checking-build measures use an instrument binding
  `{execution_kind: "instrument_build", instrument_build_ref: <exact spec ref>}`.
  Their input is the ordinary zero/one Duet launch template for that checker,
  with independently supplied fixture expectations. Source admission, typed
  input validation and evidence reconstruction select the current checker plan
  and module bytes through the existing Builder and executor. This first route
  supports execution checks, not an auxiliary static-check catalog. Source/plan
  deficits remain unavailable evidence, never a fabricated behavioral result.
- Checker admissions cannot serve as the primary build's final source receipt.
  A repaired checker is not automatically a trusted oracle, and editing it does
  not replace the measures judging its own implementation or its parent task.

Constructed-instrument return mapping (implemented in source, not executed):

- `instrument_returns` offers exact `{spec_ref, report_ref, source_ref}` selections.
  The source must belong to that authorized construction specification and the
  candidate in a returned Designer report. The Designer must have attained its
  independently assigned acceptance measure; every required acceptance check and
  transitive guard must have passed through its own returned Verify child. A local
  Implementer pass, successful compilation or model summary is not this return.
  Reports with unresolved decision-required conflicts for those requirements do
  not qualify. A suspected exact revisit alone is not a failed acceptance.
- The selection is available only within the construction owner's branch. A
  Measure proposal may optionally include `instrument_return` with that exact
  selection. It retains the original `oracle_ref`, complete independently grounded
  case set, purposes, controls, input mapping and limitations. The host derives a
  checker descriptor changing only the build receipt, and matching evaluation
  instruments changing only that descriptor plus construction provenance.
- Those are immutable reference-data artifacts in the existing Duet store, not
  new operative policies. Optional `measure_proposal.instrument_return_ref` links
  the resulting bundle. Admission independently reconstructs its Designer report,
  acceptance observations and exact source admission, rejects unrelated source
  substitutions, and carries those original references as evidence.
- The revised bindings enter the same executable-control preparation, Run and
  observation path as already-built checkers (§4.5). Every original positive and
  negative control still needs its actual independent outcome. Failing, missing
  or inconclusive controls reject the measure. The checker-construction return
  itself receives no measure-adequacy credit.
- Admitted checks pin that exact checker receipt. Later source edits or assignment
  supersession do not silently replace it or erase its original return evidence.
  A new measure still requires admission and an authorized future/successor
  assignment; existing assignment criteria remain frozen. Comparison for novelty
  uses checker source and plan meaning, not new report/receipt IDs for the same
  code. Repackaging an identical build is not another adequacy achievement.
- Successor validation retains every original mandatory criterion and guard. For
  an admitted constructed-checker measure, the exact original instrument can be
  replaced by its independently accepted construction result; the original input
  values, capability and result mapping remain unchanged. This narrowly grounded
  source substitution is not a general right to swap instruments. Credit/history
  comparisons still distinguish the new checker source, and no active assignment
  is mutated.

The construction, acquisition and adequacy connections remain unverified.
Consolidated integration/compatibility review is in progress; no claim of
executable completion follows from this mapping.

### 4.3.1 Acquiring missing measurement evidence (implemented, unexecuted)

The optional frozen `measure_admission.acquisition_refs` array names records with
this closed shape:

```text
need_ref, case_template_ref, source_ref, control_kind: predicate | execution
```

`need_ref` must name an authorized ResolveQuestion need for the same requirement.
`case_template_ref` supplies every complete-case field except `expected`,
`positive_control_refs` and `negative_control_refs`. It freezes the purpose,
oracle, domain, predicate, observation mapping, environment, guards and limits;
the child cannot redesign those after seeing the candidate. `source_ref` names
the independently approved read-only workflow in §7.1.2.

The question's fixed check projects a typed source result with `expected`,
`positive_controls` and `negative_controls`. Both control arrays must be nonempty
and cannot contain the same input on opposite sides. Predicate controls contain
`{observed: ...}`; executable controls contain `{typed_status: ...}`. The registered
`grounding_payload_v1` predicate checks this structure, **not whether the answer
is true**. The frozen independent source/projection authority is essential;
arbitrary model output or a successful unrelated Run is not an oracle.

Measure context exposes the exact acquisition specifications and available
returned findings. A proposal may select:

```text
acquired_grounding: [{acquisition_ref, report_ref, observation_ref}]
```

The host requires an owned returned question, its original supported finding,
successful observation and exact admitted source. It derives complete immutable
cases and control fixtures from that evidence, preserving the template. Optional
`measure_proposal.grounding_acquisition_refs` retains the projection bundles;
measure admission re-derives them instead of trusting the proposed case values.
Ordinary predicate controls or actual checker-control Runs still establish
adequacy. Acquiring expected values is not itself admission of a usable measure.

For a constructed checker, `acquisition_refs` in the original construction
specification fixes the additional required routes. Its measure must include
exactly one admitted acquisition per route, all original cases and the full union
of original/acquired positive and negative controls. Unrelated routes, omitted
cases and weakened expectations are rejected. Existing specifications without
this optional array still require their complete precommitted case/control set.

No available authorized source means an unresolved grounding request, not a
fabricated expected answer or permission to approve a workflow. This route does
not provide arbitrary scientific truth, new design authority or universal
measurement synthesis. Active parent criteria remain frozen; admission makes a
measure available for an authorized future assignment, not retroactive success.

### 4.4 Current first-route mapping (unexecuted)

The frozen campaign policy can authorize `measure_admission` with
`{adequacy_measure_ref, grounding_refs}`. Grounding references designate
independently approved complete cases for original requirements, not model-written
claims of entailment. The adequacy assignment selects that exact measure; the
host action `admit_measure` must also be authorized. There is no implicit grant.

A grounded case names `requirement_key`, `purpose`, `expected`, `observation_path`,
`dependency_paths`, `environment_ref`, `oracle_ref`, `input_domain_ref`,
`observation_schema_ref`, `decision_function_ref`, `independence_policy_ref`,
`uncertainty_policy_ref`, `limitation_refs`, `guard_keys`, positive/negative control
refs, and `execution_binding: {harness_ref, capability_ref, input_refs}`. Each
control is committed data `{observed, expected_outcome}` under that independent
authority. The proposed case manifest composes `grounding_refs`; it cannot edit
the cases or their expectations.

The initial implementation accepts registered observation predicates and the
existing native Target Workflow evaluation route. It verifies the controls and
retains all declared limits before installing the resulting scoped checks. An
admitted measure is available to its owner and descendants for later assignments,
not as a mutation of an active criterion. A closed `measure_admission` records
proposal/owner/measure/check refs, the evaluation binding, control outcomes,
grounding, status/reason and semantic adequacy keys. Parent reports retain these
references; they are not model summaries or execution results.

Several authorized complete cases can constrain the same requirement; the manifest
must retain their controls and guards. Each selected grounding is independently
authorized as a complete case, not an arbitrary model-selected fragment of a
larger requirement. Distinct grouping/proposal IDs are not progress identities.
Cases can now use different independently authorized native input contexts. When
there is more than one, every generated check carries its exact `execution_binding`
and the admission carries `evaluation_bindings` with the legacy singular binding
set to null. One-context admissions keep their original v1 fields and hashes.
The native bindings reference complete typed root launch inputs as described in
§7.1. Admission checks their identity and payload types independently of mutable
Target Workflow code; execution additionally requires the current admitted root interface
to accept each payload. This does not create new oracle grounding.

The existing evaluation service groups checks by these frozen contexts, records
all requests, admits candidate source once and invokes the existing executor for
each executable context. A check belongs to exactly one context: a favorable result
for a different input cannot overwrite its outcome. An ambiguous unbound check is
an explicit gap; the host does not choose its context arbitrarily. Guards can be
evaluated in another declared context, and remain necessary for operative progress.
Missing coverage or an unavailable case is retained even if another case executes.

On return, the assigning parent can establish a separate `measure_available`
decision from the admission and its original request. The resulting
`prerequisite_assessment` links the exact report, admission, purpose, requirements
and limitations. It is committed with the parent's unit and re-derived at the
publication boundary. Its fact keys derive from criterion/instrument meaning,
not the child's score. A useful new measurement option can therefore advance the
parent's inquiry without marking the implementation correct. Repeating the same
option earns no additional credit in that judgment lineage.

This is not the full §4.3 instrument-building path. No generated checker is
self-certified by these control comparisons, and a frozen grounding reference
is not permission to invent expected outputs for an unfamiliar requirement.
Unsupported instruments/grounding remain explicit parent decisions. The missing
general paths remain part of the implementation goal.

### 4.5 Executable checking adequacy (implemented, unexecuted)

For `oracle_kind: independent_execution`, `oracle_ref` must name the exact
`checker_ref` of every grounded case's instrument (§7.1.1). The checker must already
have its own approved materialized build. The original complete-case authority,
purposes, requirements, interpretation and limitations remain unchanged.

Each executable control is independently committed data:

```text
typed_status: a known satisfactory or violating result fixture
expected_outcome: pass | fail
```

Every case requires both polarities; a control cannot be repeated or assigned both
polarities in one case. These are labelled fixtures, not fabricated target Runs.
The checker receives them through the same frozen result-to-input mapping used on
real target outputs. A model may compose authorized complete cases but may not
write new expected answers and thereby authorize itself.

The assigned measurement contract must explicitly permit `bind_measure_control`
and `observe_measure_control`, in addition to measure proposal/admission. The
shared evaluator validates the complete case set before launching anything. It
then uses its existing checker preparation, source registration and executor for
each control. There is no alternate test runner or worker capability surface.

`measure_control_run` names proposal, grounding and control refs plus either its
exact Run registration or a typed preparation gap. The host independently checks
the approved checker build and complete fixture-derived launch before binding.
`measure_control_observation` names that original binding and actual execution,
preserves terminal-event evidence, and records the frozen extraction/predicate
outcome. Missing/wrong-typed checker output or unsuccessful execution is `error`,
never an invented `pass`/`fail`. These control records never mark target checks as
passing or earn target-repair credit.

Admission requires every original control observation and checks it against its
independently assigned polarity. All known-good controls must be accepted and all
known-bad controls rejected. Pending/unavailable controls, errors, inconclusive
results and mismatches reject the proposed measure. The admitted state records
the original control Runs, observations and evidence; publication re-derives the
comparison. Numerical progress is still the existing deduplicated measure-adequacy
transition, not the number of Runs or examples processed.

Control binding and observation use the existing campaign transaction/index under
the `measure_control` collection. Native predicate-control records keep their
prior shapes. Executable measure admissions additionally retain `control_run_refs`
even on rejection. Parent context carries a bounded typed projection of original
verdicts; complete history remains linked. Final build evidence includes the used
measure-admission refs and original control Run evidence, verified without another
execution or predicate pass.

Finite controls support only their declared domain and limitations. This route
does not prove arbitrary natural-language adequacy or construct a missing checker.
The construction-to-adequacy return (§4.3) and acquisition of independently
authorized grounding (§4.3.1) are implemented in source and remain unexecuted.
The existing-index collection migration is also unexecuted. No execution proof
is claimed for this implementation.

## 5. Executing each Episode

Common loop entry: retrieve the assignment, exact current candidate, relevant
attempts/lessons, current evidence, pending stages and parent decisions. Reuse a
pending operation before selecting anything new. Selection is a typed proposal;
the host admits it against stage eligibility, authority and previous observations.
Missing/invalid choices do not default to the first permitted action.

Each numbered path below is one declared repeated unit. A support action can be
its own unit; its result does not allow the source to skip the required realization
path. Incomplete substantive work is continued by another measured Episode unit,
not an internal unmeasured retry.

### 5.1 Designer

Goal: choose and revise the general approach until the approved Target Workflow
meets its original requirements.

The root receives current artifacts, exact candidate, whole-workflow composition
measurement, previous approaches, relevant dependencies and returned findings.
Its proposal contains an optional `plan`, a chosen `child` assignment and an
optional `conflict`. A plan records general approach, requirement reasoning,
source/materialization scope and dependency effects. The chosen child is one of
the four peer specialists or a declared helper.

Designer can record or revise an approach and then perform its selected
contribution in the same measured unit. A null plan retains the current approach
or allows investigation/measurement before an approach has been established.
This avoids treating design prose alone as a substantive numerical sample.
The selected peer is not fixed by the host. Current missing plans, source,
checks or observations inform Designer's reasoning; they are not a prescribed
materialize-then-code program.

Whole-workflow readiness uses independent composition evidence. Local source or
materialization improvement does not establish readiness. Designer selects
Verify when useful; automatic baseline verification and automatic post-edit
verification are not strategy substitutes.

Designer coordinates returned cross-specialty needs within the approved
architecture. It retains original requirements and history when changing the
approach or combining work. Its result is the whole-scope determination and
unresolved frontier, never a sum of child credit scores.

### 5.2 Specialized Parts

Concrete roles are `materialization_parts`, `code_parts`,
`measure_parts` and `verification_parts`. Their respective parents are
MaterializationImplementer, Code Implementer, Measure and Verify. Each has
its own goal, prompt, operations, measurement meaning and authority; only the
Episode mechanics are shared.

Every Parts Episode performs scoped work directly or delegates a genuinely
smaller contribution to the same Parts specialization. Requirements, source
paths and materialization targets are the currently supported scope dimensions.
A lone requirement with no smaller editable grant is direct work. A prose-only
case subdivision is not a persisted assignment.

Materialization Parts uses the structured plan API. Code Parts uses source tools.
Measure Parts authors/reviews checking components and runs adequacy controls;
only the enclosing Measure publishes the commissioned composite. Verification
Parts executes established checks and returns independent determinations.
All retain their assigned fixed measurement, preservation obligations and
history, and all can call Question or Support.

Parts returns findings to its owner. Cross-specialty needs eventually reach
Designer, which owns coordination across its peer specialists. Parts cannot
change its specialization or invoke a different specialist to enlarge authority.

### 5.3 Code Implementer

Goal: satisfy its frozen implementation measure and preservation conditions.

Input additions: admitted DesignPlan, exact edit scope, local measure, protected
checks, relevant prior patches/outcomes, and unresolved implementation questions.

Choices:

- **Attempt an edit:** propose ChangeSet -> host commits candidate/invalidation ->
  request local evaluation -> host admits observations, computes local progress,
  updates the shared conflict record and returns a unit receipt.
- **Delegate smaller source work:** assign Code Parts with narrowed scope,
  fixed measure and a parent-owned return contract.
- **Resolve an uncertainty or guidance gap:** call Question or Support through
  the available preauthorized observations or explicit review instrument.
- **Assess unchanged candidate:** local evaluation when existing evidence is
  insufficient; this can satisfy the assignment without a patch.

Code Implementer and Code Parts are the target-source coding roles. Neither can
modify its local measure or the parent's acceptance artifacts. Its result names candidate changes, exact local
results, preservation failures/unknowns, supported lessons and a requested parent
decision if needed. It never claims enclosing acceptance.

### 5.4 FindDesignSupport

Goal: fill a named guidance gap relevant to an admitted decision.

Input additions: `need_key`, required topics/interfaces, applicable task conditions,
allowed library catalog/revision, existing guidance and rejection history.

Unit: choose among the preauthorized investigation needs and observations ->
execute the selected existing instrument -> assess the fixed applicability
predicate. Question and Support are available child calls with scoped assignments.
This route does not provide arbitrary library search or retrieval simply because
the helper is reachable.

Output: selected source refs with supported applicability, unmet prerequisites,
conflicting sources, rejected matches/reasons and uncovered needs. Free-text
similarity alone is not sufficient for credit. Retrieved text stays reference data;
only already authorized instruction artifacts can form the pre-start instruction
package. Later retrieval does not rewrite an active system prompt.

### 5.5 ResolveQuestion

Goal: resolve a specified distinction needed for a particular decision.

Input additions: `question_key`, hypothesis refs, decision options affected,
discriminating observations, admissible evidence classes and resolution predicate.

Unit: select an admissible observation -> obtain it through host capabilities ->
compare it with the fixed resolution predicate -> admit a supported answer or
remaining uncertainty. Question and Support are available child calls; target
artifacts remain read-only. Explicit checking-program review uses the separate
review assignment rather than an arbitrary accepted-answer operation.

Output: supported answer, eliminated/remaining alternatives, counterevidence,
applicability and exact effect on the caller's options. Discovering that evidence
is inadequate can justify a decision request; it is not a fabricated answer.

Current native-execution mapping for these two roles (implemented, unexecuted):
the frozen campaign policy may contain `investigation_need_refs`. Each references
an exact committed data record with these fields:

```text
need_key, role (support | question), requirement_key, measure_ref, check_ref,
decision_ref, target_ref, applicability_ref, limitation_refs[],
outcomes: {pass: <declared state>, fail: <declared state>}
```

The check must be an authorized mandatory `execution` check for that requirement,
measure, environment and role purpose. Decision, target, applicability and limit
references resolve to exact committed data supplied under the approved policy.
For a question, the declared states are `supported`, `refuted` or `unresolved`;
for support they are `applicable`, `inapplicable` or `unresolved`. They express
bounded advisory conclusions about the named target, never new capabilities or
enforceable exclusions. An execution failure is not the `fail` predicate outcome.

An assigned child proposes `finding: {observations: [{requirement, observation_path}]}`
using the specification location and observed quantity in its declared investigation
needs. The host resolves the exact authorized checks. This is a selection,
not evidence. The host adds required guards and uses the shared evaluation
service's exact native Target Workflow binding. Source admission and actual Run
evidence precede predicate evaluation. Only then does `investigation.findings`
project the parent's fixed outcome meaning. Missing execution, stale evidence,
contradictions or failing guards cannot produce a resolved finding.

The durable report retains original evidence, candidate/dependency, measure and
environment identities. When the parent requests `investigation_findings`, its
return contains the requirement, decision meaning, applicability, supported state
and limitations. The specialist's declared investigation input supplies the
decision, target and applicability data it needs; audit envelopes are not model
inputs. The active system prompt is unchanged.
Question resolution may be positive or negative. A rejected guidance candidate
does not close the guidance need. Repeated conclusions share semantic credit
history; neither narrative length nor a new child/Run identity is progress.

This path requires pre-admitted needs/checks and the existing native Run instrument.
An independently approved reference workflow may supply original evidence through
§7.1.2; §4.3.1 describes its use for missing measure grounding. This is not an
unconstrained library-query/review capability. In particular, executing an example does not by itself justify a
general applicability claim. The parent-owned check and its declared limits must
ground that claim before the child is assigned.

### 5.6 EstablishMeasure

Goal: own and publish one reusable composite checking function for the
parent's explicit commission.

Input additions: required claim/domain, available grounded oracles, adequacy
criteria/controls, existing instrument candidates and required independence.

Unit: select/instantiate or revise an instrument proposal -> obtain missing
grounding with ResolveQuestion if needed -> run declared adequacy observations ->
host evaluate §4.2 -> admit usable instrument or exact remaining gap.

Measure can perform this work directly or commission Measure Parts for a smaller
requirement subset. Components retain their own adequate cases and control
evidence while the remainder is unfinished. `compose_components=true` composes
admitted returned work without requiring a dummy new check. Measure Parts can
compose scoped contributions; only Measure publishes the complete reusable
function for its commission. Other Episodes reuse their assigned fixed function.
The parent explicitly requests any revision.

Output: the composite's discrimination/limits and outstanding requirement
components, or an applicable instrument-build/grounding request. Measure and
Measure Parts do not edit the target or silently relax original requirements.

### 5.7 VerifyBehavior

Goal: determine what the exact candidate demonstrably satisfies under the parent's
acceptance/composition contract. Refutation is useful evidence too.

Input additions: exact candidate, parent-owned acceptance measure, required scope,
known evidence, independence constraints and unperformed checks.

Unit: select `evaluate: true` for the assigned checks or commission a smaller
Verification Parts scope, Question or Support -> assess the resulting evidence.
The root Designer's Verify uses composition; Verification Parts retains that
exact inherited purpose. There is no target repair or criterion change, and a
fresh model opinion is not an independent behavioral observation.

Output: requirement determinations, evidence domain/limits, failures, unknowns,
unperformed checks and applicability of reused evidence. `all_pass` requires all
mandatory checks under one compatible candidate/measure/environment tuple.

### 5.8 MaterializationImplementer

Goal: realize Designer's approach in the commissioned Materialization Spec.
The structured API admits exact before/after operations within assigned targets;
source is read-only. Materialization Parts handles smaller granted requirements
or targets through the same API. MaterializationImplementer retains consistency
across the assembled plan. Question and Support are available through their
declared observation/review capabilities. Missing source or inadequate checks
return as findings for Designer's coordination rather than new write authority.

## 6. Concrete progress rules for all roles

`ProgressManifest` contains `requirement_keys`, `milestones`, `lesson_admission_ref`,
`equivalence_function_ref`, `attainment_predicate_ref` and
`opportunity_bound_function_ref`. Each milestone contains `milestone_key`,
`origin_requirement_or_need`, `predicate_ref`, `evidence_class`, `guard_keys`,
`applicability_ref` and `predecessor_equivalence_refs`. These bind requirement/need
keys to registered predicates and semantic equivalence rules. The parent supplies task-specific predicates; the
host admits them before the child starts. Milestones describe observable states,
not model-rated quality, line counts or numbers of subtasks.

| Role | Credit-bearing fact, after admission | Zero-credit examples |
| --- | --- | --- |
| Designer | Newly demonstrated whole-scope requirement or composition condition; supported decision-changing knowledge | Approach prose; assigning children; child scores; unverified local passes |
| Specialized Parts | New scoped evidence under its unchanged specialist-family measure; valid verification failures count as determinations | Decomposition alone; renamed scopes; inherited old passes |
| Code Implementer / Code Parts | First attainment of a declared local milestone with required guards on that candidate; complete local acceptance; a separately admitted operative lesson | Patch size; compilation when behavior was required; restoring an old milestone |
| FindDesignSupport | First evidence-backed closure of a named guidance need, or a supported conflict/exclusion that changes its usable choices | More hits; another similar example; a prose relevance claim |
| ResolveQuestion | First supported resolution of a named distinction, including decisive counterevidence, that changes the declared decision state | Confidence; repeated answers; restating a parent hypothesis |
| EstablishMeasure | First independently demonstrated adequacy milestone or usable instrument; a supported counterexample removing an invalid instrument | More assertions; passing its own self-generated expectations |
| VerifyBehavior | First operative determination of a required behavior/evidence class, or a materially stronger declared determination; valid counterexample | Rerunning an unchanged check; favorable verdict without observations |

A semantic key includes the root requirement/need, role judgment, criterion meaning,
relevant conditions and milestone/claim equivalence class. It excludes new Run IDs,
assignment labels, report wording and candidate hashes. Those belong to provenance.
New source bytes alone never make an old achievement new. A genuinely changed
criterion is linked to its predecessor and retains equivalent prior achievements.

Two distinctions matter:

- Passing one check can be a local milestone without satisfying a multi-check
  assignment. The manifest includes a separate same-candidate joint acceptance
  condition; passes from different revisions never establish it.
- A valid failing observation may establish new negative knowledge for a verifier
  or inquiry role. The failed implementation attempt itself still earns zero.
  Any credit must identify the separate admitted determination/lesson transition.

A lesson must have committed evidence, a structured scoped claim, canonical action
equivalence, a named decision it changes, applicable conditions, and reopening
conditions. The host derives the actual advisory/policy effect. The lesson is
retrievable before later matching selections. Unused commentary, paraphrases,
uninformative failures and irrelevant distinctions do not qualify. Enforceable
exclusion needs the stronger frozen authority; no global promotion is implied.

Credit is awarded at most once per semantic fact for the same judgment lineage
through replacement assignments and recovery. Different parents judge their own
contribution predicates rather than summing or copying child scores. All projections
retain the original evidence IDs; more reports do not create corroboration.

Current implementation mapping (unexecuted): a returned direct verifier's original
observations can produce a `parent_assessment` at the parent's ordinary unit close.
It names the parent assignment/check, candidate/dependency hashes, original report
and observation references, and the host-derived outcome. The parent predicate
is evaluated separately; runtime evidence is reusable only when its instrument,
inputs, environment and extraction context match the parent's authorized measure.
Static evidence must retain the exact native check. An assessment is not another
Run observation or independent corroboration. Parent receipts, reports and scoped
context preserve `assessment_refs`; old v1 records may omit that additive field
without changing their identities. Publication re-derives assessments before
credit. More general instruments and support/question judgments remain
implementation work, not satisfied by this projection alone.

The verifier's own progress projection now admits decisive `pass` and `fail`
observations under its assigned acceptance/composition measure. These are
determination facts, not repair milestones. Each key retains the criterion,
evidence kind, environment, dependencies/extraction and instrument/input context,
plus the outcome. Run IDs, source revisions and alternative wrong values do not
create fresh keys. A newly named invocation shares its measure's judgment history.
The same host projection is re-derived at publication and used by numerical
control. It excludes stale/contradicted evidence and unresolved guards; acquisition
errors are not counterexamples. Native baseline pass/fail determinations from the
Builder handoff are excluded from new verification progress.

A verifier can establish a check's result while other checks remain unperformed;
that is not whole-requirement acceptance. The three repairing roles retain their
passing-guard and all-native-check rules. A failing verification result can end
the verifier's inquiry while leaving the parent's repair goal unmet. This mapping
is implemented but unexecuted; it is not a test or transport receipt.

### 6.1 Numerical contract version 1

Use existing numeric domains: exact integer counts/identities for admitted progress
and the existing finite-float NumericBand/incidence/hypervolume types for control.
Do not introduce floating-point approximations into hashes or evidence predicates.

For an admitted delta, let `K` be newly earned semantic fact keys not previously
credited in that judgment lineage. The deterministic registered refiner yield
function returns `realized_yield = len(K)`, their transition/evidence refs, and
cumulative historical counts before/after. Every key must reference a committed
operative state change satisfying the role's predicate. No delta means zero.

Keep typed requirement/guard/evidence states separate; the count is not a universal
quality score. A loss of correctness immediately changes operative state and
eligibility even when cumulative historical credit cannot decrease. Known-invalid
facts are not active learning, and regaining the same milestone earns zero.

The continuation controller uses:

1. One existing ResultColumnSchema position for host-admitted progress identities.
   This avoids making an optional empty result dimension veto all progress. The
   structured distinctions above remain available for admission and reporting.
2. Existing MarginalHypervolumeAssignment; baseline imported facts use EXCLUDED
   admission, not new observations. Completed semantic units supply their active
   admitted fact identities; failed evidence acquisition with no usable observation
   uses FAILED with no new identities. A valid negative observation is OBSERVED,
   not a successful repair. Rejected representations are not incidence samples;
   substantive rejected/empty results remain zero-yield observations as appropriate.
3. Existing paired_incidence with `uncertainty_alpha = 0.05`, wrapped by a new
   registered goal-aware numeric adapter described below.
4. Existing predicted_credit_upper_bound with
   `max_predicted_marginal_hypervolume = 0.01`. These match the generic reasoning
   reference defaults; no more permissive acceptance-only substitution is allowed.

The host-derived numeric adapter additionally receives an exact remaining-
opportunity upper bound or `null` (unknown). It is zero when the assignment's
required goal is established with no required open work, or a finite declared
opportunity set is demonstrably exhausted. It is **not** zero merely because the
model ran out of ideas or the current action list is temporarily unavailable.

With a zero bound the adapter returns exact total bands equal to historical
accepted counts and exact zero next-yield bands. Otherwise it delegates to
paired_incidence; v1 need not estimate a finite nonzero bound. The boundary is
numeric, not free text or requirement names. This permits already-correct work to
return without invented iterations while keeping the registered numerical rule
as the normal stop controller. Host admission must prove the zero-bound predicate.

Unavailable bands remain unavailable; they do not imply completion. Repeated
zero-yield units affect the estimator, not a hidden fixed failure/turn limit.
Missing authority/capability and parent-decision returns use §10, not a counterfeit
zero projected yield. Rarefaction is an estimate with the existing method's stated
uncertainty limitations, not a proof that no solution exists.

The refiner's registered composer records the before/after numeric inputs and
the exact selected components. Do not change the ordinary controller defaults or
reinterpret generic reasoning receipts. Calibration changes require a successor
approved contract; the initial settings are specified, not empirically validated.

## 7. Observations, reports and context

### 7.1 Evaluation records

```text
EvaluationRequest = {
  candidate_ref, measure_ref, check_keys[], input_refs[], environment_ref,
  harness_ref, purpose, parent_operation_id, capability_ref
}
EvaluationObservation = {
  request_ref, execution_ref, checked_dependency_hashes,
  observed_value_ref, outcome: pass|fail|inconclusive|error|blocked|not_run,
  evidence_refs[], counterexample_refs[], limitation_refs[]
}
```

Host interpretation, not a worker-supplied outcome, establishes the authoritative
verdict. `error`/`not_run` are not passes or decisive counterexamples. Evidence
reuse needs the admitted dependency/applicability rule. Unknown change impact
invalidates the evidence for current readiness; it does not erase history.

Implementation mapping after PR #31: each check explicitly declares
`evidence_kind: materialization|execution`. Materialization checks use the
Builder's registered definitions and stable requirement/check IDs, with
candidate-derived source and committed BuildReceipt evidence. Runtime checks
retain separately bound Run evidence. Both kinds share evaluation requests,
observation storage, regression history and parent reports; neither can satisfy
the other's evidence contract. `blocked` means an unavailable prerequisite, not
a pass or decisive counterexample. A static-only request does not execute code.

The preparation proposal includes local, acceptance and composition static checks
under the supplied measures before campaign admission. Host policy must explicitly
include `observe_materialization`. Static achievement requires every declared
check for a requirement; credit is per requirement, excludes the initial satisfied
baseline and cannot be earned again by restoring a previous pass. Behavioral
coverage is still judged independently and is not discharged by materialization.

The current shared evaluation route records an optional v1 `availability` value:
`{executable, gaps: [{kind, detail, requirement_keys, check_keys}]}`. It is derived
from the exact assigned measure and authorized checks/instrument bindings, then
re-derived at request admission. Missing coverage, uninstalled checks, unavailable guards, mismatched
environment, missing/ambiguous bindings and unsupported execution/input routes
are distinct. An absent binding has null harness/capability refs and no inputs;
it cannot bind source or a Run. Older records remain readable without this field.

When a measure has incomplete coverage or one unavailable input context, other
executable contexts may run. The unit still returns an original unresolved request
as `needs_parent_decision`, and the parent report retains all outstanding requests
from that unit; this does not count as normal completion or substitute
for a decisive observation. Publication verifies the exact decision reference.
The parent's requested `open_decisions` section supplies gap kind, meaning and
affected requirement locations. The original request remains in the audit record.
Host-derived
availability gives Designer and the relevant specialist the observed gaps
when selecting their next action. Resolving that prerequisite
does not permit mutation of the active assignment's criteria. General instrument
execution remains unfinished; this handling does not create another runner.

Native validation inputs (implemented, unexecuted): `input_refs` is empty for the
existing empty-payload route, or contains one content-hashed reference to an
existing `DuetLaunchRequest.as_record()` stored as committed campaign data. That
record retains the ordinary closed fields:

```text
request_id, workflow_id, goal_id,
artifact_ids_by_role, measurements, states, flags
```

The workflow and goal must match the campaign's approved target root. The host
validates payload types using `DuetLaunchRequest` and validates vocabulary and
required fields using the root's `HandoffPayloadContract`. It generates a fresh
request ID for the actual Run; it does not replace the input values or take launch
addresses from worker prose. More than one input reference **within one binding** is an explicit gap,
not a request to silently select one case or merge incompatible launch requests.
Empty input is also checked against required fields before runtime evaluation.
Separate cases use separate authorized bindings and check identities. The host
groups checks by their exact binding; it does not let the worker choose inputs
after seeing a preferred result. Investigation selections retain a full
`selection_check_keys` set while each request names its own context's checks, so
cross-context guards remain visible at admission.

`evaluation_inputs` is used by availability, grounded-measure admission and the
ordinary registration path. When committing the Run binding, the host re-derives
the expected launch from the evaluation's exact authorized input reference and
checks it against the registration, using the actual BuildStore root interface.
This closes the path where another correctly admitted candidate Run with different
inputs could be substituted. Malformed, wrong-target or incompatible inputs
produce a typed `launch_input_invalid` availability gap, not a behavioral verdict.
Static-only evaluation does not require an executable root interface.

Credit identities and regression comparisons use the typed input values, excluding
the template's request/artifact identity. Repackaging the same launch is not new
learning or a changed experimental condition. This is an in-memory comparison
projection; admission still requires the exact authorized reference. Empty input
keeps its prior fact identities, including an explicit all-empty template. An
unsupported input remains reference-distinct and unavailable; comparison does not
guess equivalence or throw away the original parent-decision context.

Artifact IDs retain the existing target-runtime semantics: this adapter neither
loads their bodies into prompts nor grants the target access to campaign storage.
Targets needing rich artifact contents must already have an authorized way to
consume them. Native multi-case execution and the already-approved checking route
below, including the construction-to-adequacy return, are implemented but
unexecuted; the independent grounding route is described in §4.3.1. No new runner, payload transport,
database schema, replay mechanism or normal-build hook is introduced here.

Repair progress for context-bound checks distinguishes genuinely different inputs
without rewarding request-ID changes. Succession still maps equivalent prior
facts rather than resetting history. For A/B detection, explicit case bindings
allow checks from different inputs to form one requirement vector: repairing one
case while breaking another is visible. Legacy checks lacking an explicit binding
retain their original same-context comparison. Final acceptance still requires
all mandatory cases and guards on compatible current evidence.

### 7.1.1 Separately approved checking workflow (integration verification in progress)

A frozen native instrument may additionally name `checker_ref`. This reference
designates committed data with this closed shape:

```text
workflow_ref, build_receipt_ref, authority_approval_ref, launch_ref,
entry_local_id, entry_context: "declared_goal_initial_state",
result_inputs: [{field, key, result_path}]
```

The referenced workflow is a separately approved build, not the target itself.
`launch_ref` is the existing complete `DuetLaunchRequest` envelope for that
workflow, retaining its closed-empty root payload. `entry_local_id` selects an
already-approved non-root Episode that accepts the mapped result. Each mapping
names one destination in that child's `artifact_ids_by_role`,
`measurements`, `states` or `flags`. `result_path` is a JSON pointer relative to
the candidate Run's committed typed status; for example,
`/workflow_result/measurements/makespan`. Mappings cannot collide or overwrite a
constant input in the frozen template. Values remain typed data, not instructions.
The checker receives no new artifact-body access or refiner host authority.

The shared evaluator admits and runs the candidate through the existing executor.
After actual success, it loads the independently approved checker build and
projects the declared result fields into the selected child's typed input
contract. It registers and runs that child/subtree through the same executor with
its own identity, capabilities, HTTP policy and audit. The existing Run scope
records `fresh_typed_entry`: new context derived from frozen goal declarations
and initial state, not a recorded parent decision or an interrupted-state
restoration. The root initializer and scoper execute; ancestor Episodes and their
controllers do not. A binding is admitted before either Run starts.
No specialist spawns another Designer or constructs an unchecked runtime topology.

The common experiment service records the checker as a declared measurement
dependency of the target experiment. Shared execution history links both Runs
without assigning the target's verdict to the checker implementation. Definitions
that only provide root mappings fail preview with instructions to declare a typed
child entry. They never widen the root launch contract. See the
[shared harness guide](unified_episode_test_harness_design.md#supplying-a-new-typed-input-to-a-checker)
for scope limits and the [receipts](unified_episode_test_harness_receipts.md) for
what has actually been verified.

For the checker stage, the existing immutable `evaluation_run` adds both
`target_run_ref` and `target_execution_ref`. Its `build_receipt_ref` continues to
identify the candidate's source admission; the checker source is identified by
the frozen descriptor and its registration. The request's active Run index moves
from target to checker once, retaining the original target record. Admission
independently verifies the checker registration, original successful target
evidence, and exact projected launch payload. Native records without these fields
retain their original shape and identity.

The frozen check's `observation_path` selects the checker terminal result. A
successful candidate Run cannot bypass this stage or supply a checker verdict.
Target failure produces an execution error without invoking the checker; checker
failure is also an error. Only the registered predicate over the committed checker
result can establish the stated check. Final publication preserves evidence and
bindings for both Runs without rerunning either check.

This connection accepts an instrument already authorized in the campaign's frozen
measurement policy. Approval/source identity alone does not establish that its
verdicts mean what the task requires. In particular, testing the final scalar
predicate on supplied positive/negative values does not test the checker itself.
`EstablishMeasure` therefore requires the independently grounded executable-control
route in §4.5; predicate-only controls cannot admit a checker-backed measure.
The checker construction-to-admission return is wired through those same controls;
authorized missing-grounding acquisition uses §4.3.1. These connections remain
unexecuted and do not establish generic reasoning/repair acceptance.

Malformed checker definitions are unavailable at request resolution. After the
target runs, the same shared preparation function is used by the evaluation
service and host admission. It validates original target evidence, then either
resolves the approved checker launch or returns one of these typed gaps:
`checker_source_unavailable`, `checker_source_invalid`, `checker_input_invalid`.
Unexpected errors and corrupt target evidence are not manufactured observations.

For a gap, an immutable successor `evaluation_run` retains the original target
registration and adds a closed `checking_gap` containing `kind`, `detail`,
`target_run_ref` and `target_execution_ref`. It does **not** carry top-level
checker-stage fields or claim that a checker Run exists. The existing admission
operation reconstructs the cause and verifies the exact target identity before
updating the request's existing index to unavailable. An unavailable request
cannot supply an observation or be overwritten as executed; later authorized
evaluation is a distinct request with the original history preserved.

These records enter the same decision selection used by unit closure and its
independent publication validation. The child returns `needs_parent_decision`,
and the parent gets the requested outstanding gaps, including when another case
successfully executes. Its `open_decisions` return contains the cause and affected
requirements; exact checks, candidate identities, evidence and the complete Run
registration stay in the durable record. Missing checker authority cannot be repaired by changing an
active contract, nor can input incompatibility be turned into a passing check.
This remains unexecuted code, not proof of the complete instrument-building loop.

### 7.1.2 Independently approved evidence source (implemented, unexecuted)

Question/support observations may use this exact instrument:

```text
{execution_kind: "reference_workflow", reference_ref: <source descriptor>}

source descriptor:
workflow_ref, build_receipt_ref, authority_approval_ref, launch_ref,
request_payload_contract_ref
```

The provider must already be independently approved and materialized. It cannot
be the Target Workflow or any editable checker workflow in this campaign. Its
actual BuildStore receipt, approval and root input contract must match the copied
references. Source projection uses those original modules without candidate
substitution or compilation of candidate bytes. The provider receives no editing,
learning or refiner-session authority.

Execution goes through `RefinementEvaluations` and the same Run registration,
executor and audit boundary. It uses the descriptor's launch template unless the
frozen evaluation binding supplies one complete authorized input. The source is
not a target acceptance instrument: only question/support assignments may select
this execution kind, with declared execution checks. Source admissions shown to
an assignment are scoped to its own measure; a reference-source success cannot
hide a rejected candidate build.

Original terminal evidence enters the same observation and typed parent-report
path. For measure acquisition, §4.3.1 additionally binds that evidence to the exact
provider and case template. Final build publication reconstructs these acquired
observations, confirms their successful Run, registration, audit value and approved
source, and retains their Run/binding references with the measure admission. It
does not rerun the source or count publication as new progress.

### 7.2 LocalContext

```text
assignment_ref, invocation_id, current_candidate_ref, selected_candidate_ref,
pending_stage_ref | null, local_measure_ref, current_check_state_ref,
eligible_action_records[], relevant_attempt_refs[], applicable_lesson_refs[],
regression_refs[], decision_request_refs[], dependency_delta_refs[],
history_cursor, complete_index_ref
```

The host derives eligibility. An action record contains `action_class`, typed
input contract, prerequisite refs and any advisory retry justification required.
Retrieval uses typed requirement/scope/action/environment keys. Bounded display
does not hide an applicable exclusion or conflict from authoritative selection.

### 7.3 UnitReceipt and parent reports

```text
UnitReceipt = {
  assignment_ref, invocation_id, logical_unit_id, stage_receipt_refs[],
  candidate_before_ref, candidate_after_ref, admitted_delta_ref,
  evaluation_refs[], invalidated_check_keys[], conflict_refs[],
  lesson_refs[], measurement_ref, continuation_ref,
  disposition, decision_request_ref | null
}
ParentReport = {
  request_ref, assignment_ref, invocation_id, role, scope_requirement_keys[],
  selected_candidate_ref, examined_candidate_refs[], measure_refs[],
  determinations[], changed_dependency_refs[], preservation_findings[],
  relevant_attempt_refs[], lesson_refs[], unresolved_requirement_keys[],
  decision_request_ref | null, continuation_ref, termination,
  evidence_refs[], complete_index_ref, return_value
}
```

`determinations` and the other audit fields retain requirement/check keys, exact
candidate/measure/environment identities, verdicts and original observation
references. Numerical credit and independent judgment continue to consume that
evidence. `return_value` is the separate model-facing projection requested by this
child's parent before dispatch:

```json
{
  "decision": "Does this repair warrant independent acceptance?",
  "measurements": [
    {
      "name": "Local repair outcomes",
      "purpose": "local",
      "requirements": ["/episodes/example/parts/node_plan"]
    }
  ],
  "include": ["candidate_changes", "open_decisions"]
}
```

The requirement locations identify real specification parts or contract fields;
they are not aliases for artifact hashes. Each named measurement groups outcomes
by requirement and preserves recorded versus currently applicable statuses,
unmeasured requirements, scalar observations, limitations, counterexamples and
comparable changes since assignment. A local result and an independent acceptance
result remain different measurements. Structured execution evidence stays stored;
it is not expanded into a parent report merely because it exists.

The parent selects any needed sections: `candidate_changes`,
`investigation_findings`, `measurement_findings`, `check_review`, and
`open_decisions`. These provide changed paths, decision findings, measurement
admission/control results, review reasoning, and actionable blockers respectively.
The parent report supplies only its declared measurements and sections. It does
not append child histories, full admissions, source packages or provenance hashes.

Every child path declares its own `return_contract`. Designer chooses the
information needed from each selected specialist. Each specialist and Parts
owner does the same for its scoped children; helper-to-helper calls also declare
a return. There is no second implicit verification return attached to a source
assignment. Measure's Question review for a proposed checking program requests
check-review criteria, counterexamples, limitations and open decisions.
Duet's root return requests whole-workflow composition acceptance, changes and
outstanding decisions. These declarations exist before each call.

`MODEL_INPUT_COMPONENTS` in that same Episode contract module declares working
inputs for each role. `model_inputs.py` delivers current scoped code/design when
needed, measurements, and the last operation's actionable feedback. It does not
retrieve a list of stored child reports for the parent. The fixed system
instructions remain stable across calls.

The shared `method_loop.ReportContract` names the parent's next decision,
measurement meanings, and required information fields before child launch.
Every invocation by an active parent requires it; an isolated selected-Episode
check has no executing ancestor to report to. `ChildEpisodeUnit` separately invokes
the credit projection and mandatory `synthesize_report` callback. The method
admits the returned information as a `ParentReport`, checking its exact declared
fields and rejecting the known correlation/artifact identities carried by the
child request and result. Rejected identities are not masked or shortened.
Domain-specific findings and measurement interpretation remain binding functions.

The method collects these returns even when a compound acquisition unit executes
several children. The refiner binding selects the latest return per role and
requirement scope and calls `Context.model_inputs(..., reports=selected_reports)`.
That boundary accepts only report objects admitted for this parent, owns the
`child_reports` input field, and also checks the declared inputs against known
child audit identities. Audit records and numerical controller inputs remain
separate from this model-facing synthesis. Shape/identity checks establish these
mechanical boundaries; semantic adequacy still requires live verification.

Builder admission checks the actual `ChildEpisodeUnit` constructor, including its
required synthesis callback. Each concrete slot declares a `component.report_S`
function; an approved repeatable call declares `synthesize_report` explicitly.
The root has no upward reporting obligation and retains the same requirements
for each child it invokes.

`report_contract.py` implements the declared projections; `report_overview` reads
the stored `return_value` only. Old return-contract shapes and past continuations
are not migrated or accepted through a compatibility projection. The eight-module
refiner has passed fresh materialization with these interfaces. Fresh nested
execution demonstrated distinct parent requests, their corresponding returns,
and subsequent parent decisions. See `episode_communication.md` for the exact
events, verification boundary, and remaining target-workflow limitations.

The user-facing MINI review is a projection of this data: requirement/target,
finding, current status, latest exact evidence and required decision. It does not
become another independently editable source of truth.

## 8. Stages, child calls and approved recursion

### 8.1 Executable stage contract

Use an opt-in declared staged-unit adapter around existing Episode/ChildEpisodeUnit
execution. Its definition is a finite acyclic stage graph fixed in the refiner
binding. It is not an arbitrary model-authored workflow language.

```text
StageBinding = {
  stage_id, kind: host_operation|child_call|projection,
  function_ref, child_slot | null, input_schema_ref, result_schema_ref,
  successor_by_outcome, admission_ref
}
PendingStage = {
  logical_unit_id, graph_definition_ref, stage_id, input_ref,
  operation_id, child_invocation_id | null, receipt_ref | null
}
```

Selection chooses among declared paths; host admission rejects out-of-order
requests. The child slot, operation and successors cannot change mid-unit. A child
return enters a pure typed projection, then the **explicit next stage** performs
any required action. A result projector must not launch children or validation.

Stages have durable receipts before advancing. A unit is credited and observed
once, at its admitted close. Child controllers run their own loops normally.
Interruption can leave a pending stage; it cannot fabricate a closed unit. A
supported parent-decision return may close an incomplete unit with its actual
admitted progress, never credit for the interruption itself.

No stage back-edge is allowed. Another substantive attempt requires another
Episode unit, with admission and numerical control. Representation-only repair
keeps the same operation/unit and follows existing audited repair semantics;
valid repaired content receives ordinary admission. Changed substantive claims
require a new attempt and cannot replace old evidence.

### 8.2 Recursion in a fixed approved graph

Keep the existing concrete Target Workflow and its frozen topology unchanged.
Extend the workflow contract with a **versioned, explicitly approved repeatable
call binding**, rather than making a model mutate parent pointers at runtime.

```text
RepeatableCallBinding = {
  caller_local_id, slot_name, callee_template_local_id,
  prepare_request_ref, receive_result_ref, request_schema_ref,
  invocation_admission_ref, authority_attenuation_ref
}
```

Existing nodes form the finite declared implementation/template tree. A binding
can invoke an exact node/template through its declared slot. Each specialized
Parts binding can recurse to its same concrete template. Every role, including
Question and Support, declares both helper calls, so helper recursion also uses
ordinary approved repeatable bindings. Actual invocations have distinct paths
and controllers, not new workflow designs.

Admission requires the correct caller and declared edge, inherited preservation,
history and unchanged measurement, and no added authority. A Parts child narrows
the supported requirement/path/materialization-target scope; prose-only case
slices are not supported. Equivalent active work and concealed dependency cycles
do not become progress merely through a new invocation identity.
The selected subset is task input under the approved admission predicate, not
permission to change a template, stage graph or numerical component.

This is a genuine approval/materialization/linker extension. The existing
EpisodeWorkflowSpec parent tree and materialization edge checks cannot simply be
bypassed. Versioned call bindings must participate in exact artifact approval,
plan/source identity and runtime child validation. Without such approval recursion
is unavailable; a model request cannot authorize it. Ordinary workflows omit the
extension and retain their existing behavior.

## 9. Cross-level repair cycles

### 9.1 ChangeImpact and Conflict records

```text
ChangeImpact = {
  change_set_ref, candidate_before_ref, candidate_after_ref,
  owning_assignment_ref, requirement_keys[], dependency_refs[],
  invalidated_check_keys[], reused_observation_refs[], new_observation_refs[]
}
Conflict = {
  requirement_keys[], observation_refs[], transition_refs[],
  kind: exact_revisit|opposing_regression|dependency_conflict,
  scope_owner_invocation_id, involved_assignment_refs[],
  applicability_ref, state: suspected|decision_required|resolved|reopened,
  resolution_ref | null
}
```

After each edit, mark affected checks stale immediately. After its measurements,
compare current outcomes to prior compatible outcomes across the campaign, not
just the current child. An unmeasured change can raise an impact warning but does
not falsely establish a pass/fail cycle.

An exact revisit uses canonical source/materialization content, criterion meaning
and environment/dependency hashes, excluding changing provenance labels. Reuse of
an old candidate with new independent evidence is not automatically futile.

Opposing regression detection requires actual comparable observations: a transition
that establishes B while losing A, and a later one that reestablishes A while losing
B, under unchanged criterion meanings/applicability. Source bytes need not match.
The host records the pattern and affected requirements. A coarse similar status
vector alone is only `suspected`, not an enforceable exclusion.

### 9.2 Eligibility and escalation

1. Record candidate effects and invalidate stale checks before any credit/readiness
   decision. Apply declared guard rules; unsafe local regressions cannot count as
   successful implementation milestones.
2. An observed cross-assignment opposing regression or conflict outside the active
   assignment's scope becomes `decision_required`. Block further ordinary repairs
   for those involved assignments at the next safe unit boundary.
3. Identify the coordinating ancestor whose requirement scope and granted
   operations cover the repair. Within a specialty this can be its owner;
   cross-specialty coordination belongs to Designer. If no approved scope
   covers the change, the root reports the specification/authority gap.
4. A host-authenticated decision-return receipt unwinds the active child stages to
   that owner. Each intermediate parent persists its pending stage and forwards the
   typed incident, without inventing an alternative Designer or continuing coding.
5. The owner can admit a joint assignment, correct an evidenced boundary/measure
   defect, justify reopening under materially different conditions, or expose an
   unresolved spec conflict. Decisions reference the incident and observations.

For a joint assignment, close/supersede the old assignments, retain their evidence
and semantic credit history, and require A **and** B on one candidate with the
original surrounding guards. Naming it “joint” without expanded coupled acceptance
does not discharge the incident. The conflict resolves only when relevant evidence
establishes its resolution or approved changed premises reopen the route.

This is an authority/coordination return, not a semantic retry budget or a proof
that a solution is impossible. A genuinely distinct, justified experiment remains
possible through the owner; merely changing identifiers does not reopen work.

### 9.3 Worked record sequence (design example, not an executed test)

| Candidate | A | B | Host consequence |
| --- | --- | --- | --- |
| c0 | pass | fail | Baseline evidence; B is open |
| c1 after B repair | fail | pass | A regression recorded; local guard blocks a successful repair claim |
| c2 after A repair | pass | fail | Comparable opposing regressions; return to coordinating owner |
| c3 after joint repair | pass | pass | Joint acceptance is new; restoration of A alone is not |

If c2 has not rechecked B, its state is `stale/unknown`, not `fail`, and no observed
opposing-cycle claim is made yet. If c3 combines A's c2 pass with B's c1 pass, joint
acceptance fails identity/applicability checks. A new child or worker Run between
rows does not reset the sequence.

## 10. Return, readiness and interruption

Keep three axes: transport/Run termination, numerical Episode return, and task
attainment. A numerically exhausted search may finish its loop without solving
the task. A child seeking a parent decision does not terminate the whole campaign.

| Disposition | Required basis | Parent/root treatment |
| --- | --- | --- |
| continuing | Eligible next work and numerical continuation true | Next declared unit |
| attained | Required predicates established; no required open work; numerical rule returns | Parent independently assesses its contribution; root may issue VerifiedBuild |
| yield_exhausted_unresolved | Numerical rule returns with unmet requirements | Return candidate and unresolved frontier; never ready |
| needs_parent_decision | Host-admitted conflict/scope/measure decision request | Typed incomplete child return to owning ancestor |
| blocked | Verified missing capability, oracle, authority or indispensable evidence with no permitted local resolution | Preserve frontier; parent may solve the prerequisite; root remains unresolved |
| invalid | Frozen component/contract cannot resolve or an integrity check fails | Preserve evidence; no further execution under that invalid contract |
| interrupted / resource_limited / cancelled | Observed external stop | Preserve pending stages and state; never attained |

`DecisionRequest` contains `reason_code`, affected requirements, supporting
observations/denial receipt, required scope, owning parent, available resolution
kinds and pending stage. The model may propose one but cannot set its authority.

Precedence is explicit: observed external termination or contract/integrity failure
prevents normal return; an admitted parent-decision need takes precedence over a
numerical return; a verified unresolved capability/authority gap is blocked;
otherwise apply the registered numerical decision. Preserve that decision even
when a different structural disposition takes precedence. The new refiner adapter's
normal `stop` is true only for `attained` or `yield_exhausted_unresolved` with a
matching numerical return; it is false for a typed incomplete return. Do not modify
generic reasoning's existing HostReceipt contract to implement this distinction.

The refiner adapter must support a typed incomplete source return in method_loop;
today SourceEnd admits only `source_failed`. Do not encode all these reasons as
normal `stop=True`, `None` source exhaustion, or a forged “completed” host receipt.
Map actual Run terminal states separately and retain the typed disposition.

`attained` refers to the role's assigned goal. A verifier can attain a conclusive
negative determination; a question resolver can disprove an approach. Neither
means the target passed. The parent consumes the actual typed determination, and
only root target acceptance can establish VerifiedBuild.

`VerifiedBuild` binds target approval, exact admitted BuildManifest, materialization,
full mandatory requirement catalog, compatible acceptance/composition observations,
environment/dependency scope and root return receipt. All requirements, not merely
the displayed report subset, participate. Remaining ambiguity, stale evidence,
open mandatory checks or unresolved conflicts forbid it. Statistical/reviewer
limits remain explicit; “verified” does not mean unbounded correctness.

VerifiedBuild is not permission to execute production tasks, publish code or approve
a changed Architecture. Already-correct input yields the original source identity
with new/reused assessment evidence, not a synthetic repaired revision.

Current explicit-entry return (unexecuted): `execute_refinement` returns
`RefinementRunResult`, a read-only host projection containing the original
`RunEvidence`, campaign reference, root report, selected candidate, original typed
decision records and that candidate's admitted-source references. The Episode's
existing report-ID/disposition transport handoff remains unchanged. Durable parent
reports retain `child_report_refs` for direct-child evidence and require the
contracted `return_value` described in §7.3. Model-input delivery reads that return;
it does not follow the audit links to expand stored child artifacts.

Both `succeeded` and `blocked` refiner terminal frames must agree with the exact
published host root report and root Episode identity. `attained` maps to Run
success; numerical exhaustion with unresolved work and an admitted parent-decision
return map to Run `blocked`, retaining their distinct Episode dispositions.
An arbitrary worker-authored block cannot substitute for a host decision. External
termination retains its actual status and cannot become attainment; if projected,
its campaign report is only the last-known state (`has_terminal_report: false`).

Decision records are original returned evidence, not an automatically approved
successor plan or a declaration that every historical rejection remains pending.
The caller uses the root's unresolved scope and linked evidence for its next
decision. The explicit entry now finishes this projection with the host-owned
verification step below; the projection alone does not start a new campaign.
The existing Duet successor service requires genuine human notes
and a human-started cycle; this path does not forge those inputs or call that
service automatically. Normal-build activation remains a later goal.

Implemented finalization (unexecuted): `readiness.root_readiness` reads the full
mandatory requirement catalog, authorized root composition checks and their
transitive guards. It requires current passing independent verifier observations,
returned children and an admitted source receipt for the exact selected candidate.
This projection now participates in root attainment and appears in root context,
so it is not merely a new check applied after an otherwise successful return.
Confirmed unresolved conflicts forbid readiness. Exact-revisit warnings remain
warnings; a suspected local regression needs simultaneous current passing checks.
Those historical warnings remain explicit references rather than disappearing.

`finalization.finalize_result` first checks the actual refiner RunStore evidence and
published root report. It confirms the attained root unit and numerical return,
then verifies the source package named by that candidate's host-admitted source
receipt under original target authority. That source admission already bound the
candidate-derived modules and plan. It re-reads the original observation attempts
and their BuildStore/RunStore evidence, checking immutable receipts, bindings and
the original Run observation values. It does not rerun predicates or static checks:
judgment remains in the shared evaluation/admission path, not a second final checker.
It does not run another Episode or construct another testing path.
Cross-store reads occur outside the Duet writer transaction; publication checks
the unchanged campaign commit, candidate, readiness and current target authority.

The host commits a `verified_build` record through the existing artifact store and
an existing Duet audit event. It binds the exact admitted manifest and materialized
specification, candidate/source receipt, complete mandatory requirement/check set,
observations, measure/grounding/limitation references, validation Run evidence,
environment, root receipt/report and refiner Run evidence. Declared dependency-
compatible observations can be reused; their original candidate/request references
remain intact. Repeated publication of the same record does not add another event
or credit. No worker operation can request this artifact directly.

`RefinementRunResult` adds `verified_build`, `verification_gaps` and `build_status:
verified|unresolved`. Run termination and Episode disposition remain separate.
An incomplete/external return carries the candidate and typed gaps, never a verified
artifact. Source/evidence inconsistencies fail publication rather than becoming
success. Verification means the stated checks under their stated inputs and limits,
not unbounded correctness or new execution authority. This adds one immutable
record kind, no table/index, runner, normal-builder hook or successor approval.

### Review evidence for the existing human successor path

The explicit entry now attaches a host-published `review_handoff` to its result
(implemented, not executed). It binds the original approved baseline, exact
candidate/root report, actual refiner Run evidence, original decision and source
references, verification status/gaps and complete campaign-history cursor. External
stops retain `has_terminal_report: false`; archiving their last-known state cannot
turn them into completed refinement. This artifact adds no credit or authority.

An explicit human-initiated call to the existing `IterativeEpisodeRefiner.request`
may supply `review_handoff_id` alongside its normal `baseline_id`, proposed
`candidate_workflow_architecture`, real `human_note_ids` and exact
`implementation_directives`. The proposal service validates the handoff's original
baseline/build, current campaign candidate and root report before recording the
proposal, and checks again before beginning the human-requested cycle. The review
is supporting evidence, never a substitute for notes, a replacement Architecture,
an approval or successor execution. `execute_refinement` does not call `request`.

`RefinementProposal` includes the optional link in its immutable identity only
when supplied. Old proposals retain their original record shape and hashes; an
explicit null link is rejected rather than creating a second serialization of the
same proposal. Downstream approvals bind the existing exact proposal/decision
chain. No CLI, automatic successor generator or normal-build hook is added here.

## 11. Host capability contract

Every operation binds campaign, assignment, invocation, runtime Episode/Run,
logical unit/stage, expected state version, operation ID, payload hash and actual
producer event. The host derives the caller from the registered Run/path; supplied
role/scope labels are not authorization. The dispatcher is a closed table.

The host also tracks the active invocation stack and issues a scoped invocation
handle on admitted entry. An Episode ID naming some other legitimate node is not
enough. Requests must match the active handle, parent-call receipt, permitted
stage and next operation; suspended ancestors cannot issue editing/selection
operations while a child owns that scope. Host-derived progress projections can
still update those ancestors. Candidate evaluation Runs hold no such handle.

| Operation | Caller | Result and authority check |
| --- | --- | --- |
| get_context | Any admitted role | Scoped §7.2 projection, eligibility and pending receipts |
| read_reference | Any admitted role | Authorized typed artifact/projection with hash and lineage; no arbitrary host path |
| select_action | Any admitted role | Permitted action/stage or host denial with reason/evidence |
| propose_assignment | Designer for peer specialists; each specialist for its own Parts; every role for Question/Support | Host-admitted exact child request or deficits; §5/§8 edge restrictions |
| enter_child | Registered staged adapter for an admitted caller/slot | Validate child assignment and pending stage; persist invocation/path and scoped handle; suspend caller selection |
| return_child | Registered staged adapter at that invocation boundary | Verify committed child return/disposition, derive projection and resume the recorded parent stage or propagate its decision return |
| submit_record | Any admitted role, only its allowed proposal schemas | Validated design/guidance/answer/measure/lesson proposal; admission is separate from model authorship |
| apply_change | Code Implementer/Code Parts for source; MaterializationImplementer/Materialization Parts for plans | Candidate CAS commit plus invalidations, or explicit rejection |
| request_evaluation | Roles with that stage/capability | Durable evaluation handle; no arbitrary shell/network/process capability |
| read_evaluation | Requester/authorized owner | Pending status or committed result bound to candidate/measure |
| close_unit | Any admitted role | Host re-derives delta, facts, yield, continuation, conflict return and receipt |

Campaign creation, broader approval, terminal finalization and normal-build
activation are host lifecycle operations, not worker requests. A typed promotion
or semantic-change proposal remains data for the Duet.

All executable checks/harnesses are admitted artifacts executed through existing
confinement. Never run model-provided Python in the host because it is called a
test. Host parsing/hashing/registered deterministic predicates remain host work.
A target sub-Episode needs a separately admitted harness and typed input; the
parent's ability to name it does not make it independently runnable.

Evaluation Runs have distinct registrations and audit identities linked to the
requesting campaign/unit. Use the shared RunExecutor and existing model/HTTP
brokers, not recursive session start_run. Candidate validation has no campaign-
editing privilege, even if the target itself happens to be a refiner design.
External side effects require their own approved validation capabilities.

Long operations return durable handles. Do not hold a database/file lock while
awaiting a model, child Run, or human. Blocking store work runs off the event loop
with the owning profile context; cancellation remains serviceable.

## 12. Publication and recovery

Implementation note (unexecuted): campaign-index collection additions are handled
inside the existing Duet transaction when `CampaignStore` opens. An older known
layout with a subset of current collections is copied into the current layout,
then replaced with its lookup index restored. Original immutable records, operation
IDs, credit and head pointers are not rewritten. Unknown schema changes are
rejected; this is a storage migration, not replay of prior actions. Migration and
compatibility validation remain deferred with the unified verification work.

The transaction design spans existing stores without pretending they share one
atomic commit. Exact blobs/audit observations are published first. The campaign
transaction then commits their references, admitted deltas, operative statuses,
semantic-key uniqueness, yield/controller state, stage/assignment changes and
an outbox receipt together. Only that transaction makes progress operative.

There are two transaction kinds. A **stage commit** publishes its observation or
candidate/invalidation transition and advances pending-stage state; it does not
observe a new parent semantic unit or award parent credit. A **unit close** references
the exact committed stage transitions, admits the role's still-applicable progress
facts, and atomically records yield, controller observation, disposition and receipt.
Each role judges its own contribution. Intermediate invalidations/conflict returns
are immediately operative; credit does not wait in an untracked worker buffer and
is never awarded separately for every stage of the same parent unit.

```text
authenticated attempt / host observation
  -> durable raw evidence and immutable blobs
  -> validate proposal, lineage, scope and expected predecessor
  -> transaction: admit delta + derive credit/control + persist receipt/outbox
  -> publish correlated Run audit event
  -> acknowledge worker / advance stage
```

The store publication seam independently validates the admitted transition and
credit relation; it does not trust a broker-supplied scalar or checkpoint. A
positive credit row must reference at least one valid committed transition and
its evidence. A generic stored proposal is never read as an operative commit.

| Failure point | Recovery behavior |
| --- | --- |
| Before evidence publication | No admitted progress; retry the identified acquisition only under its replay policy |
| After evidence/blob commit, before campaign transaction | Reuse evidence; orphan immutable blobs are inert, not success |
| During campaign transaction or yield calculation | Roll back operative changes; preserve attempt and persist invalid/rejection outcome when possible |
| After campaign commit, before Run audit append | Drain outbox idempotently; credit cannot be applied twice |
| After audit append, before acknowledgement | Return the existing receipt for the same operation ID/hash |
| After child return, before parent assessment | Resume the recorded next stage; do not rerun a completed child or pretend assessment occurred |
| After external stop | Mark the actual Run terminal; recover logical invocation under a fresh authorized Run with unchanged task/controller history |

Run audit publication needs a host-owned origin/sequence distinct from workers and
learning. Receipt identity is its deduplication key. An outbox replay encountering
an already terminal old Run does not append after terminal: it records the durable
campaign receipt's reconciliation and exposes it in the recovery Run audit. Final
publication must account for all earlier campaign commits before claiming readiness.

Recovery of a requested validation Run first looks up its persisted operation-to-
Run link and live/terminal evidence. It does not launch another because a response
was lost. A dead uncertain execution is finalized as interrupted before a permitted
new execution attempt; non-replayable external effects require explicit resolution.

Initialization that can fail must occur before publishing an unclaimable Run or
inside a finalizable lifecycle. A broker/preflight failure cannot leave a phantom
Run that can never receive terminal evidence. No new refiner preflight is charged
to ordinary Runs lacking the capability.

## 13. Goal 1 review and handoff

This document describes the concrete roles' inputs, stages, permitted children,
measures, admission, progress, return/recovery and information boundaries. It also
identifies three shared gaps that must actually be implemented: staged child
continuations, approved repeatable Parts calls, and authenticated incomplete
returns with campaign-aware host operations.

Design decisions are specified here; exact code-generated definition hashes,
real target-specific predicates and executable approvals must be materialized
before a Run. They are not values an active worker may invent. Missing grounding
has a specified unresolved outcome rather than an unspecified future metric.

Self-review must check the already-correct path, an ordinary repair, a missing
oracle, an instrument-build prerequisite, an A/B cycle, a cross-level return and
each recovery boundary against these contracts. Goal 2 begins only after review
and authorization. No product tests, model Runs or production edits accompany
this Goal 1 deliverable.
