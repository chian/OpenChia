"""All-channel evidence through actual frames, brokers and a claimed RunStore.

Host-session answers and the model transport are supplied. These checks prove
recording integrity and playback selection, not task reasoning or confinement.
"""

import asyncio
from copy import deepcopy

import pytest

from agent.duet_contracts import content_id, digest_record
from agent.duet_store import DuetStore
from agent.episode_contracts import OpaqueId
from episode_runtime import protocol
from episode_runtime.broker import ScopedModelBroker
from episode_runtime.contracts import RunEventKind, RunEventOrigin
from episode_runtime.executor import _HostChannel
from episode_runtime.exchanges import (
    broker_experiment_request,
    broker_learning_request,
    broker_model_request,
    broker_refinement_request,
)
from episode_runtime.records.experiments import put_data
from episode_runtime.testing.playback import RecordingCursor, ReplayDivergence
from episode_runtime.testing.recordings import (
    load_recording,
    read_recording,
    recording_summary,
    save_recording,
)
from llm_call_library import ModelTransportResponse
from tests.episode_runtime.test_model_request_thaw import REQUEST


OPERATIONS = {"learning": "retrieve", "refinement": "context", "experiment": "describe"}
HANDLERS = {
    "learning": broker_learning_request,
    "refinement": broker_refinement_request,
    "experiment": broker_experiment_request,
}


class PacketWriter:
    def __init__(self):
        self.packets = []

    def write(self, packet):
        self.packets.append(packet)

    async def drain(self):
        return None


class SuppliedSession:
    def __init__(self, kind):
        self.kind = kind

    async def __call__(self, episode_id, operation, payload):
        return {"channel": self.kind, "operation": operation, "observed": payload}

    async def exchange(self, *, episode_id, episode_path, operation, payload):
        return await self(episode_id.value, operation, payload)

    def continuation_state(self):
        # Exercise host-only metadata preservation, not a recoverable session.
        return {"fixture_only": True, "channel": self.kind}


def request_frame(binding, worker, kind, path, ordinal):
    body = {
        "episode_id": protocol.episode_id_for_path(binding.run_id, path).value,
        "episode_path": path,
    }
    if kind == "model":
        body.update(
            model_request_id=OpaqueId.mint("model_request", f"recording-{ordinal}").value,
            request=deepcopy(REQUEST),
        )
    else:
        body.update(
            request_id=OpaqueId.mint(kind + "_request", f"recording-{ordinal}").value,
            operation=OPERATIONS[kind],
            payload={"role": "parts"} if kind == "refinement" else {},
        )
    return protocol.decode_frame(
        worker.encode(kind + "_request", body),
        sender=protocol.FrameSender.WORKER,
        binding=binding,
        expected_sequence=ordinal,
    )


@pytest.mark.asyncio
async def test_all_channel_recording_keeps_host_evidence_out_of_external_playback(
    run_store, tmp_path
):
    runs, registration, _ = run_store
    binding = protocol.ProtocolBinding.from_registration(registration)
    path = [{"grain": "root", "key": registration.run_id.value}]
    worker = protocol.FrameEncoder(sender=protocol.FrameSender.WORKER, binding=binding)
    writer = PacketWriter()
    channel = _HostChannel(binding=binding, reader=asyncio.StreamReader(), writer=writer)

    async def model(request):
        return ModelTransportResponse(text='{"answer":42}', route={"model": "fixture"})

    model_broker = ScopedModelBroker(model, {("root",): "root"})
    order = ("learning", "model", "refinement", "experiment", "model")
    for ordinal, kind in enumerate(order):
        frame = request_frame(binding, worker, kind, path, ordinal)
        arguments = dict(run_store=runs, registration=registration, channel=channel, frame=frame)
        if kind == "model":
            await broker_model_request(**arguments, model_broker=model_broker)
        else:
            await HANDLERS[kind](**arguments, session=SuppliedSession(kind))

    recording = read_recording(runs, registration.run_id)
    assert [row["kind"] for row in recording["exchanges"]] == list(order)
    assert recording["gaps"] == []
    summary = recording_summary(recording)
    assert summary["exchange_counts"] == {
        "model": 2, "http": 0, "learning": 1, "refinement": 1, "experiment": 1,
    }
    assert "exchanges" not in summary
    assert summary["host_state_exchange_count"] == 1
    events = runs.read_committed_prefix(registration.run_id)
    for exchange in recording["exchanges"]:
        requested = events[exchange["request_sequence"]]
        responded = events[exchange["response_sequence"]]
        assert requested.sequence < responded.sequence
        assert exchange["request_event_ref"]["content_hash"] == requested.event_hash.value
        assert exchange["response_event_ref"]["content_hash"] == responded.event_hash.value
        if exchange["kind"] != "model":
            assert exchange["request_hash"] == digest_record(exchange["request"]).value
            assert exchange["response_hash"] == digest_record(exchange["response"]).value
    assert len(writer.packets) == len(order)

    selected = recording["exchanges"][2]
    assert selected["session_state"] == {"fixture_only": True, "channel": "refinement"}
    assert "session_state" not in selected["response"]
    prefix = read_recording(runs, registration.run_id, through_event_ref=selected["request_event_ref"])
    assert [row["kind"] for row in prefix["exchanges"]] == ["learning", "model"]
    assert len(prefix["gaps"]) == 1
    assert prefix["gaps"][0]["kind"] == "response_not_committed"
    assert prefix["gaps"][0]["channel"] == selected["kind"]
    assert prefix["gaps"][0]["event_ref"] == selected["request_event_ref"]

    target = OpaqueId.mint("run", "recorded-input-experiment").value
    cursor = RecordingCursor(recording, registration.run_id.value, target)
    target_path = [{"grain": "root", "key": target}]
    for _ in range(2):
        assert cursor.take("model", REQUEST, target_path)["text"] == '{"answer":42}'
    report = cursor.report()
    assert report["status"] == "matched"
    assert report["unused_response_count"] == 0
    assert report["non_reused_exchange_counts"] == dict.fromkeys(HANDLERS, 1)
    assert len(report["reused_responses"]) == 2
    with pytest.raises(ReplayDivergence, match="unsupported_replay_channel"):
        cursor.take("refinement", selected["request"], target_path)

    with DuetStore(tmp_path / "recordings.db") as artifacts:
        owner = registration.duet_id.value
        artifacts.create_duet(duet_id=owner, identity={}, policy={}, state="specifying")
        saved = save_recording(artifacts, runs, registration.run_id.value)
        assert load_recording(artifacts, runs, saved, owner)[1] == recording
        legacy = read_recording(runs, registration.run_id, projection_version=1)
        historical = deepcopy(recording)
        historical["schema_version"] = 1
        historical["exchanges"] = [
            {key: value for key, value in row.items() if key != "response_sequence"}
            for row in historical["exchanges"] if row["kind"] == "model"
        ]
        historical.pop("recording_id")
        historical.pop("terminal_evidence_available")
        assert legacy["recording_id"] == content_id("run_recording", historical).value
        selector = {key: legacy[key] for key in (
            "recording_id", "registration_ref", "through_event_ref", "selected_episode_ids",
        )}
        legacy_ref = put_data(artifacts, owner, "recording", selector)
        loaded = load_recording(artifacts, runs, legacy_ref, owner)[1]
        assert loaded == legacy
        assert [row["kind"] for row in loaded["exchanges"]] == ["model", "model"]
        assert loaded["recording_id"] != recording["recording_id"]
        assert any("omits host exchanges" in item for item in recording_summary(loaded)["limitations"])


