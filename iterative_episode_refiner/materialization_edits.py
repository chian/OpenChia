"""Scoped candidate plan edits through the Builder's existing validators.

This edits implementation choices, not the approved workflow. Original Builder
artifacts remain immutable; a candidate carries its own plan revision until the
ordinary source-admission path publishes a new Materialized Specification.
"""

from collections.abc import Mapping

from agent.duet_contracts import FrozenDuetWorkflow, canonical_json
from agent.episode_contracts import OpaqueId
from episode_builder._contract_chain import WorkflowMaterializationPlan
from episode_builder.plan_choices import CHOICE_FIELDS
from episode_builder.planner import (
    _BASE_BINDING_ROLES,
    _architecture_numeric_bindings,
    _module_name,
    _plan_shape_for_children,
    materializer_function_catalog,
)
from function_library.epistemic_contract import exact
from function_library.models import _thaw_json

from .plan_repair import affected_paths, choices, revise_plan
from .records import Ref, RefinementRecord, pointer_parts


EDITABLE_FIELDS = frozenset((*CHOICE_FIELDS, "child_slots"))


def source_paths(workflow, plan):
    """Include approved nodes whose initial planning never produced a module."""
    planned = {node.local_id: node.module_name for node in plan.nodes}
    return {
        design.local_id: planned.get(
            design.local_id,
            _module_name(design.local_id, design.contract.spec_hash.value),
        ).replace(".", "/")
        + ".py"
        for design in workflow.episodes
    }


def baseline_inputs(evidence, contract):
    record = evidence.reference(
        Ref.from_record(contract.body["initial_build_receipt_ref"]),
        contract.body["duet_id"],
    )
    inputs = evidence.builds.inspection_inputs_for_receipt(
        OpaqueId(record["receipt_id"])
    )
    if inputs.receipt.as_record() != record:
        raise ValueError("candidate baseline differs from its stored build receipt")
    return inputs


def candidate_materialization(evidence, contract, candidate):
    if (
        candidate.body["materialization_ref"]
        == contract.body["initial_materialization_ref"]
    ):
        return None
    materialization = RefinementRecord.from_record(
        evidence.reference(
            Ref.from_record(candidate.body["materialization_ref"]),
            contract.body["duet_id"],
        )
    )
    if (
        materialization.kind != "materialization"
        or materialization.campaign_id != candidate.campaign_id
        or materialization.body["baseline_ref"]
        != contract.body["initial_materialization_ref"]
    ):
        raise ValueError(
            "candidate plan does not retain its campaign and approved baseline"
        )
    return materialization


def plan_body(materialization, instrument=None):
    if materialization is None:
        return None
    if instrument is None:
        return materialization.body["plan"]
    revision = materialization.body.get("instrument_plans", {}).get(
        instrument["spec_ref"]["artifact_id"]
    )
    if revision is None:
        return None
    exact(revision, {"baseline_ref", "plan"}, "instrument plan revision")
    if revision["baseline_ref"] != instrument["materialization_ref"]:
        raise ValueError("instrument plan changed its approved baseline")
    return revision["plan"]


def candidate_plan(evidence, contract, candidate, baseline=None, *, instrument=None):
    if instrument is not None and baseline is None:
        raise ValueError("instrument plans require their own verified build baseline")
    baseline = baseline or baseline_inputs(evidence, contract)
    body = plan_body(
        candidate_materialization(evidence, contract, candidate), instrument
    )
    if body is None:
        return baseline.plan
    plan = WorkflowMaterializationPlan.from_record(_thaw_json(body))
    plan.validate_against(baseline.build_request, baseline.build_attempt)
    return plan


def stored_plan(view, candidate, materialization=None, *, instrument=None):
    """Read the current candidate sheet without treating it as a build receipt."""
    reference = Ref.from_record(candidate.body["materialization_ref"])
    if (
        materialization is None
        and reference.as_record() != view.contract.body["initial_materialization_ref"]
    ):
        materialization = view.read(reference, "materialization")
    body = plan_body(materialization, instrument)
    if body is not None:
        return body
    baseline_ref = (
        instrument["materialization_ref"]
        if instrument is not None
        else view.contract.body["initial_materialization_ref"]
    )
    specification = view.data(Ref.from_record(baseline_ref))
    return next(
        part["value"]
        for part in specification["workflow_global"]
        if part["name"] == "materialization_plan"
    )


