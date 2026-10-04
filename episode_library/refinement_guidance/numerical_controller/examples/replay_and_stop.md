# Challenge novelty, replay and stop decisions

Illustrative, unexecuted checking pattern. Labels A, B and J below name semantic
facts, not serialized IDs or measured numeric values. Instantiate exact facts,
predicates and expected relations before the coding assignment begins.

## Admission and history trace

Assume a task needs properties A and B together, with a separately declared joint
condition J. A is established at the baseline. The table states what evidence may
be newly admitted, not a universal credit amount.

| Observation | Current task state | Incrementally novel evidence |
| --- | --- | --- |
| Import an already established A | A pass, B unknown | No new achievement merely from importing the baseline |
| Demonstrate B for the first time | Reassess A under the candidate dependencies | B may be a new local milestone; J is still unestablished without same-candidate guards |
| Replay that exact observation | Unchanged | None; return the existing receipt |
| Rename the assignment and restate B | Unchanged | None; semantic achievement survives renaming |
| Attempt a change; it fails with no useful lesson | Record actual failed/unknown checks | No positive yield from the failure itself |
| New evidence invalidates B | B no longer operative | Remove B from active decisions; preserve history; a separate useful determination may be admitted |
| Restore the earlier B behavior | B pass again | No new B achievement; restoration is not novelty |
| Demonstrate A and B jointly on one candidate | A, B and J pass under applicable evidence | J may be novel only if predeclared, genuinely distinct and not already credited |

The exact host policy decides which observations qualify and their yield. It must
not keep a known-invalid fact active to protect a credit total. Nor should it hide
a new useful counterexample merely because the attempted implementation failed.

A local checker should challenge replay after audit commit, state commit and
measurement publication. An old operation with a different payload is a conflict,
not a new opportunity to overwrite its evidence. These are mechanism checks, not
proof that a complete reasoning task has been solved.

## Numeric continuation boundary

For a contract whose threshold is exactly `0.01`:

| Projected next-credit band | Expected numerical decision |
| --- | --- |
| Ready; upper bound `0.02` | Continue |
| Ready; upper bound `0.01` | Return under the numerical rule |
| Ready; upper bound `0.005` | Return under the numerical rule |
| Unavailable, with zero sentinel fields | Do not infer return from those zeros |
| Malformed interval or non-finite input | Reject; do not invent a band |

These examples exercise the continuation boundary only. They do not establish
that the upstream estimator produced the correct band or that all task requirements
are satisfied. Parent acceptance must examine the composed path and report unmet
requirements separately from the numerical return.

## A real receipt that must not be overextended

The recorded scheduling case solved its task, but its latest receipt used a
threshold of `0.9` and stopped near `0.749286267`. That would **not** stop under
the library's `0.01` threshold. Its in-process execution also does not establish
host-worker transport. Use it as an inspectable answer and a configuration-audit
example, not as evidence for default-threshold runtime acceptance.
