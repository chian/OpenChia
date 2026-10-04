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
from iterative_episode_refiner.readiness import root_readiness
from iterative_episode_refiner.records import Ref
from iterative_episode_refiner.runtime import Invocation
from iterative_episode_refiner.runtime_proposals import _measure, assign_child
from tests.episode_runtime.testing.refinement_fixture import prepared_refiner


def scheduling_blueprint():
    path = (
        Path(__file__).resolve().parents[3]
        / "docs/openchia/acceptance/schedule_target.blueprint.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_measure_uses_original_task_grounding_and_returns_admitted_evidence_to_parent(
    tmp_path,
    run_store,
):
    workflow = workflow_spec_from_blueprint(scheduling_blueprint())
    async with prepared_refiner(
        tmp_path,
        run_store[1].runtime_identity,
        target_workflow=workflow,
        registered_grounding=True,
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
            if row["case"]["purpose"] == "local"
        ]
        assert choices
        case = _thaw_json(choices[0]["case"])
        key = case["requirement_key"]
        with session.view() as view:
            baseline = view.candidate.ref.as_record()
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
                "measure_request": {"purpose": "local", "requirement_keys": [key]},
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
