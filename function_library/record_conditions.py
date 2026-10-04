"""Pure, typed conditions over an observed record; no executable model code.

This predicate compares actual fields and relationships without requiring an
exact copy of variable Run identifiers, timestamps or model output. It never
creates an observation. Missing data stays inconclusive, including under NOT.
"""

from collections.abc import Mapping

from .epistemic_contract import exact
from .epistemic_schemas import canonical


CONDITION_LANGUAGE = {
    "version": 1,
    "operands": {
        "literal": "Any finite JSON value, e.g. {literal: 0}.",
        "path": "JSON pointer relative to the current record, e.g. {path: /kind}.",
        "root_path": "JSON pointer relative to the original observed record.",
        "parent_path": "JSON pointer relative to the record enclosing the current some/every member. In nested quantifiers this names the outer member, allowing exact event-ID or ordinal joins. Unavailable outside a quantifier.",
    },
    "conditions": {
        "equal": "{op: equal, left: operand, right: operand}; exact JSON types.",
        "less_equal": "{op: less_equal, left: operand, right: operand}; numbers only, not booleans.",
        "type": "{op: type, value: operand, expected: object|array|string|number|integer|boolean|null}.",
        "all": "{op: all, conditions: [condition, ...]}; nonempty conjunction.",
        "any": "{op: any, conditions: [condition, ...]}; nonempty disjunction.",
        "not": "{op: not, condition: condition}; missing data stays inconclusive.",
        "some": "{op: some, value: operand, condition: condition}; at least one array member satisfies condition. Member becomes current record; root_path is unchanged.",
        "every": "{op: every, value: operand, condition: condition}; all array members satisfy condition. Empty arrays pass; pair with some when presence matters.",
        "predicate": "{op: predicate, value: operand, selection: exact registered refinement.predicate selection, expected: frozen expected value}; delegates an existing predicate, not another record_conditions_v1.",
    },
    "limitations": [
        "Conditions establish only the selected recorded facts, not unobserved branches or a model's private reasoning.",
        "A committed worker or model claim is not host certification of that claim.",
        "Controls are observed-record examples passed through this same predicate; they do not create live Run evidence or implement a new projector.",
        "Paths must exist in the supplied observation. A prose observation_schema cannot add fields or executable behavior.",
    ],
}

_FIELDS = {
    "equal": {"op", "left", "right"},
    "less_equal": {"op", "left", "right"},
    "type": {"op", "value", "expected"},
    "all": {"op", "conditions"},
    "any": {"op", "conditions"},
    "not": {"op", "condition"},
    "some": {"op", "value", "condition"},
    "every": {"op", "value", "condition"},
    "predicate": {"op", "value", "selection", "expected"},
}
_TYPES = {
    "object": lambda value: isinstance(value, Mapping),
    "array": lambda value: isinstance(value, (list, tuple)),
    "string": lambda value: isinstance(value, str),
    "number": lambda value: type(value) in (int, float),
    "integer": lambda value: type(value) is int,
    "boolean": lambda value: type(value) is bool,
    "null": lambda value: value is None,
}
_MISSING = object()


def validate_condition(condition, *, depth=0):
    from iterative_episode_refiner.records import pointer_parts

    if depth > 32:
        raise ValueError("record condition nesting exceeds the format limit")
    if not isinstance(condition, Mapping) or condition.get("op") not in _FIELDS:
        raise ValueError("unknown record condition operation")
    exact(condition, _FIELDS[condition["op"]], "record condition")
    for key in ("left", "right", "value"):
        if key not in condition:
            continue
        operand = condition[key]
        if not isinstance(operand, Mapping) or len(operand) != 1:
            raise ValueError("record operand needs exactly one literal/path/root_path/parent_path")
        source = next(iter(operand))
        if source not in {"literal", "path", "root_path", "parent_path"}:
            raise ValueError("unknown record operand source")
        if source != "literal":
            pointer_parts(operand[source])
        canonical(operand)
    if "conditions" in condition:
        children = condition["conditions"]
        if not isinstance(children, (list, tuple)) or not children:
            raise ValueError("record conjunction/disjunction cannot be empty")
        for child in children:
            validate_condition(child, depth=depth + 1)
    if "condition" in condition:
        validate_condition(condition["condition"], depth=depth + 1)
    if condition["op"] == "type" and condition["expected"] not in _TYPES:
        raise ValueError("unknown JSON record type")
    if condition["op"] == "predicate":
        from .refinement_checks import resolve_predicate

        selection = condition["selection"]
        if selection["interface"] != "refinement.predicate" or selection["function_id"] == "record_conditions_v1":
            raise ValueError("record predicate must delegate a nonrecursive observation predicate")
        resolve_predicate(selection)
        canonical(condition["expected"])


def _operand(specification, current, root, parent):
    from iterative_episode_refiner.records import project

    if "literal" in specification:
        return specification["literal"]
    source = next(iter(specification))
    record = {"path": current, "root_path": root, "parent_path": parent}[source]
    if record is _MISSING:
        return _MISSING
    try:
        return project(record, specification[source])
    except (KeyError, IndexError, TypeError, ValueError):
        return _MISSING


def _combine(values, *, conjunction):
    values = tuple(values)
    decisive = False if conjunction else True
    if decisive in values:
        return decisive
    return None if None in values else not decisive


def _comparison(condition, current, root, parent):
    left, right = (_operand(condition[key], current, root, parent) for key in ("left", "right"))
    if left is _MISSING or right is _MISSING:
        return None
    if condition["op"] == "equal":
        return canonical(left) == canonical(right)
    if type(left) not in (int, float) or type(right) not in (int, float):
        return False
    return left <= right


def _type(condition, current, root, parent):
    value = _operand(condition["value"], current, root, parent)
    return None if value is _MISSING else _TYPES[condition["expected"]](value)


def _logical(condition, current, root, parent):
    return _combine(
        (_evaluate(child, current, root, parent) for child in condition["conditions"]),
        conjunction=condition["op"] == "all",
    )


def _not(condition, current, root, parent):
    value = _evaluate(condition["condition"], current, root, parent)
    return None if value is None else not value


def _quantified(condition, current, root, parent):
    values = _operand(condition["value"], current, root, parent)
    if values is _MISSING:
        return None
    if not isinstance(values, (list, tuple)):
        return False
    return _combine(
        (_evaluate(condition["condition"], item, root, current) for item in values),
        conjunction=condition["op"] == "every",
    )


def _predicate(condition, current, root, parent):
    from .refinement_checks import resolve_predicate

    value = _operand(condition["value"], current, root, parent)
    if value is _MISSING:
        return None
    verdict = resolve_predicate(condition["selection"])(observed=value, expected=condition["expected"])
    if verdict not in {"pass", "fail", "inconclusive"}:
        raise ValueError("delegated record predicate returned an invalid outcome")
    return {"pass": True, "fail": False, "inconclusive": None}[verdict]


_OPERATIONS = {
    "equal": _comparison,
    "less_equal": _comparison,
    "type": _type,
    "all": _logical,
    "any": _logical,
    "not": _not,
    "some": _quantified,
    "every": _quantified,
    "predicate": _predicate,
}


def _evaluate(condition, current, root, parent=_MISSING):
    return _OPERATIONS[condition["op"]](condition, current, root, parent)


def record_conditions(*, observed, expected):
    validate_condition(expected)
    canonical(observed)
    result = _evaluate(expected, observed, observed)
    return "inconclusive" if result is None else "pass" if result else "fail"
