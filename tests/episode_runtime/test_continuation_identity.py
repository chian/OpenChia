"""A physical retry cannot change the logical program or its authority.

Real stores, generated refiner linking and worker request construction are used.
No resumed process is launched; reconstruction/host restoration remain required.
"""

import asyncio
import sys
from dataclasses import replace

import pytest

from agent.duet_contracts import canonical_json, content_id, digest_record
from agent.episode_contracts import OpaqueId, Sha256Digest
from episode_runtime import protocol
from episode_runtime.broker import admit_model_request
from episode_runtime.continuation import InterruptedRunRef
from episode_runtime.contracts import RunEventOrigin, RunRegistration, RunTerminalStatus, derive_executor_instance_id
from episode_runtime.executor import RunExecutionError, _RunExecutorBase
from episode_runtime.linker import prepare_source_package
from episode_runtime.store import RunStoreConflict, RunStoreNotFound
from episode_runtime.worker import _ProtocolChannel, runtime_collaborators
from tests.episode_runtime.conftest import claim_store
from tests.episode_runtime.test_model_request_thaw import REQUEST
from tests.episode_runtime.testing_harness.refinement_fixture import prepared_refiner


def interrupt(runs, registration):
    return runs.finalize_run(
        run_id=registration.run_id, origin=RunEventOrigin.HOST,
        sender_sequence=0, terminal_status=RunTerminalStatus.INTERRUPTED,
        typed_status={"outcome": "interrupted", "reason": "fixture worker stopped"},
    )


def test_continuation_preserves_exact_registration_and_rejects_changed_predecessors(run_store):
    runs, original, _ = run_store
    # Adding the optional binding does not alter existing serialized registrations.
    assert "resume_from" not in original.as_record()
    assert original.run_id == content_id("run", original.semantic_record())
    assert original.registration_hash == digest_record({"run_id": original.run_id.value, **original.semantic_record()})
    with pytest.raises(RunStoreNotFound):
        InterruptedRunRef.from_run(runs, original.run_id)
    evidence = interrupt(runs, original)
    reference = InterruptedRunRef.from_run(runs, original.run_id)
    resumed = replace(original, resume_from=reference)
    assert resumed.run_id != original.run_id
    assert resumed.logical_run_id == original.run_id
    assert resumed.logical_registration_hash == original.registration_hash
    assert RunRegistration.from_record(resumed.as_record()) == resumed
    runs.publish_registration(resumed)
    runs.publish_registration(replace(original, resume_from=reference))
    assert runs.read_registration(resumed.run_id) == resumed
    assert runs.read_evidence(original.run_id) == evidence
    with pytest.raises(RunStoreNotFound):
        runs.read_evidence(resumed.run_id)
    changed = Sha256Digest.of_bytes(b"changed")
    mutations = (
        {"manifest_hash": changed}, {"authority_head_approval_hash": changed},
        {"runtime_identity": replace(original.runtime_identity, runtime_source_manifest_hash=changed)},
        {"launch_request": replace(original.launch_request, request_id=OpaqueId.mint("request", "changed").value)},
        {"runtime_policy": replace(original.runtime_policy, max_frame_bytes=2 * original.runtime_policy.max_frame_bytes)},
        {"resume_from": replace(reference, terminal_event_hash=changed)},
    )
    for mutation in mutations:
        bad = replace(resumed, **mutation)
        with pytest.raises(ValueError, match="continuation"):
            runs.publish_registration(bad)
        with pytest.raises(RunStoreNotFound):
            runs.read_registration(bad.run_id)
    _, _, attestation = claim_store(runs.root, resumed, store=runs)
    # Repeating one claim is idempotent; a different executor cannot take it.
    runs.claim_run(attestation)
    different_pid = attestation.leader_pid + 1
    different_id = derive_executor_instance_id(
        executor_kind=attestation.executor_kind,
        unit_name=attestation.executor_unit_name,
        invocation_id=attestation.executor_invocation_id,
        boot_id=attestation.boot_id,
        leader_pid=different_pid,
        leader_start_time_ticks=attestation.leader_start_time_ticks,
        cgroup_path=attestation.cgroup_path,
    )
    different = replace(
        attestation, leader_pid=different_pid, executor_instance_id=different_id,
        landlock_receipt=replace(attestation.landlock_receipt, executor_instance_id=different_id),
        seccomp_receipt=replace(attestation.seccomp_receipt, executor_instance_id=different_id),
    )
    with pytest.raises(RunStoreConflict, match="already been claimed"):
        runs.claim_run(different)
    interrupt(runs, resumed)
    third = replace(resumed, resume_from=InterruptedRunRef.from_run(runs, resumed.run_id))
    runs.publish_registration(third)
    assert len({original.run_id, resumed.run_id, third.run_id}) == 3
    assert third.logical_run_id == original.run_id
    assert third.logical_registration_hash == original.registration_hash


