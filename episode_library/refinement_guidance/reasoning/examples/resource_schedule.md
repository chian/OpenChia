# Seven-job schedule with a checkable optimum

This is an existing **recorded live answer**, not a new run or a fully validated
refiner. The receipt used the generic reasoning loop in-process and threshold
`0.9`, not the reference's `0.01`. It does not prove confined transport or active
refiner behavior. The exact receipt and oracle sources are pinned in the card.

This file reveals the answer. Use it to design/refine methods and measures; do not
give it to a solver and then claim independent live acceptance on the same problem.

## Task and result

Two identical workers are available from time zero. Jobs are nonpreemptive, each
occupies one worker, and laser jobs additionally share one exclusive laser.
Starts are nonnegative integers; a predecessor must finish before its successor
starts. Touching endpoints do not overlap. Minimize makespan.

| Job | Duration | Predecessors | Laser | Recorded start | Finish |
| --- | ---: | --- | --- | ---: | ---: |
| A | 3 | none | yes | 4 | 7 |
| B | 4 | none | yes | 0 | 4 |
| C | 2 | none | no | 0 | 2 |
| D | 5 | A | no | 7 | 12 |
| E | 3 | B | yes | 7 | 10 |
| F | 2 | C, D | no | 12 | 14 |
| G | 4 | E | no | 10 | 14 |

The answer is 14. A separate interval checker examines job coverage, integer
starts, precedence, two-worker capacity and laser exclusivity. The recorded run's
independent exhaustive solver also returned an optimum of 14.

## Why the optimum is inspectable

The laser jobs are A, B and E, with B before E. Their only possible orders give
these lower bounds:

- A–B–E: E cannot finish before 10; its successor G adds 4, giving at least 14.
- B–A–E: A cannot finish before 7; D followed by F adds 7, giving at least 14.
- B–E–A: A cannot finish before 10; D followed by F adds 7, giving at least 17.

Inserting idle time cannot improve these bounds. The displayed schedule attains
14, so feasibility plus the bound establishes optimality for this instance.

## What a refiner should learn from the design

The answer contract requires a concrete schedule and makespan, not just a problem
formulation or a promise to use a solver. Feasibility and optimality are different
checks. An optimal number with an invalid schedule is not an accepted answer.

A coding child repairing a scheduling Episode can have frozen local checks for
its result decoder, constraints and independently specified sample instances.
The parent's acceptance checks the actual returned artifact and optimality claim,
on the exact candidate. It must not copy the candidate's own result as its oracle.
The historical test checks schedule and makespan with executable oracles; the
argument above is inspectable mathematical justification, not a general automated
natural-language proof checker.

## Receipt limits that matter

The latest documented run at `949ef227e6` made four real model calls over two
Episode units in about 128 seconds. It admitted a solution, then a verification
unit with no new credit. The projected bound near `0.749286267` permits return at
`0.9`, not at `0.01`. No default-threshold live run is documented there.

The Builder was a deterministic fixture, the broker was called in-process, and
the test recorded model-response events itself. The result is real task-answer
evidence, but not proof of the isolated execution boundary, general reasoning
quality, empirical failure-learning, or a generic IterativeEpisodeRefiner.
