# Weighted rate, not average of percentages

Illustrative, unexecuted task with an inspectable arithmetic answer. There is no
claim that a shipped calculation Episode has solved this case.

## Task

For disjoint groups with exact counts, return the fraction of all inspected items
that are defective. Counts must be integers with `0 <= defective <= inspected`.
Groups with zero inspected items contribute zero only when their defective count
is also zero. A zero total inspected count is an undefined result, not a zero rate.

| Group | Inspected | Defective |
| --- | ---: | ---: |
| A | 500 | 7 |
| B | 150 | 9 |
| C | 350 | 4 |

The quantity is `sum(defective) / sum(inspected) = 20 / 1000 = 1/50 = 2%`.
The unweighted mean of group fractions is `299/10500`, approximately `2.8476%`.
That is an answer to a different question, not a rounding variant of the correct
answer. Round only when formatting the final displayed percentage.

## Good design and measures

Design a typed integer-count input, a validated exact reduction and a separate
formatting step. Do not average already-rounded percentages or parse absent
counts as zeros.

Local implementation checks can be tied to these frozen behavioral milestones:

1. Reject invalid count pairs and preserve the specified zero-total behavior.
2. Produce the exact pooled fraction for independently specified unequal groups.
3. Preserve the result under reordering and legitimate partition/recombination.

For the third check, split A into `(200, 3)` and `(300, 4)`. The total and rate
remain unchanged. The milestone counts as progress only under the parent's
admitted measure and required preservation guards, not simply because one more
assertion was added to a test file.

Parent acceptance uses its protected input domain and an independent exact
integer/rational oracle, not the candidate's own expected outputs. Include cases
with different correct results: `(8, 1)` and `(12, 3)` together give `1/5`, so a
constant `0.02` implementation fails. All-zero totals are undefined; `(5, 6)` is
invalid. Permutation invariance alone would fail to reject a constant function.

## Refinement and limits

If the initial build averages per-group rates, the coding assignment repairs the
reduction while preserving invalid-input behavior and output representation.
Changing the task to “average group percentage” or accepting a loose tolerance
that covers both answers is not a repair.

This reasoning assumes exact, disjoint counts of the same kind of item. Overlapping
groups, sampled estimates with uncertainty, different units or a task explicitly
asking for equal group weighting need a different contract. The example is useful
because its assumptions and wrong alternatives are visible, not because its
formula should be applied to all aggregates.
