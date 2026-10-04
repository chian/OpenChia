"""Read-only report integration over real stores and typed fixture records.

The campaign index is seeded explicitly: these tests establish projection,
scope and provenance behavior, not admission, execution or live reasoning.
"""

from dataclasses import replace
import json

import pytest

from agent.duet_contracts import content_id, digest_record
from agent.duet_store import DuetStore
from episode_builder.store import BuildStore
from episode_runtime.records.outcomes import RequirementOutcome
from episode_runtime.store import RunStore
from iterative_episode_refiner.campaign_store import CampaignStore, CampaignView
from iterative_episode_refiner.context import local_context
from iterative_episode_refiner.evidence import EvidenceReader
from iterative_episode_refiner.records import EvidenceRef, RefinementRecord


@pytest.fixture
def report_campaign(tmp_path):
    with DuetStore(tmp_path / "reports.db") as duets:
        duet_id = content_id("duet", "report fixture").value
        campaign_id = content_id("campaign", "report fixture")
        parent_id = content_id("invocation", "parent")
        child_id = content_id("invocation", "child")
        duets.create_duet(duet_id=duet_id, identity={}, policy={}, state="specifying")
        store = CampaignStore(
            duets,
            EvidenceReader(duets, BuildStore(tmp_path), RunStore(tmp_path / "runs")),
        )
        source = store.put_data(duet_id, "fixture", {"test": "report projection"})
        policy = store.put_data(duet_id, "policy", {})
        catalog = store.put_data(
            duet_id,
            "requirement_catalog",
            {
                "requirements": [
                    {"requirement_key": key} for key in ("ordered", "unique")
                ]
            },
        )
        baseline = RefinementRecord(
            "candidate",
            campaign_id,
            {
                "parent_candidate_ref": None,
                "target_approval_ref": source.as_record(),
                "materialization_ref": source.as_record(),
                "files": {"target.py": digest_record({"revision": "tested"}).value},
                "implementation_directive_refs": [],
                "change_set_ref": None,
                "source_admission_ref": None,
            },
            source,
        )
        current = replace(
            baseline,
            body={
                **baseline.body,
                "parent_candidate_ref": baseline.ref.as_record(),
                "files": {"target.py": digest_record({"revision": "changed"}).value},
            },
        )
        contract = RefinementRecord(
            "campaign",
            campaign_id,
            {
                "duet_id": duet_id,
                "target_approval_ref": source.as_record(),
                "target_workflow_ref": source.as_record(),
                "initial_build_receipt_ref": source.as_record(),
                "initial_materialization_ref": source.as_record(),
                "refiner_workflow_approval_ref": source.as_record(),
                "refiner_manifest_ref": source.as_record(),
                "requirement_catalog_ref": catalog.as_record(),
                "authority_ref": source.as_record(),
                "policy_bundle_ref": policy.as_record(),
                "environment_ref": source.as_record(),
                "guidance_catalog_ref": None,
                "final_projection_ref": source.as_record(),
            },
            source,
        )

        def assignment(role, invocation_id, scope, parent=None):
            return RefinementRecord(
                "assignment",
                campaign_id,
                {
                    "parent_assignment_ref": None
                    if parent is None
                    else parent.ref.as_record(),
                    "owning_parts_invocation_id": parent_id.value,
                    "role": role,
                    "scope_requirement_keys": scope,
                    "contribution_requirement_keys": scope,
                    "scope_partition_ref": source.as_record(),
                    "owned_slice_keys": ["target"],
                    "baseline_candidate_ref": baseline.ref.as_record(),
                    "goal_record_ref": source.as_record(),
                    "authority_ref": source.as_record(),
                    "input_refs": [],
                    "preservation_requirement_keys": [],
                    "dependency_refs": [],
                    "local_measure_ref": source.as_record(),
                    "acceptance_measure_ref": source.as_record(),
                    "progress_manifest_ref": source.as_record(),
                    "allowed_action_classes": ["request_evaluation"],
                    "allowed_child_bindings": [],
                    "instruction_refs": [],
                    "history_query_ref": source.as_record(),
                    "return_projection_ref": source.as_record(),
                    "control_bundle_ref": source.as_record(),
                    "supersedes_assignment_refs": [],
                    "writable_paths": [],
                    "protected_paths": [],
                    "judgment_lineage": content_id("lineage", role).value,
                },
                source,
                invocation_id=invocation_id,
            )

        parent = assignment("parts", parent_id, ["ordered", "unique"])
        child = assignment("implementer", child_id, ["ordered"], parent)
        checks, observations, requests = [], [], []
        for key, expected, observed in (
            ("ordered", ["beta", "alpha"], ["beta", "alpha"]),
            ("unique", 2, "sibling-only observation"),
        ):
            check = RefinementRecord(
                "check",
                campaign_id,
                {
                    "requirement_key": key,
                    "evidence_kind": "execution",
                    "origin_refs": [source.as_record()],
                    "measure_ref": source.as_record(),
                    "purpose": "composition",
                    "predicate_ref": source.as_record(),
                    "expected": expected,
                    "dependency_paths": ["target.py"],
                    "environment_ref": source.as_record(),
                    "mandatory": True,
                    "guard_keys": [],
                    "grounding_refs": [source.as_record()],
                    "observation_path": f"/{key}",
                },
                source,
            )
            request = RefinementRecord(
                "evaluation",
                campaign_id,
                {
                    "candidate_ref": baseline.ref.as_record(),
                    "measure_ref": source.as_record(),
                    "check_keys": [check.artifact_id.value],
                    "input_refs": [],
                    "environment_ref": source.as_record(),
                    "harness_ref": source.as_record(),
                    "purpose": "composition",
                    "parent_operation_id": content_id("operation", key).value,
                    "capability_ref": source.as_record(),
                },
                source,
                invocation_id=child_id if key == "ordered" else parent_id,
            )
            observation = RefinementRecord(
                "observation",
                campaign_id,
                {
                    "request_ref": request.ref.as_record(),
                    "execution_ref": source.as_record(),
                    "checked_dependency_hashes": {
                        "target.py": baseline.body["files"]["target.py"]
                    },
                    "check_key": check.artifact_id.value,
                    "observed_value": observed,
                    "outcome": "pass" if key == "ordered" else "fail",
                    "counterexample_refs": [],
                    "limitation_refs": [],
                },
                source,
                evidence_refs=(
                    EvidenceRef(
                        "duet_artifact",
                        content_id("duet", "report fixture"),
                        source.artifact_id,
                        source.content_hash,
                        "",
                    ),
                ),
                invocation_id=request.invocation_id,
            )
            checks.append(check)
            requests.append(request)
            observations.append(observation)
        with duets.transaction() as connection:
            for record in (
                contract,
                baseline,
                current,
                parent,
                child,
                *checks,
                *requests,
                *observations,
            ):
                store._put(connection, duet_id, record)
            connection.execute(
                "INSERT INTO refinement_campaign_heads VALUES (?, ?, ?, NULL, ?, ?, NULL, 0)",
                (
                    campaign_id.value,
                    duet_id,
                    contract.artifact_id.value,
                    baseline.artifact_id.value,
                    current.artifact_id.value,
                ),
            )
            rows = [
                ("invocation", invocation.value, assignment, "active")
                for invocation, assignment in (
                    (parent_id, parent),
                    (child_id, child),
                )
            ]
            rows += [
                ("check", check.artifact_id.value, check, "active") for check in checks
            ]
            rows += [
                ("observation", observation.artifact_id.value, observation, "active")
                for observation in observations
            ]
            rows += [
                ("check_state", check.artifact_id.value, observation, "stale")
                for check, observation in zip(checks, observations, strict=True)
            ]
            for collection, key, record, status in rows:
                connection.execute(
                    "INSERT INTO refinement_index VALUES (?, ?, ?, ?, ?, 0)",
                    (
                        campaign_id.value,
                        collection,
                        key,
                        record.artifact_id.value,
                        status,
                    ),
                )
        yield (
            store,
            campaign_id,
            parent_id,
            child_id,
            baseline,
            current,
            checks,
            observations,
        )


