"""Admit grounded measures from predicate fixtures or actual checker-control Runs.

Original task/control authority is required in both cases. Source admission alone
does not establish checker adequacy or an arbitrary prose requirement's meaning.
"""

from agent.duet_contracts import canonical_json, content_id
from agent.episode_contracts import OpaqueId
from function_library.epistemic_contract import exact
from function_library.refinement_checks import resolve_predicate
from episode_runtime.testing.judgments import check_controls

from .checking import checker_definition
from .evaluation_inputs import instrument_context, native_template
from .records import EvidenceRef, Ref, RefinementRecord
from .measure_needs import admission_policy
from .grounding import CASE_FIELDS, authorize_acquisitions
from .state_machine import actor, derived, index


def definition(proposal):
    body = proposal.body
    return {
        "schema": "openchia.refinement.grounded_measure.v1",
        **{
            name: sorted(body[name], key=canonical_json)
            if name.endswith("_refs") or name == "requirement_keys"
            else body[name]
            for name in body
            if name
            not in {"assignment_ref", "owner_assignment_ref", "case_manifest_ref"}
        },
    }


def _controls(view, grounding, proposal, selection):
    references, positive, negative = [], [], []
    for field, outcome in (
        ("positive_control_refs", "pass"),
        ("negative_control_refs", "fail"),
    ):
        if not grounding[field]:
            raise ValueError(
                "grounded measure needs satisfactory and violating controls"
            )
        for reference in grounding[field]:
            if reference not in proposal.body[field]:
                raise ValueError("proposal omits a required independent control")
            control = exact(
                view.data(Ref.from_record(reference)),
                {"observed", "expected_outcome"},
                "grounded predicate control",
            )
            if control["expected_outcome"] != outcome:
                raise ValueError(
                    f"control {reference['artifact_id']} changes its independently assigned {outcome} polarity"
                )
            references.append(reference)
            (positive if outcome == "pass" else negative).append(control["observed"])
    results = check_controls(
        selection, expected=grounding["expected"], positive=positive, negative=negative,
    )
    return [
        {"control_ref": reference, "expected": result["expected_outcome"], "observed": result["observed_outcome"]}
        for reference, result in zip(references, results, strict=True)
    ]


