"""Admit actual observations and measure durable, non-repeatable progress."""

from agent.duet_contracts import canonical_json, content_id, digest_record
from agent.duet_store import DuetConflictError
from function_library.epistemic_contract import exact, names
from function_library.refinement_checks import resolve_predicate

from .checking import checker_definition
from .evaluation_inputs import instrument_context, semantic_inputs
from .records import Ref
from .state_machine import actor, derived, index, proposed


def dependency_hashes(check, candidate):
    paths = check.body["dependency_paths"]
    if paths is None:
        return {
            "*": digest_record({
                "files": candidate.body["files"],
                "materialization": candidate.body["materialization_ref"],
            }).value
        }
    # The empty key cannot alias a valid logical source path. A plan change can
    # change binding/prompt semantics even when every source byte is unchanged.
    return {
        "": digest_record(candidate.body["materialization_ref"]).value,
        **{path: candidate.body["files"].get(path) for path in paths},
    }


def check_fact(view, check):
    if check.body["evidence_kind"] == "materialization":
        return content_id(
            "refinement_fact",
            {
                "materialization_requirement": check.body["requirement_key"],
                "measure": check.body["measure_ref"],
                "environment": check.body["environment_ref"],
            },
        ).value
    return content_id(
        "refinement_fact",
        {
            "requirement": check.body["requirement_key"],
            "predicate": check.body["predicate_ref"],
            "expected": check.body["expected"],
            "measure": check.body["measure_ref"],
            "environment": check.body["environment_ref"],
            **(
                {
                    "instrument": instrument_context(
                        view, check.body["execution_binding"]
                    )
                }
                if "execution_binding" in check.body
                else {}
            ),
        },
    ).value


def request_evaluation(view, attempt, resolved):
    from .context import require_deliberate_retry
    from .evaluation_plan import resolve_evaluations
    from .judgment import judgment_purpose

    assignment = actor(view, attempt)
    require_deliberate_retry(view, attempt, assignment, "request_evaluation")
    exact(attempt.body["payload"], {"request"}, "evaluation submission")
    request = proposed(view, attempt, "request", "evaluation")
    if (
        request.invocation_id != attempt.invocation_id
        or request.logical_unit_id != attempt.logical_unit_id
    ):
        raise ValueError("evaluation request belongs to another invocation or unit")
    body = request.body
    candidate = view.read(Ref.from_record(body["candidate_ref"]), "candidate")
    if candidate.ref != view.candidate.ref:
        raise ValueError("new evaluation must bind the current exact candidate")
    purposes = {
        "implementer": {"local"},
        "verify": {"acceptance", "composition"},
        "measure": {"adequacy"},
        "support": {"support"},
        "question": {"question"},
    }
    if body["purpose"] not in purposes.get(assignment.body["role"], set()):
        raise ValueError("evaluation purpose violates independent judgment ownership")
    if body["purpose"] != judgment_purpose(view, assignment):
        raise ValueError("evaluation changes the judgment assigned by its parent")
    if body["measure_ref"] not in (
        assignment.body["local_measure_ref"],
        assignment.body["acceptance_measure_ref"],
    ):
        raise ValueError("evaluation tries to change its frozen measure")
    if body["environment_ref"] != view.contract.body["environment_ref"]:
        raise ValueError("new environment requires an explicit successor contract")
    investigation = assignment.body["role"] in {"support", "question"}
    keys = set(names(body["check_keys"], "checks", nonempty=investigation))
    if not investigation and "selection_check_keys" in body:
        raise ValueError("only an investigation can select a check subset")
    plans = resolve_evaluations(
        view,
        resolved.references["policy"],
        assignment,
        body["purpose"],
        selected=set(body.get("selection_check_keys", keys)) if investigation else None,
    )
    matches = [
        plan
        for plan in plans
        if keys == {check.artifact_id.value for check in plan["checks"]}
    ]
    if len(matches) != 1:
        raise ValueError("evaluation omits checks from its frozen judgment")
    plan = matches[0]
    # Harness and capability are frozen independently of a candidate's edits.
    binding = {
        key: body[key]
        for key in (
            "measure_ref",
            "harness_ref",
            "capability_ref",
            "purpose",
            "input_refs",
        )
    }
    if canonical_json(binding) != canonical_json(plan["binding"]):
        raise ValueError("evaluation harness or inputs were not admitted")
    availability = plan["availability"]
    supplied = body.get("availability")
    if supplied is None:
        # Older complete requests retain their exact v1 identity. They cannot
        # conceal an unavailable instrument by omitting the new projection.
        if not availability["executable"] or availability["gaps"]:
            raise ValueError("evaluation must preserve its host-derived gaps")
    elif canonical_json(supplied) != canonical_json(availability):
        raise ValueError("evaluation availability differs from admitted prerequisites")
    return [request], [
        index(
            "evaluation",
            request.artifact_id.value,
            request,
            "pending" if availability["executable"] else "unavailable",
        )
    ]


