"""Grounded prerequisite requests from Measure to its existing owner.

A request is not an admitted instrument, a repair verdict or new build authority.
Only the parent can choose the next permitted design/coding assignment.
"""

from agent.duet_contracts import content_id
from agent.episode_contracts import OpaqueId
from function_library.epistemic_contract import exact, names

from .records import EvidenceRef, Ref


def admission_policy(policy):
    grant = policy.get("measure_admission")
    if grant is None:
        return None
    fields = {"adequacy_measure_ref", "grounding_refs"}
    fields.update(
        set(grant) & {"instrument_build_refs", "acquisition_refs", "source_function_refs", "reviewed_designs"}
    )
    exact(grant, fields, "measure admission authority")
    Ref.from_record(grant["adequacy_measure_ref"])
    from .measure_design import policy as design_policy

    design_policy(grant)
    for key in fields - {"adequacy_measure_ref", "reviewed_designs"}:
        values = grant[key]
        if not isinstance(values, (list, tuple)):
            raise ValueError(f"{key} must contain exact reference arrays")
        references = tuple(map(Ref.from_record, values))
        if len(set(references)) != len(references):
            raise ValueError(f"{key} cannot repeat a reference")
    return grant


def build_specification(read_data, reference):
    body = read_data(reference)
    spec = exact(
        body,
        {
            "purpose",
            "requirement_keys",
            "checker_ref",
            "input_contract_ref",
            "output_contract_ref",
            "local_measure_ref",
            "acceptance_measure_ref",
            "grounding_refs",
            "positive_control_refs",
            "negative_control_refs",
            "limitation_refs",
        }
        | ({"acquisition_refs"} if "acquisition_refs" in body else set()),
        "authorized instrument-building specification",
    )
    names(spec["requirement_keys"], "instrument requirements", nonempty=True)
    if spec["purpose"] not in {"local", "acceptance", "composition", "adequacy"}:
        raise ValueError("instrument-building purpose is invalid")
    for key, value in spec.items():
        if key.endswith("_refs"):
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"instrument {key} must be an array")
            refs = tuple(map(Ref.from_record, value))
            if len(set(refs)) != len(refs):
                raise ValueError(f"instrument {key} cannot repeat a reference")
        references = (
            [value] if key.endswith("_ref") else value if key.endswith("_refs") else ()
        )
        for ref in references:
            read_data(Ref.from_record(ref))
    if not spec.get("acquisition_refs") and not all(
        spec[key]
        for key in ("grounding_refs", "positive_control_refs", "negative_control_refs")
    ):
        raise ValueError(
            "instrument-building needs independent cases and controls or exact acquisition routes"
        )
    positive = set(map(Ref.from_record, spec["positive_control_refs"]))
    negative = set(map(Ref.from_record, spec["negative_control_refs"]))
    if positive & negative:
        raise ValueError("one instrument control cannot have both polarities")
    return spec


def catalog(view, assignment, policy):
    """Expose exact selectable requests, not a model-authored reason to stop."""
    if assignment.body["role"] != "measure":
        return ()
    goal = view.data(Ref.from_record(assignment.body["goal_record_ref"]))
    requested = goal["measure_request"]
    requirements = set(requested["requirement_keys"])
    grant = admission_policy(policy)
    needs = []
    policy_ref = view.contract.body["policy_bundle_ref"]
    if grant is None:
        needs.append({
            "kind": "measure_authority_required",
            "purpose": requested["purpose"],
            "requirement_keys": sorted(requirements),
            "basis_refs": [policy_ref],
            "instrument_build_ref": None,
        })
    else:
        covered = {
            case["requirement_key"]
            for ref in grant["grounding_refs"]
            for case in (view.data(Ref.from_record(ref)),)
            if case["purpose"] == requested["purpose"]
            and case["environment_ref"] == view.contract.body["environment_ref"]
        }
        # Permission to design a check does not supply missing observations or
        # independent grounding. Keep the owner route available when design
        # cannot establish the requirement with this harness's actual evidence.
        if requirements - covered:
            needs.append({
                "kind": "grounding_required",
                "purpose": requested["purpose"],
                "requirement_keys": sorted(requirements - covered),
                "basis_refs": [policy_ref],
                "instrument_build_ref": None,
            })
        for ref in grant.get("instrument_build_refs", ()):
            spec = build_specification(view.data, Ref.from_record(ref))
            if (
                spec["purpose"] != requested["purpose"]
                or not set(spec["requirement_keys"]) <= requirements
            ):
                continue
            needs.append({
                "kind": "instrument_build_required",
                "purpose": requested["purpose"],
                "requirement_keys": sorted(spec["requirement_keys"]),
                "basis_refs": [policy_ref, ref],
                "instrument_build_ref": ref,
            })
    return tuple(
        {"need_key": content_id("measure_need", need).value, **need} for need in needs
    )


def prerequisite_record(view, attempt):
    from .state_machine import actor, derived

    assignment = actor(view, attempt)
    payload = exact(
        attempt.body["payload"], {"prerequisite_request"}, "measurement prerequisite"
    )
    choice = exact(
        payload["prerequisite_request"], {"need_key"}, "measurement prerequisite choice"
    )
    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    selected = [
        need
        for need in catalog(view, assignment, policy)
        if need["need_key"] == choice["need_key"]
    ]
    if len(selected) != 1:
        raise ValueError(
            "measurement prerequisite is not in this assignment's authorized needs"
        )
    need = selected[0]
    evidence = tuple(
        EvidenceRef(
            "duet_artifact",
            OpaqueId(view.head["duet_id"]),
            ref.artifact_id,
            ref.content_hash,
            "",
        )
        for ref in map(Ref.from_record, need["basis_refs"])
    )
    return derived(
        view,
        attempt,
        "measure_prerequisite",
        {
            "assignment_ref": assignment.ref.as_record(),
            "owner_assignment_ref": assignment.body["parent_assignment_ref"],
            "need": need,
        },
        evidence=evidence,
    )