def edit_context(view, policy, assignment, *, instrument=None):
    typed_plan = WorkflowMaterializationPlan.from_record(
        _thaw_json(stored_plan(view, view.candidate, instrument=instrument))
    )
    plan = typed_plan.as_record()
    workflow_ref = (
        view.data(Ref.from_record(instrument["checker_ref"]))["workflow_ref"]
        if instrument is not None
        else view.contract.body["target_workflow_ref"]
    )
    workflow = FrozenDuetWorkflow.from_record(
        view.data(Ref.from_record(workflow_ref))
    ).workflow
    nodes = {node.local_id: node for node in typed_plan.nodes}
    designs = {design.local_id: design for design in workflow.episodes}
    paths = source_paths(workflow, typed_plan)
    local_ids = set()
    if instrument is None:
        catalog = view.data(
            Ref.from_record(view.contract.body["requirement_catalog_ref"])
        )
        local_ids.update(
            item["local_id"]
            for item in catalog["requirements"]
            if item["requirement_key"]
            in assignment.body["contribution_requirement_keys"]
        )
    else:
        paths = {key: instrument["paths"][path] for key, path in paths.items()}
    local_ids.update(
        key for key, path in paths.items() if path in assignment.body["writable_paths"]
    )
    targets = []
    for pointer in policy.get("materialization_edit_targets", ()):
        instrument_id, local_pointer = split_target(pointer)
        if instrument_id != (
            instrument["spec_ref"]["artifact_id"] if instrument is not None else None
        ):
            continue
        local_id, field = target_parts(local_pointer)
        if local_id not in designs:
            raise ValueError("materialization edit policy names an unapproved node")
        path = paths[local_id]
        if (
            path in assignment.body["writable_paths"]
            and path not in assignment.body["protected_paths"]
        ):
            payload = choices(typed_plan, local_id, workflow.repeatable_calls)
            if payload is None and field is not None:
                continue
            targets.append({
                "json_pointer": pointer,
                "before": payload if field is None else payload[field],
                "source_path": path,
                "value_shape": (
                    _plan_shape_for_children(
                        tuple(
                            node
                            for node in nodes.values()
                            if node.parent_local_id == local_id
                        )
                    )
                    if field is None
                    else None
                ),
            })
    calls = plan.get("repeatable_calls", {}).get("edges", ())
    planning_ids = (
        {target_parts(split_target(target["json_pointer"])[1])[0] for target in targets}
        if assignment.body["role"] in {"designer", "implementer"}
        else set()
    )
    planning_inputs = []
    for local_id in sorted(planning_ids):
        bindings, failure = _architecture_numeric_bindings(designs[local_id])
        planning_inputs.append({
            "local_id": local_id,
            "design": designs[local_id].as_record(),
            "architecture_owned_bindings": list(bindings),
            "binding_rule": (
                "The host installs architecture_owned_bindings when constructing "
                "or revising this node plan. Omit those fixed roles or copy them "
                "exactly; author components only for the other roles."
            ),
            "unavailable_binding": None if failure is None else failure.as_record(),
            "direct_children": [
                node.as_record()
                for node in nodes.values()
                if node.parent_local_id == local_id
            ],
            "missing_direct_children": [
                design.local_id
                for design in workflow.episodes
                if design.workflow_parent_local_id == local_id
                and design.local_id not in nodes
            ],
            "architecture_owned_calls": [
                call.as_record()
                for call in workflow.repeatable_calls
                if local_id in (call.caller_local_id, call.callee_template_local_id)
            ],
        })
    return {
        "materialization_ref": view.candidate.body["materialization_ref"],
        "plan_id": plan["plan_id"],
        "workflow_hash": plan["workflow_hash"],
        "projection": "assigned nodes and adjacent interfaces; not a new materialization receipt",
        "nodes": [node.as_record() for key, node in nodes.items() if key in local_ids],
        "missing_nodes": [
            {"design": design.as_record(), "source_path": paths[key]}
            for key, design in designs.items()
            if key in local_ids and key not in nodes
        ],
        "source_paths": {key: path for key, path in paths.items() if key in local_ids},
        "edges": [
            edge
            for edge in (*plan["edges"], *calls)
            if edge["parent_local_id"] in local_ids
            or edge["child_local_id"] in local_ids
        ],
        "deficits": [
            item
            for item in plan["deficits"]
            if item["episode_local_id"] is None or item["episode_local_id"] in local_ids
        ],
        "permitted_detail_edits": targets,
        "planning_inputs": planning_inputs,
        "required_base_roles": sorted(_BASE_BINDING_ROLES) if planning_ids else [],
        "function_catalog": list(materializer_function_catalog())
        if planning_ids
        else [],
    }


