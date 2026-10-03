"""Publication must rederive continuation even if its producer is faulty."""

from dataclasses import replace

import pytest

from iterative_episode_refiner import state_machine


def test_store_rejects_a_forged_completion_and_retry_recovers(campaign, monkeypatch):
    campaign.implementer()
    attempt = campaign.attempt(
        "close_unit",
        {
            "candidate_before_ref": campaign.initial.ref.as_record(),
            "continuation_ref": None,
        },
    )
    admit = state_machine.admit_attempt

    def false_completion(view, attempt, resolved):
        records, deltas = admit(view, attempt, resolved)
        decision = next(record for record in records if record.kind == "continuation")
        forged = replace(
            decision,
            body={
                **decision.body,
                "attained": True,
                "stop": True,
                "remaining_opportunities": 0,
            },
        )
        receipt = next(record for record in records if record.kind == "unit_receipt")
        forged_receipt = replace(
            receipt,
            body={
                **receipt.body,
                "continuation_ref": forged.ref.as_record(),
                "disposition": "attained",
            },
        )
        return [forged, forged_receipt], [
            {**delta, "record_id": forged_receipt.artifact_id.value}
            if delta.get("record_id") == receipt.artifact_id.value
            else delta
            for delta in deltas
        ]

    with monkeypatch.context() as scoped:
        scoped.setattr(state_machine, "admit_attempt", false_completion)
        with pytest.raises(
            ValueError, match="continuation is not independently derived"
        ):
            campaign.store.commit_attempt(attempt)
    assert campaign.entries("unit") == ()
    receipt = campaign.store.commit_attempt(attempt)
    assert campaign.store.commit_attempt(attempt).ref == receipt.ref
    unit = campaign.entries("unit")[0].record
    assert unit.body["disposition"] == "continuing"
    assert unit.body["realized_yield"] == 0
