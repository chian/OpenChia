"""Approved testing access over real worker/host frames and shared stores.

Launch/attestation is deliberately inert and target output is supplied. The
production worker channel, executor dispatch, access checks and shared service
are exercised; this does not claim confinement or model-designed experiments.
"""

import json
from dataclasses import replace

import pytest

from agent.duet_store import DuetStore
from agent.episode_contracts import EpisodeCreationSpec
from agent.episode_launch import resolve_launch
from tests.episode_runtime.testing.launch_fixture import FixtureLaunchHost
from episode_builder.service import EpisodeBuilder
from episode_runtime import executor as executor_module
from episode_runtime.contracts import RunEventKind, RunTerminalStatus
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.execution import RunExecution, register_build
from episode_runtime.testing.inputs import workflow_template
from episode_runtime.records.experiments import put_data
from episode_runtime.testing.session import ExperimentAccessError
from function_library.testing_contract import TestingContract as ExperimentAccess
from llm_call_library.transport import ModelTransportResponse, model_transport_scope
from llm_call_library import CallOptions
from tests.episode_builder.test_repeatable_call_materialization import build
from tests.episode_runtime import test_executor_http_loop as pipe
from tests.episode_runtime.conftest import oid
from tests.episode_runtime.test_reasoning_workflow import (
    _approved_request,
    _plan_response,
    _module_response,
)
from tests.episode_runtime.testing.test_experiment_planning import experiment
from tests.episode_runtime.testing.test_measurements import ResultOnlyExecutor


