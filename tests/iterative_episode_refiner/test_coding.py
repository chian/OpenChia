"""Real broker, files, campaign and admission; supplied coding-session actions.

These tests exercise the integration boundary, not a model's coding ability.
No supplied final message or diagnostic result is accepted as progress credit.
"""

import asyncio
import json
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.duet_contracts import digest_record
from agent.refinement_coding import CodingTurn
from episode_runtime.broker import ScopedModelBroker, model_request_record
from episode_runtime.protocol import episode_id_for_path
from iterative_episode_refiner import coding
from iterative_episode_refiner.runtime import Invocation
from iterative_episode_refiner.runtime_proposals import admit_proposal
from llm_call_library.transport import ModelTransportRequest


def prepared(campaign, monkeypatch, factory):
    assignment = campaign.implementer()
    session = campaign.session
    root = session.calls[session.root_id]
    path = (*root.path, (session.nodes["designer"].grain_name, "design"),
            (session.nodes["implementer"].grain_name, campaign.current_invocation.value))
    wire_path = [{"grain": grain, "key": key} for grain, key in path]
    episode_id = episode_id_for_path(session.registration.logical_run_id, wire_path)
    call = Invocation(campaign.current_invocation, assignment, path, root.goal,
                      unit_id=campaign.unit, candidate_before=campaign.candidate.ref)
    session.calls[episode_id.value] = call
    binding = SimpleNamespace(
        reference={"artifact_id": "fixture-binding", "content_hash": digest_record({}).value},
        owner_duet_id=session.duet_id, api_key="fixture-not-a-credential",
        record={"session_id": "fixture-owner", "model_types": ["refinement"], "route": {
            "provider": "fixture", "model": "fixture", "base_url": "http://localhost.invalid",
            "api_mode": "codex_responses",
        }},
    )
    async def other_model(_request):
        pytest.fail("Implementer change must not fall through to the old JSON emitter")

    receipts = []
    monkeypatch.setattr(coding, "coding_backend", lambda _binding: factory)
    transport = coding.RefinementCodingTransport(session=session, binding=binding,
                                                 transport=other_model, record_attempt=receipts.append)
    broker = ScopedModelBroker.from_plan(transport, session.plan)
    request = ModelTransportRequest("episode_structured_json_reasoning", "refinement",
        ({"role": "system", "content": "Implement the scoped assignment."},
         {"role": "user", "content": json.dumps({"task": "change"})}), None, None, None, None, None)
    return session, call, broker, model_request_record(request), wire_path, receipts


@pytest.mark.asyncio
async def test_coding_diff_uses_ordinary_admission_and_unmeasured_credit(campaign, monkeypatch):
    sessions = []
    class Editor:
        runtime_id = "fixture_coding_backend"
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            sessions.append(self)
        def ensure_started(self):
            return "coding-thread"
        def process_identity(self):
            return {"pid": 2147483647, "process_start_time": 1.0}
        def run_turn(self, prompt, *, turn_timeout):
            assert turn_timeout is None
            path = Path(self.kwargs["workspace"]) / campaign.source_path
            path.write_text(path.read_text(encoding="utf-8") + "\n# Actual fixture edit\n", encoding="utf-8")
            return CodingTurn(final_text="I claim success and 100 credit", thread_id="coding-thread", turn_id="turn")
        def close(self):
            self.closed = True

    session, call, broker, request, path, receipts = prepared(campaign, monkeypatch, Editor)
    before = campaign.candidate
    response = await broker(request, episode_path=path)
    assert sessions[0].closed
    assert campaign.candidate.ref == before.ref  # Coding is not admission.
    proposal = json.loads(response.text)
    assert proposal["files"][0]["content"].endswith("# Actual fixture edit\n")
    producer = session.put_data("fixture_coding_response", {"text": response.text, "route": dict(response.route)})
    admit_proposal(session, call, "change", proposal, producer)
    assert campaign.candidate.ref != before.ref
    assert campaign.builds.read_blob(campaign.candidate.body["files"][campaign.source_path]).decode() == proposal["files"][0]["content"]
    campaign.perform("close_unit", {"candidate_before_ref": before.ref.as_record(), "continuation_ref": None})
    assert campaign.entries("unit")[-1].record.body["realized_yield"] == 0
    assert receipts[-1]["state"] == "succeeded"
    assert response.route["coding_turn_ref"]
    assert response.route["coding_runtime"] == Editor.runtime_id
    # Scope is stamped by the broker, not supplied in the serialized request.
    assert "episode_path" not in request
    with pytest.raises(ValueError, match="no host-admitted assignment"):
        await broker(request, episode_path=[*path[:-1], {**path[-1], "key": "forged"}])


@pytest.mark.asyncio
async def test_cancel_joins_writer_and_resume_preserves_unadmitted_edits(campaign, monkeypatch):
    started, stopped = threading.Event(), threading.Event()
    sessions = []
    class InterruptedEditor:
        runtime_id = "fixture_coding_backend"
        def __init__(self, **kwargs):
            self.kwargs, self.interrupt = kwargs, threading.Event()
            sessions.append(self)
        def ensure_started(self):
            return "same-coding-thread"
        def process_identity(self):
            return {"pid": 2147483647, "process_start_time": 1.0}
        def request_interrupt(self):
            self.interrupt.set()
        def run_turn(self, prompt, *, turn_timeout):
            path = Path(self.kwargs["workspace"]) / campaign.source_path
            if len(sessions) == 1:
                path.write_text(path.read_text(encoding="utf-8") + "\n# Unfinished edit\n", encoding="utf-8")
                started.set()
                assert self.interrupt.wait(10)
                return CodingTurn(interrupted=True, thread_id="same-coding-thread")
            assert self.kwargs["resume_thread_id"] == "same-coding-thread"
            assert path.read_text(encoding="utf-8").endswith("# Unfinished edit\n")
            return CodingTurn(thread_id="same-coding-thread", turn_id="resumed")
        def close(self):
            stopped.set()

    session, call, broker, request, path, receipts = prepared(campaign, monkeypatch, InterruptedEditor)
    original = campaign.candidate.ref
    pending = asyncio.create_task(broker(request, episode_path=path))
    assert await asyncio.to_thread(started.wait, 10)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert stopped.is_set() and campaign.candidate.ref == original
    assert receipts[-1]["state"] == "cancelled"
    # A new transport (as after process continuation) discovers shared records,
    # not an in-memory session or a bespoke replay mechanism.
    fresh = replace(broker, transport=coding.RefinementCodingTransport(
        session=session, binding=broker.transport.binding, transport=broker.transport.transport,
        record_attempt=receipts.append))
    result = await fresh(request, episode_path=path)
    assert json.loads(result.text)["files"][0]["content"].endswith("# Unfinished edit\n")
    assert campaign.candidate.ref == original
