"""Resolve experiment boundaries against an admitted build without executing it."""

import json

from agent.duet_contracts import canonical_json, content_id, digest_record

from .schema import MODES, RUN_MODE_STARTS
from ..records.experiments import read_reference
from .candidates import resolve_candidate


def _gap(kind, path, detail, remedy):
    return {"kind": kind, "path": path, "detail": detail, "remedy": remedy}


def run_route_gaps(request, *, fresh_entry=False):
    if request["scope"]["kind"] == "refinement" and request["mode"] != "numerical":
        return [] if (
            request["mode"] == "live_fresh"
            and request["start"]["kind"] == "fresh"
            and request["boundary"] == {"parent_context_ref": None, "children": "execute"}
            and not request["scope"]["invocation_path"]
        ) else [_gap(
            "refinement_restoration_required", "mode",
            "A prepared refinement job currently executes from its exact fresh campaign. Recorded or checkpoint execution must restore the campaign as well as the worker.",
            "For the same interrupted experiment, use continue with its exact terminal reference and owning Duet-bound service. For a new experiment, use a fresh prepared campaign and live_fresh; no fallback is performed.",
        )]
    if fresh_entry:
        return [] if request["mode"] in RUN_MODE_STARTS and request["start"]["kind"] in RUN_MODE_STARTS[request["mode"]] else [
            _gap("execution_route_unavailable", "mode", "This grounded control requires checker execution with its explicit fresh entry context.", "Choose fresh or saved-input execution, or exact recorded-response playback; no numerical or checkpoint substitution.")
        ]
    if request["mode"] == "numerical":
        requirements = (
            (
                request["scope"]["kind"] in {"episode", "nested", "workflow", "refinement"},
                "scope.kind",
                "Numerical observation replay currently supports complete invocation histories, not a component or unit projection.",
            ),
            (
                request["start"]["kind"] == "saved_inputs",
                "start.kind",
                "Numerical mode needs the exact saved recording inputs; it does not restore a checkpoint.",
            ),
            (
                request["boundary"]["children"] == "reuse",
                "boundary.children",
                "Numerical mode reuses admitted observations and child results; it does not execute children.",
            ),
            (
                request["scope"]["kind"] in {"workflow", "refinement"}
                or bool(request["scope"]["invocation_path"]),
                "scope.invocation_path",
                "Select the exact invocation path for narrower numerical scope.",
            ),
            (
                request["scope"]["kind"] not in {"workflow", "refinement"}
                or not request["scope"]["invocation_path"],
                "scope.invocation_path",
                "Workflow numerical scope selects all recorded invocations; use a narrower scope to select an invocation path.",
            ),
        )
        return [
            _gap(
                "execution_route_unavailable",
                path,
                detail,
                "Select explicit recorded invocation data; no live fallback is available.",
            )
            for available, path, detail in requirements
            if not available
        ]
    scoped = request["scope"]["kind"] in {"episode", "nested", "unit"}
    requirements = (
        (
            request["mode"] in RUN_MODE_STARTS,
            "mode",
            "This mode has no candidate execution route; it cannot be replaced by fresh execution.",
        ),
        (
            request["start"]["kind"] in RUN_MODE_STARTS.get(request["mode"], ()),
            "start.kind",
            "Saved inputs can start a new experiment; arbitrary checkpoint starts cannot. Use continue with the exact terminal reference to resume the same interrupted experiment.",
        ),
        (
            request["scope"]["kind"] in {"workflow", "episode", "nested", "component", "unit"},
            "scope.kind",
            "Refinement jobs use their own declared refinement scope and exact prepared campaign, not a workflow-scope substitution.",
        ),
        (
            request["boundary"]["children"]
            == ("none" if request["scope"]["kind"] == "component" else "execute")
            and (
                request["boundary"]["parent_context_ref"] is not None
                if scoped
                else request["boundary"]["parent_context_ref"] is None
            ),
            "boundary",
            "Selected execution needs a saved parent boundary; recorded child-result substitution is not connected.",
        ),
        (
            bool(request["scope"]["invocation_path"])
            if scoped
            else not request["scope"]["invocation_path"],
            "scope.invocation_path",
            "Selected execution must identify its saved invocation; whole-workflow execution starts a new root.",
        ),
        (
            not scoped
            or (
                request["start"]["kind"] == "saved_inputs"
                and request["mode"] in {"live_saved", "recorded"}
            ),
            "start.kind",
            "Selected invocation execution currently reconstructs exact saved initial-state context; it cannot invent or restore a changed parent state.",
        ),
    )
    return [
        _gap(
            "execution_route_unavailable",
            path,
            detail,
            "Keep this experiment unchanged until its route is implemented, or explicitly design another experiment; no scope or mode substitution is performed.",
        )
        for available, path, detail in requirements
        if not available
    ]


