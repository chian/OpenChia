"""The common registered predicate boundary for tests and refinement checks."""

from function_library.refinement_checks import resolve_predicate


def judge_value(selection, *, observed, expected):
    if selection["interface"] != "refinement.predicate":
        raise ValueError(
            "typed observations require a registered observation predicate"
        )
    try:
        predicate = resolve_predicate(selection)
    except KeyError as exc:
        raise ValueError("unknown registered observation predicate") from exc
    outcome = predicate(observed=observed, expected=expected)
    if outcome not in {"pass", "fail", "inconclusive"}:
        raise ValueError("registered predicate returned an invalid outcome")
    return outcome


def check_controls(selection, *, expected, positive, negative):
    if not positive or not negative:
        raise ValueError("a measure needs both satisfactory and violating controls")
    results = []
    for outcome, controls in (("pass", positive), ("fail", negative)):
        for value in controls:
            actual = judge_value(selection, observed=value, expected=expected)
            results.append({
                "input": value,
                "expected_outcome": outcome,
                "observed_outcome": actual,
            })
            if actual != outcome:
                raise ValueError(
                    f"measure fails its declared {outcome} control: returned {actual}"
                )
    return results
