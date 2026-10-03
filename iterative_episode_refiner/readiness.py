"""Whole-build acceptance from the complete campaign, not bounded reports."""

from .coordination import ancestors, relevant_conflicts
from .judgment import current_check_states
from .measures import authorized_check_refs
from .records import Ref


def root_readiness(view, assignment, policy):
    if (
        assignment.body["role"] != "parts"
        or assignment.body["parent_assignment_ref"] is not None
    ):
        raise ValueError("whole-build readiness belongs to root Parts")
    catalog = view.data(Ref.from_record(view.contract.body["requirement_catalog_ref"]))
    requirements = {
        row["requirement_key"] for row in catalog["requirements"] if row["mandatory"]
    }
    gaps = []

    def gap(code, *, requirements=(), records=()):
        gaps.append({
            "code": code,
            "requirement_keys": sorted(requirements),
            "record_refs": [record.ref.as_record() for record in records],
        })

    missing = requirements - set(assignment.body["contribution_requirement_keys"])
    if missing or not requirements:
        gap("root_scope_incomplete", requirements=missing)
    authorized = {
        ref.artifact_id.value: view.read(ref, "check")
        for ref in authorized_check_refs(view, policy, assignment)
    }
    required = {
        key: check
        for key, check in authorized.items()
        if check.body["requirement_key"] in requirements
        and check.body["measure_ref"] == assignment.body["acceptance_measure_ref"]
        and check.body["purpose"] == "composition"
        and check.body["mandatory"]
    }
    missing = requirements - {
        check.body["requirement_key"] for check in required.values()
    }
    if missing:
        gap("acceptance_coverage_missing", requirements=missing)
    pending = list(required.values())
    while pending:
        check = pending.pop()
        for key in check.body["guard_keys"]:
            if key in required:
                continue
            guard = authorized.get(key)
            if guard is None:
                gap("guard_unavailable", records=(check,))
            else:
                required[key] = guard
                pending.append(guard)
    states = current_check_states(view)
    observations = {}
    for key, check in sorted(required.items()):
        state = states.get(key)
        if state is None or state[1] != "pass":
            gap(
                "acceptance_not_current_pass",
                requirements=(check.body["requirement_key"],),
                records=(check,),
            )
            continue
        observation = state[0]
        request = view.read(
            Ref.from_record(observation.body["request_ref"]), "evaluation"
        )
        verifier = view.entry("invocation", observation.invocation_id.value).record
        if (
            observation.kind != "observation"
            or not observation.evidence_refs
            or observation.body["outcome"] != "pass"
            or request.body["measure_ref"] != check.body["measure_ref"]
            or request.body["purpose"] != check.body["purpose"]
            or request.body["environment_ref"] != view.contract.body["environment_ref"]
            or verifier.body["role"] != "verify"
            or assignment.ref not in {item.ref for item in ancestors(view, verifier)}
        ):
            gap("independent_acceptance_missing", records=(check, observation))
            continue
        observations[key] = observation
    warnings = []
    for conflict in relevant_conflicts(view, assignment):
        if conflict.body["state"] == "decision_required":
            gap("unresolved_conflict", records=(conflict,))
            continue
        # A source revisit is a warning, not proof of oscillation. A suspected
        # local regression remains unresolved until its checks pass together.
        keys = {
            view.read(Ref.from_record(ref), "observation").body["check_key"]
            for ref in conflict.body["observation_refs"]
        }
        if conflict.body["kind"] != "exact_revisit" and (
            not keys
            or any(key not in states or states[key][1] != "pass" for key in keys)
        ):
            gap("unresolved_conflict", records=(conflict,))
        else:
            warnings.append(conflict.ref.as_record())
    for row in view.entries("invocation"):
        if row.record.ref != assignment.ref and row.status in {
            "active",
            "waiting",
            "needs_parent_decision",
        }:
            gap("child_not_returned", records=(row.record,))
    from .instrument_builds import is_primary_source

    sources = [
        row.record
        for row in view.entries("evaluation_source")
        if row.status == "admitted"
        and row.record.body["candidate_ref"] == view.candidate.ref.as_record()
        and is_primary_source(view, row.record)
    ]
    if not sources:
        gap("current_source_not_admitted")
    return {
        "mandatory_requirement_keys": sorted(requirements),
        "check_refs": [check.ref.as_record() for _, check in sorted(required.items())],
        "observation_refs": [
            record.ref.as_record() for _, record in sorted(observations.items())
        ],
        "source_admission_ref": sources[-1].ref.as_record() if sources else None,
        "retained_warning_refs": warnings,
        "gaps": gaps,
    }
