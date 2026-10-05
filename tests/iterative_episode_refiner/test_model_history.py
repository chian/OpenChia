"""History projection invariants over stored records, not a reasoning benchmark."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from agent.duet_contracts import content_id
from episode_runtime.protocol import episode_id_for_path
from iterative_episode_refiner.campaign_store import CampaignView
from iterative_episode_refiner.context import local_context
from iterative_episode_refiner.model_history import iteration_history
from iterative_episode_refiner.records import RefinementRecord
from tests.iterative_episode_refiner.test_reports import report_campaign  # noqa: F401


@pytest.fixture
def history_campaign(report_campaign):
    store, campaign_id, parent, child, baseline, current, _, _ = report_campaign
    with store.duet_store.transaction() as connection:
        view = CampaignView(connection, campaign_id)
        contract = view.contract
        catalog = store.put_data(view.head["duet_id"], "requirement_catalog", {
            "requirements": [{
                "requirement_key": key, "source_target": f"/requirements/{key}",
                "evidence_scope": "behavior",
            } for key in ("ordered", "unique")],
        })
        contract = replace(contract, body={**contract.body, "requirement_catalog_ref": catalog.as_record()})
        store._put(connection, view.head["duet_id"], contract)
        connection.execute("UPDATE refinement_campaign_heads SET contract_id = ? WHERE campaign_id = ?",
                           (contract.artifact_id.value, campaign_id.value))
        call = SimpleNamespace(
            invocation_id=child, assignment=view.entry("invocation", child.value).record,
            path=(("parts", parent.value), ("implementer", child.value)),
        )
    session = SimpleNamespace(registration=SimpleNamespace(logical_run_id=content_id("run", "history")))
    return store, campaign_id, call, session, baseline, current, parent


def test_completed_history_retains_old_units_and_excludes_other_invocations(history_campaign):
    store, campaign_id, call, session, baseline, current, parent = history_campaign
    expected = []
    with store.duet_store.transaction() as connection:
        view = CampaignView(connection, campaign_id)
        for ordinal, invocation in enumerate([call.invocation_id] * 12 + [parent]):
            unit = content_id("unit", ordinal)
            record = RefinementRecord("unit_receipt", campaign_id, {
                "assignment_ref": call.assignment.ref.as_record(),
                "invocation_id": invocation.value, "logical_unit_id": unit.value,
                "ordinal": ordinal, "stage_receipt_refs": [],
                "candidate_before_ref": baseline.ref.as_record(),
                "candidate_after_ref": current.ref.as_record(),
                "evaluation_refs": [], "assessment_refs": [], "prerequisite_assessment_refs": [],
                "invalidated_check_keys": [], "conflict_refs": [], "lesson_refs": [],
                "semantic_fact_keys": [], "credit_before": 0, "credit_after": 0,
                "realized_yield": 0, "continuation_ref": None,
                "disposition": "continuing", "decision_request_ref": None,
            }, view.contract.producer_ref, invocation_id=invocation, logical_unit_id=unit)
            store._put(connection, view.head["duet_id"], record)
            connection.execute("INSERT INTO refinement_index VALUES (?, 'unit', ?, ?, 'active', ?)",
                               (campaign_id.value, unit.value, record.artifact_id.value, ordinal))
            if invocation == call.invocation_id:
                expected.append(record)
        before = dict(view.head)
        history = iteration_history(session, view, call)
        assert history["completed_units"] == len(expected)
        assert [row["ordinal"] for row in history["units"]] == [record.body["ordinal"] for record in expected]
        assert local_context(view, call.invocation_id).body["recent_unit_refs"] == tuple(record.ref.as_record() for record in expected)
        assert dict(CampaignView(connection, campaign_id).head) == before
        assert "child_reports" not in history


def test_proposal_history_retains_outputs_and_rejections_across_physical_runs(history_campaign):
    store, campaign_id, call, session, _, _, _ = history_campaign
    episode = episode_id_for_path(session.registration.logical_run_id, [
        {"grain": grain, "key": key} for grain, key in call.path
    ])
    expected = []
    with store.duet_store.transaction() as connection:
        view = CampaignView(connection, campaign_id)
        for ordinal in range(12):
            output = f'{{"approach": "attempt {ordinal}"}}'
            proposal = store.put_data(view.head["duet_id"], "model_proposal", {
                "task": "change", "run_id": f"physical_attempt_{ordinal // 6}",
                "event": {"episode_id": episode.value, "payload": {"response_text": output}},
            })
            reason = f"Missing evidence for attempt {ordinal}" if ordinal % 2 == 0 else None
            if reason is not None:
                store.put_data(view.head["duet_id"], "proposal_rejection", {
                    "proposal_ref": proposal.as_record(), "reason": reason,
                    "assignment_ref": call.assignment.ref.as_record(), "task": "change",
                })
            expected.append({"task": "change", "output": output,
                             "status": "rejected" if reason else "recorded", "rejection_reason": reason})
        store.put_data(view.head["duet_id"], "model_proposal", {
            "task": "change", "event": {"episode_id": "another-episode", "payload": {"response_text": "not visible"}},
        })
        history = iteration_history(session, view, call)
        assert history["proposals"] == expected
        assert history["units"] == []  # Proposals alone are not completed units or credit.
