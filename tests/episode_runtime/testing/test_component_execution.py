"""Execute real bound functions through the common service and worker linker.

The executor/confinement attestation is the existing in-process fixture. These
tests prove component selection, numerical behavior and common evidence/replay,
not native confinement or live model-directed reasoning.
"""

from copy import deepcopy
import json

import pytest

from agent.duet_store import DuetStore
from agent.episode_contracts import OpaqueId
from agent.episode_launch import resolve_launch
from tests.episode_runtime.testing.launch_fixture import FixtureLaunchHost
from episode_runtime.components import validate_component_event
from episode_runtime.contracts import RunEventKind, RunRegistration
from episode_runtime.learning_broker import LearningBroker
from episode_runtime.scoped import validate_execution_path
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.criteria import register_criterion
from episode_runtime.testing.planning import preview_experiment
from episode_runtime.testing.playback import ReplayDivergence
from episode_runtime.testing.recordings import read_recording, save_recording
from episode_runtime.testing.service import ExperimentService
from episode_runtime.records.experiments import put_data
from function_library.epistemic import RESULT_SCHEMA
from function_library.refinement_checks import EXACT_VALUE
from numeric_control_library import PREDICTED_CREDIT_UPPER_BOUND
from openchia_cli.episode_test_command import main
from tests.episode_builder.test_repeatable_call_materialization import selected
from tests.episode_runtime.testing.test_experiment_planning import experiment
from tests.episode_runtime.testing.test_scoped_execution import (
    LinkedExecutor,
    nested_build,
)


