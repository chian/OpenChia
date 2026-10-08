"""Real result storage across cancellation, without simulating workflow success."""

import asyncio
from threading import RLock
from types import SimpleNamespace

from agent.duet_store import DuetStore
from agent.episode_contracts import OpaqueId
from agent import openchia_build_job as jobs
from episode_runtime.records.experiments import put_record, read_record
from tests.episode_runtime.test_reasoning_workflow import _approved_request


def test_setup_cancellation_does_not_invent_a_run_attempt(tmp_path):
    request = _approved_request(tmp_path)
    receipt = SimpleNamespace(receipt_id=OpaqueId.mint("build_receipt", "completed-builder"))
    with DuetStore(tmp_path / "duet.db") as store:
        host = SimpleNamespace(store=store, identity=SimpleNamespace(duet_id=request.frozen_workflow.duet_id))
        store.append_event(duet_id=host.identity.duet_id.value, event_type="build_requested",
                           provenance="human_input", record={"build_request_id": request.build_request_id.value})
        saved_job = {"experiment_id": "not-dispatched"}
        jobs._publish_result(host, request, receipt, None, "cancelled", None, continued_job=saved_job)
        first = read_record(store, "build_job_result", build_receipt_id=receipt.receipt_id.value)
        assert first["record"]["state"] == "cancelled"
        assert read_record(store, "build_job_result_attempt", build_receipt_id=receipt.receipt_id.value, run_id=None) is None
        events = store.events(host.identity.duet_id.value)
        jobs._publish_result(host, request, receipt, None, "cancelled", None, continued_job=saved_job)
        assert store.events(host.identity.duet_id.value) == events
        assert read_record(store, "build_job_result", build_receipt_id=receipt.receipt_id.value) == first


def test_cancellation_discovers_refinement_handoff(tmp_path, monkeypatch):
    request = _approved_request(tmp_path)
    receipt = SimpleNamespace(receipt_id=OpaqueId.mint("build_receipt", "completed-builder"))
    with DuetStore(tmp_path / "duet.db") as store:
        host = SimpleNamespace(
            store=store, identity=SimpleNamespace(duet_id=request.frozen_workflow.duet_id),
            _build_receipt=receipt, _build_lock=RLock(), _build_progress={},
        )
        store.append_event(duet_id=host.identity.duet_id.value, event_type="build_requested",
                           provenance="human_input", record={"build_request_id": request.build_request_id.value})
        saved_job = {"experiment_id": "new-refinement-handoff"}

        async def cancel_after_handoff(*args, **kwargs):
            put_record(store, "build_job", duet_id=host.identity.duet_id.value,
                       build_request_id=request.build_request_id.value, record=saved_job)
            raise asyncio.CancelledError

        published = []
        persist = jobs._publish_result

        def observe_publication(*args, **kwargs):
            published.append(kwargs["continued_job"])
            return persist(*args, **kwargs)

        monkeypatch.setattr(jobs, "_execute", cancel_after_handoff)
        monkeypatch.setattr(jobs, "_publish_result", observe_publication)
        jobs.run_build_job(host, request, None, None, None, None)
        assert published == [saved_job]
        assert host._build_state == "cancelled"
        assert read_record(store, "build_job_result", build_receipt_id=receipt.receipt_id.value)["record"]["state"] == "cancelled"
