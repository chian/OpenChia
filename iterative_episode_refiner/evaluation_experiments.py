"""Connect assigned refinement checks to the shared experiment service.

The Episode designs the experiment. This adapter supplies admitted targets and
checks ownership, then consumes shared results under the unchanged campaign
judgment. It neither executes code nor owns a replay or continuation loop.
"""

import asyncio

from agent.duet_contracts import canonical_json
from agent.episode_contracts import OpaqueId
from agent.duet_store import DuetNotFoundError
from episode_runtime.records.experiments import read_reference
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.planning import preview_experiment
from episode_runtime.testing.schema import MODES, SCOPES
from episode_runtime.testing.service import ExperimentService
from function_library.epistemic_contract import exact
from function_library.models import _thaw_json

from .evaluation_inputs import native_template
from .records import Ref


def experiment_target(evaluations, session, call, request, receipt, checks):
    with session.view() as view:
        instrument = view.data(Ref.from_record(request.body["harness_ref"]))
        inputs = native_template(view, request.body).as_record()
    admitted = evaluations.builder.store.inspection_inputs_for_receipt(
        receipt.receipt_id
    )
    return {
        "evaluation_request_ref": request.ref.as_record(),
        "source_kind": instrument["execution_kind"],
        "source_owner_duet_id": admitted.build_request.frozen_workflow.duet_id.value,
        "candidate_ref": _thaw_json(request.body["candidate_ref"]),
        "build_receipt_ref": {
            "artifact_id": receipt.receipt_id.value,
            "content_hash": receipt.content_hash.value,
        },
        "environment_ref": _thaw_json(session.contract.body["environment_ref"]),
        "campaign_ref": session.contract.ref.as_record(),
        "launch_ref": evaluations.target_launch_ref,
        "requirements": [
            {
                "requirement_ref": check.ref.as_record(),
                "measure_ref": _thaw_json(check.body["measure_ref"]),
                "requirement_key": check.body["requirement_key"],
                "criterion_expected": _thaw_json(check.body["expected"]),
                "observation_path": check.body["observation_path"],
            }
            for check in checks
        ],
        "assigned_inputs": inputs,
        "root_local_id": admitted.plan.root_local_id,
        "local_ids": [node.local_id for node in admitted.plan.nodes],
        "scope_kinds": SCOPES,
        "modes": MODES,
        "instructions": (
            "Choose one justified experiment and predict expected and falsifying outcomes. "
            "Use the shared experiment schema; preview exposes unsupported boundaries. "
            "The parent criterion cannot be changed. Narrower or replayed evidence is "
            "diagnostic, not a substitute for this assignment's full live acceptance."
        ),
        "gaps": []
        if evaluations.target_launch_ref is not None
        else [
            "The host has not supplied the Target Workflow's registered launch configuration. "
            "It must not use the refiner's Duet model configuration as a substitute."
        ],
    }


def _assigned(evaluations, session, call, reference):
    with session.view() as view:
        request = view.entry("evaluation", reference.artifact_id.value).record
        if (
            request.ref != reference
            or request.invocation_id != call.invocation_id
            or request.logical_unit_id != call.unit_id
            or request.body["candidate_ref"] != view.candidate.ref.as_record()
        ):
            raise ValueError("experiment request is not this unit's current candidate")
        source = view.entry("evaluation_source", request.artifact_id.value)
        if source.status != "admitted":
            raise ValueError("experiment requires admitted candidate source")
        receipt_ref = Ref.from_record(source.record.body["build_receipt_ref"])
        receipt_data = view.data(receipt_ref)
        checks = [
            view.entry("check", key).record
            for key in request.body["check_keys"]
            if view.entry("check", key).record.body["evidence_kind"] == "execution"
        ]
        candidate = view.candidate
    receipt = evaluations.builder.store.inspection_inputs_for_receipt(
        receipt_data["receipt_id"]
    ).receipt
    target = experiment_target(evaluations, session, call, request, receipt, checks)
    return request, candidate, receipt_ref, checks, target


def _authorize_reuse(session, spec, target):
    from episode_runtime.testing.campaign_subjects import validate_campaign_reuse

    validate_campaign_reuse(
        spec, artifacts=session.store.evidence.duets, owner=session.duet_id,
        source_owner=target["source_owner_duet_id"],
        allowed=[row["requirement_ref"] for row in target["requirements"]],
    )


