"""Real campaign admission and executed controls; model choices are supplied.

This exercises a new check's entire nested review/return/admission path, not a
live model or worker-confinement receipt. Controls use an exhaustive solver.
"""

from copy import deepcopy

import pytest

from agent.duet_contracts import content_id
from agent.episode_blueprints import workflow_spec_from_blueprint
from agent.episode_contracts import OpaqueId
from function_library.models import _thaw_json
from iterative_episode_refiner.measure_admission import definition
from iterative_episode_refiner.measure_design import REVIEW_CRITERIA
from iterative_episode_refiner.records import Ref
from iterative_episode_refiner.runtime import Invocation
from iterative_episode_refiner.runtime_proposals import _finding, _measure, assign_child
from tests.episode_runtime.conftest import run_store as run_store
from tests.episode_runtime.testing_harness.refinement_fixture import prepared_refiner
from tests.episode_runtime.testing_harness.test_registered_measure_preparation import (
    scheduling_blueprint,
)


def enter(session, parent, choice, label):
    session.commit(parent, "enter_child", {"invocation_id": choice["invocation_id"]})
    with session.view() as view:
        assignment = view.entry("invocation", choice["invocation_id"]).record
    return Invocation(
        OpaqueId(choice["invocation_id"]),
        assignment,
        parent.path,
        parent.goal,
        unit_id=content_id("unit", label),
    )


