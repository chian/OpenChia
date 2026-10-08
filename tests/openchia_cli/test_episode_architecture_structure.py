"""Navigate the persisted architecture without changing its contracts or targets."""

import asyncio
from copy import deepcopy
import json

import pytest
from prompt_toolkit.application.current import create_app_session, set_app
from prompt_toolkit.data_structures import Point
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType
from prompt_toolkit.output import DummyOutput

from agent.episode_blueprints import workflow_blueprint_from_spec
from agent.openchia_host import OpenChiaHost
from iterative_episode_refiner.design import refinement_workflow_spec
from openchia_cli.openchia_episode_editor import _EpisodeWorkspace
from openchia_cli.openchia_episode_views import DEFAULT_MISSING_VALUE, WorkflowArchitectureViewModel


def saved_snapshot(tmp_path, blueprint):
    host = OpenChiaHost(
        home=tmp_path,
        session_id="architecture-structure",
        available_tool_names=(),
        agent_kwargs_factory=lambda *args: {},
    )
    try:
        host.submit_episode_architecture(
            candidate_workflow_architecture=blueprint,
            expected_artifact_id=None,
            expected_content_hash=None,
            expected_revision=None,
            human_note_ids=(),
        )
        return host.architecture_snapshot()
    finally:
        host.store.close()


def click_row(viewer, key, *, marker=False):
    row = 0
    target = next(i for i, entry in enumerate(viewer._entries()) if entry.selection_key == key)
    handlers = []
    for fragment in viewer._tree_fragments():
        if row == target and len(fragment) == 3:
            handlers.append(fragment[2])
        row += fragment[1].count("\n")
    handlers[0 if marker else -1](MouseEvent(
        Point(0, 0), MouseEventType.MOUSE_UP, MouseButton.LEFT, frozenset(),
    ))


async def rendered(viewer, predicate):
    ready = asyncio.Event()

    def after_render(app):
        if predicate():
            ready.set()

    viewer.application.after_render += after_render
    viewer.application.invalidate()
    try:
        await asyncio.wait_for(ready.wait(), timeout=10)
    finally:
        viewer.application.after_render -= after_render


