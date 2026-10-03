"""Episode-chosen control experiments, consumed by existing measure admission."""

from agent.duet_contracts import canonical_json, content_id
from agent.episode_contracts import OpaqueId
from episode_runtime.records.experiments import put_data
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.control_subjects import control_subject
from function_library.epistemic_contract import exact
from function_library.models import _thaw_json

from .measure_controls import control_key, prepare_control
from .records import Ref


def targets(evaluations, session, call, jobs):
    """Expose required cases; do not select their order or predict outcomes."""
    artifacts = session.store.evidence.duets
    result, gaps = [], []
    with session.view() as view:
        existing = {entry.key: entry for entry in view.entries("measure_control")}
    for job in jobs:
        key = control_key(*job)
        prior = existing.get(key)
        if prior is not None and prior.status in {"observed", "unavailable"}:
            continue
        prepared = prepare_control(
            session.store.evidence,
            session.campaign_id,
            *job,
            request_id=content_id("launch_request", {"control": key}).value,
        )
        if prepared.gap is not None:
            if prior is None:
                evaluations._bind_measure_control(
                    session, call, job, None, prepared.gap
                )
            gaps.append({"control_ref": job[2].as_record(), **prepared.gap})
            continue
        receipt = {
            "artifact_id": prepared.inputs.receipt.receipt_id.value,
            "content_hash": prepared.inputs.receipt.content_hash.value,
        }
        body = {
            "campaign_ref": session.contract.ref.as_record(),
            **{
                field: ref.as_record()
                for field, ref in zip(
                    ("proposal_ref", "grounding_ref", "control_ref"), job, strict=True
                )
            },
            "build_receipt_ref": receipt,
            "scope": prepared.execution_scope.as_record(),
        }
        reference = put_data(artifacts, session.duet_id, "control_target", body)
        scope = prepared.execution_scope
        result.append({
            "control_target_ref": reference,
            "candidate_ref": receipt,
            "build_receipt_ref": receipt,
            "environment_ref": _thaw_json(session.contract.body["environment_ref"]),
            "campaign_ref": session.contract.ref.as_record(),
            "launch_ref": evaluations.target_launch_ref,
            "requirements": [
                {"requirement_ref": reference, "measure_ref": job[0].as_record()}
            ],
            "scope": {
                "kind": scope.kind,
                "entry_local_id": scope.entry_local_id,
                "included_local_ids": list(scope.included_local_ids),
                "component_definition_id": None,
                "unit_label": None,
                "invocation_path": [],
            },
            "boundary": {
                "parent_context_ref": _thaw_json(scope.boundary_ref),
                "children": "execute",
            },
            "saved_input_ref": reference,
            "fresh_input_payload": _thaw_json(scope.boundary["input_payload"]),
            "limitations": list(scope.boundary["limitations"]),
            "previous_experiment_ref": None
            if prior is None
            else _thaw_json(prior.record.body.get("experiment_ref")),
            "instructions": "Choose this case only when it answers your next question. Declare expected and falsifying outcomes. Saved inputs name this control target; fresh inputs must exactly retain the independent grounding. A partial control pass does not admit the measure.",
        })
    return result, gaps


def validate(evaluations, session, call, proposal):
    exact(proposal, {"control_target_ref", "experiment"}, "control experiment")
    spec = ExperimentSpec.from_record(proposal["experiment"])
    request = spec.as_record()
    if request["requirements"][0]["requirement_ref"] != proposal["control_target_ref"]:
        raise ValueError("experiment changed the selected grounded control")
    inputs = evaluations.builder.store.inspection_inputs_for_receipt(
        request["build_receipt_ref"]["artifact_id"]
    )
    subject = control_subject(
        request,
        inputs=inputs,
        artifacts=session.store.evidence.duets,
        builds=evaluations.builder.store,
        runs=session.store.evidence.runs,
    )
    if subject is None or subject["owner_duet_id"] != session.duet_id:
        raise ValueError("experiment has no assigned grounded control")
    with session.view() as view:
        record = view.entry(
            "measure_proposal", subject["binding"]["proposal_ref"]["artifact_id"]
        ).record
        if (
            call.assignment.body["role"] != "measure"
            or record.body["assignment_ref"] != call.assignment.ref.as_record()
        ):
            raise ValueError("only the assigned measure child may choose this control")
    if request["launch_ref"] != evaluations.target_launch_ref and not (
        request["mode"] == "recorded" and request["launch_ref"] is None
    ):
        raise ValueError(
            "control experiment changes the target-test launch configuration"
        )
    return spec, subject


def receive(evaluations, session, call, spec, subject, result):
    measurement = result.get("measurement")
    observed = False
    job = tuple(
        Ref.from_record(subject["binding"][field])
        for field in ("proposal_ref", "grounding_ref", "control_ref")
    )
    if measurement is not None and spec.as_record()["mode"] in {
        "live_fresh",
        "live_saved",
    }:
        outcome = measurement["outcomes"][0]
        if outcome["status"] in {"pass", "fail", "error", "inconclusive"}:
            runs = session.store.evidence.runs
            registration = runs.read_registration(OpaqueId(result["run_id"]))
            evidence = runs.read_evidence(registration.run_id)
            with session.view() as view:
                prior = next(
                    (
                        entry
                        for entry in view.entries("measure_control")
                        if entry.key == control_key(*job)
                    ),
                    None,
                )
                binding = (
                    None
                    if prior is None
                    else (
                        view.read(
                            Ref.from_record(prior.record.body["control_run_ref"]),
                            "measure_control_run",
                        )
                        if prior.status == "observed"
                        else prior.record
                    )
                )
            if binding is None:
                binding = evaluations._bind_measure_control(
                    session,
                    call,
                    job,
                    registration,
                    None,
                    experiment_ref=result["intent_ref"],
                )
            if (
                canonical_json(binding.body["registration"])
                != canonical_json(registration.as_record())
                or binding.body.get("experiment_ref") != result["intent_ref"]
            ):
                raise ValueError("control already binds another experiment execution")
            if prior is None or prior.status != "observed":
                evaluations._observe_measure_control(
                    session, call, binding, registration, evidence
                )
            observed = True
            jobs = evaluations._measure_jobs(
                session,
                call,
                {
                    "unit_id": call.unit_id.value,
                    "purpose": "adequacy",
                    "proposal_ref": job[0].as_record(),
                },
            )
            with session.view() as view:
                done = all(
                    any(
                        entry.key == control_key(*item)
                        and entry.status in {"observed", "unavailable"}
                        for entry in view.entries("measure_control")
                    )
                    for item in jobs
                )
                admitted = any(
                    entry.record.body["proposal_ref"] == job[0].as_record()
                    for entry in view.entries("measure")
                )
            if done and not admitted:
                evaluations._admit_measure(
                    session,
                    call,
                    {
                        "unit_id": call.unit_id.value,
                        "purpose": "adequacy",
                        "proposal_ref": job[0].as_record(),
                    },
                )
    call.feedback_ref = session.put_data(
        "experiment_result",
        {
            "experiment_id": spec.experiment_id,
            "control_target_ref": subject["reference"],
            "measurement_ref": None
            if measurement is None
            else measurement["measurement_ref"],
            "execution_status": result["execution_status"],
            "observed_control_ref": job[2].as_record() if observed else None,
        },
    )
    return session.reply(
        call,
        experiment_result=result,
        observed_control_ref=job[2].as_record() if observed else None,
    )
