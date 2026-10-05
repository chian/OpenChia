"""Real file capture and scope checks; not a live reasoning benchmark."""

import json

import pytest

from iterative_episode_refiner.coding_workspace import CodingWorkspace, PLAN_EDITS


def test_first_implementation_and_revision_capture_disk_not_claims(tmp_path):
    workspace = CodingWorkspace(tmp_path / "candidate", source_files={},
                                writable_paths=["src/main.py"], protected_paths=[])
    workspace.stage({"goal": "Implement the assigned function"})
    path = workspace.root / "src/main.py"
    path.parent.mkdir()
    path.write_text("def answer():\n    return 42\n", encoding="utf-8")
    first = workspace.capture()
    assert first == {"files": [{"logical_path": "src/main.py", "content": path.read_text(encoding="utf-8")}],
                     "implementation_detail_operations": []}
    # Scratch/claimed success cannot masquerade as a source edit or credit.
    (workspace.root / "claim.txt").write_text("All acceptance checks passed", encoding="utf-8")
    revised = CodingWorkspace(workspace.root, source_files={"src/main.py": first["files"][0]["content"]},
                              writable_paths=["src/main.py"], protected_paths=[])
    assert revised.capture()["files"] == []
    path.write_text("def answer():\n    return 43\n", encoding="utf-8")
    assert revised.capture()["files"][0]["content"] != first["files"][0]["content"]
    path.unlink()
    assert revised.capture()["files"] == [{"logical_path": "src/main.py", "content": None}]


@pytest.mark.platforms("posix")
@pytest.mark.parametrize("violation", ["protected", "symlink", "parent_symlink", "hardlink", "plan_credit"])
def test_capture_rejects_scope_and_link_escape(tmp_path, violation):
    workspace = CodingWorkspace(tmp_path / "candidate", source_files={"src/code.py": "original"},
                                writable_paths=["src/code.py"],
                                protected_paths=["src/code.py"] if violation == "protected" else [])
    workspace.stage({})
    path = workspace.root / "src/code.py"
    outside = tmp_path / "outside.py"
    outside.write_text("outside", encoding="utf-8")
    if violation == "protected":
        path.write_text("changed", encoding="utf-8")
    elif violation == "symlink":
        path.unlink()
        path.symlink_to(outside)
    elif violation == "parent_symlink":
        path.unlink()
        path.parent.rmdir()
        path.parent.symlink_to(tmp_path, target_is_directory=True)
    elif violation == "hardlink":
        path.unlink()
        path.hardlink_to(outside)
    else:
        (workspace.root / PLAN_EDITS).write_text(json.dumps({"credit": 10}), encoding="utf-8")
    with pytest.raises(ValueError):
        workspace.capture()
    assert outside.read_text(encoding="utf-8") == "outside"
