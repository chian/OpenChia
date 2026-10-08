"""Use the Builder's static requirements in the common refinement measures.

These are checks and measurements, not another execution or replay service.
Runtime behavior remains a separate evidence kind under the parent's measure.
"""

from function_library.materialization_progress import (
    REQUIREMENT_SATISFACTION,
)
from function_library.refinement_contract import ROLE_SPECIALIZATION

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
    from .measures import selected_checks, selected_measure_ref

    progress = baseline(view)["progress"]
    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    reference = selected_measure_ref(view, assignment, "local_measure_ref")
    checks = selected_checks(view, policy, assignment, reference)
    family = ROLE_SPECIALIZATION[assignment.body["role"]]
    if family == "verify":
        outcomes = progress["check_statuses"]
        return {
            verification_fact(view, check, outcomes[check.body["expected"]["check_id"]])
            for check in checks
            if check.body["evidence_kind"] == "materialization"
            and outcomes.get(check.body["expected"]["check_id"]) in {"pass", "fail"}
        }
    if family not in {"designer", "implementer", "materialization_implementer"}:
        return set()
    from .measurement import dependency_hashes
    from .measures import measure_function, measurement_baseline, requirement_fact

    candidate = measurement_baseline(view, assignment, reference)
    function = measure_function(view, policy, assignment, reference, purpose="local")
    members = {check.artifact_id.value: check for check in checks if check.body["purpose"] == "local"}
    initial = next(entry.record for entry in view.entries("assignment")
                   if entry.record.body["parent_assignment_ref"] is None)
    initial_candidate = view.read(Ref.from_record(initial.body["baseline_candidate_ref"]), "candidate")
    policy_refs = {Ref.from_record(raw) for raw in policy["check_refs"]}
    outcomes = {key: set() for key in members}
    for key, check in members.items():
        if (check.ref in policy_refs and check.body["evidence_kind"] == "materialization"
                and dependency_hashes(check, initial_candidate) == dependency_hashes(check, candidate)):
            status = progress["check_statuses"].get(check.body["expected"]["check_id"])
            if status is not None:
                outcomes[key].add(status)
    # Evidence collected under the new function at the commissioned candidate
    # is baseline achievement, including when that evaluation happens after
    # publication. Rewording/replacing a checker cannot earn implementation credit.
    for entry in view.entries("observation"):
        observation = entry.record
        key = observation.body["check_key"]
        if (key not in members or not observation.evidence_refs
                or dependency_hashes(members[key], candidate) != dict(observation.body["checked_dependency_hashes"])):
            continue
        status = observation.body["outcome"]
        outcomes[key].add(status if status in {"pass", "fail", "blocked", "error"} else "not_checked")
    statuses = {key: next(iter(values)) if len(values) == 1 else "not_checked"
                for key, values in outcomes.items()}
    measured = function(
        observations=[{
            "check_id": key, "candidate_ref": candidate.ref.as_record(),
            "status": "blocked" if statuses[key] == "pass" and any(
                statuses.get(guard) != "pass" for guard in check.body["guard_keys"]
            ) else statuses[key],
        } for key, check in members.items()],
        candidate_ref=candidate.ref.as_record(),
        requirement_ids=assignment.body["contribution_requirement_keys"],
    )
    return {requirement_fact(view, reference, key)
            for key in measured["current_satisfied_requirement_ids"]}
