"""Shared numerical mode against actual host learning commits and CLI storage.

The source fixture runs the ledger, not Target Workflow code or confinement. This is
a numerical evidence/reuse invariant, NOT live reasoning acceptance.
"""

from copy import deepcopy
import asyncio
import json

import pytest

from agent.duet_store import DuetStore
from agent.episode_launch import resolve_launch
from tests.episode_runtime.testing.launch_fixture import FixtureLaunchHost
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunTerminalStatus
from episode_runtime.learning import LearningLedger
from episode_runtime.protocol import episode_id_for_path
from episode_runtime.store import RunStore
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.recordings import read_recording, save_recording
from episode_runtime.testing.service import ExperimentService
from episode_runtime.records.experiments import put_data
from openchia_cli.episode_test_command import main
from tests.episode_builder.test_repeatable_call_materialization import build
from tests.episode_runtime.conftest import claim_store, oid
from tests.episode_runtime.testing.test_experiment_planning import experiment


class LedgerOnlyExecutor:
    def __init__(self, root, identity, contract):
        self.root, self.identity, self.contract = root, identity, contract
        self.run_store = RunStore(root / "runs")
        self.path = None
        self.receipts = []

    def inspect_runtime_identity(self, **kwargs):
        return self.identity

    async def execute(self, *, registration, **kwargs):
        claim_store(self.root, registration)
        self.path = [{"grain": "inquiry", "key": registration.run_id.value}]
        episode_id = episode_id_for_path(registration.run_id, self.path)
        self.run_store.append_event(
            run_id=registration.run_id,
            origin=RunEventOrigin.WORKER,
            sender_sequence=0,
            kind=RunEventKind.EPISODE_STARTED,
            episode_id=episode_id,
            payload={
                "grain": "inquiry",
                "key": registration.run_id.value,
                "episode_path": self.path,
                "request": {},
            },
        )
        ledger = LearningLedger(self.run_store, registration.run_id)
        policy = {
            "episode_id": episode_id,
            "contract": self.contract.epistemic,
            "numerical_control": self.contract.numeric_control,
        }
        for ordinal in range(3):
            bundle = ledger.retrieve(**policy)
            ledger.select(
                **policy,
                ordinal=ordinal,
                action_class="discover",
                action_inputs={},
                retry_reason="Fixture deliberately retries to inspect duplicate credit.",
            )
            result = {
                "action_class": "discover",
                "action_inputs": {},
                "status": "failed",
                "expected_observation": "relevant records",
                "observed_outcome": "no records",
                "candidate_lessons": [],
                "entities": [],
                "revisions": [],
            }
            if ordinal:
                result["candidate_lessons"] = [
                    {
                        "claim": "Empty search under the stated conditions.",
                        "scope_tier": "episode",
                        "action_class": "discover",
                        "reopening_conditions": ["dataset changes"],
                        "evidence_refs": [bundle["evidence"][0]["artifact_id"]],
                    }
                ]
            self.receipts.append(
                ledger.commit(
                    **policy,
                    ordinal=ordinal,
                    result=result,
                    producer_call_id=oid("call").value,
                )
            )
        return self.run_store.finalize_run(
            run_id=registration.run_id,
            origin=RunEventOrigin.HOST,
            sender_sequence=0,
            terminal_status=RunTerminalStatus.INTERRUPTED,
            typed_status={
                "outcome": "interrupted",
                "reason": "Ledger-only fixture; no candidate execution.",
            },
        )


