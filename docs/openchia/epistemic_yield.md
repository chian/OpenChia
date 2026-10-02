# Generic reasoning Episodes and durable epistemic yield

## Architecture mapping (Phase 0)

| Specification concept | Existing implementation and extension |
| --- | --- |
| Approved frozen contract | `agent.episode_contract_models.EpisodeCreationSpec`; optional epistemic contract, omitted for legacy records |
| Exact registered schema/projector/admission/yield | `function_library.LibraryFunction` and `FunctionLibrary`; versioned function IDs plus immutable definition IDs, no parallel registry |
| Reference reasoning Episode | `episode_library.EpisodeLibraryDesign`, catalog and `episode_builder.reference.EpisodeReferenceResolver` |
| Materialization identity | `WorkflowMaterializationPlan.validate_against`, host-owned selections and declarations; the contract hash covers epistemic policy |
| Runtime source identity | `episode_runtime.identity`; selected local sources and entire admitted library roots are staged and hashed |
| Repeated unit and topology | `method_loop.Episode`, `Leaf`, `ControllerRuntime`; existing fixed topology and numeric stop semantics |
| Host audit/persistence | `episode_runtime.store.RunStore`: canonical immutable files, exclusive publication, fsync, claim lock, hash-linked events |
| Learning ledger | Typed host-owned learning events in the existing Run event chain; immutable transitions and durable before/after state |
| Numeric control | Existing float-based `NumericBand`, registered rarefaction and continuation; no new floating-point domain or semantic budget |
| Worker boundary | Closed `episode_runtime.protocol` exchange, analogous to model transport; worker submits candidates, host supplies admitted state and numerical decisions |
| Parent handoff | `ClosedRecord` and `handoff_library.ChildResult`; projections contain typed artifacts and provenance, never audit prose as instructions |

### Existing transaction path

```text
Duet exact approval -> ApprovedBuildRequest -> materialization plan
 -> generated modules + static admission -> immutable manifest
 -> RunRegistration -> staged runtime -> confined worker -> typed protocol
 -> RunStore event chain -> terminal audit chunks/manifest -> RunEvidence
```

The existing generic controller runs in the worker and RunStore explicitly
provides terminal audit reads, not resumable execution. Reasoning requires a
host-owned unit transaction and typed retrieval. Extending the existing store
with this narrowly scoped operation preserves confinement: the worker never
receives a filesystem path or a mutable host ledger. Legacy controllers remain
unchanged. Durable unit retry/recovery does not imply that the one-shot isolated
executor can resume an arbitrary terminated process.

### Decision

Add a generic reasoning reference and an inquiry reference using shared,
registered primitives. Freeze schema, projector, admission, yield, scope,
action set, evidence criteria and environmental assumptions in the approved
contract. Local and explicitly authorized workflow learning share the Run
ledger; domain/global promotion is rejected pending its own approval workflow.

Audit evidence is published before admission. One atomic host event contains
the admitted transitions, resulting state, yield measurement, and registered
continuation decision. This stronger transaction boundary removes the
ledger-committed/credit-missing window. A retry returns the existing receipt;
it cannot create a second transition or credit event. Evidence left by an
interrupted transaction remains auditable and non-operative.

Automatic negative knowledge is conservative: it describes a failed attempt
under exact recorded conditions and defaults to advisory. Structural admission
of a problem formulation is not proof that its scientific claims are true.
Evidence and explicit unresolved uncertainties must remain visible. Raw text
and model-authored scalar ratings never enter numerical control directly.

## Delivered library and runtime surface

The catalog entries are `reasoning.generic` and `reasoning.inquiry`. Neither is
a new Episode runtime class. `episode_library.inquiry.inquiry_contract` builds
the frozen problem-discovery configuration; use `EpistemicContract` directly
for other reasoning goals. Attach it as `EpisodeCreationSpec.epistemic` and
select the corresponding library reference in the Duet architecture.

The optional contract freezes the allowed action classes, goal/domain,
environment and assumptions, required formulation fields and evidence classes,
learning scope and strength, and five exact registered component selections.
An existing Episode without this field retains its previous serialized record
and controller. The Architecture view exposes the policy as “Reasoning and
learning”; the materialization binds its exact function definition identities.

Each unit selects an action and typed `action_inputs`, obtains host permission,
then calls the model for the result. A lesson applies to that action **and its
inputs**, not to every use of a broad operation such as searching. The host
requires a deliberate explanation for advisory retries; an explicitly approved
enforceable exclusion rejects matching actions. Different input conditions do
not inherit that exclusion.

### Schema and storage

Version 1 uses the existing `FunctionLibrary` with `epistemic.*_v1` identifiers
and immutable definition hashes. There is no new database, migration, core
model tool, environment setting, or outbound telemetry. Existing Run events
gain these additive kinds:

