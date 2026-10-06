"""Admit and observe executable checker controls in the shared campaign ledger.

This module does not launch processes. The common evaluation service uses the
existing executor; these operations bind independently supplied fixtures to its
actual Runs. Control observations never count as repaired target behavior.
"""

from collections.abc import Mapping

from agent.duet_contracts import canonical_json, content_id
from agent.episode_contracts import OpaqueId
from episode_runtime.contracts import RunRegistration
from function_library.epistemic_contract import exact
from episode_runtime.testing_harness.judgments import judge_value

from .checking import admitted_build, checker_definition, prepare_checker_inputs
from .records import Ref, RefinementRecord, project
from .state_machine import actor, derived, index, proposed


def control_definition(view, reference, expected):
    control = exact(
        view.data(reference),
        {"typed_status", "expected_outcome"},
        "independent executable control",
    )
    if (
        not isinstance(control["typed_status"], Mapping)
        or control["expected_outcome"] != expected
    ):
        raise ValueError(
            "executable control must retain its independently supplied input and polarity"
        )
    return control


def control_key(proposal_ref, grounding_ref, control_ref):
    return content_id(
        "refinement_control",
        {
            "proposal": proposal_ref.as_record(),
            "grounding": grounding_ref.as_record(),
            "control": control_ref.as_record(),
        },
    ).value


def control_request(view, proposal_ref, grounding_ref, control_ref):
    from .measure_admission import grounded_cases

    proposal = view.entry("measure_proposal", proposal_ref.artifact_id.value).record
    if (
        proposal.ref != proposal_ref
        or proposal.body["oracle_kind"] != "independent_execution"
    ):
        raise ValueError(
            "control execution requires an exact independent-execution proposal"
        )
    policy = view.data(Ref.from_record(view.contract.body["policy_bundle_ref"]))
    cases, _, _ = grounded_cases(view, proposal, policy)
    matches = [case for ref, case in cases if ref == grounding_ref]
    if len(matches) != 1:
        raise ValueError("control grounding is outside the proposed complete case set")
    grounding = matches[0]
    polarities = [
        outcome
        for field, outcome in (
            ("positive_control_refs", "pass"),
            ("negative_control_refs", "fail"),
        )
        if control_ref.as_record() in grounding[field]
    ]
    if len(polarities) != 1:
        raise ValueError(
            "control must have exactly one independently assigned polarity"
        )
    control = control_definition(view, control_ref, polarities[0])
    return (
        proposal,
        grounding,
        control,
        checker_definition(view, grounding["execution_binding"]),
    )


def prepare_control(
    reader, campaign_id, proposal_ref, grounding_ref, control_ref, *, request_id
):
    from .campaign_store import CampaignView

    with reader.duets.transaction() as connection:
        view = CampaignView(connection, campaign_id)
        _, _, control, checker = control_request(
            view, proposal_ref, grounding_ref, control_ref
        )
    return prepare_checker_inputs(
        reader,
        campaign_id,
        checker,
        control["typed_status"],
        request_id=request_id,
        input_evidence_ref=control_ref.as_record(),
    )


def bind_control(view, attempt, resolved):
    assignment = actor(view, attempt)
    exact(attempt.body["payload"], {"binding"}, "measure control binding")
    binding = proposed(view, attempt, "binding", "measure_control_run")
    body = binding.body
    references = [
        Ref.from_record(body[field])
        for field in ("proposal_ref", "grounding_ref", "control_ref")
    ]
    proposal, _, _, _ = control_request(view, *references)
    if (
        assignment.body["role"] != "measure"
        or proposal.body["assignment_ref"] != assignment.ref.as_record()
        or binding.invocation_id != attempt.invocation_id
        or binding.logical_unit_id != attempt.logical_unit_id
    ):
        raise ValueError(
            "only the assigned measure child may execute its proposed controls"
        )
    key = control_key(*references)
    if any(row.key == key for row in view.entries("measure_control")):
        raise ValueError("this proposal's control already has a bound execution or gap")
    if canonical_json(body["gap"]) != canonical_json(
        resolved.references["control_gap"]
    ):
        raise ValueError("control availability differs from actual checker preparation")
    if body["gap"] is None:
        if canonical_json(body["registration"]) != canonical_json(
            resolved.references["admitted_registration"]
        ) or canonical_json(body["registration"]["launch_request"]) != canonical_json(
            resolved.references["control_launch"]
        ):
            raise ValueError(
                "control Run differs from its approved source or exact fixture input"
            )
        if "experiment_ref" in body:
            dispatch = view.data(Ref.from_record(body["experiment_ref"]))
            subject = dispatch["plan"].get("subject", {})
            target = view.data(Ref.from_record(subject["reference"]))
            if (
                subject.get("kind") != "grounded_control"
                or dispatch["spec"]["mode"] not in {"live_fresh", "live_saved"}
                or canonical_json(dispatch["registration"]) != canonical_json(body["registration"])
                or any(target[field] != body[field] for field in ("proposal_ref", "grounding_ref", "control_ref"))
            ):
                raise ValueError("control binding does not retain its exact shared live experiment")
    elif body["registration"] is not None:
        raise ValueError("an unavailable control cannot claim a Run registration")
    return [binding], [
        index(
            "measure_control",
            key,
            binding,
            "pending" if body["gap"] is None else "unavailable",
        )
    ]