def component_experiment(artifacts, builds, request, receipt, tmp_path, definition, payload):
    raw = experiment(artifacts, request, receipt)
    raw["scope"].update(
        kind="component",
        entry_local_id="group",
        included_local_ids=["group"],
        component_definition_id=definition.definition_id,
    )
    raw["boundary"]["children"] = "none"
    raw["start"]["input_payload"] = payload
    launch = resolve_launch({
        "project": "component-fixture",
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
    raw["launch_ref"] = put_data(
        artifacts, request.frozen_workflow.duet_id.value, "launch", launch.record
    )
    FixtureLaunchHost(artifacts, builds, request.frozen_workflow.duet_id.value).approve_fixture(launch)
    return raw


def assign_measure(raw, artifacts, builds, duet_id, path, expected, rejected):
    grounding = put_data(
        artifacts, duet_id, "grounding", {"expected": expected, "rejected": rejected}
    )
    registered = register_criterion(
        {
            "schema_version": 1,
            "build_receipt_ref": raw["build_receipt_ref"],
            "environment_ref": raw["environment_ref"],
            "requirement_key": "bound-component-behavior",
            "description": "Inspect the actual selected function output under exact inputs.",
            "scope": raw["scope"],
            "accepted_modes": ["live_fresh", "live_saved", "recorded"],
            "input_payload": raw["start"]["input_payload"],
            "predicate": selected(EXACT_VALUE).as_record(),
            "observation_path": path,
            "expected_value": expected,
            "positive_controls": [expected],
            "negative_controls": [rejected],
            "grounding_refs": [grounding],
            "limitations": [
                "Does not test the Episode loop or independently establish the calibration of its rarefaction estimator."
            ],
        },
        artifacts=artifacts,
        builds=builds,
        duet_id=duet_id,
    )
    raw["requirements"] = [
        {
            "requirement_ref": registered["requirement_ref"],
            "measure_ref": registered["measure_ref"],
            "expected": "Output matches the declared function behavior.",
            "falsifying": "Output violates the frozen criterion.",
        }
    ]


@pytest.mark.asyncio
async def test_component_continuation_uses_bound_parameters_without_running_episodes(
    tmp_path, run_store, monkeypatch, capsys
):
    request, builds, receipt = await nested_build(tmp_path)
    executor = LinkedExecutor(tmp_path / "execution", run_store[1].runtime_identity)

    def forbidden_model(*args, **kwargs):
        raise AssertionError(
            "component selection must not run an ancestor or child model"
        )

    monkeypatch.setattr("agent.episode_launch_transport._invoke", forbidden_model)
    duet_id = request.frozen_workflow.duet_id.value
    with DuetStore(tmp_path / "duet.db") as artifacts:
        service = ExperimentService(
            artifacts=artifacts,
            builds=builds,
            runs=executor.run_store,
            executor=executor,
        )
        for projected in (0.8, 0.95):
            raw = component_experiment(
                artifacts,
                builds,
                request,
                receipt,
                tmp_path,
                PREDICTED_CREDIT_UPPER_BOUND,
                {
                    "binding_role": "controller.continuation",
                    "adapter": "numeric_band",
                    "inputs": {
                        "projected_credit": {
                            "value": projected,
                            "lower": projected,
                            "upper": projected,
                            "uncertainty_alpha": 0.0,
                            "status": "ready",
                        }
                    },
                },
            )
            plan = preview_experiment(
                ExperimentSpec.from_record(raw),
                builds=builds,
                artifacts=artifacts,
                runs=executor.run_store,
            )
            assert plan["resolved"], plan["gaps"]
            binding = plan["execution_scope"]["binding"]
            threshold = binding["arguments"]["max_predicted_marginal_hypervolume"]
            expected = projected <= threshold
            assign_measure(
                raw,
                artifacts,
                builds,
                duet_id,
                "/component_result/value/stop",
                expected,
                not expected,
            )
            spec = ExperimentSpec.from_record(raw)
            path = tmp_path / "component.json"
            path.write_text(spec.canonical_record, encoding="utf-8")
            assert (
                main([
                    "preview",
                    "--spec",
                    str(path),
                    "--duet-store",
                    str(tmp_path / "duet.db"),
                    "--build-store",
                    str(tmp_path),
                    "--run-store",
                    str(executor.run_store.root),
                ])
                == 0
            )
            preview = json.loads(capsys.readouterr().out)
            assert preview["scope"]["component_bindings"][0]["configuration_is_frozen"]
            assert "projected_credit" in [
                row["name"]
                for row in preview["scope"]["component_bindings"][0]["call_signature"]
            ]
            assert any(
                row["definition_id"] == PREDICTED_CREDIT_UPPER_BOUND.definition_id
                for row in preview["scope"]["available_component_bindings"]
            )
            result = await service.run(spec)
            assert result["execution_status"] == "succeeded", result
            assert result["candidate_verdict"] == "pass", result
            assert (
                result["typed_status"]["component_result"]["value"]["threshold"]
                == threshold
            )
            assert result["measurement"]["outcomes"][0]["observed"] is expected
            assert not result["measurement"]["progress"]["admitted"]
            assert not result["measurement"]["acceptance"]["admitted"]
            assert "workflow_result" not in result["typed_status"]
            record = read_recording(executor.run_store, result["run_id"])
            assert (
                not record["invocations"]
                and not record["units"]
                and not record["learning"]
                and not record["exchanges"]
            )
            assert len(record["components"]) == 1
            count = executor.calls
            assert await service.run(spec) == result
            assert executor.calls == count

        run_id = OpaqueId(result["run_id"])
        registration = executor.run_store.read_registration(run_id)
        assert RunRegistration.from_record(registration.as_record()) == registration
        broker = LearningBroker(
            executor.run_store,
            registration,
            builds.verify_source_package(
                builds.inspection_inputs_for_receipt(receipt.receipt_id).manifest
            ),
        )
        forged = {
            **result["typed_status"],
            "completion": {"claim": "episode completed"},
        }
        with pytest.raises(ValueError, match="cannot claim Episode completion"):
            broker.validate_completion(forged)
        event = record["components"][0]
        with pytest.raises(ValueError, match="cannot run an Episode"):
            validate_component_event(
                registration,
                RunEventKind.EPISODE_STARTED,
                OpaqueId(event["episode_id"]),
                {"episode_path": event["episode_path"]},
            )
        with pytest.raises(ValueError, match="outside the exact"):
            validate_execution_path(
                registration,
                [*event["episode_path"], {"grain": "leaf", "key": "child"}],
            )

        changed = deepcopy(raw)
        changed["start"]["input_payload"]["inputs"]["parameters"] = {
            "max_predicted_marginal_hypervolume": 1
        }
        denied = preview_experiment(
            ExperimentSpec.from_record(changed),
            builds=builds,
            artifacts=artifacts,
            runs=executor.run_store,
        )
        assert not denied["resolved"]
        assert any(
            row["kind"] == "component_input_unavailable" for row in denied["gaps"]
        )

        recording_ref = save_recording(artifacts, executor.run_store, result["run_id"])
        for mode in ("live_saved", "recorded"):
            saved = deepcopy(raw)
            saved["mode"] = mode
            saved["start"] = {
                "kind": "saved_inputs",
                "artifact_ref": recording_ref,
                "input_payload": {},
            }
            saved["recording_ref"] = recording_ref if mode == "recorded" else None
            again = await service.run(ExperimentSpec.from_record(saved))
            assert again["execution_status"] == "succeeded", again
            assert again["candidate_verdict"] == "pass"
            assert (
                again["typed_status"]["component_result"]
                == result["typed_status"]["component_result"]
            )

        changed = deepcopy(raw)
        changed["mode"] = "recorded"
        changed["recording_ref"] = recording_ref
        changed["start"]["input_payload"]["inputs"]["projected_credit"].update(
            value=0.7, lower=0.7, upper=0.7
        )
        count = executor.calls
        with pytest.raises(ReplayDivergence, match="execution_context_mismatch"):
            await service.run(ExperimentSpec.from_record(changed))
        assert executor.calls == count


@pytest.mark.asyncio
async def test_component_observes_real_schema_rejection_as_data_not_completion(
    tmp_path, run_store
):
    request, builds, receipt = await nested_build(tmp_path)
    executor = LinkedExecutor(tmp_path / "execution", run_store[1].runtime_identity)
    duet_id = request.frozen_workflow.duet_id.value
    with DuetStore(tmp_path / "duet.db") as artifacts:
        raw = component_experiment(
            artifacts,
            builds,
            request,
            receipt,
            tmp_path,
            RESULT_SCHEMA,
            {
                "binding_role": "component.epistemic_result_schema",
                "adapter": "json_keywords",
                "inputs": {"value": {"status": "I award myself credit"}},
            },
        )
        assign_measure(
            raw,
            artifacts,
            builds,
            duet_id,
            "/component_result/status",
            "raised",
            "returned",
        )
        service = ExperimentService(
            artifacts=artifacts,
            builds=builds,
            runs=executor.run_store,
            executor=executor,
        )
        result = await service.run(ExperimentSpec.from_record(raw))
        assert result["execution_status"] == "succeeded", result
        assert result["candidate_verdict"] == "pass", result
        observation = result["typed_status"]["component_result"]
        assert observation["error"]["type"] == "ValueError"
        assert observation["value"] is None
        assert not read_recording(executor.run_store, result["run_id"])["learning"]
