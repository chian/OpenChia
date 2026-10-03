"""Approved auxiliary sources use the same Episode-authored experiment path.

Assignments and model choices are supplied. Builder admission, model-response
authentication, campaign operations, the linked source loop, shared service and
measurement are real. This proves neither live reasoning nor OS confinement.
"""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from agent.duet_contracts import content_id
from agent.episode_contracts import OpaqueId
from agent.episode_launch import resolve_launch
from episode_builder.service import EpisodeBuilder
from episode_library.testing import DESIGN as TESTING_DESIGN
from episode_runtime import protocol
from episode_runtime.broker import ScopedModelBroker
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunTerminalStatus
from episode_runtime.exchanges import broker_model_request
from episode_runtime.records.catalog import HistoryQuery, history
from episode_runtime.records.experiments import put_data, read_record
from episode_runtime.testing.contracts import ExperimentSpec
from episode_runtime.testing.execution import register_build
from episode_runtime.testing.inputs import workflow_template
from episode_runtime.testing.recordings import save_recording
from episode_runtime.testing.service import ExperimentService
from episode_runtime.testing.session import ExperimentAccessError, ExperimentSession
from function_library.testing_contract import TestingContract as Access
from handoff_library import ParentRequest
from iterative_episode_refiner.evaluation_experiments import _validate
from iterative_episode_refiner.records import Ref
from iterative_episode_refiner.runtime_proposals import (
    _finding,
    _inherited_draft,
    assign_child,
)
from llm_call_library import CallOptions, ModelTransportResponse
from llm_call_library.transport import model_transport_scope
from tests.episode_runtime.conftest import claim_store, oid
from tests.episode_runtime.test_epistemic_learning import attempt
from tests.episode_runtime.test_model_request_thaw import REQUEST
from tests.episode_runtime.test_reasoning_workflow import (
    _approved_request, _module_response, _plan_response,
)
from tests.episode_runtime.testing.launch_fixture import FixtureLaunchHost
from tests.episode_runtime.testing.refinement_fixture import prepared_refiner
from tests.episode_runtime.testing.test_recorded_execution import _Channel


