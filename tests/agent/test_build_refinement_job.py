"""One normal build enters the real refiner without another command.

Model decisions are supplied fixtures. The failed-build case uses a native
systemd worker; the already-materialized case executes in-process. The host
entry, Builder, admitted refiner code, nested loop, broker, campaign and shared
records are real. These tests establish handoff/cancellation, not repair quality.
"""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from agent.episode_blueprints import workflow_blueprint_from_spec
from agent.episode_contracts import (
    EpisodeCreationSpec,
    EpisodeDesignSpec,
    EpisodeWorkflowSpec,
    OpaqueId,
)
from agent.openchia_host import OpenChiaHost
from episode_library.reasoning import DESIGN
from function_library.epistemic_contract import inquiry_contract
from episode_library.models import EpisodeReference
from episode_runtime.records.experiments import read_record
from episode_runtime.executor import make_systemd_run_executor_factory
from episode_runtime.executor_lifecycle import verify_stopped_executor
from tests.agent.test_episode_testing_launch import HostExecutor
from tests.episode_runtime.conftest import claim_store, numerical_control
from tests.episode_runtime.test_reasoning_workflow import (
    _module_response,
    _plan_response,
)


@pytest.mark.parametrize(
    "initial_passes",
    [
        pytest.param(
            False,
            marks=pytest.mark.platforms("linux"),
            id="failed-build-native-refiner",
        ),
        pytest.param(True, id="materialized-build-linked-refiner"),
    ],
)
def test_one_build_enters_refinement_and_cancel_stops_same_job(
    tmp_path, monkeypatch, initial_passes
):
    runtime = claim_store(tmp_path / "runtime")[1].runtime_identity
    executor_factory = lambda runs: HostExecutor(runs, runtime)
    if not initial_passes:
        runtime_dir = Path("/run/user") / str(os.getuid())
        if (runtime_dir / "bus").exists():
            monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
            monkeypatch.setenv(
                "DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir / 'bus'}"
            )
        probe = subprocess.run(
            ["systemctl", "--user", "is-system-running"],
            capture_output=True,
            timeout=5,
        )
        if probe.stdout.strip() not in {b"running", b"degraded"}:
            pytest.skip("native build handoff requires a running user systemd manager")
        executor_factory = make_systemd_run_executor_factory(
            repository_root=Path(__file__).resolve().parents[2]
        )
    reached = threading.Event()
    calls = []

    def respond(route, key, request, cancel, progress):
        prompt = json.loads(request.messages[-1]["content"])
        calls.append((route["model"], prompt))
        if route["model"] == "duet-fixture":
            reached.set()
            assert cancel.wait(90), "owning build never cancelled the refiner call"
            return "{}", route["model"]
        if "node" in prompt:
            value = _plan_response(prompt) if initial_passes else {}
        else:
            value = _module_response(prompt)
        return json.dumps(value), route["model"]

    monkeypatch.setattr("agent.episode_launch_transport._invoke", respond)
    host = OpenChiaHost(
        home=tmp_path,
        session_id="build-cycle",
        available_tool_names=(),
        agent_kwargs_factory=lambda *args: {},
        run_executor_factory=executor_factory,
    )
    host._duet_agent = SimpleNamespace(
        _duet_identity=host.identity,
        reasoning_config=None,
        _current_main_runtime=lambda: {
            "model": "duet-fixture",
            "provider": "custom",
            "base_url": "https://example.org/v1",
            "api_mode": "chat_completions",
            "session_id": "build-cycle",
            "api_key": None,
        },
    )
    launch_path = tmp_path / "launch.json"
    launch_path.write_text(
        json.dumps({
            "project": "build-cycle",
            "project_root": str(tmp_path),
            "env_files": [],
            "routes": {
                "target": {
                    "model": "target-fixture",
                    "provider": "custom",
                    "base_url": "https://example.org/v1",
                    "api_mode": "chat_completions",
                    "auth": {"kind": "none"},
                }
            },
            "model_slots": {
                name: "target" for name in ("planner", "writer", "selector", "executor")
            },
            "builder_slots": {"planning": "planner", "emission": "writer"},
        }),
        encoding="utf-8",
    )
    contract = EpisodeCreationSpec(
        goal="Inspect the supplied evidence",
        progress="Admitted knowledge",
        stopping="Host numerical decision",
        numeric_control=numerical_control(0.9),
        epistemic=inquiry_contract(
            goal_class="inquiry",
            domain="build-cycle",
            environment={"dataset": "fixture"},
        ),
    )
    workflow = EpisodeWorkflowSpec((
        EpisodeDesignSpec(
            "inquiry",
            None,
            contract,
            EpisodeReference(DESIGN.episode_id),
        ),
    ))
    try:
        host.configure_launch(str(launch_path))
        host.approve_launch(host.preview_launch()["configuration_hash"])
        draft = host.submit_episode_architecture(
            candidate_workflow_architecture=workflow_blueprint_from_spec(workflow),
            expected_artifact_id=None,
            expected_content_hash=None,
            expected_revision=None,
            human_note_ids=(),
        )
        assert draft["ready"], draft
        host.approve_current()
        approvals = [
            e
            for e in host.store.events(host.identity.duet_id.value)
            if e["provenance"] == "human_approval"
        ]
        host.start_build()
        worker = host._build_thread
        deadline = time.monotonic() + 180
        while (
            not reached.wait(0.1) and worker.is_alive() and time.monotonic() < deadline
        ):
            pass
        assert reached.is_set(), host.build_status()
        active = host.build_status()
        assert active["state"] == "refining", active
        assert host.build_receipt()["status"] == (
            "materialized" if initial_passes else "blocked"
        )
        assert not any(
            e["event_type"] == "build_finished"
            for e in host.store.events(host.identity.duet_id.value)
        )
        assert host.cancel_build()
        worker.join(timeout=60)
        assert not worker.is_alive(), host.build_status()
        status = host.build_status()
        assert status["state"] == "cancelled", status
        result = read_record(
            host.store, "build_job_result", build_receipt_id=status["build_receipt_id"]
        )
        assert result["record"]["state"] == "cancelled"
        job = read_record(
            host.store, "build_job", build_request_id=status["build_request_id"]
        )
        dispatch = read_record(
            host.store, "dispatch", experiment_id=job["record"]["experiment_id"]
        )
        evidence = host.run_store.read_evidence(
            OpaqueId(dispatch["record"]["registration"]["run_id"])
        )
        assert evidence.terminal_status.value == "cancelled"
        if not initial_passes:
            claim = host.run_store.read_claim(evidence.run_id)
            assert asyncio.run(
                verify_stopped_executor(executor_factory(host.run_store), claim)
            )["stopped"]
        assert approvals == [
            e
            for e in host.store.events(host.identity.duet_id.value)
            if e["provenance"] == "human_approval"
        ]
        assert calls[-1][0] == "duet-fixture"
        assert "assignment_context" in calls[-1][1]
    finally:
        host.close()

    reopened = OpenChiaHost(
        home=tmp_path,
        session_id="build-cycle",
        available_tool_names=(),
        agent_kwargs_factory=lambda *args: {},
    )
    try:
        assert reopened.build_status()["state"] == "cancelled"
    finally:
        reopened.close()
