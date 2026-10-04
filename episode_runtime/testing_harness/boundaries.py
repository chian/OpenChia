"""Saved invocation boundaries derived from the shared, verified Run recording."""

from agent.duet_contracts import canonical_json
from method_loop import EpisodeGoal

from ..broker import admitted_call_graph, resolve_call_path
from ..scoped import RunScope, initial_launch
from .recordings import load_recording
from ..records.experiments import read_reference


def fresh_entry_declaration(inputs, *, entry_local_id):
    """Resolve declared scope before target data or execution exists."""
    from function_library.models import _thaw_json

    nodes = {node.local_id: node for node in inputs.plan.nodes}
    if entry_local_id not in nodes or entry_local_id == inputs.plan.root_local_id:
        raise ValueError(
            "typed checker input requires an existing declared non-root entry"
        )
    node = nodes[entry_local_id]
    path, edge_slots = [node], []
    while path[-1].local_id != inputs.plan.root_local_id:
        parent = nodes.get(path[-1].parent_local_id)
        edges = [
            edge
            for edge in inputs.plan.edges
            if edge.child_local_id == path[-1].local_id
        ]
        if (
            parent is None
            or parent in path
            or len(edges) != 1
            or edges[0].parent_local_id != parent.local_id
        ):
            raise ValueError("fresh entry requires an unambiguous concrete parent path")
        path.append(parent)
        edge_slots.append(edges[0].slot_name)
    path.reverse()
    edge_slots.reverse()
    included = {entry_local_id}
    pending = [entry_local_id]
    while pending:
        parent = pending.pop()
        for edge in inputs.plan.all_edges:
            if edge.parent_local_id == parent and edge.child_local_id not in included:
                included.add(edge.child_local_id)
                pending.append(edge.child_local_id)
    if included & {node.local_id for node in path[:-1]}:
        raise ValueError("checker entry may not call an excluded ancestor")
    contracts = {
        node.local_id: node.contract
        for node in inputs.build_request.frozen_workflow.workflow.episodes
    }
    return {
        "kind": "episode" if len(included) == 1 else "nested",
        "entry_local_id": entry_local_id,
        "included_local_ids": sorted(included),
        "included_grains": [nodes[key].grain_name for key in sorted(included)],
        "origin": "fresh_typed_entry",
        "workflow_hash": inputs.build_request.frozen_workflow.workflow_hash.value,
        "build_receipt_id": inputs.receipt.receipt_id.value,
        "path_grains": [node.grain_name for node in path],
        "path_local_ids": [node.local_id for node in path],
        "edge_slots": edge_slots,
        "goals": [
            {
                "objective": contracts[node.local_id].goal,
                "result_contract": _thaw_json(node.result_payload_contract),
            }
            for node in path
        ],
        "limitations": [
            "This is new test context derived from the frozen checker declaration, not a recorded parent-selected goal.",
            "The root state initializer and scoper run; ancestor Episodes and their controllers do not.",
            "Only initial state is supplied; parent-produced state and interrupted continuation are not reconstructed.",
        ],
    }


def fresh_entry_scope(
    inputs,
    *,
    entry_local_id,
    input_payload,
    definition_ref,
    input_evidence_ref,
    artifacts,
    duet_id,
):
    """Bind exact input evidence to an explicitly new test entry."""
    from handoff_library import HandoffPayloadContract
    from ..scoped import FreshEntryScope
    from ..records.experiments import put_data

    declaration = fresh_entry_declaration(inputs, entry_local_id=entry_local_id)
    node = next(node for node in inputs.plan.nodes if node.local_id == entry_local_id)
    HandoffPayloadContract.from_record(node.request_payload_contract).validate(**{
        **input_payload,
        "artifact_ids_by_role": {
            key: tuple(value)
            for key, value in input_payload["artifact_ids_by_role"].items()
        },
    })
    scope_fields = {key: declaration.pop(key) for key in (
        "kind", "entry_local_id", "included_local_ids", "included_grains"
    )}
    boundary = {
        **declaration,
        "input_payload": input_payload,
        "definition_ref": definition_ref,
        "input_evidence_ref": input_evidence_ref,
    }
    reference = put_data(artifacts, duet_id, "fresh_entry_boundary", boundary)
    scope = FreshEntryScope(
        **scope_fields,
        boundary_ref=reference,
        boundary=boundary,
    )
    scope.validate_plan(inputs.plan)
    return scope