def resolve_scope(spec, inputs, *, fresh_entry=False):
    """Keep requested members exact, even when missing dependencies prevent a Run.

    Repeatable calls form a graph, not necessarily a tree. Traverse with a visited
    set; an allowed recursive edge does not mean manufacturing new design nodes.
    """
    request = spec.as_record()
    scope = request["scope"]
    plan = inputs.plan
    nodes = {node.local_id: node for node in plan.nodes}
    included = set(scope["included_local_ids"])
    gaps = []
    unknown = included - nodes.keys()
    if unknown:
        gaps.append(
            _gap(
                "unknown_episode",
                "scope.included_local_ids",
                f"Candidate has no Episodes {sorted(unknown)}.",
                "Select local IDs from this exact build's plan.",
            )
        )
    entry = nodes.get(scope["entry_local_id"])
    if scope["kind"] in {"workflow", "refinement"}:
        if included != nodes.keys() or scope["entry_local_id"] != plan.root_local_id:
            gaps.append(
                _gap(
                    "incomplete_workflow",
                    "scope",
                    "Full-workflow scope must explicitly select the root and every template.",
                    "Include the complete plan, or choose a narrower scope.",
                )
            )
    outgoing = [edge for edge in plan.all_edges if edge.parent_local_id in included]
    omitted = [edge for edge in outgoing if edge.child_local_id not in included]
    if (
        scope["kind"] != "component"
        and omitted
        and request["boundary"]["children"] == "execute"
    ):
        gaps.append(
            _gap(
                "child_outside_scope",
                "boundary.children",
                "Executing declared children could leave the explicitly selected scope.",
                "Select the needed nested group, or explicitly reuse recorded child boundaries.",
            )
        )
    if request["boundary"]["children"] == "reuse" and request["recording_ref"] is None:
        gaps.append(
            _gap(
                "child_recording_missing",
                "recording_ref",
                "Reusing child results needs a matching boundary recording.",
                "Provide a recording with the exact child request, context and typed return.",
            )
        )
    if (
        entry is not None
        and entry.local_id != plan.root_local_id
        and scope["kind"] != "component"
    ):
        if (
            request["boundary"]["parent_context_ref"] is None
            and request["mode"] != "numerical"
        ):
            gaps.append(
                _gap(
                    "parent_context_missing",
                    "boundary.parent_context_ref",
                    "A child cannot be promoted to a root with an invented goal or shared state.",
                    "Provide its saved parent request and scoped goal state.",
                )
            )
        if not scope["invocation_path"] and not fresh_entry:
            gaps.append(
                _gap(
                    "invocation_missing",
                    "scope.invocation_path",
                    "A template ID alone does not identify a nested invocation.",
                    "Select the saved invocation's complete path, including keys.",
                )
            )
    reachable = {scope["entry_local_id"]}
    pending = list(reachable)
    while pending:
        parent = pending.pop()
        for edge in outgoing:
            child = edge.child_local_id
            if (
                edge.parent_local_id == parent
                and child in included
                and child not in reachable
            ):
                reachable.add(child)
                pending.append(child)
    if included - reachable:
        gaps.append(
            _gap(
                "disconnected_scope",
                "scope.included_local_ids",
                f"These templates are unreachable from the entry: {sorted(included - reachable)}.",
                "Choose a connected scope or separate experiments.",
            )
        )
    definitions = () if entry is None else entry.function_definition_ids
    definition = scope["component_definition_id"]
    if definition is not None and definition not in definitions:
        gaps.append(
            _gap(
                "component_not_bound",
                "scope.component_definition_id",
                "The selected definition is not used by the candidate's entry Episode.",
                "Select an exact registered definition from this Episode's materialized design.",
            )
        )
    return {
        "kind": scope["kind"],
        "entry_local_id": scope["entry_local_id"],
        "included_local_ids": sorted(included),
        "excluded_local_ids": sorted(nodes.keys() - included),
        "component_definition_id": definition,
        "available_component_bindings": []
        if entry is None
        else [
            {
                key: binding[key]
                for key in ("role", "definition_id", "interface", "arguments")
            }
            for binding in entry.as_record()["selected_function_bindings"]
            if binding["source"] == "library"
        ],
        "component_bindings": _component_bindings(entry, definition)
        if scope["kind"] == "component"
        else [],
        "unit_label": scope["unit_label"],
        "invocation_path": scope["invocation_path"],
        "internal_edges": [
            edge.as_record() for edge in outgoing if edge.child_local_id in included
        ],
        "external_child_edges": [edge.as_record() for edge in omitted],
        "capabilities": sorted({
            name
            for key in included & nodes.keys()
            for name in nodes[key].capability_names
        }),
        "gaps": gaps,
    }