def test_parent_and_child_share_exact_results_without_widening_scope(report_campaign):
    store, campaign_id, parent, child, baseline, current, checks, observations = (
        report_campaign
    )
    report = store.project(campaign_id, parent).as_record()
    with store.duet_store.transaction() as connection:
        view = CampaignView(connection, campaign_id)
        context = local_context(view, child).as_record()
    determinations = {
        row["requirement_key"]: row for row in report["body"]["determinations"]
    }
    result = determinations["ordered"]["test_result"]
    outcome = RequirementOutcome.model_validate(result["outcome"])
    assert (
        result["candidate_ref"] == baseline.ref.as_record() != current.ref.as_record()
    )
    assert result["criterion_ref"] == checks[0].ref.as_record()
    assert outcome.status == "pass"
    assert outcome.observed == outcome.criterion_expected == ["beta", "alpha"]
    assert outcome.evidence_ref.model_dump() == observations[0].ref.as_record()
    assert outcome.predicted is None and outcome.falsifying is None
    assert outcome.requirement_key == "ordered"
    assert determinations["ordered"]["candidate_ref"] == current.ref.as_record()
    assert determinations["ordered"]["outcome"] == "stale"
    assert "ordered" in report["body"]["unresolved_requirement_keys"]
    assert context["body"]["check_states"] == [
        {
            "check_key": checks[0].artifact_id.value,
            "status": "stale",
            "observation_ref": observations[0].ref.as_record(),
            "test_result": result,
        }
    ]
    assert "sibling-only observation" not in json.dumps(context)
    assert determinations["unique"]["test_result"]["outcome"]["status"] == "fail"
    assert observations[0].evidence_refs[0].as_record() in report["evidence_refs"]
    assert store.project(campaign_id, parent).as_record() == report

    from iterative_episode_refiner.reports import report_overview

    overview = report_overview(store.project(campaign_id, parent))
    assert overview["report_ref"] == {
        key: report[key] for key in ("artifact_id", "content_hash")
    }
    states = {row["check_key"]: row for row in overview["check_states"]}
    assert states[checks[0].artifact_id.value]["outcome"] == "stale"
    assert states[checks[0].artifact_id.value]["observation_ref"] == observations[0].ref.as_record()
    assert overview["unresolved_requirement_keys"] == report["body"]["unresolved_requirement_keys"]
    assert len(json.dumps(overview)) < len(json.dumps(report))
    assert overview["details_query"] == {"refinement_collection": "reports"}