def boundary_record(artifacts, runs, recording_ref, episode_id, duet_id):
    source, recording = load_recording(artifacts, runs, recording_ref, duet_id)
    invocations = recording["invocations"]
    selected = [row for row in invocations if row["episode_id"] == episode_id]
    if len(selected) != 1:
        raise ValueError("boundary requires exactly one recorded invocation")
    entry = selected[0]
    needed = {"request", "goal_view", "goal_state_id", "initial_goal_state_id"}
    if not needed <= entry.keys():
        raise ValueError(
            "recording lacks an exact invocation request, goal view or state identity; capture a new source Run"
        )
    path = entry["episode_path"]
    goal = EpisodeGoal.from_record(entry["request"]["goal"])
    parent_goal_id = ""
    if len(path) > 1:
        parents = [row for row in invocations if row["episode_path"] == path[:-1]]
        inherited = source.execution_scope
        inherited_entry = inherited is not None and tuple(
            (part["grain"], part["key"]) for part in path
        ) == inherited.entry_path(source.run_id.value)
        if not parents and inherited_entry:
            from ..scoped import FreshEntryScope

            if isinstance(inherited, FreshEntryScope):
                declared_goal = inherited.goal(source)
                if declared_goal != goal:
                    raise ValueError(
                        "recorded checker goal differs from its declared fresh context"
                    )
                parent_goal_id = declared_goal.parent_goal_id
            else:
                parent_goal_id = inherited.boundary["parent_goal_id"]
        elif len(parents) != 1:
            raise ValueError("recording omits the selected invocation's parent context")
        else:
            parent_goal = EpisodeGoal.from_record(parents[0]["request"]["goal"])
            parent_goal_id = parent_goal.goal_id
            if goal.task_context != parent_goal.task_context:
                raise ValueError("saved child changes the parent's root task context")
    if goal.parent_goal_id != parent_goal_id:
        raise ValueError("saved goal does not identify its recorded parent")
    return {
        "source_run_id": source.run_id.value,
        "source_workflow_hash": source.workflow_hash.value,
        "source_build_receipt_id": source.build_receipt_id.value,
        "source_launch_request": initial_launch(source).as_record(),
        "episode_path": path,
        "entry_request": entry["request"],
        "parent_goal_id": parent_goal_id,
        "goal_view": entry["goal_view"],
        "goal_state_id": entry["goal_state_id"],
        "initial_goal_state_id": entry["initial_goal_state_id"],
        "event_ref": entry["event_ref"],
        "recording_ref": recording_ref,
    }


def save_boundary(artifacts, runs, recording_ref, episode_id, duet_id):
    from ..records.experiments import put_data

    record = boundary_record(artifacts, runs, recording_ref, episode_id, duet_id)
    return put_data(artifacts, duet_id, "boundary", record)


def capture_boundary(artifacts, runs, run_id, episode_id):
    from agent.episode_contracts import OpaqueId
    from .recordings import save_recording

    source = runs.read_registration(OpaqueId(run_id))
    recording_ref = save_recording(artifacts, runs, run_id)
    reference = save_boundary(
        artifacts, runs, recording_ref, episode_id, source.duet_id.value
    )
    record = read_reference(artifacts, reference, source.duet_id.value)["record"]
    return {
        "parent_context_ref": reference,
        "recording_ref": recording_ref,
        "invocation_path": record["episode_path"],
        "initial_state_reproducible": record["goal_state_id"]
        == record["initial_goal_state_id"],
        "limitations": [
            "This boundary is evidence, not execution authority or a restored interrupted loop.",
            "Selected execution reuses parent context without running ancestors; changed GoalState restoration is not yet supported.",
        ],
    }


