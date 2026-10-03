"""Canonical length-prefixed host/worker protocol for one admitted Run."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import struct
from types import MappingProxyType
from typing import Any, BinaryIO, Mapping

from agent.episode_contracts import OpaqueId, Sha256Digest
from method_loop.identities import EpisodeRef
from function_library.refinement_contract import OPERATIONS as REFINEMENT_OPERATIONS

from .contracts import (
    DEFAULT_MAX_FRAME_BYTES,
    MAX_MAX_FRAME_BYTES,
    TERMINAL_EVENT_KINDS,
    InspectedExecutorAttestation,
    RunEventKind,
    RunRegistration,
    RunTerminalStatus,
)
from .http_contracts import (
    HttpBrokerError,
    admit_http_request,
    admit_http_response,
)
from .landlock import LandlockPolicyReceipt
from .seccomp import SeccompPolicyReceipt


_LENGTH = struct.Struct(">I")


class ProtocolError(ValueError):
    """A wire frame violated the closed runtime protocol."""


class FrameSender(str, Enum):
    HOST = "host"
    WORKER = "worker"


class HostFrameType(str, Enum):
    INITIALIZE = "initialize"
    START = "start"
    MODEL_RESPONSE = "model_response"
    HTTP_RESPONSE = "http_response"
    LEARNING_RESPONSE = "learning_response"
    REFINEMENT_RESPONSE = "refinement_response"
    TERMINAL_ACK = "terminal_ack"
    CANCEL = "cancel"


class WorkerFrameType(str, Enum):
    READY = "ready"
    MODEL_REQUEST = "model_request"
    HTTP_REQUEST = "http_request"
    LEARNING_REQUEST = "learning_request"
    REFINEMENT_REQUEST = "refinement_request"
    RUN_EVENT = "run_event"
    TERMINAL = "terminal"


class CancelKind(str, Enum):
    HUMAN_CANCELLED = "human_cancelled"
    HOST_SHUTDOWN = "host_shutdown"
    PROTOCOL_VIOLATION = "protocol_violation"


_TYPES_BY_SENDER: Mapping[FrameSender, frozenset[str]] = {
    FrameSender.HOST: frozenset(item.value for item in HostFrameType),
    FrameSender.WORKER: frozenset(item.value for item in WorkerFrameType),
}


def _record(
    value: object,
    name: str,
    expected: set[str],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ProtocolError(
            f"{name} must contain exactly {sorted(expected)!r}"
        )
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProtocolError(f"{name} must be a non-negative integer")
    return value


def _freeze_json(value: object, name: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ProtocolError(f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        keys = tuple(value)
        if any(not isinstance(key, str) or not key for key in keys):
            raise ProtocolError(f"{name} keys must be non-empty strings")
        return MappingProxyType(
            {
                key: _freeze_json(value[key], f"{name}.{key}")
                for key in sorted(keys)
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(
            _freeze_json(item, f"{name}[{index}]")
            for index, item in enumerate(value)
        )
    raise ProtocolError(f"{name} must contain only JSON-shaped values")


def _json_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProtocolError(f"{name} must be a JSON object")
    frozen = _freeze_json(value, name)
    if not isinstance(frozen, Mapping):
        raise AssertionError("mapping freeze changed the top-level shape")
    return frozen


def _episode_path(value: object) -> tuple[Mapping[str, str], ...]:
    if not isinstance(value, (tuple, list)) or not value:
        raise ProtocolError("episode_path must be a non-empty list")
    segments: list[Mapping[str, str]] = []
    for index, item in enumerate(value):
        segment = _record(item, f"episode_path[{index}]", {"grain", "key"})
        grain = segment["grain"]
        key = segment["key"]
        if (
            not isinstance(grain, str)
            or not grain
            or not isinstance(key, str)
            or not key
        ):
            raise ProtocolError(
                "episode_path segments must carry non-empty grain and key text"
            )
        segments.append(MappingProxyType({"grain": grain, "key": key}))
    return tuple(segments)


def episode_id_for_path(
    run_id: OpaqueId,
    episode_path: object,
) -> OpaqueId:
    """Recompute the runtime Episode identity the linker gives ``episode_path``."""

    if not isinstance(run_id, OpaqueId):
        raise TypeError("run_id must be an OpaqueId")
    segments = _episode_path(episode_path)
    return OpaqueId(
        EpisodeRef(
            run_id=run_id.value,
            path=tuple((item["grain"], item["key"]) for item in segments),
        ).episode_id
    )


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(
        _thaw_json(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ProtocolError(f"non-finite JSON number {value!r} is prohibited")


def _parse_canonical(payload: bytes) -> Mapping[str, object]:
    try:
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("frame payload is not strict UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise ProtocolError("frame payload must be a JSON object")
    frozen = _json_mapping(value, "frame")
    if _canonical_bytes(frozen) != payload:
        raise ProtocolError("frame JSON is not in canonical encoding")
    return frozen


@dataclass(frozen=True)
class ProtocolBinding:
    run_id: OpaqueId
    registration_hash: Sha256Digest
    manifest_id: OpaqueId
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, OpaqueId):
            raise TypeError("run_id must be an OpaqueId")
        if not isinstance(self.registration_hash, Sha256Digest):
            raise TypeError("registration_hash must be a Sha256Digest")
        if not isinstance(self.manifest_id, OpaqueId):
            raise TypeError("manifest_id must be an OpaqueId")
        if (
            isinstance(self.max_frame_bytes, bool)
            or not isinstance(self.max_frame_bytes, int)
            or self.max_frame_bytes < 1024
            or self.max_frame_bytes > MAX_MAX_FRAME_BYTES
        ):
            raise ValueError("max_frame_bytes is outside the admitted range")

    @classmethod
    def from_registration(
        cls,
        registration: RunRegistration,
    ) -> "ProtocolBinding":
        if not isinstance(registration, RunRegistration):
            raise TypeError("registration must be a RunRegistration")
        return cls(
            run_id=registration.run_id,
            registration_hash=registration.registration_hash,
            manifest_id=registration.manifest_id,
            max_frame_bytes=registration.runtime_policy.max_frame_bytes,
        )


def _validate_body(
    *,
    sender: FrameSender,
    frame_type: str,
    body: object,
    binding: ProtocolBinding,
) -> Mapping[str, object]:
    if sender is FrameSender.HOST and frame_type == HostFrameType.REFINEMENT_RESPONSE.value:
        record = _record(body, "refinement response", {"request_id", "response"})
        return MappingProxyType({
            "request_id": OpaqueId(record["request_id"]).value,
            "response": _json_mapping(record["response"], "refinement response"),
        })
    if sender is FrameSender.WORKER and frame_type == WorkerFrameType.REFINEMENT_REQUEST.value:
        record = _record(body, "refinement request", {
            "request_id", "episode_id", "episode_path", "operation", "payload",
        })
        operation = record["operation"]
        if not isinstance(operation, str) or operation not in REFINEMENT_OPERATIONS:
            raise ProtocolError("unknown refinement operation")
        path = _episode_path(record["episode_path"])
        episode_id = episode_id_for_path(binding.run_id, path)
        if episode_id.value != record["episode_id"]:
            raise ProtocolError("refinement caller differs from its runtime path")
        return MappingProxyType({
            "request_id": OpaqueId(record["request_id"]).value,
            "episode_id": episode_id.value,
            "episode_path": path,
            "operation": operation,
            "payload": _json_mapping(record["payload"], "refinement payload"),
        })
    if sender is FrameSender.HOST and frame_type == HostFrameType.LEARNING_RESPONSE.value:
        record = _record(body, "learning response", {"request_id", "response"})
        return MappingProxyType({"request_id": OpaqueId(record["request_id"]).value,
                                 "response": _json_mapping(record["response"], "learning response")})
    if sender is FrameSender.WORKER and frame_type == WorkerFrameType.LEARNING_REQUEST.value:
        record = _record(body, "learning request", {"request_id", "episode_id", "operation", "payload"})
        if record["operation"] not in {"retrieve", "select", "submit"}:
            raise ProtocolError("unknown learning operation")
        return MappingProxyType({"request_id": OpaqueId(record["request_id"]).value,
                                 "episode_id": OpaqueId(record["episode_id"]).value,
                                 "operation": record["operation"],
                                 "payload": _json_mapping(record["payload"], "learning payload")})
    if sender is FrameSender.HOST:
        if frame_type == HostFrameType.INITIALIZE.value:
            record = _record(
                body,
                "initialize body",
                {"registration", "executor_instance_id"},
            )
            # Frames arrive frozen (arrays as tuples); the contract parsers want plain JSON.
            registration = RunRegistration.from_record(
                _thaw_json(record["registration"])
            )
            if (
                registration.run_id != binding.run_id
                or registration.registration_hash
                != binding.registration_hash
                or registration.manifest_id != binding.manifest_id
            ):
                raise ProtocolError("initialize carries another registration")
            executor_id = OpaqueId(record["executor_instance_id"])
            return MappingProxyType(
                {
                    "executor_instance_id": executor_id.value,
                    "registration": registration.as_record(),
                }
            )
        if frame_type == HostFrameType.START.value:
            record = _record(
                body,
                "start body",
                {"executor_attestation"},
            )
            attestation = InspectedExecutorAttestation.from_record(
                _thaw_json(record["executor_attestation"])
            )
            if (
                attestation.run_id != binding.run_id
                or attestation.registration_hash != binding.registration_hash
                or attestation.manifest_id != binding.manifest_id
            ):
                raise ProtocolError("start carries another executor attestation")
            return MappingProxyType(
                {"executor_attestation": attestation.as_record()}
            )
        if frame_type == HostFrameType.MODEL_RESPONSE.value:
            record = _record(
                body,
                "model_response body",
                {"model_request_id", "response"},
            )
            request_id = OpaqueId(record["model_request_id"])
            response = _json_mapping(record["response"], "model response")
            return MappingProxyType(
                {
                    "model_request_id": request_id.value,
                    "response": response,
                }
            )
        if frame_type == HostFrameType.HTTP_RESPONSE.value:
            record = _record(
                body,
                "http_response body",
                {"http_request_id", "response"},
            )
            request_id = OpaqueId(record["http_request_id"])
            try:
                response = admit_http_response(record["response"])
            except HttpBrokerError as exc:
                raise ProtocolError(f"http response: {exc}") from exc
            return MappingProxyType(
                {
                    "http_request_id": request_id.value,
                    "response": _json_mapping(response, "http response"),
                }
            )
        if frame_type == HostFrameType.TERMINAL_ACK.value:
            record = _record(
                body,
                "terminal_ack body",
                {"evidence_id", "evidence_hash"},
            )
            evidence_id = OpaqueId(record["evidence_id"])
            evidence_hash = Sha256Digest(record["evidence_hash"])
            return MappingProxyType(
                {
                    "evidence_id": evidence_id.value,
                    "evidence_hash": evidence_hash.value,
                }
            )
        if frame_type == HostFrameType.CANCEL.value:
            record = _record(body, "cancel body", {"cancel_kind"})
            try:
                cancel_kind = CancelKind(record["cancel_kind"])
            except (TypeError, ValueError) as exc:
                raise ProtocolError("cancel_kind is unknown") from exc
            return MappingProxyType({"cancel_kind": cancel_kind.value})
    else:
        if frame_type == WorkerFrameType.READY.value:
            record = _record(
                body,
                "ready body",
                {
                    "runtime_id",
                    "runtime_hash",
                    "landlock_receipt",
                    "seccomp_receipt",
                },
            )
            runtime_id = OpaqueId(record["runtime_id"])
            runtime_hash = Sha256Digest(record["runtime_hash"])
            receipt = LandlockPolicyReceipt.from_record(
                record["landlock_receipt"]
            )
            seccomp_receipt = SeccompPolicyReceipt.from_record(
                record["seccomp_receipt"]
            )
            if (
                receipt.run_id != binding.run_id
                or seccomp_receipt.run_id != binding.run_id
                or seccomp_receipt.executor_instance_id
                != receipt.executor_instance_id
            ):
                raise ProtocolError("ready receipt belongs to another Run")
            return MappingProxyType(
                {
                    "runtime_id": runtime_id.value,
                    "runtime_hash": runtime_hash.value,
                    "landlock_receipt": receipt.as_record(),
                    "seccomp_receipt": seccomp_receipt.as_record(),
                }
            )
        if frame_type == WorkerFrameType.MODEL_REQUEST.value:
            record = _record(
                body,
                "model_request body",
                {"model_request_id", "episode_id", "request"},
            )
            request_id = OpaqueId(record["model_request_id"])
            episode_id = OpaqueId(record["episode_id"])
            request = _json_mapping(record["request"], "model request")
            return MappingProxyType(
                {
                    "model_request_id": request_id.value,
                    "episode_id": episode_id.value,
                    "request": request,
                }
            )
        if frame_type == WorkerFrameType.HTTP_REQUEST.value:
            record = _record(
                body,
                "http_request body",
                {"http_request_id", "episode_id", "episode_path", "request"},
            )
            request_id = OpaqueId(record["http_request_id"])
            episode_id = OpaqueId(record["episode_id"])
            episode_path = _episode_path(record["episode_path"])
            if episode_id_for_path(binding.run_id, episode_path) != episode_id:
                raise ProtocolError(
                    "http_request episode_path does not identify its episode_id"
                )
            try:
                request = admit_http_request(record["request"])
            except HttpBrokerError as exc:
                raise ProtocolError(f"http request: {exc}") from exc
            return MappingProxyType(
                {
                    "http_request_id": request_id.value,
                    "episode_id": episode_id.value,
                    "episode_path": episode_path,
                    "request": _json_mapping(request, "http request"),
                }
            )
        if frame_type == WorkerFrameType.RUN_EVENT.value:
            record = _record(
                body,
                "run_event body",
                {"episode_id", "event_kind", "payload"},
            )
            episode_id = (
                None
                if record["episode_id"] is None
                else OpaqueId(record["episode_id"])
            )
            try:
                event_kind = RunEventKind(record["event_kind"])
            except (TypeError, ValueError) as exc:
                raise ProtocolError("run_event kind is unknown") from exc
            if event_kind in TERMINAL_EVENT_KINDS:
                raise ProtocolError("terminal events use the terminal frame")
            payload = _json_mapping(record["payload"], "run event payload")
            return MappingProxyType(
                {
                    "episode_id": (
                        None if episode_id is None else episode_id.value
                    ),
                    "event_kind": event_kind.value,
                    "payload": payload,
                }
            )
        if frame_type == WorkerFrameType.TERMINAL.value:
            record = _record(
                body,
                "terminal body",
                {"terminal_status", "typed_status"},
            )
            try:
                terminal_status = RunTerminalStatus(
                    record["terminal_status"]
                )
            except (TypeError, ValueError) as exc:
                raise ProtocolError("terminal status is unknown") from exc
            typed_status = _json_mapping(
                record["typed_status"],
                "terminal typed_status",
            )
            return MappingProxyType(
                {
                    "terminal_status": terminal_status.value,
                    "typed_status": typed_status,
                }
            )
    raise ProtocolError(
        f"frame type {frame_type!r} is not admitted from {sender.value}"
    )


@dataclass(frozen=True)
class ProtocolFrame:
    sender: FrameSender
    frame_type: str
    run_id: OpaqueId
    registration_hash: Sha256Digest
    manifest_id: OpaqueId
    sender_sequence: int
    body: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.sender, FrameSender):
            raise TypeError("sender must be a FrameSender")
        if (
            not isinstance(self.frame_type, str)
            or self.frame_type not in _TYPES_BY_SENDER[self.sender]
        ):
            raise ProtocolError("frame_type is not admitted from its sender")
        if not isinstance(self.run_id, OpaqueId):
            raise TypeError("run_id must be an OpaqueId")
        if not isinstance(self.registration_hash, Sha256Digest):
            raise TypeError("registration_hash must be a Sha256Digest")
        if not isinstance(self.manifest_id, OpaqueId):
            raise TypeError("manifest_id must be an OpaqueId")
        _integer(self.sender_sequence, "sender_sequence")
        binding = ProtocolBinding(
            run_id=self.run_id,
            registration_hash=self.registration_hash,
            manifest_id=self.manifest_id,
        )
        object.__setattr__(
            self,
            "body",
            _validate_body(
                sender=self.sender,
                frame_type=self.frame_type,
                body=self.body,
                binding=binding,
            ),
        )

    def as_record(self) -> dict[str, object]:
        return {
            "type": self.frame_type,
            "run_id": self.run_id.value,
            "registration_hash": self.registration_hash.value,
            "manifest_id": self.manifest_id.value,
            "sender_sequence": self.sender_sequence,
            "body": _thaw_json(self.body),
        }

    @classmethod
    def from_record(
        cls,
        value: object,
        *,
        sender: FrameSender,
        binding: ProtocolBinding,
        expected_sequence: int,
    ) -> "ProtocolFrame":
        record = _record(
            value,
            "protocol frame",
            {
                "type",
                "run_id",
                "registration_hash",
                "manifest_id",
                "sender_sequence",
                "body",
            },
        )
        frame = cls(
            sender=sender,
            frame_type=record["type"],
            run_id=OpaqueId(record["run_id"]),
            registration_hash=Sha256Digest(record["registration_hash"]),
            manifest_id=OpaqueId(record["manifest_id"]),
            sender_sequence=record["sender_sequence"],
            body=record["body"],
        )
        if (
            frame.run_id != binding.run_id
            or frame.registration_hash != binding.registration_hash
            or frame.manifest_id != binding.manifest_id
        ):
            raise ProtocolError("frame binding differs from this Run")
        if frame.sender_sequence != expected_sequence:
            raise ProtocolError(
                "sender_sequence must be contiguous and monotonically increasing"
            )
        return frame


def encode_frame(
    frame: ProtocolFrame,
    *,
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
) -> bytes:
    if not isinstance(frame, ProtocolFrame):
        raise TypeError("frame must be a ProtocolFrame")
    if (
        isinstance(max_frame_bytes, bool)
        or not isinstance(max_frame_bytes, int)
        or max_frame_bytes < 1024
        or max_frame_bytes > MAX_MAX_FRAME_BYTES
    ):
        raise ValueError("max_frame_bytes is outside the admitted range")
    payload = _canonical_bytes(frame.as_record())
    if not payload or len(payload) > max_frame_bytes:
        raise ProtocolError("frame exceeds its exact transport size bound")
    return _LENGTH.pack(len(payload)) + payload


def decode_frame(
    packet: bytes,
    *,
    sender: FrameSender,
    binding: ProtocolBinding,
    expected_sequence: int,
) -> ProtocolFrame:
    if not isinstance(packet, bytes):
        raise TypeError("packet must be bytes")
    if len(packet) < _LENGTH.size:
        raise ProtocolError("frame is missing its length prefix")
    (length,) = _LENGTH.unpack(packet[: _LENGTH.size])
    if length == 0 or length > binding.max_frame_bytes:
        raise ProtocolError("frame length is outside its admitted bound")
    payload = packet[_LENGTH.size :]
    if len(payload) != length:
        raise ProtocolError("frame length prefix does not match its payload")
    return ProtocolFrame.from_record(
        _parse_canonical(payload),
        sender=sender,
        binding=binding,
        expected_sequence=expected_sequence,
    )


def _read_exact(stream: BinaryIO, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = stream.read(remaining)
        if not isinstance(chunk, bytes):
            raise ProtocolError("protocol stream must return bytes")
        if not chunk:
            raise ProtocolError("protocol stream ended inside a frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class FrameEncoder:
    """One fresh sender sequence; there is intentionally no resume position."""

    def __init__(self, *, sender: FrameSender, binding: ProtocolBinding) -> None:
        if not isinstance(sender, FrameSender):
            raise TypeError("sender must be a FrameSender")
        if not isinstance(binding, ProtocolBinding):
            raise TypeError("binding must be a ProtocolBinding")
        self._sender = sender
        self._binding = binding
        self._next_sequence = 0

    def encode(self, frame_type: str, body: Mapping[str, object]) -> bytes:
        frame = ProtocolFrame(
            sender=self._sender,
            frame_type=frame_type,
            run_id=self._binding.run_id,
            registration_hash=self._binding.registration_hash,
            manifest_id=self._binding.manifest_id,
            sender_sequence=self._next_sequence,
            body=body,
        )
        packet = encode_frame(
            frame,
            max_frame_bytes=self._binding.max_frame_bytes,
        )
        self._next_sequence += 1
        return packet

    def write(
        self,
        stream: BinaryIO,
        frame_type: str,
        body: Mapping[str, object],
    ) -> ProtocolFrame:
        packet = self.encode(frame_type, body)
        offset = 0
        while offset < len(packet):
            written = stream.write(packet[offset:])
            if (
                isinstance(written, bool)
                or not isinstance(written, int)
                or written <= 0
            ):
                raise ProtocolError("protocol stream did not accept a full frame")
            offset += written
        if hasattr(stream, "flush"):
            stream.flush()
        return decode_frame(
            packet,
            sender=self._sender,
            binding=self._binding,
            expected_sequence=self._next_sequence - 1,
        )


class FrameDecoder:
    """One fresh receiver sequence; duplicate, skipped, and replayed frames fail."""

    def __init__(self, *, sender: FrameSender, binding: ProtocolBinding) -> None:
        if not isinstance(sender, FrameSender):
            raise TypeError("sender must be a FrameSender")
        if not isinstance(binding, ProtocolBinding):
            raise TypeError("binding must be a ProtocolBinding")
        self._sender = sender
        self._binding = binding
        self._next_sequence = 0

    def decode(self, packet: bytes) -> ProtocolFrame:
        frame = decode_frame(
            packet,
            sender=self._sender,
            binding=self._binding,
            expected_sequence=self._next_sequence,
        )
        self._next_sequence += 1
        return frame

    def read(self, stream: BinaryIO) -> ProtocolFrame:
        prefix = _read_exact(stream, _LENGTH.size)
        (length,) = _LENGTH.unpack(prefix)
        if length == 0 or length > self._binding.max_frame_bytes:
            raise ProtocolError("frame length is outside its admitted bound")
        return self.decode(prefix + _read_exact(stream, length))


__all__ = [
    "CancelKind",
    "FrameDecoder",
    "FrameEncoder",
    "FrameSender",
    "HostFrameType",
    "ProtocolBinding",
    "ProtocolError",
    "ProtocolFrame",
    "WorkerFrameType",
    "decode_frame",
    "encode_frame",
    "episode_id_for_path",
]
