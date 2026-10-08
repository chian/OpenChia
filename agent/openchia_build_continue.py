"""Continue the normal build job through the shared experiment service.

This module restores host ownership and configuration. Worker reconstruction,
process checks, admission and execution remain in the ordinary Run machinery.
"""

import asyncio
import contextvars
import threading

from agent.duet_contracts import DuetProvenance
from agent.duet_episode_transport import DuetEpisodeBinding
from agent.episode_contracts import OpaqueId
from agent.episode_launch_host import resolve_approved_launch
from episode_runtime.records.experiments import read_record, read_reference


def restore_binding(host, reference):
    """Bind future calls to the owning Duet's current selection at continuation.

    Completed responses retain their original route. Each physical Run records
    its actual binding separately; the original experiment is never rewritten.
    """
    owner = host.identity.duet_id.value
    row = read_reference(host.store, reference, owner)
    record = row["record"]
    agent = host._duet_agent
    identity = getattr(agent, "_duet_identity", None)
    if identity is None or identity.duet_id.value != owner:
        raise ValueError("Continuation requires the original owning Duet's bound agent.")
    if (
        row["kind"] != "experiment.duet_model_binding.v1"
        or record["owner_duet_id"] != owner
        or record["source"] != "bound_duet_agent"
        or record["credential_source"] != "owning_duet_host_memory"
        or set(record["model_types"]) != {"refinement"}
    ):
        raise ValueError("Saved refiner model binding does not belong to this owning Duet.")
    runtime = agent._current_main_runtime()
    route = record["route"]
    if (
        all(runtime.get(key) == route[key] for key in ("provider", "model", "base_url", "api_mode"))
        and runtime.get("auth_mode", "") == record["auth_mode"]
        and getattr(agent, "reasoning_config", None) == route.get("reasoning")
    ):
        # A credential refresh alone must not silently install new recovery
        # defaults into a previously frozen binding.
        binding = DuetEpisodeBinding(owner, dict(reference), record, runtime.get("api_key") or None)
        binding.validate(artifacts=host.store, reference=reference, owner_duet_id=owner, model_types={"refinement"})
        return binding
    return DuetEpisodeBinding.from_bound_agent(
        artifacts=host.store, owner_duet_id=owner, agent=agent,
        model_types=record["model_types"],
    )


def continue_build(host, build_request_id=None):
    from agent.build_refinement import BuildRefinement
    from agent.openchia_build_job import run_build_job
    from agent.openchia_host import OpenChiaHostError
    from agent.workflow_editing import require_no_editor

    with host._build_lock:
        require_no_editor(host)
        host._require_no_active_run("build continuation")
        if host._build_thread is not None and host._build_thread.is_alive():
            raise OpenChiaHostError("an Episode build is already active")
        status = host.build_status()
        if build_request_id is None and status["state"] == "verified":
            return status
        selected = build_request_id or status["build_request_id"]
        if selected is None:
            raise OpenChiaHostError("No saved build job is selected for continuation.")
        request = host.build_store.read_build_request(OpaqueId(selected))
        authorization = host.service.resolve_current_build_authorization(host.identity.duet_id)
        if (
            request.authority_approval != authorization.authority_approval
            or request.workflow_approval != authorization.workflow_approval
            or request.frozen_workflow != authorization.frozen_workflow
            or request.admission_authority != authorization.admission_authority
            or request.frozen_workflow.duet_id != host.identity.duet_id
        ):
            raise OpenChiaHostError("Saved build no longer has the current exact workflow authority.")
        row = read_record(host.store, "build_job", build_request_id=request.build_request_id.value)
        if row is not None and row["duet_id"] != host.identity.duet_id.value:
            raise OpenChiaHostError("Saved refinement handoff belongs to another Duet.")
        from agent.openchia_build_recovery import requested_jobs, require_owner_stopped, owner_record

        starts = [item for item in requested_jobs(host) if item["build_request_id"] == selected]
        if len(starts) != 1:
            raise OpenChiaHostError("Continuation requires its exact original build request event.")
        require_owner_stopped(host, starts[0])
        job = None if row is None else row["record"]
        launches = [
            event["record"] for event in host.store.events(host.identity.duet_id.value)
            if event["event_type"] == "model_launch_resolved"
            and event["record"]["kind"] == "build"
            and event["record"]["subject_id"] == request.build_request_id.value
        ]
        if len(launches) != 1:
            raise OpenChiaHostError("Build continuation needs its one recorded Target Workflow launch.")
        _, launch, _ = resolve_approved_launch(
            host.store, host.identity.duet_id.value,
            configuration_hash=launches[0]["configuration_hash"],
        )
        reference = starts[0]["refiner_binding_ref"] if job is None else job["experiment"]["launch_ref"]
        refiner = BuildRefinement(host, binding=restore_binding(host, reference))
        builder = host._builder_for(request, launch)
        cancel = threading.Event()
        host._build_request, host._build_receipt = request, None
        start = read_record(host.store, "construction_start", build_request_id=selected)
        host._build_attempt_id = None if start is None else OpaqueId(start["record"]["inputs"]["build_attempt_id"])
        host._build_baseline = None
        host._build_cancel_event, host._build_error = cancel, None
        host._build_state = "continuing"
        host._build_progress = host._empty_progress("continuing")
        host._build_progress["counts"]["episodes_total"] = len(request.frozen_workflow.workflow.episodes)

        async def continuation():
            with host._build_lock:
                if cancel.is_set():
                    raise asyncio.CancelledError
                host._build_loop = asyncio.get_running_loop()
                host._build_refinement_task = asyncio.create_task(refiner.continue_job(job, builder, launch))
            return await host._build_refinement_task

        def work():
            run_build_job(
                host, request, builder, launch, cancel, refiner,
                continuation=continuation if job is not None else None, continued_job=job,
            )

        context = contextvars.copy_context()
        worker = threading.Thread(
            target=context.run, args=(work,), daemon=False,
            name=f"openchia-continue-{request.build_request_id.value[-12:]}",
        )
        host._build_thread = worker
        host.store.append_event(
            duet_id=host.identity.duet_id.value, event_type="build_continue_requested",
            provenance=DuetProvenance.HUMAN_INPUT.value,
            record={"build_request_id": request.build_request_id.value,
                    "experiment_id": None if job is None else job["experiment_id"], "owner": owner_record()},
        )
        try:
            worker.start()
        except Exception:
            host._build_thread, host._build_cancel_event = None, None
            host._build_state = "host_error"
            raise
    return host.build_status()
