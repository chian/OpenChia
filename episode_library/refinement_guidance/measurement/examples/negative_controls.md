# Scheduling checks that a plausible answer can fail

Illustrative, unexecuted controls based on the exact seven-job scheduling problem
in the source inventory. They are proposed instrument-adequacy cases, not a new
acceptance run. This file reveals benchmark answers; keep it out of a blinded
solver's context for this same case.

The known valid start mapping is:

```text
A=4, B=0, C=0, D=7, E=7, F=12, G=10; makespan=14
```

## Distinguish separate requirements

Each row modifies that mapping unless stated otherwise. The oracle must derive
finishes from the problem's durations, not trust supplied finish labels.

| Candidate/control | What must be rejected or distinguished |
| --- | --- |
| Remove F | Missing required job, even if every remaining interval is feasible |
| Give C a boolean rather than integer start | Invalid representation; a language's boolean-as-integer behavior must not silently admit it |
| Change D's start to 6 | D begins before A finishes at 7; worker/laser availability does not excuse precedence |
| Change A's start to 3 | A and B share the laser during 3–4 despite having only two workers active |
| Change C's start to 7 | C, D and E require three workers during 7–9; laser constraints alone do not detect it |
| Keep all valid starts but claim makespan 13 | Declared objective disagrees with the actual completion time 14 |
| Use serial starts A=0, B=3, C=7, D=9, E=14, F=17, G=19; claim 23 | Feasible, but not optimal; a feasibility checker alone must not certify minimum makespan |
| Return only the number 14 | Missing the required concrete schedule and justification |

A second **valid** mapping changes C's start from 0 to 2 while keeping the other
known valid starts. Its makespan is still 14 and all constraints hold. A checker
that compares only against one stored answer would incorrectly reject it.

## Where each check belongs

The instrument builder can use these controls to establish discrimination of
representation, job coverage, precedence, capacity and objective claims. The
coding child can use its admitted local subset while refining the implementation.
The parent independently checks the actual produced result and optimality on the
exact candidate under its protected acceptance contract.

The existing exhaustive oracle receives the fixed problem, not the model's
explanation. Its fixed job order is topological for this case. Applying it to a
different graph without establishing that property is outside its current scope.
An inspectable proof or suitable independent oracle is required for optimality;
confidence and explanation length do not substitute for it.

These controls do not establish transport, confinement, arbitrary scheduling
correctness or general reasoning ability. They establish what a narrowly scoped
instrument ought to distinguish. Any executed claim must cite the real resulting
observations, not this authored table.
