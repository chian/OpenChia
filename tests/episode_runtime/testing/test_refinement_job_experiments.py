"""A prepared refiner job uses the shared service and a pinned Duet route.

The local HTTP provider supplies an invalid choice, then is cancelled. Actual
generated refiner code, admission, broker, HTTP serialization and campaign
feedback run in-process. This proves routing and interruption, not live reasoning
or native worker confinement.
"""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from types import SimpleNamespace

import pytest

from agent.duet_contracts import DuetIdentity, content_id
from agent.duet_episode_transport import DuetEpisodeBinding, required_slots
from agent.openchia_host import OpenChiaHost
from episode_runtime.records.experiments import put_data, read_record
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.criteria import register_criterion
from episode_runtime.testing.service import ExperimentService
from episode_runtime.testing.recordings import save_recording
from function_library.refinement_checks import EXACT_VALUE
from tests.episode_runtime.testing.refinement_fixture import prepared_refiner


@contextmanager
def local_provider():
    requests, waiting, release = [], asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({
                "body": request,
                "auth": self.headers.get("Authorization"),
            })
            if len(requests) > 1:
                loop.call_soon_threadsafe(waiting.set)
                release.wait(timeout=120)
            result = json.dumps({
                "id": "fixture-call",
                "object": "chat.completion",
                "created": 0,
                "model": request["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"invalid_assignment":true}',
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            try:
                self.wfile.write(result)
            except (BrokenPipeError, ConnectionResetError):
                # The second request is deliberately cancelled by the caller.
                pass

        def log_message(self, *_args):
            return

    with ThreadingHTTPServer(("127.0.0.1", 0), Provider) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1", requests, waiting
        finally:
            release.set()
            server.shutdown()
            thread.join(timeout=5)


def job_spec(session, binding, *, completed=False):
    artifacts, builds = session.store.evidence.duets, session.store.evidence.builds
    inputs = builds.inspection_inputs_for_receipt(session.registration.build_receipt_id)
    source_owner = session.registration.duet_id.value
    receipt = {
        "artifact_id": inputs.receipt.receipt_id.value,
        "content_hash": inputs.receipt.content_hash.value,
    }
    environment = put_data(
        artifacts,
        source_owner,
        "environment",
        {"case": "prepared refiner, supplied decisions", "completed": completed},
    )
    grounding = put_data(
        artifacts,
        source_owner,
        "grounding",
        {"fact": "A cancelled run is not a completed refined build."},
    )
    scope = {
        "kind": "refinement",
        "entry_local_id": inputs.plan.root_local_id,
        "included_local_ids": sorted(node.local_id for node in inputs.plan.nodes),
        "component_definition_id": None,
        "unit_label": None,
        "invocation_path": [],
    }
    criterion = register_criterion(
        {
            "schema_version": 1,
            "build_receipt_ref": receipt,
            "environment_ref": environment,
            "requirement_key": "refiner-return",
            "description": "A complete refiner result requires its typed terminal report.",
            "scope": scope,
            "accepted_modes": ["live_fresh"],
            "input_payload": {},
            "predicate": {
                key: value
                for key, value in EXACT_VALUE.bind("measurement").as_record().items()
                if key != "name"
            },
            "observation_path": "/workflow_result/disposition" if completed else "/workflow_result/stop",
            "expected_value": "attained" if completed else True,
            "positive_controls": ["attained"] if completed else [True],
            "negative_controls": ["cancelled", "unresolved"] if completed else [False],
            "grounding_refs": [grounding],
            "limitations": ["Cancellation provides no completed-candidate verdict."],
        },
        builds=builds,
        artifacts=artifacts,
        duet_id=source_owner,
    )
    return ExperimentSpec.from_record({
        "schema_version": 1,
        "question": (
            "Does exact continuation preserve nested refinement and return its terminal report?"
            if completed else "Does the refiner preserve invalid-choice feedback and report interruption honestly?"
        ),
        "rationale": "Exercise the real refiner through the shared service; supplied decisions do not establish reasoning quality.",
        "candidate_ref": receipt,
        "build_receipt_ref": receipt,
        "environment_ref": environment,
        "scope": scope,
        "boundary": {"parent_context_ref": None, "children": "execute"},
        "start": {"kind": "fresh", "artifact_ref": None, "input_payload": {}},
        "mode": "live_fresh",
        "recording_ref": None,
        "launch_ref": binding.reference,
        "campaign_ref": session.contract.ref.as_record(),
        "requirements": [
            {
                "requirement_ref": criterion["requirement_ref"],
                "measure_ref": criterion["measure_ref"],
                "expected": "The completed refiner returns attained." if completed else "No completed build is claimed after cancellation.",
                "falsifying": "A missing or unresolved report fails." if completed else "The cancelled Run is represented as a completed refinement.",
            }
        ],
        "unresolved_questions": [
            "A successful live repair is not exercised by this experiment."
        ],
    })


@pytest.mark.asyncio
async def test_refinement_job_uses_owning_duet_without_target_launch_fallback(
    tmp_path, run_store
):
    async with prepared_refiner(tmp_path, run_store[1].runtime_identity) as session:
        artifacts, builds, runs = (
            session.store.evidence.duets,
            session.store.evidence.builds,
            session.store.evidence.runs,
        )
        inputs = builds.inspection_inputs_for_receipt(
            session.registration.build_receipt_id
        )
        identity = DuetIdentity.from_record(
            artifacts.get_duet(session.duet_id)["identity"]
        )
        with local_provider() as (url, requests, waiting):
            # An already bound Duet agent's concrete configuration. No target
            # launch exists in this fixture; no auxiliary resolver supplies it.
            runtime = {
                "model": "owning-duet-model",
                "provider": "custom",
                "base_url": url,
                "api_mode": "chat_completions",
                "session_id": "owning-duet-session",
                "api_key": "duet-only-fixture-key",
                "auth_mode": "api_key",
            }
            agent = SimpleNamespace(
                _duet_identity=identity,
                _current_main_runtime=lambda: dict(runtime),
                reasoning_config=None,
            )
            binding = DuetEpisodeBinding.from_bound_agent(
                artifacts=artifacts,
                owner_duet_id=session.duet_id,
                agent=agent,
                model_types=required_slots(inputs),
            )
            host = SimpleNamespace(
                store=artifacts,
                build_store=builds,
                run_store=runs,
                identity=identity,
                _duet_agent=agent,
                egress_credentials={},
            )
            service = OpenChiaHost.refinement_experiment_service(
                host,
                refiner_build_receipt_id=session.registration.build_receipt_id,
                evaluations=session.evaluations,
            )
            spec = job_spec(session, binding)
            unbound = ExperimentService(
                artifacts=artifacts,
                builds=builds,
                runs=runs,
                executor=session.evaluations.executor,
            )
            assert any(
                gap["kind"] == "refinement_host_binding_missing"
                for gap in unbound.preview(spec)["gaps"]
            )
            preview = service.preview(spec)
            assert preview["resolved"], preview["gaps"]
            assert preview["subject"]["owner_duet_id"] == session.duet_id
            assert preview["scope"]["boundary_origin"] == "prepared_refinement_campaign"
            ordinary = deepcopy(spec.as_record())
            ordinary["scope"]["kind"] = "workflow"
            refused = service.preview(ExperimentSpec.from_record(ordinary))
            assert not refused["resolved"]
            assert any(
                "ordinary target route" in gap["detail"] for gap in refused["gaps"]
            )
            runtime["model"] = "changed-after-binding"
            runtime["api_key"] = "changed-after-binding-key"
            task = asyncio.create_task(service.run(spec))
            provider_wait = asyncio.create_task(waiting.wait())
            try:
                done, _ = await asyncio.wait(
                    (task, provider_wait),
                    timeout=120,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if task in done:
                    pytest.fail(
                        f"Refiner returned before the second provider request: {await task!r}; requests={requests!r}"
                    )
                assert provider_wait in done, (
                    f"Refiner has not reached its second request: task={task!r}, requests={requests!r}"
                )
                task.cancel()
                result = await asyncio.wait_for(task, timeout=120)
            finally:
                provider_wait.cancel()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
            assert result["execution_status"] == "cancelled", result
            assert result["candidate_verdict"] == "unmeasured"
            assert result["refinement"]["build_status"] == "unresolved"
            assert result["refinement"]["disposition"] == "cancelled"
            assert all(row["body"]["model"] == "owning-duet-model" for row in requests)
            assert all(
                row["auth"] == "Bearer duet-only-fixture-key" for row in requests
            )
            second = json.loads(requests[1]["body"]["messages"][-1]["content"])
            assert second["assignment_context"]["last_feedback"]["reason"]
            execution = read_record(artifacts, "execution", run_id=result["run_id"])[
                "record"
            ]
            assert execution["duet_model_binding_ref"] == binding.reference
            assert execution["launch_approval_ref"] is None
            count = len(requests)
            assert (await service.run(spec))["run_id"] == result["run_id"]
            assert len(requests) == count
            changed = deepcopy(spec.as_record())
            changed["question"] = "Try the same used campaign as a different experiment"
            assert not service.preview(ExperimentSpec.from_record(changed))["resolved"]
            recording = save_recording(artifacts, runs, result["run_id"])
            replay = deepcopy(spec.as_record())
            replay.update(
                question="Does the recorded refiner control decision reproduce from its exact saved statistics?",
                mode="numerical",
                recording_ref=recording,
                launch_ref=None,
                start={
                    "kind": "saved_inputs",
                    "artifact_ref": recording,
                    "input_payload": {},
                },
                boundary={"parent_context_ref": None, "children": "reuse"},
            )
            replay_spec = ExperimentSpec.from_record(replay)
            replay_plan = service.preview(replay_spec)
            assert replay_plan["resolved"], replay_plan["gaps"]
            with session.view() as view:
                campaign_before = dict(view.head)
            calculation = await service.run(replay_spec)
            assert calculation["execution_status"] == "evaluated"
            assert calculation["controller_comparison"] == "reproduced"
            assert calculation["candidate_verdict"] == "unmeasured"
            assert not calculation["progress"]["admitted"]
            assert all(
                trace["family"] == "refinement" and trace["units"]
                for trace in calculation["invocations"]
            )
            with session.view() as view:
                assert dict(view.head) == campaign_before
            assert len(requests) == count
            assert (await service.run(replay_spec))["result_ref"] == calculation[
                "result_ref"
            ]
            persisted = json.dumps(
                artifacts.get_artifact(binding.reference["artifact_id"])["record"]
            )
            assert "duet-only-fixture-key" not in persisted
            assert "changed-after-binding-key" not in persisted


def test_refinement_numerical_snapshot_rejects_incomplete_or_inconsistent_history():
    from numeric_control_library.credit_assignment import (
        CreditObservation,
        CreditSnapshot,
        MarginalHypervolumeAssignment,
        ResultColumnSchema,
    )
    from iterative_episode_refiner.control import CHANNEL, recompute_numerical_step

    assignment = MarginalHypervolumeAssignment(ResultColumnSchema((CHANNEL,), (0.0,)))
    identity = content_id("result", {"fact": "admitted"}).value
    assignment.admit(CreditObservation.observed({CHANNEL: (identity,)}))
    valid = assignment.state().as_record()
    restored = CreditSnapshot.from_record(valid)
    assert restored == assignment.state()
    invalid = deepcopy(valid)
    invalid["incidence_by_position"][0][0][1] = 0
    with pytest.raises(ValueError, match="disagrees"):
        CreditSnapshot.from_record(invalid)
    with pytest.raises(ValueError, match="invalid fields"):
        CreditSnapshot.from_record({**valid, "invented_history": []})
    with pytest.raises(ValueError, match="lacks its prior opportunity"):
        recompute_numerical_step({"numeric_step": {"admission": {"before": valid}}})