def observe(view, attempt, resolved):
    actor(view, attempt)
    payload = exact(
        attempt.body["payload"],
        {"request_ref", "run_id", "execution_ref", "check_key"},
        "observation submission",
    )
    request_ref = Ref.from_record(payload["request_ref"])
    request = view.entry("evaluation", request_ref.artifact_id.value).record
    if request.ref != request_ref or request.invocation_id != attempt.invocation_id:
        raise ValueError("observation belongs to another invocation's request")
    key = payload["check_key"]
    if key not in request.body["check_keys"]:
        raise ValueError("unrequested check")
    check = view.entry("check", key).record
    if check.body["evidence_kind"] != "execution":
        raise ValueError("runtime evidence cannot replace a materialization check")
    candidate = view.read(Ref.from_record(request.body["candidate_ref"]), "candidate")
    registration = resolved.references["registration"]
    binding = view.entry("evaluation_run", request.artifact_id.value).record
    if "checking_gap" in binding.body:
        raise ValueError(
            "unavailable checking is a parent decision, not an observation"
        )
    if (
        canonical_json(binding.body["registration"]) != canonical_json(registration)
        or binding.body["request_ref"] != request.ref.as_record()
        or binding.body["candidate_ref"] != candidate.ref.as_record()
    ):
        raise ValueError(
            "Run does not match the candidate and request bound before execution"
        )
    execution = resolved.references["execution"]
    if (
        execution["terminal_status"] == "succeeded"
        and checker_definition(view, request.body) is not None
        and "target_run_ref" not in binding.body
    ):
        raise ValueError(
            "successful target execution cannot replace its independent checker verdict"
        )
    if execution["terminal_status"] != "succeeded":
        outcome, observed = "error", None
    else:
        if (
            len(resolved.values) != 1
            or attempt.evidence_refs[0].store_kind != "run_audit"
        ):
            raise ValueError("check needs one committed execution observation")
        if attempt.evidence_refs[0].owner_id.value != payload["run_id"]:
            raise ValueError("observation is from a different Run")
        if (
            attempt.evidence_refs[0].record_id.value != execution["terminal_event_id"]
            or attempt.evidence_refs[0].observation_path
            != check.body["observation_path"]
        ):
            raise ValueError(
                "observation must use the frozen terminal-result projection"
            )
        observed = resolved.values[0]
        outcome = resolve_predicate(resolved.references["predicate"])(
            observed=observed, expected=check.body["expected"]
        )
        if outcome not in {"pass", "fail", "inconclusive"}:
            raise ValueError("registered predicate returned an invalid outcome")
    return _record_observation(
        view,
        attempt,
        request,
        check,
        candidate,
        payload["execution_ref"],
        observed,
        outcome,
    )


