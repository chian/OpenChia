"""Candidate environment edits use the same admission and evidence identities."""

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from episode_runtime.target_environment import ENVIRONMENT_RECIPE_PATH, TargetEnvironmentRecipe
from iterative_episode_refiner.candidate_source import project_candidate_sources
from iterative_episode_refiner.measurement import dependency_hashes


@pytest.mark.asyncio
async def test_broken_recipe_is_durable_repairable_and_invalidates_source_only_evidence(campaign):
    campaign.implementer(additional_paths=[ENVIRONMENT_RECIPE_PATH])
    original = campaign.candidate

    def edit(text):
        before = campaign.candidate
        old = before.body["files"].get(ENVIRONMENT_RECIPE_PATH)
        change = campaign.record("change", {
            "assignment_ref": campaign.implementation.ref.as_record(),
            "design_plan_ref": campaign.plan.ref.as_record(),
            "expected_head_ref": before.ref.as_record(),
            "file_operations": [{
                "kind": "add" if old is None else "replace",
                "logical_path": ENVIRONMENT_RECIPE_PATH,
                "before_hash": old,
                "after_blob_hash": campaign.builds.put_blob(text.encode()).value,
            }],
            "implementation_detail_operations": [], "rationale_claim_refs": [],
        })
        campaign.perform("apply_change", {"change": change.as_record()})
        return campaign.candidate

    broken = edit('{"dependencies":')
    projected = project_candidate_sources(campaign.store.evidence, campaign.session.contract, broken)
    assert any(item.code == "environment_recipe_invalid" for item in projected.deficits)
    from iterative_episode_refiner.candidate_environment import findings
    from iterative_episode_refiner.model_inputs import _feedback
    from iterative_episode_refiner.runtime import Invocation
    from iterative_episode_refiner.report_contract import _environment_findings

    call = Invocation(
        invocation_id=campaign.current_invocation, assignment=campaign.implementation,
        path=(), goal=campaign.session.calls[campaign.session.root_id].goal,
        unit_id=campaign.unit,
    )
    await campaign.session.evaluations.prepare_environment(
        campaign.session, call, {"unit_id": campaign.unit.value, "purpose": "local"},
    )
    with campaign.session.view() as view:
        returned = _feedback(campaign.session, view, call)
        history = findings(view, invocation_id=campaign.current_invocation.value)
        parent_findings = _environment_findings(view, campaign.implementation, {
            "invocation_id": campaign.current_invocation.value, "child_report_refs": [],
        }, {})
    assert returned["status"] == "failed"
    assert returned["diagnostics"][0]["code"] == "environment_recipe_invalid"
    assert returned["log_refs"][0]["content_hash"] == broken.body["files"][ENVIRONMENT_RECIPE_PATH]
    assert history[-1]["record_ref"] == call.feedback_ref.as_record()
    assert parent_findings[-1]["recipe_path"] == ENVIRONMENT_RECIPE_PATH
    assert parent_findings[-1]["diagnostics"] == returned["diagnostics"]
    assert call.feedback_ref.artifact_id.value not in json.dumps(parent_findings)
    assert broken.artifact_id.value not in json.dumps(parent_findings)
    recipe = TargetEnvironmentRecipe(python="3.14", dependencies=("packaging>=24,<26",),
                                     import_roots=("packaging",), setup_instructions="Use the managed environment.")
    corrected = edit(json.dumps(recipe.as_record()))
    projected = project_candidate_sources(campaign.store.evidence, campaign.session.contract, corrected)
    assert projected.environment_recipe == recipe.as_record()
    assert not any(item.code == "environment_recipe_invalid" for item in projected.deficits)
    assert campaign.builds.read_blob(broken.body["files"][ENVIRONMENT_RECIPE_PATH]) == b'{"dependencies":'
    assert corrected.body["files"][campaign.source_path] == original.body["files"][campaign.source_path]
    check = next(row.record for row in campaign.entries("check") if row.record.body["evidence_kind"] == "execution")
    source_only = replace(check, body={**check.body, "dependency_paths": [campaign.source_path]})
    assert dependency_hashes(source_only, original) != dependency_hashes(source_only, broken)
    assert dependency_hashes(source_only, broken) != dependency_hashes(source_only, corrected)
    assert not campaign.entries("unit")  # Environment edits are not behavioral credit.


