"""Original task -> independently derived cases -> Measure -> parent report.

Parent/child choices and Builder replies are supplied. The real admission,
stores, controls, numerical credit and parent-return path execute; this is not
a live reasoning or Target Workflow execution receipt.
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from agent.duet_contracts import content_id
from agent.episode_blueprints import workflow_spec_from_blueprint
from agent.episode_contracts import OpaqueId
from function_library.models import _thaw_json
from iterative_episode_refiner.measure_admission import definition
from iterative_episode_refiner.measure_controls import final_control_rows
from iterative_episode_refiner.evaluation_plan import resolve_evaluations
from iterative_episode_refiner.readiness import root_readiness
from iterative_episode_refiner.records import Ref
from iterative_episode_refiner.runtime import Invocation
from iterative_episode_refiner.runtime_proposals import _measure, assign_child
from tests.episode_runtime.testing_harness.refinement_fixture import prepared_refiner
from tests.episode_runtime.testing_harness.test_measurements import ResultOnlyExecutor


def scheduling_blueprint():
    path = (
        Path(__file__).resolve().parents[3]
        / "docs/openchia/acceptance/schedule_target.blueprint.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


async def assert_shared_group_measurement(session, check, case, tmp_path):
    """Use the shared service on supplied answers; no candidate execution claim."""
    from agent.episode_launch import resolve_launch
    from episode_runtime.records.experiments import put_data
    from episode_runtime.testing_harness.contracts import ExperimentSpec
    from episode_runtime.testing_harness.service import ExperimentService
    from tests.episode_runtime.testing_harness.launch_fixture import FixtureLaunchHost
    from tests.episode_runtime.testing_harness.test_experiment_planning import experiment

    artifacts, builds = session.store.evidence.duets, session.store.evidence.builds
    with session.view() as view:
        receipt = view.data(
            Ref.from_record(session.contract.body["initial_build_inputs_ref"])
        )
        candidate = view.candidate
        cases = [
            (view.data(Ref.from_record(case[field][0]))["observed"], outcome)
            for field, outcome in (
                ("positive_control_refs", "pass"),
                ("negative_control_refs", "fail"),
            )
        ]
    inputs = builds.inspection_inputs_for_receipt(receipt["receipt_id"])
    launch = resolve_launch({
        "project": "grouped-measure-fixture",
        "project_root": str(tmp_path),
        "env_files": [],
        "routes": {
            "local": {
                "provider": "custom",
                "model": "unused",
                "base_url": "http://localhost:9999/v1",
                "api_mode": "chat_completions",
                "auth": {"kind": "none"},
            }
        },
        "model_slots": {"selector": "local", "executor": "local"},
        "builder_slots": {"planning": "selector", "emission": "executor"},
    })
    FixtureLaunchHost(artifacts, builds, session.duet_id).approve_fixture(launch)
    raw = experiment(artifacts, inputs.build_request, inputs.receipt)
    raw.update(
        candidate_ref=candidate.ref.as_record(),
        campaign_ref=session.contract.ref.as_record(),
        environment_ref=dict(session.contract.body["environment_ref"]),
        launch_ref=put_data(artifacts, session.duet_id, "launch", launch.record),
        requirements=[
            {
                "requirement_ref": check.ref.as_record(),
                "measure_ref": _thaw_json(check.body["measure_ref"]),
                "expected": "A feasible optimal schedule passes the original check.",
                "falsifying": "An infeasible answer fails, regardless of its explanation.",
            }
        ],
    )
    raw["scope"].update(
        entry_local_id=inputs.plan.root_local_id,
        included_local_ids=[node.local_id for node in inputs.plan.nodes],
    )
    executor = session.evaluations.executor
    service = ExperimentService(
        artifacts=artifacts, builds=builds, runs=executor.run_store, executor=executor
    )
    for answer, expected in cases:
        raw["question"] = (
            f"Does this supplied {expected} control retain its judgment through the parent group?"
        )
        executor.result = {
            "workflow_result": {
                "admitted_problem_frontier": [{"fields": _thaw_json(answer)}]
            }
        }
        spec = ExperimentSpec.from_record(raw)
        preview = service.preview(spec)
        assert preview["resolved"], preview["gaps"]
        assert preview["measurements"][0]["eligible"]
        result = await service.run(spec)
        assert result["candidate_verdict"] == expected
        assert (
            result["measurement"]["outcomes"][0]["measure_ref"]
            == check.body["measure_ref"]
        )
        assert not result["measurement"]["acceptance"]["admitted"]
        assert not result["measurement"]["progress"]["admitted"]


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["local", "composition"])
async def test_measure_uses_original_task_grounding_and_returns_admitted_evidence_to_parent(
    tmp_path,
    run_store,
    purpose,
):
    workflow = workflow_spec_from_blueprint(scheduling_blueprint())
    async with prepared_refiner(
        tmp_path,
        run_store[1].runtime_identity,
        target_workflow=workflow,
        registered_grounding=True,
        grouped_measures=purpose == "composition",
        executor_type=ResultOnlyExecutor if purpose == "composition" else None,
    ) as session:
        root = session.calls[session.root_id]
        root.unit_id = content_id(
            "unit", "parent requests original schedule measurement"
        )
        grant = session.policy["measure_admission"]
        context = session.snapshot(root)["context"]
        # Available evidence is not an installed check, acceptance or credit.
        choices = [
            row
            for row in context["measure_grounding"]
            if row["case"]["purpose"] == purpose
        ]
        assert choices
        case = _thaw_json(choices[0]["case"])
        key = case["requirement_key"]
        with session.view() as view:
            baseline = view.candidate.ref.as_record()
            initial_checks = {row.record.ref for row in view.entries("check")}
            assert not view.entries("measure")
            assert not view.entries("credit")
            assert not any(
                row.record.body["evidence_kind"] == "execution"
                for row in view.entries("check")
            )
            origin = view.data(Ref.from_record(case["oracle_ref"]))
            assert (
                origin["requirement_catalog_ref"]
                == view.contract.body["requirement_catalog_ref"]
            )
            assert (
                origin["target_workflow_ref"]
                == view.contract.body["target_workflow_ref"]
            )

        chosen = assign_child(
            session,
            root,
            {
                "role": "measure",
                "goal": "Establish a schedule feasibility and optimality check from the approved problem.",
                "contribution_requirement_keys": [key],
                "owned_slice_keys": [key],
                "writable_paths": [],
                "local_measure_ref": _thaw_json(grant["adequacy_measure_ref"]),
                "acceptance_measure_ref": _thaw_json(
                    root.assignment.body["acceptance_measure_ref"]
                ),
                "measure_request": {"purpose": purpose, "requirement_keys": [key]},
            },
            session.contract.producer_ref,
        )
        session.commit(root, "enter_child", {"invocation_id": chosen["invocation_id"]})
        with session.view() as view:
            assignment = view.entry("invocation", chosen["invocation_id"]).record
        child = Invocation(
            OpaqueId(chosen["invocation_id"]),
            assignment,
            root.path,
            root.goal,
            unit_id=content_id("unit", "establish schedule measure"),
        )
        instrument = {
            name: case[name]
            for name in (
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
            oracle_kind="registered_predicate",
            requirement_keys=[key],
            grounding_refs=[choices[0]["reference"]],
            case_manifest={"grounding_refs": [choices[0]["reference"]]},
        )
        # A new artifact does not make an altered expected answer authorized.
        altered = deepcopy(case)
        altered["expected"] = {"benchmark_id": "model-invented-easy-task"}
        forged_ref = session.put_data("grounded_case", altered).as_record()
        forged = {
            **instrument,
            "grounding_refs": [forged_ref],
            "case_manifest": {"grounding_refs": [forged_ref]},
        }

        for proposal_body, expected in ((forged, "rejected"), (instrument, "admitted")):
            response = _measure(
                session,
                child,
                {"instrument": proposal_body},
                session.contract.producer_ref,
            )
            with session.view() as view:
                proposal = view.read(
                    Ref.from_record(response["proposal_ref"]), "measure_proposal"
                )
            measure = session.put_data("measure", definition(proposal))
            session.commit(
                child,
                "admit_measure",
                {
                    "proposal_ref": proposal.ref.as_record(),
                    "measure_ref": measure.as_record(),
                },
            )
            with session.view() as view:
                decision = next(
                    row.record
                    for row in view.entries("measure")
                    if row.record.body["proposal_ref"] == proposal.ref.as_record()
                )
                assert decision.body["status"] == expected
                if expected == "rejected":
                    assert not decision.body["fact_keys"]
                    assert not decision.body["check_refs"]
                else:
                    assert all(
                        item["expected"] == item["observed"]
                        for item in decision.body["control_results"]
                    )
                    assert {
                        item["expected"] for item in decision.body["control_results"]
                    } == {"pass", "fail"}

        session.commit(
            child,
            "close_unit",
            {"candidate_before_ref": baseline, "continuation_ref": None},
        )
        session.commit(child, "return_child", {})
        session.commit(
            root,
            "close_unit",
            {"candidate_before_ref": baseline, "continuation_ref": None},
        )
        with session.view() as view:
            parent = next(
                row.record
                for row in view.entries("unit")
                if row.record.invocation_id == root.invocation_id
            )
            assert parent.body["realized_yield"] > 0
            assert parent.body["disposition"] != "attained"
            assessments = [
                view.read(Ref.from_record(ref), "prerequisite_assessment")
                for ref in parent.body["prerequisite_assessment_refs"]
            ]
            assert assessments[0].body["decision"]["kind"] == "measure_available"
            assert assessments[0].body["decision"]["requirement_keys"] == (key,)
            assert root_readiness(view, root.assignment, session.policy)["gaps"]
            if purpose == "composition":
                # Same frozen parent measure now contains the admitted criterion;
                # neither the old static checks nor their identities were lost.
                readiness = root_readiness(view, root.assignment, session.policy)
                checks = [
                    view.read(Ref.from_record(ref), "check")
                    for ref in readiness["check_refs"]
                ]
                grouped = next(
                    check for check in checks if check.body["requirement_key"] == key
                )
                assert (
                    grouped.body["measure_ref"]
                    == root.assignment.body["acceptance_measure_ref"]
                )
                original = view.read(
                    Ref.from_record(grouped.body["origin_refs"][-1]), "check"
                )
                assert original.body["measure_ref"] == measure.as_record()
                assert all(
                    grouped.body[field] == original.body[field]
                    for field in (
                        "predicate_ref",
                        "expected",
                        "purpose",
                        "guard_keys",
                        "execution_binding",
                        "requirement_key",
                        "dependency_paths",
                        "grounding_refs",
                        "observation_path",
                    )
                )
                assert initial_checks <= {
                    row.record.ref for row in view.entries("check")
                }
                assert any(
                    gap["code"] == "acceptance_not_current_pass"
                    and key in gap["requirement_keys"]
                    for gap in readiness["gaps"]
                )
                admissions, controls = final_control_rows(
                    view, [grouped.ref.as_record()]
                )
                assert admissions == [decision.ref.as_record()]
                assert not controls  # This oracle is pure, not a checker Run.
                assert (
                    len(decision.body["fact_keys"]) == 1
                )  # Grouping adds no adequacy credit.

        if purpose == "composition":
            await assert_shared_group_measurement(session, grouped, case, tmp_path)
            # The independently assigned verifier must include the new check;
            # an old static-only request cannot stand in for its full judgment.
            root.unit_id = content_id("unit", "parent requests independent acceptance")
            from iterative_episode_refiner.runtime_proposals import (
                verification_assignment,
            )

            chosen = verification_assignment(session, root, "composition")
            session.commit(
                root, "enter_child", {"invocation_id": chosen["invocation_id"]}
            )
            with session.view() as view:
                assignment = view.entry("invocation", chosen["invocation_id"]).record
                plans = resolve_evaluations(
                    view, session.policy, assignment, "composition"
                )
                assert grouped.ref in {
                    check.ref for plan in plans for check in plan["checks"]
                }
            verifier = Invocation(
                OpaqueId(chosen["invocation_id"]),
                assignment,
                root.path,
                root.goal,
                unit_id=content_id("unit", "evaluate grouped criterion"),
            )
            _, requests = session.evaluations._requests(
                session,
                verifier,
                {
                    "unit_id": verifier.unit_id.value,
                    "purpose": "composition",
                },
            )
            request = next(
                request
                for request, _ in requests
                if grouped.artifact_id.value in request.body["check_keys"]
            )
            omitted = session.record(
                verifier,
                "evaluation",
                {
                    **request.body,
                    "check_keys": [
                        check
                        for check in request.body["check_keys"]
                        if check != grouped.artifact_id.value
                    ],
                },
            )
            with pytest.raises(ValueError, match="omits checks"):
                session.commit(
                    verifier, "request_evaluation", {"request": omitted.as_record()}
                )
            with session.view() as view:
                assert view.read(request.ref, "evaluation") == request


@pytest.mark.asyncio
async def test_task_change_does_not_inherit_registered_benchmark_grounding(
    tmp_path, run_store
):
    blueprint = scheduling_blueprint()
    # Same familiar benchmark ID cannot override changed approved conditions.
    blueprint["episodes"][0]["contract"]["epistemic"]["environment"]["workers"] = 1
    async with prepared_refiner(
        tmp_path,
        run_store[1].runtime_identity,
        target_workflow=workflow_spec_from_blueprint(blueprint),
        registered_grounding=True,
    ) as session:
        assert not session.policy["measure_admission"]["grounding_refs"]
        root = session.calls[session.root_id]
        context = session.snapshot(root)["context"]
        assert not context["measure_grounding"]
        assert context["measurement_gaps"]
