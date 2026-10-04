# A parent consumes admitted results, not child prose

This is a statically inspected library pattern. It is not a live refiner result.
The existing search-strategy and web-search declarations separate selecting a
child, preparing its request, admitting its result and computing parent-local
credit. They are useful because they specify the information boundary.

## Existing pattern

| Boundary | Declared content/responsibility |
| --- | --- |
| Strategy to web-search | Selected search task and scoped Goal artifact identities, through a closed ParentRequest |
| Web-search's local loop | Page candidates, selected work and measured prior Page results |
| Web-search to strategy | Accepted logical identities by channel, declared measurements/flags and evidence artifact identities |
| Strategy receives result | Correlate the request and child result; recompute the strategy's own identity vector |

The library declares that raw search prose, prompts, page bodies and model
rationales do not become the upward result. A `HandoffPayloadContract` names the
allowed artifact roles, measurements, states and flags; arbitrary extra fields
are not an alternate instruction channel.

## Apply the information principle to refinement

Suppose an implementer is repairing a schema decoder. Its local context needs
actual malformed cases, attempted patches, exact observations and applicable
lessons. The Designer usually needs a narrower report:

- Candidate/change identities and the local measure that was applied.
- Which required decoding behaviors now hold, which failed, and which remain
  unknown or stale after the edit.
- Preservation effects on downstream consumers.
- Exact evidence handles and any design/measure decision required.

“Decoder fixed; all tests pass” is inadequate. A concise typed determination
with the actual candidate, check and original observation identities allows the
Designer to invoke its independent acceptance without reading every attempt.

If the same decoder evidence travels through two children, its original identity
must survive both reports. The parent must not count the echoes as independent
confirmation. If downstream results used an older decoder version, their previous
passes must be reconsidered under the dependency rules.

## Transfer limits

The existing search boundary is not evidence that staged Designer calls, Parts
recursion, source editing or cross-level repair-cycle reporting are already
implemented. Those require the refiner's exact approved contracts and runtime
support. Reuse the closed-projection principle and existing mechanisms where they
fit; do not import an unrelated search topology or make a new handoff registry.
