# Design the full numerical controller

Treat credit assignment, rarefaction, continuation and their composition as one
design assignment. A function can be correct in isolation while the wrong
observation semantics or units make the combined controller wrong.

This concerns the **target controller being refined**, not permission to change
the controller judging the running Designer or Implementer.

## Fix the meaning before choosing functions

Record the declared repeated unit, result schema, admitted progress identities,
equivalence rules, baseline facts and observation statuses. Specify exactly what
durable state transition makes an identity eligible. Failure narration is not an
identity, and an old milestone under a new assignment ID is not a new achievement.

Keep current operative state distinct from cumulative history. Invalidation must
immediately remove a false lesson or stale pass from current decisions even if
historical credit is monotonic. A repeated restoration cannot earn fresh credit.

## Preserve the numeric boundaries

The inspected reference pipeline has distinct responsibilities:

- Credit assignment sees stable identities and the declared result-column schema.
  It admits observed/failed/excluded units and exports numeric incidence statistics.
- `paired_incidence` receives numeric sufficient statistics, not goal names,
  raw evidence, free text or instructions about when to stop.
- The composer combines the selected credit, estimator and continuation functions.
  Inspect the full data path, not only the three registered names.
- `predicted_credit_upper_bound` stops only for a ready projected-credit band whose
  upper bound is at or below the frozen threshold. An unavailable band is not zero.

In the inspected generic reasoning reference, `uncertainty_alpha` is `0.05` and
`max_predicted_marginal_hypervolume` is `0.01`. These values describe that binding;
they are not permission to override another approved target's parameters.

## Design the behavior that is easy to get wrong

Specify handling of duplicate results, imported baseline knowledge, contradictory
evidence, invalidation/reopening and crash replay. Representation-only output
repair stays within the same substantive unit; a valid repaired output goes
through ordinary admission. Do not turn its rejected serialization attempts into
new numerical observations.

Ensure the observed result dimensions represent real progress. An always-empty
dimension can suppress a composed measure; deleting a required dimension merely
to make the number increase is not an acceptable fix. Schema and admission changes
need the proper successor contract, not an active-run mutation.

For already-correct work, require the declared numeric handling of proven exhausted
required opportunities. A model saying “nothing left” is not such evidence. The
proposed refiner needs an admitted goal-aware path; the existing reference composer
alone must not be assumed to implement it.

## Separate local checks from acceptance

Local checks can establish determinism, identity equivalence, correct statistics,
band validity and threshold behavior on fixed traces. Parent acceptance also needs
the actual composed loop: committed transitions, replay-safe observations,
correct current state, exact selected functions/parameters and honest terminal
states on an inspectable target task.

Neither a few declining yields nor a passing threshold unit check proves that the
estimator is well calibrated for every adaptive search process. State the method's
limits. Numerical return with unsatisfied requirements is an incomplete result;
resource interruption or missing capability cannot be relabeled as yield exhaustion.
