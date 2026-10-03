# IterativeEpisodeRefiner: Goal 1 contract self-review

2026-10-02. Reviewed [contract design v1](iterative_episode_refiner_contracts.md)
against [design v3](iterative_episode_refiner_episodes.md), Goal 1's completion
conditions and the [static repository map](iterative_episode_refiner_integration.md).
This is a design self-review, not independent review, execution evidence, approval
of a runnable workflow, or completion of the implementation goals.

## Goal 1 completion conditions

| Condition | Contract decision / evidence |
| --- | --- |
| Only Parts creates Designers or nested Parts | §§1, 3.3, 5, 8.2 and 11: closed child graph, host-admitted caller/slot, no helper-mediated design creation |
| Implementer remains inside Designer | §5.2: approach admission -> implementation -> independent part acceptance is the required realization path |
| Every role has a concrete measure | §§4–6: grounded task predicates, fixed role-specific admission rules, explicit progress manifest and semantic keys; prose/confidence/volume cannot award credit |
| Task measures precede coding | §§3.4 and 4: exact DesignPlan/instrument admission, protected checks and successor assignments for changed criteria |
| Numerical-controller design stays coupled | §§3.4 and 5.2: one plan/assignment and composition acceptance for credit, rarefaction and continuation |
| Cross-level cycle response occurs during iteration | §§7–9: immediate invalidation/effect records, comparable-regression predicate, common-owner decision return and same-candidate joint acceptance |
| Reassignment retains history | §§2, 3.3, 6, 9 and 12: stable campaign/semantic identities, supersession, replay-safe operations, no new credit for an old pass |
| Honest distinct outcomes | §10: attained, numerically returned unresolved, needs-parent, blocked, invalid and external stop distinctions with explicit precedence |
| No semantic budget | §§6.1 and 10: existing numerical continuation with an evidence-supported zero-opportunity case; no fixed retry/time/token completion rule |
| Shared integration and migrations explicit | Integration map §§1–4: reuse stores/registries/executor; explicitly versioned stages/calls/returns and additive persistence, unchanged old identities |

Completion here means an implementable contract proposal is recorded for review.
Code-generated definition IDs, task-specific oracle artifacts and exact runtime
approvals are later materialization inputs, not unchosen role-level policies.
Missing grounding has a defined outcome, not a placeholder instruction to invent
the metric later.

## Path review

| Situation | Trace through the proposed contract | Result |
| --- | --- | --- |
| Already-correct initial build | Parts baseline assessment -> VerifyBehavior -> exact compatible mandatory evidence -> no required remaining opportunity -> registered numerical return | Original source selected; no invented repair |
| Initial source cannot compile | Independent refiner reads candidate blobs -> scoped design/local measure -> implementer edit -> source admission -> local check -> part acceptance -> enclosing acceptance | Broken source is eligible for repair, not for execution |
| Local change passes | Implementer admits local facts -> Designer invokes its protected acceptance -> Parts judges contribution/composition | No local-to-whole success shortcut |
| Designer needs guidance | Scoped cards/selected body or FindDesignSupport -> applicability admission -> frozen child inputs | Search can help without changing authority or forcing a known specialty |
| A measure needs code | EstablishMeasure returns grounded instrument-build request -> permitted DesignPart/Implementer path with independent controls -> adequacy evaluation | Instrument does not certify itself |
| No grounded instrument/control exists | Question/review can provide evidence under authority; otherwise measurement gap | Honest unresolved result; no endless judge-of-judge chain |
| One root requirement has several behavioral parts | Admit containment/coverage partition -> delegate a proper subset of its slices | Recursion is possible without inventing extra original goals |
| New independent design problem appears in a specialist | Typed need/evidence -> Parts owner -> explicit new or joint assignment | No Designer-to-Designer recursion |
| Candidate edits affect an old pass | Change transaction marks affected observations stale before further selection/readiness | Missing recheck is unknown, never green |
| Two repairs oppose each other | Admitted compatible observations -> conflict record -> safe-boundary return through intermediate stages -> common Parts owner | Conflict visible before child success, with original evidence |
| Joint repair succeeds | New candidate must establish both original conditions plus guards simultaneously | Joint acceptance can be new; repeated old single passes are zero incremental credit |
| A new worker or renamed assignment retries old work | Stable campaign/equivalence/operation records retrieved before selection | No history reset or duplicate award |
| Child completed but parent assessment crashed | Durable child receipt + pending next stage -> new authorized recovery Run -> parent assessment | No unnecessary child rerun and no false whole-build acceptance |
| Host commit succeeded but response disappeared | Same operation ID/hash returns committed receipt; audit outbox reconciles | One state transition and one credit award |
| Child requests an unsupported block | Host checks actual denial/evidence and available resolution paths | Worker status alone cannot terminate work |
| Normal projection predicts low yield while requirements remain | Registered numerical return + unresolved frontier | Not VerifiedBuild |
| Cancellation races with positive progress | Committed facts remain; external terminal status wins over normal readiness | No cancelled Run masquerades as successful completion |

## Corrections made during this review

1. **Strict subset of original requirement IDs was too restrictive.** One complex
   root requirement may have several valid behavioral parts. Added an admitted
   scope partition and proper containment of slices, retaining original credit
   identities and grounded coverage.
2. **Stage persistence and unit credit needed separate transaction kinds.** Candidate
   invalidation must become visible immediately, but a serial parent unit must not
   count as several observations. Specified stage commits versus unit close.
3. **A supplied Episode ID did not authenticate the active role.** Added host-owned
   active invocation handles/stack, admitted enter/return operations, and suspended
   ancestor restrictions.
4. **Conflict and numerical-return precedence needed to be explicit.** A recorded
   controller decision does not override an external stop or parent coordination
   need. Specified the adapter's normal stop separately from typed incomplete return.
5. **A completed goal needed a numerical return without invented work.** Specified
   an evidence-supported zero remaining-opportunity adapter, keeping existing
   continuation and defaults rather than an LLM-determined completion flag.
6. **The current store and linker were not already sufficient.** Recorded explicit
   versioned call/stage/return extensions and campaign persistence in the existing
   Duet database; did not claim that method-loop recursion alone provides them.

No unresolved structural contradiction was found in this self-review. That is not
a guarantee that implementation will reveal none; a newly discovered conflict
must be reported rather than quietly changing these contracts.

## Review boundaries and next work

- The initial numerical settings are exact proposals, not empirically calibrated
  performance claims. Acceptance must use the shipped selected settings and record
  any approved substitution.
- Semantic grounding cannot be made universally automatic by a schema. The design
  explicitly retains approved interpretations, independent evidence and necessary
  human determinations. Missing ones keep the affected requirement unresolved.
- Goal 1 adds documentation only. No product tests or live model Runs were used
  to establish these claims, and no production runtime changes were made.
- The separately requested Goal 5 head start owns only guidance catalog data and
  examples. It is not evidence that selection/search or prompt integration works.
- User review of these contracts precedes Goal 2 implementation. Executable workflow
  approval, authority grants, validation, commits and publication remain distinct.
