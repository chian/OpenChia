"""Unit boundaries are selectors into the common journal, not another replay log."""

from agent.episode_contracts import OpaqueId
from method_loop.identities import UnitRef

from ..contracts import RunEventKind
from ..records.facts import event_fact, unit_prefix
from .boundaries import boundary_record
from .recordings import event_reference, load_recording, read_recording, save_recording


def unit_boundary_record(artifacts, runs, recording_ref, unit_id, duet_id):
    _, recording = load_recording(artifacts, runs, recording_ref, duet_id)
    selected = [row for row in recording["units"] if row["unit_ref"]["unit_id"] == unit_id]
    if len(selected) != 1:
        raise ValueError("unit boundary requires one exact recorded UnitRef, not a label")
    row = selected[0]
    unit = UnitRef.from_record(row["unit_ref"])
    if row["event_ref"] != recording["through_event_ref"]:
        raise ValueError("unit recording must end at its exact committed unit event")
    return {
        "invocation": boundary_record(artifacts, runs, recording_ref, unit.episode_id, duet_id),
        "unit_ref": unit.as_record(), "unit_label": row["unit_label"],
        "unit_event_ref": row["event_ref"],
    }


def capture_unit_boundary(artifacts, runs, run_id, unit_id):
    from ..records.experiments import put_data

    source = runs.read_registration(OpaqueId(run_id))
    recording = read_recording(runs, run_id)
    selected = [row for row in recording["units"] if row["unit_ref"]["unit_id"] == unit_id]
    if len(selected) != 1:
        raise ValueError("select an existing unit_id from this Run's recording")
    reference = save_recording(artifacts, runs, run_id, through_event_ref=selected[0]["event_ref"])
    body = unit_boundary_record(artifacts, runs, reference, unit_id, source.duet_id.value)
    boundary_ref = put_data(artifacts, source.duet_id.value, "unit_boundary", body)
    invocation = body["invocation"]
    return {
        "parent_context_ref": boundary_ref, "recording_ref": reference,
        "invocation_path": invocation["episode_path"],
        "unit_ref": body["unit_ref"], "unit_label": body["unit_label"],
        "reconstruction_prefix": verified_unit_prefix(runs, source, body["unit_event_ref"]),
        "initial_state_reproducible": body["unit_ref"]["unit_index"] == 0 and invocation["goal_state_id"] == invocation["initial_goal_state_id"],
        "limitations": [
            "The source recording is cut at this exact unit; no later exchanges are reused.",
            "reconstruction_prefix identifies history before this unit was selected, not a source/controller/host-state snapshot or permission to execute it.",
            "Later-unit execution needs coherent source/controller/shared-state restoration; preceding units are never silently rerun.",
        ],
    }


def verified_unit_prefix(runs, registration, selected_event_ref):
    """Verify the same selector shown by the inexpensive record inventory."""
    start, previous, starts, units = None, None, 0, 0
    events = runs.read_committed_prefix(registration.run_id)
    selected = next((
        event for event in events
        if event_reference(event) == selected_event_ref
    ), None)
    if selected is None or selected.kind is not RunEventKind.UNIT_COMPLETED:
        raise ValueError("unit prefix requires its exact committed unit observation")
    for event in events:
        if event.sequence >= selected.sequence:
            break
        if event.episode_id != selected.episode_id:
            continue
        if event.kind is RunEventKind.EPISODE_STARTED:
            start = event_fact(event, starts, logical_run_id=registration.logical_run_id)
            starts += 1
        elif event.kind is RunEventKind.UNIT_COMPLETED:
            previous = event_fact(event, units)
            units += 1
    return unit_prefix(event_fact(selected, units), invocation_start=start, previous_unit=previous)
