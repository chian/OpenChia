# Projected marginal-credit intervals

Credit assignment uses one normalization vector for both the current and
projected progress of a possible next unit. Rarefaction supplies the numeric
total and yield intervals; continuation compares the resulting upper credit
bound with the selected threshold.

For one coordinate, let `c` be the accepted count, `y` the projected next yield,
and `s = max(1, total, c + 1)` the normalization. Its current coordinate is
`c / s`, and its projected coordinate is `min(1, (c + y) / s)`. Marginal credit
is the product of projected coordinates minus the product of current ones.
An exactly empty coordinate retains the existing neutral value of one.

The upper bound maximizes this marginal difference over the supplied interval
box. It uses each yield's upper endpoint. For any one scale, with the other
coordinates fixed, write their projected product as `A` and current product
as `B`, with `A >= B >= 0`:

- While the coordinate is clipped, the difference is `A - c*B/s`, which is
  nondecreasing in `s`.
- After clipping ends, it is `((c+y)*A - c*B)/s`, which is nonincreasing in `s`.

Therefore each maximizing scale is `c + y`, clamped to the admitted scale
interval. These maxima can be selected independently across coordinates.
This retains every combination in the interval box, including combinations
that dependence between estimated totals and yields might rule out. It does
not claim tighter statistical coverage than the estimator supplies.

Subtracting a current value at one scale from a projected value at another
introduces a positive floor unrelated to possible new yield. Shared-scale
maximization makes identically zero next yield produce exactly zero marginal
credit, even when estimated total richness remains uncertain. The existing
conservative lower bound, point estimate, realized-credit normalization,
admission history, estimator, and continuation threshold are unchanged.

Behavior checks: `scripts/run_tests.sh
tests/numeric_control_library/test_credit_intervals.py` exercises zero-yield
invariance and an attainable multicolumn upper bound including an interior
clipping maximum and column permutation.
