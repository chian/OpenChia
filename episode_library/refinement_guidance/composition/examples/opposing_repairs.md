# Turn an A/B repair cycle into one joint task

Illustrative, unexecuted example of the proposed shared-history behavior. It is
not evidence that the runtime already detects or resolves repair cycles.

## A concrete coupled requirement

A target returns distinct string identifiers in order of their first occurrence.
Both are required:

- A: no duplicate identifier in the result.
- B: include every input identifier, introduce no new identifier, and preserve
  the order of first appearances. Extra repetitions are judged by A, not B.

For input `["beta", "alpha", "beta"]`, the required output is
`["beta", "alpha"]`. Correctness includes empty input and already-distinct
inputs. Identifiers use exact case-sensitive equality in this example.

## How separate fixes can oscillate

| Candidate/approach | Output on the example | Findings |
| --- | --- | --- |
| R0: preserve the input list unchanged | beta, alpha, beta | B passes, but A fails |
| R1: deduplicate then sort alphabetically | alpha, beta | A passes; required first-occurrence order fails |
| R2: restore the input list unchanged | beta, alpha, beta | The earlier duplicate failure returns |

B alone permits repetitions, so it is deliberately insufficient for acceptance.
A and B together require exactly the first-occurrence sequence. Keep a separate
same-candidate joint acceptance predicate; convenient local pass labels cannot
replace the complete requirement.

Persist candidate/source identities, exact outputs, check definitions, dependency
effects and prior attempts at each transition. A different patch text or child
name cannot erase this history. An unperformed recheck is unknown, not green.

## The owning parent changes the assignment boundary

The nearest RefineParts owner covering A and B receives the supported regression
report. It closes/replaces the conflicting assignments with one task: implement
stable uniqueness, preserving first-occurrence order **on the same candidate**.
Relevant failed approaches and protected checks accompany the new assignment.
The Designer does not spawn another Designer to fix B privately.

A suitable approach scans the input left-to-right, appending an identifier only
on its first occurrence while separately tracking membership. Its local measure
must reject both unchanged-input and sorted-unique shortcuts. Parent acceptance
uses the exact output sequence over its protected cases, including `[]`, repeated
singletons, already-distinct reverse-alphabetical order and interleaved duplicates.

The integrated result is accepted only with both properties on one candidate and
applicable evidence. Restoring R0 does not earn new A/B credit. A genuinely new
joint achievement or an admitted scoped lesson can count under the frozen policy;
the conflict report or assignment creation alone is not a solved task.

## Limits

This example has compatible requirements and an elementary solution. Other
conflicts may expose a bad measure, an invalid assumption or incompatible approved
requirements. Preserve those distinctions; a cycle detector must not declare
impossibility from repeated pass/fail patterns alone. Report an unresolved decision
when the owner lacks the evidence or authority to reconcile the requirements.
