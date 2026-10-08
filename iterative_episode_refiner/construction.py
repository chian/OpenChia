"""Persist the Refiner's starting candidate directly from approved architecture.

This records construction inputs, not a preliminary construction pass. Episode
choices and source are authored by the Refiner's separately authorized Episodes.
Existing human work is imported through the same plan validators as later edits.
"""

from dataclasses import replace

from agent.duet_contracts import content_id
from episode_builder._contract_base import BuildAttempt, BuildDeficit
from episode_builder._contract_chain import WorkflowMaterializationPlan
from episode_builder.handoff import inspect_materialization
from episode_builder.inspection import MaterializationInspectionInput
from episode_builder.service import _materializer_identity, _incremental_predecessor_plan_id
from episode_builder.source_inputs import put_source_inputs
from episode_runtime.records.experiments import put_record, read_record

from .human_workspace import snapshot_from_candidate
from .plan_repair import revise_plan


def input_record(inputs):
    return {
        "build_request_id": inputs.build_request.build_request_id.value,
        "build_attempt_id": inputs.build_attempt.build_attempt_id.value,
        "plan_id": inputs.plan.plan_id.value,
        "emitted_module_ids_by_local_id": {
            item.local_id: item.emitted_module_id.value for item in inputs.emitted_modules
        },
        "admission_report_id": None if inputs.admission_report is None else inputs.admission_report.report_id.value,
        "manifest_id": None if inputs.manifest is None else inputs.manifest.manifest_id.value,
        "receipt_id": None if inputs.receipt is None else inputs.receipt.receipt_id.value,
    }


def _starting_snapshot(store, request):
    """Carry approved predecessor work, leaving changed contracts to be rebuilt."""
    from agent.episode_blueprints import workflow_blueprint_from_spec

    if request.predecessor_receipt is None:
        return None
    prior = store.inspection_inputs_for_receipt(request.predecessor_receipt.receipt_id)
    handoff = store.read_materialization_handoff(prior.receipt.receipt_id)
    snapshot = snapshot_from_candidate(
        prior, prior.plan, handoff=handoff,
        files={path: store.read_blob(digest).decode("utf-8")
               for path, digest in handoff["candidate"]["files"].items()},
    )
    old = {node.local_id: node for node in prior.build_request.frozen_workflow.workflow.episodes}
    workflow = request.frozen_workflow.workflow
    unchanged = {node.local_id for node in workflow.episodes if old.get(node.local_id) == node}
    return {
        **snapshot.as_record(),
        "architecture": workflow_blueprint_from_spec(workflow),
        "materialization": {node.local_id: snapshot.materialization.get(node.local_id)
                            if node.local_id in unchanged else None for node in workflow.episodes},
        "sources": {key: value for key, value in snapshot.sources.items() if key in unchanged},
    }


def prepare_construction(host, request, builder):
    """Idempotent host entry; no planner, emitter, admission or model call."""
    from agent.workflow_editing import approved_edit

    owner = request.frozen_workflow.duet_id.value
    saved = read_record(host.store, "construction_start", build_request_id=request.build_request_id.value)
    if saved is not None:
        if saved["duet_id"] != owner:
            raise ValueError("construction start belongs to another Duet")
        return host.build_store.inspection_inputs(**saved["record"]["inputs"]), saved["record"]["handoff"]
    editing = approved_edit(host, request)
    snapshot = editing["snapshot"] if editing is not None else _starting_snapshot(host.build_store, request)
    origin = ({"submission_ref": editing["reference"], "edit_id": editing["edit_id"]}
              if editing is not None else {"approved_build_request_id": request.build_request_id.value})
    attempt = BuildAttempt(
        build_request_id=request.build_request_id,
        materializer=_materializer_identity(builder.planner.call_options, builder.emitter.call_options),
        nonce=content_id("construction_start", {"request": request.build_request_id.value}).value.removeprefix("construction_start_"),
    )
    workflow = request.frozen_workflow.workflow
    plan = WorkflowMaterializationPlan(
        build_request_id=request.build_request_id, build_attempt_id=attempt.build_attempt_id,
        workflow_hash=workflow.workflow_hash,
        root_local_id=next(node.local_id for node in workflow.episodes if node.workflow_parent_local_id is None),
        nodes=(), edges=(), node_dispositions={},
        predecessor_plan_id=_incremental_predecessor_plan_id(request),
        deficits=tuple(BuildDeficit(
            code="node_unplanned", field_path="node_plan", episode_local_id=node.local_id,
            detail="This approved Episode awaits materialization by MaterializationImplementer.",
        ) for node in workflow.episodes),
    )
    inputs = MaterializationInspectionInput(request, attempt, plan, ())
    if snapshot is not None:
        from .human_workspace import WorkflowEditSnapshot

        snapshot = WorkflowEditSnapshot.from_record(snapshot)
        if snapshot.validate() != workflow:
            raise ValueError("construction input differs from the approved Architecture")
        designs = {node.local_id: node for node in workflow.episodes}

        def depth(key):
            count, parent = 0, designs[key].workflow_parent_local_id
            while parent is not None:
                count, parent = count + 1, designs[parent].workflow_parent_local_id
            return count

        failures = []
        for key in sorted(designs, key=lambda key: (-depth(key), key)):
            value = snapshot.materialization[key]
            if value is None:
                continue
            try:
                plan = revise_plan(plan, inputs, {key: value}, {key: {None}})
            except (TypeError, ValueError) as exc:
                failures.append(BuildDeficit(
                    code="submitted_plan_invalid", field_path="node_plan", episode_local_id=key,
                    detail=str(exc).replace("\x00", " ")[:2048],
                ))
        plan = revise_plan(plan, inputs, {}, {})
        plan = replace(plan, deficits=(*plan.deficits, *failures))
        inputs = MaterializationInspectionInput(request, attempt, plan, ())
    host.build_store.put_build_request(request)
    host.build_store.put_build_attempt(attempt)
    host.build_store.put_plan(plan)
    if snapshot is not None:
        put_source_inputs(host.build_store, request, attempt, plan,
                          sources=snapshot.sources, materialization=snapshot.materialization,
                          environment_source=snapshot.environment, origin=origin)
    handoff = inspect_materialization(host.build_store, inputs)
    put_record(host.store, "construction_start", duet_id=owner,
               build_request_id=request.build_request_id.value,
               record={"inputs": input_record(inputs), "handoff": handoff})
    return inputs, handoff