def grounded_cases(view, proposal, policy):
    """Validate the complete frozen task/fixture authority before any execution."""
    body = proposal.body
    grant = admission_policy(policy)
    if grant is None:
        raise ValueError("campaign has no authority to admit newly composed measures")
    assignment = view.read(Ref.from_record(body["assignment_ref"]), "assignment")
    if assignment.body["local_measure_ref"] != grant["adequacy_measure_ref"]:
        raise ValueError(
            "instrument admission cannot replace the assigned adequacy measure"
        )
    view.data(Ref.from_record(grant["adequacy_measure_ref"]))
    if body["oracle_kind"] not in {"registered_predicate", "independent_execution"}:
        raise ValueError(
            "this route requires grounded predicates or independently controlled execution, not review claims"
        )
    if body["oracle_kind"] == "independent_execution" and not {
        "bind_measure_control",
        "observe_measure_control",
    } <= set(assignment.body["allowed_action_classes"]):
        raise ValueError(
            "the frozen assignment does not authorize executable adequacy controls"
        )
    grounding_refs = [Ref.from_record(ref) for ref in body["grounding_refs"]]
    authorized = {Ref.from_record(ref) for ref in grant["grounding_refs"]}
    acquired = authorize_acquisitions(view, body)
    authorized.update(acquired.case_refs)
    if (
        not grounding_refs
        or len(set(grounding_refs)) != len(grounding_refs)
        or not set(grounding_refs) <= authorized
    ):
        raise ValueError(
            "measure grounding is not independently authorized by the frozen campaign"
        )
    manifest = exact(
        view.data(Ref.from_record(body["case_manifest_ref"])),
        {"grounding_refs"},
        "composed case manifest",
    )
    if set(map(Ref.from_record, manifest["grounding_refs"])) != set(grounding_refs):
        raise ValueError("case manifest changes the proposed grounding set")
    selection = view.data(Ref.from_record(body["decision_function_ref"]))
    if selection["interface"] != "refinement.predicate":
        raise ValueError("measure must select a registered observation predicate")
    resolve_predicate(selection)
    from .instrument_return import admitted_return

    constructed = admitted_return(view, proposal)
    cases, bindings = [], {}
    for reference in grounding_refs:
        grounding = exact(
            view.data(reference),
            CASE_FIELDS,
            "approved grounded case",
        )
        for field in (
            "purpose",
            "oracle_ref",
            "input_domain_ref",
            "observation_schema_ref",
            "decision_function_ref",
            "independence_policy_ref",
            "uncertainty_policy_ref",
        ):
            if canonical_json(grounding[field]) != canonical_json(body[field]):
                raise ValueError(f"measure changes independently grounded {field}")
        if grounding["environment_ref"] != view.contract.body["environment_ref"]:
            raise ValueError("grounding applies to a different environment")
        if not set(map(Ref.from_record, grounding["limitation_refs"])) <= set(
            map(Ref.from_record, body["limitation_refs"])
        ):
            raise ValueError("measure omits independently established limitations")
        instrument = exact(
            grounding["execution_binding"],
            {"harness_ref", "capability_ref", "input_refs"},
            "grounded instrument binding",
        )
        expected_checker_ref = body["oracle_ref"]
        if constructed is not None:
            expected_checker_ref, revisions, _ = constructed
            instrument = {
                **instrument,
                "harness_ref": revisions[Ref.from_record(instrument["harness_ref"])],
            }
            grounding = {**grounding, "execution_binding": instrument}
        bindings[canonical_json(instrument)] = instrument
        executable = view.data(Ref.from_record(instrument["harness_ref"]))
        view.data(Ref.from_record(instrument["capability_ref"]))
        if executable["execution_kind"] not in {
            "target_workflow",
            "instrument_build",
        } or (
            executable["execution_kind"] == "target_workflow"
            and executable["target_workflow_ref"]
            != view.contract.body["target_workflow_ref"]
        ):
            raise ValueError(
                "this instrument needs the independent execution route; native target evaluation cannot execute it"
            )
        native_template(view, instrument)
        checker = checker_definition(view, instrument)
        if body["oracle_kind"] == "registered_predicate" and checker is not None:
            raise ValueError(
                "checker adequacy needs actual independent execution controls; predicate-only controls cannot certify executable behavior"
            )
        if body["oracle_kind"] == "independent_execution" and (
            checker is None or executable["checker_ref"] != expected_checker_ref
        ):
            raise ValueError(
                "independent measure must name its exact approved checking oracle"
            )
        for key in grounding["guard_keys"]:
            view.entry("check", key)
        if (
            not grounding["positive_control_refs"]
            or not grounding["negative_control_refs"]
        ):
            raise ValueError(
                "every case needs independent satisfactory and violating controls"
            )
        if body["oracle_kind"] == "independent_execution":
            from .measure_controls import control_definition

            seen_controls = set()
            for field, outcome in (
                ("positive_control_refs", "pass"),
                ("negative_control_refs", "fail"),
            ):
                for control_ref in grounding[field]:
                    control_reference = Ref.from_record(control_ref)
                    if control_reference in seen_controls:
                        raise ValueError(
                            "an executable case cannot repeat a control or assign both polarities"
                        )
                    seen_controls.add(control_reference)
                    control_definition(view, control_reference, outcome)
        cases.append((reference, grounding))
    requirements = [case["requirement_key"] for _, case in cases]
    if set(requirements) != set(body["requirement_keys"]):
        raise ValueError(
            "measure must cover exactly the parent's requested requirements"
        )
    for field in ("positive_control_refs", "negative_control_refs", "limitation_refs"):
        declared = [Ref.from_record(ref) for ref in body[field]]
        required = {Ref.from_record(ref) for _, case in cases for ref in case[field]}
        if constructed is not None and field == "limitation_refs":
            required.update(map(Ref.from_record, constructed[2]))
        if len(set(declared)) != len(declared) or set(declared) != required:
            raise ValueError(f"measure must retain exactly its grounded {field}")
    return cases, bindings, selection