async def _assert_worker_discovery(service, raw, result, saved, tmp_path):
    """A fixture-approved testing session reads only its assigned source tests."""
    target = {key: raw[key] for key in (
        "candidate_ref", "build_receipt_ref", "environment_ref", "launch_ref", "campaign_ref",
    )}
    target.update(
        requirements=[{key: item[key] for key in ("requirement_ref", "measure_ref")} for item in raw["requirements"]],
        recording_refs=[saved], parent_context_refs=[saved],
    )
    source_inputs = service.builds.inspection_inputs_for_receipt(raw["build_receipt_ref"]["artifact_id"])
    contract = replace(
        source_inputs.build_request.frozen_workflow.workflow.episodes[0].contract,
        execution_capability_names=("episode_testing",),
        testing=Access({"source": target}, ("workflow",), ("live_fresh", "numerical")),
    )
    request = _approved_request(
        tmp_path, duet_id=oid("source_tester"), spec=contract,
        reference=TESTING_DESIGN, allowed_capabilities=("episode_testing",),
    )

    async def builder_model(call):
        prompt = json.loads(call.messages[-1]["content"])
        value = _plan_response(prompt, testing=True) if "node" in prompt else _module_response(prompt)
        return ModelTransportResponse(text=json.dumps(value), route={})

    with model_transport_scope(builder_model):
        receipt = await EpisodeBuilder(
            store=service.builds, planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"selector": {}, "executor": {}},
        ).build(request)
    assert receipt.materialized, [row.as_record() for row in receipt.deficits]
    inputs = service.builds.inspection_inputs_for_receipt(receipt.receipt_id)
    source = service.runs.read_registration(OpaqueId(result["run_id"]))
    registration, _ = register_build(
        service.executor, service.builds, inputs,
        workflow_template(request.frozen_workflow), source.runtime_policy,
    )
    claim_store(service.executor.root, registration, store=service.runs)
    path = [{"grain": inputs.plan.nodes[0].grain_name, "key": registration.run_id.value}]
    caller = protocol.episode_id_for_path(registration.run_id, path)
    service.runs.append_event(
        run_id=registration.run_id, origin=RunEventOrigin.WORKER, sender_sequence=0,
        kind=RunEventKind.EPISODE_STARTED, episode_id=caller, payload={"episode_path": path},
    )
    testing = ExperimentSession(service=service, registration=registration, inputs=inputs)

    async def exchange(operation, payload):
        return await testing.exchange(
            episode_id=caller, episode_path=path, operation=operation, payload=payload,
        )

    selection = {"source": {"kind": "experiment", "experiment_id": result["experiment_id"]}, "query": {"kind": "units"}}
    with pytest.raises(ExperimentAccessError, match="not assigned"):
        await exchange("inventory", selection)
    assert (await exchange("preview", {"spec": raw}))["resolved"]
    assert (await exchange("run", {"spec": raw}))["run_id"] == result["run_id"]
    inventory = await exchange("inventory", selection)
    assert inventory["run_id"] == result["run_id"] and inventory["items"]
    page = await exchange("history", {"query": {}})
    row, = page["items"]
    reports = await exchange("history", {"query": row["reports_query"]})
    report, = reports["items"]
    assert report["is_current"] and report["measurement_ref"] == result["measurement"]["measurement_ref"]
    numerical = deepcopy(raw)
    numerical.update(
        mode="numerical", recording_ref=saved, launch_ref=None,
        start={"kind": "saved_inputs", "artifact_ref": saved, "input_payload": {}},
        boundary={"parent_context_ref": saved, "children": "reuse"},
    )
    diagnostic = await exchange("run", {"spec": numerical})
    assert diagnostic["execution_status"] == "evaluated", diagnostic
    recorded_inventory = await exchange("inventory", {
        "source": {"kind": "experiment", "experiment_id": diagnostic["experiment_id"]},
        "query": {"kind": "units"},
    })
    assert recorded_inventory["run_id"] == result["run_id"]
    assert recorded_inventory["items"] == inventory["items"]
    service.runs.finalize_run(
        run_id=registration.run_id, origin=RunEventOrigin.HOST, sender_sequence=0,
        terminal_status=RunTerminalStatus.CANCELLED,
        typed_status={"reason": "Supplied testing-session discovery fixture ended."},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source_kind", ("instrument_build", "reference_workflow"))
async def test_campaign_source_requires_episode_experiment_and_preserves_its_identity(
    tmp_path, run_store, monkeypatch, source_kind
):
    async with prepared_refiner(
        tmp_path,
        run_store[1].runtime_identity,
        campaign_source_kind=source_kind,
        runtime_check={
            "purpose": "support",
            "expected": 0,
            "observation_path": "/payload/typed_status/workflow_result/measurement/credit_after",
            "grounding": {
                "claim": "Failure with no proposed lesson or entity admits no state and earns zero credit.",
                "positive": 0,
                "negative": 1,
            },
        },
    ) as session:
        evaluations = session.evaluations
        artifacts, builds, runs = (
            session.store.evidence.duets,
            evaluations.builder.store,
            session.store.evidence.runs,
        )
        launch = resolve_launch({
            "project": "campaign-source-fixture",
            "project_root": str(tmp_path),
            "env_files": [],
            "routes": {"supplied": {
                "provider": "custom", "model": "supplied-source-answers",
                "base_url": "https://example.org/v1", "api_mode": "chat_completions",
                "auth": {"kind": "none"},
            }},
            "model_slots": {"selector": "supplied", "executor": "supplied"},
            "builder_slots": {"planning": "selector", "emission": "executor"},
        })
        FixtureLaunchHost(artifacts, builds, session.duet_id).approve_fixture(launch)
        evaluations.target_launch_ref = put_data(artifacts, session.duet_id, "launch", launch.record)
        service = ExperimentService(
            artifacts=artifacts, builds=builds, runs=runs, executor=evaluations.executor,
        )
        claim_store(runs.root, session.registration, store=runs)
        root = session.calls[session.root_id]

        async def host(episode_id, call, operation, payload):
            return await session.exchange(
                episode_id=OpaqueId(episode_id),
                episode_path=[{"grain": grain, "key": key} for grain, key in call.path],
                operation=operation, payload=payload,
            )

        await host(session.root_id, root, "begin_unit", {"role": "parts"})
        with session.view() as view:
            check = view.entry("check", session.policy["check_refs"][0]["artifact_id"]).record
            original_candidate = view.candidate.ref.as_record()
            original_head = view.candidate.as_record()
            target_receipt = view.data(Ref.from_record(session.contract.body["initial_build_receipt_ref"]))
        draft = _inherited_draft(root, "support", goal="Check the approved source without substituting it for the target.")
        draft["contribution_requirement_keys"] = [check.body["requirement_key"]]
        selection = assign_child(session, root, draft, session.contract.producer_ref)
        await host(session.root_id, root, "prepare_child", {
            "unit_id": root.unit_id.value, "selection": selection,
        })
        child_id, child = next(iter(session.pending.items()))
        request = ParentRequest(
            request_id=content_id("request", {"child": child_id}).value,
            parent_episode_id=session.root_id, child_episode_id=child_id,
            goal_id=child.goal.goal_id, child_interface="refinement.support",
            artifact_ids_by_role={
                "campaign": (session.campaign_id.value,),
                "assignment": (child.assignment.artifact_id.value,),
                "invocation": (child.invocation_id.value,),
            },
        )
        await host(session.root_id, root, "enter_child", {
            "request": request.as_record(), "goal": child.goal.as_record(),
            "invocation": {"child_episode_id": child_id},
        })
        await host(child_id, child, "begin_unit", {"role": "support"})
        finding = _finding(session, child, {"finding": {"check_keys": [check.artifact_id.value]}}, session.contract.producer_ref)
        prepared = await evaluations.evaluate(session, child, {
            "unit_id": child.unit_id.value, "purpose": "support",
            "proposal_ref": finding["proposal_ref"],
        })
        assert evaluations.executor.calls == 0
        target, = prepared["experiment_targets"]
        assert target["candidate_ref"] == original_candidate
        assert target["source_kind"] == source_kind
        assert target["source_owner_duet_id"] == oid("campaign_source_duet").value
        assert target["build_receipt_ref"]["artifact_id"] != target_receipt["receipt_id"]
        proposal = {
            "evaluation_request_ref": target["evaluation_request_ref"],
            "experiment": {
                "schema_version": 1,
                "question": "Does the independently approved source avoid credit for empty failure?",
                "rationale": "Execute the exact source build and compare its typed credit to the parent's fixed zero-credit criterion.",
                **{key: target[key] for key in (
                    "candidate_ref", "build_receipt_ref", "environment_ref", "campaign_ref", "launch_ref",
                )},
                "scope": {
                    "kind": "workflow", "entry_local_id": target["root_local_id"],
                    "included_local_ids": target["local_ids"], "component_definition_id": None,
                    "unit_label": None, "invocation_path": [],
                },
                "boundary": {"parent_context_ref": None, "children": "execute"},
                "start": {"kind": "fresh", "artifact_ref": None, "input_payload": target["assigned_inputs"]},
                "mode": "live_fresh", "recording_ref": None,
                "requirements": [{
                    "requirement_ref": row["requirement_ref"], "measure_ref": row["measure_ref"],
                    "expected": "Zero credit because the source proposes no durable transition.",
                    "falsifying": "Any positive credit contradicts the fixed failure-to-yield invariant.",
                } for row in target["requirements"]],
                "unresolved_questions": ["This source observation is not primary-target repair acceptance."],
            },
        }
        for field, replacement in (
            ("candidate_ref", session.contract.ref.as_record()),
            ("build_receipt_ref", {"artifact_id": target_receipt["receipt_id"], "content_hash": target_receipt["content_hash"]}),
            ("criterion", child.assignment.as_record()["body"]["acceptance_measure_ref"]),
        ):
            forged = deepcopy(proposal)
            if field == "criterion":
                forged["experiment"]["requirements"][0]["measure_ref"] = replacement
            else:
                forged["experiment"][field] = replacement
            with pytest.raises(ValueError, match="(identity|assigned|candidate|build|measure)"):
                _validate(evaluations, session, child, forged)
            rejected = service.preview(ExperimentSpec.from_record(forged["experiment"]))
            assert not rejected["resolved"], (field, rejected)
            assert rejected["gaps"], (field, rejected)
            if field == "build_receipt_ref":
                # Both stock fixtures have the same local IDs. The mismatch
                # must be the actual admitted source, not a scope-name typo.
                assert "projected source" in json.dumps(rejected["gaps"])
        assert evaluations.executor.calls == 0

        # The actual model broker records the supplied Episode choice. Admission
        # must authenticate that event; the test does not fabricate producer rows.
        async def proposed_model(call):
            return ModelTransportResponse(text=json.dumps(proposal), route={"fixture": "supplied experiment choice"})

        binding = protocol.ProtocolBinding.from_registration(session.registration)
        channel = _Channel(binding)
        worker = protocol.FrameEncoder(sender=protocol.FrameSender.WORKER, binding=binding)
        path = [{"grain": grain, "key": key} for grain, key in child.path]
        frame = protocol.decode_frame(worker.encode("model_request", {
            "episode_id": child_id, "episode_path": path,
            "model_request_id": content_id("model_request", {"source": source_kind}).value,
            "request": {**REQUEST, "model_type": "refinement"},
        }), sender=protocol.FrameSender.WORKER, binding=binding, expected_sequence=0)
        refiner_inputs = builds.inspection_inputs_for_receipt(session.registration.build_receipt_id)
        await broker_model_request(
            run_store=runs, registration=session.registration, channel=channel, frame=frame,
            model_broker=ScopedModelBroker.from_plan(proposed_model, refiner_inputs.plan),
        )
        producer, = [event for event in runs.read_committed_prefix(session.registration.run_id) if event.kind is RunEventKind.MODEL_RESPONDED]
        admitted = await host(child_id, child, "propose", {
            "unit_id": child.unit_id.value, "task": "experiment",
            "raw_response": producer.payload["response_text"],
            "producer_call_id": producer.payload["producer_call_id"],
        })
        assert admitted["proceed"], admitted
        assert admitted["experiment_plan"]["resolved"]
        assert evaluations.executor.calls == 0
        source_calls = []

        def source_model(route, key, call, cancel, progress):
            prompt = json.loads(call.messages[-1]["content"])
            source_calls.append(prompt)
            response = attempt() if "selected_action" in prompt else {
                "action_class": "discover", "action_inputs": {},
                "retry_reason": "Observe only the supplied empty route.",
            }
            return json.dumps(response), route["model"]

        monkeypatch.setattr("agent.episode_launch_transport._invoke", source_model)
        payload = {"unit_id": child.unit_id.value, "experiment_proposal_ref": admitted["experiment_proposal_ref"]}
        received = await evaluations.evaluate(session, child, payload)
        result = received["experiment_result"]
        assert result["execution_status"] == "succeeded", result
        assert result["candidate_verdict"] == "pass", result["measurement"]
        outcome, = result["measurement"]["outcomes"]
        assert outcome["observed"] == outcome["criterion_expected"] == 0
        assert not result["measurement"]["acceptance"]["admitted"]
        assert source_calls and evaluations.executor.calls == 1
        registration = runs.read_registration(OpaqueId(result["run_id"]))
        assert registration.duet_id.value == target["source_owner_duet_id"]
        assert registration.build_receipt_id.value == target["build_receipt_ref"]["artifact_id"]
        assert registration.duet_id.value != session.duet_id
        with session.view() as view:
            assert view.candidate.as_record() == original_head
            instrument_manifest = session.contract.body.get("instrument_builds_ref")
            if source_kind == "instrument_build":
                namespace, = view.data(Ref.from_record(instrument_manifest))["builds"]
                assert all(path.startswith("__refinement_instruments/") for path in namespace["paths"].values())
                assert set(namespace["paths"].values()) <= set(view.candidate.body["files"])
            else:
                assert instrument_manifest is None
            observations = [row.record for row in view.entries("observation") if row.record.invocation_id == child.invocation_id]
            assert len(observations) == 1
        spec = ExperimentSpec.from_record(proposal["experiment"])
        dispatch = read_record(artifacts, "dispatch", experiment_id=spec.experiment_id)
        assert dispatch["record"]["spec"] == proposal["experiment"]
        recorded = history(artifacts, runs, duet_id=session.duet_id, query=HistoryQuery())
        row, = [row for row in recorded["items"] if row["experiment_id"] == spec.experiment_id]
        assert row["measurement"]["candidate_verdict"] == "pass"
        assert row["measurement"]["measurement_ref"]
        assert row["subject"]["kind"] == "campaign_evaluation"
        inventory = ExperimentService.inventory(
            artifacts, runs, duet_id=session.duet_id,
            source={"kind": "experiment", "experiment_id": spec.experiment_id},
            query={"kind": "units"},
        )
        assert inventory["run_id"] == result["run_id"]
        assert inventory["items"]
        with pytest.raises(ValueError, match="(owner|available|Duet)"):
            ExperimentService.inventory(
                artifacts, runs, duet_id=session.duet_id,
                source={"kind": "run", "run_id": result["run_id"]},
                query={"kind": "units"},
            )
        calls_before = len(source_calls)
        again = await evaluations.evaluate(session, child, payload)
        assert again["experiment_result"] == result
        assert len(source_calls) == calls_before and evaluations.executor.calls == 1
        assert ExperimentService.status(artifacts, runs, spec.experiment_id)["run_id"] == result["run_id"]
        source_audit = tuple(event.as_record() for event in runs.read_audit_log(registration.run_id))
        with session.view() as view:
            before_replay = dict(view.head)
        saved = save_recording(artifacts, runs, result["run_id"])
        await _assert_worker_discovery(service, proposal["experiment"], result, saved, tmp_path)
        assert evaluations.executor.calls == 1
        recorded = deepcopy(proposal)
        recorded["experiment"].update(
            mode="recorded", recording_ref=saved, launch_ref=None,
        )
        replay_spec, _ = _validate(evaluations, session, child, recorded)
        replay = await service.run(replay_spec)
        # Stock source prompts contain original Episode/evidence provenance.
        # A new Run cannot borrow those answers by silently rewriting prompts.
        assert replay["execution_status"] == "invalid", replay
        assert replay["recorded_execution"]["status"] == "diverged"
        assert replay["recorded_execution"]["divergence"]["kind"] == "unmatched_external_request"
        assert replay["run_id"] != result["run_id"]
        assert not replay["progress"]["admitted"]
        assert len(source_calls) == calls_before
        assert evaluations.executor.calls == 2
        assert tuple(event.as_record() for event in runs.read_audit_log(registration.run_id)) == source_audit
        with session.view() as view:
            assert dict(view.head) == before_replay
        runs.finalize_run(
            run_id=session.registration.run_id, origin=RunEventOrigin.HOST,
            sender_sequence=channel.next_sender_sequence,
            terminal_status=RunTerminalStatus.CANCELLED,
            typed_status={"outcome": "cancelled", "reason": "Supplied support-choice fixture ends after measured return."},
        )
