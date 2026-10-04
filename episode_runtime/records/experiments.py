"""Experiment record identities and persistence in the existing DuetStore.

This is the storage boundary, not a second store or an execution service.
Lifecycle modules validate their record bodies; this module owns names, keys,
envelopes and digest verification. Atomic dispatch still uses the store's
existing artifact-and-event transaction with ``artifact_fields``.
"""

from dataclasses import replace

from agent.duet_contracts import canonical_json, content_id, digest_record


# These keys preserve the existing identities; consolidation needs no migration.
RECORDS = {
    "build_job": ("build_request_id",),
    "build_job_result": ("build_receipt_id",),
    "build_job_result_attempt": ("build_receipt_id", "run_id"),
    "build_continuation": ("predecessor_build_request_id",),
    "build_parent": ("build_request_id",),
    "refinement_job": ("campaign_id",),
    "refinement_result": ("experiment_id",),
    "refinement_result_attempt": ("experiment_id", "run_id"),
    "instrument": ("experiment_id", "instrument_id"),
    "instrument_result": ("experiment_id", "instrument_id"),
    "instrument_result_attempt": ("experiment_id", "instrument_id", "run_id"),
    "dispatch": ("experiment_id",),
    "execution": ("run_id",),
    "continuation": ("predecessor_run_id",),
    "measurement": ("experiment_id",),
    "measurement_attempt": ("experiment_id", "execution_set_hash"),
    "numerical": ("experiment_id",),
    "playback": ("run_id",),
    "access": ("run_id", "episode_id", "key"),
    "recording_access": ("run_id", "episode_id", "key"),
    "boundary_access": ("run_id", "episode_id", "key"),
}

# Opaque ID kinds are limited to 32 characters. Keep established identities;
# only the new per-attempt report names need shorter ID namespaces.
_ID_KINDS = {
    "build_job_result_attempt": "experiment_build_result_attempt",
    "refinement_result_attempt": "experiment_refiner_attempt",
    "instrument_result_attempt": "experiment_instrument_attempt",
}


def record_id(kind, **identity):
    if kind not in RECORDS or set(identity) != set(RECORDS[kind]):
        raise ValueError(f"invalid experiment {kind} record identity")
    return content_id(_ID_KINDS.get(kind, f"experiment_{kind}"), identity).value


def artifact_fields(kind, *, duet_id, record, **identity):
    """Fields for the existing store API, including its atomic batch API."""
    return {
        "artifact_id": record_id(kind, **identity),
        "duet_id": duet_id,
        "kind": f"experiment.{kind}.v1",
        "revision": 1,
        "content_hash": digest_record(record).value,
        "record": record,
    }


def read_record(artifacts, kind, **identity):
    artifact_id = record_id(kind, **identity)
    row = artifacts.get_artifact(artifact_id)
    if row is not None and (
        row["artifact_id"] != artifact_id
        or row["kind"] != f"experiment.{kind}.v1"
        or row["revision"] != 1
        or digest_record(row["record"]).value != row["content_hash"]
    ):
        raise ValueError(f"experiment {kind} record differs from its committed identity")
    return row


def put_record(artifacts, kind, *, duet_id, record, **identity):
    artifacts.put_artifact(**artifact_fields(
        kind, duet_id=duet_id, record=record, **identity
    ))


def put_data(artifacts, duet_id, kind, record):
    """Save immutable inputs/selectors by content, never another response log."""
    reference = {
        "artifact_id": content_id(
            "experiment_data", {"duet_id": duet_id, "kind": kind, "record": record}
        ).value,
        "content_hash": digest_record(record).value,
    }
    artifacts.put_artifact(
        **reference,
        duet_id=duet_id,
        kind=f"experiment.{kind}.v1",
        revision=1,
        record=record,
    )
    return reference


def read_reference(duets, reference, duet_id):
    row = duets.get_artifact(reference["artifact_id"])
    if (
        row is None
        or row["duet_id"] != duet_id
        or row["content_hash"] != reference["content_hash"]
    ):
        raise ValueError(
            "reference is missing, changed, or outside its authorized Duet"
        )
    value = row["record"]
    if digest_record(value).value == reference["content_hash"]:
        # Plain reference data hashes its whole body. A schema identifier in
        # that data (for example a return-format description) is not an envelope.
        return row
    if row["kind"].startswith("refinement."):
        # Existing typed envelopes hash their semantic content, not the envelope
        # including its own hash. Reuse their decoder instead of inventing a
        # different identity convention for testing them.
        from iterative_episode_refiner.records import RefinementRecord

        record = RefinementRecord.from_record(value)
        if (
            record.ref.as_record() != reference
            or row["kind"] != f"refinement.{record.kind}.v1"
        ):
            raise ValueError("refinement evidence identity mismatch")
    else:
        raise ValueError("evidence bytes do not match their content digest")
    return row


