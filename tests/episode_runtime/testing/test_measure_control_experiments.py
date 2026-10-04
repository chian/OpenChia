"""Actual checker execution validates controls before admitting a measure.

The fixture drives host-authorized Measure choices, not live model reasoning.
The admitted generated checker consumes each mapped answer itself; its result
is not supplied by the test executor. Execution is in-process, not confinement.
"""

from dataclasses import replace

import pytest

from agent.duet_contracts import content_id
from agent.episode_launch import resolve_launch
from episode_runtime.records.experiments import put_data
from episode_runtime.testing.service import ExperimentService
from function_library.models import _thaw_json
from function_library.refinement_contract import CHILDREN
from iterative_episode_refiner.evaluation_experiments import _receive, _validate
from iterative_episode_refiner.measure_controls import validated_control_facts
from iterative_episode_refiner.records import Ref
from iterative_episode_refiner.runtime import Invocation
from iterative_episode_refiner.runtime_proposals import _measure
from iterative_episode_refiner.state_machine import judgment_lineage
from iterative_episode_refiner import state_machine
from tests.episode_runtime.testing.launch_fixture import FixtureLaunchHost
from tests.episode_runtime.testing.refinement_fixture import prepared_refiner


@pytest.mark.asyncio
async def test_grounded_control_experiments_accumulate_credit_without_early_admission(
    tmp_path, run_store, monkeypatch
):
    async with prepared_refiner(
        tmp_path, run_store[1].runtime_identity, independent_measure=True
    ) as session:
        evaluations = session.evaluations
        artifacts, builds, runs = (
            session.store.evidence.duets,
            evaluations.builder.store,
            session.store.evidence.runs,
        )
        launch = resolve_launch({
            "project": "known-answer-controls",
            "project_root": str(tmp_path),
            "env_files": [],
            "routes": {
                "fixture": {
                    "provider": "custom",
                    "model": "unused",
                    "base_url": "http://localhost:9999/v1",
                    "api_mode": "chat_completions",
                    "auth": {"kind": "none"},
                }
            },
            "model_slots": {"selector": "fixture", "executor": "fixture"},
            "builder_slots": {"planning": "selector", "emission": "executor"},
        })
        FixtureLaunchHost(artifacts, builds, session.duet_id).approve_fixture(launch)
        evaluations.target_launch_ref = put_data(
            artifacts, session.duet_id, "launch", launch.record
        )
        grant = session.policy["measure_admission"]
        with session.view() as view:
            case = _thaw_json(view.data(Ref.from_record(grant["grounding_refs"][0])))
            baseline = view.candidate.ref.as_record()
        root = session.calls[session.root_id]
        root.unit_id = content_id("unit", "assign checker adequacy")
        goal = session.put_data(
            "assigned_goal",
            {
                "goal": "Establish the checker's discrimination on the two independent controls.",
                "measure_request": {
                    "purpose": case["purpose"],
                    "requirement_keys": [case["requirement_key"]],
                },
            },
        )
        body = {
            **root.assignment.as_record()["body"],
            "parent_assignment_ref": root.assignment.ref.as_record(),
            "role": "measure",
            "goal_record_ref": goal.as_record(),
            "contribution_requirement_keys": [case["requirement_key"]],
            "local_measure_ref": _thaw_json(grant["adequacy_measure_ref"]),
            "allowed_child_bindings": list(CHILDREN["measure"]),
            "supersedes_assignment_refs": [],
        }
        body["judgment_lineage"] = judgment_lineage(body)
        assignment = session.record(root, "assignment", body)
        invocation = content_id("invocation", "independent measure fixture")
        session.commit(
            root,
            "assign",
            {"assignment": assignment.as_record(), "invocation_id": invocation.value},
        )
        session.commit(root, "enter_child", {"invocation_id": invocation.value})
        child = Invocation(
            invocation,
            assignment,
            root.path,
            root.goal,
            unit_id=content_id("unit", "negative control"),
        )
        instrument = {
            key: case[key]
            for key in (
                "purpose",
                "oracle_ref",
                "input_domain_ref",
                "observation_schema_ref",
                "decision_function_ref",
                "positive_control_refs",
                "negative_control_refs",
                "independence_policy_ref",
                "uncertainty_policy_ref",
                "limitation_refs",
            )
        }
        instrument.update(
            oracle_kind="independent_execution",
            requirement_keys=[case["requirement_key"]],
            grounding_refs=_thaw_json(grant["grounding_refs"]),
            case_manifest={"grounding_refs": _thaw_json(grant["grounding_refs"])},
        )
        proposed = _measure(
            session, child, {"instrument": instrument}, session.contract.producer_ref
        )
        proposal_ref = proposed["proposal_ref"]
        service = ExperimentService(
            artifacts=artifacts, builds=builds, runs=runs, executor=evaluations.executor
        )
        receipts = []
        for ordinal, (control_ref, expected, mode) in enumerate((
            (case["negative_control_refs"][0], False, "live_fresh"),
            (case["positive_control_refs"][0], True, "live_saved"),
        )):
            if ordinal:
                child.unit_id = content_id("unit", "positive control")
                resumed = _measure(
                    session,
                    child,
                    {"resume_proposal_ref": proposal_ref},
                    session.contract.producer_ref,
                )
                assert resumed["proposal_ref"] == proposal_ref
            prepared = await evaluations.evaluate(
                session,
                child,
                {
                    "unit_id": child.unit_id.value,
                    "purpose": "adequacy",
                    "proposal_ref": proposal_ref,
                },
            )
            # The caller deliberately selects the negative case first; the
            # host exposes required cases but does not prescribe their order.
            target = next(
                row
                for row in prepared["experiment_targets"]
                if artifacts.get_artifact(row["control_target_ref"]["artifact_id"])[
                    "record"
                ]["control_ref"]
                == control_ref
            )
            proposal = {
                "control_target_ref": target["control_target_ref"],
                "experiment": {
                    "schema_version": 1,
                    "question": "Does the checker classify this independently known answer correctly?",
                    "rationale": "Exercise the declared checker child on one grounded control before admitting the whole measure.",
                    **{
                        key: target[key]
                        for key in (
                            "candidate_ref",
                            "build_receipt_ref",
                            "environment_ref",
                            "campaign_ref",
                            "launch_ref",
                            "scope",
                            "boundary",
                        )
                    },
                    "start": {
                        "kind": "fresh",
                        "artifact_ref": None,
                        "input_payload": target["fresh_input_payload"],
                    }
                    if mode == "live_fresh"
                    else {
                        "kind": "saved_inputs",
                        "artifact_ref": target["saved_input_ref"],
                        "input_payload": {},
                    },
                    "mode": mode,
                    "recording_ref": None,
                    "requirements": [
                        {
                            **row,
                            "expected": "The checker matches the independent control polarity.",
                            "falsifying": "The checker accepts an incorrect answer or rejects the correct answer.",
                        }
                        for row in target["requirements"]
                    ],
                    "unresolved_questions": [
                        "These two controls do not cover every possible input."
                    ],
                },
            }
            spec, assigned = _validate(evaluations, session, child, proposal)
            result = await service.run(spec)
            assert result["execution_status"] == "succeeded", result
            outcome = result["measurement"]["outcomes"][0]
            assert outcome["observed"] is expected
            assert outcome["status"] == "pass"
            assert outcome["criterion_expected"]["required_outcome"] == (
                "pass" if expected else "fail"
            )
            assert not result["measurement"]["acceptance"]["admitted"]
            _receive(evaluations, session, child, spec, assigned, result)
            calls = evaluations.executor.calls
            with session.view() as view:
                head = dict(view.head)
                assert (
                    len(
                        validated_control_facts(
                            view, proposal_ref=Ref.from_record(proposal_ref)
                        )
                    )
                    == ordinal + 1
                )
                admissions = [
                    row for row in view.entries("measure") if row.status == "admitted"
                ]
                assert bool(admissions) is bool(ordinal)
            again = await service.run(spec)
            _receive(evaluations, session, child, spec, assigned, again)
            assert evaluations.executor.calls == calls
            with session.view() as view:
                assert dict(view.head) == head
            if ordinal == 0:
                admit = state_machine.admit_attempt

                def forged_control_key(view, attempt, resolved):
                    records, deltas = admit(view, attempt, resolved)
                    receipt = next(row for row in records if row.kind == "unit_receipt")
                    invented = content_id(
                        "fact", "unestablished control behavior"
                    ).value
                    forged = replace(
                        receipt,
                        body={
                            **receipt.body,
                            "semantic_fact_keys": [invented],
                        },
                    )
                    return [
                        forged if row.ref == receipt.ref else row for row in records
                    ], [
                        {
                            **delta,
                            "key": invented,
                            "receipt_id": forged.artifact_id.value,
                        }
                        if delta["kind"] == "credit"
                        else {**delta, "record_id": forged.artifact_id.value}
                        if delta.get("record_id") == receipt.artifact_id.value
                        else delta
                        for delta in deltas
                    ]

                with monkeypatch.context() as patched:
                    patched.setattr(state_machine, "admit_attempt", forged_control_key)
                    with pytest.raises(
                        ValueError, match="operative evidence under its frozen measure"
                    ):
                        session.commit(
                            child,
                            "close_unit",
                            {
                                "candidate_before_ref": baseline,
                                "continuation_ref": None,
                            },
                        )
                with session.view() as view:
                    assert dict(view.head) == head
                    assert not view.entries("unit")
            session.commit(
                child,
                "close_unit",
                {"candidate_before_ref": baseline, "continuation_ref": None},
            )
            with session.view() as view:
                receipt = next(
                    row.record
                    for row in view.entries("unit")
                    if row.record.logical_unit_id == child.unit_id
                )
                receipts.append(receipt)
                assert receipt.body["realized_yield"] == 1
                assert receipt.body["credit_after"] == ordinal + 1
        assert receipts[0].body["disposition"] == "continuing"
        assert receipts[1].body["disposition"] == "attained"
        with session.view() as view:
            admission = next(
                row.record
                for row in view.entries("measure")
                if row.status == "admitted"
            )
            assert set(admission.body["fact_keys"]) == set().union(
                *(set(row.body["semantic_fact_keys"]) for row in receipts)
            )
        history = session.snapshot(root)["context"]["test_history"]
        controls = history["controls"]
        assert len(controls["items"]) == 2
        assert {row["kind"] for row in controls["items"]} == {
            "measure_adequacy_control"
        }
        assert {row["checker_predicate_outcome"] for row in controls["items"]} == {
            "pass",
            "fail",
        }
        assert {row["outcome"]["status"] for row in controls["items"]} == {"pass"}
        assert all(
            row["measurement_ref"] and row["execution_ref"] for row in controls["items"]
        )
        page = ExperimentService.history(
            artifacts,
            runs,
            duet_id=session.duet_id,
            query={
                **controls["query"],
                "limit": 1,
            },
        )
        assert page["next_query"] is not None
        next_page = ExperimentService.history(
            artifacts, runs, duet_id=session.duet_id, query=page["next_query"]
        )
        assert page["items"][0]["control_ref"] != next_page["items"][0]["control_ref"]
        experiments = ExperimentService.history(
            artifacts, runs, duet_id=session.duet_id, query={}
        )
        assert {row["subject"]["kind"] for row in experiments["items"]} == {
            "measure_adequacy_control"
        }
