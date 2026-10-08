"""Persist submitted candidate bytes independently of successful emission.

Human-edited source has its own provenance. It must survive the same partial
materialization boundary as rejected model source, without inventing a model call.
"""

from agent.duet_contracts import content_id
from agent.episode_contracts import Sha256Digest


def _identified(body):
    return {**body, "artifact_id": content_id("build_source_input", body).value,
            "content_hash": Sha256Digest.of_record(body).value}


def put_source_inputs(store, request, attempt, plan, *, sources, materialization, environment_source, origin):
    plan.validate_against(request, attempt)
    ids = {node.local_id for node in request.frozen_workflow.workflow.episodes}
    if set(sources) - ids or any(not isinstance(value, str) for value in sources.values()):
        raise ValueError("submitted source must name approved Episodes and contain text")
    if not isinstance(materialization, dict) or set(materialization) != ids:
        raise ValueError("submitted materialization must retain every approved Episode's choices")
    if not isinstance(origin, dict) or not origin:
        raise ValueError("submitted source requires its recorded origin")
    if environment_source is not None and not isinstance(environment_source, str):
        raise ValueError("submitted environment recipe must be text")
    record = _identified({
        "build_request_id": request.build_request_id.value,
        "build_attempt_id": attempt.build_attempt_id.value,
        "plan_id": plan.plan_id.value,
        "sources": {key: store.put_blob(value.encode("utf-8")).value for key, value in sorted(sources.items())},
        "materialization": materialization,
        "environment_source": None if environment_source is None else store.put_blob(environment_source.encode("utf-8")).value,
        "origin": origin,
    })
    store._put_record("source_inputs", attempt.build_attempt_id, record)
    return record


def read_source_inputs(store, inputs):
    path = store._record_path("source_inputs", inputs.build_attempt.build_attempt_id)
    if not path.exists():
        return None

    def validate(record):
        body = {key: value for key, value in record.items() if key not in {"artifact_id", "content_hash"}}
        if _identified(body) != record or any(record[key] != value for key, value in (
            ("build_request_id", inputs.build_request.build_request_id.value),
            ("build_attempt_id", inputs.build_attempt.build_attempt_id.value),
            ("plan_id", inputs.plan.plan_id.value),
        )):
            raise ValueError("submitted source identity or build linkage is stale")
        ids = {node.local_id for node in inputs.build_request.frozen_workflow.workflow.episodes}
        if set(record["sources"]) - ids or set(record["materialization"]) != ids:
            raise ValueError("submitted choices/source differ from the approved Episodes")
        for digest in (*record["sources"].values(), record["environment_source"]):
            if digest is not None:
                store.read_blob(digest)
        return dict(record)

    return store._read_record("source_inputs", inputs.build_attempt.build_attempt_id, validate)
