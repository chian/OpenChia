"""Isolated worker entrypoint for one non-resumable Episode Run."""

from __future__ import annotations

from function_library.reasoning_transport import reasoning_transport_scope

import argparse
import asyncio
import inspect
import sys
from types import MappingProxyType
from typing import Mapping, Optional


from agent.duet_contracts import content_id, digest_record
from agent.episode_contracts import OpaqueId, Sha256Digest
from http_call_library import (
    HttpTransportRequest,
    HttpTransportResponse,
    http_transport_scope,
)
from llm_call_library import (
    ModelTransportRequest,
    ModelTransportResponse,
    model_transport_scope,
)

from episode_runtime.broker import (
    admit_model_response,
    model_request_record,
)
from episode_runtime.contracts import (
    InspectedExecutorAttestation,
    RunRegistration,
    RunTerminalStatus,
)
from episode_runtime.http_contracts import (
    http_request_record,
    http_transport_response,
)
from episode_runtime.identity import verify_runtime_identity
from episode_runtime.landlock import apply_landlock_abi7
from episode_runtime.linker import (
    current_runtime_episode_id,
    current_runtime_episode_path,
    prepare_source_package,
)
from episode_runtime.protocol import (
    CancelKind,
    FrameDecoder,
    FrameEncoder,
    FrameSender,
    HostFrameType,
    ProtocolBinding,
    ProtocolError,
    ProtocolFrame,
    WorkerFrameType,
    decode_frame,
)
from episode_runtime.seccomp import apply_seccomp_policy


class WorkerError(RuntimeError):
    """The isolated worker cannot continue the one-shot Run."""


def _failure_status(exc: BaseException) -> Mapping[str, object]:
    message = " ".join(str(exc).replace("\x00", " ").split())[:2048]
    return MappingProxyType(
        {
            "outcome": "failed",
            "failure_type": type(exc).__name__,
            "failure": message or "isolated worker failure",
        }
    )


