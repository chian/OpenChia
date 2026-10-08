"""Connect Measure-authored programs to shared execution and ordinary credit.

Review freezes the program and fixtures. The common harness executes them;
admission re-derives the exact inputs and reads its receipts. Candidate results
use the usual observation ledger, dependency invalidation and parent judgment.
"""

from agent.duet_contracts import canonical_json
from agent.episode_contracts import OpaqueId
from episode_runtime.testing_harness.checker_programs import execute_program
from episode_runtime.testing_harness.judgments import judge_value
from function_library.epistemic_contract import exact
from function_library.refinement_contract import ROLE_SPECIALIZATION

from .records import EvidenceRef, Ref


def instrument(view, binding):
    value = view.data(Ref.from_record(binding["harness_ref"]))
    if value.get("execution_kind") != "checking_program":
        return None
    exact(value, {"execution_kind", "definition_ref", "target_workflow_ref", "readable_paths", "input"}, "checking program binding")
    from .measure_design import reviewed

    definition = view.read(Ref.from_record(value["definition_ref"]), "measure_definition")
    assignment = view.read(Ref.from_record(definition.body["assignment_ref"]), "assignment")
    reviewed(view, value["definition_ref"], assignment)
    from .measure_components import readable_paths

    if (value["target_workflow_ref"] != view.contract.body["target_workflow_ref"]
            or sorted(value["readable_paths"]) != readable_paths(view, assignment)
            or definition.body["design"]["program"] is None):
        raise ValueError("checking program differs from its reviewed scope")
    return value, definition.body["design"]["program"]


def candidate_fixture(view, reader, candidate, harness):
    from .materialization_edits import stored_plan

    return {
        "files": {path: reader.builds.read_blob(candidate.body["files"][path]).decode("utf-8")
                  for path in harness["readable_paths"] if path in candidate.body["files"]},
        "materialization": stored_plan(view, candidate),
        "input": harness["input"],
    }


def coding_references(view, policy, assignment):
    """Expose the assigned local predicates as protected diagnostic sources.

    The evaluation resolver owns selection. These copies explain the actual
    check input; host execution still uses the immutable reviewed instrument.
    """
    from .evaluation_plan import resolve_evaluations
    from .materialization_edits import stored_plan
    from .report_contract import requirement_address, requirement_catalog

    catalog = requirement_catalog(view)
    files, programs = {}, {}
    for plan in resolve_evaluations(view, policy, assignment, "local"):
        if not plan["availability"]["executable"]:
            continue
        selected = instrument(view, plan["binding"])
        if selected is None:
            continue
        harness, program = selected
        definition_id = harness["definition_ref"]["artifact_id"]
        if definition_id not in programs:
            directory = f".openchia-local-checks/program_{len(programs) + 1}"
            paths = {name: f"{directory}/{name}" for name in program["files"]}
            files.update({paths[name]: source for name, source in program["files"].items()})
            programs[definition_id] = {
                "definition_ref": harness["definition_ref"],
                "directory": directory, "entrypoint": program["entrypoint"],
                "files": paths, "cases": [],
                "materialization_file": ".openchia-local-checks/materialization.json",
            }
        item = programs[definition_id]
        input_file = f"{item['directory']}/.openchia-case-{len(item['cases']) + 1}.json"
        if input_file in files:
            raise ValueError("checking program overlaps coding reference metadata")
        files[input_file] = canonical_json(harness["input"])
        item["cases"].append({
            "input_file": input_file,
            "readable_source_paths": list(harness["readable_paths"]),
            "checks": [{
                "requirement": requirement_address(catalog[check.body["requirement_key"]]),
                "observation_path": check.body["observation_path"],
                "predicate": view.data(Ref.from_record(check.body["predicate_ref"])),
                "expected": check.body["expected"],
            } for check in plan["checks"]],
        })
    if programs:
        files[".openchia-local-checks/materialization.json"] = canonical_json(
            stored_plan(view, view.candidate)
        )
    return list(programs.values()), files


def subject(view, call, *, candidate=None, check=None, proposal=None, grounding=None, control=None):
    return {
        "campaign_id": view.campaign_id.value,
        "invocation_id": call.invocation_id.value,
        "unit_id": call.unit_id.value,
        **({"candidate_ref": candidate.ref.as_record(), "check_ref": check.ref.as_record()}
           if candidate is not None else {
               "proposal_ref": proposal.ref.as_record(), "grounding_ref": grounding.as_record(),
               "control_ref": control.as_record(),
           }),
    }


def _saved(view, expected):
    rows = view.connection.execute(
        "SELECT artifact_id, content_hash FROM artifacts WHERE duet_id = ? AND kind = ? "
        "AND json_extract(record_json, '$.subject.campaign_id') = ? "
        "AND json_extract(record_json, '$.subject.invocation_id') = ? "
        "AND json_extract(record_json, '$.subject.unit_id') = ? ORDER BY rowid DESC",
        (view.head["duet_id"], "refinement.checker_result.v1", view.campaign_id.value,
         expected["invocation_id"], expected["unit_id"]),
    )
    for row in rows:
        record = view.data(Ref.from_record({"artifact_id": row[0], "content_hash": row[1]}))
        if canonical_json(record["subject"]) == canonical_json(expected):
            return record["execution_ref"]
    return None