@pytest.mark.asyncio
async def test_linker_and_worker_preserve_logical_ids_but_authenticate_new_run(tmp_path, run_store):
    async with prepared_refiner(tmp_path, run_store[1].runtime_identity) as session:
        runs = session.store.evidence.runs
        original = session.registration
        claim_store(runs.root, original, store=runs)
        interrupt(runs, original)
        resumed = replace(original, resume_from=InterruptedRunRef.from_run(runs, original.run_id))
        inputs = session.evaluations.builder.store.inspection_inputs_for_receipt(original.build_receipt_id)
        package = session.evaluations.builder.store.verify_source_package(inputs.manifest)

        async def no_events(*args):
            raise AssertionError("linking must not execute the Episode")

        linked = []
        frames = []
        for registration in (original, resumed):
            prepared = prepare_source_package(registration, package)
            try:
                linked.append(prepared.activate().link(
                    event_sink=no_events, collaborators=runtime_collaborators(prepared.plan),
                ))
            finally:
                # Each actual worker has a fresh interpreter. The in-process
                # fixture must release only the generated modules it activated.
                for module in prepared.modules.values():
                    sys.modules.pop(module.module_name, None)
            binding = protocol.ProtocolBinding.from_registration(registration)
            channel = _ProtocolChannel(binding=binding, reader=asyncio.StreamReader())
            emitted = []

            async def capture(kind, body):
                # Real framing and worker request-ID construction; transport only is supplied.
                packet = channel.encoder.encode(kind, body)
                emitted.append(protocol.decode_frame(packet, sender=protocol.FrameSender.WORKER, binding=binding, expected_sequence=len(emitted)))
                channel._pending_models[body["model_request_id"]].set_result(None)

            channel.send = capture
            root = linked[-1].root_episode
            path = [{"grain": grain, "key": key} for grain, key in root.runtime_episode_path]
            await channel.request_model(admit_model_request(REQUEST), episode_id=root.runtime_episode_id, episode_path=path)
            frames.append(emitted[0])
        assert linked[0].root_episode.runtime_episode_id == linked[1].root_episode.runtime_episode_id
        assert linked[0].root_episode.request == linked[1].root_episode.request
        assert linked[0].root_episode.runtime_episode_path == linked[1].root_episode.runtime_episode_path
        assert canonical_json(frames[0].body) == canonical_json(frames[1].body)
        assert frames[0].run_id != frames[1].run_id
        assert frames[0].registration_hash != frames[1].registration_hash
        with pytest.raises(protocol.ProtocolError):
            protocol.decode_frame(protocol.encode_frame(frames[1]), sender=protocol.FrameSender.WORKER, binding=protocol.ProtocolBinding.from_registration(original), expected_sequence=0)
        # Wire bytes cannot select a different logical identity from the host binding.
        forged = frames[1].as_record()
        forged["logical_run_id"] = OpaqueId.mint("run", "forged").value
        with pytest.raises(ValueError, match="protocol frame"):
            protocol.ProtocolFrame.from_record(forged, sender=protocol.FrameSender.WORKER, binding=protocol.ProtocolBinding.from_registration(resumed), expected_sequence=0)
        with pytest.raises(RunExecutionError, match="restoration"):
            await _RunExecutorBase().execute(registration=resumed, source_package_path=package, model_broker=None, http_broker=None)
