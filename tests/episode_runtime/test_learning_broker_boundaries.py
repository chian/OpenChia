"""Host-boundary regressions; these do not claim live confinement coverage."""

import asyncio
from contextvars import ContextVar
import json
from pathlib import Path
import threading

import pytest

from episode_builder.service import EpisodeBuilder
from episode_builder.store import BuildStore
from episode_runtime import executor as executor_module
from episode_runtime.broker import ScopedModelBroker
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunRegistration
from episode_runtime.executor import ExecutorResources, SystemdRunExecutor
from episode_runtime.learning_broker import LearningBroker
from episode_runtime.linker import RuntimeLinkError
from episode_runtime.store import RunStore, RunStoreNotFound
from function_library.epistemic_schemas import identity, model_call_id
from function_library.reasoning import ReasoningSource
from handoff_library import DuetLaunchRequest
from llm_call_library.transport import ModelTransportResponse, model_transport_scope

from conftest import claim_store, oid
from test_reasoning_workflow import _approved_request, _module_response, _plan_response

pytestmark = [pytest.mark.platforms("linux"), pytest.mark.asyncio]


async def _broker(tmp_path, run_store):
    request = _approved_request(tmp_path)
    builder = BuildStore(tmp_path)

    async def materialization(call):
        prompt = json.loads(call.messages[-1]["content"])
        value = _plan_response(prompt) if "node" in prompt else _module_response(prompt)
        return ModelTransportResponse(json.dumps(value), {})

    with model_transport_scope(materialization):
        built = await EpisodeBuilder(store=builder).build(request)
    assert built.status == "materialized"
    manifest = builder.read_manifest(built.manifest_id)
    registration = RunRegistration.from_admitted_build(
        build_request=request,
        build_attempt=builder.read_build_attempt(built.build_attempt_id),
        build_receipt=built,
        build_manifest=manifest,
        launch_request=DuetLaunchRequest(
            oid("launch").value,
            request.frozen_workflow.artifact_id.value,
            oid("goal").value,
            {},
        ),
        runtime_identity=run_store[1].runtime_identity,
        runtime_policy=run_store[1].runtime_policy,
    )
    store, registration, _ = claim_store(tmp_path / "broker", registration)
    broker = LearningBroker(
        store, registration, builder.source_package_path(manifest.manifest_id)
    )
    episode_id = oid("started_reasoning")
    store.append_event(
        run_id=registration.run_id,
        origin=RunEventOrigin.WORKER,
        sender_sequence=0,
        kind=RunEventKind.EPISODE_STARTED,
        episode_id=episode_id,
        payload={"grain": broker.root_grain},
    )
    return broker, episode_id.value


async def test_invalid_package_cannot_leave_an_unclaimed_registration(
    tmp_path, run_store, monkeypatch
):
    registration = run_store[1]
    store = RunStore(tmp_path / "fresh")
    package = tmp_path / registration.manifest_id.value
    package.mkdir()  # Real malformed package: missing immutable metadata.
    executor = SystemdRunExecutor(
        run_store=store,
        repository_root=Path(__file__).resolve().parents[2],
        resources=ExecutorResources(None, None, 100, None, 100000),
    )
    # This probe covers preflight ordering, not interpreter attestation.
    monkeypatch.setattr(
        executor_module, "verify_runtime_identity", lambda *a, **k: None
    )
    monkeypatch.setattr(
        executor_module, "load_verified_bootstrap_program", lambda *a, **k: "unused"
    )

    async def no_model(call):
        raise AssertionError("preflight must not call a model")

    with pytest.raises(RuntimeLinkError, match="omits"):
        await executor.execute(
            registration=registration,
            source_package_path=package,
            model_broker=ScopedModelBroker(no_model),
        )
    with pytest.raises(RunStoreNotFound):
        store.read_registration(registration.run_id)


@pytest.mark.parametrize("basis", ["forged", "model", "host_denial"])
async def test_blocked_outcome_requires_a_committed_producer_or_host_denial(
    tmp_path, run_store, basis
):
    broker, episode = await _broker(tmp_path, run_store)
    bundle = await broker(episode, "retrieve", {})
    action = "undeclared" if basis == "host_denial" else bundle["allowed_actions"][0]
    selection = await broker(
        episode,
        "select",
        {
            "ordinal": 0,
            "action_class": action,
            "action_inputs": {},
            "retry_reason": "",
        },
    )
    result = ReasoningSource._blocked_result(selection, "action unavailable")
    producer = identity("call", {"selection": selection})
    if basis == "model":
        text = json.dumps(result)
        producer = model_call_id(text, "episode_structured_json_reasoning", {})
        broker.store.append_event(
            run_id=broker.registration.run_id,
            origin=RunEventOrigin.HOST,
            sender_sequence=0,
            kind=RunEventKind.MODEL_RESPONDED,
            episode_id=oid("started_reasoning"),
            payload={"producer_call_id": producer, "response_text": text},
        )
    submission = {"ordinal": 0, "result": result, "producer_call_id": producer}
    if basis == "forged":
        with pytest.raises(ValueError, match="producing call|host denial"):
            await broker(episode, "submit", submission)
        assert (await broker(episode, "retrieve", {}))["last_receipt"] is None
    else:
        receipt = await broker(episode, "submit", submission)
        assert receipt["terminal_state"] == "blocked" and not receipt["stop"]
        assert receipt["measurement"]["realized_yield"] == 0


async def test_journal_work_runs_off_loop_with_context_preserved(
    tmp_path, run_store, monkeypatch
):
    broker, episode = await _broker(tmp_path, run_store)
    loop_thread = threading.get_ident()
    scope = ContextVar("broker_test_scope", default=None)
    token = scope.set("owning-request")
    original = broker.store._load_event_chain_locked

    def read(*args, **kwargs):
        assert threading.get_ident() != loop_thread
        assert scope.get() == "owning-request"
        return original(*args, **kwargs)

    monkeypatch.setattr(broker.store, "_load_event_chain_locked", read)
    try:
        bundle = await asyncio.wait_for(broker(episode, "retrieve", {}), 10)
        assert bundle["next_ordinal"] == 0
        selection = await broker(
            episode,
            "select",
            {
                "ordinal": 0,
                "action_class": "undeclared",
                "action_inputs": {},
                "retry_reason": "",
            },
        )
        await broker(
            episode,
            "submit",
            {
                "ordinal": 0,
                "result": ReasoningSource._blocked_result(
                    selection, "action unavailable"
                ),
                "producer_call_id": identity("call", {"selection": selection}),
            },
        )
    finally:
        scope.reset(token)
