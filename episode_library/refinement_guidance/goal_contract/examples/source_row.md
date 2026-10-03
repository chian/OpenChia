# Source-grounded rows are more than valid JSON

Illustrative, unexecuted fixture. The existing lexical-probe/source-table library
provides exact-span, declared-field and typed-return patterns; it does not supply
a receipt for this particular example.

## Task and answer

Source artifact S contains exactly:

```text
Site Alder: sample count 12; failures 2.
Site Birch: sample count 8; failure count not reported.
```

The task requires one row for each explicitly named site, reported sample counts,
reported failure counts when present, and exact evidence spans. Missing failure
counts remain absent; they are not zero and cannot be borrowed from another site.

The supported rows are Alder `(sample_count=12, failures=2)` and Birch
`(sample_count=8, failures=absent)`. Each value links to the relevant span in S.
This mathematical/value projection is distinct from the library's exact string
extraction: any string-to-integer conversion needs its own declared normalization.

## Good design and separate judgments

| Boundary | What it establishes |
| --- | --- |
| Admission | Only declared fields; each asserted source string exists in S; required site identity is complete |
| Local implementation measure | Given this frozen fixture, both expected identities and their attributed values match; unreported values stay absent |
| Parent acceptance | Independently specified fixtures exercise multiple sites, repeated numbers, absent fields and changed ordering; no cross-subject mixing or invented value |
| Whole result | Required rows and evidence are returned through the typed result on the same source/check revision |

The measures must inspect subject attribution, not only substring membership.
The string `2` is present in S, but attaching it as Birch's failure count is wrong.
A valid JSON object with no rows also fails the requirement to return the two sites.

## Candidate repair and credit

Suppose a candidate copies Alder's `2` into Birch's missing field. A scoped coding
assignment can repair field-to-site attribution and rerun its fixed local checks.
Deleting Birch entirely or changing the expected answer is not a repair.

A newly admitted behavioral milestone may count under the assignment's measure.
Re-emitting the same rows under fresh IDs does not. A raw failed extraction earns
no learning credit; a lesson needs evidence and a scoped future decision it changes.

This fixture is not a general language-understanding oracle. Arbitrary ambiguous
tables, units and source claims may need separately grounded interpretation. Exact
spans prove what was written, not that the real-world source claim is true.