def observe_materialization(view, attempt, resolved):
    actor(view, attempt)
    payload = exact(
        attempt.body["payload"],
        {"request_ref", "check_key"},
        "materialization observation",
    )
    request_ref = Ref.from_record(payload["request_ref"])
    request = view.entry("evaluation", request_ref.artifact_id.value).record
    if request.ref != request_ref or request.invocation_id != attempt.invocation_id:
        raise ValueError("static observation belongs to another evaluation")
    key = payload["check_key"]
    if key not in request.body["check_keys"]:
        raise ValueError("unrequested static check")
    check = view.entry("check", key).record
    if check.body["evidence_kind"] != "materialization":
        raise ValueError("static evidence cannot satisfy runtime behavior")
    source = view.entry("evaluation_source", request.artifact_id.value).record
    if source.body["candidate_ref"] != request.body["candidate_ref"]:
        raise ValueError("static observation differs from admitted source candidate")
    result = resolved.references["materialization_result"]
    definition = resolved.references["predicate"]
    if (
        check.body["expected"] != {"check_id": result["check"]["check_id"]}
        or check.body["requirement_key"] != result["check"]["requirement_id"]
        or definition["definition_id"] != result["check"]["definition_id"]
        or definition["interface"] != "materialization.validation"
        or len(resolved.values) != 1
        or attempt.evidence_refs[0].store_kind != "duet_artifact"
        or Ref(
            attempt.evidence_refs[0].record_id, attempt.evidence_refs[0].content_hash
        ).as_record()
        != source.body["build_receipt_ref"]
        or attempt.evidence_refs[0].observation_path != ""
    ):
        raise ValueError(
            "static result lacks its exact frozen check or committed build evidence"
        )
    candidate = view.read(Ref.from_record(request.body["candidate_ref"]), "candidate")
    outcome = result["observation"]
    if outcome["candidate_ref"] != candidate.ref.as_record():
        raise ValueError("static result belongs to another candidate")
    return _record_observation(
        view,
        attempt,
        request,
        check,
        candidate,
        source.ref.as_record(),
        outcome,
        outcome["status"],
    )


def _record_observation(
    view, attempt, request, check, candidate, execution_ref, observed, outcome
):
    from .cycles import conflicting_observation, opposing_regressions

    key = check.artifact_id.value
    observation = derived(
        view,
        attempt,
        "observation",
        {
            "request_ref": request.ref.as_record(),
            "execution_ref": execution_ref,
            "checked_dependency_hashes": dependency_hashes(check, candidate),
            "check_key": key,
            "observed_value": observed,
            "outcome": outcome,
            "counterexample_refs": [],
            "limitation_refs": [],
        },
    )
    status = (
        outcome
        if dependency_hashes(check, candidate)
        == dependency_hashes(check, view.candidate)
        else "stale"
    )
    contradictions = conflicting_observation(view, attempt, observation)
    if contradictions and status != "stale":
        status = "contradicted"
    deltas = [
        index("observation", observation.artifact_id.value, observation),
        index("check_state", key, observation, status),
    ]
    conflicts = [*contradictions, *opposing_regressions(view, attempt, observation)]
    contradicted_refs = {
        Ref.from_record(ref)
        for conflict in contradictions
        for ref in conflict.body["observation_refs"]
    }
    for entry in view.entries("lesson"):
        if entry.status == "active" and any(
            Ref.from_record(ref) in contradicted_refs
            for ref in entry.record.body["supporting_observation_refs"]
        ):
            deltas.append(index("lesson", entry.key, entry.record, "contradicted"))
    deltas.extend(
        index("conflict", item.artifact_id.value, item, item.body["state"])
        for item in conflicts
    )
    return [observation, *conflicts], deltas