def request_prerequisite(view, attempt):
    from .state_machine import index

    record = prerequisite_record(view, attempt)
    return [record], [
        index("measure_need", record.artifact_id.value, record, "requested")
    ]


def return_prerequisite(view, attempt):
    """Move an exact returned child need up one ownership edge, without credit."""
    from .state_machine import actor, derived, index

    assignment = actor(view, attempt)
    if (
        assignment.body["role"] not in {"designer", "parts"}
        or assignment.body["parent_assignment_ref"] is None
    ):
        raise ValueError("only a nested Parts or Designer may return a child prerequisite to its parent")
    payload = exact(attempt.body["payload"], {"return_prerequisite_ref"}, "prerequisite return")
    reference = Ref.from_record(payload["return_prerequisite_ref"])
    entry = view.entry("measure_need", reference.artifact_id.value)
    source = entry.record
    child = view.entry("invocation", source.invocation_id.value)
    if (
        entry.status != "requested"
        or source.ref != reference
        or child.status != "returned"
        or child.record.ref.as_record() != source.body["assignment_ref"]
        or child.record.body["parent_assignment_ref"] != assignment.ref.as_record()
        or source.body["owner_assignment_ref"] != assignment.ref.as_record()
        or not set(source.body["need"]["requirement_keys"]).issubset(
            assignment.body["contribution_requirement_keys"]
        )
    ):
        raise ValueError("prerequisite return must cite an exact returned direct-child need within this assignment")
    record = derived(
        view,
        attempt,
        "measure_prerequisite",
        {
            "assignment_ref": assignment.ref.as_record(),
            "owner_assignment_ref": assignment.body["parent_assignment_ref"],
            "need": source.body["need"],
        },
        evidence=(EvidenceRef(
            "duet_artifact", OpaqueId(view.head["duet_id"]),
            reference.artifact_id, reference.content_hash, "",
        ),),
    )
    return [record], [index("measure_need", record.artifact_id.value, record, "requested")]


def unit_prerequisite(view, attempt):
    return next(
        (
            entry.record
            for entry in view.entries("measure_need")
            if entry.record.invocation_id == attempt.invocation_id
            and entry.record.logical_unit_id == attempt.logical_unit_id
        ),
        None,
    )




def prerequisite_assignments(view, references):
    """Follow exact handoff provenance, not unrelated campaign histories."""
    pending = list(map(Ref.from_record, references))
    seen, assignments = set(), set()
    while pending:
        reference = pending.pop()
        if reference in seen:
            continue
        seen.add(reference)
        record = view.read(reference, "measure_prerequisite")
        assignment_ref = Ref.from_record(record.body["assignment_ref"])
        assignments.add(assignment_ref)
        assignment = view.read(assignment_ref, "assignment")
        goal = view.data(Ref.from_record(assignment.body["goal_record_ref"]))
        pending.extend(map(Ref.from_record, goal.get("prerequisite_refs", ())))
        attempt = view.read(record.predecessor_refs[0], "attempt")
        forwarded = attempt.body["payload"].get("return_prerequisite_ref")
        if forwarded is not None:
            pending.append(Ref.from_record(forwarded))
    return assignments


def assignment_prerequisites(view, parent, selected, requirements):
    """Keep the original request through assignment, without copying its authority."""
    parent_goal = view.data(Ref.from_record(parent.body["goal_record_ref"]))
    inherited = {
        Ref.from_record(ref) for ref in parent_goal.get("prerequisite_refs", ())
    }
    if not isinstance(selected, (list, tuple)):
        raise ValueError("assignment prerequisite references must be an array")
    requested = tuple(map(Ref.from_record, selected))
    if len(set(requested)) != len(requested):
        raise ValueError("an assignment cannot repeat a prerequisite reference")
    result = dict.fromkeys(inherited)
    for reference in requested:
        entry = view.entry("measure_need", reference.artifact_id.value)
        record = entry.record
        if record.ref != reference or entry.status != "requested":
            raise ValueError(
                "assignment prerequisite differs from its admitted request"
            )
        if reference not in inherited:
            source = view.entry("invocation", record.invocation_id.value)
            if (
                record.body["owner_assignment_ref"] != parent.ref.as_record()
                or source.status != "returned"
            ):
                raise ValueError(
                    "only the assigning owner may route a returned prerequisite"
                )
            if not set(record.body["need"]["requirement_keys"]) <= set(requirements):
                raise ValueError("assignment omits part of its selected prerequisite")
        result[reference] = None
    return [
        ref.as_record() for ref in sorted(result, key=lambda ref: ref.artifact_id.value)
    ]


def validate_assignment_prerequisites(view, parent, assignment):
    goal = view.data(Ref.from_record(assignment.body["goal_record_ref"]))
    expected = assignment_prerequisites(
        view,
        parent,
        goal.get("prerequisite_refs", ()),
        assignment.body["contribution_requirement_keys"],
    )
    if expected != list(goal.get("prerequisite_refs", ())) or not set(
        map(Ref.from_record, expected)
    ) <= set(map(Ref.from_record, assignment.body["input_refs"])):
        raise ValueError("assignment loses its original prerequisite input references")
