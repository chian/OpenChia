"""Measured-output plumbing against an independently computed scheduling optimum.

The executor only publishes supplied typed results with inert attestation. It
does not execute a candidate, contact a model, or prove confinement. These are
measurement/comparison checks, not the required live reasoning acceptance run.
"""

from copy import deepcopy
import json

import pytest

from agent.duet_store import DuetStore
from agent.episode_launch import resolve_launch
from tests.episode_runtime.testing_harness.launch_fixture import FixtureLaunchHost
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunTerminalStatus
from agent.episode_contracts import OpaqueId
from episode_runtime.store import RunStore
from episode_runtime.testing_harness.contracts import ExperimentSpec
from episode_runtime.testing_harness.criteria import register_criterion
from episode_runtime.testing_harness.planning import preview_experiment
from episode_runtime.testing_harness.service import ExperimentService
from episode_runtime.records.experiments import put_data, read_record
from function_library.refinement_checks import EXACT_VALUE
from openchia_cli.episode_test_command import main
from tests.episode_builder.test_repeatable_call_materialization import build, selected
from tests.episode_runtime.conftest import claim_store
from function_library.scheduling_benchmark import optimal_schedule, violations
from tests.episode_runtime.testing_harness.test_experiment_planning import experiment


class ResultOnlyExecutor:
    def __init__(self, root, identity):
        self.root = root
        self.run_store = RunStore(root / "runs")
        self.identity = identity
        self.result = {}
        self.terminal = RunTerminalStatus.SUCCEEDED
        self.calls = 0

    def inspect_runtime_identity(self, **kwargs):
        return self.identity

    async def execute(self, *, registration, **kwargs):
        self.calls += 1
        claim_store(self.root, registration)
        self.run_store.append_event(
            run_id=registration.run_id, origin=RunEventOrigin.HOST,
            sender_sequence=0, kind=RunEventKind.RUN_STARTED, episode_id=None,
            payload={"fixture": "supplied result, no candidate execution"},
        )
        return self.run_store.finalize_run(
            run_id=registration.run_id,
            origin=RunEventOrigin.HOST,
            sender_sequence=1,
            terminal_status=self.terminal,
            typed_status=self.result,
        )


