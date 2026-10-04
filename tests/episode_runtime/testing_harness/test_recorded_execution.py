"""Recorded mode through the shared service, real brokers, frames and stores.

The executor fixture emits two protocol exchanges then interrupts. It DOES NOT
run Target Workflow code or attest confinement. The live transport is canned. These
are recording/integration checks, not the reasoning acceptance demonstration.
"""

from copy import deepcopy
import json

import pytest

from agent.duet_store import DuetStore
from agent.episode_contracts import OpaqueId
from agent.episode_launch import resolve_launch
from tests.episode_runtime.testing_harness.launch_fixture import FixtureLaunchHost
from episode_runtime import protocol
from episode_runtime.contracts import RunEventOrigin, RunTerminalStatus
from episode_runtime.exchanges import broker_model_request, broker_http_request
from episode_runtime.store import RunStore
from episode_runtime.testing_harness.contracts import ExperimentSpec
from episode_runtime.testing_harness.playback import ReplayDivergence
from episode_runtime.testing_harness.recordings import (
    load_recording,
    read_recording,
)
from episode_runtime.testing_harness.service import ExperimentService
from episode_runtime.records.experiments import put_data
from openchia_cli.episode_test_command import main
from tests.episode_builder.test_repeatable_call_materialization import build
from tests.episode_runtime.conftest import claim_store
from tests.episode_runtime.test_model_request_thaw import REQUEST
from tests.episode_runtime.testing_harness.test_experiment_planning import experiment


class _Channel:
    @property
    def next_sender_sequence(self):
        return self.sequence

    def __init__(self, binding):
        self.binding = binding
        self.encoder = protocol.FrameEncoder(
            sender=protocol.FrameSender.HOST, binding=binding
        )
        self.sequence = 0

    def prepare(self, kind, body):
        packet = self.encoder.encode(kind, body)
        frame = protocol.decode_frame(
            packet,
            sender=protocol.FrameSender.HOST,
            binding=self.binding,
            expected_sequence=self.sequence,
        )
        self.sequence += 1
        return frame, packet

    async def publish(self, prepared):
        return prepared[0]

    async def send(self, kind, body):
        return await self.publish(self.prepare(kind, body))


class ExchangeOnlyExecutor:
    def __init__(self, root, identity):
        self.root = root
        self.run_store = RunStore(root / "runs")
        self.identity = identity
        self.model_request = deepcopy(REQUEST)
        self.launches = 0

    def inspect_runtime_identity(self, **kwargs):
        return self.identity

    async def execute(self, *, registration, model_broker, http_broker, **kwargs):
        self.launches += 1
        claim_store(self.root, registration)  # explicitly inert attestation fixture
        binding = protocol.ProtocolBinding.from_registration(registration)
        channel = _Channel(binding)
        worker = protocol.FrameEncoder(
            sender=protocol.FrameSender.WORKER, binding=binding
        )
        path = [{"grain": "inquiry", "key": registration.run_id.value}]
        records = [
            ("model", self.model_request, broker_model_request, model_broker),
            (
                "http",
                {
                    "method": "GET",
                    "url": "https://example.org/test",
                    "headers": {},
                    "body": None,
                    "timeout": 10.0,
                },
                broker_http_request,
                http_broker,
            ),
        ]
        try:
            for index, (kind, request, exchange, broker) in enumerate(records):
                frame = protocol.decode_frame(
                    worker.encode(
                        kind + "_request",
                        {
                            kind + "_request_id": OpaqueId.mint(
                                kind + "_request", "fixture"
                            ).value,
                            "episode_id": protocol.episode_id_for_path(
                                registration.run_id, path
                            ).value,
                            "episode_path": path,
                            "request": request,
                        },
                    ),
                    sender=protocol.FrameSender.WORKER,
                    binding=binding,
                    expected_sequence=index,
                )
                await exchange(
                    run_store=self.run_store,
                    registration=registration,
                    channel=channel,
                    frame=frame,
                    **{kind + "_broker": broker},
                )
        except ReplayDivergence:
            self.run_store.finalize_run(
                run_id=registration.run_id,
                origin=RunEventOrigin.HOST,
                sender_sequence=channel.sequence,
                terminal_status=RunTerminalStatus.INVALID,
                typed_status={"outcome": "invalid", "failure_type": "ReplayDivergence"},
            )
            raise
        return self.run_store.finalize_run(
            run_id=registration.run_id,
            origin=RunEventOrigin.HOST,
            sender_sequence=channel.sequence,
            terminal_status=RunTerminalStatus.INTERRUPTED,
            typed_status={
                "outcome": "interrupted",
                "reason": "exchange-only fixture, no candidate was executed",
            },
        )


