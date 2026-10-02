# Live reasoning acceptance: resource-constrained scheduling

Run on 2026-10-02 against the generic reasoning Episode. **Passed.**

Latest recorded run, at `949ef227e6` after the same-unit repair fix: provider `openai-codex`, model
`gpt-5.6-sol-900k`. Four real model calls produced two Episode units in
approximately 128 seconds. Both submissions met the frozen schema immediately;
this live run did not need a repair.

Both live runs explicitly used the approved benchmark continuation threshold
`max_predicted_marginal_hypervolume: 0.9`, overriding the library reference's
`0.01`. The duration and call counts describe that benchmark configuration,
**not the shipped default**. Neither recorded stopping bound would stop at
`0.01`; a default-threshold live run has not been performed.

## Problem and returned answer

Schedule seven nonpreemptive jobs on two identical workers available from time
zero. A job occupies one worker throughout. Laser jobs also require the single
shared laser. All starts are nonnegative integers. A predecessor must finish
before its successor starts; touching endpoints do not overlap. Minimize the
time when all jobs are finished.

| Job | Duration | Predecessors | Laser? | Returned start | Finish |
| --- | ---: | --- | --- | ---: | ---: |
| A | 3 | — | yes | 4 | 7 |
| B | 4 | — | yes | 0 | 4 |
| C | 2 | — | no | 0 | 2 |
| D | 5 | A | no | 7 | 12 |
| E | 3 | B | yes | 7 | 10 |
| F | 2 | C, D | no | 12 | 14 |
| G | 4 | E | no | 10 | 14 |

The Episode's answer is **14**. A separate exhaustive solver, never exposed to
the model, also found minimum makespan **14**. An independent interval checker
found no worker-capacity, laser-exclusivity, start-time or precedence violations.

## Inspectable optimality argument

The laser jobs A, B and E cannot overlap, and B must precede E. There are only
three possible orders:

- A–B–E: E finishes no earlier than `3 + 4 + 3 = 10`; G adds four, so at least 14.
- B–A–E: A finishes no earlier than `4 + 3 = 7`; D then F add seven, so at least 14.
- B–E–A: A finishes no earlier than `4 + 3 + 3 = 10`; D then F add seven, so at least 17.

Idle time cannot reduce these bounds. The displayed schedule achieves 14, so
the lower bound is attained. This is the substance of the model's returned
argument, which can be checked without trusting the model's confidence.

## Control trace and the earlier repair defect

The latest run selected `solve`, admitted the schedule, and earned yield 1.
It then selected `verify`, checked the existing answer, and earned no additional
credit. The two committed observations have cumulative credits 1 and 1.

The fixed continuation threshold was 0.9. At return, the existing numerical
controller's projected marginal credit upper bound was approximately
0.749286267, so it returned `yield_saturated`. The model did not choose the
completion condition. The test's external timeout did not fire.

An earlier live run against `ff56a38dfa` also solved the problem, but its first
three outputs violated the frozen representation types. Those were incorrectly
counted as zero-yield reasoning units before the fourth output was admitted.
That run exposed a controller defect, not evidence that this behavior was right.

The follow-up keeps rejected representations and repairs inside the same
selected unit, outside numerical observation. The frozen types are now fully
visible to the model. Repaired outputs enter ordinary admission and credit
assignment. Scripted integration checks exercise malformed JSON followed by
repair; durable-store checks establish identical credit/rarefaction to a clean
submission, including interruption/replay. These are control-mechanics checks,
not an additional live reasoning claim.

## Evidence and limits

The latest local raw report is
`/tmp/openchia-reasoning-repair-live.Q01qIk/report.json` (SHA-256
`b5f73b2808abce58f989045159c26ee613caeeaae5ecda80db797dd54299f83c`).
It contains the problem, every live model request/response and route, all host
learning events, the final receipt, the schedule, the explanation and the
independent oracle result. Temporary RunStore files belong to the normal
test-runner sandbox and are cleaned after the run. The earlier diagnostic
report remains at `/tmp/openchia-live-acceptance.9YiSGf/report-v2.json`.

This demonstrates a real model solving a checkable reasoning problem through
the generic Episode loop and returning under host numerical control.
It does **not** establish general research quality, prove every possible
admission policy, or demonstrate live empirical failure-learning. Those claims
would require additional cases with independently observed failure evidence.

The Builder is a deterministic materialization fixture in this acceptance
test. The normal linker, Episode loop, host ledger and numerical controller
are exercised in-process. The tests call the learning broker directly and
record model-response events themselves; they do not exercise the executor's
host–worker transport, process confinement, or live Builder generation.
The separate confined-worker test is unavailable on this host because the
CPU cgroup allocation cannot be attested. See the
[implementation and test instructions](epistemic_yield.md).