def target_parts(pointer):
    parts = pointer_parts(pointer)
    if (
        len(parts) not in {4, 5}
        or parts[0] != "episodes"
        or parts[2:4] != ("parts", "node_plan")
        or (len(parts) == 5 and parts[4] not in EDITABLE_FIELDS)
    ):
        raise ValueError(
            "detail edits must name node-plan choices or one permitted implementation field"
        )
    return parts[1], parts[4] if len(parts) == 5 else None


def split_target(pointer):
    parts = pointer_parts(pointer)
    if parts and parts[0] == "instrument_builds":
        if len(parts) < 3:
            raise ValueError(
                "instrument edit must name an exact build and node-plan target"
            )
        OpaqueId(parts[1])
        local_pointer = "/" + pointer.split("/", 3)[3]
        target_parts(local_pointer)
        return parts[1], local_pointer
    target_parts(pointer)
    return None, pointer


def _stale_value_detail(expected, submitted, pointer):
    """Locate the first real mismatch without repeating an entire node plan."""
    if isinstance(expected, Mapping) and isinstance(submitted, Mapping):
        for key in sorted(expected.keys() | submitted.keys()):
            child = pointer + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in expected:
                return f"{child}: submitted before contains an extra field"
            if key not in submitted:
                return f"{child}: submitted before omits the current field"
            if canonical_json(expected[key]) != canonical_json(submitted[key]):
                return _stale_value_detail(expected[key], submitted[key], child)
    if isinstance(expected, (list, tuple)) and isinstance(submitted, (list, tuple)):
        if len(expected) != len(submitted):
            return f"{pointer}: current length {len(expected)}, submitted length {len(submitted)}"
        for index, (left, right) in enumerate(zip(expected, submitted)):
            if canonical_json(left) != canonical_json(right):
                return _stale_value_detail(left, right, f"{pointer}/{index}")
    if isinstance(expected, str) and isinstance(submitted, str):
        index = next(
            (i for i, (left, right) in enumerate(zip(expected, submitted)) if left != right),
            min(len(expected), len(submitted)),
        )
        start, end = max(0, index - 12), index + 24
        return (
            f"{pointer}: string differs at character {index}; "
            f"current excerpt {expected[start:end]!r}, submitted excerpt {submitted[start:end]!r}. "
            "Literal backslash characters and newline characters are different values"
        )
    return (
        f"{pointer}: current {canonical_json(expected)[:160]}, "
        f"submitted {canonical_json(submitted)[:160]}"
    )


