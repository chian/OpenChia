"""One user-started build owns materialization, refinement and validation.

The nested refiner owns all repair choices and iteration. This lifecycle only
connects approved architecture, the shared experiment and the final build;
it is not a second Episode runner or retry loop.
"""

import asyncio

from agent.duet_contracts import DuetProvenance
from episode_builder import BuildReceipt
from llm_call_library.transport import ModelCallFailed
from episode_runtime.records.experiments import (
    artifact_fields,
    read_record,
    read_reference,
)


def finalization_for(host, receipt):
    row = read_record(
        host.store, "build_job_result", build_receipt_id=receipt.receipt_id.value
    )
    if row is None:
        return None
    job = read_record(host.store, "build_job", build_request_id=row["record"]["build_request_id"])
    if job is not None:
        run_id = latest_job_run(host, job["record"])
        continued = None if run_id is None else read_record(
            host.store, "build_job_result_attempt",
            build_receipt_id=receipt.receipt_id.value, run_id=run_id,
        )
        if continued is not None:
            row = continued
    result = row["record"]
    if row[
        "duet_id"
    ] != host.identity.duet_id.value or receipt.receipt_id.value != result["build_receipt_id"]:
        raise ValueError("build finalization belongs to another build")
    return result


def latest_job_run(host, job):
    from episode_runtime.records.experiments import execution_attempts

    dispatch = read_record(host.store, "dispatch", experiment_id=job["experiment_id"])
    if dispatch is None:
        return None
    attempts = execution_attempts(host.store, None, dispatch["record"]["registration"]["run_id"])
    return None if not attempts else attempts[-1]["record"]["registration"]["run_id"]


def refinement_links(host, request):
    row = read_record(
        host.store, "build_job", build_request_id=request.build_request_id.value
    )
    if row is None:
        return None
    if row["duet_id"] != host.identity.duet_id.value:
        raise ValueError("build job belongs to another Duet")
    return {key: row["record"][key] for key in ("campaign_ref", "experiment_id")}


def accepted_receipt(host, result, request):
    """Resolve only a host-verified revision of this job's approved workflow."""
    from iterative_episode_refiner.records import RefinementRecord

    value = result.get("verified_build")
    if value is None:
        return None
    verified = RefinementRecord.from_record(value)
    stored = read_reference(
        host.store, verified.ref.as_record(), host.identity.duet_id.value
    )
    if (
        stored["record"] != value
        or verified.kind != "verified_build"
        or result["disposition"] != "attained"
        or result["verification_gaps"]
        or verified.body["target_approval_ref"]["artifact_id"]
        != request.authority_approval.approval_id.value
        or verified.body["candidate_ref"]
        != {key: result["candidate"][key] for key in ("artifact_id", "content_hash")}
    ):
        raise ValueError("refinement did not verify this job's exact candidate")
    receipt = BuildReceipt.from_record(
        read_reference(
            host.store, verified.body["build_receipt_ref"], host.identity.duet_id.value
        )["record"]
    )
    inputs = host.build_store.inspection_inputs_for_receipt(receipt.receipt_id)
    if (
        inputs.receipt != receipt
        or not receipt.materialized
        or inputs.build_request.authority_approval != request.authority_approval
        or inputs.build_request.frozen_workflow != request.frozen_workflow
    ):
        raise ValueError("verified build differs from this job's approved workflow")
    host.build_store.verify_source_package(inputs.manifest)
    return receipt


def _publish_result(host, request, receipt, result, state, error, *, continued_job=None):
    record = {
        "build_request_id": request.build_request_id.value,
        "authority_head_approval_id": request.authority_approval.approval_id.value,
        "build_receipt_id": None if receipt is None else receipt.receipt_id.value,
        "state": state,
        "refinement": result,
        "error": error,
    }
    # Every host execution has a result, including construction before admission.
    # Bind publication to its request/continuation event, not a fabricated receipt.
    owner_sequence = max(event["sequence"] for event in host.store.events(host.identity.duet_id.value)
                         if event["event_type"] in {"build_requested", "build_continue_requested"}
                         and event["record"]["build_request_id"] == request.build_request_id.value)
    receipts = set() if receipt is None else {receipt.receipt_id.value}
    run_id = None if continued_job is None else latest_job_run(host, continued_job)
    # Setup can stop before dispatch or admission. Its request-owned result is
    # still persisted; receipt/Run links appear only when those artifacts exist.
    per_attempt = continued_job is not None and run_id is not None
    artifacts = [artifact_fields(
        "build_execution_result", duet_id=host.identity.duet_id.value,
        build_request_id=request.build_request_id.value, owner_event_sequence=owner_sequence,
        record=record,
    )]
    for receipt_id in sorted(receipts):
        artifacts.append(artifact_fields(
            "build_job_result_attempt" if per_attempt else "build_job_result",
            duet_id=host.identity.duet_id.value,
            build_receipt_id=receipt_id,
            **({"run_id": run_id} if per_attempt else {}),
            record=record,
        ))
        if per_attempt and read_record(
            host.store, "build_job_result", build_receipt_id=receipt_id
        ) is None:
            # A crash can precede the initial job's report; a newly accepted
            # revision also needs its first receipt-to-job link. Existing
            # terminal reports are immutable and remain in the history.
            artifacts.append(artifact_fields(
                "build_job_result", duet_id=host.identity.duet_id.value,
                build_receipt_id=receipt_id, record=record,
            ))
    host.store.put_artifacts_with_events(
        artifacts=tuple(artifacts),
        events=(
            {
                "event_type": "build_finished",
                "provenance": DuetProvenance.HOST_VALIDATION.value,
                "record": record,
            },
        ),
        idempotency_artifact_ids=tuple(item["artifact_id"] for item in artifacts),
        duet_id=host.identity.duet_id.value,
        expected_state="sealed",
        expected_authority_head_approval_id=request.authority_approval.approval_id.value,
    )