def resolve_run_scope(request, *, inputs, builds, artifacts, runs):
    from .subjects import resolve_subject

    subject = resolve_subject(request, inputs=inputs, artifacts=artifacts, builds=builds, runs=runs)
    if subject is not None and subject["kind"] in {"grounded_control", "refinement_job"}:
        return subject["execution_scope"]
    if request["scope"]["kind"] == "workflow":
        return None
    if request["scope"]["kind"] == "component":
        from .components import resolve_component_scope

        return resolve_component_scope(
            request, inputs=inputs, artifacts=artifacts, runs=runs
        )
    if request["scope"]["kind"] not in {"episode", "nested", "unit"}:
        raise ValueError("this route requires workflow, episode or nested scope")
    duet_id = inputs.build_request.frozen_workflow.duet_id.value
    reference = request["boundary"]["parent_context_ref"]
    if reference is None or runs is None:
        raise ValueError(
            "selected execution needs its saved boundary and source RunStore"
        )
    row = read_reference(artifacts, reference, duet_id)
    unit_selection = {}
    kind = request["scope"]["kind"]
    expected_kind = (
        "experiment.unit_boundary.v1" if kind == "unit" else "experiment.boundary.v1"
    )
    if row["kind"] != expected_kind:
        raise ValueError(
            "parent_context_ref must name a host-projected invocation boundary"
        )
    recorded = row["record"]
    if kind == "unit":
        from .units import unit_boundary_record

        actual_unit = unit_boundary_record(
            artifacts,
            runs,
            recorded["invocation"]["recording_ref"],
            recorded["unit_ref"]["unit_id"],
            duet_id,
        )
        if canonical_json(actual_unit) != canonical_json(recorded):
            raise ValueError("unit boundary differs from its committed unit event")
        if request["scope"]["unit_label"] != recorded["unit_label"]:
            raise ValueError("selected unit label differs from its recorded identity")
        if (
            request["mode"] == "recorded"
            and request["recording_ref"] != recorded["invocation"]["recording_ref"]
        ):
            raise ValueError(
                "unit playback requires the exact recording ending at its selected unit"
            )
        unit_selection = {
            key: recorded[key] for key in ("unit_ref", "unit_label", "unit_event_ref")
        }
        recorded = recorded["invocation"]
    from ..protocol import episode_id_for_path
    from agent.episode_contracts import OpaqueId

    episode_id = episode_id_for_path(
        OpaqueId(recorded["source_run_id"]), recorded["episode_path"]
    ).value
    actual = boundary_record(
        artifacts, runs, recorded["recording_ref"], episode_id, duet_id
    )
    if canonical_json(recorded) != canonical_json(actual):
        raise ValueError("boundary differs from its committed source invocation")
    if request["scope"]["invocation_path"] != actual["episode_path"]:
        raise ValueError("selected scope names a different saved invocation")
    if request["start"]["artifact_ref"] != actual["recording_ref"]:
        raise ValueError(
            "selected execution must use the boundary's exact saved inputs"
        )
    if (
        actual["source_workflow_hash"]
        != inputs.build_request.frozen_workflow.workflow_hash.value
    ):
        raise ValueError("boundary belongs to a different approved workflow")
    source = builds.inspection_inputs_for_receipt(actual["source_build_receipt_id"])
    paths, edges = admitted_call_graph(inputs.plan)
    ancestors = {
        resolve_call_path(
            paths,
            edges,
            tuple(part["grain"] for part in actual["episode_path"][:length]),
        )
        for length in range(1, len(actual["episode_path"]))
    }
    # The shared GoalState initializer is a dependency even when the selected
    # invocation is the workflow root. Changed initializers need a new boundary.
    ancestors.add(inputs.plan.root_local_id)
    for local_id in ancestors:
        if (
            source.manifest.module_hashes_by_local_id[local_id]
            != inputs.manifest.module_hashes_by_local_id[local_id]
        ):
            raise ValueError(
                "saved boundary ancestor or GoalState initializer changed; capture a matching boundary"
            )
    from ..units import UnitScope

    if kind == "unit" and unit_selection["unit_ref"]["unit_index"] > 0:
        if request["mode"] != "live_saved":
            raise ValueError("later-unit state restoration currently requires live_saved; recorded requests are not rewritten for a new identity")
        from .reconstruction_source import admit_reasoning_unit_source
        from ..learning_baseline import baseline_selector
        from ..linker import RuntimeLinkError

        try:
            admission = admit_reasoning_unit_source(
                inputs, source_package_path=builds.verify_source_package(inputs.manifest),
                entry_local_id=request["scope"]["entry_local_id"],
            )
        except (ValueError, RuntimeLinkError) as exc:
            raise ValueError(f"later-unit restoration unavailable: {exc}") from exc
        original = runs.read_registration(OpaqueId(actual["source_run_id"]))
        if original.manifest_id != inputs.manifest.manifest_id:
            raise ValueError("later-unit restoration requires the exact original build; changed code needs an explicit state-transfer contract")
        unit_selection["learning_baseline"] = baseline_selector(
            runs, original, unit_ref=unit_selection["unit_ref"],
            selected_event_ref=unit_selection["unit_event_ref"], source_admission=admission,
        )
    scope_type = UnitScope if kind == "unit" else RunScope
    scope = scope_type(
        kind=request["scope"]["kind"],
        entry_local_id=request["scope"]["entry_local_id"],
        included_local_ids=tuple(request["scope"]["included_local_ids"]),
        included_grains=tuple(
            node.grain_name
            for node in inputs.plan.nodes
            if node.local_id in request["scope"]["included_local_ids"]
        ),
        boundary_ref=reference,
        boundary=actual,
        **unit_selection,
    )
    scope.validate_plan(inputs.plan)
    return scope