```text
learning_opened   frozen policy and numerical selections
learning_evidence   immutable human-approved evidence envelopes
learning_selected   permitted/denied action and exact typed inputs
learning_attempt   raw candidate, producing call and stable unit identity
learning_committed   admitted transitions + checkpoint + credit + decision
```

The committed result envelope and admitted records carry content hashes.
Ordering and provenance use the existing hash-linked event sequence rather
than adding nondeterministic timestamps to retry identities. Status changes
are new transitions; previously published records are never overwritten.
The store checks audit/evidence lineage, before/after consistency, checkpoint
completeness, immutable hashes and credit/delta consistency before publication.

An atomic `learning_committed` event contains the complete causal receipt:
attempt audit → candidate admission/rejection → state delta → yield → historical
credit → rarefaction/continuation. Its `terminal_state` separates ordinary
yield-based completion from blocked work. Run terminal states also distinguish
interruption, invalid execution, resource limitation and cancellation. A worker
cannot publish successful reasoning completion without the host's receipt.

### Current policy and deliberate limits

- Automatic negative learning requires an independent, matching observation
  in the approved evidence, including exact action inputs, conditions, expected
  and observed outcomes. A model's own account of a failed experiment is not
  an independently verified observation. The current Run supports brokered
  model calls, not arbitrary new empirical tool/evidence sources.
- Formulations must include the frozen fields, answer forms, acceptance and
  falsification criteria, and exact quotations from every required evidence
  class. This establishes an evidence-linked formulation, **not proof of its
  truth, importance, novelty, or the correctness of an answer**. Domain-specific
  semantic validation needs an appropriately registered admission function.
- Version 1 yield counts distinct, newly admitted operative records. Failed
  attempts, rejected proposals, paraphrases sharing an equivalence key and
  reactivation of previously credited knowledge earn no additional credit.
  Identity is conservative: shared evidence cannot generate arbitrarily many
  credited formulations. This is not general semantic-equivalence detection.
- Historical credit is monotonic. Reopening, supersession and contradiction
  remove operative effects without erasing history or refunding past credit.
  The next numerical observation includes only currently operative knowledge.
- Episode-local and explicitly approved workflow-local scopes are implemented
  within a Run. Siblings cannot earn fresh credit for preexisting shared state.
  Domain/global promotion is rejected; it has no implicit authority path.
- Environment applicability can be re-evaluated by the host. The initial broker
  uses approved environment facts; no worker-controlled fingerprint update or
  automatic external dependency monitor is introduced.
- Unit transaction replay is crash-safe. Full process resumption remains an
  existing one-shot executor limitation, not a newly claimed feature.

## Validation: distinguish machinery from reasoning

The first [live acceptance receipt](epistemic_yield_acceptance.md) records an
independently verified optimal schedule, including the actual model's answer
and a human-checkable optimality argument.

`test_epistemic_learning.py` checks real durable IO, crash replay, authority,
conditional retrieval, exclusions, revisions, duplicate credit and forged
commits. `test_reasoning_workflow.py` exercises approval, materialization,
linking and the generic loop with **scripted model responses**. These tests
establish control invariants; neither demonstrates a model's reasoning ability.

`test_live_reasoning_acceptance.py` is a separate, opt-in acceptance test. Its
seven-job scheduling problem requires a concrete optimal schedule and a
lower-bound argument. Every action-selection and reasoning response comes
from the configured live model. An independent exhaustive integer scheduler
computes the optimum, and a separate interval checker checks every resource
and precedence constraint. The oracle's answer is never sent to the model.
The report includes the problem, raw model answers, provider route, final
schedule, claimed optimum, lower-bound explanation and independent verdict.
The numeric optimum is mechanically verified; the explanation remains
available for human inspection rather than being declared proven by an LLM.

The live test uses a deterministic Builder fixture and the real linked Episode
loop/host ledger. It does not claim live Builder-generation or process-isolation
coverage. A separate systemd/Landlock/seccomp test requires a host whose cgroup
allocation can be attested and skips explicitly otherwise.

Run the hermetic checks through the project runner:

```bash
scripts/run_tests.sh tests/episode_runtime/ tests/method_loop/ -q
```

For live reasoning, create a private temporary directory and start the host
bridge with the normal configured provider. The test runner remains isolated
from credentials and the production Hermes home:

```bash
python scripts/openchia_live_model_bridge.py --socket /private/temp/model.sock
scripts/run_tests.sh tests/episode_runtime/test_live_reasoning_acceptance.py \
  --file-timeout 900 -- -q --tb=short \
  --live-reasoning-socket /private/temp/model.sock \
  --live-reasoning-report /private/temp/report.json
```

The harness timeout is an external test fail-safe: it cannot make the Episode
complete. The bridge is opt-in, uses a mode-0600 local Unix socket, and exposes
only the existing scoped model transport. Stop it after the acceptance run.
