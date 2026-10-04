# Build a measure that rejects the wrong thing

A useful measure states what observation would distinguish satisfaction from
violation of an actual task requirement. A count of tests, a model's confidence
or a checklist of activities is not that measure.

## Establish grounding

Bind the original requirement, input domain, observation procedure, expected
relation, oracle source, decision predicate and evidence limits. The expected
answer must not be copied from the implementation being repaired.

Use an independently admitted reference, exhaustive finite oracle, mathematical
relation, trusted predicate or explicitly authorized review. Inspect the oracle's
applicability rather than treating its name as proof. Finite positive examples
support their tested domain; one valid counterexample can refute a universal claim.

If no such grounding is available, report a measurement gap. Another model agreeing
with the first is not an independent behavioral observation or an authorized
human determination.

## Challenge adequacy before use

Try a known satisfactory case and known violations of each discriminating
condition. Include plausible shortcuts: constant answers, missing required work,
correct output shape with wrong semantics, stale evidence and a check that never
executes. If a trivial candidate passes, explain which requirement is uncovered.

Do not confuse these three judgments:

| Judgment | Question |
| --- | --- |
| Instrument adequacy | Does this check observe and discriminate the intended condition within its declared domain? |
| Local implementation measure | Is this candidate making new demonstrated progress toward its assigned behavior while preserving required guards? |
| Parent acceptance | Does the exact candidate satisfy the enclosing requirement, including behavior local milestones do not prove? |

Controls are necessary, not a universal proof that the checker cannot be wrong.
When instrument code is needed, return a grounded instrument-building task for
the authorized design/coding path. Do not let the instrument certify itself from
its own generated expectations or start an unbounded chain of judging agents.

## Protect the judgment during refinement

Freeze the local measure and parent acceptance contract before the affected child
starts. The coder may challenge them with evidence but cannot change protected
criteria to make a favored candidate pass. A genuine change needs a successor
assignment retaining relevant history.

Bind every observation to exact candidate, inputs, checks, dependencies and
environment. An unperformed, errored, stale or inconclusive check is not a pass.
Reusing a result needs an admitted dependency match, not a familiar filename.

VerifyBehavior performs independent acceptance, not repairs. It returns supported
determinations, counterexamples, unperformed checks and limitations. A valid
counterexample may be useful progress; a favorable label without observations
is not. The host decides admission, credit and authoritative status.
