"""Declared measurement Runs within a shared experiment.

A checker is a dependency of the frozen measure, not another experimental
choice or an Episode created by the harness. It uses the ordinary Run execution,
recording and playback facilities; its result never replaces target evidence.
"""

import asyncio

from agent.duet_contracts import canonical_json, content_id
from agent.episode_contracts import OpaqueId
from episode_runtime.contracts import RunRegistration
from iterative_episode_refiner.checking import (
    admitted_build,
    prepare_checker_inputs,
    validate_checker_entry,
)
from iterative_episode_refiner.evidence import EvidenceReader
from iterative_episode_refiner.records import Ref
from function_library.models import _thaw_json

from ..records.experiments import (
    artifact_fields,
    put_record,
    read_record,
    read_reference,
)
from .execution import RunExecution, register_build
from .recordings import save_recording


def _ref(row):
    return {key: row[key] for key in ("artifact_id", "content_hash")}


def preview_instrument(definition, request, *, artifacts, builds, runs, duet_id):
    if builds is None:
        raise ValueError("independent measurement requires the checker BuildStore")
    definition = _thaw_json(definition)
    reader = EvidenceReader(artifacts, builds, runs)
    inputs = admitted_build(reader, definition, duet_id=duet_id)
    template = reader.reference(Ref.from_record(definition["launch_ref"]), duet_id)
    declaration = validate_checker_entry(inputs, definition, template)
    instrument_id = content_id("measurement_instrument", definition).value
    recording_ref = None
    if request["mode"] == "recorded":
        selector = read_reference(artifacts, request["recording_ref"], duet_id)
        if selector["kind"] != "experiment.recording.v1":
            raise ValueError("checker replay requires a shared source recording")
        execution = read_record(
            artifacts,
            "execution",
            run_id=selector["record"]["registration_ref"]["run_id"],
        )
        if execution is None:
            raise ValueError("checker replay source has no shared execution record")
        parent = read_reference(artifacts, execution["record"]["intent_ref"], duet_id)
        if parent["kind"] != "experiment.dispatch.v1":
            raise ValueError(
                "source Run has no recorded experimental measurement dependencies"
            )
        from .contracts import ExperimentSpec

        source_id = ExperimentSpec.from_record(parent["record"]["spec"]).experiment_id
        saved = read_record(
            artifacts,
            "instrument_result",
            experiment_id=source_id,
            instrument_id=instrument_id,
        )
        if saved is None or saved["record"]["recording_ref"] is None:
            raise ValueError(
                "the selected recording has no matching checker recording; live checking is not a fallback"
            )
        recording_ref = saved["record"]["recording_ref"]
    else:
        # Resolution reads settings only, not credentials or the network. The
        # checker gets its own admitted call graph and must accept these routes.
        from .service import ExperimentService

        ExperimentService(
            artifacts=artifacts, builds=builds, runs=runs
        )._resolve_live_launch(request, inputs, duet_id=duet_id)
    return {
        "instrument_id": instrument_id,
        "definition": definition,
        "build_receipt_ref": {
            "artifact_id": inputs.receipt.receipt_id.value,
            "content_hash": inputs.receipt.content_hash.value,
        },
        "workflow_ref": definition["workflow_ref"],
        "executing_duet_id": inputs.build_request.frozen_workflow.duet_id.value,
        "input_projection": definition["result_inputs"],
        "scope": {
            key: declaration[key]
            for key in (
                "kind", "entry_local_id", "included_local_ids", "included_grains",
                "origin", "path_local_ids", "edge_slots", "limitations",
            )
        },
        "mode": request["mode"],
        "recording_ref": recording_ref,
        "launch_ref": request["launch_ref"],
    }


def _declared(dispatch):
    return {
        row["instrument"]["instrument_id"]: row["instrument"]
        for row in dispatch["plan"]["measurements"]
        if row.get("eligible") and row.get("instrument") is not None
    }


def instrument_status(artifacts, runs, experiment_id, instrument_id):
    saved = read_record(
        artifacts,
        "instrument_result",
        experiment_id=experiment_id,
        instrument_id=instrument_id,
    )
    if saved is not None and saved["record"].get("checking_gap") is not None:
        return {
            **saved["record"],
            "instrument_id": instrument_id,
            "result_ref": _ref(saved),
        }
    row = read_record(
        artifacts,
        "instrument",
        experiment_id=experiment_id,
        instrument_id=instrument_id,
    )
    if row is None:
        return {"instrument_id": instrument_id, "execution_status": "not_dispatched"}
    result = RunExecution.status(
        artifacts, runs, row["record"]["registration"]["run_id"]
    )
    if result["execution_status"] == "not_dispatched":
        result["execution_status"] = "terminal_evidence_unavailable"
    return {**result, "instrument_id": instrument_id, "instrument_ref": _ref(row)}


