"""Admit grounded measures from predicate fixtures or actual checker-control Runs.

Original task/control authority is required in both cases. Source admission alone
does not establish checker adequacy or an arbitrary prose requirement's meaning.
"""

from agent.duet_contracts import canonical_json, content_id
from agent.episode_contracts import OpaqueId
from function_library.epistemic_contract import exact
from function_library.materialization_progress import RequirementMeasure
from function_library.refinement_checks import resolve_predicate
from function_library.refinement_contract import ROLE_SPECIALIZATION
from episode_runtime.testing_harness.judgments import judge_value

from .checking import checker_definition
from .evaluation_inputs import native_template
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
    results = []
    controls = [("pass", value) for value in positive] + [("fail", value) for value in negative]
    for reference, (expected, value) in zip(references, controls, strict=True):
        actual = judge_value(selection, observed=value, expected=grounding["expected"])
        results.append({
            "control_ref": reference, "expected": expected, "observed": actual,
            "status": "pass" if actual == expected else "fail",
            "reason": None if actual == expected else f"control expected {expected}, observed {actual}",
        })
    return results


def _case_results(view, proposal, cases, selection, *, snapshot=None):
    """Assess every case; an inadequate instrument is not a failed target."""
    case_results, results, evidence = [], [], []
    for reference, grounding in cases:
        try:
            if proposal.body["oracle_kind"] == "checking_program":
                from .authored_checks import control_results

                outcomes, proofs = control_results(view, proposal, reference, grounding, selection, snapshot=snapshot)
            elif proposal.body["oracle_kind"] == "independent_execution":
                from .measure_controls import control_results

                outcomes, proofs = control_results(view, proposal, reference, grounding, selection, snapshot=snapshot)
            else:
                outcomes, proofs = _controls(view, grounding, proposal, selection), []
            statuses = {row["status"] for row in outcomes}
            status = next((value for value in ("error", "fail", "blocked") if value in statuses),
                          "pass")
            reason = "; ".join(dict.fromkeys(row["reason"] for row in outcomes if row.get("reason"))) or None
            evidence.extend(proofs)
        except (ValueError, KeyError, TypeError) as exc:
            outcomes, status, reason = [], "error", str(exc)
        results.extend({"grounding_ref": reference.as_record(),
                        "requirement_key": grounding["requirement_key"], **row} for row in outcomes)
        case_results.append({
            "grounding_ref": reference.as_record(), "requirement_key": grounding["requirement_key"],
            "status": status, "reason": reason,
            "controls_total": len(grounding["positive_control_refs"]) + len(grounding["negative_control_refs"]),
            "controls_matched": sum(row["expected"] == row["observed"] for row in outcomes),
        })
    return case_results, results, evidence


def requirement_results(proposal, cases, *, blocked_reason=None):
    """Publish one explicit adequacy result for every requested requirement."""
    requirements = [{
        "requirement_id": key, "mandatory": True,
        "check_ids": [case["grounding_ref"]["artifact_id"] for case in cases
                      if case["requirement_key"] == key],
    } for key in proposal.body["requirement_keys"]]
    # Here the evaluated candidate is the proposed instrument. The same fixed
    # requirement aggregation later measures Target Workflow observations;
    # instrument adequacy and target success retain different candidate IDs.
    progress = RequirementMeasure(requirements)(
        observations=[{
            "check_id": case["grounding_ref"]["artifact_id"],
            "candidate_ref": proposal.ref.as_record(), "status": case["status"],
        } for case in cases],
        candidate_ref=proposal.ref.as_record(),
    )
    result = []
    for key in sorted(proposal.body["requirement_keys"]):
        selected = [case for case in cases if case["requirement_key"] == key]
        status = progress["requirement_statuses"][key] if selected else "blocked"
        result.append({
            "requirement_key": key, "status": status,
            "reason": blocked_reason if not selected else None,
            "cases": selected,
        })
    return result


