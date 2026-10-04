# Separate model, simulator and evidence

Keep three questions distinct: is the model a justified description of the target,
does the implementation follow that model, and what does the simulated evidence
support? A fast, reproducible simulation can still answer the wrong question.

## Fix model and observation semantics

Record state variables, units, initial conditions, transition/event rules, time
conventions, random inputs, observations and the quantity to estimate. Define
event ordering and boundary behavior; otherwise two apparently valid simulators
may implement different processes.

Separate the random-input mechanism from state-transition logic where the task
permits. That enables exact deterministic controls without pretending a stochastic
trajectory must equal its expected value.

## Choose local implementation measures

Use invariants and independently calculated small cases: legal states, conserved
quantities, impossible transitions, deterministic limits, exact one-step or
short-horizon distributions. Instrument checks must detect constant outputs and
plausible but wrong transition rules, not only confirm output shape.

Do not let exact local controls become a claim about arbitrary long trajectories
or real-world validity. Statistical checks of random-input behavior and complete
execution belong in the declared parent acceptance as well.

## Declare statistical judgments before seeing results

Specify the estimand, independent replication unit, sampling design, seed/random
stream policy, decision procedure, uncertainty and error allowance. Account for
multiple comparisons or adaptive observation when those occur. Correlated time
steps are not automatically independent samples.

A fixed sample size can be part of a **measurement instrument**. It is not a turn,
token or time budget that determines semantic Episode completion. If repeated
looks at results are allowed, use the admitted sequential procedure; do not keep
sampling or changing seeds until a favorable threshold happens to be crossed.

## Acceptance and reporting

The parent verifies the exact candidate, model, inputs and statistical procedure.
Retain raw observations, aggregate counts and uncertainty in evidence artifacts;
pass the supported determination and its limits upward, not every trajectory or
a model-written assurance that the simulation “looks right.”

If a chosen model conflicts with external evidence, propose that design issue to
the owning Parts Episode. Silently changing the model to fit observed outputs is
not an implementation repair. If the required validation evidence does not exist,
return the gap rather than promoting simulated plausibility to fact.