class _ProtocolChannel:
    def __init__(
        self,
        *,
        binding: ProtocolBinding,
        reader: asyncio.StreamReader,
    ) -> None:
        self.binding = binding
        self.reader = reader
        self.decoder = FrameDecoder(sender=FrameSender.HOST, binding=binding)
        self.encoder = FrameEncoder(sender=FrameSender.WORKER, binding=binding)
        self._send_lock = asyncio.Lock()
        self._receive_lock = asyncio.Lock()
        self._sent_sequence = 0
        self._model_ordinal = 0
        self._http_ordinal = 0
        self._terminal_sent = False
        self._pending_models: dict[str, asyncio.Future[ModelTransportResponse]] = {}
        self._pending_http: dict[str, asyncio.Future[HttpTransportResponse]] = {}
        self._pending_learning: dict[str, asyncio.Future] = {}
        self._learning_ordinal = 0
        self.cancelled: asyncio.Future[CancelKind] = (
            asyncio.get_running_loop().create_future()
        )
        self.terminal_ack: asyncio.Future[ProtocolFrame] = (
            asyncio.get_running_loop().create_future()
        )

    async def receive(self) -> ProtocolFrame:
        async with self._receive_lock:
            try:
                prefix = await self.reader.readexactly(4)
                length = int.from_bytes(prefix, "big")
                if length < 1 or length > self.binding.max_frame_bytes:
                    raise ProtocolError("frame length is outside its admitted bound")
                payload = await self.reader.readexactly(length)
            except asyncio.IncompleteReadError as exc:
                raise ProtocolError("host protocol stream ended inside a frame") from exc
            return self.decoder.decode(prefix + payload)

    async def send(
        self,
        frame_type: str,
        body: Mapping[str, object],
    ) -> ProtocolFrame:
        async with self._send_lock:
            expected = self._sent_sequence
            packet = self.encoder.encode(frame_type, body)
            frame = decode_frame(
                packet,
                sender=FrameSender.WORKER,
                binding=self.binding,
                expected_sequence=expected,
            )
            self._sent_sequence += 1
            stream = sys.stdout.buffer
            offset = 0
            while offset < len(packet):
                written = stream.write(packet[offset:])
                if not isinstance(written, int) or written <= 0:
                    raise ProtocolError("worker protocol stream rejected a frame")
                offset += written
            stream.flush()
            return frame

    async def event(
        self,
        kind: object,
        episode_id: OpaqueId,
        payload: Mapping[str, object],
    ) -> None:
        await self.send(
            WorkerFrameType.RUN_EVENT.value,
            {
                "episode_id": episode_id.value,
                "event_kind": kind.value,
                "payload": payload,
            },
        )

    async def terminal(
        self,
        *,
        terminal_status: RunTerminalStatus,
        typed_status: Mapping[str, object],
    ) -> None:
        if self._terminal_sent:
            raise ProtocolError("worker attempted to emit more than one terminal frame")
        await self.send(
            WorkerFrameType.TERMINAL.value,
            {
                "terminal_status": terminal_status.value,
                "typed_status": typed_status,
            },
        )
        self._terminal_sent = True

    async def request_model(
        self,
        request: ModelTransportRequest,
        *,
        episode_id: OpaqueId,
        episode_path: list[dict[str, str]],
    ) -> ModelTransportResponse:
        request_record = model_request_record(request)
        request_id = content_id(
            "model_request",
            {
                "run_id": self.binding.run_id.value,
                "registration_hash": self.binding.registration_hash.value,
                "episode_id": episode_id.value,
                "ordinal": self._model_ordinal,
                "request_hash": digest_record(request_record).value,
            },
        )
        self._model_ordinal += 1
        future: asyncio.Future[ModelTransportResponse] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending_models[request_id.value] = future
        try:
            await self.send(
                WorkerFrameType.MODEL_REQUEST.value,
                {
                    "model_request_id": request_id.value,
                    "episode_id": episode_id.value,
                    "episode_path": episode_path,
                    "request": request_record,
                },
            )
            return await future
        finally:
            self._pending_models.pop(request_id.value, None)

    async def request_http(
        self,
        request_record: Mapping[str, object],
        *,
        episode_id: OpaqueId,
        episode_path: list[dict[str, str]],
    ) -> HttpTransportResponse:
        request_id = content_id(
            "http_request",
            {
                "run_id": self.binding.run_id.value,
                "registration_hash": self.binding.registration_hash.value,
                "episode_id": episode_id.value,
                "ordinal": self._http_ordinal,
                "request_hash": digest_record(request_record).value,
            },
        )
        self._http_ordinal += 1
        future: asyncio.Future[HttpTransportResponse] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending_http[request_id.value] = future
        try:
            await self.send(
                WorkerFrameType.HTTP_REQUEST.value,
                {
                    "http_request_id": request_id.value,
                    "episode_id": episode_id.value,
                    "episode_path": episode_path,
                    "request": request_record,
                },
            )
            return await future
        finally:
            self._pending_http.pop(request_id.value, None)

    async def receive_loop(self) -> None:
        while True:
            frame = await self.receive()
            if frame.frame_type == HostFrameType.LEARNING_RESPONSE.value:
                future = self._pending_learning.get(frame.body["request_id"])
                if future is None or future.done():
                    raise ProtocolError("learning response has no outstanding request")
                future.set_result(frame.body["response"])
                continue
            if frame.frame_type == HostFrameType.MODEL_RESPONSE.value:
                request_id = frame.body["model_request_id"]
                future = self._pending_models.get(str(request_id))
                if future is None or future.done():
                    raise ProtocolError("model response has no outstanding request")
                future.set_result(admit_model_response(frame.body["response"]))
                continue
            if frame.frame_type == HostFrameType.HTTP_RESPONSE.value:
                request_id = frame.body["http_request_id"]
                future = self._pending_http.get(str(request_id))
                if future is None or future.done():
                    raise ProtocolError("http response has no outstanding request")
                future.set_result(http_transport_response(frame.body["response"]))
                continue
            if frame.frame_type == HostFrameType.CANCEL.value:
                if self.cancelled.done():
                    raise ProtocolError("host sent more than one cancel frame")
                self.cancelled.set_result(CancelKind(frame.body["cancel_kind"]))
                continue
            if frame.frame_type == HostFrameType.TERMINAL_ACK.value:
                if not self._terminal_sent:
                    raise ProtocolError(
                        "terminal_ack arrived before the worker entered ACK phase"
                    )
                if self.terminal_ack.done():
                    raise ProtocolError("host sent more than one terminal_ack")
                self.terminal_ack.set_result(frame)
                return
            raise ProtocolError(
                f"host frame {frame.frame_type!r} is invalid after start"
            )

    async def request_learning(self, operation, payload):
        from .linker import current_runtime_episode_id
        episode_id = current_runtime_episode_id()
        request_id = content_id("learning_request", {"run_id": self.binding.run_id.value,
            "episode_id": episode_id.value, "ordinal": self._learning_ordinal})
        self._learning_ordinal += 1
        future = asyncio.get_running_loop().create_future()
        self._pending_learning[request_id.value] = future
        try:
            await self.send(WorkerFrameType.LEARNING_REQUEST.value, {
                "request_id": request_id.value, "episode_id": episode_id.value,
                "operation": operation, "payload": payload})
            return await future
        finally:
            self._pending_learning.pop(request_id.value, None)


class _WorkerModelTransport:
    def __init__(self, channel: _ProtocolChannel) -> None:
        self.channel = channel

    async def __call__(
        self,
        request: ModelTransportRequest,
    ) -> ModelTransportResponse:
        if not isinstance(request, ModelTransportRequest):
            raise TypeError("request must be a ModelTransportRequest")
        if request.main_runtime is not None:
            raise WorkerError("isolated worker cannot send host runtime routing state")
        return await self.channel.request_model(
            request,
            episode_id=current_runtime_episode_id(),
            episode_path=current_runtime_episode_path(),
        )