def admit_lesson(view, attempt, resolved):
    assignment = actor(view, attempt)
    payload = exact(
        attempt.body["payload"],
        {"action_class", "action_inputs", "supporting_observation_refs"},
        "lesson proposal",
    )
    if payload["action_class"] not in assignment.body["allowed_action_classes"]:
        raise ValueError("lesson cannot suppress an action outside the assignment")
    observations = []
    for reference in payload["supporting_observation_refs"]:
        ref = Ref.from_record(reference)
        observation = view.entry("observation", ref.artifact_id.value).record
        if observation.ref != ref:
            raise ValueError(
                "lesson evidence identity differs from its admitted observation"
            )
        observations.append(observation)
    if not observations or any(item.body["outcome"] != "fail" for item in observations):
        raise ValueError("a failure lesson requires decisive committed counterevidence")
    proposed_evidence = {item.ref for item in observations}
    if any(
        entry.record.body["kind"] == "dependency_conflict"
        and any(
            Ref.from_record(ref) in proposed_evidence
            for ref in entry.record.body["observation_refs"]
        )
        for entry in view.entries("conflict")
    ):
        raise ValueError(
            "contradictory evidence cannot support a determinate failure lesson"
        )
    requirements = set()
    requests = []
    for observation in observations:
        check = view.entry("check", observation.body["check_key"]).record
        requirements.add(check.body["requirement_key"])
        request = view.read(
            Ref.from_record(observation.body["request_ref"]), "evaluation"
        )
        requests.append(request)
        if request.body["environment_ref"] != view.contract.body["environment_ref"]:
            raise ValueError("lesson conditions do not match its evidence")
    if not requirements.issubset(assignment.body["scope_requirement_keys"]):
        raise ValueError("lesson extends beyond the assigned scope")
    # v1 admits only a narrow reproducible claim: this exact candidate has failed
    # these checks. It does NOT infer that every implementation of an approach fails.
    candidates = {canonical_json(request.body["candidate_ref"]) for request in requests}
    if len(candidates) != 1:
        raise ValueError("lesson must state exact common candidate conditions")
    candidate = view.read(
        Ref.from_record(requests[0].body["candidate_ref"]), "candidate"
    )
    conditions = {
        "files": candidate.body["files"],
        "materialization_ref": candidate.body["materialization_ref"],
        "check_facts": sorted({
            check_fact(view, view.entry("check", observation.body["check_key"]).record)
            for observation in observations
        }),
    }
    fact_keys = sorted({
        content_id(
            "negative_fact",
            {
                "criterion": check_fact(
                    view, view.entry("check", observation.body["check_key"]).record
                ),
                "inputs": semantic_inputs(view, request.body),
                "environment": request.body["environment_ref"],
            },
        ).value
        for observation, request in zip(observations, requests)
    })
    key = content_id(
        "lesson_equivalence",
        {
            "requirements": sorted(requirements),
            # A new file hash is new provenance, not a new negative insight.
            # v1 values the first demonstrated failure of these exact criteria
            # and inputs, not arbitrary wrong answers or cosmetic code variants.
            "fact_keys": fact_keys,
        },
    ).value
    if any(
        entry.record.body["equivalence_key"] == key
        and canonical_json(entry.record.body["action_inputs"])
        == canonical_json(conditions)
        for entry in view.entries("lesson")
    ):
        return [], []
    lesson = derived(
        view,
        attempt,
        "lesson",
        {
            "requirement_keys": sorted(requirements),
            "action_class": "request_evaluation",
            "action_inputs": conditions,
            "environment_ref": view.contract.body["environment_ref"],
            "supporting_observation_refs": [
                item.ref.as_record() for item in observations
            ],
            "policy_effect": {
                "kind": "advisory_repetition",
                "failed_candidate": candidate.ref.as_record(),
            },
            "reopening_conditions": [
                "candidate_content_changed",
                "criterion_changed",
                "environment_changed",
                "independent_counterevidence",
            ],
            "equivalence_key": key,
            "fact_keys": fact_keys,
        },
        evidence=tuple(
            dict.fromkeys(ref for item in observations for ref in item.evidence_refs)
        ),
    )
    return [lesson], [index("lesson", lesson.artifact_id.value, lesson)]


