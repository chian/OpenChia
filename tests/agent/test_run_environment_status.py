"""Saved environment failures remain visible without inventing a worker Run."""

from types import SimpleNamespace

from agent.duet_store import DuetStore
from agent.openchia_host import OpenChiaHost
from agent.openchia_run_continue import saved_run_status
from tests.episode_runtime.conftest import claim_store, oid


def _host(store, runs, registration):
    return SimpleNamespace(
        store=store, run_store=runs,
        identity=SimpleNamespace(duet_id=registration.duet_id),
        _run_status_record=OpenChiaHost._run_status_record,
    )


def _event(store, registration, kind, record):
    store.append_event(
        duet_id=registration.duet_id.value, event_type=kind,
        provenance="host_validation", record=record,
    )


def _preparation_failure(registration, run_id=None):
    return {
        "run_id": run_id, "registration_hash": None,
        "build_receipt_id": registration.build_receipt_id.value,
        "error": "EnvironmentPreparationFailure: dependency resolution failed",
        "environment_preparation": {
            "status": "failed",
            "diagnostics": [{"stage": "lock", "error_type": "RuntimeError",
                             "message": "No matching distribution for requested package"}],
            "log_refs": [{"stream": "stderr", "content_hash": "sha256:" + "a" * 64}],
            "preparation_ref": {"artifact_id": "preparation_saved", "content_hash": "sha256:" + "b" * 64},
        },
    }


def test_preclaim_failure_survives_store_reopen_without_inventing_a_run(tmp_path):
    runs, registration, _ = claim_store(tmp_path / "runs")
    baseline = SimpleNamespace(build_receipt_id=registration.build_receipt_id)
    failure = _preparation_failure(registration)
    path = tmp_path / "duet.db"
    with DuetStore(path) as store:
        store.create_duet(duet_id=registration.duet_id.value, identity={}, policy={}, state="sealed")
        _event(store, registration, "run_host_failure", failure)
        # A different build's failure must not replace this build's diagnostics.
        _event(store, registration, "run_host_failure", {
            **failure, "build_receipt_id": oid("different_build_receipt").value,
        })
    with DuetStore(path) as store:
        status = saved_run_status(_host(store, runs, registration), baseline)
        assert status is not None
        assert status["state"] == "host_error"
        assert status["run_id"] is None
        assert status["build_receipt_id"] == registration.build_receipt_id.value
        assert status["error"] == failure["error"]
        assert status["environment_preparation"] == failure["environment_preparation"]
        assert "continuation" not in status


def test_failed_restore_preserves_run_identity_until_a_newer_request(tmp_path):
    runs, registration, _ = claim_store(tmp_path / "runs")
    baseline = SimpleNamespace(
        build_receipt_id=registration.build_receipt_id, build_manifest_id=registration.manifest_id,
    )
    request = {
        "registration": registration.as_record(), "run_id": registration.run_id.value,
        "registration_hash": registration.registration_hash.value,
        "build_receipt_id": registration.build_receipt_id.value,
        "intent_ref": {"artifact_id": "saved_intent", "content_hash": "sha256:" + "c" * 64},
    }
    failure = _preparation_failure(registration, registration.run_id.value)
    path = tmp_path / "duet.db"
    with DuetStore(path) as store:
        store.create_duet(duet_id=registration.duet_id.value, identity={}, policy={}, state="sealed")
        _event(store, registration, "run_requested", request)
        _event(store, registration, "run_host_failure", failure)
    with DuetStore(path) as store:
        host = _host(store, runs, registration)
        status = saved_run_status(host, baseline)
        assert status["state"] == "host_error"
        assert status["run_id"] == registration.run_id.value
        assert status["continuation"]["command"] == "/run continue"
        assert status["environment_preparation"] == failure["environment_preparation"]
        _event(store, registration, "run_continue_requested", request)
        restarted = saved_run_status(host, baseline)
        assert restarted["state"] != "host_error"
        assert "environment_preparation" not in restarted