def close(session, call, candidate):
    session.commit(
        call,
        "close_unit",
        {"candidate_before_ref": candidate, "continuation_ref": None},
    )
    session.commit(call, "return_child", {})


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_controls", [False, True])
async def test_separate_review_and_executable_controls_are_both_required(
    tmp_path, run_store, invalid_controls
):
    workflow = workflow_spec_from_blueprint(scheduling_blueprint())
    async with prepared_refiner(
        tmp_path,
        run_store[1].runtime_identity,
        target_workflow=workflow,
        registered_grounding=True,
    ) as session:
        root = session.calls[session.root_id]
        root.unit_id = content_id("unit", "request new check design")
        producer = session.contract.producer_ref
        grant = session.policy["measure_admission"]
        context = session.snapshot(root)["context"]
        case = next(
            item["case"]
            for item in context["measure_grounding"]
            if item["case"]["purpose"] == "local"
        )
        key = case["requirement_key"]
        with session.view() as view:
            candidate = view.candidate.ref.as_record()
            predicate = view.data(Ref.from_record(case["decision_function_ref"]))
            positive = view.data(Ref.from_record(case["positive_control_refs"][0]))[
                "observed"
            ]
            negative = view.data(Ref.from_record(case["negative_control_refs"][0]))[
                "observed"
            ]
        choice = assign_child(
            session,
            root,
            {
                "role": "measure",
                "goal": "Design an adequate check of the original scheduling objective.",
                "contribution_requirement_keys": [key],
                "owned_slice_keys": [key],
                "writable_paths": [],
                "local_measure_ref": _thaw_json(grant["adequacy_measure_ref"]),
                "acceptance_measure_ref": _thaw_json(
                    root.assignment.body["acceptance_measure_ref"]
                ),
                "measure_request": {"purpose": "local", "requirement_keys": [key]},
            },
            producer,
        )
        measure = enter(session, root, choice, "design a scheduling check")
        design = {
            "purpose": "local",
            "predicate": predicate,
            "cases": [
                {
                    "requirement_key": key,
                    "rationale": "The original task requires a feasible schedule and minimum completion time; exhaustive enumeration gives an independent optimum.",
                    "expected": _thaw_json(case["expected"]),
                    "observation_path": case["observation_path"],
                    "positive_controls": [
                        {
                            "observed": negative if invalid_controls else positive,
                            "rationale": "Claimed feasible optimal witness; the host must actually check this claim.",
                        }
                    ],
                    "negative_controls": [
                        {
                            "observed": {},
                            "rationale": "An empty answer omits all scheduled jobs and cannot satisfy the task.",
                        }
                    ],
                }
            ],
            "input_domain": {
                "description": "Original seven-job problem with two workers and one laser."
            },
            "observation_schema": {
                "description": "String-valued schedule, makespan and optimality_argument fields."
            },
            "execution_binding": _thaw_json(case["execution_binding"]),
            "limitations": [
                "Does not establish correctness of the prose optimality argument."
            ],
        }
        proposed = _measure(session, measure, {"check_design": design}, producer)
        with session.view() as view:
            draft = view.entries("measure_definition")[0].record
            assert not view.entries("measure")
            assert not view.entries("credit")
        # Storing the definition alone grants no authority; the independent
        # child must return, and it cannot substitute a different definition.
        with pytest.raises(ValueError, match="separately returned review"):
            _measure(
                session,
                measure,
                {"reviewed_definition_ref": draft.ref.as_record()},
                producer,
            )
        reviewer = enter(session, measure, proposed["child"], "review exact check")
        review = {
            "definition_ref": draft.ref.as_record(),
            "criteria": {
                name: {
                    "satisfied": True,
                    "reason": "The specified schedule predicate evaluates the original constraints; executable controls must still confirm their proposed polarities.",
                }
                for name in REVIEW_CRITERIA
            },
            "counterexamples": [],
            "limitations": [
                "Review can be mistaken and does not replace executable controls."
            ],
        }
        _finding(session, reviewer, {"check_review": review}, producer)
        with pytest.raises(ValueError, match="has not returned"):
            _measure(
                session,
                measure,
                {"reviewed_definition_ref": draft.ref.as_record()},
                producer,
            )
        close(session, reviewer, candidate)
        with session.view() as view:
            receipt = next(
                row.record
                for row in view.entries("unit")
                if row.record.invocation_id == reviewer.invocation_id
            )
            assert receipt.body["realized_yield"] == 0
            assert receipt.body["disposition"] == "needs_parent_decision"
            assert not view.entries("measure")
        response = _measure(
            session,
            measure,
            {"reviewed_definition_ref": draft.ref.as_record()},
            producer,
        )
        with session.view() as view:
            proposal = view.read(
                Ref.from_record(response["proposal_ref"]), "measure_proposal"
            )
            # A changed expected result cannot piggyback on an honest review.
            from iterative_episode_refiner.measure_design_runtime import authorize

            altered = deepcopy(_thaw_json(proposal.body))
            altered["purpose"] = "composition"
            forged = session.record(measure, "measure_proposal", altered)
            with pytest.raises(ValueError, match="differs from the exact reviewed"):
                authorize(view, forged)
        measure_ref = session.put_data("measure", definition(proposal))
        session.commit(
            measure,
            "admit_measure",
            {
                "proposal_ref": proposal.ref.as_record(),
                "measure_ref": measure_ref.as_record(),
            },
        )
        with session.view() as view:
            admission = view.entries("measure")[0].record
            assert admission.body["status"] == (
                "rejected" if invalid_controls else "admitted"
            )
            assert bool(admission.body["fact_keys"]) is not invalid_controls
            if invalid_controls:
                assert "fails its declared pass control" in admission.body["reason"]
            else:
                assert {
                    row["observed"] for row in admission.body["control_results"]
                } == {"pass", "fail"}
                assert all(
                    row["observed"] == row["expected"]
                    for row in admission.body["control_results"]
                )
        close(session, measure, candidate)
        session.commit(
            root,
            "close_unit",
            {"candidate_before_ref": candidate, "continuation_ref": None},
        )
        with session.view() as view:
            parent = next(
                row.record
                for row in view.entries("unit")
                if row.record.invocation_id == root.invocation_id
            )
            assert (parent.body["realized_yield"] > 0) is not invalid_controls
            assert parent.body["disposition"] != "attained"
            reports = [
                row.record
                for row in view.entries("report")
                if row.record.invocation_id == measure.invocation_id
            ]
            assert (
                admission.ref.as_record() in reports[0].body["measure_admission_refs"]
            )