def observe_control(view, attempt, resolved):
    assignment = actor(view, attempt)
    payload = exact(
        attempt.body["payload"],
        {"control_run_ref", "run_id", "execution_ref"},
        "measure control observation",
    )
    binding = view.read(
        Ref.from_record(payload["control_run_ref"]), "measure_control_run"
    )
    references = [
        Ref.from_record(binding.body[field])
        for field in ("proposal_ref", "grounding_ref", "control_ref")
    ]
    proposal, grounding, _, _ = control_request(view, *references)
    entry = view.entry("measure_control", control_key(*references))
    if (
        assignment.body["role"] != "measure"
        or proposal.body["assignment_ref"] != assignment.ref.as_record()
        or entry.status != "pending"
        or entry.record.ref != binding.ref
        or binding.invocation_id != attempt.invocation_id
        or binding.logical_unit_id != attempt.logical_unit_id
        or canonical_json(binding.body["registration"])
        != canonical_json(resolved.references["registration"])
    ):
        raise ValueError(
            "control observation has another owner, Run, or lifecycle state"
        )
    execution = resolved.references["execution"]
    outcome, observed, error = "error", None, execution["terminal_status"]
    if execution["terminal_status"] == "succeeded":
        if len(attempt.evidence_refs) != 1 or len(resolved.values) != 1:
            raise ValueError("checker control needs one actual terminal observation")
        evidence = attempt.evidence_refs[0]
        if (
            evidence.store_kind != "run_audit"
            or evidence.owner_id.value != payload["run_id"]
            or evidence.record_id.value != execution["terminal_event_id"]
            or evidence.observation_path != ""
        ):
            raise ValueError(
                "control observation must use its frozen terminal-result projection"
            )
        selection = view.data(Ref.from_record(proposal.body["decision_function_ref"]))
        try:
            observed = project(resolved.values[0], grounding["observation_path"])
            outcome = judge_value(
                selection, observed=observed, expected=grounding["expected"]
            )
            error = None
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            # The original terminal event remains evidence. Missing/wrong-typed
            # output is inadequate checking, never an invented verdict.
            outcome, observed, error = "error", None, str(exc)
        if outcome not in {"pass", "fail", "inconclusive", "error"}:
            raise ValueError("control predicate returned an invalid outcome")
    elif attempt.evidence_refs:
        raise ValueError("unsuccessful control Run cannot claim a result observation")
    observation = derived(
        view,
        attempt,
        "measure_control_observation",
        {
            "control_run_ref": binding.ref.as_record(),
            "execution_ref": payload["execution_ref"],
            "observed_value": observed,
            "outcome": outcome,
            "error": error,
        },
    )
    return [observation], [index("measure_control", entry.key, observation, "observed")]


def control_results(view, proposal, grounding_ref, grounding, selection):
    results, evidence = [], []
    rows = {row.key: row for row in view.entries("measure_control")}
    for field, expected in (
        ("positive_control_refs", "pass"),
        ("negative_control_refs", "fail"),
    ):
        for raw in grounding[field]:
            reference = Ref.from_record(raw)
            control_definition(view, reference, expected)
            entry = rows.get(control_key(proposal.ref, grounding_ref, reference))
            if entry is None:
                raise ValueError("checker adequacy has an unexecuted required control")
            if entry.status == "unavailable":
                gap = entry.record.body["gap"]
                raise ValueError(
                    f"control {reference.artifact_id.value}: {gap['kind']}: {gap['detail']}"
                )
            if entry.status != "observed":
                raise ValueError(
                    "checker adequacy requires all actual control observations"
                )
            observation = entry.record
            binding = view.read(
                Ref.from_record(observation.body["control_run_ref"]),
                "measure_control_run",
            )
            if any(
                binding.body[field] != ref.as_record()
                for field, ref in (
                    ("proposal_ref", proposal.ref),
                    ("grounding_ref", grounding_ref),
                    ("control_ref", reference),
                )
            ):
                raise ValueError(
                    "control observation belongs to another proposal or case"
                )
            if observation.body["outcome"] == "error" or not observation.evidence_refs:
                raise ValueError(
                    f"checker control has no adequate observation: {observation.body['error']}"
                )
            actual = judge_value(
                selection,
                observed=observation.body["observed_value"],
                expected=grounding["expected"],
            )
            if actual != expected or actual != observation.body["outcome"]:
                raise ValueError(
                    f"control {reference.artifact_id.value} requires {expected}; actual checker yielded {actual}"
                )
            results.append({
                "control_ref": raw,
                "expected": expected,
                "observed": actual,
                "control_run_ref": binding.ref.as_record(),
                "observation_ref": observation.ref.as_record(),
            })
            evidence.extend(observation.evidence_refs)
    return results, evidence


