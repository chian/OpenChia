"""Select a Duet's saved Run; recovery stays in the shared execution service."""

import asyncio
from dataclasses import replace

from agent.episode_contracts import OpaqueId
from agent.episode_launch_host import resolve_approved_launch
from agent.openchia_host import OpenChiaHostError
from episode_runtime.contracts import RunRegistration
from episode_runtime.continuation import InterruptedRunRef
from episode_runtime.records.experiments import execution_attempts, read_run_intent
from episode_runtime.store import RunStoreNotFound


def select_run(host, baseline):
    """Discover the latest physical attempt without requiring final publication."""
    requests = [
        event["record"] for event in host.store.events(host.identity.duet_id.value)
        if event["event_type"] == "run_requested"
        and event["record"]["build_receipt_id"] == baseline.build_receipt_id.value
    ]
    if not requests:
        return None
    request = requests[-1]
    attempts = execution_attempts(host.store, None, request["run_id"])
    if attempts:
        latest = attempts[-1]["record"]
        registration = RunRegistration.from_record(latest["registration"])
        intent_ref = latest["intent_ref"]
    else:
        saved = request.get("registration")
        registration = (
            host.run_store.read_registration(OpaqueId(request["run_id"]))
            if saved is None else RunRegistration.from_record(saved)
        )
        intent_ref = request["intent_ref"]
    if (
        registration.duet_id != host.identity.duet_id
        or registration.logical_run_id.value != request["run_id"]
        or registration.build_receipt_id != baseline.build_receipt_id
        or registration.manifest_id != baseline.build_manifest_id
        or registration.logical_registration_hash.value != request["registration_hash"]
        or intent_ref != request["intent_ref"]
    ):
        raise OpenChiaHostError("Saved Run does not belong to this Duet's exact build and launch.")
    return registration, intent_ref


def restore_run(host, baseline):
    selected = select_run(host, baseline)
    if selected is None:
        raise OpenChiaHostError("No saved Target Workflow Run; /run starts a fresh execution.")
    registration, intent_ref = selected
    intent = read_run_intent(host.store, intent_ref, registration)
    if intent["kind"] != "experiment.launch_intent.v1":
        raise OpenChiaHostError("The saved Run is not an ordinary Duet launch.")
    from episode_runtime.testing.launches import validate_launch_intent

    validate_launch_intent(host.store, replace(registration, resume_from=None), intent["record"])
    _, launch, _ = resolve_approved_launch(
        host.store, host.identity.duet_id.value,
        configuration_hash=intent["record"]["configuration_hash"],
    )
    return registration, intent_ref, intent["record"]["model_launch_id"], launch


async def prepare_continuation(host, executor, previous):
    from episode_runtime.testing.recovery import recover_stopped_run

    evidence = await asyncio.to_thread(
        recover_stopped_run, runs=host.run_store, artifacts=host.store,
        executor=executor, registration=previous,
    )
    if evidence is None:
        # No durable claim means START never authorized candidate execution.
        return previous, None
    if evidence.terminal_status.value not in {"interrupted", "cancelled", "resource_limited"}:
        # Finish the interrupted host publication, not another workflow Run.
        return previous, evidence
    reference = await asyncio.to_thread(InterruptedRunRef.from_run, host.run_store, previous.run_id)
    return replace(previous, resume_from=reference), None


def saved_run_status(host, baseline):
    selected = select_run(host, baseline)
    if selected is None:
        return None
    registration, _intent = selected
    from episode_runtime.testing.recovery import execution_owner_status

    ownership = execution_owner_status(host.store, registration)
    try:
        facts = host.run_store.read_run_record(registration.run_id)
    except RunStoreNotFound:
        facts = None
    record = None if facts is None else facts["record"]
    terminal = None if record is None else record["terminal_status"]
    state = terminal or {
        "live": "running", "stopped": "interrupted",
        "released": "interrupted", "unknown": "ownership_unknown",
    }[ownership["state"]]
    result = host._run_status_record(state=state, registration=registration, evidence=None, error=None)
    result.update(
        terminal_status=terminal, logical_run_id=registration.logical_run_id.value,
        ownership=ownership,
        continuation={"command": "/run continue", "verification_required": True},
    )
    if facts is not None:
        result["run_record"] = facts
        reference = None if record is None else record["evidence_ref"]
        result["evidence_id"] = None if reference is None else reference["artifact_id"]
    return result
