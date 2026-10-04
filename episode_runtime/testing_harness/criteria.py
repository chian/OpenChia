"""Frozen experimental criteria using the existing registered host predicates.

Configuration is not workflow approval or parent acceptance. A testing worker
may select only criteria delegated by its parent; it may not call registration.
The operator CLI prepares criteria before dispatch, independently of predictions.
Campaign-owned criteria retain their stronger existing admission policy.
"""

from typing import Annotated, Literal

from pydantic import Field, JsonValue, ValidationError

from agent.duet_contracts import canonical_json
from agent.episode_contracts import EpisodeFunctionSelectionSpec
from iterative_episode_refiner.records import pointer_parts

from .inputs import workflow_template
from .implementation import measurement_implementation
from .judgments import check_controls
from ..records.experiments import read_reference
from .schema import ArtifactReference, ScopeInput, Text, _ClosedInput


class PredicateSelection(_ClosedInput):
    library: Text
    function_id: Text
    interface: Text
    definition_id: Text
    arguments: dict[str, JsonValue]


class CriterionInput(_ClosedInput):
    schema_version: Literal[1]
    build_receipt_ref: ArtifactReference
    environment_ref: ArtifactReference
    requirement_key: Text
    description: Text
    scope: ScopeInput
    accepted_modes: Annotated[
        list[Literal["live_fresh", "live_saved", "recorded", "numerical"]],
        Field(min_length=1),
    ]
    input_payload: dict[str, JsonValue]
    predicate: PredicateSelection
    observation_path: str
    expected_value: JsonValue
    positive_controls: Annotated[list[JsonValue], Field(min_length=1)]
    negative_controls: Annotated[list[JsonValue], Field(min_length=1)]
    grounding_refs: Annotated[list[ArtifactReference], Field(min_length=1)]
    limitations: list[Text]


def criterion_schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "openchia:experiment-criterion:1",
        **CriterionInput.model_json_schema(),
    }


def semantic_launch(workflow, payload, scope=None):
    if scope is not None and scope["kind"] == "component":
        from ..components import component_input

        return component_input(payload)
    value = workflow_template(workflow, payload or None).as_record()
    value.pop("request_id")
    return value


def register_criterion(raw, *, builds, artifacts, duet_id):
    try:
        value = CriterionInput.model_validate(raw).model_dump(mode="json")
    except ValidationError as exc:
        detail = exc.errors(include_input=False, include_url=False)[0]
        raise ValueError(
            f"invalid criterion at {detail['loc']}: {detail['type']}"
        ) from None
    inputs = builds.inspection_inputs_for_receipt(
        value["build_receipt_ref"]["artifact_id"]
    )
    if (
        inputs.receipt.content_hash.value != value["build_receipt_ref"]["content_hash"]
        or inputs.build_request.frozen_workflow.duet_id.value != duet_id
        or not inputs.receipt.materialized
    ):
        raise ValueError(
            "criterion requires an admitted build belonging to the exact receipt and Duet"
        )
    pointer_parts(value["observation_path"])
    EpisodeFunctionSelectionSpec.from_record(value["predicate"])
    for ref in [value["environment_ref"], *value["grounding_refs"]]:
        read_reference(artifacts, ref, duet_id)
    controls = check_controls(
        value["predicate"],
        expected=value["expected_value"],
        positive=value["positive_controls"],
        negative=value["negative_controls"],
    )
    from ..records.experiments import put_data

    implementation_ref = put_data(
        artifacts, duet_id, "measurement_runtime", measurement_implementation()
    )
    record = {
        "criterion": value,
        "workflow_ref": {
            "artifact_id": inputs.build_request.frozen_workflow.artifact_id.value,
            "content_hash": inputs.build_request.frozen_workflow.workflow_hash.value,
        },
        "launch_inputs": semantic_launch(
            inputs.build_request.frozen_workflow, value["input_payload"], value["scope"]
        ),
        "control_results": controls,
        "implementation_ref": implementation_ref,
        "authority": "operator_configured_experimental_criterion",
    }
    measure_ref = put_data(artifacts, duet_id, "criterion", record)
    requirement_ref = put_data(
        artifacts,
        duet_id,
        "requirement",
        {
            "requirement_key": value["requirement_key"],
            "description": value["description"],
            "measure_ref": measure_ref,
            "workflow_ref": record["workflow_ref"],
        },
    )
    return {
        "requirement_ref": requirement_ref,
        "measure_ref": measure_ref,
        "control_results": controls,
        "acceptance_authority_granted": False,
    }