def instrument_statuses(artifacts, runs, dispatch):
    from .contracts import ExperimentSpec

    value = dispatch["record"]
    experiment_id = ExperimentSpec.from_record(value["spec"]).experiment_id
    return [
        instrument_status(artifacts, runs, experiment_id, key)
        for key in _declared(value)
    ]


def _inputs(artifacts, builds, runs, parent, instrument, *, request_id):
    from ..records.experiments import execution_attempts

    target = RunRegistration.from_record(parent["registration"])
    attempts = execution_attempts(artifacts, runs, target.run_id.value)
    if attempts:
        target = RunRegistration.from_record(attempts[-1]["record"]["registration"])
    evidence = runs.read_evidence(target.run_id)
    if (
        runs.read_registration(target.run_id) != target
        or evidence.registration_hash != target.registration_hash
        or evidence.terminal_status.value != "succeeded"
    ):
        raise ValueError(
            "independent checking requires this experiment's successful Target Workflow Run"
        )
    campaign = read_reference(
        artifacts, parent["spec"]["campaign_ref"], target.duet_id.value
    )
    prepared = prepare_checker_inputs(
        EvidenceReader(artifacts, builds, runs),
        OpaqueId(campaign["record"]["campaign_id"]),
        instrument["definition"],
        evidence.as_record()["typed_status"],
        request_id=request_id,
        input_evidence_ref={
            "artifact_id": evidence.evidence_id.value,
            "content_hash": evidence.content_hash.value,
        },
    )
    if prepared.gap is not None:
        return prepared, evidence
    receipt = prepared.inputs.receipt
    if instrument["build_receipt_ref"] != {
        "artifact_id": receipt.receipt_id.value,
        "content_hash": receipt.content_hash.value,
    }:
        raise ValueError("checker source differs from the frozen measurement plan")
    return prepared, evidence


def validate_instrument_intent(artifacts, builds, runs, row, registration):
    """Re-derive the exact input projection before the ordinary Run is admitted."""
    body = row["record"]
    parent_row = read_reference(artifacts, body["experiment_ref"], row["duet_id"])
    if parent_row["kind"] != "experiment.dispatch.v1":
        raise ValueError("instrument requires its frozen parent experiment")
    parent = parent_row["record"]
    declared = _declared(parent).get(body["instrument_id"])
    if declared is None or canonical_json(body["registration"]) != canonical_json(
        registration.as_record()
    ):
        raise ValueError("checker Run differs from its declared instrument")
    prepared, evidence = _inputs(
        artifacts,
        builds,
        runs,
        parent,
        declared,
        request_id=registration.launch_request.request_id,
    )
    if prepared.gap is not None:
        raise ValueError("checker launch no longer has its required typed inputs")
    if (
        prepared.inputs.receipt.receipt_id != registration.build_receipt_id
        or prepared.execution_scope != registration.execution_scope
        or canonical_json(prepared.launch.as_record())
        != canonical_json(registration.launch_request.as_record())
        or body["target_execution_ref"]
        != {
            "artifact_id": evidence.evidence_id.value,
            "content_hash": evidence.content_hash.value,
        }
    ):
        raise ValueError(
            "checker launch lost its exact target evidence or frozen field mapping"
        )
    return {
        "mode": declared["mode"],
        "recording_ref": declared["recording_ref"],
        "launch_ref": declared["launch_ref"],
        "environment_ref": parent["spec"]["environment_ref"],
    }


