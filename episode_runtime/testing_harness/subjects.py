"""Resolve declared campaign subjects without granting general cross-Duet access."""


def resolve_subject(request, *, inputs, artifacts, builds, runs=None):
    from .control_subjects import control_subject
    from .campaign_subjects import campaign_subject
    from .refinement_subjects import refinement_subject

    refiner = any(
        node.interface.startswith("refinement.") for node in inputs.plan.nodes
    )
    refinement_context = request["scope"]["kind"] == "refinement" or (
        refiner and request["mode"] == "numerical"
    )
    if refiner and not refinement_context and request["scope"]["kind"] != "component":
        raise ValueError(
            "A refiner Episode cannot execute through the ordinary target route. Select a fresh complete refinement job with its owning Duet binding, or numerical replay. Saved/recorded invocation execution requires coherent campaign restoration."
        )
    resolver = refinement_subject if refinement_context else control_subject
    subject = resolver(
        request, inputs=inputs, artifacts=artifacts, builds=builds, runs=runs
    )
    if subject is None and not refinement_context:
        return campaign_subject(request, inputs=inputs, artifacts=artifacts, builds=builds, runs=runs)
    return subject


def reference_owner(subject, path, default):
    if subject is None:
        return default
    if path == "recording_ref":
        return subject["recording_owner_duet_id"]
    if subject["kind"] == "campaign_evaluation" and path in {
        "start.artifact_ref", "boundary.parent_context_ref",
    }:
        return subject["recording_owner_duet_id"]
    if subject["kind"] == "refinement_job" and path not in {
        "campaign_ref",
        "launch_ref",
    }:
        return subject["recording_owner_duet_id"]
    return subject["owner_duet_id"]
