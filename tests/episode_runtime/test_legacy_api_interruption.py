"""Legacy API stops are resumable without opening ordinary failures or rewriting history."""

from dataclasses import replace

import pytest

from episode_runtime.broker import admit_model_request, model_request_hash
from episode_runtime.continuation import InterruptedRunRef, resumable_run
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunTerminalStatus
from episode_runtime.protocol import episode_id_for_path
from tests.episode_runtime.test_model_request_thaw import REQUEST


@pytest.mark.parametrize("origin,failure_type,expected", [
    (RunEventOrigin.HOST, "LaunchModelError", True),
    (RunEventOrigin.HOST, "ValueError", False),
    (RunEventOrigin.WORKER, "LaunchModelError", False),
])
def test_only_host_recorded_legacy_api_failure_can_continue(run_store, origin, failure_type, expected):
    runs, registration, _ = run_store
    path = [{"grain": "inquiry", "key": "root"}]
    runs.append_event(
        run_id=registration.run_id, origin=RunEventOrigin.WORKER, sender_sequence=0,
        kind=RunEventKind.MODEL_REQUESTED, episode_id=episode_id_for_path(registration.run_id, path),
        payload={"model_request_id": "pending", "request_hash": model_request_hash(admit_model_request(REQUEST)).value,
                 "task": REQUEST["task"], "request": REQUEST, "episode_path": path},
    )
    evidence = runs.finalize_run(
        run_id=registration.run_id, origin=origin, sender_sequence=1,
        terminal_status=RunTerminalStatus.FAILED,
        typed_status={"outcome": "failed", "failure_type": failure_type, "failure": "legacy failed call"},
    )
    audit = runs.read_audit_log(registration.run_id)
    assert resumable_run(runs, registration.run_id) is expected
    if expected:
        ref = InterruptedRunRef.from_run(runs, registration.run_id)
        runs.publish_registration(replace(registration, resume_from=ref))
    else:
        with pytest.raises(ValueError):
            InterruptedRunRef.from_run(runs, registration.run_id)
    assert runs.read_evidence(registration.run_id) == evidence
    assert runs.read_audit_log(registration.run_id) == audit