async def _execute(
    host, request, builder, launch, cancel_event, refiner,
):
    from iterative_episode_refiner.construction import prepare_construction

    inputs, handoff = await asyncio.to_thread(prepare_construction, host, request, builder)
    with host._build_lock:
        host._build_receipt = None
        host._build_attempt_id = inputs.build_attempt.build_attempt_id
        host._build_baseline = None
        host._build_progress = host._empty_progress("refining")
        host._build_progress["counts"].update(
            episodes_total=len(request.frozen_workflow.workflow.episodes),
            episodes_planned=len(inputs.plan.nodes),
            blocking_deficits=sum(item.blocking for item in inputs.plan.deficits),
        )
        if cancel_event.is_set():
            return None
        host._build_state = "refining"
        host._build_progress["stage"] = "refining"
        host._build_refinement_task = asyncio.create_task(
            refiner.run(request, inputs, handoff, builder, launch)
        )
        host._build_loop = asyncio.get_running_loop()
    return await host._build_refinement_task


def run_build_job(
    host, request, builder, launch, cancel_event, refiner,
    *, continuation=None, continued_job=None,
):
    from agent.openchia_host import _describe_exception

    receipt, result, error = None, None, None
    state = "host_error"
    try:
        result = asyncio.run(
            continuation() if continuation is not None else _execute(
                host, request, builder, launch, cancel_event, refiner,
            )
        )
        if result is None:
            state = "cancelled"
        else:
            accepted = accepted_receipt(host, result, request)
            if accepted is not None:
                receipt, state = accepted, "verified"
            else:
                state = result["disposition"]
                if state == "attained":
                    state = "unresolved"
        _publish_result(host, request, receipt, result, state, error, continued_job=continued_job)
        if state == "verified":
            revised_request = host.build_store.read_build_request(
                receipt.build_request_id
            )
            baseline = host._persist_materialized_specification(
                revised_request, receipt
            )
            with host._build_lock:
                host._build_baseline = baseline
                host._build_receipt = receipt
                host._build_attempt_id = receipt.build_attempt_id
                host._build_progress = host._receipt_progress(revised_request, receipt)
    except ModelCallFailed as exc:
        state, error = "interrupted", _describe_exception(exc)
        receipt = host._build_receipt
        saved_job = read_record(
            host.store, "build_job", build_request_id=request.build_request_id.value,
        )
        continued_job = None if saved_job is None else saved_job["record"]
        _publish_result(host, request, receipt, None, state, error, continued_job=continued_job)
    except asyncio.CancelledError:
        state = "cancelled"
        receipt = host._build_receipt
        saved_job = read_record(host.store, "build_job", build_request_id=request.build_request_id.value)
        continued_job = None if saved_job is None else saved_job["record"]
        _publish_result(host, request, receipt, None, state, None, continued_job=continued_job)
    except Exception as exc:
        state, error = "host_error", _describe_exception(exc)
        host.store.append_event(
            duet_id=host.identity.duet_id.value,
            event_type="build_host_failure",
            provenance=DuetProvenance.HOST_VALIDATION.value,
            record={"build_request_id": request.build_request_id.value, "error": error},
        )
    finally:
        with host._build_lock:
            host._build_state, host._build_error = state, error
            host._build_progress["stage"] = state
            host._build_model_call_active = False
            host._build_model_call_token = None
            host._build_thread = None
            host._build_cancel_event = None
            host._build_loop = None
            host._build_refinement_task = None