def grounded_cases(view, proposal, policy):
    """Validate the complete frozen task/fixture authority before any execution."""
    body = proposal.body
    grant = admission_policy(policy)
    if grant is None:
        raise ValueError("campaign has no authority to admit newly composed measures")
    assignment = view.read(Ref.from_record(body["assignment_ref"]), "assignment")
    basis = retained_basis(view, proposal)
    if not set(body["requirement_keys"]) <= set(basis["requirement_keys"]):
        raise ValueError("Measure's requested revision expands the parent's fixed requirement scope")
    if assignment.body["local_measure_ref"] != grant["adequacy_measure_ref"]:
        raise ValueError(
            "instrument admission cannot replace the assigned adequacy measure"
        )
    view.data(Ref.from_record(grant["adequacy_measure_ref"]))
    if body["oracle_kind"] not in {"registered_predicate", "independent_execution", "checking_program"}:
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
    from .measure_design_runtime import authorize as authorize_reviewed_design

    authorized.update(authorize_reviewed_design(view, proposal))
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
        if body["oracle_kind"] == "checking_program":
            from .authored_checks import instrument as checking_program

            selected = checking_program(view, instrument)
            if selected is None or selected[0]["definition_ref"] != body.get("reviewed_definition_ref"):
                raise ValueError("checking program requires its exact reviewed definition")
            for field, polarity in (("positive_control_refs", "pass"), ("negative_control_refs", "fail")):
                if not grounding[field]:
                    raise ValueError("checking program requires both control polarities")
                for raw in grounding[field]:
                    control = exact(view.data(Ref.from_record(raw)), {"fixture", "expected_outcome"}, "checking control")
                    if control["expected_outcome"] != polarity:
                        raise ValueError("checking fixture polarity differs from review")
            cases.append((reference, grounding))
            continue
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


def retained_basis(view, proposal):
    """The exact measure captured by the parent when it requested this revision."""
    assignment = view.read(Ref.from_record(proposal.body["assignment_ref"]), "assignment")
    goal = view.data(Ref.from_record(assignment.body["goal_record_ref"]))
    if proposal.body["basis_ref"] != goal["measure_basis_ref"]:
        raise ValueError("a measure proposal changed the parent's fixed composition basis")
    basis = exact(view.data(Ref.from_record(proposal.body["basis_ref"])), {
        "owner_assignment_ref", "measure_ref", "purpose", "requirement_keys",
        "check_refs", "check_bindings", "baseline_candidate_ref",
    }, "measure composition basis")
    if (basis["owner_assignment_ref"] != proposal.body["owner_assignment_ref"]
            or basis["purpose"] != proposal.body["purpose"]):
        raise ValueError("a measure composition changed its owner or requested purpose")
    references = tuple(map(Ref.from_record, basis["check_refs"]))
    if len(set(references)) != len(references) or set(basis["check_bindings"]) != {
        ref.artifact_id.value for ref in references
    }:
        raise ValueError("composition basis must bind every retained check exactly once")
    for reference in references:
        installed = view.entry("check", reference.artifact_id.value).record
        if (installed.ref != reference or installed.body["purpose"] != basis["purpose"]
                or installed.body["requirement_key"] not in basis["requirement_keys"]):
            raise ValueError("composition basis lost an exact admitted check")
    view.read(Ref.from_record(basis["baseline_candidate_ref"]), "candidate")
    return basis