def resolve_criterion(
    requirement, request, *, artifacts, duet_id, workflow, launch_inputs=None, builds=None, runs=None
):
    row = read_reference(artifacts, requirement["measure_ref"], duet_id)
    if row["kind"] != "experiment.criterion.v1":
        from .campaign_criteria import resolve_campaign_criterion

        return resolve_campaign_criterion(
            requirement, request, artifacts=artifacts, duet_id=duet_id,
            workflow=workflow, launch_inputs=launch_inputs,
            builds=builds, runs=runs,
        )
    record = row["record"]
    value = CriterionInput.model_validate(record["criterion"]).model_dump(mode="json")
    linked = read_reference(artifacts, requirement["requirement_ref"], duet_id)
    if linked["kind"] != "experiment.requirement.v1" or linked["record"] != {
        "requirement_key": value["requirement_key"],
        "description": value["description"],
        "measure_ref": requirement["measure_ref"],
        "workflow_ref": record["workflow_ref"],
    }:
        raise ValueError("requirement does not bind the exact frozen measurement")
    if record["workflow_ref"] != {
        "artifact_id": workflow.artifact_id.value,
        "content_hash": workflow.workflow_hash.value,
    }:
        raise ValueError("criterion names a different approved workflow")
    for ref in value["grounding_refs"]:
        read_reference(artifacts, ref, duet_id)
    verify_implementation(artifacts, record["implementation_ref"], duet_id)
    # Revalidate the registered predicate and control relationship at dispatch;
    # source changes cannot silently bless a stale control receipt.
    controls = check_controls(
        value["predicate"],
        expected=value["expected_value"],
        positive=value["positive_controls"],
        negative=value["negative_controls"],
    )
    if canonical_json(controls) != canonical_json(record["control_results"]):
        raise ValueError("measurement control result differs from its frozen receipt")
    conditions = (
        (
            request["environment_ref"] == value["environment_ref"],
            "different_environment",
        ),
        (
            request["mode"] in value["accepted_modes"],
            "mode_does_not_establish_this_requirement",
        ),
        (
            canonical_json(request["scope"]) == canonical_json(value["scope"]),
            "scope_does_not_establish_this_requirement",
        ),
        (launch_inputs == record["launch_inputs"], "different_or_unresolved_inputs"),
    )
    reasons = [reason for applies, reason in conditions if not applies]
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "criterion": value,
        "requirement_ref": requirement["requirement_ref"],
        "measure_ref": requirement["measure_ref"],
        "implementation_ref": record["implementation_ref"],
        "authority": record["authority"],
        "owner_duet_id": duet_id,
    }


def verify_implementation(artifacts, reference, duet_id):
    row = read_reference(artifacts, reference, duet_id)
    if row["kind"] != "experiment.measurement_runtime.v1" or canonical_json(
        row["record"]
    ) != canonical_json(measurement_implementation()):
        raise ValueError(
            "measurement implementation differs from the frozen criterion; register a new criterion and fork the experiment"
        )


def preview_measurements(request, *, inputs, artifacts, builds=None, runs=None):
    from .control_subjects import control_subject
    from .campaign_subjects import campaign_subject

    subject = control_subject(request, inputs=inputs, artifacts=artifacts, builds=builds, runs=runs)
    if subject is not None:
        return [subject["measurement"]]
    subject = campaign_subject(request, inputs=inputs, artifacts=artifacts, builds=builds, runs=runs)
    workflow = inputs.build_request.frozen_workflow
    owner = workflow.duet_id.value if subject is None else subject["owner_duet_id"]
    payload = request["start"]["input_payload"]
    launch = None
    if request["scope"]["kind"] == "component":
        from .components import selected_inputs

        launch = selected_inputs(
            request, artifacts=artifacts, runs=runs, duet_id=workflow.duet_id.value
        )
    elif request["start"]["kind"] == "fresh":
        launch = semantic_launch(workflow, payload)
    elif request["start"]["kind"] == "saved_inputs" and runs is not None:
        from .recordings import load_recording

        source, _ = load_recording(
            artifacts, runs, request["start"]["artifact_ref"], workflow.duet_id.value
        )
        launch = semantic_launch(workflow, source.launch_request.as_record())
    return [
        resolve_criterion(
            requirement,
            request,
            artifacts=artifacts,
            duet_id=owner,
            workflow=workflow,
            launch_inputs=launch,
            builds=builds, runs=runs,
        )
        for requirement in request["requirements"]
    ]