def test_missing_or_conflicting_current_evidence_does_not_rewrite_history(
    report_campaign,
):
    store, campaign_id, parent, child, _baseline, _current, checks, observations = (
        report_campaign
    )
    with store.duet_store.transaction() as connection:
        connection.execute(
            "UPDATE refinement_index SET status = 'contradicted' WHERE campaign_id = ? "
            "AND collection = 'check_state' AND item_key = ?",
            (campaign_id.value, checks[0].artifact_id.value),
        )
        connection.execute(
            "DELETE FROM refinement_index WHERE campaign_id = ? "
            "AND collection = 'check_state' AND item_key = ?",
            (campaign_id.value, checks[1].artifact_id.value),
        )
    report = store.project(campaign_id, parent).as_record()["body"]
    determinations = {row["requirement_key"]: row for row in report["determinations"]}
    assert determinations["ordered"]["outcome"] == "contradicted"
    assert determinations["ordered"]["test_result"]["outcome"]["status"] == "pass"
    assert determinations["unique"]["outcome"] == "not_run"
    assert determinations["unique"]["test_result"] is None
    assert set(report["unresolved_requirement_keys"]) == {"ordered", "unique"}
    with store.duet_store.transaction() as connection:
        view = CampaignView(connection, campaign_id)
        assert view.read(observations[1].ref).as_record() == observations[1].as_record()
        assert (
            local_context(view, child).body["check_states"][0]["status"]
            == "contradicted"
        )