@pytest.mark.asyncio
async def test_shared_recorded_dispatch_uses_original_evidence_without_live_fallback(
    tmp_path, run_store, monkeypatch, capsys
):
    request, builds, receipt = await build(tmp_path, ())
    executor = ExchangeOnlyExecutor(
        tmp_path / "execution", run_store[1].runtime_identity
    )
    calls = []

    def model(route, key, request, cancel, progress):
        calls.append((route["model"], key))
        return '{"fixture_reply":42}', route["model"]

    monkeypatch.setattr("agent.episode_launch_transport._invoke", model)
    credential_file = tmp_path / "recording.env"
    credential_file.write_text("RECORDING_TEST_KEY=private-recording-fixture-token\n", encoding="utf-8")
    launch = resolve_launch({
        "project": "recording-fixture",
        "project_root": str(tmp_path),
        "env_files": [str(credential_file)],
        "routes": {
            "test": {
                "provider": "custom",
                "model": "fixture",
                "base_url": "https://example.org/v1",
                "api_mode": "chat_completions",
                "auth": {
                    "kind": "env",
                    "env": "RECORDING_TEST_KEY",
                    "account": "fixture",
                },
            }
        },
        "model_slots": {"selector": "test", "executor": "test", "reasoning": "test"},
        "builder_slots": {"planning": "selector", "emission": "executor"},
    })
    with DuetStore(tmp_path / "duet.db") as artifacts:
        service = ExperimentService(
            artifacts=artifacts,
            builds=builds,
            runs=executor.run_store,
            executor=executor,
        )
        raw = experiment(artifacts, request, receipt)
        FixtureLaunchHost(artifacts, builds, request.frozen_workflow.duet_id.value).approve_fixture(launch)
        raw["launch_ref"] = put_data(
            artifacts, request.frozen_workflow.duet_id.value, "launch", launch.record
        )
        live_launch_ref = raw["launch_ref"]
        live = await service.run(ExperimentSpec.from_record(raw))
        assert live["execution_status"] == "interrupted"
        assert calls == [("fixture", "private-recording-fixture-token")]
        source = read_recording(executor.run_store, live["run_id"])
        assert len(source["exchanges"]) == 2
        assert (
            main([
                "recording",
                "--run-store",
                str(executor.root / "runs"),
                "--run-id",
                live["run_id"],
                "--save",
                "--duet-store",
                str(tmp_path / "duet.db"),
            ])
            == 0
        )
        inspected = json.loads(capsys.readouterr().out)
        assert "exchanges" not in inspected
        saved = inspected["recording_ref"]
        _, recovered = load_recording(
            artifacts, executor.run_store, saved, request.frozen_workflow.duet_id.value
        )
        assert recovered == source

        credential_file.unlink()
        raw.update(mode="recorded", recording_ref=saved, launch_ref=None)
        spec = ExperimentSpec.from_record(raw)
        replay = await service.run(spec)
        assert replay["mode"] == "recorded"
        assert replay["execution_status"] == "interrupted"  # never completion
        assert replay["candidate_verdict"] == "unmeasured"
        assert not replay["progress"]["admitted"]
        assert replay["recorded_execution"]["status"] == "matched"
        assert len(calls) == 1  # source call only; credential is now unavailable
        replayed = read_recording(executor.run_store, replay["run_id"])
        for original, reused in zip(
            source["exchanges"], replayed["exchanges"], strict=True
        ):
            assert reused["response"] == original["response"]
            assert (
                reused["reused_from"]["response_event_ref"]
                == original["response_event_ref"]
            )
        assert await service.run(spec) == replay
        assert executor.launches == 2

        changed_context = deepcopy(raw)
        changed_context["environment_ref"] = put_data(
            artifacts,
            request.frozen_workflow.duet_id.value,
            "environment",
            {"dataset": "changed-dataset"},
        )
        with pytest.raises(ReplayDivergence, match="execution_context_mismatch"):
            await service.run(ExperimentSpec.from_record(changed_context))
        assert executor.launches == 2
        assert len(calls) == 1

        credential_file.write_text("RECORDING_TEST_KEY=private-recording-fixture-token\n", encoding="utf-8")
        saved_input = deepcopy(raw)
        saved_input.update(
            mode="live_saved", recording_ref=None, launch_ref=live_launch_ref
        )
        saved_input["start"] = {
            "kind": "saved_inputs",
            "artifact_ref": saved,
            "input_payload": {},
        }
        fresh_from_saved = await service.run(ExperimentSpec.from_record(saved_input))
        assert fresh_from_saved["mode"] == "live_saved"
        assert "recorded_execution" not in fresh_from_saved
        assert len(calls) == 2  # this mode makes a new external call
        source_launch = executor.run_store.read_registration(
            OpaqueId(live["run_id"])
        ).launch_request.as_record()
        new_launch = executor.run_store.read_registration(
            OpaqueId(fresh_from_saved["run_id"])
        ).launch_request.as_record()
        assert source_launch.pop("request_id") != new_launch.pop("request_id")
        assert source_launch == new_launch
        credential_file.unlink()

        executor.model_request["messages"][1]["content"] = (
            "Changed request must not borrow an old answer."
        )
        raw["question"] = "Does an incompatible external request fail explicitly?"
        divergent = await service.run(ExperimentSpec.from_record(raw))
        assert divergent["execution_status"] == "invalid"
        assert (
            divergent["recorded_execution"]["divergence"]["kind"]
            == "unmatched_external_request"
        )
        assert len(calls) == 2
        assert read_recording(executor.run_store, live["run_id"]) == source


