from copy import deepcopy

import pytest

from hermes_cli.openchia_episode_editor import EpisodeEditorModel, EpisodeTreeEditor


MISSING = "<OPENCHIA: value required>"


def _contract(goal: str, *, creator: bool = False) -> dict:
    return {
        "goal": goal,
        "unit": "one attempt",
        "result": "one accepted result",
        "progress": {
            "description": "accepted results",
            "unit": "results",
            "direction": "increase",
            "baseline": 0,
            "adapter_id": "evidence_gate_score_v1",
        },
        "stopping": {
            "target": 1,
            "minimum_delta": 0.1,
            "stagnation_observations": 3,
        },
        "execution_capability_names": [],
        "creator_contract": (
            {
                "design_context": {"schema_version": 1},
                "design_scope": "bounded design",
                "assignable_capability_names": [],
                "may_assign_creator_capability": False,
                "evidence_requirements": [],
                "required_existing_evidence_ids": [],
                "credit_assignment": {
                    "aggregation": "normalized_weighted_sum_v1",
                    "components": [],
                },
                "return_contract": {
                    "measurement_ids": [],
                    "credit_component_ids": [],
                    "status_fields": [],
                },
            }
            if creator
            else None
        ),
        "deliverable": {
            "kind": "typed_status",
            "description": "status",
            "tool_names": [],
        },
        "safety_bounds": None,
    }


def test_editor_projects_nested_episode_hierarchy_and_scoped_sections():
    root_contract = _contract("Coordinate the workflow", creator=True)
    child_contract = _contract("Build one item")
    sibling_contract = _contract("Qualify the result")
    document = {
        "episodes": [
            {
                "local_id": "orchestrator",
                "workflow_parent_local_id": None,
                "contract": root_contract,
            },
            {
                "local_id": "builder",
                "workflow_parent_local_id": "orchestrator",
                "contract": child_contract,
            },
            {
                "local_id": "qualification",
                "workflow_parent_local_id": "orchestrator",
                "contract": sibling_contract,
            },
        ]
    }
    original = deepcopy(document)
    model = EpisodeEditorModel(document, missing_value=MISSING)

    episode_entries = [
        entry for entry in model.visible_entries() if entry.kind == "episode"
    ]
    assert [(entry.episode.name, entry.depth) for entry in episode_entries] == [
        ("orchestrator", 0),
        ("builder", 1),
        ("qualification", 1),
    ]
    root_sections = [item.label for item in model.sections_for(model.roots[0])]
    assert root_sections[:5] == [
        "Goal",
        "Planning",
        "Task",
        "Credit assignment",
        "Rarefaction",
    ]
    assert "Creator authority" in root_sections

    child = model.roots[0].children[0]
    goal_section = model.sections_for(child)[0]
    model.apply_section(
        child,
        goal_section,
        {"goal": "Build and test one item", "result": "one accepted item"},
    )
    edited = model.result()

    assert document == original
    assert edited["episodes"][0]["contract"]["goal"] == "Coordinate the workflow"
    assert edited["episodes"][1]["contract"]["goal"] == "Build and test one item"
    assert edited["episodes"][1]["contract"]["result"] == "one accepted item"
    assert edited["episodes"][2]["contract"] == sibling_contract


def test_editor_rejects_partial_section_replacement_and_marks_missing_values():
    contract = _contract("Design a workflow", creator=True)
    contract["progress"] = MISSING
    model = EpisodeEditorModel(contract, missing_value=MISSING)
    episode = model.roots[0]
    sections = {section.key: section for section in model.sections_for(episode)}

    assert model.section_complete(episode, sections["goal"]) is True
    assert model.section_complete(episode, sections["planning"]) is False
    with pytest.raises(ValueError, match="fields must be exactly"):
        model.apply_section(episode, sections["goal"], {"goal": "changed"})
    assert model.result()["goal"] == "Design a workflow"

    editor = EpisodeTreeEditor(contract, missing_value=MISSING)
    assert editor.application.mouse_support() is True
    assert all(callable(fragment[2]) for fragment in editor._tree_fragments())