def close_unit(view, attempt, resolved):
    from function_library.refinement_control import SEMANTIC_YIELD, resolve_selection
    from .control import numerical_decision, observation_inputs
    from .coordination import pending_decisions
    from .evaluation_admission import source_decision
    from .evaluation_plan import unavailable_request
    from .materialization import baseline_fact_keys
    from .judgment import operative_check_facts, parent_assessments
    from .measures import admission_decision, unit_admissions
    from .measure_needs import unit_prerequisite
    from .prerequisites import parent_prerequisites
    from .succession import credited_facts

    assignment = actor(view, attempt)
    payload = exact(
        attempt.body["payload"],
        {"candidate_before_ref", "continuation_ref"},
        "unit close",
    )
    unit = attempt.logical_unit_id.value
    unit_key = content_id(
        "unit_key", {"invocation": attempt.invocation_id.value, "unit": unit}
    ).value
    if any(entry.key == unit_key for entry in view.entries("unit")):
        raise DuetConflictError("logical unit has already closed")
    view.read(Ref.from_record(payload["candidate_before_ref"]), "candidate")
    if payload["continuation_ref"] is not None:
        raise ValueError("only the host may compute or bind a continuation decision")
    lineage = assignment.body["judgment_lineage"]
    credited = credited_facts(view, assignment)
    baseline_keys = baseline_fact_keys(view, assignment)
    assessments = parent_assessments(view, attempt, assignment)
    prerequisites = parent_prerequisites(view, attempt, assignment)
    facts = {}
    for key, records in operative_check_facts(view, assignment, assessments).items():
        # A parent's assessment belongs to this unit and cites the original
        # verifier observations. Merely importing another unit's pass does not.
        for record in records:
            if (
                record.invocation_id == attempt.invocation_id
                and record.logical_unit_id == attempt.logical_unit_id
            ):
                facts[key] = record
                break
    lessons = [
        entry
        for entry in view.entries("lesson")
        if entry.status == "active"
        and entry.record.invocation_id == attempt.invocation_id
        and entry.record.logical_unit_id == attempt.logical_unit_id
    ]
    for entry in lessons:
        for key in entry.record.body["fact_keys"]:
            facts[key] = entry.record
    for admission in unit_admissions(view, attempt):
        if admission.body["status"] == "admitted":
            for key in admission.body["fact_keys"]:
                facts[key] = admission
    for assessment in prerequisites:
        for key in assessment.body["fact_keys"]:
            facts[key] = assessment
    fresh = {
        key: record
        for key, record in facts.items()
        if key not in credited | baseline_keys
    }
    conflicts = pending_decisions(view, attempt.invocation_id.value)
    previous = [
        entry
        for entry in view.entries("unit")
        if entry.record.invocation_id == attempt.invocation_id
    ]
    policy = resolved.references["policy"]
    measurement = resolve_selection(policy["yield_function"], SEMANTIC_YIELD)(
        prior_fact_keys=sorted(credited),
        admitted_fact_keys=sorted(fresh),
    )
    active_keys, usable = observation_inputs(
        view, attempt, assignment, assessments, prerequisites
    )
    decision = derived(
        view,
        attempt,
        "continuation",
        numerical_decision(view, assignment, policy, active_keys, usable=usable),
    )
    disposition = "continuing"
    source_request = (
        source_decision(view, attempt)
        or admission_decision(view, attempt)
        or unit_prerequisite(view, attempt)
        or unavailable_request(view, attempt)
    )
    if conflicts or source_request is not None:
        disposition = "needs_parent_decision"
    elif decision.body["stop"]:
        disposition = (
            "attained" if decision.body["attained"] else "yield_exhausted_unresolved"
        )
    receipt = derived(
        view,
        attempt,
        "unit_receipt",
        {
            "assignment_ref": assignment.ref.as_record(),
            "invocation_id": attempt.invocation_id.value,
            "logical_unit_id": unit,
            "ordinal": len(previous),
            "stage_receipt_refs": [
                view.read(row[0], "commit").ref.as_record()
                for row in view.connection.execute(
                    "SELECT commit_id FROM refinement_operations WHERE campaign_id = ? "
                    "AND invocation_id = ? AND logical_unit_id = ? AND commit_id IS NOT NULL ORDER BY rowid",
                    (
                        view.campaign_id.value,
                        attempt.invocation_id.value,
                        attempt.logical_unit_id.value,
                    ),
                )
            ],
            "candidate_before_ref": payload["candidate_before_ref"],
            "candidate_after_ref": view.candidate.ref.as_record(),
            "evaluation_refs": [
                entry.record.ref.as_record()
                for entry in view.entries("observation")
                if entry.record.logical_unit_id == attempt.logical_unit_id
                and entry.record.invocation_id == attempt.invocation_id
            ],
            "assessment_refs": [item.ref.as_record() for item in assessments],
            "prerequisite_assessment_refs": [
                item.ref.as_record() for item in prerequisites
            ],
            "invalidated_check_keys": [
                entry.key
                for entry in view.entries("check_state")
                if entry.status == "stale"
            ],
            "conflict_refs": [item.ref.as_record() for item in conflicts],
            "lesson_refs": [entry.record.ref.as_record() for entry in lessons],
            **measurement,
            "continuation_ref": decision.ref.as_record(),
            "disposition": disposition,
            "decision_request_ref": conflicts[0].ref.as_record()
            if conflicts
            else source_request.ref.as_record()
            if source_request
            else None,
        },
        evidence=tuple(
            dict.fromkeys(
                ref for record in fresh.values() for ref in record.evidence_refs
            )
        ),
    )
    deltas = [index("unit", unit_key, receipt)]
    if disposition != "continuing":
        deltas.append(
            index("invocation", attempt.invocation_id.value, assignment, disposition)
        )
    deltas.extend(
        {
            "kind": "credit",
            "lineage": lineage,
            "key": key,
            "record_id": record.artifact_id.value,
            "receipt_id": receipt.artifact_id.value,
        }
        for key, record in fresh.items()
    )
    return [*assessments, *prerequisites, decision, receipt], deltas