def _admitted_checks(view, attempt, proposal, measure_ref, policy, snapshot):
    from .instrument_return import return_evidence

    body = proposal.body
    cases, bindings, selection = grounded_cases(view, proposal, policy)
    acquired = authorize_acquisitions(view, body)
    cases_assessed, results, executed = _case_results(view, proposal, cases, selection, snapshot=snapshot)
    controls = []
    execution_evidence = [*acquired.evidence_refs, *executed]
    review_provenance = []
    if "reviewed_definition_ref" in body:
        from .measure_design import reviewed

        assignment = view.read(Ref.from_record(body["assignment_ref"]), "assignment")
        check_definition, reviews = reviewed(view, body["reviewed_definition_ref"], assignment)
        review_provenance = [check_definition.ref, *(record.ref for record in reviews)]
    for reference, grounding in cases:
        controls.extend(
            grounding["positive_control_refs"] + grounding["negative_control_refs"]
        )
    # Every selected grounding is independently authorized as a complete case,
    # not a model-created fragment of an acceptance criterion. Multiple such
    # cases may constrain one requirement; none loses its guards or controls.
    checks = []
    ready_requirements = {row["requirement_key"] for row in requirement_results(proposal, cases_assessed)
                          if row["status"] == "pass"}
    ready_cases = [(reference, grounding) for reference, grounding in cases
                   if grounding["requirement_key"] in ready_requirements]
    for reference, grounding in ready_cases:
        checks.append(
            RefinementRecord(
                "check",
                view.campaign_id,
                {
                    "requirement_key": grounding["requirement_key"],
                    "evidence_kind": "checking_program" if body["oracle_kind"] == "checking_program" else "execution",
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
                    "execution_binding": grounding["execution_binding"],
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
            *review_provenance,
            Ref.from_record(body["basis_ref"]),
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
    return (
        checks,
        results,
        admitted_bindings,
        tuple(dict.fromkeys((*evidence, *execution_evidence))),
        cases_assessed,
    )


def adequacy_fact_keys(view, proposal, results):
    """One completed requirement of the commissioned instrument is one fact.

    The parent's previous measure identifies the revision being requested.
    Rewriting a program, regrouping cases or adding controls cannot multiply
    achievements while fulfilling that same request.
    """
    basis = retained_basis(view, proposal)
    return sorted({
        content_id(
            "refinement_fact",
            {
                "kind": "measure_requirement_adequacy",
                "requirement_key": row["requirement_key"],
                "purpose": proposal.body["purpose"],
                "previous_measure_ref": basis["measure_ref"],
                "environment_ref": view.contract.body["environment_ref"],
            },
        ).value
        for row in results if row["status"] == "pass"
    })


def _binding_fields(bindings):
    if len(bindings) <= 1:
        return {"evaluation_binding": bindings[0] if bindings else None}
    return {"evaluation_binding": None, "evaluation_bindings": list(bindings)}


def measurement_function(view, proposal, checks):
    """Compile the Measure's exact admitted cases into one reusable callable."""
    basis = retained_basis(view, proposal)
    catalog = view.data(Ref.from_record(view.contract.body["requirement_catalog_ref"]))
    mandatory = {row["requirement_key"]: row["mandatory"] for row in catalog["requirements"]}
    return RequirementMeasure([{
        "requirement_id": key,
        "mandatory": mandatory[key],
        "check_ids": [check.artifact_id.value for check in checks
                      if check.body["requirement_key"] == key],
    } for key in basis["requirement_keys"]]).as_record()


def _control_links(view, proposal, snapshot):
    if proposal.body["oracle_kind"] != "independent_execution":
        return {}
    from .measure_controls import control_run_refs

    return {"control_run_refs": control_run_refs(view, proposal, snapshot=snapshot)}


def control_snapshot(view, proposal):
    """Pin the available control evidence for this immutable assessment.

    A later unit can finish more controls of the same proposal. Revalidating
    an earlier partial assessment still uses the evidence it actually saw.
    """
    from .measure_controls import control_key

    result = {}
    if proposal.body["oracle_kind"] == "checking_program":
        rows = view.connection.execute(
            "SELECT artifact_id, content_hash FROM artifacts WHERE duet_id = ? "
            "AND kind = 'refinement.checker_result.v1' "
            "AND json_extract(record_json, '$.subject.proposal_ref.artifact_id') = ? "
            "ORDER BY rowid",
            (view.head["duet_id"], proposal.artifact_id.value),
        )
        for row in rows:
            record = view.data(Ref.from_record(dict(row)))
            subject = record["subject"]
            if (subject["campaign_id"] != view.campaign_id.value
                    or subject["invocation_id"] != proposal.invocation_id.value
                    or subject["unit_id"] != proposal.logical_unit_id.value
                    or subject["proposal_ref"] != proposal.ref.as_record()):
                continue
            key = control_key(proposal.ref, Ref.from_record(subject["grounding_ref"]),
                              Ref.from_record(subject["control_ref"]))
            result[key] = record["execution_ref"]
    elif proposal.body["oracle_kind"] == "independent_execution":
        for entry in view.entries("measure_control"):
            binding = (entry.record if entry.record.kind == "measure_control_run" else
                       view.read(Ref.from_record(entry.record.body["control_run_ref"]), "measure_control_run"))
            if binding.body["proposal_ref"] == proposal.ref.as_record():
                result[entry.key] = entry.record.ref.as_record()
    return result


def _assess_proposal(view, attempt, proposal, measure_ref, policy, *, snapshot=None):
    """Derive publication and partial adequacy from the same control evidence."""
    from .measure_components import retain_components

    checks, results, bindings, evidence, cases = [], [], (), (), []
    reason = None
    if snapshot is None:
        snapshot = control_snapshot(view, proposal)
    if proposal.body["oracle_kind"] == "component_composite":
        retained_basis(view, proposal)
        assessed = []
    else:
        try:
            checks, results, bindings, evidence, cases = _admitted_checks(
                view, attempt, proposal, measure_ref, policy, snapshot
            )
            if any(row["status"] != "pass" for row in cases):
                reason = "Some requirement checks are not ready; see requirement_results."
        except (ValueError, KeyError, TypeError) as exc:
            reason = str(exc)
        assessed = requirement_results(proposal, cases, blocked_reason=reason)
    checks, bindings, evidence, assessed, results, limitations = retain_components(
        view, proposal, measure_ref, checks=checks, bindings=bindings,
        evidence=evidence, assessed=assessed, controls=results,
    )
    status = "partial" if any(row["status"] == "pass" for row in assessed) else "rejected"
    assignment = view.read(Ref.from_record(proposal.body["assignment_ref"]), "assignment")
    complete = all(row["status"] == "pass" for row in assessed)
    if complete and assignment.body["role"] == "measure":
        basis = retained_basis(view, proposal)
        commissioned = {row["requirement_key"] for row in assessed}
        # Completed components replace only this commissioned requirement set.
        # Other original checks retain their identities and guard pointers.
        retained = [check for raw in basis["check_refs"]
                    for check in (view.read(Ref.from_record(raw), "check"),)
                    if check.body["requirement_key"] not in commissioned]
        combined = [*checks, *retained]
        keys = {check.artifact_id.value for check in combined}
        if any(set(check.body["guard_keys"]) - keys for check in combined):
            reason = "The revised composite needs coordinated revision of a retained check's missing guard."
        else:
            checks = combined
            bindings = tuple({canonical_json(binding): binding for binding in (
                *bindings,
                *({**basis["check_bindings"][check.artifact_id.value],
                   "measure_ref": measure_ref.as_record(), "purpose": proposal.body["purpose"]}
                  for check in retained),
            )}.values())
            status, reason = "admitted", None
    if status != "admitted" and reason is None:
        reason = ("Adequate scoped components are ready for the enclosing Measure to compose."
                  if complete else "The commissioned composite has unfinished requirements; see requirement_results.")
    body = {
        "proposal_ref": proposal.ref.as_record(),
        "owner_assignment_ref": proposal.body["owner_assignment_ref"],
        "measure_ref": measure_ref.as_record(),
        "check_refs": [check.ref.as_record() for check in checks],
        "measurement_function": measurement_function(view, proposal, checks)
        if status == "admitted" else None,
        **_binding_fields(bindings),
        **_control_links(view, proposal, snapshot),
        "control_snapshot": snapshot,
        "control_results": results,
        "requirement_results": assessed,
        "grounding_refs": proposal.body["grounding_refs"],
        "limitation_refs": limitations,
        "status": status,
        "reason": reason,
        "fact_keys": adequacy_fact_keys(view, proposal, assessed)
        if any(row["status"] == "pass" for row in assessed) else [],
    }
    return body, checks, evidence


def admit_measure(view, attempt, resolved):
    assignment = actor(view, attempt)
    payload = exact(
        attempt.body["payload"], {"proposal_ref", "measure_ref"}, "measure admission"
    )
    proposal_ref = Ref.from_record(payload["proposal_ref"])
    proposal = view.entry("measure_proposal", proposal_ref.artifact_id.value).record
    if (
        ROLE_SPECIALIZATION[assignment.body["role"]] != "measure"
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
    body, checks, evidence = _assess_proposal(
        view, attempt, proposal, measure_ref, resolved.references["policy"]
    )
    admission = derived(view, attempt, "measure_admission", body, evidence=evidence)
    installed = {entry.record.ref for entry in view.entries("check")}
    new_checks = [check for check in checks if check.ref not in installed]
    return [*new_checks, admission], [
        index("measure", admission.artifact_id.value, admission, body["status"]),
        *(index("check", check.artifact_id.value, check) for check in new_checks),
    ]


def validate_admission(view, admission):
    """Re-derive both complete and partial adequacy at publication or credit."""
    proposal = view.read(
        Ref.from_record(admission.body["proposal_ref"]), "measure_proposal"
    )
    attempt = view.read(admission.predecessor_refs[0], "attempt")
    assignment = view.entry("invocation", admission.invocation_id.value).record
    measure_ref = Ref.from_record(admission.body["measure_ref"])
    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    from .measure_components import measure_owner

    if (
        attempt.body["action"] != "admit_measure"
        or attempt.body["payload"]
        != {
            "proposal_ref": proposal.ref.as_record(),
            "measure_ref": measure_ref.as_record(),
        }
        or attempt.invocation_id != admission.invocation_id
        or attempt.logical_unit_id != admission.logical_unit_id
        or ROLE_SPECIALIZATION[assignment.body["role"]] != "measure"
        or proposal.body["assignment_ref"] != assignment.ref.as_record()
        or admission.body["owner_assignment_ref"]
        != measure_owner(view, assignment).body["parent_assignment_ref"]
        or canonical_json(view.data(measure_ref))
        != canonical_json(definition(proposal))
    ):
        raise ValueError("measure admission has invalid provenance or definition")
    expected, checks, evidence = _assess_proposal(
        view, attempt, proposal, measure_ref, policy,
        snapshot=admission.body["control_snapshot"],
    )
    if (
        canonical_json(admission.body) != canonical_json(expected)
        or admission.evidence_refs != evidence
    ):
        raise ValueError("admitted measure differs from grounded controls")
    for check in checks:
        view.read(check.ref, "check")
