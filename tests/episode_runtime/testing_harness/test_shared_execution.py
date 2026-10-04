"""Real approval/build/store dispatch checks, not behavioral acceptance.

The executor deliberately raises before launching anything. This proves that
missing terminal evidence cannot be mistaken for completion or trigger a second
launch. It does not claim candidate execution, model reasoning or confinement.
"""

import pytest

from agent.duet_store import DuetStore
from episode_runtime.broker import (
    ModelBrokerError,
    ScopedModelBroker,
    model_request_record,
)
from episode_runtime.store import RunStore
from episode_runtime.testing_harness.execution import (
    ExecutionPending,
    RunExecution,
    register_build,
)
from episode_runtime.testing_harness.inputs import workflow_template
from episode_runtime.records.experiments import put_data
from llm_call_library import ModelTransportRequest, ModelTransportResponse
from tests.episode_builder.test_repeatable_call_materialization import build, call


class LaunchUnavailable:
    def __init__(self, runs, identity):
        self.run_store = runs
        self.identity = identity
        self.calls = []

    def inspect_runtime_identity(self, **kwargs):
        return self.identity

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError("injected executor-unavailable failure")


@pytest.mark.asyncio
async def test_shared_dispatch_preserves_exact_intent_and_does_not_relaunch(
    tmp_path, run_store
):
    request, builds, receipt = await build(tmp_path, ())
    inputs = builds.inspection_inputs_for_receipt(receipt.receipt_id)
    runs = RunStore(tmp_path / "experiment-runs")
    executor = LaunchUnavailable(runs, run_store[1].runtime_identity)
    registration, package = register_build(
        executor,
        builds,
        inputs,
        workflow_template(request.frozen_workflow),
        run_store[1].runtime_policy,
    )
    with DuetStore(tmp_path / "duet.db") as artifacts:
        intent = put_data(
            artifacts,
            registration.duet_id.value,
            "intent",
            {
                "question": "Does the admitted inquiry return a problem frontier?",
                "build_receipt_ref": {
                    "artifact_id": receipt.receipt_id.value,
                    "content_hash": receipt.content_hash.value,
                },
            },
        )
        execution = RunExecution(
            artifacts=artifacts, builds=builds, runs=runs, executor=executor
        )
        arguments = dict(
            registration=registration,
            source_package_path=package,
            intent_ref=intent,
            model_broker=None,
            http_broker=None,
        )
        from episode_runtime.http_broker import ScopedHttpBroker
        from episode_runtime.testing_harness.playback import RecordingCursor

        hidden_replay = ScopedHttpBroker(
            policy=registration.egress_policy,
            credentials={},
            transport=None,
            max_frame_bytes=registration.runtime_policy.max_frame_bytes,
            recording=RecordingCursor({"exchanges": []}, "source", "target"),
        )
        with pytest.raises(ValueError, match="frozen experiment mode"):
            await execution.execute(**{**arguments, "http_broker": hidden_replay})
        assert (
            execution.status(artifacts, runs, registration.run_id.value)[
                "execution_status"
            ]
            == "not_dispatched"
        )
        with pytest.raises(ValueError, match="reference is missing"):
            await execution.execute(**{
                **arguments,
                "intent_ref": {**intent, "content_hash": "sha256:" + "0" * 64},
            })
        assert executor.calls == []
        with pytest.raises(RuntimeError, match="injected executor-unavailable"):
            await execution.execute(**arguments)
        with pytest.raises(ExecutionPending, match="do not relaunch"):
            await execution.execute(**arguments)
        assert len(executor.calls) == 1
        events = artifacts.events(registration.duet_id.value)
        dispatched = [
            row
            for row in events
            if row["event_type"] == "experiment_execution_dispatched"
        ]
        assert len(dispatched) == 1
        record = artifacts.get_artifact(dispatched[0]["record"]["execution_id"])[
            "record"
        ]
        assert record["registration"] == registration.as_record()
        assert record["intent_ref"] == intent
        assert "candidate_verdict" not in record  # dispatch never fabricated a pass
        status = RunExecution.status(artifacts, runs, registration.run_id.value)
        assert status["execution_status"] == "terminal_evidence_unavailable"
        assert status["candidate_verdict"] == "unmeasured"
        assert not status["progress"]["admitted"]
        assert status["intent_ref"] == intent


@pytest.mark.asyncio
async def test_broker_resolves_only_approved_repeated_paths(tmp_path):
    _, builds, receipt = await build(tmp_path, (call(),))
    plan = builds.read_plan(receipt.plan_id)
    received = []

    async def transport(request):
        received.append(request)
        return ModelTransportResponse(text="{}", route={})

    broker = ScopedModelBroker.from_plan(transport, plan)
    request = model_request_record(
        ModelTransportRequest(
            task="episode_structured_json_reasoning",
            model_type="selector",
            messages=(
                {"role": "system", "content": "Return JSON."},
                {"role": "user", "content": "Evaluate this action."},
            ),
            temperature=None,
            max_tokens=None,
            timeout=None,
            reasoning_config=None,
            main_runtime=None,
        )
    )
    grain = plan.nodes[0].grain_name
    path = [{"grain": grain, "key": key} for key in ("root", "part", "subpart")]
    await broker(request, episode_path=path)
    assert received[-1].episode_local_id == plan.root_local_id
    with pytest.raises(ModelBrokerError, match="outside the admitted workflow"):
        await broker(
            request, episode_path=[*path, {"grain": "invented", "key": "child"}]
        )
    assert len(received) == 1
