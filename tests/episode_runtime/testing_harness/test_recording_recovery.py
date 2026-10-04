"""The same immutable recording survives existing RunStore publication recovery."""

import pytest

from episode_runtime.contracts import RunEventOrigin, RunTerminalStatus
from episode_runtime.testing_harness.recordings import read_recording


def test_terminal_publication_recovery_preserves_recording_identity(
    run_store, monkeypatch
):
    runs, registration, _ = run_store

    def interrupted_publication(**kwargs):
        raise OSError("injected interruption after terminal event commit")

    with monkeypatch.context() as patch:
        patch.setattr(
            runs, "_publish_terminal_artifacts_locked", interrupted_publication
        )
        with pytest.raises(OSError, match="after terminal event"):
            runs.finalize_run(
                run_id=registration.run_id,
                origin=RunEventOrigin.HOST,
                sender_sequence=0,
                terminal_status=RunTerminalStatus.INTERRUPTED,
                typed_status={"outcome": "interrupted"},
            )
    before = read_recording(runs, registration.run_id)
    assert before["source_terminal_status"] == "interrupted"
    assert not before["terminal_evidence_available"]
    evidence = runs.complete_terminal_publication(registration.run_id)
    after = read_recording(
        runs, registration.run_id, through_event_ref=before["through_event_ref"]
    )
    assert after["terminal_evidence_available"]
    assert after["source_terminal_status"] == "interrupted"
    assert before["recording_id"] == after["recording_id"]
    assert before["through_event_ref"] == after["through_event_ref"]
    assert runs.complete_terminal_publication(registration.run_id) == evidence