def _evidence(view, reference):
    reference = Ref.from_record(reference)
    return EvidenceRef("duet_artifact", OpaqueId(view.head["duet_id"]),
                       reference.artifact_id, reference.content_hash, "")


def _control_jobs(view, policy, proposal):
    from .measure_admission import grounded_cases
    from types import SimpleNamespace

    call = SimpleNamespace(invocation_id=proposal.invocation_id, unit_id=proposal.logical_unit_id)
    cases, _, _ = grounded_cases(view, proposal, policy)
    jobs = []
    for grounding_ref, grounding in cases:
        _, program = instrument(view, grounding["execution_binding"])
        for field in ("positive_control_refs", "negative_control_refs"):
            for raw in grounding[field]:
                control_ref = Ref.from_record(raw)
                control = view.data(control_ref)
                expected = subject(view, call, proposal=proposal, grounding=grounding_ref, control=control_ref)
                jobs.append((program, control["fixture"], expected))
    return jobs


async def prepare(evaluations, session, call, payload):
    """Execute outside the campaign transaction; admission consumes exact receipts."""
    with session.view() as view:
        candidate = view.candidate
        if ROLE_SPECIALIZATION[call.assignment.body["role"]] == "measure" and "proposal_ref" in payload:
            proposal = view.read(Ref.from_record(payload["proposal_ref"]), "measure_proposal")
            if proposal.body["oracle_kind"] != "checking_program":
                return
            if proposal.body["assignment_ref"] != call.assignment.ref.as_record():
                raise ValueError("checking controls belong to another Measure")
            try:
                jobs = _control_jobs(view, session.policy, proposal)
            except (ValueError, KeyError, TypeError):
                # Admission records the rejected proposal through the ordinary
                # feedback path. Invalid controls never reach execution.
                return
        else:
            _, plans = evaluations._plans(session, call, payload)
            jobs = []
            for plan in plans:
                if not plan["availability"]["executable"]:
                    continue
                selected = instrument(view, plan["binding"])
                if selected is None:
                    continue
                harness, program = selected
                fixture = candidate_fixture(view, session.store.evidence, candidate, harness)
                for check in plan["checks"]:
                    jobs.append((program, fixture, subject(view, call, candidate=candidate, check=check)))
    if not jobs:
        return
    for program, fixture, expected in jobs:
        with session.view() as view:
            if _saved(view, expected) is not None:
                continue
        execution = await execute_program(
            executor=evaluations.executor, artifacts=session.store.evidence.duets,
            builds=evaluations.builder.store, runs=session.store.evidence.runs,
            duet_id=session.duet_id, program=program, fixture=fixture, subject=expected,
            environment_service=evaluations.environment_service(session),
        )
        session.put_data("checker_result", {"subject": expected, "execution_ref": execution})


def control_results(view, proposal, grounding_ref, grounding, selection, *, snapshot=None):
    """Require real discrimination by the exact reviewed program, not example labels."""
    from types import SimpleNamespace
    from .measure_controls import control_key

    call = SimpleNamespace(invocation_id=proposal.invocation_id, unit_id=proposal.logical_unit_id)
    _, program = instrument(view, grounding["execution_binding"])
    results, evidence = [], []
    for field, polarity in (("positive_control_refs", "pass"), ("negative_control_refs", "fail")):
        for raw in grounding[field]:
            ref = Ref.from_record(raw)
            control = exact(view.data(ref), {"fixture", "expected_outcome"}, "checking fixture")
            if control["expected_outcome"] != polarity:
                raise ValueError("checker control changes its reviewed polarity")
            expected = subject(view, call, proposal=proposal, grounding=grounding_ref, control=ref)
            execution = (_saved(view, expected) if snapshot is None else
                         snapshot.get(control_key(proposal.ref, grounding_ref, ref)))
            if execution is None:
                results.append({"control_ref": raw, "expected": polarity,
                                "observed": None, "status": "blocked",
                                "reason": "checking program has no executed control receipt"})
                continue
            # Read through the same transaction; generated code never has this connection.
            outcome = _read_execution(view, execution, program=program, fixture=control["fixture"], subject=expected)
            actual = (judge_value(selection, observed=outcome["result"], expected=grounding["expected"])
                      if outcome["status"] == "completed" else "error")
            status = "error" if actual == "error" else "pass" if actual == polarity else "fail"
            results.append({
                "control_ref": raw, "expected": polarity, "observed": actual,
                "status": status,
                "reason": None if status == "pass" else (
                    f"checking control expected {polarity}, observed {actual}: {outcome['diagnostics']}"
                ),
            })
            evidence.append(_evidence(view, execution))
    return results, evidence


