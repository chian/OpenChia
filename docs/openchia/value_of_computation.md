# Value-of-computation yield estimator

`numeric_control_library/value_of_computation.py` supplies a reusable estimator
for repeated attempts where a diagnosis can improve the next decision without
immediately raising the measured score. The standalone algorithm and its
evidence journal come from
[`millenial_biology` at `f4d1ed2`](https://github.com/chian/millenial_biology/blob/f4d1ed2d0aeca2386d45f1f720461f53dd2c7a39/value_of_computation.py).

The registered function is `yield_estimation.value_of_computation`, exported as
`VALUE_OF_COMPUTATION`. It uses the standard `LibraryFunction` definition,
content-derived definition ID, parameter admission, executable loading, and
deterministic admission scenarios. EpisodeBuilder includes it in its reusable
function catalog. Calling it requires no model service or external dependency.

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

The existing `compose_incidence_controller` and Architecture rarefaction
selection consume `NumericIncidenceState` and return `NumericYieldProjection`.
Those anonymous counts cannot reconstruct the action transitions needed here.
This addition leaves that controller and its selectable rarefaction functions
unchanged. It does **not** make this estimator a drop-in replacement for
`paired_incidence` in that controller. A caller must supply its predictive
model and decide how the forecast informs its own numerical control.

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
