"""Measure materialization requirements from persisted, host-admitted checks.

The caller owns the requirement set and evidence admission. This pure function
measures those admitted facts; it does not validate code, mint evidence, choose
repairs, or decide when refinement stops. A Refiner imports its initial baseline
by seeding credited IDs with that baseline's satisfied IDs before measuring its
own work. The baseline's achievement is not fresh refinement progress.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .models import FunctionImplementation, LibraryFunction
from .registry import FunctionLibrary


_STATUSES = ("pass", "fail", "blocked", "not_checked", "error")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be nonempty text")
    return value


def _sequence(value: object, name: str) -> Sequence:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} must be a sequence")
    return value


def _ids(values: object, name: str) -> set[str]:
    return {_text(value, name) for value in _sequence(values, name)}


def _candidate_identity(value: object) -> tuple[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("candidate_ref must be an artifact reference")
    return (
        _text(value.get("artifact_id"), "candidate artifact_id"),
        _text(value.get("content_hash"), "candidate content_hash"),
    )


def _requirements_by_id(requirements: object) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for record in _sequence(requirements, "requirements"):
        if not isinstance(record, Mapping):
            raise ValueError("requirements must contain records")
        requirement_id = _text(record.get("requirement_id"), "requirement_id")
        if not isinstance(record.get("mandatory"), bool):
            raise ValueError(f"requirement {requirement_id!r} needs mandatory boolean")
        declaration = dict(record)
        declaration["check_ids"] = sorted(
            _ids(record.get("check_ids"), "requirement check_ids")
        )
        if requirement_id in indexed and indexed[requirement_id] != declaration:
            raise ValueError(f"conflicting requirement declarations: {requirement_id}")
        indexed[requirement_id] = declaration
    return indexed


def _check_outcomes(
    observations: object,
    check_ids: set[str],
    candidate_identity: tuple[str, str],
) -> dict[str, str]:
    fresh: dict[str, str] = {}
    for record in _sequence(observations, "observations"):
        if not isinstance(record, Mapping):
            raise ValueError("observations must contain records")
        check_id = _text(record.get("check_id"), "check_id")
        if check_id not in check_ids:
            raise ValueError(f"observation references undeclared check: {check_id}")
        status = record.get("status")
        if status not in _STATUSES:
            raise ValueError(f"invalid status for check {check_id!r}: {status!r}")
        if _candidate_identity(record.get("candidate_ref")) != candidate_identity:
            continue
        if check_id in fresh and fresh[check_id] != status:
            raise ValueError(f"conflicting fresh outcomes for check: {check_id}")
        fresh[check_id] = status
    return {check_id: fresh.get(check_id, "not_checked") for check_id in sorted(check_ids)}


def _requirement_status(statuses: Sequence[str]) -> str:
    if not statuses:
        return "not_checked"
    # A failing/error check remains visible even if another prerequisite is
    # missing. The individual check outcomes always accompany this summary.
    return next(
        status
        for status in ("error", "fail", "blocked", "not_checked", "pass")
        if status in statuses
    )


def _counts(statuses: Sequence[str]) -> dict[str, int]:
    return {status: statuses.count(status) for status in _STATUSES}


def requirement_satisfaction(
    *,
    requirements: Sequence[Mapping[str, object]],
    observations: Sequence[Mapping[str, object]],
    candidate_ref: Mapping[str, str],
    credited_requirement_ids: Sequence[str] = (),
    previous_satisfied_requirement_ids: Sequence[str] = (),
) -> dict[str, object]:
    """Count distinct satisfied requirements, separately from first-time yield.

    A requirement earns one unit exactly when its nonempty check set is wholly
    passing for this exact candidate. Check IDs name distinct obligations, not
    messages or executions. Repeated identical outcomes have no effect;
    contradictory fresh outcomes raise rather than selecting a winner.

    Persist ``credited_requirement_ids`` across attempts to prevent restored
    passes from earning new credit. Pass the immediately preceding candidate's
    satisfied IDs separately to expose regressions, including removed IDs.
    """

    identity = _candidate_identity(candidate_ref)
    indexed = _requirements_by_id(requirements)
    admitted_check_ids = {
        check_id for record in indexed.values() for check_id in record["check_ids"]
    }
    check_statuses = _check_outcomes(observations, admitted_check_ids, identity)
    requirement_statuses = {
        requirement_id: _requirement_status(
            [check_statuses[check_id] for check_id in indexed[requirement_id]["check_ids"]]
        )
        for requirement_id in sorted(indexed)
    }
    satisfied = {
        requirement_id
        for requirement_id, status in requirement_statuses.items()
        if status == "pass"
    }
    credited = _ids(credited_requirement_ids, "credited_requirement_ids")
    previous = _ids(
        previous_satisfied_requirement_ids, "previous_satisfied_requirement_ids"
    )
    newly_satisfied = satisfied - credited
    mandatory = {
        requirement_id
        for requirement_id, record in indexed.items()
        if record["mandatory"]
    }
    mandatory_satisfied = mandatory & satisfied
    regressed = previous - satisfied
    return {
        "candidate_ref": {"artifact_id": identity[0], "content_hash": identity[1]},
        "requirement_total": len(indexed),
        "check_total": len(admitted_check_ids),
        "check_statuses": check_statuses,
        "check_status_counts": _counts(list(check_statuses.values())),
        "requirement_statuses": requirement_statuses,
        "requirement_status_counts": _counts(list(requirement_statuses.values())),
        "current_satisfied_requirement_ids": sorted(satisfied),
        "current_satisfied_count": len(satisfied),
        "newly_satisfied_requirement_ids": sorted(newly_satisfied),
        "newly_satisfied_count": len(newly_satisfied),
        "regressed_requirement_ids": sorted(regressed),
        "regressed_count": len(regressed),
        "credited_requirement_ids": sorted(credited | satisfied),
        "mandatory_total": len(mandatory),
        "mandatory_satisfied": len(mandatory_satisfied),
        "attained": bool(mandatory) and mandatory_satisfied == mandatory,
    }


materialization_progress_library = FunctionLibrary()

REQUIREMENT_SATISFACTION = materialization_progress_library.register(
    LibraryFunction(
        library="materialization",
        function_id="requirement_satisfaction",
        interface="materialization.requirement_satisfaction",
        description=(
            "Count distinct materialization requirements satisfied by exact-candidate "
            "host-admitted check outcomes; separate current achievement, new credit, "
            "and regressions."
        ),
        implementation=FunctionImplementation(
            module="function_library.materialization_progress",
            symbol="requirement_satisfaction",
            is_async=False,
        ),
        input_type=(
            "Keyword inputs: requirements, observations, candidate_ref, "
            "credited_requirement_ids, previous_satisfied_requirement_ids"
        ),
        output_type="JSON record of requirement satisfaction, first-time credit, and regressions",
        effect="Pure measurement over host-admitted persisted facts; grants no evidence authority.",
        failure_contract=(
            "Reject malformed inputs, unknown observation check IDs, conflicting "
            "requirement declarations, and contradictory fresh outcomes. Stale "
            "observations and missing checks grant no satisfaction."
        ),
        provenance={
            "authority": "Caller supplies the approved requirements and admitted check outcomes.",
            "baseline": (
                "Seed credited_requirement_ids from the imported baseline's satisfied "
                "requirements before crediting refinement work."
            ),
        },
    )
)


__all__ = [
    "REQUIREMENT_SATISFACTION",
    "materialization_progress_library",
    "requirement_satisfaction",
]