class _WorkerHttpTransport:
    def __init__(self, channel: _ProtocolChannel) -> None:
        self.channel = channel

    async def __call__(
        self,
        request: HttpTransportRequest,
    ) -> HttpTransportResponse:
        if not isinstance(request, HttpTransportRequest):
            raise TypeError("request must be an HttpTransportRequest")
        return await self.channel.request_http(
            http_request_record(request),
            episode_id=current_runtime_episode_id(),
            episode_path=current_runtime_episode_path(),
        )


async def _stream_reader() -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_running_loop().connect_read_pipe(
        lambda: protocol,
        sys.stdin.buffer,
    )
    return reader


async def _run_worker(arguments: argparse.Namespace) -> int:
    binding = ProtocolBinding(
        run_id=OpaqueId(arguments.run_id),
        registration_hash=Sha256Digest(arguments.registration_hash),
        manifest_id=OpaqueId(arguments.manifest_id),
        max_frame_bytes=arguments.max_frame_bytes,
    )
    channel = _ProtocolChannel(binding=binding, reader=await _stream_reader())
    initialize = await channel.receive()
    if initialize.frame_type != HostFrameType.INITIALIZE.value:
        raise ProtocolError("the first host frame must be initialize")
    registration = RunRegistration.from_record(initialize.body["registration"])
    executor_instance_id = OpaqueId(initialize.body["executor_instance_id"])
    if (
        registration.run_id != binding.run_id
        or registration.registration_hash != binding.registration_hash
        or registration.manifest_id != binding.manifest_id
    ):
        raise WorkerError("initialize registration differs from worker binding")

    verify_runtime_identity(
        registration.runtime_identity,
        runtime_source_package=arguments.runtime_source_package,
    )
    prepared = prepare_source_package(registration, arguments.source_package)
    seccomp_receipt = apply_seccomp_policy(
        run_id=registration.run_id,
        executor_instance_id=executor_instance_id,
    )
    landlock_receipt = apply_landlock_abi7(
        run_id=registration.run_id,
        executor_instance_id=executor_instance_id,
    )
    activated = prepared.activate()
    await channel.send(
        WorkerFrameType.READY.value,
        {
            "runtime_id": registration.runtime_identity.runtime_id.value,
            "runtime_hash": registration.runtime_identity.content_hash.value,
            "landlock_receipt": landlock_receipt.as_record(),
            "seccomp_receipt": seccomp_receipt.as_record(),
        },
    )
    start = await channel.receive()
    if start.frame_type != HostFrameType.START.value:
        raise ProtocolError("ready must be followed by one start frame")
    attestation = InspectedExecutorAttestation.from_record(
        start.body["executor_attestation"]
    )
    attestation.validate_against(registration)
    if (
        attestation.executor_instance_id != executor_instance_id
        or attestation.landlock_receipt != landlock_receipt
        or attestation.seccomp_receipt != seccomp_receipt
    ):
        raise WorkerError("start attestation differs from the live worker")

    linked = activated.link(event_sink=channel.event, collaborators={})
    model_transport = _WorkerModelTransport(channel)
    http_transport = _WorkerHttpTransport(channel)
    receiver = asyncio.create_task(channel.receive_loop())
    with model_transport_scope(model_transport), http_transport_scope(
        http_transport
    ), reasoning_transport_scope(channel.request_learning):
        run_task = asyncio.create_task(linked.run())
        done, _ = await asyncio.wait(
            {run_task, receiver, channel.cancelled},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if channel.cancelled in done:
            cancel_kind = channel.cancelled.result()
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass
            terminal_status = RunTerminalStatus.CANCELLED
            typed_status: Mapping[str, object] = MappingProxyType(
                {"outcome": "cancelled", "cancel_kind": cancel_kind.value}
            )
        elif receiver in done:
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass
            exception = receiver.exception()
            if exception is None:
                exception = WorkerError("host protocol ended before the Run")
            terminal_status = RunTerminalStatus.FAILED
            typed_status = _failure_status(exception)
        else:
            try:
                typed_status = await run_task
                terminal_status = RunTerminalStatus(typed_status["outcome"])
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                typed_status = _failure_status(exc)
                terminal_status = RunTerminalStatus.FAILED

    await channel.terminal(
        terminal_status=terminal_status,
        typed_status=typed_status,
    )
    if receiver.done():
        if receiver.exception() is not None:
            raise receiver.exception()  # type: ignore[misc]
        if not channel.terminal_ack.done():
            raise WorkerError("host protocol ended before terminal acknowledgement")
    else:
        await channel.terminal_ack
        await receiver
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openchia-episode-worker")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--registration-hash", required=True)
    parser.add_argument("--manifest-id", required=True)
    parser.add_argument("--max-frame-bytes", required=True, type=int)
    parser.add_argument("--source-package", required=True)
    parser.add_argument("--runtime-source-package", required=True)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        return asyncio.run(_run_worker(arguments))
    except KeyboardInterrupt:
        return 130
    except BaseException as exc:
        message = " ".join(str(exc).replace("\x00", " ").split())[:2048]
        sys.stderr.write(f"isolated worker failed: {type(exc).__name__}: {message}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["WorkerError", "main"]
