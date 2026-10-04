"""One fixed scheduling benchmark and its independent host-side answer check.

The exhaustive solver sees only the problem, never the proposed answer. The
interval validator separately checks feasibility. Neither certifies the prose
explanation, which remains part of the observed evidence for human inspection.
"""

from collections.abc import Mapping
import json
import math
import re

from .epistemic_contract import exact


BENCHMARK_ID = "seven_job_resource_schedule_v1"


JOBS = {
    "A": {"duration": 3, "after": [], "laser": True},
    "B": {"duration": 4, "after": [], "laser": True},
    "C": {"duration": 2, "after": [], "laser": False},
    "D": {"duration": 5, "after": ["A"], "laser": False},
    "E": {"duration": 3, "after": ["B"], "laser": True},
    "F": {"duration": 2, "after": ["C", "D"], "laser": False},
    "G": {"duration": 4, "after": ["E"], "laser": False},
}

PROBLEM = (
    "Find a minimum-makespan schedule for the seven jobs below. Two identical workers "
    "are available from time 0. Each nonpreemptive job occupies one worker throughout "
    "its execution. There is one laser: laser jobs cannot overlap each other. "
    "A job starts only after every listed predecessor has finished. Start times are "
    "nonnegative integers. Touching endpoints do not overlap. Return fields.schedule "
    "as a JSON-encoded object mapping every job name to its integer start time, "
    "fields.makespan as the integer completion time written as text, and "
    "fields.optimality_argument explaining why a shorter schedule is impossible. "
    "The result must include a concrete feasible schedule, not merely a formulation "
    "of this task or a proposal to use a solver. Jobs: " + repr(JOBS)
)


def violations(starts):
    if not isinstance(starts, dict) or set(starts) != set(JOBS):
        return ["schedule must include each job exactly once"]
    if any(type(t) is not int or t < 0 for t in starts.values()):
        return ["start times must be nonnegative integers"]
    ends = {j: starts[j] + job["duration"] for j, job in JOBS.items()}
    errors = []
    for j, job in JOBS.items():
        if any(starts[j] < ends[p] for p in job["after"]):
            errors.append(f"precedence violation at {j}")
    for t in range(max(ends.values())):
        active = [j for j in JOBS if starts[j] <= t < ends[j]]
        if len(active) > 2:
            errors.append(f"worker capacity exceeded at {t}")
        if sum(JOBS[j]["laser"] for j in active) > 1:
            errors.append(f"laser overlap at {t}")
    return errors


def optimal_schedule():
    """Enumerate every integer start assignment within each candidate horizon.

    This verifier receives only JOBS, never a model response or rationale. The
    search uses a different representation from the interval-checking validator.
    """
    order = tuple(JOBS)  # topological order of this fixed benchmark
    total = sum(job["duration"] for job in JOBS.values())
    for horizon in range(math.ceil(total / 2), total + 1):
        workers, lasers, starts = [0] * horizon, [0] * horizon, {}

        def visit(index):
            if index == len(order):
                return dict(starts)
            name = order[index]
            job = JOBS[name]
            earliest = max(
                (starts[p] + JOBS[p]["duration"] for p in job["after"]), default=0
            )
            for start in range(earliest, horizon - job["duration"] + 1):
                slots = range(start, start + job["duration"])
                if any(workers[t] == 2 or (job["laser"] and lasers[t]) for t in slots):
                    continue
                starts[name] = start
                for t in slots:
                    workers[t] += 1
                    lasers[t] += int(job["laser"])
                answer = visit(index + 1)
                for t in slots:
                    workers[t] -= 1
                    lasers[t] -= int(job["laser"])
                del starts[name]
                if answer is not None:
                    return answer
            return None

        found = visit(0)
        if found is not None:
            return horizon, found
    raise AssertionError("serial execution must be feasible")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("schedule repeats a job key")
        result[key] = value
    return result


