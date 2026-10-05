"""State invariants only; not a claim that a model can design or repair Episodes."""

from dataclasses import replace

import pytest

from agent.duet_store import DuetConflictError
from iterative_episode_refiner.records import logical_path


@pytest.mark.asyncio
async def test_candidate_cas_and_audited_retry_preserve_exact_baseline(campaign):
    campaign.implementer()
    original = campaign.candidate
    attempt = campaign.change(b"# First unmeasured revision\n" + campaign.initial_source)
    commit = campaign.store.commit_attempt(attempt)
    revised = campaign.candidate
    assert revised.ref != original.ref
    assert (
        campaign.builds.read_blob(original.body["files"][campaign.source_path])
        == campaign.initial_source
    )
    assert campaign.store.commit_attempt(attempt).ref == commit.ref
    assert campaign.candidate.ref == revised.ref
    stale = campaign.change(b"# Stale revision\n" + campaign.initial_source, before=original)
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


@pytest.mark.asyncio
async def test_unmeasured_edit_and_revisit_do_not_mint_credit(campaign):
    campaign.implementer()
    attempt = campaign.change(b"# Unmeasured edit\n" + campaign.initial_source)
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
    campaign.store.commit_attempt(campaign.change(campaign.initial_source))
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
    campaign.perform(
        "close_unit",
        {"candidate_before_ref": receipt.body["candidate_after_ref"], "continuation_ref": None},
    )
    revisited = campaign.entries("unit")[-1].record
    assert revisited.body["realized_yield"] == 0
    assert revisited.body["credit_before"] == revisited.body["credit_after"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_role", ("designer", "implementer"))
async def test_specialists_cannot_create_designers_through_an_assignment(campaign, parent_role):
    getattr(campaign, parent_role)()
    malicious = campaign.assignment("designer", campaign.current_assignment)
    with pytest.raises(ValueError, match="cannot create"):
        campaign.perform(
            "assign",
            {
                "assignment": malicious.as_record(),
                "invocation_id": "invocation_" + "b" * 64,
            },
        )