def _read_execution(view, reference, **expected):
    # CampaignView deliberately exposes a transaction-bound data reader, not a
    # separate DuetStore. Recheck the two immutable envelopes and exact inputs.
    value = view.data(Ref.from_record(reference))
    row = view.connection.execute("SELECT kind FROM artifacts WHERE artifact_id = ?", (reference["artifact_id"],)).fetchone()
    if row is None or row[0] != "experiment.checker_execution.v1":
        raise ValueError("checking receipt is not host execution evidence")
    inputs_ref = Ref.from_record(value["intent_ref"])
    inputs = view.data(inputs_ref)
    row = view.connection.execute("SELECT kind FROM artifacts WHERE artifact_id = ?", (inputs_ref.artifact_id.value,)).fetchone()
    if row is None or row[0] != "experiment.checker_inputs.v1":
        raise ValueError("checking receipt lacks host-recorded inputs")
    if any(canonical_json(inputs[key]) != canonical_json(item) for key, item in expected.items()):
        raise ValueError("checking receipt differs from its exact subject or reviewed input")
    return value


def control_context(view, proposals):
    """Return the current authored instrument's actual controls and diagnostics."""
    from types import SimpleNamespace
    from .report_contract import requirement_address, requirement_catalog

    catalog = requirement_catalog(view)
    result = []
    for proposal in proposals:
        if proposal.body["oracle_kind"] != "checking_program":
            continue
        call = SimpleNamespace(invocation_id=proposal.invocation_id, unit_id=proposal.logical_unit_id)
        selection = view.data(Ref.from_record(proposal.body["decision_function_ref"]))
        for raw in proposal.body["grounding_refs"]:
            grounding_ref = Ref.from_record(raw)
            grounding = view.data(grounding_ref)
            _, program = instrument(view, grounding["execution_binding"])
            for field, polarity in (("positive_control_refs", "pass"), ("negative_control_refs", "fail")):
                for control_raw in grounding[field]:
                    control_ref = Ref.from_record(control_raw)
                    expected = subject(view, call, proposal=proposal, grounding=grounding_ref, control=control_ref)
                    reference = _saved(view, expected)
                    if reference is None:
                        continue
                    control = view.data(control_ref)
                    execution = _read_execution(view, reference, program=program, fixture=control["fixture"], subject=expected)
                    result.append({
                        "requirement": requirement_address(catalog[grounding["requirement_key"]]),
                        "expected_outcome": polarity,
                        "outcome": judge_value(selection, observed=execution["result"], expected=grounding["expected"])
                        if execution["status"] == "completed" else "error",
                        "status": execution["status"], "diagnostics": execution["diagnostics"],
                        "log_refs": execution["log_refs"],
                    })
    return result


def observe_prepared(session, call, request, candidate, checks):
    for check in checks:
        with session.view() as view:
            expected = subject(view, call, candidate=candidate, check=check)
            execution = _saved(view, expected)
            if execution is None:
                raise ValueError("candidate checking has no prepared execution receipt")
            evidence = _evidence(view, execution)
        session.commit(call, "observe_checker", {
            "request_ref": request.ref.as_record(), "check_key": check.artifact_id.value,
            "execution_ref": execution,
        }, evidence=(evidence,))


def verified_observation(view, attempt, resolved):
    from types import SimpleNamespace

    payload = exact(attempt.body["payload"], {"request_ref", "check_key", "execution_ref"}, "checker observation")
    request_ref = Ref.from_record(payload["request_ref"])
    request = view.entry("evaluation", request_ref.artifact_id.value).record
    check = view.entry("check", payload["check_key"]).record
    if (request.ref != request_ref or request.invocation_id != attempt.invocation_id
            or request.logical_unit_id != attempt.logical_unit_id
            or check.artifact_id.value not in request.body["check_keys"]
            or check.body["evidence_kind"] != "checking_program"):
        raise ValueError("checker observation is outside its exact request")
    candidate = view.read(Ref.from_record(request.body["candidate_ref"]), "candidate")
    harness, program = instrument(view, request.body)
    expected = subject(view, SimpleNamespace(invocation_id=attempt.invocation_id, unit_id=attempt.logical_unit_id),
                       candidate=candidate, check=check)
    # Cross-store candidate bytes were read outside the writer transaction.
    fixture = resolved.references["checker_fixture"]
    if payload["execution_ref"] != _saved(view, expected) or attempt.evidence_refs != (_evidence(view, payload["execution_ref"]),):
        raise ValueError("checker observation lacks its exact execution evidence")
    execution = _read_execution(view, payload["execution_ref"], program=program, fixture=fixture, subject=expected)
    selection = view.data(Ref.from_record(check.body["predicate_ref"]))
    outcome = (judge_value(selection, observed=execution["result"], expected=check.body["expected"])
               if execution["status"] == "completed" else "error")
    return request, check, candidate, execution, outcome


def observe(view, attempt, resolved):
    from .state_machine import actor
    from .measurement import _record_observation

    actor(view, attempt)
    request, check, candidate, execution, outcome = verified_observation(view, attempt, resolved)
    return _record_observation(view, attempt, request, check, candidate, attempt.body["payload"]["execution_ref"],
                               execution["result"] if outcome != "error" else execution["diagnostics"], outcome)
