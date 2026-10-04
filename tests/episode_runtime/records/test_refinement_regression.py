"""Admitted source revisions and observations remain visible across child returns.

Host calls drive the real campaign admissions and common experiment service.
The existing result-only executor supplies contrasting typed outputs; this tests
regression history, not live reasoning, source correctness or confinement.
"""

import pytest

from agent.duet_contracts import content_id
from agent.episode_launch import resolve_launch
from episode_runtime.protocol import episode_id_for_path
from episode_runtime.records.experiments import put_data
from episode_runtime.testing.service import ExperimentService
from function_library.refinement_contract import CHILDREN
from iterative_episode_refiner.evaluation_experiments import _receive, _validate
from iterative_episode_refiner.records import Ref
from iterative_episode_refiner.runtime import Invocation
from iterative_episode_refiner.state_machine import judgment_lineage
from tests.episode_runtime.testing.launch_fixture import FixtureLaunchHost
from tests.episode_runtime.testing.refinement_fixture import prepared_refiner
from tests.episode_runtime.testing.test_measurements import ResultOnlyExecutor


def source_deficits(session, invocation_id):
    with session.view() as view:
        return [
            view.data(Ref.from_record(row.record.body["build_receipt_ref"]))["deficits"]
            for row in view.entries("evaluation_source")
            if row.record.invocation_id == invocation_id
        ]


