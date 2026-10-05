"""Opt-in real coding tools + known-answer check, using the existing test runner.

This checks the new coding capability and native thread resumption. It is NOT a
complete build/refine/Target Workflow acceptance run. No model answers or tool
actions are supplied. The independent scheduling oracle is not given to Codex.
"""

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.refinement_coding import CODING_INSTRUCTIONS, coding_backend
from function_library.scheduling_benchmark import BENCHMARK_ID, PROBLEM, check_optimal_schedule
from iterative_episode_refiner.coding_workspace import CodingWorkspace


def live_binding(request):
    profile = request.config.getoption("--live-coding-profile")
    reference = request.config.getoption("--live-coding-binding")
    if not profile or not reference:
        pytest.skip("requires explicit --live-coding-profile and --live-coding-binding")
    database = Path(profile).resolve() / "openchia" / "authority.sqlite3"
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT record_json FROM artifacts WHERE artifact_id = ? AND kind = ?",
            (reference, "experiment.duet_model_binding.v1"),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None, "No such Duet model binding"
    record = json.loads(row[0])
    # The explicit opt-in path is read only. Do not run profile credential
    # discovery/refresh or rebind HERMES_HOME inside the hermetic test process.
    auth = json.loads((Path(profile) / "auth.json").read_text(encoding="utf-8"))
    credential = auth["providers"]["openai-codex"]["tokens"]["access_token"]
    return SimpleNamespace(record=record, api_key=credential)


@pytest.mark.platforms("linux")
@pytest.mark.allow_real_home_io  # Explicit profile/binding flags; reads only, all outputs stay in tmp_path.
def test_live_coder_creates_runs_and_revises_a_known_answer_program(tmp_path, request):
    binding = live_binding(request)
    sources, thread_id, turns = {}, None, []
    for revision in range(2):
        workspace = CodingWorkspace(tmp_path / "candidate", source_files=sources,
                                    writable_paths=["solve.py", "answer.json"], protected_paths=[])
        workspace.stage({
            "problem": PROBLEM,
            "assignment": {
                "goal": (
                    "Create solve.py that computes an optimal schedule from the job data. "
                    "Run it using your command tool to write answer.json containing {fields: "
                    "{schedule: JSON-string, makespan: string, optimality_argument: string}}. "
                    "Do not import OpenChia or look up its verifier. Use the standard library."
                    if revision == 0 else
                    "Revise solve.py to independently validate precedence, worker capacity and "
                    "laser capacity of its computed answer, and raise on a violation. Run the "
                    "revised program to regenerate answer.json, adding a top-level verified=true "
                    "only after its checks pass. Preserve the original fields and optimality."
                ),
                "writable_paths": ["solve.py", "answer.json"],
                "preservation_requirements": ["All original scheduling constraints still hold"],
            },
            "independent_previous_check": None if not sources else "Prior answer passed the independent host oracle",
        })
        events = []
        coder = coding_backend(binding)(binding=binding, workspace=workspace.root, state_dir=tmp_path / "native",
                                        instructions=CODING_INSTRUCTIONS, resume_thread_id=thread_id, on_event=events.append)
        try:
            assert thread_id is None or coder.ensure_started() == thread_id
            result = coder.run_turn("Read .openchia-assignment.json and carry out this coding unit.", turn_timeout=None)
        finally:
            coder.close()
        turns.append({"thread_id": result.thread_id, "turn_id": result.turn_id,
                      "tool_iterations": result.tool_iterations, "error": result.error,
                      "interrupted": result.interrupted, "final_text": result.final_text})
        commands = [event["native"]["params"]["item"] for event in events
                    if event["kind"] == "item_completed"
                    and event["native"].get("params", {}).get("item", {}).get("type") == "commandExecution"]
        print(json.dumps({"revision": revision, "coding": turns[-1], "commands": commands}, ensure_ascii=False))
        assert not result.error and not result.interrupted, turns[-1]
        assert result.thread_id and result.turn_id and result.tool_iterations > 0, turns[-1]
        assert any("solve.py" in item.get("command", "") and item.get("exitCode") == 0
                   for item in commands), "A successful command must actually run the solver"
        thread_id = result.thread_id
        proposal = workspace.capture()
        changed = {item["logical_path"]: item["content"] for item in proposal["files"]}
        assert "solve.py" in changed, "The coding agent must actually create/revise code"
        sources.update(changed)
        answer = json.loads((workspace.root / "answer.json").read_text(encoding="utf-8"))
        assert check_optimal_schedule(observed=answer["fields"], expected={"benchmark_id": BENCHMARK_ID}) == "pass"
        if revision:
            assert answer["verified"] is True
        print(json.dumps({"revision": revision, "route": binding.record["route"],
                          "answer": answer, "coding": turns[-1],
                          "commands": [{key: item.get(key) for key in ("command", "exitCode", "aggregatedOutput")}
                                       for item in commands]}, ensure_ascii=False))