@pytest.mark.asyncio
async def test_frozen_measure_distinguishes_values_without_acceptance_or_credit(
    tmp_path, run_store, capsys, monkeypatch
):
    request, builds, receipt = await build(tmp_path, ())
    duet_id = request.frozen_workflow.duet_id.value
    executor = ResultOnlyExecutor(tmp_path / "execution", run_store[1].runtime_identity)
    optimum, witness = optimal_schedule()
    assert not violations(witness)
    launch = resolve_launch({
        "project": "measurement-fixture",
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
        FixtureLaunchHost(artifacts, builds, duet_id).approve_fixture(launch)
        raw["launch_ref"] = put_data(artifacts, duet_id, "launch", launch.record)
        grounding = put_data(
            artifacts, duet_id, "grounding", {"optimum": optimum, "witness": witness}
        )
        criterion = {
            "schema_version": 1,
            "build_receipt_ref": raw["build_receipt_ref"],
            "environment_ref": raw["environment_ref"],
            "requirement_key": "minimum-completion-time",
            "description": "Returned minimum equals the independently enumerated optimum.",
            "scope": raw["scope"],
            "accepted_modes": ["live_fresh"],
            "input_payload": {},
            "predicate": selected(EXACT_VALUE).as_record(),
            "observation_path": "/minimum_completion",
            "expected_value": optimum,
            "positive_controls": [optimum],
            "negative_controls": [optimum - 1, optimum + 1, str(optimum)],
            "grounding_refs": [grounding],
            "limitations": [
                "This scalar criterion does not validate a returned schedule or its optimality argument."
            ],
        }
        invalid = deepcopy(criterion)
        invalid["negative_controls"] = [optimum]
        with pytest.raises(ValueError, match="fails its declared fail control"):
            register_criterion(
                invalid, artifacts=artifacts, builds=builds, duet_id=duet_id
            )

        file = tmp_path / "criterion.json"
        file.write_text(json.dumps(criterion), encoding="utf-8")
        assert (
            main([
                "register-measure",
                "--file",
                str(file),
                "--duet-store",
                str(tmp_path / "duet.db"),
                "--duet-id",
                duet_id,
                "--build-store",
                str(tmp_path),
            ])
            == 0
        )
        registered = json.loads(capsys.readouterr().out)
        assert not registered["acceptance_authority_granted"]
        assert [row["observed_outcome"] for row in registered["control_results"]] == [
            "pass",
            "fail",
            "fail",
            "fail",
        ]
        raw["requirements"] = [
            {
                "requirement_ref": registered["requirement_ref"],
                "measure_ref": registered["measure_ref"],
                "expected": "The reported minimum will equal the independent optimum.",
                "falsifying": "A claimed minimum differs from exhaustive enumeration.",
            }
        ]
        service = ExperimentService(
            artifacts=artifacts,
            builds=builds,
            runs=executor.run_store,
            executor=executor,
        )
        executor.result = {"minimum_completion": optimum}
        spec = ExperimentSpec.from_record(raw)
        good = await service.run(spec)
        assert good["execution_status"] == "succeeded"
        assert good["candidate_verdict"] == "pass"
        measured = good["measurement"]
        assert measured["outcomes"][0]["observed"] == optimum
        assert measured["outcomes"][0]["criterion_expected"] == optimum
        assert not measured["acceptance"]["admitted"]
        assert not measured["progress"]["admitted"]
        assert await service.run(spec) == good
        assert executor.calls == 1

        # A changed prediction creates a new experiment, not new acceptance rules.
        raw["requirements"][0]["expected"] = (
            "Accept the shorter impossible completion time."
        )
        executor.result = {"minimum_completion": optimum - 1}
        bad = await service.run(ExperimentSpec.from_record(raw))
        assert bad["execution_status"] == "succeeded"
        assert bad["candidate_verdict"] == "fail"
        assert bad["measurement"]["outcomes"][0]["criterion_expected"] == optimum
        assert (
            main([
                "results",
                "--duet-store",
                str(tmp_path / "duet.db"),
                "--run-store",
                str(executor.root / "runs"),
                "--experiment-id",
                bad["experiment_id"],
            ])
            == 2
        )
        assert json.loads(capsys.readouterr().out)["measurement"] == bad["measurement"]
        assert (
            main([
                "compare",
                "--duet-store",
                str(tmp_path / "duet.db"),
                "--before",
                good["experiment_id"],
                "--after",
                bad["experiment_id"],
            ])
            == 0
        )
        comparison = json.loads(capsys.readouterr().out)
        assert comparison["outcomes"][0]["regression"]
        assert not comparison["progress"]["admitted"]

        # Good-looking output during an interrupted run is not a behavioral pass.
        raw["question"] = "Was a correct value returned successfully?"
        executor.terminal = RunTerminalStatus.INTERRUPTED
        executor.result = {"minimum_completion": optimum}
        interrupted = await service.run(ExperimentSpec.from_record(raw))
        assert interrupted["candidate_verdict"] == "unmeasured"
        assert interrupted["measurement"]["outcomes"][0]["status"] == "error"

        # Continue the exact experiment through the shared service. This fixture
        # only publishes supplied results; reconstruction is tested separately.
        saved_report = read_record(artifacts, "measurement", experiment_id=interrupted["experiment_id"])
        old_audit = executor.run_store.read_audit_log(OpaqueId(interrupted["run_id"]))
        execute_fixture = executor.execute
        admissions = []

        async def continue_fixture(**kwargs):
            admissions.append(await kwargs.pop("continuation_admission")())
            return await execute_fixture(**kwargs)

        executor.terminal = RunTerminalStatus.SUCCEEDED
        with monkeypatch.context() as patch:
            patch.setattr(executor, "execute", continue_fixture)
            continuation = {
                "experiment_id": interrupted["experiment_id"],
                "resume_from": interrupted["resume_from"],
            }
            repaired = await service.continue_run(**continuation)
            assert await service.continue_run(**continuation) == repaired
        assert len(admissions) == 1
        assert repaired["experiment_id"] == interrupted["experiment_id"]
        assert repaired["run_id"] != interrupted["run_id"]
        assert repaired["logical_run_id"] == interrupted["run_id"]
        assert repaired["candidate_verdict"] == "pass" and repaired["resume_from"] is None
        assert repaired["measurement"]["measurement_ref"] != interrupted["measurement"]["measurement_ref"]
        assert repaired["measurement"]["execution_ref"] == repaired["evidence_ref"]
        assert read_record(artifacts, "measurement", experiment_id=interrupted["experiment_id"]) == saved_report
        assert executor.run_store.read_audit_log(OpaqueId(interrupted["run_id"])) == old_audit

        # A different environment does not silently reuse the original criterion.
        executor.terminal = RunTerminalStatus.SUCCEEDED
        raw["environment_ref"] = put_data(
            artifacts, duet_id, "environment", {"dataset": "other"}
        )
        changed = await service.run(ExperimentSpec.from_record(raw))
        assert changed["candidate_verdict"] == "unmeasured"
        assert changed["measurement"]["outcomes"][0]["status"] == "not_applicable"
        assert (
            main([
                "compare",
                "--duet-store",
                str(tmp_path / "duet.db"),
                "--before",
                good["experiment_id"],
                "--after",
                changed["experiment_id"],
            ])
            == 0
        )
        comparison = json.loads(capsys.readouterr().out)
        assert "environment_ref" in comparison["context_differences"]
        assert not comparison["outcomes"][0]["regression"]
        assert not comparison["outcomes"][0]["comparable"]

        from episode_runtime.testing_harness.recordings import event_reference, save_recording

        recording_ref = save_recording(artifacts, executor.run_store, good["run_id"])
        first = executor.run_store.read_audit_log(OpaqueId(good["run_id"]))[0]
        prefix_ref = save_recording(
            artifacts, executor.run_store, good["run_id"],
            through_event_ref=event_reference(first),
        )

        def no_audit(*args, **kwargs):
            raise AssertionError("history must read maintained records, not reconstruct Run logs")

        with monkeypatch.context() as patch:
            patch.setattr(RunStore, "_load_event_chain_locked", no_audit)
            patch.setattr(RunStore, "read_evidence", no_audit)
            rows, cursor = [], None
            while True:
                page = service.history(
                    artifacts, executor.run_store, duet_id=duet_id,
                    query={"limit": 1, "after": cursor},
                )
                rows.extend(page["items"])
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            indexed = {row["experiment_id"]: row for row in rows}
            assert len(indexed) == len(rows)
            assert set(indexed) == {
                value["experiment_id"] for value in (good, bad, interrupted, changed)
            }
            assert indexed[bad["experiment_id"]]["measurement"]["candidate_verdict"] == "fail"
            assert indexed[interrupted["experiment_id"]]["execution"]["run_record"]["record"]["terminal_status"] == "succeeded"
            assert indexed[interrupted["experiment_id"]]["measurement"]["measurement_ref"] == repaired["measurement"]["measurement_ref"]
            replay = indexed[good["experiment_id"]]["execution"]
            assert {
                row["recording_ref"]["artifact_id"] for row in replay["recordings"]["items"]
            } == {recording_ref["artifact_id"], prefix_ref["artifact_id"]}
            query = {**replay["recordings"]["query"], "limit": 1}
            first_page = service.history(
                artifacts, executor.run_store, duet_id=duet_id, query=query,
            )
            second_page = service.history(
                artifacts, executor.run_store, duet_id=duet_id, query=first_page["next_query"],
            )
            assert first_page["record_type"] == second_page["record_type"] == "recordings"
            assert second_page["next_query"] is None
            assert {
                row["recording_ref"]["artifact_id"]
                for page in (first_page, second_page) for row in page["items"]
            } == {recording_ref["artifact_id"], prefix_ref["artifact_id"]}
            with pytest.raises(ValueError, match="outside the owned experiment lineage"):
                service.history(
                    artifacts, executor.run_store, duet_id=duet_id,
                    query={**first_page["next_query"], "experiment_id": bad["experiment_id"]},
                )
            with pytest.raises(ValueError, match="not available to this history owner"):
                service.history(
                    artifacts, executor.run_store, duet_id="unrelated-owner", query=query,
                )
            assert replay["reuse"]["recorded_responses"] == "requires_preview"
            assert replay["reuse"]["continue_interrupted"] == "not_interrupted"
            assert service.history(
                artifacts, executor.run_store, duet_id="unrelated-owner", query={}
            )["items"] == []
            assert main([
                "history", "--duet-store", str(tmp_path / "duet.db"),
                "--duet-id", duet_id, "--run-store", str(executor.root / "runs"),
            ]) == 0
            assert {
                row["experiment_id"] for row in json.loads(capsys.readouterr().out)["items"]
            } == set(indexed)
            assert main([
                "history", "--duet-store", str(tmp_path / "duet.db"),
                "--duet-id", duet_id, "--run-store", str(executor.root / "runs"),
                "--experiment-id", good["experiment_id"], "--limit", "1",
            ]) == 0
            assert json.loads(capsys.readouterr().out)["next_query"] == first_page["next_query"]
            assert main([
                "run-record", "--run-store", str(executor.root / "runs"),
                "--run-id", interrupted["run_id"],
            ]) == 0
            assert json.loads(capsys.readouterr().out)["record"]["terminal_status"] == "interrupted"

        # An honestly content-addressed artifact with a stale implementation is
        # still unusable. Rehashing a record is not source compatibility.
        record = artifacts.get_artifact(registered["measure_ref"]["artifact_id"])[
            "record"
        ]
        runtime = artifacts.get_artifact(record["implementation_ref"]["artifact_id"])[
            "record"
        ]
        runtime["host_adapter_hashes"]["episode_runtime/testing_harness/judgments.py"] = (
            "sha256:" + "0" * 64
        )
        record["implementation_ref"] = put_data(
            artifacts, duet_id, "measurement_runtime", runtime
        )
        replacement = put_data(artifacts, duet_id, "criterion", record)
        requirement = artifacts.get_artifact(
            registered["requirement_ref"]["artifact_id"]
        )["record"]
        requirement["measure_ref"] = replacement
        raw["requirements"][0].update(
            measure_ref=replacement,
            requirement_ref=put_data(artifacts, duet_id, "requirement", requirement),
        )
        refused = preview_experiment(
            ExperimentSpec.from_record(raw), builds=builds, artifacts=artifacts
        )
        assert not refused["resolved"]
        assert any("implementation differs" in gap["detail"] for gap in refused["gaps"])
        assert (
            service.status(artifacts, executor.run_store, good["experiment_id"])[
                "measurement"
            ]
            == measured
        )
