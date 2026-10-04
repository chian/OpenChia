"""Parent-owned meanings for support/question observations.

The model selects an observation, not its conclusion or decision effect. These
projections use the common check/evidence state; there is no second ledger,
execution service, or free-text finding admission path.
"""

from agent.duet_contracts import content_id
from function_library.epistemic_contract import exact, names

from .records import Ref


_STATES = {
    "question": {"supported", "refuted", "unresolved"},
    "support": {"applicable", "inapplicable", "unresolved"},
}
_RESOLVED = {"question": {"supported", "refuted"}, "support": {"applicable"}}


def needs(view, policy, assignment):
    """Read only exact needs already authorized by the frozen campaign policy."""
    from .measures import authorized_check_refs

    role = assignment.body["role"]
    if role not in _STATES:
        return ()
    authorized = set(authorized_check_refs(view, policy, assignment))
    selected = []
    seen = set()
    for value in policy.get("investigation_need_refs", ()):
        reference = Ref.from_record(value)
        need = view.data(reference)
        exact(
            need,
            {
                "need_key",
                "role",
                "requirement_key",
                "measure_ref",
                "check_ref",
                "decision_ref",
                "target_ref",
                "applicability_ref",
                "limitation_refs",
                "outcomes",
            },
            "parent investigation need",
        )
        if (
            need["role"] != role
            or need["measure_ref"] != assignment.body["local_measure_ref"]
            or need["requirement_key"]
            not in assignment.body["contribution_requirement_keys"]
        ):
            continue
        names((need["need_key"],), "investigation need", nonempty=True)
        if need["need_key"] in seen:
            raise ValueError("one measure cannot repeat a named investigation need")
        seen.add(need["need_key"])
        check = view.read(Ref.from_record(need["check_ref"]), "check")
        if (
            check.ref not in authorized
            or check.body["measure_ref"] != need["measure_ref"]
            or check.body["requirement_key"] != need["requirement_key"]
            or check.body["purpose"] != role
            or not check.body["mandatory"]
            or check.body["evidence_kind"] != "execution"
            or check.body["environment_ref"] != view.contract.body["environment_ref"]
        ):
            raise ValueError("investigation need lacks its authorized behavioral check")
        exact(need["outcomes"], {"pass", "fail"}, "investigation outcome meanings")
        if any(state not in _STATES[role] for state in need["outcomes"].values()):
            raise ValueError(
                "investigation effect is outside the role's advisory scope"
            )
        for field in ("decision_ref", "target_ref", "applicability_ref"):
            view.data(Ref.from_record(need[field]))
        for ref in need["limitation_refs"]:
            view.data(Ref.from_record(ref))
        selected.append({"reference": reference.as_record(), "need": need})
    return tuple(selected)


def require_assignment(view, policy, assignment):
    if assignment.body["role"] not in _STATES:
        return
    from .measure_design import assigned_definition

    if assigned_definition(view, assignment) is not None:
        return
    assigned = needs(view, policy, assignment)
    if {item["need"]["requirement_key"] for item in assigned} != set(
        assignment.body["contribution_requirement_keys"]
    ):
        raise ValueError(
            "investigation needs parent-owned decision meanings for every contribution"
        )


def selected_checks(view, policy, assignment, keys):
    """An observation bundle includes its frozen guards, not model-picked ones."""
    from .measures import authorized_check_refs

    requested = set(names(keys, "investigation check selection", nonempty=True))
    available = {
        item["need"]["check_ref"]["artifact_id"]
        for item in needs(view, policy, assignment)
    }
    if not requested.issubset(available):
        raise ValueError("investigation selected a check outside its parent's needs")
    checks = {
        check.artifact_id.value: check
        for reference in authorized_check_refs(view, policy, assignment)
        for check in (view.read(reference, "check"),)
        if check.body["measure_ref"] == assignment.body["local_measure_ref"]
        and check.body["purpose"] == assignment.body["role"]
        and check.body["requirement_key"] in assignment.body["scope_requirement_keys"]
    }
    pending = list(requested)
    while pending:
        check = checks[pending.pop()]
        for guard in check.body["guard_keys"]:
            # A missing/out-of-scope guard remains on the check. The common
            # evaluation projection reports it; selection cannot invent it.
            if guard in checks and guard not in requested:
                requested.add(guard)
                pending.append(guard)
    return requested


