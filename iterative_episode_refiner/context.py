"""Focused typed context and policy-relevant lesson retrieval before selection."""

from agent.duet_contracts import canonical_json
from function_library.epistemic_contract import exact

from .records import Ref, RefinementRecord
from .state_machine import actor, derived, index


def applicable_lessons(view, assignment, candidate=None):
    candidate = candidate or view.candidate
    result = []
    for entry in view.entries("lesson"):
        if entry.status != "active":
            continue
        body = entry.record.body
        conditions = body["action_inputs"]
        if (
            set(body["requirement_keys"]).intersection(
                assignment.body["scope_requirement_keys"]
            )
            and body["environment_ref"] == view.contract.body["environment_ref"]
            and conditions["files"] == candidate.body["files"]
            and conditions["materialization_ref"]
            == candidate.body["materialization_ref"]
        ):
            result.append(entry.record)
    return tuple(result)


def local_context(view, invocation_id):
    from .coordination import pending_decisions, relevant_conflicts

    invocation = view.entry("invocation", invocation_id.value)
    assignment = invocation.record
    scope = set(assignment.body["scope_requirement_keys"])
    conflicts = relevant_conflicts(view, assignment)
    pending = pending_decisions(view, invocation_id.value)
    active_lessons = applicable_lessons(view, assignment)
    actions = []
    if invocation.status == "active":
        for action in assignment.body["allowed_action_classes"]:
            if pending and action not in {
                "observe",
                "observe_measure_control",
                "close_unit",
                "return_child",
            }:
                continue
            actions.append({
                "action_class": action,
                "retry_justification_required": any(
                    item.body["action_class"] == action for item in active_lessons
                ),
            })
    elif invocation.status in {
        "attained",
        "yield_exhausted_unresolved",
        "needs_parent_decision",
    }:
        actions = [
            {"action_class": "return_child", "retry_justification_required": False}
        ]
    check_keys = {
        entry.key
        for entry in view.entries("check")
        if entry.record.body["requirement_key"] in scope
    }
    check_states = [
        {
            "check_key": entry.key,
            "status": entry.status,
            "observation_ref": entry.record.ref.as_record(),
        }
        for entry in view.entries("check_state")
        if entry.key in check_keys
    ]
    lessons = [
        entry.record
        for entry in view.entries("lesson")
        if entry.status == "active"
        and set(entry.record.body["requirement_keys"]).intersection(scope)
    ]
    units = [
        entry.record
        for entry in view.entries("unit")
        if entry.record.invocation_id == invocation_id
    ]
    cursor = (
        view.read(view.head["latest_commit_id"]).ref
        if view.head["latest_commit_id"]
        else view.contract.ref
    )
    return RefinementRecord(
        "local_context",
        view.campaign_id,
        {
            "assignment_ref": assignment.ref.as_record(),
            "invocation_id": invocation_id.value,
            "current_candidate_ref": view.candidate.ref.as_record(),
            "local_measure_ref": assignment.body["local_measure_ref"],
            "check_states": check_states,
            "assessment_refs": [
                reference
                for unit in units[-8:]
                for reference in unit.body.get("assessment_refs", ())
            ],
            "prerequisite_assessment_refs": [
                reference
                for unit in units[-8:]
                for reference in unit.body.get("prerequisite_assessment_refs", ())
            ],
            "eligible_actions": actions,
            "applicable_lesson_refs": [item.ref.as_record() for item in active_lessons],
            "reopened_lesson_refs": [
                item.ref.as_record() for item in lessons if item not in active_lessons
            ],
            "conflict_refs": [item.ref.as_record() for item in conflicts],
            "recent_unit_refs": [item.ref.as_record() for item in units[-8:]],
            "history_cursor": view.head["sequence"],
            "complete_index_ref": cursor.as_record(),
        },
        view.contract.producer_ref,
        predecessor_refs=(cursor,),
        invocation_id=invocation_id,
    )


def select_action(view, attempt, resolved):
    assignment = actor(view, attempt)
    payload = exact(
        attempt.body["payload"],
        {"action_class", "action_inputs", "candidate_ref", "retry_justification_ref"},
        "action selection",
    )
    if Ref.from_record(payload["candidate_ref"]) != view.candidate.ref:
        raise ValueError("selection must consider the current candidate")
    options = local_context(view, attempt.invocation_id).body["eligible_actions"]
    eligible = next(
        (
            option
            for option in options
            if option["action_class"] == payload["action_class"]
        ),
        None,
    )
    if eligible is None:
        raise ValueError("selected action is not currently eligible")
    lessons = [
        item
        for item in applicable_lessons(view, assignment)
        if item.body["action_class"] == payload["action_class"]
    ]
    if (
        eligible["retry_justification_required"]
        and payload["retry_justification_ref"] is None
    ):
        raise ValueError(
            "an advisory lesson requires a deliberate, recorded retry justification"
        )
    selection = derived(
        view,
        attempt,
        "selection",
        {
            **payload,
            "considered_lesson_refs": [item.ref.as_record() for item in lessons],
        },
    )
    return [selection], [index("selection", attempt.invocation_id.value, selection)]


def require_deliberate_retry(view, attempt, assignment, action):
    lessons = [
        item
        for item in applicable_lessons(view, assignment)
        if item.body["action_class"] == action
    ]
    if not lessons:
        return
    selection = view.entry("selection", attempt.invocation_id.value).record
    if (
        selection.logical_unit_id != attempt.logical_unit_id
        or selection.body["candidate_ref"] != view.candidate.ref.as_record()
        or selection.body["action_class"] != action
        or selection.body["retry_justification_ref"] is None
        or canonical_json(selection.body["considered_lesson_refs"])
        != canonical_json([item.ref.as_record() for item in lessons])
    ):
        raise ValueError(
            "applicable failure knowledge has not been considered before repeating the action"
        )