@pytest.mark.asyncio
async def test_admitted_cross_child_regression_is_visible_without_audit_reconstruction(
    tmp_path,
    run_store,
    monkeypatch,
):
    checks = [
        {
            "requirement_field": field,
            "expected": True,
            "observation_path": f"/payload/typed_status/{field}",
            "grounding": {
                "fixture": "both independent properties must hold",
                "field": field,
            },
        }
        for field in ("goal", "progress")
    ]
    async with prepared_refiner(
        tmp_path,
        run_store[1].runtime_identity,
        runtime_checks=checks,
        allow_source_edits=True,
        executor_type=ResultOnlyExecutor,
    ) as session:
        root = session.calls[session.root_id]
        root.unit_id = content_id("unit", "root assignment")
        with session.view() as view:
            baseline = view.candidate
            runtime_checks = sorted(
                (
                    row.record
                    for row in view.entries("check")
                    if row.record.body["evidence_kind"] == "execution"
                ),
                key=lambda record: record.body["observation_path"],
            )
        keys = [row.body["requirement_key"] for row in runtime_checks]
        assert len(set(keys)) == 2
        source_path = next(iter(baseline.body["files"]))
        builds, artifacts, runs = (
            session.store.evidence.builds,
            session.store.evidence.duets,
            session.store.evidence.runs,
        )
        source = builds.read_blob(baseline.body["files"][source_path])
        launch = resolve_launch({
            "project": "regression-history-fixture",
            "project_root": str(tmp_path),
            "env_files": [],
            "routes": {
                "supplied": {
                    "provider": "custom",
                    "model": "unused",
                    "base_url": "http://localhost:9999/v1",
                    "api_mode": "chat_completions",
                    "auth": {"kind": "none"},
                }
            },
            "model_slots": {"selector": "supplied", "executor": "supplied"},
            "builder_slots": {"planning": "selector", "emission": "executor"},
        })
        session.evaluations.target_launch_ref = put_data(
            artifacts, session.duet_id, "launch", launch.record
        )
        FixtureLaunchHost(artifacts, builds, session.duet_id).approve_fixture(launch)
        service = ExperimentService(
            artifacts=artifacts,
            builds=builds,
            runs=runs,
            executor=session.evaluations.executor,
        )

        def child(parent, role, number, contribution):
            invocation_id = content_id("invocation", {"role": role, "number": number})
            with session.view() as view:
                candidate_ref = view.candidate.ref.as_record()
            body = {
                **parent.assignment.as_record()["body"],
                "parent_assignment_ref": parent.assignment.ref.as_record(),
                "role": role,
                "scope_requirement_keys": keys,
                "contribution_requirement_keys": contribution,
                "preservation_requirement_keys": [],
                "baseline_candidate_ref": candidate_ref,
                "allowed_child_bindings": list(CHILDREN[role]),
                "supersedes_assignment_refs": [],
            }
            body["judgment_lineage"] = judgment_lineage(body)
            assignment = session.record(parent, "assignment", body)
            session.commit(
                parent,
                "assign",
                {
                    "assignment": assignment.as_record(),
                    "invocation_id": invocation_id.value,
                },
            )
            session.commit(
                parent, "enter_child", {"invocation_id": invocation_id.value}
            )
            call = Invocation(
                invocation_id,
                assignment,
                (*parent.path, (session.nodes[role].grain_name, invocation_id.value)),
                parent.goal,
                unit_id=content_id("unit", invocation_id.value),
            )
            path = [{"grain": grain, "key": key} for grain, key in call.path]
            session.calls[episode_id_for_path(session.registration.logical_run_id, path).value] = call
            return call

        designer = child(root, "designer", 0, keys)
        plan = session.record(
            designer,
            "design_plan",
            {
                "assignment_ref": designer.assignment.ref.as_record(),
                "approach_key": "preserve both properties",
                "requirement_mapping": keys,
                "assumption_refs": [],
                "proposed_component_refs": [],
                "intended_change_scope": [source_path],
                "dependency_effects": [],
                "local_measure_ref": designer.assignment.body["local_measure_ref"],
                "acceptance_measure_ref": designer.assignment.body[
                    "acceptance_measure_ref"
                ],
                "preservation_measure_refs": [],
                "expected_observation_refs": [],
                "falsifying_observation_refs": [],
                "open_need_refs": [],
            },
        )
        session.commit(designer, "admit_plan", {"plan": plan.as_record()})
        candidates, children, experiment_ids = [], [], []
        for number, values in enumerate(((True, False), (False, True), (True, False))):
            active = child(designer, "implementer", number, [keys[number % 2]])
            children.append(active)
            with session.view() as view:
                before = view.candidate
            change = session.record(
                active,
                "change",
                {
                    "assignment_ref": active.assignment.ref.as_record(),
                    "design_plan_ref": plan.ref.as_record(),
                    "expected_head_ref": before.ref.as_record(),
                    "file_operations": [
                        {
                            "kind": "replace",
                            "logical_path": source_path,
                            "before_hash": before.body["files"][source_path],
                            "after_blob_hash": builds.put_blob(
                                f"# Measured fixture revision {number}\n".encode()
                                + source
                            ).value,
                        }
                    ],
                    "implementation_detail_operations": [],
                    "rationale_claim_refs": [],
                },
            )
            session.commit(active, "apply_change", {"change": change.as_record()})
            with session.view() as view:
                candidates.append(view.candidate.ref.as_record())
            path = [{"grain": grain, "key": key} for grain, key in active.path]
            prepared = await session.exchange(
                episode_id=episode_id_for_path(session.registration.logical_run_id, path),
                episode_path=path,
                operation="evaluate",
                payload={
                    "unit_id": active.unit_id.value,
                    "purpose": "local",
                },
            )
            if not prepared["source_admitted"]:
                pytest.fail(str(source_deficits(session, active.invocation_id)))
            target = prepared["experiment_targets"][0]
            proposal = {
                "evaluation_request_ref": target["evaluation_request_ref"],
                "experiment": {
                    "schema_version": 1,
                    "question": "Which of the two assigned properties holds after this revision?",
                    "rationale": "Retain both results so repairs in distinct child assignments can be compared.",
                    **{
                        key: target[key]
                        for key in (
                            "candidate_ref",
                            "build_receipt_ref",
                            "environment_ref",
                            "campaign_ref",
                            "launch_ref",
                        )
                    },
                    "scope": {
                        "kind": "workflow",
                        "entry_local_id": target["root_local_id"],
                        "included_local_ids": target["local_ids"],
                        "component_definition_id": None,
                        "unit_label": None,
                        "invocation_path": [],
                    },
                    "boundary": {"parent_context_ref": None, "children": "execute"},
                    "start": {
                        "kind": "fresh",
                        "artifact_ref": None,
                        "input_payload": target["assigned_inputs"],
                    },
                    "mode": "live_fresh",
                    "recording_ref": None,
                    "requirements": [
                        {
                            **{
                                key: row[key]
                                for key in ("requirement_ref", "measure_ref")
                            },
                            "expected": "The property is true.",
                            "falsifying": "A false property is a counterexample.",
                        }
                        for row in target["requirements"]
                    ],
                    "unresolved_questions": [
                        "Supplied outputs do not establish source correctness."
                    ],
                },
            }
            # Host-authored fixture intent uses the same validation/admission as
            # authenticated worker proposals, without pretending a model chose it.
            spec, assigned = _validate(session.evaluations, session, active, proposal)
            session.evaluations.executor.result = dict(
                zip(("goal", "progress"), values, strict=True)
            )
            result = await service.run(spec)
            _receive(session.evaluations, session, active, spec, assigned, result)
            experiment_ids.append(spec.experiment_id)
            session.commit(
                active,
                "close_unit",
                {
                    "candidate_before_ref": before.ref.as_record(),
                    "continuation_ref": None,
                },
            )
            if number < 2:
                session.commit(active, "return_child", {})

        def no_scan(*args, **kwargs):
            raise AssertionError(
                "shared regression discovery cannot reconstruct audit or enumerate the campaign"
            )

        monkeypatch.setattr(type(runs), "_load_event_chain_locked", no_scan)
        monkeypatch.setattr(type(runs), "read_evidence", no_scan)
        from iterative_episode_refiner.campaign_store import CampaignView

        monkeypatch.setattr(CampaignView, "entries", no_scan)
        query = {
            "kind": "refinement",
            "campaign_id": session.campaign_id.value,
            "invocation_id": root.invocation_id.value,
            "refinement_collection": "conflicts",
        }
        history = service.history(artifacts, runs, duet_id=session.duet_id, query=query)
        incident = next(
            row for row in history["items"] if row["kind"] == "opposing_regression"
        )
        assert incident["state"] == "decision_required"
        assert incident["scope_owner_invocation_id"] == root.invocation_id.value
        assert [
            row["candidate_ref"] for row in incident["candidate_results"]
        ] == candidates
        vectors = [
            {
                row["test_result"]["outcome"]["requirement_key"]: row["test_result"][
                    "outcome"
                ]["status"]
                for row in candidate["observations"]
            }
            for candidate in incident["candidate_results"]
        ]
        assert vectors[0] == vectors[2] != vectors[1]
        assert all(set(vector.values()) == {"pass", "fail"} for vector in vectors)
        assert {
            row["invocation_id"]
            for candidate in incident["candidate_results"]
            for row in candidate["observations"]
        } == {call.invocation_id.value for call in children}
        assert {
            row["test_result"]["experiment_id"]
            for candidate in incident["candidate_results"]
            for row in candidate["observations"]
        } == set(experiment_ids)
        assert (
            history["related_queries"]["observations"]["invocation_id"]
            == root.invocation_id.value
        )
        default = service.history(
            artifacts,
            runs,
            duet_id=session.duet_id,
            query={**query, "refinement_collection": "observations"},
        )
        assert default["conflicts"]["items"] == history["items"]
