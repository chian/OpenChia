"""Project committed host experiment responses into scoped learning evidence."""

from function_library.epistemic_schemas import ArtifactEnvelope, canonical, identity
from function_library.models import _thaw_json
from function_library.testing_admission import MEASUREMENT_KIND

from ..contracts import RunEventKind, RunEventOrigin


def measured_sources(*, events, episode_id, scope):
    requests = {
        (event.run_id, event.payload["request_id"]): event
        for event in events
        if event.kind is RunEventKind.EXPERIMENT_REQUESTED
        and event.origin is RunEventOrigin.WORKER
        and event.episode_id == episode_id
        and event.payload["operation"] in {"run", "results", "status"}
    }
    for event in events:
        if (
            event.kind is not RunEventKind.EXPERIMENT_RESPONDED
            or event.origin is not RunEventOrigin.HOST
            or event.episode_id != episode_id
            or (event.run_id, event.payload["request_id"]) not in requests
        ):
            continue
        response = event.payload["response"]
        report = response.get("measurement")
        if not report or response.get("execution_status") != "succeeded":
            continue
        for outcome in report["outcomes"]:
            if outcome["status"] not in {"pass", "fail"}:
                continue
            observation = {
                "subject": {
                    "candidate_ref": report["candidate_ref"],
                    "requirement_ref": outcome["requirement_ref"],
                    "measure_ref": outcome["measure_ref"],
                    "scope": report["scope"],
                    "context": report["context"],
                    # Re-reading saved inputs does not make the same finding new.
                    "evidence_mode": "live"
                    if report["mode"] in {"live_fresh", "live_saved"}
                    else report["mode"],
                },
                "status": outcome["status"],
                "observed": outcome["observed"],
                "criterion_expected": outcome["criterion_expected"],
                "limitations": list(outcome["limitations"])
                + list(report["limitations"]),
            }
            yield ArtifactEnvelope(
                schema_id="openchia.experiment-measurement",
                schema_version=1,
                run_id=event.run_id.value,
                episode_id=scope["key"],
                unit_id=identity("measured_requirement", observation),
                producer_call_id="host-experiment-measurement",
                evidence_refs=(
                    event.event_id.value,
                    report["measurement_ref"]["artifact_id"],
                ),
                body={
                    "kind": MEASUREMENT_KIND,
                    "text": canonical(observation).decode(),
                    "observation": _thaw_json(observation),
                },
            ).as_record()