WORKER = r"""
import asyncio, json, platform, sys
from agent.episode_contracts import OpaqueId, Sha256Digest
from episode_runtime.contracts import RunEventKind, RunTerminalStatus
from episode_runtime.landlock import LandlockPolicyReceipt
from episode_runtime.seccomp import SeccompPolicyReceipt, normalize_machine, seccomp_policy_hash
from episode_runtime.protocol import ProtocolBinding, HostFrameType, WorkerFrameType, episode_id_for_path
from episode_runtime.worker import _ProtocolChannel
from episode_runtime.linker import _CURRENT_RUNTIME_EPISODE_ID, _CURRENT_RUNTIME_EPISODE_PATH
from function_library.testing import experiment_request, experiment_transport_scope

async def main():
    run, reg, manifest, limit, runtime, runtime_hash = sys.argv[1:7]
    scenarios = json.loads(sys.argv[7])
    binding = ProtocolBinding(OpaqueId(run), Sha256Digest(reg), OpaqueId(manifest), int(limit))
    reader = asyncio.StreamReader()
    await asyncio.get_running_loop().connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    channel = _ProtocolChannel(binding=binding, reader=reader)
    init = await channel.receive()
    assert init.frame_type == HostFrameType.INITIALIZE.value
    executor = OpaqueId(init.body['executor_instance_id'])
    machine = normalize_machine(platform.machine())
    await channel.send(WorkerFrameType.READY.value, {
        'runtime_id': runtime, 'runtime_hash': runtime_hash,
        'landlock_receipt': LandlockPolicyReceipt(binding.run_id, executor).as_record(),
        'seccomp_receipt': SeccompPolicyReceipt(binding.run_id, executor, machine, seccomp_policy_hash(machine)).as_record(),
    })
    assert (await channel.receive()).frame_type == HostFrameType.START.value
    path = [{'grain': 'inquiry', 'key': run}]
    episode = episode_id_for_path(binding.run_id, path)
    _CURRENT_RUNTIME_EPISODE_ID.set(episode)
    _CURRENT_RUNTIME_EPISODE_PATH.set((('inquiry', run),))
    await channel.event(RunEventKind.EPISODE_STARTED, episode, {'episode_path': path})
    receiver = asyncio.create_task(channel.receive_loop())
    with experiment_transport_scope(channel.request_experiment):
        description = await experiment_request(operation='describe', payload={})
        assert description['assigned_access']['targets']
        history = await experiment_request(operation='history', payload={'query': {}})
        assert not history['items'], history  # Prior invocations cannot leak their tests.
        if scenarios['deny'] == 'unowned':
            recordings = await experiment_request(operation='history', payload={'query': {'experiment_id': scenarios['experiment_id']}})
            assert recordings['operation_status'] == 'rejected'
            await experiment_request(operation='results', payload={'experiment_id': scenarios['experiment_id']})
        if scenarios['deny'] == 'unowned_inventory':
            await experiment_request(operation='inventory', payload={'source': {'kind': 'experiment', 'experiment_id': scenarios['experiment_id']}, 'query': {}})
        if scenarios['deny'] == 'unowned_continue':
            await experiment_request(operation='continue', payload={'experiment_id': scenarios['experiment_id'], 'resume_from': scenarios['resume_from']})
        plan = await experiment_request(operation='preview', payload={'spec': scenarios['spec']})
        assert plan['resolved'], plan
        result = await experiment_request(operation='run', payload={'spec': scenarios['spec']})
        again = await experiment_request(operation='results', payload={'experiment_id': result['experiment_id']})
        assert result == again
        if scenarios['deny'] is False:
            continued = await experiment_request(operation='continue', payload={'experiment_id': result['experiment_id'], 'resume_from': result['resume_from']})
            assert continued.get('operation_status') != 'rejected', continued
            assert continued['run_id'] != result['run_id']
            assert continued['logical_run_id'] == result['logical_run_id']
            assert continued['experiment_id'] == result['experiment_id']
            result = continued
        recording = await experiment_request(operation='recording', payload={'experiment_id': result['experiment_id']})
        assert recording['recording_ref']
        history = await experiment_request(operation='history', payload={'query': {}})
        assert [row['experiment_id'] for row in history['items']] == [result['experiment_id']]
        assert history['items'][0]['execution']['recordings']['items'][0]['recording_ref'] == recording['recording_ref']
        reports_query = {**history['items'][0]['reports_query'], 'limit': 1}
        reports = await experiment_request(operation='history', payload={'query': reports_query})
        assert reports['record_type'] == 'reports', reports
        assert len(reports['items']) == 1, reports
        assert reports['next_query'] is not None, reports
        later_reports = await experiment_request(operation='history', payload={'query': reports['next_query']})
        assert len(later_reports['items']) == 1, later_reports
        assert later_reports['next_query'] is None
        retained = reports['items'] + later_reports['items']
        assert sum(row['is_current'] for row in retained) == 1
        current = next(row for row in retained if row['is_current'])
        assert current['measurement_ref'] == result['measurement']['measurement_ref']
        assert reports['current_measurement_ref'] == later_reports['current_measurement_ref'] == current['measurement_ref']
        assert retained[0]['measurement_ref'] != retained[1]['measurement_ref']
        assert retained[0]['execution_ref'] != retained[1]['execution_ref']
        recordings = await experiment_request(operation='history', payload={'query': {'experiment_id': result['experiment_id']}})
        assert recordings['record_type'] == 'recordings'
        assert recordings['items'][0]['recording_ref'] == recording['recording_ref']
        inventory = await experiment_request(operation='inventory', payload={'source': {'kind': 'experiment', 'experiment_id': result['experiment_id']}, 'query': {}})
        assert inventory['selection_status'] == 'required', inventory
        assert inventory['required_action'] == 'select_attempt_prefix'
        assert not inventory['items']
        attempt = next(row for row in inventory['attempts'] if row['run_id'] == result['run_id'])
        inventory = await experiment_request(operation='inventory', payload=attempt['inventory_requests']['invocations'])
        assert inventory['coverage'] == 'physical_attempt_only'
        assert inventory['run_id'] == result['run_id']
        assert inventory['index_status'] == 'current'
        assert not inventory['items']  # Supplied-result target executes no Episode.
        recorded_inventory = await experiment_request(operation='inventory', payload={'source': {'kind': 'recording', 'recording_ref': recording['recording_ref']}, 'query': {}})
        assert recorded_inventory['through_event_ref'] == inventory['through_event_ref']
        if scenarios['deny'] is True:
            # The exact same spec was already run, but an unapproved criterion
            # cannot borrow its authority or its result.
            changed = json.loads(json.dumps(scenarios['spec']))
            changed['requirements'][0]['measure_ref'] = changed['environment_ref']
            await experiment_request(operation='run', payload={'spec': changed})
        await channel.terminal(terminal_status=RunTerminalStatus.INTERRUPTED,
            typed_status={'reason': 'transport fixture, no testing Episode or model executed', 'experiment_id': result['experiment_id']})
        await receiver

asyncio.run(main())
"""