def control_run_refs(view, proposal):
    records = []
    for entry in view.entries("measure_control"):
        binding = (
            entry.record
            if entry.record.kind == "measure_control_run"
            else view.read(
                Ref.from_record(entry.record.body["control_run_ref"]),
                "measure_control_run",
            )
        )
        if binding.body["proposal_ref"] == proposal.ref.as_record():
            records.append(binding.ref.as_record())
    return records


def validated_control_facts(view, *, assignment_ref=None, proposal_ref=None):
    """Distinct grounded behavior, independent of proposal or unit identity."""
    facts = {}
    for entry in view.entries("measure_control"):
        if entry.status != "observed":
            continue
        observation = entry.record
        binding = view.read(Ref.from_record(observation.body["control_run_ref"]), "measure_control_run")
        if "experiment_ref" not in binding.body or not observation.evidence_refs:
            continue
        proposal, grounding, control, _ = control_request(
            view, *(Ref.from_record(binding.body[field]) for field in ("proposal_ref", "grounding_ref", "control_ref"))
        )
        if (assignment_ref is not None and proposal.body["assignment_ref"] != assignment_ref.as_record()) or (proposal_ref is not None and proposal.ref != proposal_ref):
            continue
        selection = view.data(Ref.from_record(proposal.body["decision_function_ref"]))
        if observation.body["outcome"] != control["expected_outcome"] or judge_value(selection, observed=observation.body["observed_value"], expected=grounding["expected"]) != control["expected_outcome"]:
            continue
        experiment = view.data(Ref.from_record(binding.body["experiment_ref"]))
        registration = binding.body["registration"]
        boundary = registration["execution_scope"]["boundary"]
        fact = content_id("refinement_fact", {
            "kind": "validated_grounded_control_v1",
            "source_files": experiment["plan"]["candidate"]["source_files"],
            "workflow_hash": registration["workflow_hash"],
            "entry_path": boundary["path_local_ids"],
            "goal_context": boundary["goals"],
            "mapped_input": boundary["input_payload"],
            "requirement_key": grounding["requirement_key"],
            "input_domain_ref": proposal.body["input_domain_ref"],
            "predicate": selection,
            "predicate_expected": grounding["expected"],
            "required_outcome": control["expected_outcome"],
            "observation_path": grounding["observation_path"],
            "environment_ref": experiment["spec"]["environment_ref"],
            # Fresh and saved-input live Runs exercise the same exact case.
            # Changing input selection syntax cannot manufacture another fact.
            "execution_mode": "live",
        }).value
        facts[fact] = observation
    return facts


def control_context(view, proposal_refs):
    """Small original verdicts for the current designer/measure context."""
    selected = set(proposal_refs)
    results = []
    for entry in view.entries("measure_control"):
        observed = entry.status == "observed"
        binding = (
            view.read(
                Ref.from_record(entry.record.body["control_run_ref"]),
                "measure_control_run",
            )
            if observed
            else entry.record
        )
        if Ref.from_record(binding.body["proposal_ref"]) not in selected:
            continue
        results.append({
            "control_run_ref": binding.ref.as_record(),
            "proposal_ref": binding.body["proposal_ref"],
            "grounding_ref": binding.body["grounding_ref"],
            "control_ref": binding.body["control_ref"],
            "status": entry.status,
            "gap": binding.body["gap"],
            "observation_ref": entry.record.ref.as_record() if observed else None,
            "outcome": entry.record.body["outcome"] if observed else None,
            "error": entry.record.body["error"] if observed else None,
        })
    return results[-12:]


def final_control_rows(view, check_refs):
    """Retain the original adequacy evidence for each used admitted measure."""
    selected = set(map(Ref.from_record, check_refs))
    admissions = {}
    for entry in view.entries("measure"):
        reference = Ref.from_record(entry.record.body["measure_ref"])
        if entry.status == "admitted" and selected.intersection(
            map(Ref.from_record, entry.record.body["check_refs"])
        ):
            admissions.setdefault(reference, entry.record)
    rows = []
    for admission in admissions.values():
        for result in admission.body["control_results"]:
            if "control_run_ref" not in result:
                continue
            binding = view.read(
                Ref.from_record(result["control_run_ref"]), "measure_control_run"
            )
            observation = view.read(
                Ref.from_record(result["observation_ref"]),
                "measure_control_observation",
            )
            if (
                observation.body["control_run_ref"] != binding.ref.as_record()
                or observation.body["outcome"] != result["expected"]
            ):
                raise ValueError(
                    "measure admission lost its original successful adequacy controls"
                )
            _, grounding, _, checker = control_request(
                view,
                *(
                    Ref.from_record(binding.body[field])
                    for field in ("proposal_ref", "grounding_ref", "control_ref")
                ),
            )
            attempt = view.read(observation.predecessor_refs[0], "attempt")
            rows.append((binding, observation, attempt, grounding, checker))
    return [record.ref.as_record() for record in admissions.values()], rows