def _admitted_checks(view, attempt, proposal, measure_ref, policy):
    from .instrument_return import return_evidence
    from .measure_groups import project_admitted_checks

    body = proposal.body
    cases, bindings, selection = grounded_cases(view, proposal, policy)
    acquired = authorize_acquisitions(view, body)
    results, controls, execution_evidence = [], [], list(acquired.evidence_refs)
    for reference, grounding in cases:
        if body["oracle_kind"] == "independent_execution":
            from .measure_controls import control_results

            outcomes, evidence = control_results(
                view, proposal, reference, grounding, selection
            )
            results.extend(outcomes)
            execution_evidence.extend(evidence)
        else:
            results.extend(_controls(view, grounding, proposal, selection))
        controls.extend(
            grounding["positive_control_refs"] + grounding["negative_control_refs"]
        )
    # Every selected grounding is independently authorized as a complete case,
    # not a model-created fragment of an acceptance criterion. Multiple such
    # cases may constrain one requirement; none loses its guards or controls.
    checks = []
    for reference, grounding in cases:
        checks.append(
            RefinementRecord(
                "check",
                view.campaign_id,
                {
                    "requirement_key": grounding["requirement_key"],
                    "evidence_kind": "execution",
                    "origin_refs": [reference.as_record()],
                    "measure_ref": measure_ref.as_record(),
                    "purpose": body["purpose"],
                    "predicate_ref": body["decision_function_ref"],
                    "expected": grounding["expected"],
                    "dependency_paths": grounding["dependency_paths"],
                    "environment_ref": grounding["environment_ref"],
                    "mandatory": True,
                    "guard_keys": grounding["guard_keys"],
                    "grounding_refs": [reference.as_record()],
                    "observation_path": grounding["observation_path"],
                    **(
                        {"execution_binding": grounding["execution_binding"]}
                        if len(bindings) > 1 or policy.get("measure_group_refs")
                        else {}
                    ),
                },
                view.contract.producer_ref,
            )
        )
    evidence = tuple(
        EvidenceRef(
            "duet_artifact",
            OpaqueId(view.head["duet_id"]),
            ref.artifact_id,
            ref.content_hash,
            "",
        )
        for ref in dict.fromkeys([
            *(reference for reference, _ in cases),
            *(Ref.from_record(ref) for ref in controls),
            *return_evidence(view, proposal),
            *acquired.provenance_refs,
        ])
    )
    admitted_bindings = tuple(
        {
            **binding,
            "measure_ref": measure_ref.as_record(),
            "purpose": body["purpose"],
        }
        for _, binding in sorted(bindings.items())
    )
    checks = project_admitted_checks(view, policy, checks, admitted_bindings)
    return (
        checks,
        results,
        admitted_bindings,
        tuple(dict.fromkeys((*evidence, *execution_evidence))),
    )


def _fact_keys(view, checks, binding, proposal):
    if proposal.body["oracle_kind"] == "independent_execution":
        from .measure_controls import validated_control_facts

        controls = validated_control_facts(view, proposal_ref=proposal.ref)
        if controls:
            # The same facts may already have earned partial progress. Full
            # admission establishes coverage, not another copy of that credit.
            return sorted(controls)
    # Grouping the same requirements into new bundles is not new adequacy.
    # Measure/proposal/assignment IDs are provenance, not semantic novelty.
    return sorted({
        content_id(
            "refinement_fact",
            {
                "kind": "grounded_measure_adequacy",
                "check": {
                    field: check.body[field]
                    for field in (
                        "requirement_key",
                        "purpose",
                        "predicate_ref",
                        "expected",
                        "environment_ref",
                        "dependency_paths",
                        "observation_path",
                        "guard_keys",
                    )
                },
                "instrument": instrument_context(
                    view, check.body.get("execution_binding", binding)
                ),
            },
        ).value
        for check in checks
    })


def _binding_fields(bindings):
    if len(bindings) <= 1:
        return {"evaluation_binding": bindings[0] if bindings else None}
    return {"evaluation_binding": None, "evaluation_bindings": list(bindings)}


def _control_links(view, proposal):
    if proposal.body["oracle_kind"] != "independent_execution":
        return {}
    from .measure_controls import control_run_refs

    return {"control_run_refs": control_run_refs(view, proposal)}