@pytest.mark.parametrize("kind", tuple(HANDLERS))
@pytest.mark.parametrize("fault", (
    "missing_content", "missing_hashes", "request_digest", "response_digest",
    "path", "episode", "response_id",
))
def test_host_pairing_distinguishes_missing_evidence_from_corruption(run_store, kind, fault):
    runs, registration, _ = run_store
    binding = protocol.ProtocolBinding.from_registration(registration)
    path = [{"grain": "root", "key": registration.run_id.value}]
    frame = request_frame(
        binding, protocol.FrameEncoder(sender=protocol.FrameSender.WORKER, binding=binding),
        kind, path, 0,
    )
    body = protocol._thaw_json(frame.body)
    request = {"operation": body["operation"], "payload": body["payload"]}
    before = {**body, "request": request, "request_hash": digest_record(request).value}
    response = {"observed": "fixture"}
    after = {
        "request_id": body["request_id"], "request_hash": before["request_hash"],
        "response": response, "response_hash": digest_record(response).value,
    }
    changed_hash = digest_record({"different": True}).value
    mutations = {
        "missing_content": lambda: before.pop("request"),
        "missing_hashes": lambda: (
            before.pop("request_hash"), after.pop("request_hash"), after.pop("response_hash"),
        ),
        "request_digest": lambda: (
            before.update(request_hash=changed_hash), after.update(request_hash=changed_hash),
        ),
        "response_digest": lambda: after.update(response_hash=changed_hash),
        "path": lambda: before.update(episode_path=[{"grain": "root", "key": "other"}]),
        "episode": lambda: None,
        "response_id": lambda: after.update(request_id=OpaqueId.mint("request", "other").value),
    }
    mutations[fault]()
    episode_id = OpaqueId(body["episode_id"])
    runs.append_event(
        run_id=registration.run_id, origin=RunEventOrigin.WORKER, sender_sequence=0,
        kind=RunEventKind(kind + "_requested"), episode_id=episode_id, payload=before,
    )
    runs.append_event(
        run_id=registration.run_id, origin=RunEventOrigin.HOST, sender_sequence=0,
        kind=RunEventKind(kind + "_responded"),
        episode_id=OpaqueId.mint("episode", "other") if fault == "episode" else episode_id,
        payload=after,
    )
    if fault.startswith("missing_"):
        recording = read_recording(runs, registration.run_id)
        assert recording["exchanges"] == []
        assert recording["gaps"][0]["kind"] == "recording_content_missing"
        assert recording["gaps"][0]["channel"] == kind
        assert recording["gaps"][0]["missing_fields"]
        assert not any(recording_summary(recording)["exchange_counts"].values())
        cursor = RecordingCursor(recording, registration.run_id.value, registration.run_id.value)
        assert cursor.report()["non_reused_exchange_gaps"] == recording["gaps"]
    else:
        expected = {
            "request_digest": "committed digest", "response_digest": "committed digest",
            "path": "Episode identity", "episode": "request context",
            "response_id": "no preceding request",
        }
        with pytest.raises(ValueError, match=expected[fault]):
            read_recording(runs, registration.run_id)