def _validate(evaluations, session, call, proposal):
    if "control_target_ref" in proposal:
        from .measure_experiments import validate

        return validate(evaluations, session, call, proposal)
    exact(proposal, {"evaluation_request_ref", "experiment"}, "refinement experiment")
    assigned = _assigned(
        evaluations, session, call, Ref.from_record(proposal["evaluation_request_ref"])
    )
    target = assigned[-1]
    experiment = ExperimentSpec.from_record(proposal["experiment"])
    spec = experiment.as_record()
    for field in (
        "candidate_ref",
        "build_receipt_ref",
        "environment_ref",
        "campaign_ref",
    ):
        if spec[field] != target[field]:
            raise ValueError(f"experiment changes the assigned {field}")
    if spec["launch_ref"] != target["launch_ref"] and not (
        spec["launch_ref"] is None and spec["mode"] in {"recorded", "numerical"}
    ):
        raise ValueError(
            "experiment changes the host-selected Target Workflow launch configuration"
        )
    allowed = [
        {key: row[key] for key in ("requirement_ref", "measure_ref")}
        for row in target["requirements"]
    ]
    if any(
        {key: row[key] for key in ("requirement_ref", "measure_ref")} not in allowed
        for row in spec["requirements"]
    ):
        raise ValueError("experiment changes the parent's assigned checks or measures")
    _authorize_reuse(session, spec, target)
    return experiment, assigned


def propose_experiment(evaluations, session, call, proposal, producer):
    experiment, _ = _validate(evaluations, session, call, proposal)
    plan = preview_experiment(
        experiment,
        artifacts=session.store.evidence.duets,
        builds=evaluations.builder.store,
        runs=session.store.evidence.runs,
    )
    reference = session.put_data(
        "experiment_proposal",
        {
            "assignment_ref": call.assignment.ref.as_record(),
            "invocation_id": call.invocation_id.value,
            "logical_unit_id": call.unit_id.value,
            "producer_ref": producer.as_record(),
            "proposal": proposal,
        },
    )
    if not plan["resolved"]:
        call.feedback_ref = session.put_data(
            "experiment_preview",
            {
                "experiment_proposal_ref": reference.as_record(),
                "plan": plan,
            },
        )
    return session.reply(
        call,
        proceed=plan["resolved"],
        experiment_proposal_ref=reference.as_record(),
        experiment_plan=plan,
    )


async def execute_experiment(evaluations, session, call, payload, *, request_event=None):
    exact(
        payload,
        {"unit_id", "experiment_proposal_ref"},
        "refinement experiment execution",
    )

    def prepare():
        envelope = session.store.evidence.reference(
            Ref.from_record(payload["experiment_proposal_ref"]), session.duet_id
        )
        if (
            envelope["assignment_ref"] != call.assignment.ref.as_record()
            or envelope["invocation_id"] != call.invocation_id.value
            or envelope["logical_unit_id"] != call.unit_id.value
        ):
            raise ValueError(
                "experiment proposal belongs to another assignment or unit"
            )
        return _validate(evaluations, session, call, envelope["proposal"])

    spec, assigned = await asyncio.to_thread(prepare)
    service = ExperimentService(
        artifacts=session.store.evidence.duets,
        builds=evaluations.builder.store,
        runs=session.store.evidence.runs,
        executor=evaluations.executor,
        http_credentials=evaluations.http_credentials,
        runtime_policy=evaluations.runtime_policy,
    )
    result = await service.run(spec)
    if session.registration.resume_from is not None and result["execution_status"] in {
        "interrupted", "cancelled", "resource_limited", "terminal_evidence_unavailable",
    }:
        result = await service.continue_interrupted(experiment_id=spec.experiment_id)
    task = asyncio.create_task(asyncio.to_thread(
        session.commit_response, request_event,
        _receive, evaluations, session, call, spec, assigned, result,
    ))
    from episode_runtime.host_tasks import join_local

    return await join_local(task, propagate_cancel=False)