def read_run_intent(duets, reference, registration):
    """An approved executable may serve another Duet's exact campaign.

    This authorizes only the linked intent, not browsing the other Duet. Run
    admission and campaign admission still own their respective authorities.
    The same immutable relationship is readable after a campaign has returned.
    Continued physical attempts keep that original intent; the caller admitting
    execution separately verifies the pinned terminal lineage with RunStore.
    """
    registration = replace(registration, resume_from=None)
    owner = registration.duet_id.value
    row = duets.get_artifact(reference["artifact_id"])
    if row is None or row["duet_id"] == owner:
        return read_reference(duets, reference, owner)
    if row["kind"] in {"experiment.instrument.v1", "experiment.dispatch.v1"}:
        row = read_reference(duets, reference, row["duet_id"])
        if row["kind"] == "experiment.dispatch.v1" and row["record"]["plan"].get("subject", {}).get("kind") not in {"grounded_control", "refinement_job", "campaign_evaluation"}:
            raise ValueError("cross-Duet experiment must name its exact declared campaign dependency")
        if canonical_json(row["record"]["registration"]) != canonical_json(registration.as_record()):
            raise ValueError("measurement intent does not bind this exact approved Run")
        return row
    if row["kind"] not in {
        "refinement.campaign.v1",
        "refinement.evaluation_run.v1",
        "refinement.measure_control_run.v1",
    }:
        raise ValueError("Run intent is outside its authorized Duet")
    row = read_reference(duets, reference, row["duet_id"])
    from iterative_episode_refiner.records import RefinementRecord

    record = RefinementRecord.from_record(row["record"])
    body = record.body
    if record.kind == "campaign":
        bound = (
            body["duet_id"] == row["duet_id"]
            and body["refiner_workflow_approval_ref"] == {
                "artifact_id": registration.workflow_approval_id.value,
                "content_hash": registration.workflow_approval_hash.value,
            }
            and body["refiner_manifest_ref"] == {
                "artifact_id": registration.manifest_id.value,
                "content_hash": registration.manifest_hash.value,
            }
        )
    else:
        bound = canonical_json(body["registration"]) == canonical_json(registration.as_record())
    if not bound:
        raise ValueError("campaign intent does not bind this exact approved Run")
    return row


def execution_attempts(artifacts, runs, run_id):
    """Resolve one logical execution's linked attempts, retaining physical rows.

    A link pins terminal predecessor evidence and the exact next dispatch. It
    grants neither launch authority nor permission to read a different intent.
    Missing terminal evidence for the last dispatched attempt remains pending.
    Index-only readers may pass runs=None; actual admission supplies RunStore
    to additionally verify every pinned terminal evidence boundary.
    """
    from agent.episode_contracts import OpaqueId
    from episode_runtime.continuation import validate_resume_registration
    from episode_runtime.contracts import RunRegistration

    run_id = OpaqueId(run_id) if isinstance(run_id, str) else run_id
    requested = read_record(artifacts, "execution", run_id=run_id.value)
    if requested is None:
        return ()
    registration = RunRegistration.from_record(requested["record"]["registration"])
    if registration.run_id != run_id:
        raise ValueError("execution binding names another Run")
    row = read_record(artifacts, "execution", run_id=registration.logical_run_id.value)
    if row is None:
        raise ValueError("continued execution has no original dispatch")
    original = RunRegistration.from_record(row["record"]["registration"])
    if original.resume_from is not None or original.run_id != registration.logical_run_id:
        raise ValueError("execution lineage has no original logical registration")
    intent_ref = row["record"]["intent_ref"]
    attempts, seen = [], set()
    while True:
        current = RunRegistration.from_record(row["record"]["registration"])
        if (
            current.run_id in seen
            or current.logical_registration_hash != original.registration_hash
            or row["duet_id"] != original.duet_id.value
            or row["revision"] != 1
            or row["record"]["intent_ref"] != intent_ref
            or row["artifact_id"] != record_id("execution", run_id=current.run_id.value)
        ):
            raise ValueError("execution continuation changes its logical owner or intent")
        seen.add(current.run_id)
        attempts.append(row)
        link = read_record(artifacts, "continuation", predecessor_run_id=current.run_id.value)
        if link is None:
            if run_id not in seen:
                raise ValueError("execution attempt has no committed continuation link")
            return tuple(attempts)
        body = link["record"]
        if (
            link["duet_id"] != current.duet_id.value
            or set(body) != {"resume_from", "execution_ref"}
            or body["resume_from"]["run_id"] != current.run_id.value
        ):
            raise ValueError("continuation link names a different predecessor")
        row = read_reference(artifacts, body["execution_ref"], current.duet_id.value)
        if row["kind"] != "experiment.execution.v1":
            raise ValueError("continuation link does not name an execution dispatch")
        following = RunRegistration.from_record(row["record"]["registration"])
        if (
            following.resume_from is None
            or following.resume_from.as_record() != body["resume_from"]
            or following.resume_from.registration_hash != current.registration_hash
        ):
            raise ValueError("continued execution differs from its pinned predecessor")
        if runs is not None:
            validate_resume_registration(runs, following)
