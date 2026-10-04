"""A worker's frozen MODEL_REQUEST body must reach the host broker as plain
JSON (issue #21): the decoder turns lists into tuples for hashing, and the
broker contract requires a two-item ``list`` of messages."""

from __future__ import annotations

import asyncio

import pytest

from agent.episode_contracts import OpaqueId
from episode_runtime import broker, protocol
from episode_runtime.contracts import RunEventOrigin, RunTerminalStatus
from episode_runtime.executor import _HostChannel
from episode_runtime.exchanges import broker_model_request
from episode_runtime.testing.recordings import read_recording
from llm_call_library import ModelTransportResponse

REQUEST = {
    "task": "episode_structured_json_fast",
    "model_type": "reasoning",
    "messages": [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "usr"},
    ],
    "temperature": 0.0,
    "max_tokens": 128,
    "timeout": 30,
    "reasoning_config": None,
    "main_runtime": None,
}


def test_frozen_request_is_rejected_until_thawed() -> None:
    frozen = protocol._freeze_json(REQUEST, "request")
    assert isinstance(frozen["messages"], tuple)
    try:
        broker.admit_model_request(frozen)
    except broker.ModelBrokerError:
        pass
    else:  # pragma: no cover - the premise of the regression
        raise AssertionError("frozen request unexpectedly admitted")
    admitted = broker.admit_model_request(protocol._thaw_json(frozen))
    assert admitted.task == REQUEST["task"]


@pytest.mark.asyncio
@pytest.mark.parametrize("publication_fails", [False, True])
async def test_executor_thaws_and_commits_the_exact_exchange(run_store, publication_fails):
    """Real frame admission/broker/journal; not a confinement or live-model test."""
    store, registration, _ = run_store
    binding = protocol.ProtocolBinding.from_registration(registration)
    path = [{"grain": "inquiry", "key": "root"}]
    worker = protocol.FrameEncoder(sender=protocol.FrameSender.WORKER, binding=binding)
    packet = worker.encode(
        protocol.WorkerFrameType.MODEL_REQUEST.value,
        {
            "model_request_id": OpaqueId.mint("model_request", "thaw-test").value,
            "episode_id": protocol.episode_id_for_path(registration.run_id, path).value,
            "episode_path": path,
            "request": REQUEST,
        },
    )
    frame = protocol.decode_frame(
        packet, sender=protocol.FrameSender.WORKER, binding=binding, expected_sequence=0
    )
    response = ModelTransportResponse(text='{"answer":42}', route={"model": "test"})
    calls = []

    async def transport(request):
        calls.append(request)
        return response

    published = []

    class ResponseWriter:
        def write(self, packet):
            sent = protocol.decode_frame(
                packet,
                sender=protocol.FrameSender.HOST,
                binding=binding,
                expected_sequence=0,
            )
            # The real channel must not expose bytes before their durable reply.
            committed = read_recording(store, registration.run_id)["exchanges"]
            assert len(committed) == 1
            assert committed[0]["response"] == protocol._thaw_json(sent.body["response"])
            published.append(sent)

        async def drain(self):
            if publication_fails:
                raise BrokenPipeError("worker disconnected after response commit")

    channel = _HostChannel(
        binding=binding, reader=asyncio.StreamReader(), writer=ResponseWriter()
    )
    exchange_call = broker_model_request(
        run_store=store,
        registration=registration,
        channel=channel,
        frame=frame,
        model_broker=broker.ScopedModelBroker(
            transport, episode_paths={("inquiry",): "inquiry"}
        ),
    )
    if publication_fails:
        with pytest.raises(BrokenPipeError):
            await exchange_call
    else:
        await exchange_call
    assert len(published) == 1
    assert broker.model_request_record(calls[0]) == REQUEST
    recording = read_recording(store, registration.run_id)
    assert recording["source_terminal_status"] is None
    assert recording["gaps"] == []
    exchange = recording["exchanges"][0]
    assert exchange["request"] == REQUEST
    assert exchange["episode_path"] == path
    assert exchange["response"] == broker.model_response_record(response)

    # A prefix ending after the request must not manufacture its later response.
    prefix = read_recording(
        store, registration.run_id, through_event_ref=exchange["request_event_ref"]
    )
    assert prefix["exchanges"] == []
    assert prefix["gaps"][0]["kind"] == "response_not_committed"

    if publication_fails:
        # A committed reply reserves its sequence even when publication fails.
        # The interruption can still be finalized and retains the exact reply.
        evidence = store.finalize_run(
            run_id=registration.run_id,
            origin=RunEventOrigin.HOST,
            sender_sequence=channel.next_sender_sequence,
            terminal_status=RunTerminalStatus.INTERRUPTED,
            typed_status={"outcome": "interrupted", "reason": "worker disconnected"},
        )
        assert evidence.terminal_status is RunTerminalStatus.INTERRUPTED
        terminal = read_recording(store, registration.run_id)
        assert terminal["source_terminal_status"] == "interrupted"
        assert terminal["exchanges"] == recording["exchanges"]
