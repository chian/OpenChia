"""Frozen groups accumulate admitted checks, never replacement criteria.

A group is declared before the campaign starts. Admission projects each member
into the group's measure identity while retaining its original check, predicate,
guards and instrument. Existing evaluation/acceptance then uses ordinary exact
check records. Past requests keep their exact check sets and observations.
"""

from agent.duet_contracts import canonical_json
from function_library.epistemic_contract import exact, names

from .records import Ref, RefinementRecord


SCHEMA = "openchia.refinement.measure_group.v1"


def group_definition(*purposes):
    names(purposes, "measure group purposes", nonempty=True)
    if not set(purposes) <= {"local", "acceptance", "composition"}:
        raise ValueError(
            "measure groups cannot confer investigation or adequacy authority"
        )
    return {"schema": SCHEMA, "purposes": list(purposes)}


def declarations(view, policy):
    groups = {}
    for raw in policy.get("measure_group_refs", ()):
        reference = Ref.from_record(raw)
        value = exact(view.data(reference), {"schema", "purposes"}, "measure group")
        if canonical_json(value) != canonical_json(
            group_definition(*value["purposes"])
        ):
            raise ValueError("measure group differs from the registered group rule")
        if reference in groups:
            raise ValueError("a frozen policy cannot repeat a measure group")
        groups[reference] = value["purposes"]
    return groups


def project_admitted_checks(view, policy, checks, bindings):
    """Called within admission and independently re-derived at publication."""
    from .measures import bindings_for_check

    projected = list(checks)
    for reference, purposes in declarations(view, policy).items():
        for check in checks:
            if check.body["purpose"] not in purposes:
                continue
            matches = bindings_for_check(bindings, check)
            if len(matches) != 1:
                raise ValueError("a grouped check needs its exact admitted instrument")
            binding = matches[0]
            context = {
                key: binding[key]
                for key in (
                    "harness_ref",
                    "capability_ref",
                    "input_refs",
                )
            }
            projected.append(
                RefinementRecord(
                    "check",
                    view.campaign_id,
                    {
                        **check.body,
                        "measure_ref": reference.as_record(),
                        "origin_refs": [
                            *check.body["origin_refs"],
                            check.ref.as_record(),
                        ],
                        "execution_binding": context,
                    },
                    view.contract.producer_ref,
                )
            )
    return projected


def admitted_members(view, policy, assignment):
    """Share only scoped group members, not arbitrary sibling measures/history."""
    groups = declarations(view, policy)
    if not groups:
        return ()
    scope = set(assignment.body["scope_requirement_keys"])
    result = []
    for row in view.entries("measure"):
        if row.status != "admitted":
            continue
        for raw in row.record.body["check_refs"]:
            check = view.read(Ref.from_record(raw), "check")
            if (
                Ref.from_record(check.body["measure_ref"]) in groups
                and check.body["requirement_key"] in scope
            ):
                result.append((check, row.record))
    return tuple(result)


def member_bindings(members):
    return [
        {
            **check.body["execution_binding"],
            "measure_ref": check.body["measure_ref"],
            "purpose": check.body["purpose"],
        }
        for check, _ in members
    ]