@pytest.mark.asyncio
async def test_recording_cursor_rejects_wrong_invocation_and_exhaustion(run_store):
    from episode_runtime.broker import ScopedModelBroker
    from episode_runtime.testing_harness.playback import RecordingCursor
    from llm_call_library import ModelTransportResponse

    runs, registration, _ = run_store
    path = [
        {"grain": "root", "key": registration.run_id.value},
        {"grain": "child", "key": "one"},
    ]
    binding = protocol.ProtocolBinding.from_registration(registration)
    worker = protocol.FrameEncoder(sender=protocol.FrameSender.WORKER, binding=binding)
    frame = protocol.decode_frame(
        worker.encode(
            "model_request",
            {
                "model_request_id": OpaqueId.mint("model_request", "fixture").value,
                "episode_id": protocol.episode_id_for_path(
                    registration.run_id, path
                ).value,
                "episode_path": path,
                "request": REQUEST,
            },
        ),
        sender=protocol.FrameSender.WORKER,
        binding=binding,
        expected_sequence=0,
    )

    async def response(request):
        return ModelTransportResponse(text="fixture", route={})

    await broker_model_request(
        run_store=runs,
        registration=registration,
        channel=_Channel(binding),
        frame=frame,
        model_broker=ScopedModelBroker(response, {("root", "child"): "child"}),
    )
    recorded = read_recording(runs, registration.run_id)
    target_id = OpaqueId.mint("run", "fork").value
    cursor = RecordingCursor(recorded, registration.run_id.value, target_id)
    broker = ScopedModelBroker(None, {("root", "child"): "child"}, recording=cursor)
    target_path = [
        {"grain": "root", "key": target_id},
        {"grain": "child", "key": "one"},
    ]
    assert (await broker(REQUEST, episode_path=target_path)).text == "fixture"
    with pytest.raises(ReplayDivergence):
        await broker(REQUEST, episode_path=target_path)
    wrong = ScopedModelBroker(
        None,
        {("root", "child"): "child"},
        recording=RecordingCursor(recorded, registration.run_id.value, target_id),
    )
    with pytest.raises(ReplayDivergence):
        await wrong(
            REQUEST, episode_path=[target_path[0], {"grain": "child", "key": "two"}]
        )
    with pytest.raises(TypeError, match="no live transport"):
        ScopedModelBroker(response, {}, recording=cursor)
    wrong_root = RecordingCursor(recorded, registration.run_id.value, target_id)
    with pytest.raises(ReplayDivergence, match="invocation_context_mismatch"):
        wrong_root.take("model", REQUEST, path)
