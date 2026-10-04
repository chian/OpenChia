"""Reconstruction matching over real frames/brokers/store, not live recovery.

Supplied boundary records and host answers exercise the reconstruction verifier.
They do not establish source determinism, model reasoning or process confinement.
"""

import asyncio
from dataclasses import replace

import pytest

from agent.episode_contracts import OpaqueId
from episode_runtime import protocol
from episode_runtime.broker import ScopedModelBroker
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunTerminalStatus
from episode_runtime.continuation import InterruptedRunRef
from episode_runtime.executor import _HostChannel
from episode_runtime.exchanges import broker_http_request, broker_model_request
from episode_runtime.http_broker import ScopedHttpBroker
from episode_runtime.testing.reconstruction import (
    ReconstructionBoundaryReached,
    ReconstructionCursor,
    ReconstructionError,
)
from episode_runtime.testing.recordings import read_recording
from episode_runtime.testing.reconstruction_host import HostReconstruction
from llm_call_library import ModelTransportResponse
from method_loop.identities import UnitRef
from tests.episode_runtime.test_executor_http_loop import REQUEST as HTTP_REQUEST
from tests.episode_runtime.conftest import claim_store
from tests.episode_runtime.test_model_request_thaw import REQUEST
from tests.episode_runtime.testing.test_host_exchange_recordings import (
    HANDLERS, OPERATIONS, PacketWriter, SuppliedSession,
)


async def recorded_nested_prefix(run_store, *, pending=False, finalize=True):
    runs, registration, _ = run_store
    binding = protocol.ProtocolBinding.from_registration(registration)
    worker = protocol.FrameEncoder(sender=protocol.FrameSender.WORKER, binding=binding)
    channel = _HostChannel(binding=binding, reader=asyncio.StreamReader(), writer=PacketWriter())
    frames, live_calls = [], []
    root = [{"grain": "root", "key": registration.run_id.value}]
    child = [*root, {"grain": "child", "key": "selected"}]

    def frame(kind, body):
        value = protocol.decode_frame(
            worker.encode(kind, body), sender=protocol.FrameSender.WORKER,
            binding=binding, expected_sequence=len(frames),
        )
        frames.append(value)
        return value

    def boundary(kind, path):
        episode_id = protocol.episode_id_for_path(binding.run_id, path)
        started = {
            "episode_path": path,
            "request": {"fixture_boundary": episode_id.value},
            "goal_view": {"goal": "inspect reconstruction ordering"},
            "goal_state_id": "fixture-state", "initial_goal_state_id": "fixture-state",
        }
        completed = {
            "ended_by": "controller", "end_reason": "fixture boundary",
            "units_consumed": 1, "controller_state": {"fixture": True},
        }
        unit = {
            "unit_ref": UnitRef(episode_id.value, 0).as_record(),
            "unit_label": "fixture-unit", "epoch": 0,
            "controller_input": {"fixture_credit": 0},
            "controller_step": {"stop": False},
            "episode_update": None, "goal_result": None,
        }
        payload = {
            RunEventKind.EPISODE_STARTED: started,
            RunEventKind.EPISODE_COMPLETED: completed,
            RunEventKind.UNIT_COMPLETED: unit,
        }[kind]
        value = frame("run_event", {
            "event_kind": kind.value, "episode_id": episode_id.value, "payload": payload,
        })
        runs.append_event(
            run_id=registration.run_id, origin=RunEventOrigin.WORKER,
            sender_sequence=value.sender_sequence, kind=kind,
            episode_id=episode_id, payload=payload,
        )

    async def model(request):
        live_calls.append("model")
        return ModelTransportResponse(text='{"answer":42}', route={})

    async def http(*args, **kwargs):
        raise AssertionError("unapproved HTTP must not reach a transport")

    models = ScopedModelBroker(model, {("root", "child"): "child", ("root",): "root"})
    http_broker = ScopedHttpBroker(policy={}, credentials={}, transport=http, max_frame_bytes=binding.max_frame_bytes)
    boundary(RunEventKind.EPISODE_STARTED, root)
    boundary(RunEventKind.EPISODE_STARTED, child)
    for kind in ("refinement", "model", "learning", "http", "experiment"):
        body = {
            "episode_id": protocol.episode_id_for_path(binding.run_id, child).value,
            "episode_path": child,
        }
        key = kind + "_request_id" if kind in {"model", "http"} else "request_id"
        body[key] = OpaqueId.mint(kind + "_request", f"reconstruction-{len(frames)}").value
        if kind in {"model", "http"}:
            body["request"] = REQUEST if kind == "model" else HTTP_REQUEST
        else:
            body.update(operation=OPERATIONS[kind], payload={})
        value = frame(kind + "_request", body)
        arguments = dict(run_store=runs, registration=registration, channel=channel, frame=value)
        if kind == "model":
            await broker_model_request(**arguments, model_broker=models)
        elif kind == "http":
            await broker_http_request(**arguments, http_broker=http_broker)
        else:
            await HANDLERS[kind](**arguments, session=SuppliedSession(kind))
    boundary(RunEventKind.EPISODE_COMPLETED, child)
    # Identical model input at the parent is not interchangeable with its child.
    parent = frame("model_request", {
        "episode_id": protocol.episode_id_for_path(binding.run_id, root).value,
        "episode_path": root,
        "model_request_id": OpaqueId.mint("model_request", "parent").value,
        "request": REQUEST,
    })
    if pending:
        async def interrupt(request):
            raise asyncio.CancelledError
        models = ScopedModelBroker(interrupt, {("root",): "root"})
    try:
        await broker_model_request(
            run_store=runs, registration=registration, channel=channel,
            frame=parent, model_broker=models,
        )
    except asyncio.CancelledError:
        if not pending:
            raise
    if not pending:
        boundary(RunEventKind.UNIT_COMPLETED, root)
    if finalize:
        runs.finalize_run(
            run_id=registration.run_id, origin=RunEventOrigin.HOST,
            sender_sequence=channel.next_sender_sequence,
            terminal_status=RunTerminalStatus.INTERRUPTED,
            typed_status={"outcome": "interrupted", "reason": "fixture process stopped"},
        )
    return frames, live_calls