@pytest.mark.asyncio
async def test_admitted_package_retains_exact_recipe_and_lock(campaign):
    from agent.duet_contracts import canonical_json
    from agent.episode_contracts import Sha256Digest
    from episode_builder._contract_chain import BuildManifest
    from episode_runtime.target_environment import TargetEnvironmentLock

    inputs = campaign.builds.inspection_inputs_for_receipt(
        campaign.session.materialization_handoff["receipt_id"]
    )
    recipe = TargetEnvironmentRecipe(python="3.14", dependencies=("packaging==25.0",),
                                     import_roots=("packaging",))
    lock = TargetEnvironmentLock(recipe.recipe_hash, Sha256Digest.of_record({"runtime": "test"}),
                                 'version = 1\n[[package]]\nname = "packaging"\nversion = "25.0"\n')
    manifest = replace(inputs.manifest, environment_recipe=recipe.as_record(), environment_lock=lock.as_record())
    assert manifest.manifest_id != inputs.manifest.manifest_id
    assert BuildManifest.from_record(manifest.as_record()) == manifest
    campaign.builds.put_manifest(manifest)
    package = campaign.builds.publish_source_package(manifest)
    assert campaign.builds.verify_source_package(manifest) == package
    assert (package / ENVIRONMENT_RECIPE_PATH).read_text(encoding="utf-8") == canonical_json(recipe.as_record())
    assert (package / "TARGET_ENVIRONMENT_LOCK.json").read_text(encoding="utf-8") == canonical_json(lock.as_record())
    other = TargetEnvironmentRecipe(python="3.14", dependencies=("packaging==24.0",), import_roots=("packaging",))
    with pytest.raises(ValueError, match="different recipe"):
        replace(manifest, environment_recipe=other.as_record())


@pytest.mark.parametrize("receiver", ["evaluation", "control"])
@pytest.mark.parametrize("location", ["target", "plan", "checker", "continued_checker"])
def test_experiment_preparation_diagnostics_reach_next_input_and_requested_report(
    campaign, receiver, location,
):
    """Storage/projection invariant; the unavailable Run result is supplied data."""
    from iterative_episode_refiner.evaluation_experiments import _receive
    from iterative_episode_refiner.measure_experiments import receive
    from iterative_episode_refiner.model_inputs import _feedback
    from iterative_episode_refiner.candidate_environment import findings
    from iterative_episode_refiner.report_contract import _environment_findings
    from iterative_episode_refiner.runtime import Invocation

    campaign.implementer(additional_paths=[ENVIRONMENT_RECIPE_PATH])
    session = campaign.session
    root = session.calls[session.root_id]
    path = (*root.path, (session.nodes["designer"].grain_name, "design"),
            (session.nodes["implementer"].grain_name, campaign.current_invocation.value))
    call = Invocation(campaign.current_invocation, campaign.implementation, path,
                      root.goal, unit_id=campaign.unit)
    log = campaign.builds.put_blob(b"Dependency download failed; complete diagnostic stream.")
    failure = {
        "status": "failed", "prepared": None,
        "diagnostics": [{"stage": "sync", "error_type": "DownloadFailure",
                         "message": "Could not retrieve the pinned dependency wheel."}],
        "log_refs": [{"stream": "stderr", "content_hash": log.value}],
        "preparation_ref": session.put_data("fixture_preparation", {"log": log.value}).as_record(),
    }
    result = {"execution_status": "unavailable"}
    if location == "plan":
        result["plan"] = {"resolved": False, "gaps": [], "environment_preparation": failure}
    elif location == "checker":
        result.update(execution_status="succeeded", instrument_runs=[{
            "execution_status": "unavailable", "environment_preparation": failure,
        }])
    else:
        result["environment_preparation"] = failure
        if location == "continued_checker":
            result["environment_subject"] = "measurement"
    spec = SimpleNamespace(experiment_id="supplied_unavailable_experiment")
    if receiver == "evaluation":
        _receive(session.evaluations, session, call, spec,
                 (campaign.plan, campaign.candidate, None, [], None), result)
    else:
        reference = campaign.plan.ref.as_record()
        receive(session.evaluations, session, call, spec, {
            "reference": reference,
            "binding": {field: reference for field in ("proposal_ref", "grounding_ref", "control_ref")},
        }, result)
    with session.view() as view:
        feedback = _feedback(session, view, call)
        own_history = findings(view, invocation_id=call.invocation_id.value)
        parent = _environment_findings(view, call.assignment, {
            "invocation_id": call.invocation_id.value, "child_report_refs": [],
        }, {})
    assert feedback["environment_findings"][0]["diagnostics"] == failure["diagnostics"]
    assert feedback["environment_findings"][0]["log_refs"] == failure["log_refs"]
    assert own_history[-1]["diagnostics"] == failure["diagnostics"]
    assert parent[-1]["diagnostics"] == failure["diagnostics"]
    assert parent[-1]["subject"] == ("measurement" if location in {"checker", "continued_checker"} else "target_workflow")
    assert log.value not in json.dumps(parent)
    assert not campaign.entries("observation")