def test_structure_is_navigation_and_call_return_preserves_the_selected_contract(tmp_path):
    blueprint = workflow_blueprint_from_spec(refinement_workflow_spec())
    snapshot = saved_snapshot(tmp_path, blueprint)
    recursive = next(binding for binding in blueprint["repeatable_calls"]["bindings"]
                     if binding["caller_local_id"] == binding["callee_template_local_id"])

    async def exercise():
        with create_pipe_input() as keyboard, create_app_session(input=keyboard, output=DummyOutput()):
            viewer = _EpisodeWorkspace(
                architecture_snapshot=snapshot, materialized_snapshot=None,
                notes=(), architecture_changed_paths=(), materialized_changed_paths=(),
                edit_architecture=True, architecture_edit_notice=None, notes_enabled=False,
                save_note=lambda **kwargs: pytest.fail("browsing must not save a note"),
                missing_value=DEFAULT_MISSING_VALUE,
            )
            view = viewer.architecture
            # Contract fields no longer separate a parent from its child nodes.
            assert all(entry.kind != "part" for entry in view.visible_entries())
            view.expanded_episode_ids = set(view._episodes)
            all_entries = view.visible_entries()
            assert sorted(entry.episode.local_id for entry in all_entries if entry.kind == "episode") == sorted(
                episode["local_id"] for episode in blueprint["episodes"]
            )
            calls = [entry.part.declaration for entry in all_entries if entry.kind == "call"]
            assert sorted(json.dumps(call, sort_keys=True) for call in calls) == sorted(
                json.dumps(binding, sort_keys=True)
                for binding in blueprint["repeatable_calls"]["bindings"]
            )
            view.expanded_episode_ids = {root.local_id for root in view.roots}
            with set_app(viewer.application):
                running = asyncio.create_task(viewer.application.run_async())
                try:
                    await rendered(viewer, lambda: viewer.application.is_running)
                    path = []
                    current = view._episodes[recursive["caller_local_id"]]
                    while current is not None:
                        path.append(current.local_id)
                        current = view._episodes.get(current.parent_local_id)
                    for local_id in reversed(path):
                        index = view.index_for_episode(local_id)
                        delta = index - viewer.selected_index
                        keyboard.send_text(("\x1b[B" if delta >= 0 else "\x1b[A") * abs(delta))
                        await rendered(viewer, lambda: viewer._entry().selection_key == ("episode", local_id, ""))
                        keyboard.send_text("\x1b[C")
                        await rendered(viewer, lambda: local_id in view.expanded_episode_ids)
                    call = next(entry for entry in viewer._entries()
                                if entry.kind == "call" and entry.part.declaration == recursive)
                    click_row(viewer, call.selection_key)
                    assert json.loads(viewer._detail().declaration) == recursive
                    viewer._activate_detail_page(1)
                    before_expansion = set(view.expanded_episode_ids)
                    keyboard.send_text("\r")
                    await rendered(viewer, lambda: viewer._entry().selection_key == ("episode", call.part.callee_local_id, ""))
                    assert viewer._detail().target == view._episodes[call.part.callee_local_id].target
                    assert len(view.visible_entries()) <= len(all_entries)
                    keyboard.send_text("\x7f")
                    await rendered(viewer, lambda: viewer._entry().selection_key == call.selection_key)
                    assert viewer.active_detail_page_index == 1
                    assert view.expanded_episode_ids == before_expansion
                    assert json.loads(viewer.detail_area.text) == recursive
                    # A mouse-opened shared call follows the same path and returns.
                    shared = next(entry for entry in viewer._entries()
                                  if entry.kind == "call" and entry.episode == call.episode
                                  and entry.part.callee_local_id != entry.episode.local_id)
                    click_row(viewer, shared.selection_key, marker=True)
                    assert viewer._entry().selection_key == ("episode", shared.part.callee_local_id, "")
                    keyboard.send_text("\x7f")
                    await rendered(viewer, lambda: viewer._entry().selection_key == shared.selection_key)
                    # The collapsed Details group retains the exact editing target.
                    details_key = ("details", call.episode.local_id, "")
                    click_row(viewer, details_key, marker=True)
                    goal = next(entry for entry in viewer._entries()
                                if entry.kind == "part" and entry.episode.local_id == call.episode.local_id
                                and entry.part.key == "goal")
                    click_row(viewer, goal.selection_key)
                    assert viewer._detail().target == goal.part.target
                    assert viewer._detail_editable
                    original = viewer.detail_area.text
                    viewer.detail_area.buffer.text = "{"
                    click_row(viewer, details_key)
                    assert viewer._entry().selection_key == goal.selection_key
                    viewer.detail_area.buffer.text = original
                    click_row(viewer, details_key)
                    assert viewer._entry().selection_key == details_key
                    assert view.result() == blueprint
                    click_row(viewer, goal.selection_key)
                    edited_goal = json.loads(original)["goal"] + " Preserve the supplied evidence."
                    viewer.detail_area.buffer.text = json.dumps({"goal": edited_goal})
                    click_row(viewer, details_key)
                    expected = deepcopy(blueprint)
                    next(item for item in expected["episodes"]
                         if item["local_id"] == call.episode.local_id)["contract"]["goal"] = edited_goal
                    assert view.result() == expected
                    assert call.episode.local_id in view.expanded_details_ids
                    assert viewer._entry().selection_key == details_key
                finally:
                    viewer.application.exit()
                    await asyncio.wait_for(running, timeout=10)

    asyncio.run(exercise())


@pytest.mark.parametrize("extension", [None, {"version": 1, "bindings": [
    {"caller_local_id": "launch", "slot_name": "pending"},
    {"caller_local_id": "missing", "slot_name": "pending", "callee_template_local_id": "launch"},
]}])
def test_incomplete_calls_remain_visible_without_creating_targets_or_changing_the_draft(tmp_path, extension):
    blueprint = deepcopy(workflow_blueprint_from_spec(refinement_workflow_spec()))
    blueprint["repeatable_calls"] = extension
    snapshot = saved_snapshot(tmp_path, blueprint)
    view = WorkflowArchitectureViewModel(snapshot)
    unresolved = [entry.part for entry in view.visible_entries()
                  if entry.part is not None and entry.part.key.startswith("repeatable_call_")]
    assert snapshot["validation_deficits"]
    assert unresolved
    for part in unresolved:
        assert part.incomplete and part.callee_local_id is None
        assert part.target is None and not part.editable
        assert "Incomplete repeatable call" in part.summary
    assert view.result() == blueprint
