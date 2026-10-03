"""State invariants only; not a claim that a model can design or repair Episodes."""

from dataclasses import replace

import pytest

from agent.duet_store import DuetConflictError
from iterative_episode_refiner.records import logical_path


def test_candidate_cas_and_audited_retry_preserve_exact_baseline(campaign):
    campaign.implementer()
    original = campaign.candidate
    attempt = campaign.change(b"def solve(values):\n    return sorted(set(values))\n")
    commit = campaign.store.commit_attempt(attempt)
    revised = campaign.candidate
    assert revised.ref != original.ref
    assert (
        campaign.builds.read_blob(original.body["files"]["target.py"])
        == b"def solve(values):\n    return values\n"
    )
    assert campaign.store.commit_attempt(attempt).ref == commit.ref
    assert campaign.candidate.ref == revised.ref
    stale = campaign.change(b"def solve(values):\n    return []\n", before=original)
    with pytest.raises(DuetConflictError, match="stale"):
        campaign.store.commit_attempt(stale)
    with campaign.duets.transaction() as connection:
        row = connection.execute(
            "SELECT commit_id FROM refinement_operations WHERE operation_id = ?",
            (stale.body["operation_id"],),
        ).fetchone()
    assert row is not None and row[0] is None
    assert campaign.candidate.ref == revised.ref
    changed_payload = replace(
        attempt, body={**attempt.body, "payload": stale.body["payload"]}
    )
    with pytest.raises(DuetConflictError, match="replaced"):
        campaign.store.commit_attempt(changed_payload)


@pytest.mark.parametrize(
    "path",
    [
        "../target.py",
        "/target.py",
        "dir/../target.py",
        "dir//target.py",
        "dir\\target.py",
    ],
)
def test_scoped_candidate_namespace_rejects_aliases(path):
    with pytest.raises(ValueError):
        logical_path(path)


def test_unmeasured_edit_and_revisit_do_not_mint_credit(campaign):
    campaign.implementer()
    attempt = campaign.change(b"def solve(values):\n    raise ValueError('failed')\n")
    campaign.store.commit_attempt(attempt)
    campaign.perform(
        "close_unit",
        {
            "candidate_before_ref": campaign.initial.ref.as_record(),
            "continuation_ref": None,
        },
    )
    receipt = campaign.entries("unit")[0].record
    assert receipt.body["realized_yield"] == 0
    assert receipt.body["credit_before"] == receipt.body["credit_after"] == 0
    campaign.unit = type(campaign.unit).mint("unit", "next")
    campaign.store.commit_attempt(
        campaign.change(
            campaign.builds.read_blob(campaign.initial.body["files"]["target.py"])
        )
    )
    conflict = campaign.entries("conflict")[0].record
    assert conflict.body["kind"] == "exact_revisit"
    assert conflict.body["state"] == "suspected"
    # A revisit is visible, but does not assert that new evidence is impossible.
    assert (
        campaign.store.project(campaign.campaign_id, campaign.current_invocation).body[
            "termination"
        ]
        == "continuing"
    )


def test_designer_cannot_create_another_designer_through_an_assignment(campaign):
    campaign.implementer()
    malicious = campaign.assignment(
        "designer", campaign.implementation, campaign.current_invocation
    )
    with pytest.raises(ValueError, match="cannot create"):
        campaign.perform(
            "assign",
            {
                "assignment": malicious.as_record(),
                "invocation_id": "invocation_" + "b" * 64,
            },
        )