def test_history_uses_indexed_scope_and_cli_pages_without_reconstructing_audit(
    report_campaign,
    monkeypatch,
    tmp_path,
    capsys,
):
    from episode_runtime.records.refinement import assigned_history
    from episode_runtime.testing.service import ExperimentService
    from openchia_cli.episode_test_command import main

    store, campaign_id, parent, child, _baseline, _current, _checks, observations = (
        report_campaign
    )
    duet_id = content_id("duet", "report fixture").value

    def no_scan(*args, **kwargs):
        raise AssertionError(
            "history must page indexes, not decode the complete campaign or Run journal"
        )

    monkeypatch.setattr(CampaignView, "entries", no_scan)
    monkeypatch.setattr(store.duet_store, "events", no_scan)
    monkeypatch.setattr(type(store.evidence.runs), "_load_event_chain_locked", no_scan)
    query = {
        "kind": "refinement",
        "campaign_id": campaign_id.value,
        "invocation_id": parent.value,
        "limit": 1,
    }

    def history(value=query, owner=duet_id):
        return ExperimentService.history(
            store.duet_store,
            store.evidence.runs,
            duet_id=owner,
            query=value,
        )

    first = history()
    second = history(first["next_query"])
    assert first["campaign_head_ref"] == second["campaign_head_ref"]
    assert second["next_query"] is None
    assert {
        row["observation_ref"]["artifact_id"]
        for page in (first, second)
        for row in page["items"]
    } == {record.artifact_id.value for record in observations}
    assert all(
        row["current_status"] == "stale"
        for page in (first, second)
        for row in page["items"]
    )
    child_query = {**query, "invocation_id": child.value}
    child_history = history(child_query)
    assert len(child_history["items"]) == 1 and child_history["next_query"] is None
    assert "sibling-only observation" not in json.dumps(child_history)
    with store.duet_store.transaction() as connection:
        view = CampaignView(connection, campaign_id)
        assert assigned_history(view, child, {"limit": 1}) == child_history
        with pytest.raises(ValueError, match="host-bound"):
            assigned_history(view, child, query)
    with pytest.raises(ValueError, match="another campaign or owner"):
        history(owner="unrelated")
    with pytest.raises(ValueError, match="outside the assigned scope"):
        history({
            **first["next_query"],
            "invocation_id": child.value,
            "after": observations[1].artifact_id.value,
        })
    with pytest.raises(ValueError, match="requires the returned campaign_head_ref"):
        history({**query, "after": first["next_cursor"]})

    query_file = tmp_path / "history-page.json"
    query_file.write_text(json.dumps(first["next_query"]), encoding="utf-8")
    assert (
        main([
            "history",
            "--duet-store",
            str(tmp_path / "reports.db"),
            "--duet-id",
            duet_id,
            "--run-store",
            str(tmp_path / "runs"),
            "--query",
            str(query_file),
        ])
        == 0
    )
    assert json.loads(capsys.readouterr().out) == second

    # Ordinary testing access must not accept a worker-selected campaign owner.
    with pytest.raises(ValueError, match="host-bound refinement assignment"):
        ExperimentService.history(
            store.duet_store,
            store.evidence.runs,
            duet_id=duet_id,
            query=query,
            invocation={
                "run_id": "test-run",
                "episode_id": "test-episode",
                "registration_hash": "test-hash",
            },
        )
    with store.duet_store.transaction() as connection:
        view = CampaignView(connection, campaign_id)
        commit = RefinementRecord(
            "commit",
            campaign_id,
            {
                "previous_commit_ref": view.contract.ref.as_record(),
                "sequence": 1,
                "attempt_ref": view.contract.ref.as_record(),
                "deltas": [],
            },
            view.contract.producer_ref,
        )
        store._put(connection, duet_id, commit)
        connection.execute(
            "UPDATE refinement_campaign_heads SET latest_commit_id = ?, sequence = 1 WHERE campaign_id = ?",
            (commit.artifact_id.value, campaign_id.value),
        )
    with pytest.raises(ValueError, match="campaign changed while paging"):
        history(first["next_query"])