def _prepare(service, dispatch, instrument):
    from .contracts import ExperimentSpec

    parent = dispatch["record"]
    experiment_id = ExperimentSpec.from_record(parent["spec"]).experiment_id
    identity = {
        "experiment_id": experiment_id,
        "instrument_id": instrument["instrument_id"],
    }
    existing = read_record(service.artifacts, "instrument", **identity)
    if existing is not None:
        return existing, None
    gap = read_record(service.artifacts, "instrument_result", **identity)
    if gap is not None:
        return None, None
    prepared, evidence = _inputs(
        service.artifacts,
        service.builds,
        service.runs,
        parent,
        instrument,
        request_id=content_id("launch_request", identity).value,
    )
    if prepared.gap is not None:
        put_record(
            service.artifacts,
            "instrument_result",
            duet_id=dispatch["duet_id"],
            record={
                "experiment_ref": _ref(dispatch),
                "instrument_id": instrument["instrument_id"],
                "instrument_ref": None,
                "run_id": None,
                "execution_status": "unavailable",
                "evidence_ref": None,
                "recording_ref": None,
                "target_execution_ref": {
                    "artifact_id": evidence.evidence_id.value,
                    "content_hash": evidence.content_hash.value,
                },
                "checking_gap": prepared.gap,
            },
            **identity,
        )
        return None, None
    inputs = prepared.inputs
    launch = (
        None
        if instrument["mode"] == "recorded"
        else service._resolve_live_launch(
            parent["spec"], inputs, duet_id=dispatch["duet_id"]
        )
    )
    registration, package = register_build(
        service.executor,
        service.builds,
        inputs,
        prepared.launch,
        RunRegistration.from_record(parent["registration"]).runtime_policy,
        execution_scope=prepared.execution_scope,
    )
    record = {
        "experiment_ref": _ref(dispatch),
        "instrument_id": instrument["instrument_id"],
        "registration": registration.as_record(),
        "target_execution_ref": {
            "artifact_id": evidence.evidence_id.value,
            "content_hash": evidence.content_hash.value,
        },
    }
    artifact = artifact_fields(
        "instrument", duet_id=dispatch["duet_id"], record=record, **identity
    )
    owner = service.artifacts.get_duet(dispatch["duet_id"])
    if (
        owner["authority_head_approval_id"]
        != parent["registration"]["authority_head_approval_id"]
    ):
        raise ValueError(
            "measurement no longer matches the experiment's authority head"
        )
    created = service.artifacts.put_artifacts_with_events(
        artifacts=(artifact,),
        events=(
            {
                "event_type": "experiment_instrument_dispatched",
                "provenance": "host_validation",
                "record": {**identity, "run_id": registration.run_id.value},
            },
        ),
        idempotency_artifact_ids=(artifact["artifact_id"],),
        duet_id=dispatch["duet_id"],
        expected_state=owner["state"],
        expected_authority_head_approval_id=owner["authority_head_approval_id"],
    )
    return (
        artifact
        if created
        else read_record(service.artifacts, "instrument", **identity),
        (registration, inputs, launch, package) if created else None,
    )


def _save_result(service, dispatch, instrument_id, result):
    from .contracts import ExperimentSpec

    if result.get("evidence_ref") is None:
        return
    experiment_id = ExperimentSpec.from_record(dispatch["record"]["spec"]).experiment_id
    identity = {"experiment_id": experiment_id, "instrument_id": instrument_id}
    registration = service.runs.read_registration(OpaqueId(result["run_id"]))
    kind = "instrument_result_attempt" if registration.resume_from is not None else "instrument_result"
    if registration.resume_from is not None:
        identity["run_id"] = registration.run_id.value
    existing = read_record(service.artifacts, kind, **identity)
    if existing is not None:
        return
    recording_ref = save_recording(service.artifacts, service.runs, result["run_id"])
    put_record(
        service.artifacts,
        kind,
        duet_id=dispatch["duet_id"],
        record={
            "experiment_ref": _ref(dispatch),
            "instrument_id": instrument_id,
            "instrument_ref": result["instrument_ref"],
            "run_id": result["run_id"],
            "execution_status": result["execution_status"],
            "evidence_ref": result["evidence_ref"],
            "recording_ref": recording_ref,
            "checking_gap": None,
        },
        **identity,
    )


async def run_instruments(service, experiment_id):
    dispatch = await asyncio.to_thread(
        read_record, service.artifacts, "dispatch", experiment_id=experiment_id
    )
    if dispatch is None:
        raise ValueError("measurement requires an existing experiment dispatch")
    from .measurements import measurement_run

    registration = await asyncio.to_thread(measurement_run, service.artifacts, experiment_id, runs=service.runs)
    target = await asyncio.to_thread(service.runs.read_evidence, registration.run_id)
    if target.terminal_status.value != "succeeded":
        return []
    results = []
    for key, instrument in _declared(dispatch["record"]).items():
        row, prepared = await asyncio.to_thread(_prepare, service, dispatch, instrument)
        if prepared is not None:
            await service._execute_registered(
                *prepared, _ref(row), launch_id=f"{experiment_id}:{key}"
            )
        result = await asyncio.to_thread(
            instrument_status, service.artifacts, service.runs, experiment_id, key
        )
        await asyncio.to_thread(_save_result, service, dispatch, key, result)
        results.append(result)
    return results
