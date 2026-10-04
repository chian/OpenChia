"""Restore the initial Builder stage, then use the ordinary complete job."""

import contextvars
import threading
from dataclasses import replace

from agent.build_refinement import BuildRefinement
from agent.duet_contracts import DuetProvenance, content_id
from agent.episode_launch_host import resolve_approved_launch
from agent.openchia_build_continue import restore_binding
from agent.openchia_build_job import run_build_job
from agent.openchia_build_recovery import BuilderResponses, owner_record, requested_jobs, require_owner_stopped
from episode_runtime.records.experiments import artifact_fields


def continue_builder(host, predecessor):
    jobs = [job for job in requested_jobs(host) if job["build_request_id"] == predecessor.build_request_id.value]
    if len(jobs) != 1:
        raise ValueError("Builder continuation requires its unique original job record.")
    job = jobs[0]
    require_owner_stopped(host, job)
    reference = job.get("refiner_binding_ref")
    if reference is None:
        raise ValueError("Legacy Builder job has no saved owning-Duet binding; exact continuation is unavailable.")
    binding = restore_binding(host, reference)
    launches = [
        event["record"] for event in host.store.events(host.identity.duet_id.value)
        if event["event_type"] == "model_launch_resolved"
        and event["record"]["kind"] == "build"
        and event["record"]["subject_id"] == predecessor.build_request_id.value
    ]
    if len(launches) != 1:
        raise ValueError("Builder continuation requires its exact recorded Target Workflow launch.")
    _, launch, _ = resolve_approved_launch(
        host.store, host.identity.duet_id.value,
        configuration_hash=launches[0]["configuration_hash"],
    )
    receipts = host.build_store.receipts_for_build_request(predecessor.build_request_id)
    existing = receipts[0] if receipts else None
    if existing is not None and any(deficit.code == "build_cancelled" for deficit in existing.deficits):
        existing = None
    # A completed Builder receipt is already authoritative input for the
    # refiner, even when failed admission is exactly what needs repairing.
    request = predecessor if existing is not None else replace(
        predecessor,
        request_nonce=content_id("build_continue", {"predecessor": predecessor.build_request_id.value}).value,
    )
    builder = host._builder_for(request, launch)
    refiner = BuildRefinement(host, binding=binding)
    cancel = threading.Event()
    live = host._model_launch_transport(launches[0]["launch_id"], launch, cancel_event=cancel)
    responses = None if existing is not None else BuilderResponses(host, builder, predecessor, live, request)
    if existing is None:
        host.build_store.put_build_request(request)
        link = {
            "predecessor_build_request_id": predecessor.build_request_id.value,
            "build_request_id": request.build_request_id.value,
        }
        artifacts = (
            artifact_fields("build_continuation", duet_id=host.identity.duet_id.value,
                            predecessor_build_request_id=predecessor.build_request_id.value, record=link),
            artifact_fields("build_parent", duet_id=host.identity.duet_id.value,
                            build_request_id=request.build_request_id.value, record=link),
        )
        created = host.store.put_artifacts_with_events(
            artifacts=artifacts,
            events=({
                "event_type": "build_requested", "provenance": DuetProvenance.HUMAN_INPUT.value,
                "record": {
                    **link, "owner": owner_record(), "refiner_binding_ref": binding.reference,
                    "authority_head_approval_id": request.authority_approval.approval_id.value,
                    "workflow_approval_id": request.workflow_approval.approval_id.value,
                },
            }, {
                "event_type": "model_launch_resolved",
                "provenance": DuetProvenance.HOST_VALIDATION.value,
                "record": {
                    **launches[0], "subject_id": request.build_request_id.value,
                    "launch_id": content_id("model_launch", {"build_request_id": request.build_request_id.value}).value,
                    "continued_from_launch_id": launches[0]["launch_id"],
                },
            }),
            idempotency_artifact_ids=tuple(item["artifact_id"] for item in artifacts),
            duet_id=host.identity.duet_id.value, expected_state="sealed",
            expected_authority_head_approval_id=request.authority_approval.approval_id.value,
        )
        if not created:
            return host.build_status()
        live.launch_id = content_id("model_launch", {"build_request_id": request.build_request_id.value}).value
    host._build_request = request
    host._build_attempt_id = None if existing is None else existing.build_attempt_id
    host._build_receipt, host._build_baseline = existing, host.workspace.current_baseline()
    host._build_error, host._build_cancel_event = None, cancel
    host._build_state = "continuing"
    host._build_progress = host._empty_progress("continuing")
    host._build_progress["counts"]["episodes_total"] = len(request.frozen_workflow.workflow.episodes)
    host._build_model_call_active, host._build_model_call_task = False, None
    host._build_model_call_token, host._build_model_call_started_at = None, None
    host._build_last_model_response_at = None

    def work():
        run_build_job(
            host, request, builder, launch, responses or live, cancel, refiner,
            builder_responses=responses, existing_receipt=existing,
        )

    context = contextvars.copy_context()
    worker = threading.Thread(
        target=context.run, args=(work,), daemon=False,
        name=f"openchia-continue-{request.build_request_id.value[-12:]}",
    )
    host._build_thread = worker
    try:
        worker.start()
    except Exception:
        host._build_thread, host._build_cancel_event = None, None
        host._build_state = "host_error"
        raise
    return host.build_status()