def _revise_edits(current, inputs, operations):
    workflow = inputs.build_request.frozen_workflow.workflow
    designs = {node.local_id for node in workflow.episodes}
    proposed, fields = {}, {}
    changed = set()
    for operation in operations:
        exact(
            operation, {"json_pointer", "before", "after"}, "implementation-detail edit"
        )
        pointer = operation["json_pointer"]
        local_id, field = target_parts(pointer)
        if pointer in changed:
            raise ValueError("one change cannot edit a plan field twice")
        if local_id not in designs:
            raise ValueError("plan repair cannot create an unapproved Episode")
        selected_fields = fields.setdefault(local_id, set())
        if None in selected_fields or (field is None and selected_fields):
            raise ValueError("whole-node and field edits must not overlap")
        prior = choices(current, local_id, workflow.repeatable_calls)
        if prior is None and field is not None:
            raise ValueError("a missing node requires a complete planner-choice object")
        before = prior if field is None else prior[field]
        if canonical_json(before) != canonical_json(operation["before"]):
            detail = _stale_value_detail(before, operation["before"], pointer)
            raise ValueError(
                "implementation-detail edit has a stale before value: " + detail
                + ". Copy the exact before value from the current "
                "candidate_materialization.permitted_detail_edits; put intended changes only in after."
            )
        if canonical_json(before) == canonical_json(operation["after"]):
            raise ValueError("implementation-detail edit is empty")
        if field is None:
            proposed[local_id] = operation["after"]
        else:
            proposed.setdefault(local_id, prior)[field] = operation["after"]
        selected_fields.add(field)
        changed.add(pointer)
    if not changed:
        raise ValueError("candidate materialization needs an actual detail change")
    plan = revise_plan(current, inputs, proposed, fields)
    if plan == current:
        raise ValueError("normalized plan repair does not change the candidate")
    paths = source_paths(workflow, plan)
    return plan, set(affected_paths(current, plan)) | {paths[key] for key in proposed}


def prepare_edits(evidence, contract, candidate, operations):
    """One atomic plan revision across approved packages, using the same Builder."""
    from .instrument_builds import _baseline

    grouped, changed = {}, set()
    for operation in operations:
        exact(
            operation, {"json_pointer", "before", "after"}, "implementation-detail edit"
        )
        pointer = operation["json_pointer"]
        if pointer in changed:
            raise ValueError("one change cannot edit a plan field twice")
        instrument_id, local_pointer = split_target(pointer)
        grouped.setdefault(instrument_id, []).append({
            **operation,
            "json_pointer": local_pointer,
        })
        changed.add(pointer)
    if not changed:
        raise ValueError("candidate materialization needs an actual detail change")
    previous = candidate_materialization(evidence, contract, candidate)
    primary = candidate_plan(evidence, contract, candidate)
    instrument_plans = (
        _thaw_json(previous.body.get("instrument_plans", {})) if previous else {}
    )
    manifest_ref = contract.body.get("instrument_builds_ref")
    builds = (
        evidence.reference(Ref.from_record(manifest_ref), contract.body["duet_id"])[
            "builds"
        ]
        if manifest_ref
        else ()
    )
    instruments = {item["spec_ref"]["artifact_id"]: item for item in builds}
    affected = set()
    for instrument_id, edits in grouped.items():
        if instrument_id is None:
            primary, paths = _revise_edits(
                primary, baseline_inputs(evidence, contract), edits
            )
        else:
            if instrument_id not in instruments:
                raise ValueError("plan repair names an unauthorized instrument")
            instrument = instruments[instrument_id]
            checker = evidence.reference(
                Ref.from_record(instrument["checker_ref"]), contract.body["duet_id"]
            )
            inputs = _baseline(evidence, contract.body["duet_id"], checker)
            current = candidate_plan(
                evidence, contract, candidate, inputs, instrument=instrument
            )
            plan, local_paths = _revise_edits(current, inputs, edits)
            paths = {instrument["paths"][path] for path in local_paths}
            instrument_plans[instrument_id] = {
                "baseline_ref": instrument["materialization_ref"],
                "plan": plan.as_record(),
            }
        affected.update(paths)
    body = {
        "baseline_ref": contract.body["initial_materialization_ref"],
        "plan": primary.as_record(),
        "changed_targets": sorted(changed),
    }
    if instrument_plans:
        body["instrument_plans"] = instrument_plans
    return {"record": body, "affected_source_paths": sorted(affected)}
