# Live reasoning acceptance: resource-constrained scheduling

Run on 2026-10-02 against the generic reasoning Episode. **Passed.**

Provider receipt: `openai-codex`, model `gpt-5.6-sol-900k`. Eight real model
calls produced four Episode units. The test took approximately 325 seconds.
Production implementation: `ff56a38dfa` (subsequent changes add a scope test
and documentation, not different reasoning or admission behavior).

## Problem and returned answer

Schedule seven nonpreemptive jobs on two identical workers available from time
zero. A job occupies one worker throughout. Laser jobs also require the single
shared laser. All starts are nonnegative integers. A predecessor must finish
before its successor starts; touching endpoints do not overlap. Minimize the
time when all jobs are finished.

| Job | Duration | Predecessors | Laser? | Returned start | Finish |
| --- | ---: | --- | --- | ---: | ---: |
| A | 3 | — | yes | 0 | 3 |
| B | 4 | — | yes | 3 | 7 |
| C | 2 | — | no | 0 | 2 |
| D | 5 | A | no | 3 | 8 |
| E | 3 | B | yes | 7 | 10 |
| F | 2 | C, D | no | 8 | 10 |
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

## What the real run exposed

The first three responses contained an answer but violated the frozen output
types: structured schedule data appeared as an object instead of JSON text,
and one observation was an object instead of text. The host rejected those
results for **zero yield**. The model received the typed rejection receipts
and eventually repaired the representation. The fourth unit was admitted,
with realized yield 1 and historical credit changing from 0 to 1.

The fixed continuation threshold was 0.9. At return, the existing numerical
controller's projected marginal credit upper bound was approximately
0.743900839, so it returned `yield_saturated`. The model did not choose the
completion condition. The test's external timeout did not fire.

## Evidence and limits

The local raw report is
`/tmp/openchia-live-acceptance.9YiSGf/report-v2.json`: it contains the problem,
every live model request/response and route, the final host receipt, the
schedule, the explanation and the independent oracle result. Temporary RunStore
files belong to the normal test-runner sandbox and are cleaned after the run.

This demonstrates a real model solving a checkable reasoning problem through
the generic Episode loop, including rejection and repair of malformed results.
It does **not** establish general research quality, prove every possible
admission policy, or demonstrate live empirical failure-learning. Those claims
would require additional cases with independently observed failure evidence.

The Builder is a deterministic materialization fixture in this acceptance
test. The normal linker, Episode loop, host ledger and numerical controller
are exercised, but process confinement and live Builder generation are not.
The separate confined-worker test is unavailable on this host because the
CPU cgroup allocation cannot be attested. See the
[implementation and test instructions](epistemic_yield.md).
