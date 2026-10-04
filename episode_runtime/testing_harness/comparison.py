"""Compare committed requirement outcomes without widening their claims."""

from agent.duet_contracts import canonical_json

from .measurements import saved_measurements
from ..records.experiments import read_record


def _read(artifacts, experiment_id):
    row = read_record(artifacts, "dispatch", experiment_id=experiment_id)
    if row is None:
        raise ValueError("comparison requires an exact committed experiment dispatch")
    return row, saved_measurements(artifacts, experiment_id)


def compare_experiments(artifacts, before_id, after_id):
    """Differences are inspectable even when they prohibit a regression claim."""
    before, left = _read(artifacts, before_id)
    after, right = _read(artifacts, after_id)
    if before["duet_id"] != after["duet_id"]:
        raise ValueError("comparison requires experiments owned by the same Duet")
    if left is None or right is None:
        return {
            "before_experiment_id": before_id,
            "after_experiment_id": after_id,
            "comparison_status": "unavailable",
            "reason": "Both experiments need committed requirement measurements; execution status or numerical agreement alone is not candidate acceptance.",
        }
    left_spec, right_spec = before["record"]["spec"], after["record"]["spec"]
    differences = [
        name
        for name in ("scope", "boundary", "mode", "environment_ref", "launch_ref")
        if canonical_json(left_spec[name]) != canonical_json(right_spec[name])
    ]
    inputs = []
    for row in (before, after):
        launch = dict(row["record"]["registration"]["launch_request"])
        launch.pop("request_id")
        inputs.append(launch)
    if canonical_json(inputs[0]) != canonical_json(inputs[1]):
        differences.append("launch_inputs")
    left_outcomes = {
        canonical_json(row["requirement_ref"]): row for row in left["outcomes"]
    }
    right_outcomes = {
        canonical_json(row["requirement_ref"]): row for row in right["outcomes"]
    }
    outcomes = []
    for key in sorted(left_outcomes.keys() | right_outcomes.keys()):
        old, new = left_outcomes.get(key), right_outcomes.get(key)
        reasons = list(differences)
        if old is None or new is None:
            reasons.append("requirement_not_measured_in_both")
        elif old["measure_ref"] != new["measure_ref"]:
            reasons.append("different_measure")
        elif old["status"] not in {"pass", "fail"} or new["status"] not in {
            "pass",
            "fail",
        }:
            reasons.append("non_decisive_measurement")
        comparable = not reasons
        outcomes.append({
            "requirement_ref": (old if old is not None else new)["requirement_ref"],
            "before": old,
            "after": new,
            "comparable": comparable,
            "limitations": reasons,
            "regression": comparable
            and old["status"] == "pass"
            and new["status"] == "fail",
            "resolved_failure": comparable
            and old["status"] == "fail"
            and new["status"] == "pass",
        })
    return {
        "schema_version": 1,
        "comparison_status": "compared",
        "before_experiment_id": before_id,
        "after_experiment_id": after_id,
        "before_measurement_ref": left["measurement_ref"],
        "after_measurement_ref": right["measurement_ref"],
        "before_candidate_ref": left_spec["candidate_ref"],
        "after_candidate_ref": right_spec["candidate_ref"],
        "context_differences": differences,
        "outcomes": outcomes,
        "progress": {"admitted": False},
        "acceptance": {"admitted": False},
        "limitations": [
            "These are differences between exact measurements, not a causal attribution to a code change.",
            "A missing or incompatible measurement cannot establish a regression or a repair.",
        ],
    }