class ExperimentPipeExecutor(pipe._PipeExecutor):
    def __init__(self, runs, script, identity, target):
        super().__init__(runs, script)
        self.identity, self.target = identity, target
        self.supplied = ResultOnlyExecutor(runs.root.parent, identity)
        self.supplied.run_store = runs
        self.supplied.terminal = RunTerminalStatus.INTERRUPTED
        self.continuation_admissions = []

    def inspect_runtime_identity(self, **kwargs):
        return self.identity

    async def execute(self, **kwargs):
        if kwargs["registration"].build_receipt_id == self.target:
            if kwargs["registration"].resume_from is not None:
                # Real current-authority admission, but no worker restoration:
                # this target deliberately emits only a supplied result.
                self.continuation_admissions.append(
                    await kwargs["continuation_admission"]()
                )
            return await self.supplied.execute(**kwargs)
        return await super().execute(**kwargs)


@pytest.mark.asyncio
async def test_worker_channel_preserves_approved_access_and_uses_shared_service(
    tmp_path, run_store, monkeypatch
):
    target_request, builds, target_receipt = await build(tmp_path, ())
    with DuetStore(tmp_path / "duet.db") as artifacts:
        spec = experiment(artifacts, target_request, target_receipt)
        launch = resolve_launch({
            "project": "testing-channel",
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
        spec["launch_ref"] = put_data(
            artifacts,
            target_request.frozen_workflow.duet_id.value,
            "launch",
            launch.record,
        )
        FixtureLaunchHost(artifacts, builds, target_request.frozen_workflow.duet_id.value).approve_fixture(launch)
    target = {
        key: spec[key]
        for key in (
            "candidate_ref",
            "build_receipt_ref",
            "environment_ref",
            "launch_ref",
            "campaign_ref",
        )
    }
    target.update(
        requirements=[
            {key: row[key] for key in ("requirement_ref", "measure_ref")}
            for row in spec["requirements"]
        ],
        recording_refs=[],
        parent_context_refs=[],
    )
    approved = replace(
        target_request.frozen_workflow.workflow.episodes[0].contract,
        execution_capability_names=("episode_testing",),
        testing=ExperimentAccess({"target": target}, ("workflow",), ("live_fresh",)),
    )
    assert EpisodeCreationSpec.from_record(approved.as_record()) == approved
    with pytest.raises(ValueError, match="approved episode_testing capability"):
        replace(approved, execution_capability_names=())
    request = _approved_request(
        tmp_path,
        spec=approved,
        allowed_capabilities=("episode_testing",),
        duet_id=oid("tester"),
    )

    async def builder_model(request):
        prompt = json.loads(request.messages[-1]["content"])
        response = (
            _plan_response(prompt) if "node" in prompt else _module_response(prompt)
        )
        return ModelTransportResponse(text=json.dumps(response), route={})

    with model_transport_scope(builder_model):
        receipt = await EpisodeBuilder(
            store=builds,
            planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"selector": {}, "executor": {}},
        ).build(request)
    assert receipt.materialized, [row.as_record() for row in receipt.deficits]
    inputs = builds.inspection_inputs_for_receipt(receipt.receipt_id)
    assert (
        inputs.build_request.frozen_workflow.workflow.episodes[0].contract.testing
        == approved.testing
    )
    script = tmp_path / "worker.py"
    script.write_text(WORKER, encoding="utf-8")
    from episode_runtime.store import RunStore

    runs = RunStore(tmp_path / "execution" / "runs")
    executor = ExperimentPipeExecutor(
        runs, script, run_store[1].runtime_identity, target_receipt.receipt_id
    )
    # These two replacements concern only inert launch/attestation. Real source
    # admission, protocol validation, LearningBroker and RunStore remain active.
    monkeypatch.setattr(
        executor_module, "verify_runtime_identity", lambda *a, **k: None
    )
    monkeypatch.setattr(
        executor_module, "load_verified_bootstrap_program", lambda *a, **k: ""
    )
    from episode_runtime.broker import ScopedModelBroker
    from episode_runtime.http_broker import ScopedHttpBroker

    model = ScopedModelBroker.from_plan(pipe._unused_model_transport, inputs.plan)

    async def unused_http(**kwargs):
        raise AssertionError("no HTTP call is part of this fixture")

    with DuetStore(tmp_path / "duet.db") as artifacts:
        execution = RunExecution(
            artifacts=artifacts, builds=builds, runs=runs, executor=executor
        )
        from episode_runtime.testing.planning import preview_experiment

        recorded_tester = experiment(artifacts, request, receipt)
        recorded_tester["mode"] = "recorded"
        preview = preview_experiment(
            ExperimentSpec.from_record(recorded_tester),
            builds=builds,
            artifacts=artifacts,
        )
        assert any(
            gap["kind"] == "nested_experiment_replay_unavailable"
            for gap in preview["gaps"]
        )
        from episode_runtime.testing.service import ExperimentService

        for deny in (False, True, "unowned", "unowned_inventory", "unowned_continue"):
            current = ExperimentService.status(
                artifacts, runs, ExperimentSpec.from_record(spec).experiment_id
            )
            monkeypatch.setattr(
                pipe,
                "REQUEST",
                {
                    "spec": spec,
                    "deny": deny,
                    "experiment_id": ExperimentSpec.from_record(spec).experiment_id,
                    "resume_from": current.get("resume_from"),
                },
            )
            launch_request = replace(
                workflow_template(request.frozen_workflow),
                request_id=oid(f"launch_{str(deny).lower()}").value,
            )
            registration, package = register_build(
                executor, builds, inputs, launch_request, run_store[1].runtime_policy
            )
            intent = put_data(
                artifacts,
                registration.duet_id.value,
                "intent",
                {"why": "exercise worker test access", "deny": deny},
            )
            execution_arguments = dict(
                registration=registration,
                source_package_path=package,
                intent_ref=intent,
                model_broker=model,
                http_broker=ScopedHttpBroker(
                    policy=registration.egress_policy,
                    credentials={},
                    transport=unused_http,
                    max_frame_bytes=registration.runtime_policy.max_frame_bytes,
                ),
            )
            if deny:
                with pytest.raises(ExperimentAccessError, match="assigned"):
                    await execution.execute(**execution_arguments)
                evidence = runs.read_evidence(registration.run_id)
            else:
                evidence = await execution.execute(**execution_arguments)
            assert evidence.terminal_status.value == (
                "failed" if deny else "interrupted"
            )
            events = runs.read_audit_log(registration.run_id)
            requested = [
                row for row in events if row.kind is RunEventKind.EXPERIMENT_REQUESTED
            ]
            responded = [
                row for row in events if row.kind is RunEventKind.EXPERIMENT_RESPONDED
            ]
            expected = {
                False: ["describe", "history", "preview", "run", "results", "continue"],
                True: ["describe", "history", "preview", "run", "results", "recording"],
                "unowned": ["describe", "history", "history", "results"],
                "unowned_inventory": ["describe", "history", "inventory"],
                "unowned_continue": ["describe", "history", "continue"],
            }
            assert [row.payload["operation"] for row in requested][:6] == expected[deny]
            assert len(requested) == len(responded) + int(bool(deny))
            if deny:
                assert "assigned" in evidence.typed_status["failure"]
            else:
                assert (
                    evidence.typed_status["experiment_id"]
                    == ExperimentSpec.from_record(spec).experiment_id
                )
        # One initial attempt and one owned continuation. Later invocations may
        # inspect their own tests but cannot continue another invocation's test.
        assert executor.supplied.calls == 2
        assert len(executor.continuation_admissions) == 1