@pytest.mark.asyncio
async def test_reconstruction_matches_all_channels_and_nested_boundaries_without_effects(run_store):
    frames, live_calls = await recorded_nested_prefix(run_store)
    runs, registration, _ = run_store
    before = runs.read_audit_log(registration.run_id)
    cursor = ReconstructionCursor(runs, registration.run_id.value)
    recording = read_recording(runs, registration.run_id)
    replies = []
    for frame in frames:
        reply = cursor.accept(frame)
        if reply is not None:
            replies.append(reply)
            assert "session_state" not in reply.body
    assert [protocol._thaw_json(reply.body["response"]) for reply in replies] == [
        exchange["response"] for exchange in recording["exchanges"]
    ]
    assert cursor.prefix_verified
    report = cursor.report()
    assert report["remaining_worker_frames"] == 0
    assert report["expected_active_stack"] == [{
        "episode_id": frames[0].body["episode_id"],
        "episode_path": protocol._thaw_json(frames[0].body["payload"]["episode_path"]),
    }]
    assert report["live_work_authorized"] is False
    assert cursor.host_state["state"] == {"fixture_only": True, "channel": "refinement"}
    with pytest.raises(ReconstructionBoundaryReached, match="not been authorized"):
        cursor.accept(frames[-1])
    assert live_calls == ["model", "model"]
    assert runs.read_audit_log(registration.run_id) == before

    # Drive the same host switch used by the executor. Only source/authority and
    # confinement are supplied here; no new broker receives a historical frame.
    resumed = replace(registration, resume_from=InterruptedRunRef.from_run(runs, registration.run_id))
    claim_store(runs.root, resumed, store=runs)
    gate = HostReconstruction(runs, resumed, {"modules": [{"family": "reasoning"}]})
    channel = _HostChannel(
        binding=protocol.ProtocolBinding.from_registration(resumed),
        reader=asyncio.StreamReader(), writer=PacketWriter(),
    )
    authorizations = []

    async def authorize():
        authorizations.append("supplied authority/stopped-process check")
        return {"fixture_only": True}

    for frame in frames:
        assert await gate.consume(frame, channel, authorize=authorize)
    assert authorizations == ["supplied authority/stopped-process check"]
    assert gate.activated
    assert not await gate.consume(frames[-1], channel, authorize=authorize)
    current = runs.read_committed_prefix(resumed.run_id)
    assert len(current) == 1 and current[0].kind is RunEventKind.RUN_RECONSTRUCTED
    assert current[0].origin is RunEventOrigin.HOST_RECONSTRUCTION
    assert runs.read_audit_log(registration.run_id) == before
    assert live_calls == ["model", "model"]
    runs.finalize_run(
        run_id=resumed.run_id, origin=RunEventOrigin.HOST,
        sender_sequence=channel.next_sender_sequence,
        terminal_status=RunTerminalStatus.INTERRUPTED,
        typed_status={"outcome": "interrupted", "reason": "fixture stopped after reconstruction"},
    )
    again = ReconstructionCursor(runs, resumed.run_id)
    assert again.report()["remaining_worker_frames"] == len(frames)
    assert again.host_state == cursor.host_state
    assert len(again.report()["execution_lineage"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ("order", "child", "request_id", "event", "controller", "pending", "active"))
async def test_reconstruction_rejects_divergence_and_never_falls_back_to_an_earlier_prefix(run_store, fault):
    frames, live_calls = await recorded_nested_prefix(run_store, pending=fault == "pending", finalize=fault != "active")
    runs, registration, _ = run_store
    before = runs.read_committed_prefix(registration.run_id)
    if fault in {"pending", "active"}:
        with pytest.raises(ReconstructionError, match="incomplete exchanges|terminal interruption"):
            ReconstructionCursor(runs, registration.run_id)
        return
    cursor = ReconstructionCursor(runs, registration.run_id)
    for frame in (frames[:-1] if fault == "controller" else frames[:3]):
        cursor.accept(frame)
    expected = frames[-1] if fault == "controller" else frames[3]
    body = protocol._thaw_json(expected.body)
    changes = {
        "order": lambda: frames[4],
        "child": lambda: frames[-2],
        "request_id": lambda: replace(expected, body={**body, "model_request_id": OpaqueId.mint("model_request", "changed").value}),
        "event": lambda: frames[7],
        "controller": lambda: replace(expected, body={**body, "payload": {
            **body["payload"], "controller_input": {"fixture_credit": 1},
        }}),
    }
    with pytest.raises(ReconstructionError, match="reconstruction_diverged"):
        cursor.accept(changes[fault]())
    # A subsequent correct request cannot hide the earlier divergence.
    with pytest.raises(ReconstructionError, match="reconstruction_diverged"):
        cursor.accept(expected)
    assert not cursor.prefix_verified
    assert cursor.report()["live_work_authorized"] is False
    assert live_calls == ["model", "model"]
    assert runs.read_committed_prefix(registration.run_id) == before