def _component_bindings(entry, definition):
    from .components import describe_bindings

    return [] if entry is None else describe_bindings(entry, definition)


def preview_experiment(spec, *, builds, artifacts, runs=None, duet_binding=None, refinement_evaluations=None):
    """Read-only preview. Resolving a scope is not permission to execute it.

    ``artifacts`` is the existing DuetStore, not a second harness database. The
    execution service still has to admit each resolved role-specific contract.
    """
    request = spec.as_record()
    gaps = []
    receipt_ref = request["build_receipt_ref"]
    inputs = builds.inspection_inputs_for_receipt(receipt_ref["artifact_id"])
    if inputs.receipt.content_hash.value != receipt_ref["content_hash"]:
        raise ValueError("build receipt hash differs from experiment")
    if not inputs.receipt.materialized:
        gaps.append(
            _gap(
                "build_not_admitted",
                "build_receipt_ref",
                "The candidate has no admitted executable source package.",
                "Materialize and admit the candidate before requesting execution.",
            )
        )
    references = {
        "environment_ref": request["environment_ref"],
        "start.artifact_ref": request["start"]["artifact_ref"],
        "boundary.parent_context_ref": request["boundary"]["parent_context_ref"],
        **{
            key: request[key] for key in ("recording_ref", "launch_ref", "campaign_ref")
        },
    }
    for index, requirement in enumerate(request["requirements"]):
        for key in ("requirement_ref", "measure_ref"):
            references[f"requirements.{index}.{key}"] = requirement[key]
    duet_id = inputs.build_request.frozen_workflow.duet_id.value
    from .subjects import resolve_subject, reference_owner

    subject = None
    try:
        subject = resolve_subject(request, inputs=inputs, artifacts=artifacts, builds=builds, runs=runs)
    except ValueError as exc:
        gaps.append(_gap("refinement_context_invalid" if request["scope"]["kind"] == "refinement" else "control_context_invalid", "campaign_ref" if request["scope"]["kind"] == "refinement" else "requirements", str(exc), "Use the exact prepared campaign or assigned grounded control and its declared executable."))
    if subject is not None:
        duet_id = subject["owner_duet_id"]
        if subject["kind"] == "refinement_job" and request["mode"] != "numerical":
            try:
                from agent.duet_episode_transport import required_slots

                if duet_binding is None:
                    raise ValueError("The owning Duet agent is not bound to this experiment service. Use the owning host's refinement_experiment_service; Target Workflow launch settings are not the refiner model.")
                duet_binding.validate(artifacts=artifacts, reference=request["launch_ref"], owner_duet_id=duet_id, model_types=required_slots(inputs))
                if refinement_evaluations is None:
                    raise ValueError("The owning host has not attached the shared target-evaluation service.")
            except ValueError as exc:
                gaps.append(_gap("refinement_host_binding_missing", "launch_ref", str(exc), "Bind the owning Duet configuration and target evaluation service through the existing host; the CLI cannot invent an owner."))
    if (
        request["mode"] == "recorded"
        and request["scope"]["kind"] != "component"
        and any(
            node.contract.testing is not None
            for node in inputs.build_request.frozen_workflow.workflow.episodes
        )
    ):
        gaps.append(
            _gap(
                "nested_experiment_replay_unavailable",
                "mode",
                "Recorded execution of a testing workflow requires replay of its nested experiment responses, which is not yet connected.",
                "Keep this experiment pending or explicitly choose another mode; nested live execution is never substituted.",
            )
        )
    dependencies = []
    candidate = None
    try:
        candidate = resolve_candidate(
            request, inputs, artifacts=artifacts, builds=builds, subject=subject
        )
    except ValueError as exc:
        gaps.append(
            _gap(
                "candidate_source_mismatch",
                "candidate_ref",
                str(exc),
                "Use the exact build receipt as the candidate, or admit the actual refinement revision before testing it.",
            )
        )
    for path, reference in references.items():
        if reference is None:
            continue
        try:
            owner = reference_owner(subject, path, duet_id)
            artifact = read_reference(artifacts, reference, owner)
        except ValueError as exc:
            gaps.append(
                _gap(
                    "artifact_unavailable",
                    path,
                    str(exc),
                    "Supply the exact committed reference from the owning Duet; changed inputs require a new experiment.",
                )
            )
            continue
        dependencies.append({"path": path, "ref": reference, "kind": artifact["kind"]})
    mode = MODES[request["mode"]]
    for needed in mode["needs"]:
        if references[needed] is None:
            gaps.append(
                _gap(
                    "mode_input_missing",
                    needed,
                    f"Mode {request['mode']} requires {needed}.",
                    "Provide the missing reference or explicitly choose a different mode.",
                )
            )
    if request["scope"]["kind"] == "refinement" and request["campaign_ref"] is None:
        gaps.append(
            _gap(
                "campaign_missing",
                "campaign_ref",
                "Refinement execution needs its exact campaign.",
                "Select the admitted refinement campaign, not a bare Target Workflow.",
            )
        )
    fresh_entry = subject is not None and subject["kind"] == "grounded_control"
    scope = resolve_scope(spec, inputs, fresh_entry=fresh_entry)
    gaps.extend(scope.pop("gaps"))
    gaps.extend(run_route_gaps(request, fresh_entry=fresh_entry))
    if fresh_entry:
        scope.update(
            boundary_origin="fresh_typed_entry",
            limitations=list(subject["execution_scope"].boundary["limitations"]),
        )
    elif subject is not None and subject["kind"] == "refinement_job" and request["mode"] != "numerical":
        scope.update(boundary_origin="prepared_refinement_campaign", limitations=subject["limitations"], starting_state=subject["starting_state"])
    elif subject is not None and subject["kind"] == "refinement_job":
        scope.update(boundary_origin="recorded_controller_observations", limitations=["Reuses exact committed numerical snapshots; the current campaign is not replayed or changed."])
    execution_scope = None
    if request["mode"] != "numerical" and not gaps:
        from .boundaries import resolve_run_scope

        try:
            selected = resolve_run_scope(
                request, inputs=inputs, builds=builds, artifacts=artifacts, runs=runs
            )
            execution_scope = None if selected is None else selected.as_record()
        except ValueError as exc:
            gaps.append(
                _gap(
                    "component_input_unavailable"
                    if request["scope"]["kind"] == "component"
                    else "invocation_boundary_unavailable",
                    "start.input_payload"
                    if request["scope"]["kind"] == "component"
                    else "boundary.parent_context_ref",
                    str(exc),
                    "For component scope supply binding_role, adapter and inputs; configuration stays bound to the candidate. For invocation scope save the exact boundary and matching recording; changed GoalState requires restoration.",
                )
            )
    measurements = []
    if not gaps:
        from .criteria import preview_measurements

        try:
            measurements = preview_measurements(
                request, inputs=inputs, artifacts=artifacts, builds=builds, runs=runs
            )
        except ValueError as exc:
            gaps.append(
                _gap(
                    "measurement_context_invalid",
                    "requirements",
                    str(exc),
                    "Bind the exact frozen requirement and measure; different criteria require a new experiment.",
                )
            )
    numerical_inputs = None
    if request["mode"] == "numerical" and not gaps:
        if runs is None:
            gaps.append(
                _gap(
                    "recording_store_missing",
                    "run_store",
                    "Numerical scope must be resolved against its committed Run journal.",
                    "Supply --run-store alongside --duet-store and --build-store.",
                )
            )
        else:
            from .numerical import prepare_numerical

            try:
                source, recording, traces = prepare_numerical(
                    spec, builds=builds, artifacts=artifacts, runs=runs
                )
                numerical_inputs = {
                    "source_run_id": source.run_id.value,
                    "through_event_ref": recording["through_event_ref"],
                    "invocations": [
                        {
                            "episode_id": row["episode_id"],
                            "local_id": row["local_id"],
                            "episode_path": row["episode_path"],
                            "policy_ref": row["policy_ref"],
                            "reused_unit_count": len(row.get("inherited_history", ())),
                            **({"inherited_history_ref": row["inherited_history_ref"]}
                               if "inherited_history_ref" in row else {}),
                            "units": [
                                {
                                    "unit_id": event["payload"]["unit_id"],
                                    "event_ref": event["event_ref"],
                                }
                                for event in row["commits"]
                            ],
                        }
                        for row in traces
                    ],
                    "unobserved_local_ids": sorted(
                        set(scope["included_local_ids"])
                        - {row["local_id"] for row in traces}
                    ),
                }
            except ValueError as exc:
                gaps.append(
                    _gap(
                        "numerical_context_unavailable",
                        "recording_ref",
                        str(exc),
                        "Inspect the exact recording and request a scope with complete admitted observations.",
                    )
                )
    result = {
        "schema_version": 1,
        "experiment_id": spec.experiment_id,
        "experiment_hash": spec.content_hash,
        "resolved": not gaps,
        "execution_authorized": False,
        "candidate_ref": request["candidate_ref"],
        "candidate": candidate,
        "build_receipt_ref": receipt_ref,
        "workflow_hash": inputs.build_request.frozen_workflow.workflow_hash.value,
        "manifest_ref": None
        if inputs.manifest is None
        else {
            "artifact_id": inputs.manifest.manifest_id.value,
            "content_hash": digest_record(inputs.manifest.as_record()).value,
        },
        "scope": scope,
        "boundary": request["boundary"],
        "start": request["start"],
        "mode": request["mode"],
        "mode_evidence": mode,
        "dependencies": dependencies,
        "measurements": measurements,
        "measurement_implementation_hash": None,
        "numerical_inputs": numerical_inputs,
        "execution_scope": execution_scope,
        **({"subject": {
            "kind": subject["kind"], "reference": subject["reference"], "owner_duet_id": duet_id,
            **({"source_kind": subject["source_kind"], "source_owner_duet_id": subject["recording_owner_duet_id"]}
               if subject["kind"] == "campaign_evaluation" else {}),
        }} if subject is not None else {}),
        "gaps": gaps,
    }
    if any(row.get("eligible") and row.get("implementation_ref") is None for row in measurements):
        from .implementation import measurement_implementation

        result["measurement_implementation_hash"] = digest_record(measurement_implementation()).value
    # Return independent JSON data; the public mode catalog cannot be mutated by
    # changing a preview, and hashes bind the entire resolved scope.
    result = json.loads(canonical_json(result))
    return {"plan_id": content_id("experiment_plan", result).value, **result}