def _receive(evaluations, session, call, spec, assigned, result):
    if isinstance(assigned, dict) and assigned.get("kind") == "grounded_control":
        from .measure_experiments import receive

        return receive(evaluations, session, call, spec, assigned, result)
    request, candidate, receipt_ref, checks, _ = assigned
    measurement = result.get("measurement")
    observed = []
    # The common result may answer a narrower question. Only applicable live
    # whole-target evidence can be submitted to this native-workflow judgment.
    if (
        measurement is not None
        and spec.as_record()["mode"] in {"live_fresh", "live_saved"}
        and spec.as_record()["scope"]["kind"] == "workflow"
    ):
        observed = [
            check
            for check in checks
            if any(
                row["requirement_ref"] == check.ref.as_record()
                and row["status"] in {"pass", "fail"}
                for row in measurement["outcomes"]
            )
        ]
    if observed:
        runs = session.store.evidence.runs
        target_registration = runs.read_registration(OpaqueId(result["run_id"]))
        target_evidence = runs.read_evidence(target_registration.run_id)
        evidence_refs = {
            row["evidence_ref"]["artifact_id"]
            for row in measurement["outcomes"]
            if any(
                row["requirement_ref"] == check.ref.as_record() for check in observed
            )
        }
        if len(evidence_refs) != 1:
            raise ValueError(
                "one evaluation request must use its single declared checking source"
            )
        registration, evidence = target_registration, target_evidence
        checker = next(
            (
                row
                for row in result.get("instrument_runs", ())
                if row.get("evidence_ref", {}).get("artifact_id") in evidence_refs
            ),
            None,
        )
        if checker is not None:
            registration = runs.read_registration(OpaqueId(checker["run_id"]))
            evidence = runs.read_evidence(registration.run_id)
        if evidence.evidence_id.value not in evidence_refs:
            raise ValueError(
                "measured outcome does not identify this experiment's result"
            )
        with session.view() as view:
            existing = next(
                (
                    row.record
                    for row in view.entries("evaluation_run")
                    if row.key == request.artifact_id.value
                ),
                None,
            )
            if view.candidate.ref != candidate.ref:
                raise ValueError("experiment returned after the candidate changed")
            recorded = set()
            for check in observed:
                try:
                    prior = view.entry("check_state", check.artifact_id.value).record
                except DuetNotFoundError:
                    continue
                if prior.body["request_ref"] == request.ref.as_record() and prior.body[
                    "execution_ref"
                ] == {
                    "artifact_id": evidence.evidence_id.value,
                    "content_hash": evidence.content_hash.value,
                }:
                    recorded.add(check.artifact_id.value)
        if existing is None:
            existing = evaluations._bind(
                session,
                call,
                request,
                candidate,
                receipt_ref,
                target_registration,
                stage={"experiment_ref": result["intent_ref"]},
            )
        if checker is not None and "target_run_ref" not in existing.body:
            existing = evaluations._bind(
                session,
                call,
                request,
                candidate,
                receipt_ref,
                registration,
                stage={
                    "experiment_ref": result["intent_ref"],
                    "target_run_ref": existing.ref.as_record(),
                    "target_execution_ref": result["evidence_ref"],
                },
            )
        if canonical_json(existing.body["registration"]) != canonical_json(registration.as_record()):
            raise ValueError("evaluation request already binds another experiment Run")
        evaluations._observe(
            session,
            call,
            request,
            registration,
            evidence,
            [check for check in observed if check.artifact_id.value not in recorded],
        )
    call.feedback_ref = session.put_data(
        "experiment_result",
        {
            "experiment_id": spec.experiment_id,
            "evaluation_request_ref": request.ref.as_record(),
            "measurement_ref": None
            if measurement is None
            else measurement["measurement_ref"],
            "execution_status": result["execution_status"],
            "observed_check_keys": [check.artifact_id.value for check in observed],
        },
    )
    return session.reply(
        call,
        experiment_result=result,
        observed_check_keys=[check.artifact_id.value for check in observed],
    )


def feedback(session, reference):
    """Read the shared result by reference, without copying it into campaign state."""
    row = read_reference(
        session.store.evidence.duets, reference.as_record(), session.duet_id
    )
    value = row["record"]
    if row["kind"] == "refinement.proposal_rejection.v1":
        proposal = read_reference(
            session.store.evidence.duets, value["proposal_ref"], session.duet_id
        )
        if proposal["kind"] != "refinement.model_proposal.v1":
            raise ValueError("proposal feedback does not reference a model proposal")
        payload = proposal["record"]["event"]["payload"]
        # Each unit makes a fresh call: an inaccessible artifact reference and
        # parse offset do not let its producer repair the rejected output.
        return {
            **value,
            "rejected_proposal": {
                "raw_response": payload["response_text"],
                "producer_call_id": payload["producer_call_id"],
                "admitted": False,
            },
        }
    if row["kind"] != "refinement.experiment_result.v1":
        return value
    from episode_runtime.testing.measurements import saved_measurements

    measurement = saved_measurements(
        session.store.evidence.duets, value["experiment_id"]
    )
    if (
        measurement is not None
        and measurement["measurement_ref"] != value["measurement_ref"]
    ):
        raise ValueError("experiment feedback differs from its committed measurement")
    return {**value, "measurement": measurement}