def confirm_control_evidence(reader, rows, *, duet_id):
    """Confirm original Runs/values, not another adequacy evaluation or replay."""
    executions = {}
    for binding, observation, attempt, grounding, checker in rows:
        if (
            attempt.body["action"] != "observe_measure_control"
            or attempt.body["payload"]["control_run_ref"] != binding.ref.as_record()
            or attempt.body["payload"]["execution_ref"]
            != observation.body["execution_ref"]
            or attempt.evidence_refs != observation.evidence_refs
            or len(observation.evidence_refs) != 1
        ):
            raise ValueError("adequacy observation has inconsistent attempt provenance")
        reference = observation.evidence_refs[0]
        registration = RunRegistration.from_record(binding.body["registration"])
        execution = reader.runs.read_evidence(registration.run_id)
        inputs = admitted_build(reader, checker, duet_id=duet_id)
        if (
            execution.terminal_status.value != "succeeded"
            or Ref(execution.evidence_id, execution.content_hash).as_record()
            != observation.body["execution_ref"]
            or reader.runs.read_registration(registration.run_id) != registration
            or registration.build_receipt_id != inputs.receipt.receipt_id
            or reference.store_kind != "run_audit"
            or reference.owner_id != registration.run_id
            or reference.record_id != execution.terminal_event_id
            or reference.observation_path != ""
        ):
            raise ValueError(
                "adequacy evidence lacks its exact approved checker execution"
            )
        value = reader.read(
            reference, duet_id=duet_id, allowed_runs={registration.run_id.value}
        )
        if canonical_json(
            project(value, grounding["observation_path"])
        ) != canonical_json(observation.body["observed_value"]):
            raise ValueError(
                "adequacy observation differs from the committed checker result"
            )
        executions[execution.evidence_id.value] = Ref(
            execution.evidence_id, execution.content_hash
        ).as_record()
    return [executions[key] for key in sorted(executions)]


def resolve_control_attempt(reader, attempt):
    """Read cross-store execution evidence before the campaign writer transaction."""
    from .campaign_store import CampaignView

    payload = attempt.body["payload"]
    if attempt.body["action"] == "bind_measure_control":
        binding = RefinementRecord.from_record(payload["binding"])
        body = binding.body
        registration = (
            RunRegistration.from_record(body["registration"])
            if body["registration"] is not None
            else None
        )
        prepared = prepare_control(
            reader,
            attempt.campaign_id,
            *(
                Ref.from_record(body[field])
                for field in ("proposal_ref", "grounding_ref", "control_ref")
            ),
            request_id=registration.launch_request.request_id
            if registration
            else content_id("control_input", binding.ref.as_record()).value,
        )
        result = {"control_gap": prepared.gap}
        if prepared.gap is None:
            if registration is None:
                raise ValueError("available control cannot be published as unavailable")
            inputs = prepared.inputs
            admitted = RunRegistration.from_admitted_build(
                build_request=inputs.build_request,
                build_attempt=inputs.build_attempt,
                build_receipt=inputs.receipt,
                build_manifest=inputs.manifest,
                launch_request=registration.launch_request,
                runtime_identity=registration.runtime_identity,
                runtime_policy=registration.runtime_policy,
                execution_scope=prepared.execution_scope,
                target_environment=registration.target_environment,
            )
            result.update(
                admitted_registration=admitted.as_record(),
                control_launch=prepared.launch.as_record(),
            )
        return result, set()
    with reader.duets.transaction() as connection:
        view = CampaignView(connection, attempt.campaign_id)
        binding = view.read(
            Ref.from_record(payload["control_run_ref"]), "measure_control_run"
        )
    run_id = OpaqueId(payload["run_id"])
    evidence = reader.runs.read_evidence(run_id)
    registration = reader.runs.read_registration(run_id)
    if Ref(evidence.evidence_id, evidence.content_hash) != Ref.from_record(
        payload["execution_ref"]
    ) or canonical_json(registration.as_record()) != canonical_json(
        binding.body["registration"]
    ):
        raise ValueError("control execution evidence differs from its actual bound Run")
    return {
        "execution": evidence.as_record(),
        "registration": registration.as_record(),
    }, {run_id.value}
