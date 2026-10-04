"""One user-started build owns materialization, refinement and validation.

The nested refiner owns all repair choices and iteration. This lifecycle only
connects the initial Builder receipt, the shared experiment and the final build;
it is not a second Episode runner or retry loop.
"""

import asyncio

from agent.duet_contracts import DuetProvenance
from episode_builder import BuildReceipt
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
    result = row["record"]
    if row[
        "duet_id"
    ] != host.identity.duet_id.value or receipt.receipt_id.value not in {
        result["initial_build_receipt_id"],
        result["build_receipt_id"],
    }:
        raise ValueError("build finalization belongs to another build")
    if (
        result["state"] == "verified"
        and result["build_receipt_id"] != receipt.receipt_id.value
    ):
        # Verification may commit before the selected baseline is published.
        # Preserve its reference, but do not label the older baseline complete.
        return {**result, "state": "interrupted"}
    return result


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


def _publish_result(host, request, initial, receipt, result, state, error):
    record = {
        "build_request_id": request.build_request_id.value,
        "authority_head_approval_id": request.authority_approval.approval_id.value,
        "initial_build_receipt_id": None
        if initial is None
        else initial.receipt_id.value,
        "build_receipt_id": None if receipt is None else receipt.receipt_id.value,
        "state": state,
        "refinement": result,
        "error": error,
    }
    # Both receipts lead to the same result, including across a crash before the
    # accepted baseline is published. Initial evidence is never overwritten.
    receipts = {
        item.receipt_id.value for item in (initial, receipt) if item is not None
    }
    artifacts = tuple(
        artifact_fields(
            "build_job_result",
            duet_id=host.identity.duet_id.value,
            build_receipt_id=receipt_id,
            record=record,
        )
        for receipt_id in sorted(receipts)
    )
    host.store.put_artifacts_with_events(
        artifacts=artifacts,
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
    host, request, builder, launch, launch_transport, cancel_event, refiner
):
    from llm_call_library import model_transport_scope

    async def build_transport(model_request):
        return await host._builder_model_transport(
            model_request, cancel_event, launch_transport
        )

    with model_transport_scope(build_transport):
        raw = await builder.build(
            request,
            progress_callback=lambda value: host._record_build_progress(request, value),
            cancel_event=cancel_event,
        )
    receipt = host._correlated_receipt(request, raw)
    baseline = await asyncio.to_thread(
        host._persist_materialized_specification, request, receipt
    )
    with host._build_lock:
        host._build_receipt = receipt
        host._build_attempt_id = receipt.build_attempt_id
        host._build_baseline = baseline
        host._build_progress = host._receipt_progress(request, receipt)
        if cancel_event.is_set():
            return receipt, None
        host._build_state = "refining"
        host._build_progress["stage"] = "refining"
        # Initial Builder cancellation is cooperative so its partial receipt is
        # retained. During refinement, cancel the shared service task instead;
        # its existing executor stops and audits in-flight nested Runs.
        host._build_refinement_task = asyncio.create_task(
            refiner.run(request, baseline, builder, launch)
        )
        host._build_loop = asyncio.get_running_loop()
    return receipt, await host._build_refinement_task


def run_build_job(
    host, request, builder, launch, launch_transport, cancel_event, refiner
):
    from agent.openchia_host import _describe_exception

    initial, receipt, result, error = None, None, None, None
    state = "host_error"
    try:
        initial, result = asyncio.run(
            _execute(
                host, request, builder, launch, launch_transport, cancel_event, refiner
            )
        )
        receipt = initial
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
        _publish_result(host, request, initial, receipt, result, state, error)
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
    except asyncio.CancelledError:
        state = "cancelled"
        initial = receipt = host._build_receipt
        _publish_result(host, request, initial, receipt, None, state, None)
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
