"""Logical learning survives physical interruption without copying old credit.

Uses real append-only Run storage and admission. No worker is resumed here;
worker reconstruction and live continuation require separate execution evidence.
"""

from dataclasses import replace

import pytest

from episode_runtime.continuation import InterruptedRunRef
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunTerminalStatus
from episode_runtime.learning import LearningLedger
from episode_runtime.store import RunStoreConflict
from function_library.epistemic_schemas import identity
from function_library.models import _thaw_json

from .conftest import claim_store
from .test_epistemic_learning import attempt, commit, setup


pytestmark = pytest.mark.platforms("linux")


def continue_attempt(runs, registration):
    runs.finalize_run(
        run_id=registration.run_id,
        origin=RunEventOrigin.HOST,
        sender_sequence=0,
        terminal_status=RunTerminalStatus.INTERRUPTED,
        typed_status={"outcome": "interrupted"},
    )
    resumed = replace(
        registration,
        resume_from=InterruptedRunRef.from_run(runs, registration.run_id),
    )
    claim_store(runs.root, resumed, store=runs)
    return resumed, LearningLedger(runs, resumed.run_id)


def test_continuation_reuses_original_evidence_and_credit_without_copying_events(run_store):
    runs, original, _ = run_store
    ledger, kwargs, evidence_ref = setup(run_store)
    result = attempt(evidence_ref)
    admitted = commit(ledger, kwargs, 0, result)
    original_bundle = ledger.retrieve(**kwargs)
    assert admitted["measurement"]["realized_yield"] > 0

    resumed, ledger = continue_attempt(runs, original)
    original_log = runs.read_audit_log(original.run_id)
    original_evidence = runs.read_evidence(original.run_id)
    bundle = ledger.retrieve(**kwargs)
    assert bundle["evidence"] == original_bundle["evidence"]
    assert bundle["applicable_lessons"] == original_bundle["applicable_lessons"]
    assert bundle["last_receipt"] == admitted
    assert bundle["next_ordinal"] == admitted["ordinal"] + 1
    assert commit(ledger, kwargs, 0, result) == admitted
    assert runs.read_committed_prefix(resumed.run_id) == ()

    duplicate = commit(ledger, kwargs, 1, attempt(evidence_ref, "Same route, new wording"))
    assert duplicate["measurement"]["realized_yield"] == 0
    assert duplicate["measurement"]["credit_before"] == admitted["measurement"]["credit_after"]
    assert duplicate["measurement"]["credit_after"] == admitted["measurement"]["credit_after"]
    assert duplicate["result_artifact"]["run_id"] == resumed.run_id.value
    physical = runs.read_committed_prefix(resumed.run_id)
    assert physical[0].sequence == 0 and physical[0].previous_event_hash is None
    assert [event.sender_sequence for event in physical] == list(range(len(physical)))
    assert all(event.run_id == resumed.run_id for event in physical)
    assert not any(event.kind in {RunEventKind.LEARNING_OPENED, RunEventKind.LEARNING_EVIDENCE} for event in physical)
    assert runs.read_execution_prefix(resumed.run_id) == (*original_log, *physical)
    assert runs.read_audit_log(original.run_id) == original_log
    assert runs.read_evidence(original.run_id) == original_evidence
    with pytest.raises(RunStoreConflict, match="terminal"):
        LearningLedger(runs, original.run_id).retrieve(**kwargs)

    # The same identity remains anchored to the first attempt through a chain.
    third, ledger = continue_attempt(runs, resumed)
    assert ledger.retrieve(**kwargs)["last_receipt"] == duplicate
    assert commit(ledger, kwargs, 0, result) == admitted
    assert runs.read_committed_prefix(third.run_id) == ()
    assert third.logical_run_id == original.run_id


@pytest.mark.parametrize("attack", ["reset_credit", "discard_prior_state"])
def test_pending_submission_uses_original_audit_and_store_rejects_forged_history(
    run_store, monkeypatch, attack,
):
    runs, original, _ = run_store
    ledger, kwargs, evidence_ref = setup(run_store)
    admitted = commit(ledger, kwargs, 0, attempt(evidence_ref))
    captured = []
    publish = runs._publish_event

    def interrupt_before_commit(event):
        if event.kind is RunEventKind.LEARNING_COMMITTED:
            captured.append(event)
            raise OSError("process lost before learning commit publication")
        publish(event)

    monkeypatch.setattr(runs, "_publish_event", interrupt_before_commit)
    pending_result = attempt()
    with pytest.raises(OSError, match="process lost"):
        commit(ledger, kwargs, 1, pending_result)
    monkeypatch.setattr(runs, "_publish_event", publish)
    expected = _thaw_json(captured[0].payload)
    resumed, ledger = continue_attempt(runs, original)
    original_log = runs.read_audit_log(original.run_id)
    bundle = ledger.retrieve(**kwargs)
    assert bundle["pending_submission"]["result"] == pending_result
    assert bundle["next_ordinal"] == 1
    assert any(event.event_id.value == expected["receipt"]["audit_ref"] for event in original_log)

    forged = _thaw_json(expected)
    if attack == "reset_credit":
        forged["receipt"]["measurement"].update(credit_before=0, credit_after=0)
        error = "credit update does not match durable history"
    else:
        forged["state"]["records"] = []
        error = "checkpoint contains unadmitted changes"
    forged["receipt"]["receipt_id"] = identity(
        "receipt", {key: value for key, value in forged["receipt"].items() if key != "receipt_id"},
    )
    with pytest.raises(ValueError, match=error):
        runs.append_event(
            run_id=resumed.run_id,
            origin=RunEventOrigin.HOST_LEARNING,
            sender_sequence=0,
            kind=RunEventKind.LEARNING_COMMITTED,
            episode_id=kwargs["episode_id"],
            payload=forged,
        )
    assert runs.read_committed_prefix(resumed.run_id) == ()

    receipt = commit(ledger, kwargs, 1, pending_result)
    assert receipt["audit_ref"] == expected["receipt"]["audit_ref"]
    assert receipt["numeric_step"] == expected["receipt"]["numeric_step"]
    assert receipt["measurement"]["credit_after"] == admitted["measurement"]["credit_after"]
    assert receipt["measurement"]["realized_yield"] == 0
    assert commit(ledger, kwargs, 1, pending_result) == receipt
    physical = runs.read_committed_prefix(resumed.run_id)
    assert [event.kind for event in physical] == [RunEventKind.LEARNING_COMMITTED]
    assert physical[0].sequence == 0 and physical[0].previous_event_hash is None
    assert runs.read_audit_log(original.run_id) == original_log
