# Design reasoning around an inspectable answer

Define what an answer must contain, what would make it adequate, and what would
show that it fails. These are separate requirements. A typed claim and a persuasive
explanation are not themselves a verified answer.

## Start with the actual question

Distinguish discovering candidate problems, answering a known question, finding a
feasible object, and establishing optimality or impossibility. A search strategy
is not a schedule; a feasible schedule is not automatically an optimal one.
The existing inquiry reference is for problem discovery, while the generic
reasoning binding permits task-specific goals and admitted state transitions.

Specify required evidence classes, admissible actions, counterevidence and known
uncertainties. Allow an explicit unsupported/unresolved state rather than forcing
the model to populate an answer field as if every question had been settled.

## Make progress observable

Potential milestones include a fully scoped candidate, an independently checked
constraint, a falsified approach, or a testable answer criterion. A milestone needs
committed evidence and a defined effect on the decision state. Another paragraph,
an expression of confidence or another formulation of the same claim is not new
progress.

Separate direct answers from failure-derived knowledge. A failed approach can
support a conditional lesson only when its conditions, evidence, future effect,
novelty and reopening conditions are admitted. “This never works” is not a valid
inference from one local failure.

## Local implementation and parent judgment

The implementer can measure schema handling, evidence linkage, declared action
eligibility and behavior on independently specified local cases. If its assignment
is to produce a solver, the local measure must also examine solution behavior;
passing plumbing alone does not meet a reasoning requirement.

The parent separately verifies the exact result against the original problem:
for example, a constraint checker for feasibility plus an independent reference
or inspectable proof for an optimality claim. Do not let the solver define its
own expected answer or substitute one model's endorsement for independent evidence.

Use a numerical controller for repetition, not a fixed number of reasoning turns
or the model's declaration that it is done. A supported partial frontier can be
returned when yield rarefies, but unmet answer requirements remain explicit.

## Transfer limits

An oracle for a finite scheduling instance does not validate open-ended scientific
claims. An answer revealed in a worked example cannot later serve as a blinded
test of independent reasoning on that same instance. Use comparable undisclosed
cases or clearly label the exercise as a reproduction.

When facts cannot currently be independently checked, keep provenance and the
required review authority visible. Good design includes an honest evidence gap;
it does not conceal the gap behind extra reasoning agents.