def findings(view, assignment):
    """Typed current decision state, with unchanged original observation refs."""
    from .judgment import current_check_states, verification_fact

    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    states = current_check_states(view)
    results = []
    for item in needs(view, policy, assignment):
        need = item["need"]
        key = need["check_ref"]["artifact_id"]
        current = states.get(key)
        if current is None:
            continue
        observation, outcome = current
        source = view.entry("invocation", observation.invocation_id.value).record
        check = view.entry("check", key).record
        if (
            source.ref != assignment.ref
            or outcome not in {"pass", "fail"}
            or not observation.evidence_refs
            or any(
                guard not in states or states[guard][1] != "pass"
                for guard in check.body["guard_keys"]
            )
        ):
            continue
        request = view.read(
            Ref.from_record(observation.body["request_ref"]), "evaluation"
        )
        state = need["outcomes"][outcome]
        resolved = state in _RESOLVED[need["role"]]
        fact_key = content_id(
            "investigation_fact",
            {
                "need_key": need["need_key"],
                "decision_ref": need["decision_ref"],
                "criterion": verification_fact(view, check, outcome, request),
                "state": state,
            },
        ).value
        results.append({
            "need_ref": item["reference"],
            "need_key": need["need_key"],
            "role": need["role"],
            "requirement_key": need["requirement_key"],
            "owner_assignment_ref": assignment.body["parent_assignment_ref"],
            "assignment_ref": assignment.ref.as_record(),
            "decision_ref": need["decision_ref"],
            "target_ref": need["target_ref"],
            "state": state,
            "policy_strength": "advisory",
            "resolved": resolved,
            "candidate_ref": request.body["candidate_ref"],
            "measure_ref": need["measure_ref"],
            "environment_ref": check.body["environment_ref"],
            "checked_dependency_hashes": observation.body["checked_dependency_hashes"],
            "check_ref": check.ref.as_record(),
            "observation_ref": observation.ref.as_record(),
            "evidence_refs": [ref.as_record() for ref in observation.evidence_refs],
            "applicability_ref": need["applicability_ref"],
            "limitation_refs": need["limitation_refs"],
            "fact_key": fact_key if resolved else None,
        })
    return tuple(results)


def catalog(view, policy, assignment):
    """Compact authorized needs for this role and its permitted prerequisites."""
    roles = {assignment.body["role"], *assignment.body["allowed_child_bindings"]}
    return tuple(
        {"reference": ref, "need": need}
        for ref in policy.get("investigation_need_refs", ())
        for need in (view.data(Ref.from_record(ref)),)
        if need["role"] in roles
        and need["requirement_key"] in assignment.body["scope_requirement_keys"]
    )


def reference_data(view, policy, assignment, visible):
    """Complete selected reference data, never rewritten prompt instructions."""
    selected = [item["need"] for item in needs(view, policy, assignment)]
    selected.extend(visible)
    refs = {
        Ref.from_record(ref)
        for item in selected
        for ref in (
            item["decision_ref"],
            item["target_ref"],
            item["applicability_ref"],
            *item["limitation_refs"],
        )
    }
    return tuple(
        {"reference": ref.as_record(), "data": view.data(ref)}
        for ref in sorted(refs, key=lambda ref: ref.artifact_id.value)
    )


def visible_findings(view, assignment):
    """Share through the assigning owner's branch, not unrestricted memory."""
    from .coordination import ancestors

    caller_path = {item.ref for item in ancestors(view, assignment)}
    scope = set(assignment.body["scope_requirement_keys"])
    result = []
    for entry in view.entries("invocation"):
        source = entry.record
        if source.body["role"] not in _STATES:
            continue
        owner = view.read(
            Ref.from_record(source.body["parent_assignment_ref"]), "assignment"
        )
        if owner.ref not in caller_path and assignment.ref not in {
            item.ref for item in ancestors(view, owner)
        }:
            continue
        result.extend(
            item for item in findings(view, source) if item["requirement_key"] in scope
        )
    return tuple(result)
