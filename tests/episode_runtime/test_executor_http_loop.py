"""The executor brokers one worker HTTP request over the real frame pipes (#8).

A stub ``_RunExecutorBase`` launches a tiny Python worker that speaks the
closed protocol on its stdin/stdout: INITIALIZE -> READY, START, one
HTTP_REQUEST, its HTTP_RESPONSE, TERMINAL -> TERMINAL_ACK.  Only launch and
inspection are stubbed; the frame loop, the broker, and the RunStore event
chain are the production code.  The host transport is a fake: no network.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path, PurePosixPath
import sys
import uuid

import pytest

from agent.episode_contracts import EpisodeEgressRule, OpaqueId, Sha256Digest
from episode_runtime import executor as executor_module
from episode_runtime.contracts import (
    RUNTIME_WORKER_ENTRYPOINT,
    ExecutorKind,
    ReadOnlyRuntimeMount,
    RunEventKind,
    RunEventOrigin,
    RunRegistration,
    RunTerminalStatus,
    RuntimeIdentity,
    RuntimeMountKind,
    RuntimePolicy,
)
from episode_runtime.http_broker import ScopedHttpBroker
from episode_runtime.http_contracts import http_request_hash, http_response_hash
from episode_runtime.broker import ScopedModelBroker
from episode_runtime.store import RunStore
from handoff_library import DuetLaunchRequest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HOST = "www.bv-brc.org"
REQUEST = {
    "method": "GET",
    "url": f"https://{HOST}/ragstack/api/v1/query?q=asm",
    "headers": {"accept": "application/json"},
    "body": None,
    "timeout": 10.0,
}

WORKER = r'''
import json, platform, sys
from agent.episode_contracts import OpaqueId, Sha256Digest
from episode_runtime.landlock import LandlockPolicyReceipt
from episode_runtime.protocol import (
    FrameDecoder, FrameEncoder, FrameSender, HostFrameType, ProtocolBinding,
    WorkerFrameType, episode_id_for_path,
)
from episode_runtime.seccomp import SeccompPolicyReceipt, normalize_machine, seccomp_policy_hash

run_id, registration_hash, manifest_id, max_frame, runtime_id, runtime_hash = sys.argv[1:7]
request = json.loads(sys.argv[7])
binding = ProtocolBinding(
    run_id=OpaqueId(run_id), registration_hash=Sha256Digest(registration_hash),
    manifest_id=OpaqueId(manifest_id), max_frame_bytes=int(max_frame),
)
stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
decoder = FrameDecoder(sender=FrameSender.HOST, binding=binding)
encoder = FrameEncoder(sender=FrameSender.WORKER, binding=binding)

def send(frame_type, body):
    stdout.write(encoder.encode(frame_type, body)); stdout.flush()

def expect(frame_type):
    frame = decoder.read(stdin)
    assert frame.frame_type == frame_type, frame.frame_type
    return frame

init = expect(HostFrameType.INITIALIZE.value)
executor_id = OpaqueId(init.body["executor_instance_id"])
machine = normalize_machine(platform.machine())
send(WorkerFrameType.READY.value, {
    "runtime_id": runtime_id, "runtime_hash": runtime_hash,
    "landlock_receipt": LandlockPolicyReceipt(
        run_id=binding.run_id, executor_instance_id=executor_id).as_record(),
    "seccomp_receipt": SeccompPolicyReceipt(
        run_id=binding.run_id, executor_instance_id=executor_id, machine=machine,
        policy_hash=seccomp_policy_hash(machine)).as_record(),
})
expect(HostFrameType.START.value)
path = [{"grain": "fetcher", "key": "root"}]
send(WorkerFrameType.HTTP_REQUEST.value, {
    "http_request_id": OpaqueId.mint("http_request", "loop-test").value,
    "episode_id": episode_id_for_path(binding.run_id, path).value,
    "episode_path": path,
    "request": request,
})
response = expect(HostFrameType.HTTP_RESPONSE.value).body["response"]
send(WorkerFrameType.TERMINAL.value, {
    "terminal_status": "succeeded",
    "typed_status": {"outcome": "succeeded", "http_outcome": response["outcome"],
                     "http_body": response["body"]},
})
expect(HostFrameType.TERMINAL_ACK.value)
'''


def _digest(label: str) -> Sha256Digest:
    return Sha256Digest.of_bytes(label.encode())


def _registration(rule: EpisodeEgressRule) -> RunRegistration:
    workflow_id = OpaqueId.mint("workflow", "http-loop")
    return RunRegistration(
        duet_id=OpaqueId.mint("duet", "http-loop"),
        admission_authority_id=OpaqueId.mint("admission", "http-loop"),
        admission_authority_hash=_digest("admission"),
        authority_head_approval_id=OpaqueId.mint("approval", "head"),
        authority_head_approval_hash=_digest("head"),
        workflow_approval_id=OpaqueId.mint("approval", "workflow"),
        workflow_approval_hash=_digest("workflow-approval"),
        workflow_id=workflow_id,
        workflow_hash=_digest("workflow"),
        build_request_id=OpaqueId.mint("build_request", "http-loop"),
        build_attempt_id=OpaqueId.mint("build_attempt", "http-loop"),
        build_receipt_id=OpaqueId.mint("build_receipt", "http-loop"),
        manifest_id=OpaqueId.mint("manifest", "http-loop"),
        manifest_hash=_digest("manifest"),
        launch_request=DuetLaunchRequest(
            request_id=OpaqueId.mint("request", "http-loop").value,
            workflow_id=workflow_id.value,
            goal_id=OpaqueId.mint("goal", "http-loop").value,
            artifact_ids_by_role={},
        ),
        runtime_identity=RuntimeIdentity(
            worker_entrypoint=RUNTIME_WORKER_ENTRYPOINT,
            runtime_source_manifest_id=OpaqueId.mint("runtime_source_manifest", "x"),
            runtime_source_manifest_hash=_digest("source"),
            interpreter_runtime_id=OpaqueId.mint("interpreter_runtime", "x"),
            interpreter_runtime_hash=_digest("interpreter"),
        ),
        runtime_policy=RuntimePolicy(),
        egress_policy={"fetcher": (rule,)},
    )


class _PipeExecutor(executor_module._RunExecutorBase):
    """Launch the protocol stub as a plain subprocess; attest canned facts."""

    def __init__(self, run_store: RunStore, worker_script: Path) -> None:
        self.run_store = run_store
        self.repository_root = REPOSITORY_ROOT
        self.worker_script = worker_script

    def _identity_arguments(self):
        return {}

    def _launch_identity(self, run_id):
        return executor_module._launch_identity(run_id, ExecutorKind.CONTAINER)

    def _runtime_mounts(self, registration, runtime_source_package, source_package):
        base = PurePosixPath("/tmp/openchia-http-loop-test")
        return (
            ReadOnlyRuntimeMount(
                kind=RuntimeMountKind.RUNTIME_SOURCE_PACKAGE,
                source_path=str(runtime_source_package),
                target_path=str(
                    base / registration.runtime_identity.runtime_source_manifest_id.value
                ),
            ),
            ReadOnlyRuntimeMount(
                kind=RuntimeMountKind.SOURCE_PACKAGE,
                source_path=str(source_package),
                target_path=str(base / registration.manifest_id.value),
            ),
        )

    async def _launch(self, registration, launch_identity, mounts, bootstrap_program):
        env = dict(os.environ, PYTHONPATH=str(REPOSITORY_ROOT))
        return await asyncio.create_subprocess_exec(
            sys.executable,
            str(self.worker_script),
            registration.run_id.value,
            registration.registration_hash.value,
            registration.manifest_id.value,
            str(registration.runtime_policy.max_frame_bytes),
            registration.runtime_identity.runtime_id.value,
            registration.runtime_identity.content_hash.value,
            json.dumps(REQUEST),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            cwd=str(REPOSITORY_ROOT),
            env=env,
        )

    async def _inspect(self, launch_identity, launcher, mounts):
        return executor_module._ExecutorFacts(
            executor_kind=ExecutorKind.CONTAINER,
            unit_name=launch_identity.unit_name,
            invocation_id="a" * 64,
            launch_description=launch_identity.description,
            boot_id=str(uuid.uuid4()),
            leader_pid=launcher.pid,
            leader_start_time_ticks=1,
            cgroup_path="/openchia-http-loop-test",
            read_only_runtime_mounts=mounts,
            memory_max_bytes=None,
            pids_max=None,
            cpu_weight=100,
            cpu_quota_micros=None,
            cpu_period_micros=100_000,
            filesystem_namespace_isolated=True,
            process_namespace_isolated=True,
            network_namespace_isolated=True,
            host_runtime_read_only=True,
            no_new_privs=True,
        )

    async def _stop_exact(self, launch_identity, launcher, facts):
        launcher.kill()
        await launcher.wait()


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return 200, {"Content-Type": "application/json"}, b'{"hits":3}'


async def _unused_model_transport(request):  # pragma: no cover - never called
    raise AssertionError("the HTTP loop test makes no model call")


def test_one_http_round_trip_is_brokered_and_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(executor_module, "verify_runtime_identity", lambda *a, **k: None)

    # Learning is orthogonal to this test: the real LearningBroker inspects the
    # materialized source package (APPROVED_BUILD_REQUEST.json ...), which the
    # minimal stub package here does not carry.
    import episode_runtime.learning_broker as learning_module

    class _NoLearning:
        def __init__(self, *args, **kwargs):
            pass

        async def __call__(self, *args, **kwargs):
            raise AssertionError("no learning request expected in the HTTP loop test")

        def validate_completion(self, typed_status=None):
            return None

    monkeypatch.setattr(learning_module, "LearningBroker", _NoLearning)
    monkeypatch.setattr(
        executor_module, "load_verified_bootstrap_program", lambda *a, **k: ""
    )
    rule = EpisodeEgressRule.from_record(
        {
            "name": "ragstack_query",
            "host": HOST,
            "path_prefix": "/ragstack/api/",
            "methods": ["GET"],
            "read_only": True,
            "max_requests": 5,
            "max_response_bytes": 65536,
            "credential": None,
        }
    )
    registration = _registration(rule)
    store = RunStore(tmp_path / "runs")
    source_package = tmp_path / "sources" / registration.manifest_id.value
    source_package.mkdir(parents=True)
    worker_script = tmp_path / "worker_stub.py"
    worker_script.write_text(WORKER)
    transport = _FakeTransport()
    http_broker = ScopedHttpBroker(
        policy=registration.egress_policy,
        credentials={},
        transport=transport,
        max_frame_bytes=registration.runtime_policy.max_frame_bytes,
    )

    evidence = asyncio.run(
        asyncio.wait_for(
            _PipeExecutor(store, worker_script).execute(
                registration=registration,
                source_package_path=source_package,
                model_broker=ScopedModelBroker(_unused_model_transport, episode_paths={}),
                http_broker=http_broker,
            ),
            timeout=60,
        )
    )

    assert evidence.terminal_status is RunTerminalStatus.SUCCEEDED
    assert evidence.typed_status["http_outcome"] == "ok"
    assert evidence.typed_status["http_body"] == '{"hits":3}'
    assert len(transport.calls) == 1
    assert http_broker.request_count("fetcher", "ragstack_query") == 1

    events = store.read_audit_log(registration.run_id)
    kinds = [event.kind for event in events]
    requested = events[kinds.index(RunEventKind.HTTP_REQUESTED)]
    responded = events[kinds.index(RunEventKind.HTTP_RESPONDED)]
    assert requested.sequence + 1 == responded.sequence
    assert requested.origin is RunEventOrigin.WORKER
    assert responded.origin is RunEventOrigin.HOST
    assert requested.episode_id == responded.episode_id is not None
    request_hash = http_request_hash(REQUEST).value
    assert dict(requested.payload) == {
        "http_request_id": requested.payload["http_request_id"],
        "request_hash": request_hash,
        "rule": "ragstack_query",
        "method": "GET",
        "host": HOST,
        "path": "/ragstack/api/v1/query",
    }
    expected_response = {
        "outcome": "ok",
        "status": 200,
        "headers": {"content-type": "application/json"},
        "body": '{"hits":3}',
        "body_encoding": "utf-8",
        "reason": None,
        "rule": "ragstack_query",
    }
    assert dict(responded.payload) == {
        "http_request_id": requested.payload["http_request_id"],
        "request_hash": request_hash,
        "response_hash": http_response_hash(expected_response).value,
        "outcome": "ok",
        "status": 200,
        "response_bytes": len(b'{"hits":3}'),
        "rule": "ragstack_query",
    }
