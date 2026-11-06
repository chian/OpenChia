# Value-of-computation yield estimator

`numeric_control_library/value_of_computation.py` supplies a reusable estimator
for repeated attempts where a diagnosis can improve the next decision without
immediately raising the measured score. The standalone algorithm and its
evidence journal come from
[`millenial_biology` at `f4d1ed2`](https://github.com/chian/millenial_biology/blob/f4d1ed2d0aeca2386d45f1f720461f53dd2c7a39/value_of_computation.py).

Two reusable components are registered in EpisodeBuilder's function catalog:

| Registered component | Export | Purpose |
| --- | --- | --- |
| `yield_estimation.value_of_computation` | `VALUE_OF_COMPUTATION` | Forecast from an explicit predictive model. |
| `controller_composition.compose_computation_controller` | `COMPOSE_COMPUTATION_CONTROLLER` | Connect measured Episode outcomes to forecasts and chooser feedback. |

Both use standard `LibraryFunction` definitions, content-derived definition
IDs, parameter admission, executable loading, and deterministic admission
scenarios. Neither requires a model service or an external dependency.

## Inputs and results

The caller supplies a `PredictiveModel` with three methods:

- `score(state)`: the measured scalar value of a state.
- `actions(state)`: available action names.
- `predict(state, action, history)`: a probability distribution over successor
  states, or `None` when the prediction is unknown. `history` contains imagined
  observations along this forecast branch, allowing posterior updates inside
  planning without modifying actual observations.

States must retain information that changes later decisions, including cases
where that information does not change the current score. The reference
`BayesianTransitionModel` uses categorical transitions with explicit Dirichlet
priors or observed outcomes. Distinct states do not automatically share evidence.

```python
from numeric_control_library import BayesianTransitionModel, VALUE_OF_COMPUTATION

model = BayesianTransitionModel()
model.register_state("unqualified", score=0, actions=("diagnose",))
model.register_state("defect_known", score=0, actions=("repair",))
model.register_state("qualified", score=1)
model.observe(
    "diagnosis:1", state="unqualified", action="diagnose",
    next_state="defect_known", evidence_refs=["control:counterexample"],
)
model.observe(
    "repair:1", state="defect_known", action="repair",
    next_state="qualified", evidence_refs=["control:qualified_repair"],
)
parameters = VALUE_OF_COMPUTATION.admit_arguments({"lookahead": 2})
report = VALUE_OF_COMPUTATION.load()(model, "unqualified", **parameters)
assert report.estimates[0].immediate_gain == 0
assert report.estimates[0].expected_gain == 1
```

For each action, `ComputationReport` records expected terminal score, expected
gain relative to the current score, immediate gain, continuation gain,
predictive standard deviation, probability of improvement, evidence IDs, and
unmodeled decisions. The follow-up policy chooses using expected values before
future outcomes are known. It can retain the current state instead of taking
an unhelpful follow-up action.

Scores are terminal values rather than accumulated transient rewards. A cycle
of awarding and retracting the same provisional score cannot manufacture yield.
An action with a negative immediate gain can still enable valuable repair.

## Evidence revisions and limits of the forecast

`observe` records evidence-bearing actual transitions. Revisions of one event
replace that event's statistical contribution. Confirmation cannot double-count
a provisional event. Pending and withdrawn observations do not count as failed
attempts. `snapshot()` and `from_snapshot()` retain and validate the full journal.

Predictions without declared priors are conditional on observed support: they
cannot rule out unseen outcomes. An action without evidence or a declared prior
remains unknown. Forecasts expose unknown alternatives, including follow-ups,
and never interpret them as zero yield or an exhausted search. Predictive
standard deviation describes outcome dispersion, not a confidence interval for
the estimated mean. Forecast quality depends on model calibration.

`lookahead` is a positive forecast depth, defaulting to 3. It does not bound
Episode execution. The estimator performs no actions, assigns no credit, and
makes no stopping decision.

## Interface compatibility

The registered interface is `yield.posterior_predictive`. It consumes a
predictive state/action model and returns `ComputationReport`. It can be called
directly by code using that contract or selected as a reusable helper in a
materialization.

The connection lives in `numeric_control_library/computation_adapter.py`. Its
registered `controller.compose_predictive_computation` interface returns a
`ControllerFactory` implementing the existing method-loop protocol. Bind that
factory to a `Grain.controller`; no method-loop changes are required. Each
Episode path receives an independent advisor and model journal.

The factory signature is
`compose_computation_controller(*, epoch, initial_state, lookahead=3, model_snapshot=None)`.
`epoch` and `initial_state` are runtime measurements; `lookahead` is the
function-owned binding parameter. A supplied model snapshot explicitly seeds
the model, including any declared priors. Without one, predictions start
unknown and learn only from supplied observations.

The caller's task-specific projection constructs these library records:

| Record | Required information |
| --- | --- |
| `ComputationState` | Immutable state identity, measured scalar score, evidence references, and available action names. |
| `ComputationObservation` | Event identity, origin state, chosen action, successor state, and evidence references; optional status and revision. |
| `ComputationInput` | The current measured state and a tuple of newly available observations or corrections. |

Retained diagnostic findings must change the state identity when they affect
subsequent decisions, even if the numerical score is unchanged. State evidence
references identify the measurement and retained information; actual execution
references belong to observations. The adapter does not define scientific
state equivalence, calculate scores, or transfer outcomes between different
states. Those decisions stay with the caller's task-specific projection.
EpisodeBuilder exposes the measured-record constructors and keyword-only
factory signature in its generated-code contract and checks their arguments
during source admission.

An acquired unit's result projection returns a `ComputationInput`. The method
routes it to `ComputationAdvisor.observe`. The source's next decision receives
`view.controller_state`, a `ComputationFeedback` containing:

- `current_state` and `current_score`;
- `computation_value`, the forecast for every available action;
- `credit_history`, the evidence-bearing observation revisions with origin
  score, successor score, and signed score change.

That history is an event journal, not an additive reward stream: revisions of
one event replace its statistical contribution. Historical corrections are
separate from the explicitly supplied current state. Pending and withdrawn
observations carry no numeric outcome. Invalid batches are rejected without
partially changing the model. Snapshot/replay preserves the current state,
model journal, and forecast depth; duplicate deliveries do not add samples.

The source's chooser owns action selection and task completion. The advisor's
structural `stop` and `requests_transition` flags stay false. An unknown
prediction, negative return, or absence of modeled gain cannot stop the
Episode. A new objective epoch requires a new, explicitly mapped advisor.

The existing `compose_incidence_controller` and Architecture rarefaction
selection consume `NumericIncidenceState` and return `NumericYieldProjection`.
Those anonymous counts cannot reconstruct the action transitions needed here.
That controller and its Architecture rarefaction selections remain unchanged.
The new adapter is a separate registered composition for the generic Episode
method, and is also usable as an advisor from a source's decision code. It
does not reinterpret predictive outcome dispersion as the confidence band
required by incidence continuation. Existing Architecture contracts fixed to
incidence composition are not automatically switched to the new composition.

## Validation

Run through the repository's isolated test runner:

```bash
scripts/run_tests.sh tests/numeric_control_library/ tests/episode_builder/test_value_of_computation_catalog.py
```

Tests cover adaptive diagnosis, posterior learning during forecasts, negative
first gains, provisional-score cycles, unknown alternatives, absence of
clairvoyant choice, correction accounting, journal replay, invalid predictions,
and execution through the actual reusable-function catalog. These are checks
of the algorithm and library boundary, not evidence of research-domain calibration.

Adapter tests execute the real Episode method on independent binomial controls.
Two verifier defects initially have the same score. Forecast-driven choices
select diagnosis and then opposite repairs depending on the returned finding.
The tests also check current-state handling during corrections, signed history,
unknown options, snapshot replay, atomic rejection, and isolation between paths.
Builder admission tests accept valid constructions and reject missing measured
inputs or positional calls to the keyword-only factory before execution.