@pytest.mark.asyncio
async def test_cli_numerical_reuses_exact_history_without_new_run_or_credit(
    tmp_path, run_store, capsys
):
    request, builds, receipt = await build(tmp_path, ())
    executor = LedgerOnlyExecutor(
        tmp_path / "execution",
        run_store[1].runtime_identity,
        request.frozen_workflow.workflow.episodes[0].contract,
    )
    launch = resolve_launch({
        "project": "numerical-fixture",
        "project_root": str(tmp_path),
        "env_files": [],
        "routes": {
            "local": {
                "provider": "custom",
                "model": "unused",
                "base_url": "http://localhost:9999/v1",
                "api_mode": "chat_completions",
                "auth": {"kind": "none"},
            }
        },
        "model_slots": {"selector": "local", "executor": "local"},
        "builder_slots": {"planning": "selector", "emission": "executor"},
    })
    with DuetStore(tmp_path / "duet.db") as artifacts:
        raw = experiment(artifacts, request, receipt)
        FixtureLaunchHost(artifacts, builds, request.frozen_workflow.duet_id.value).approve_fixture(launch)
        raw["launch_ref"] = put_data(
            artifacts, request.frozen_workflow.duet_id.value, "launch", launch.record
        )
        service = ExperimentService(
            artifacts=artifacts,
            builds=builds,
            runs=executor.run_store,
            executor=executor,
        )
        live = await service.run(ExperimentSpec.from_record(raw))
        assert executor.receipts[0]["measurement"]["realized_yield"] == 0
        assert executor.receipts[1]["measurement"]["realized_yield"] > 0
        assert executor.receipts[2]["measurement"]["realized_yield"] == 0
        source = read_recording(executor.run_store, live["run_id"])
        assert source["source_terminal_status"] == "interrupted"
        saved = save_recording(artifacts, executor.run_store, live["run_id"])
        raw.update(
            mode="numerical",
            recording_ref=saved,
            launch_ref=None,
            start={"kind": "saved_inputs", "artifact_ref": saved, "input_payload": {}},
            boundary={"children": "reuse", "parent_context_ref": None},
        )
        spec = ExperimentSpec.from_record(raw)
        file = tmp_path / "experiment.json"
        file.write_text(spec.canonical_record, encoding="utf-8")
        # No executor is needed: even a nonexistent backend image is irrelevant
        # to numerical-only evaluation, and no model credentials are available.
        argv = [
            "run",
            "--spec",
            str(file),
            "--duet-store",
            str(tmp_path / "duet.db"),
            "--build-store",
            str(tmp_path),
            "--run-store",
            str(executor.root / "runs"),
            "--backend",
            "container",
            "--image",
            "unused",
        ]
        assert await asyncio.to_thread(main, argv) == 0
        replay = json.loads(capsys.readouterr().out)
        assert replay["execution_status"] == "evaluated"
        assert replay["controller_comparison"] == "reproduced"
        assert replay["source_terminal_status"] == "interrupted"
        assert replay["candidate_verdict"] == "unmeasured"
        assert not replay["progress"]["admitted"]
        assert "run_id" not in replay
        assert len(replay["invocations"][0]["units"]) == 3
        assert all(row["matches"] for row in replay["invocations"][0]["units"])
        assert await asyncio.to_thread(main, argv) == 0
        assert json.loads(capsys.readouterr().out) == replay
        assert read_recording(executor.run_store, live["run_id"]) == source

        narrow = deepcopy(raw)
        narrow["scope"].update(kind="episode", invocation_path=executor.path)
        pure = ExperimentService(
            artifacts=artifacts, builds=builds, runs=executor.run_store
        )
        scoped = await pure.run(ExperimentSpec.from_record(narrow))
        assert scoped["controller_comparison"] == "reproduced"
        assert scoped["scope"]["kind"] == "episode"
        assert scoped["invocations"] == replay["invocations"]

        missing = deepcopy(narrow)
        missing["scope"]["invocation_path"][0]["key"] = oid("different").value
        refused = await pure.run(ExperimentSpec.from_record(missing))
        assert refused["execution_status"] == "unavailable"
        assert "no matching invocation" in refused["plan"]["gaps"][0]["detail"]

        # A committed prefix before the first observation is not a green empty
        # replay, even though the complete source Run later acquired evidence.
        empty = save_recording(
            artifacts,
            executor.run_store,
            live["run_id"],
            through_event_ref=source["learning"][0]["event_ref"],
        )
        raw["recording_ref"] = raw["start"]["artifact_ref"] = empty
        refused = await pure.run(ExperimentSpec.from_record(raw))
        assert refused["execution_status"] == "unavailable"
        assert "empty trace is not a pass" in refused["plan"]["gaps"][0]["detail"]