def test_history_shares_parent_conflicts_but_filters_child_details(report_campaign):
    from episode_runtime.records.refinement import assigned_history
    from episode_runtime.testing.service import ExperimentService

    store, campaign_id, parent, child, _baseline, _current, _checks, observations = (
        report_campaign
    )
    duet_id = content_id("duet", "report fixture").value
    parent_report = store.project(campaign_id, parent)
    child_report = store.project(campaign_id, child)
    conflict = RefinementRecord(
        "conflict",
        campaign_id,
        {
            "requirement_keys": ["ordered", "unique"],
            "observation_refs": [record.ref.as_record() for record in observations],
            "transition_refs": [],
            "kind": "opposing_regressions",
            "scope_owner_invocation_id": parent.value,
            "involved_assignment_refs": [
                parent_report.body["assignment_ref"],
                child_report.body["assignment_ref"],
            ],
            "applicability_ref": parent_report.producer_ref.as_record(),
            "state": "decision_required",
            "resolution_ref": None,
        },
        parent_report.producer_ref,
    )
    with store.duet_store.transaction() as connection:
        for collection, record, status in (
            ("report", parent_report, "active"),
            ("report", child_report, "active"),
            ("conflict", conflict, "decision_required"),
        ):
            store._put(connection, duet_id, record)
            connection.execute(
                "INSERT INTO refinement_index VALUES (?, ?, ?, ?, ?, 0)",
                (
                    campaign_id.value,
                    collection,
                    record.artifact_id.value,
                    record.artifact_id.value,
                    status,
                ),
            )
        view = CampaignView(connection, campaign_id)
        parent_conflicts = assigned_history(
            view, parent, {"refinement_collection": "conflicts"}
        )
        child_conflicts = assigned_history(
            view, child, {"refinement_collection": "conflicts"}
        )
        assert (
            parent_conflicts["items"][0]["observation_refs"]
            == conflict.as_record()["body"]["observation_refs"]
        )
        limited = child_conflicts["items"][0]
        assert limited["requirement_keys"] == ["ordered"]
        assert limited["observation_refs"] == [observations[0].ref.as_record()]
        assert limited["withheld_observation_count"] == 1
        assert limited["scope_owner_invocation_id"] == parent.value
        assert len(parent_conflicts["items"][0]["candidate_results"]) == 1
        results = parent_conflicts["items"][0]["candidate_results"][0]["observations"]
        assert {row["test_result"]["outcome"]["status"] for row in results} == {
            "pass",
            "fail",
        }
        assert {row["invocation_id"] for row in results} == {parent.value, child.value}
        assert "sibling-only observation" not in json.dumps(child_conflicts)
        assert all(
            row["test_result"]["outcome"]["requirement_key"] == "ordered"
            for row in limited["candidate_results"][0]["observations"]
        )
        followup = child_conflicts["related_queries"]["observations"]
        detail = assigned_history(view, child, followup)
        assert [row["observation_ref"] for row in detail["items"]] == [
            observations[0].ref.as_record()
        ]
        with pytest.raises(ValueError, match="outside the assigned scope"):
            assigned_history(view, child, {"requirement_key": "unique"})
        resolved = replace(
            conflict,
            body={
                **conflict.body,
                "state": "resolved",
                "resolution_ref": conflict.producer_ref.as_record(),
            },
            predecessor_refs=(conflict.ref,),
        )
        store._put(connection, duet_id, resolved)
        connection.execute(
            "INSERT INTO refinement_index VALUES (?, 'conflict', ?, ?, 'resolved', 99)",
            (
                campaign_id.value,
                resolved.artifact_id.value,
                resolved.artifact_id.value,
            ),
        )
        default = assigned_history(view, parent)
        assert [row["conflict_ref"] for row in default["conflicts"]["items"]] == [
            conflict.ref.as_record()
        ]
        assert default["conflicts"]["query"]["conflict_status"] == "decision_required"
        all_incidents = assigned_history(
            view, parent, {"refinement_collection": "conflicts"}
        )
        assert {row["state"] for row in all_incidents["items"]} == {
            "decision_required",
            "resolved",
        }
    query = {
        "kind": "refinement",
        "campaign_id": campaign_id.value,
        "invocation_id": parent.value,
        "refinement_collection": "reports",
    }
    reports = ExperimentService.history(
        store.duet_store, store.evidence.runs, duet_id=duet_id, query=query
    )
    assert {row["report_ref"]["artifact_id"] for row in reports["items"]} == {
        parent_report.artifact_id.value,
        child_report.artifact_id.value,
    }
    query["invocation_id"] = child.value
    child_reports = ExperimentService.history(
        store.duet_store, store.evidence.runs, duet_id=duet_id, query=query
    )
    assert [row["report_ref"] for row in child_reports["items"]] == [
        child_report.ref.as_record()
    ]