def check_optimal_schedule(*, observed, expected):
    """Accept every feasible optimal answer, not just the oracle's witness.

    Expected identifies the fixed problem, not a caller-supplied optimum. The
    measured fields match the reasoning Episode's string-valued result schema.
    Prose has no authority: a persuasive explanation cannot repair a bad answer,
    and changing only the explanation cannot invalidate a correct schedule.
    """
    expected = exact(expected, {"benchmark_id"}, "scheduling benchmark")
    if expected["benchmark_id"] != BENCHMARK_ID:
        raise ValueError("unknown scheduling benchmark")
    if not isinstance(observed, Mapping) or set(observed) != {
        "schedule", "makespan", "optimality_argument"
    }:
        return "fail"
    if any(not isinstance(value, str) for value in observed.values()):
        return "fail"
    if re.fullmatch(r"[0-9]+", observed["makespan"]) is None:
        return "fail"
    try:
        starts = json.loads(observed["schedule"], object_pairs_hook=_unique_object)
        claimed = int(observed["makespan"])
    except (ValueError, RecursionError):
        return "fail"
    if not isinstance(starts, dict) or set(starts) != set(JOBS):
        return "fail"
    optimum, _witness = optimal_schedule()
    # Bound validation by the known optimum, not an untrusted enormous time.
    if claimed != optimum or any(
        type(start) is not int or not 0 <= start <= optimum - JOBS[job]["duration"]
        for job, start in starts.items()
    ):
        return "fail"
    actual = max(starts[job] + value["duration"] for job, value in JOBS.items())
    return "pass" if actual == claimed and not violations(starts) else "fail"


def ground_requirement(*, workflow, requirement):
    """Ground only the exact approved problem, without examining a candidate.

    This source covers the schedule answer, not the remaining Episode contract.
    Different tasks need their own grounded instrument; substring matching or a
    model's assertion that two problems are equivalent would be insufficient.
    """
    from .epistemic_schemas import canonical
    from .refinement_checks import OPTIMAL_SCHEDULE

    if (
        requirement.get("evidence_scope") != "contract_coverage"
        or requirement.get("field") != "goal"
        or requirement.get("approved_value") != PROBLEM
        or len(workflow["episodes"]) != 1
    ):
        return None
    node = workflow["episodes"][0]
    if (
        node["local_id"] != requirement["local_id"]
        or node["workflow_parent_local_id"] is not None
        or node["contract"]["goal"] != PROBLEM
    ):
        return None
    epistemic = node["contract"].get("epistemic")
    environment = {
        "benchmark_id": BENCHMARK_ID,
        "lasers": 1,
        "preemptive": False,
        "time_domain": "nonnegative_integer",
        "workers": 2,
    }
    problem = {**environment, "jobs": JOBS}
    if (
        not epistemic
        or canonical(epistemic["environment"]) != canonical(environment)
        or not any(
            item["kind"] == "problem_specification"
            and canonical(item["observation"]) == canonical(problem)
            for item in epistemic["evidence"]
        )
    ):
        return None
    optimum, witness = optimal_schedule()

    def answer(starts, completion):
        return {
            "schedule": json.dumps(starts, sort_keys=True),
            "makespan": str(completion),
            "optimality_argument": "Control fixture; explanation is not a proof certificate.",
        }

    predicate = OPTIMAL_SCHEDULE.bind("entry").as_record()
    predicate.pop("name")
    return {
        "predicate": predicate,
        "expected": {"benchmark_id": BENCHMARK_ID},
        "observation_path": "/payload/typed_status/workflow_result/admitted_problem_frontier/0/fields",
        "positive_controls": [answer(witness, optimum)],
        "negative_controls": [
            answer({job: 0 for job in JOBS}, optimum),
            answer({job: start + 1 for job, start in witness.items()}, optimum + 1),
            {},
        ],
        "input_domain": problem,
        "observation_schema": {
            "schedule": "string",
            "makespan": "string",
            "optimality_argument": "string",
        },
        "independence": "Exhaustive solver receives only the approved problem, never the candidate answer.",
        "limitations": [
            "Covers feasibility and optimality for this exact integer-start problem only.",
            "Explanation text is retained, not certified as a mathematical proof.",
            "Does not establish the Episode's credit, continuation, capabilities or other contract fields.",
        ],
    }
