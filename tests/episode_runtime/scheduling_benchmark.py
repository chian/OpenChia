"""A checkable resource-constrained scheduling task; no model answers here."""

import math


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
