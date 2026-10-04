"""A durable claim permits completing its exact attempt, not spending it twice."""

from dataclasses import replace

import pytest

from episode_builder._contract_base import BuildAttempt
from episode_builder.service import _materializer_identity
from episode_builder.store import BuildArtifactConflictError, BuildStore
from llm_call_library import CallOptions
from tests.episode_runtime.test_reasoning_workflow import _approved_request


def test_interrupted_claim_keeps_nonce_diagnostic_and_identical_retry(tmp_path, monkeypatch):
    request = _approved_request(tmp_path)
    store = BuildStore(tmp_path)
    store.put_build_request(request)
    attempt = BuildAttempt(
        build_request_id=request.build_request_id,
        materializer=_materializer_identity(CallOptions(model_type="planner"), CallOptions(model_type="writer")),
        nonce="a" * 64,
    )
    persist = store._put_record

    def lose_process_after_claim(*args):
        raise OSError("interrupted before attempt publication")

    monkeypatch.setattr(store, "_put_record", lose_process_after_claim)
    with pytest.raises(OSError, match="interrupted before attempt"):
        store.put_build_attempt(attempt)
    assert store.build_request_consumed(request.build_request_id)
    assert store.attempts_for_build_request(request.build_request_id) == ()
    monkeypatch.setattr(store, "_put_record", persist)
    with pytest.raises(BuildArtifactConflictError, match="fresh request nonce"):
        store.put_build_attempt(replace(attempt, nonce="b" * 64))
    assert store.put_build_attempt(attempt) == attempt.build_attempt_id
    assert store.put_build_attempt(attempt) == attempt.build_attempt_id
    assert store.attempts_for_build_request(request.build_request_id) == (attempt,)
