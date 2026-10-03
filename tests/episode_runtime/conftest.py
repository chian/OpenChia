"""Real RunStore fixtures; attestation data describes an inert test executor."""

import pytest

from agent.duet_contracts import content_id
from agent.episode_contracts import (
    EpisodeFunctionSelectionSpec,
    EpisodeNumericalControlSpec,
    Sha256Digest,
)
from episode_runtime.contracts import (
    ExecutorKind,
    InspectedExecutorAttestation,
    ReadOnlyRuntimeMount,
    RunRegistration,
    RuntimeIdentity,
    RuntimeMountKind,
    RuntimePolicy,
    derive_executor_instance_id,
)
from episode_runtime.landlock import LandlockPolicyReceipt
from episode_runtime.seccomp import (
    SeccompPolicyReceipt,
    seccomp_policy_hash,
    seccomp_policy_record,
)
from episode_runtime.store import RunStore
from handoff_library import DuetLaunchRequest
from numeric_control_library import PAIRED_INCIDENCE, PREDICTED_CREDIT_UPPER_BOUND


def pytest_addoption(parser):
    parser.addoption(
        "--live-reasoning-socket",
        default=None,
        help="Explicit opt-in Unix socket to a configured live model bridge",
    )
    parser.addoption(
        "--live-reasoning-report",
        default=None,
        help="Path for the inspectable live acceptance JSON report",
    )


def oid(name):
    return content_id(name, {"fixture": name})


def numerical_control(threshold=0.01):
    def selection(function, arguments):
        return EpisodeFunctionSelectionSpec(
            function.library,
            function.function_id,
            function.interface,
            function.definition_id,
            arguments,
        )

    return EpisodeNumericalControlSpec(
        selection(PAIRED_INCIDENCE, {"uncertainty_alpha": 0.05}),
        selection(
            PREDICTED_CREDIT_UPPER_BOUND,
            {"max_predicted_marginal_hypervolume": threshold},
        ),
    )


def claim_store(root, registration=None):
    digest = Sha256Digest.of_bytes(b"inert fixture identity")
    runtime = RuntimeIdentity(
        "episode_runtime.worker.main",
        oid("runtime_source_manifest"),
        digest,
        oid("interpreter_runtime"),
        digest,
    )
    if registration is None:
        registration = RunRegistration(
            duet_id=oid("duet"),
            admission_authority_id=oid("authority"),
            admission_authority_hash=digest,
            authority_head_approval_id=oid("approval"),
            authority_head_approval_hash=digest,
            workflow_approval_id=oid("approval"),
            workflow_approval_hash=digest,
            workflow_id=oid("workflow"),
            workflow_hash=digest,
            build_request_id=oid("build_request"),
            build_attempt_id=oid("build_attempt"),
            build_receipt_id=oid("build_receipt"),
            manifest_id=oid("manifest"),
            manifest_hash=digest,
            launch_request=DuetLaunchRequest(
                oid("request").value, oid("workflow").value, oid("goal").value, {}
            ),
            runtime_identity=runtime,
            runtime_policy=RuntimePolicy(),
        )
    runtime = registration.runtime_identity
    nonce = "a" * 32
    unit_name = f"openchia-episode-{registration.run_id.value.rsplit('_', 1)[-1][:32]}-{nonce}.service"
    topology = dict(
        boot_id="12345678-1234-1234-1234-123456789abc",
        leader_pid=123,
        leader_start_time_ticks=100,
        cgroup_path=f"/test/{unit_name}",
    )
    executor_id = derive_executor_instance_id(
        executor_kind=ExecutorKind.SYSTEMD, unit_name=unit_name,
        invocation_id=nonce, **topology,
    )
    mounts = tuple(
        ReadOnlyRuntimeMount(
            kind, str(root / "source" / name), str(root / "target" / name)
        )
        for kind, name in (
            (
                RuntimeMountKind.RUNTIME_SOURCE_PACKAGE,
                runtime.runtime_source_manifest_id.value,
            ),
            (RuntimeMountKind.SOURCE_PACKAGE, registration.manifest_id.value),
        )
    )
    attestation = InspectedExecutorAttestation(
        run_id=registration.run_id,
        registration_hash=registration.registration_hash,
        manifest_id=registration.manifest_id,
        executor_instance_id=executor_id,
        runtime_id=runtime.runtime_id,
        runtime_hash=runtime.content_hash,
        runtime_policy_id=registration.runtime_policy.policy_id,
        runtime_policy_hash=registration.runtime_policy.content_hash,
        landlock_receipt=LandlockPolicyReceipt(registration.run_id, executor_id),
        seccomp_receipt=SeccompPolicyReceipt(
            registration.run_id,
            executor_id,
            seccomp_policy_record()["machine"],
            seccomp_policy_hash(),
        ),
        executor_kind=ExecutorKind.SYSTEMD,
        executor_unit_name=unit_name,
        executor_invocation_id=nonce,
        launch_description=f"openchia-episode-launch:{registration.run_id.value}:{nonce}",
        read_only_runtime_mounts=mounts,
        memory_max_bytes=None,
        pids_max=None,
        cpu_weight=100,
        cpu_quota_micros=None,
        cpu_period_micros=100000,
        filesystem_namespace_isolated=True,
        process_namespace_isolated=True,
        network_namespace_isolated=True,
        host_runtime_read_only=True,
        no_new_privs=True,
        **topology,
    )
    store = RunStore(root / "runs")
    store.publish_registration(registration)
    store.claim_run(attestation)
    return store, registration, attestation


@pytest.fixture
def run_store(tmp_path):
    return claim_store(tmp_path)