def admit_measure(view, attempt, resolved):
    assignment = actor(view, attempt)
    payload = exact(
        attempt.body["payload"], {"proposal_ref", "measure_ref"}, "measure admission"
    )
    proposal_ref = Ref.from_record(payload["proposal_ref"])
    proposal = view.entry("measure_proposal", proposal_ref.artifact_id.value).record
    if (
        assignment.body["role"] != "measure"
        or proposal.ref != proposal_ref
        or proposal.body["assignment_ref"] != assignment.ref.as_record()
    ):
        raise ValueError(
            "only the proposing EstablishMeasure invocation may submit admission"
        )
    measure_ref = Ref.from_record(payload["measure_ref"])
    if canonical_json(view.data(measure_ref)) != canonical_json(definition(proposal)):
        raise ValueError("measure definition differs from its semantic proposal")
    already_admitted = any(
        entry.status == "admitted"
        and entry.record.body["measure_ref"] == measure_ref.as_record()
        for entry in view.entries("measure")
    )
    if not already_admitted and any(
        entry.status in {"active", "waiting", "ready"}
        and measure_ref.as_record()
        in (
            entry.record.body["local_measure_ref"],
            entry.record.body["acceptance_measure_ref"],
        )
        for entry in view.entries("invocation")
    ):
        raise ValueError(
            "admitting checks cannot change an already frozen assignment's measure"
        )
    checks, results, bindings, evidence = [], [], (), ()
    status, reason = "admitted", None
    try:
        checks, results, bindings, evidence = _admitted_checks(
            view, attempt, proposal, measure_ref, resolved.references["policy"]
        )
    except (ValueError, KeyError, TypeError) as exc:
        status, reason = "rejected", str(exc)
    admission = derived(
        view,
        attempt,
        "measure_admission",
        {
            "proposal_ref": proposal.ref.as_record(),
            "owner_assignment_ref": proposal.body["owner_assignment_ref"],
            "measure_ref": measure_ref.as_record(),
            "check_refs": [check.ref.as_record() for check in checks],
            **_binding_fields(bindings),
            **_control_links(view, proposal),
            "control_results": results,
            "grounding_refs": proposal.body["grounding_refs"],
            "status": status,
            "reason": reason,
            "fact_keys": _fact_keys(view, checks, bindings[0], proposal)
            if status == "admitted"
            else [],
        },
        evidence=evidence,
    )
    return [*checks, admission], [
        index("measure", admission.artifact_id.value, admission, status),
        *(index("check", check.artifact_id.value, check) for check in checks),
    ]


def validate_admission(view, admission):
    """Re-derive operative checks, control results and credit at publication."""
    proposal = view.read(
        Ref.from_record(admission.body["proposal_ref"]), "measure_proposal"
    )
    attempt = view.read(admission.predecessor_refs[0], "attempt")
    assignment = view.entry("invocation", admission.invocation_id.value).record
    measure_ref = Ref.from_record(admission.body["measure_ref"])
    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    if (
        attempt.body["action"] != "admit_measure"
        or attempt.body["payload"]
        != {
            "proposal_ref": proposal.ref.as_record(),
            "measure_ref": measure_ref.as_record(),
        }
        or attempt.invocation_id != admission.invocation_id
        or attempt.logical_unit_id != admission.logical_unit_id
        or assignment.body["role"] != "measure"
        or proposal.body["assignment_ref"] != assignment.ref.as_record()
        or admission.body["owner_assignment_ref"]
        != assignment.body["parent_assignment_ref"]
        or canonical_json(view.data(measure_ref))
        != canonical_json(definition(proposal))
    ):
        raise ValueError("measure admission has invalid provenance or definition")
    checks, results, bindings, evidence = _admitted_checks(
        view, attempt, proposal, measure_ref, policy
    )
    expected = {
        "proposal_ref": proposal.ref.as_record(),
        "owner_assignment_ref": proposal.body["owner_assignment_ref"],
        "measure_ref": measure_ref.as_record(),
        "check_refs": [check.ref.as_record() for check in checks],
        **_binding_fields(bindings),
        **_control_links(view, proposal),
        "control_results": results,
        "grounding_refs": proposal.body["grounding_refs"],
        "status": "admitted",
        "reason": None,
        "fact_keys": _fact_keys(view, checks, bindings[0], proposal),
    }
    if (
        canonical_json(admission.body) != canonical_json(expected)
        or admission.evidence_refs != evidence
    ):
        raise ValueError("admitted measure differs from grounded controls")
    for check in checks:
        view.read(check.ref, "check")
