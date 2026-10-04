"""Use the Builder's static requirements in the common refinement measures.

These are checks and measurements, not another execution or replay service.
Runtime behavior remains a separate evidence kind under the parent's measure.
"""

from function_library.materialization_progress import (
    REQUIREMENT_SATISFACTION,
    requirement_satisfaction,
)

from .records import Ref, RefinementRecord


def initial_checks(
    store,
    *,
    duet_id,
    campaign_id,
    authority_ref,
    environment_ref,
    handoff,
    handoff_ref,
    local_measure_ref,
    acceptance_measure_ref,
):
    """Propose fixed Builder checks before the campaign contract is admitted."""
    definitions = {row["definition_id"]: row for row in handoff["check_definitions"]}
    predicates = {}
    for identifier, definition in definitions.items():
        predicates[identifier] = store.put_data(
            duet_id,
            "predicate",
            {
                **{
                    key: definition[key]
                    for key in ("library", "function_id", "interface", "definition_id")
                },
                "arguments": {},
            },
        )
    checks = []
    for purpose, measure in (
        ("local", local_measure_ref),
        ("acceptance", acceptance_measure_ref),
        ("composition", acceptance_measure_ref),
    ):
        for check in handoff["checks"]:
            checks.append(
                RefinementRecord(
                    "check",
                    campaign_id,
                    {
                        "requirement_key": check["requirement_id"],
                        "evidence_kind": "materialization",
                        "origin_refs": [handoff_ref.as_record()],
                        "measure_ref": measure.as_record(),
                        "purpose": purpose,
                        "predicate_ref": predicates[check["definition_id"]].as_record(),
                        "expected": {"check_id": check["check_id"]},
                        # The registered check binds an exact whole candidate. This is
                        # conservative invalidation, not a guess about dependency safety.
                        "dependency_paths": None,
                        "environment_ref": environment_ref.as_record(),
                        "mandatory": True,
                        "guard_keys": [],
                        "grounding_refs": [handoff_ref.as_record()],
                        "observation_path": "/status",
                    },
                    authority_ref,
                )
            )
    with store.duet_store.transaction() as connection:
        for check in checks:
            store._put(connection, duet_id, check)
    return tuple(checks)


def baseline(view):
    catalog = view.data(Ref.from_record(view.contract.body["requirement_catalog_ref"]))
    handoff = view.data(Ref.from_record(catalog["materialization_handoff_ref"]))
    if (
        handoff["progress_definition"]["definition_id"]
        != REQUIREMENT_SATISFACTION.definition_id
    ):
        raise ValueError("materialization measurement differs from the frozen handoff")
    return handoff


def baseline_fact_keys(view, assignment):
    from .judgment import verification_fact
    from .measurement import check_fact

    progress = baseline(view)["progress"]
    if assignment.body["role"] == "verify":
        outcomes = progress["check_statuses"]
        return {
            verification_fact(view, check, outcomes[check.body["expected"]["check_id"]])
            for entry in view.entries("check")
            for check in (entry.record,)
            if check.body["evidence_kind"] == "materialization"
            and check.body["measure_ref"] == assignment.body["local_measure_ref"]
            and outcomes.get(check.body["expected"]["check_id"]) in {"pass", "fail"}
        }
    known = set(progress["credited_requirement_ids"])
    return {
        check_fact(view, entry.record)
        for entry in view.entries("check")
        if entry.record.body["evidence_kind"] == "materialization"
        and entry.record.body["requirement_key"] in known
        and entry.record.body["measure_ref"] == assignment.body["local_measure_ref"]
    }


def satisfied_requirements(view, assignment, assessments=()):
    """One requirement needs all its frozen checks, not one favorable result."""
    from .judgment import current_check_states

    handoff = baseline(view)
    requirements = [
        row
        for row in handoff["requirements"]
        if row["requirement_id"] in assignment.body["contribution_requirement_keys"]
    ]
    declared = {key for row in requirements for key in row["check_ids"]}
    checks = {row.key: row.record for row in view.entries("check")}
    observations = []
    for key, (record, status) in current_check_states(view, assessments).items():
        check = checks[key]
        if (
            check.body["evidence_kind"] != "materialization"
            or check.body["measure_ref"] != assignment.body["local_measure_ref"]
            or check.body["expected"]["check_id"] not in declared
        ):
            continue
        if status not in {
            "pass",
            "fail",
            "blocked",
            "error",
        }:
            continue
        observations.append({
            "check_id": check.body["expected"]["check_id"],
            "candidate_ref": view.candidate.ref.as_record(),
            "status": status,
        })
    return set(
        requirement_satisfaction(
            requirements=requirements,
            observations=observations,
            candidate_ref=view.candidate.ref.as_record(),
            credited_requirement_ids=handoff["progress"]["credited_requirement_ids"],
        )["current_satisfied_requirement_ids"]
    )
