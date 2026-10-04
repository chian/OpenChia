# Define quantities before calculating

A calculation design starts with the quantity the task asks for, not a convenient
formula or a numeric-looking output field. This is guidance for the reusable
Designer, not a separate calculation runtime class.

## Establish the numeric contract

State the input domain, units, identity/grain of each observation, aggregation
rule, precision and rounding point. Define missing/invalid data and degenerate
cases explicitly. An absent value is not automatically zero; an undefined ratio
is not automatically a valid zero result.

Choose exact integers, rational numbers or decimal arithmetic where the task
requires exactness. If approximation is necessary, bind absolute/relative error
criteria to the quantity and domain before implementation. Do not choose a
tolerance after seeing a candidate's error.

## Design discriminating local measures

Use independently grounded small cases and relations that expose common mistakes:

- Different denominators distinguish a pooled rate from an unweighted mean.
- Equivalent units distinguish correct conversion from raw-number aggregation.
- Reordering independent inputs must not change a commutative aggregate.
- Splitting and recombining one group must preserve its aggregate when the task
  semantics permit that operation.
- Zero denominators, out-of-domain counts and missing inputs must take the
  declared path, not silently produce an attractive number.

Metamorphic relations are useful guards, not sufficient acceptance by themselves:
a constant function can be order-invariant and still be completely wrong.
Anchor them with exact examples or an independently admitted reference.

## Keep local progress and acceptance distinct

The coder's local measure can expose a wrong reduction, rounding point or input
case under the fixed contract. The parent separately examines the exact produced
behavior over the required domain, protected cases and declared output semantics.
Passing a single easy arithmetic example is not generic correctness.

The repeated unit must reflect real work: a candidate implementation change and
measurement, or an actual declared calculation opportunity. A deterministic
calculation that is already correct does not need invented reasoning turns.

If input independence, unit interpretation or the intended aggregation is unknown,
return that specific question. Do not turn a disputed task definition into a
coding choice. Changing the intended quantity requires an authorized interpretation
or successor assignment, not a local check edit.
