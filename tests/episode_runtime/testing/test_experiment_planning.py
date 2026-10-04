"""Contract/preview integration through real approval, BuildStore and DuetStore.

The deterministic Builder response fixture materializes source; these checks do
not execute a candidate or stand in for the goal's live reasoning acceptance.
"""

import json
import sys

import pytest

from agent.duet_contracts import content_id, digest_record
from agent.duet_store import DuetStore
from episode_runtime.testing.contracts import ExperimentError, ExperimentSpec
from episode_runtime.testing.planning import preview_experiment
from openchia_cli.episode_test_command import main
from tests.episode_builder.test_repeatable_call_materialization import build, call


def data_ref(store, duet_id, kind, value):
    reference = {
        "artifact_id": content_id(kind, {"duet_id": duet_id, "value": value}).value,
        "content_hash": digest_record(value).value,
    }
    store.put_artifact(
        **reference,
        duet_id=duet_id,
        kind=kind,
        revision=1,
        record=value,
    )
    return reference


def experiment(store, request, receipt):
    duet_id = request.frozen_workflow.duet_id.value
    return {
        "schema_version": 1,
        "question": "Does this candidate return an admissible problem frontier?",
        "rationale": "Inspect the complete inquiry before attributing a child-level defect.",
        "candidate_ref": {
            "artifact_id": receipt.receipt_id.value,
            "content_hash": receipt.content_hash.value,
        },
        "build_receipt_ref": {
            "artifact_id": receipt.receipt_id.value,
            "content_hash": receipt.content_hash.value,
        },
        "environment_ref": data_ref(
            store, duet_id, "environment", {"dataset": "test-v1"}
        ),
        "scope": {
            "kind": "workflow",
            "entry_local_id": "inquiry",
            "included_local_ids": ["inquiry"],
            "component_definition_id": None,
            "unit_label": None,
            "invocation_path": [],
        },
        "boundary": {"parent_context_ref": None, "children": "execute"},
        "start": {"kind": "fresh", "artifact_ref": None, "input_payload": {}},
        "mode": "live_fresh",
        "recording_ref": None,
        "launch_ref": data_ref(store, duet_id, "launch", {"routes": {"test": "local"}}),
        "campaign_ref": None,
        "requirements": [
            {
                "requirement_ref": data_ref(
                    store, duet_id, "requirement", {"field": "frontier"}
                ),
                "measure_ref": data_ref(
                    store, duet_id, "measure", {"predicate": "admitted_frontier"}
                ),
                "expected": "Every surviving problem has evidence and an answer contract.",
                "falsifying": "A surviving problem has no evidence or no answer contract.",
            }
        ],
        "unresolved_questions": [],
    }


@pytest.mark.asyncio
async def test_preview_binds_real_build_and_never_turns_resolution_into_acceptance(
    tmp_path, capsys, monkeypatch
):
    request, builds, receipt = await build(tmp_path, (call(),))
    assert receipt.materialized, [item.as_record() for item in receipt.deficits]
    with DuetStore(tmp_path / "duet.db") as store:
        raw = experiment(store, request, receipt)
        spec = ExperimentSpec.from_record(raw)
        preview = preview_experiment(spec, builds=builds, artifacts=store)
        assert preview["resolved"], preview["gaps"]
        assert not preview["execution_authorized"]
        assert (
            preview["scope"]["included_local_ids"] == raw["scope"]["included_local_ids"]
        )
        assert preview["scope"]["internal_edges"][0]["child_local_id"] == "inquiry"
        assert preview["workflow_hash"] == request.frozen_workflow.workflow_hash.value
        claimed = spec.as_record()
        claimed["candidate_ref"] = data_ref(
            store,
            request.frozen_workflow.duet_id.value,
            "candidate",
            {"claim": "This is the corrected implementation."},
        )
        refused = preview_experiment(
            ExperimentSpec.from_record(claimed), builds=builds, artifacts=store
        )
        assert not refused["resolved"]
        assert any(
            gap["kind"] == "candidate_source_mismatch" for gap in refused["gaps"]
        )
        assert preview["candidate"]["source_files"] == {
            module.module_name.replace(".", "/") + ".py": module.source_hash.value
            for module in builds.inspection_inputs_for_receipt(
                receipt.receipt_id
            ).emitted_modules
        }

        # Mutating caller data cannot edit an existing experiment's predictions.
        raw["requirements"][0]["expected"] = "Accept an empty unsupported result."
        changed = ExperimentSpec.from_record(raw)
        assert changed.experiment_id != spec.experiment_id
        assert (
            spec.as_record()["requirements"][0]["expected"]
            != raw["requirements"][0]["expected"]
        )
        assert preview_experiment(spec, builds=builds, artifacts=store) == preview

        # Missing recorded responses do not select a live fallback or enlarge scope.
        raw["mode"] = "recorded"
        recorded = preview_experiment(
            ExperimentSpec.from_record(raw), builds=builds, artifacts=store
        )
        assert not recorded["resolved"]
        assert any(gap["path"] == "recording_ref" for gap in recorded["gaps"])
        assert recorded["scope"] == preview["scope"]

    # Exercise the installed entry point without initializing a chat session or
    # opening a model connection. The preview is the same service, not a CLI copy.
    from openchia_cli.openchia_main import main as installed_main

    spec_path = tmp_path / "experiment.json"
    spec_path.write_text(spec.canonical_record, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "openchia",
            "test",
            "preview",
            "--spec",
            str(spec_path),
            "--duet-store",
            str(tmp_path / "duet.db"),
            "--build-store",
            str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit) as completed:
        installed_main()
    assert completed.value.code == 0
    assert json.loads(capsys.readouterr().out) == preview

    assert main(["describe"]) == 0
    description = json.loads(capsys.readouterr().out)
    assert set(description["scopes"]) >= {
        "component",
        "unit",
        "episode",
        "nested",
        "workflow",
        "refinement",
    }
    assert (
        description["modes"]["recorded"]["reused"]
        != description["modes"]["live_fresh"]["reused"]
    )


@pytest.mark.asyncio
async def test_invalid_or_unknown_scope_is_not_replaced_by_available_workflow(
    tmp_path, capsys
):
    request, builds, receipt = await build(tmp_path, ())
    with DuetStore(tmp_path / "duet.db") as store:
        raw = experiment(store, request, receipt)
        raw["scope"]["included_local_ids"] = ["inquiry", "invented_child"]
        preview = preview_experiment(
            ExperimentSpec.from_record(raw), builds=builds, artifacts=store
        )
        assert not preview["resolved"]
        assert "invented_child" in preview["scope"]["included_local_ids"]
        assert {gap["kind"] for gap in preview["gaps"]} >= {
            "unknown_episode",
            "incomplete_workflow",
        }

        raw["scope"]["included_local_ids"] = ["inquiry"]
        raw["scope"]["kind"] = "component"
        raw["boundary"]["children"] = "none"
        raw["scope"]["component_definition_id"] = "function_" + "0" * 64
        preview = preview_experiment(
            ExperimentSpec.from_record(raw), builds=builds, artifacts=store
        )
        assert not preview["resolved"]
        assert any(gap["kind"] == "component_not_bound" for gap in preview["gaps"])

        spec_path = tmp_path / "unsupported.json"
        spec_path.write_text(
            ExperimentSpec.from_record(raw).canonical_record, encoding="utf-8"
        )
        # An invalid backend image cannot distract from the scope explanation:
        # the CLI resolves scope before constructing any execution backend.
        assert (
            main([
                "run",
                "--spec",
                str(spec_path),
                "--duet-store",
                str(tmp_path / "duet.db"),
                "--build-store",
                str(tmp_path),
                "--run-store",
                str(tmp_path / "runs"),
                "--backend",
                "container",
                "--image",
                "missing-image",
            ])
            == 2
        )
        refused = json.loads(capsys.readouterr().out)
        assert refused["execution_status"] == "unavailable"
        assert refused["plan"]["scope"] == preview["scope"]
        assert not (tmp_path / "runs").exists()

        raw["start"]["kind"] = "saved_inputs"
        raw["start"]["artifact_ref"] = raw["environment_ref"]
        with pytest.raises(ExperimentError, match="live_fresh requires a fresh start"):
            ExperimentSpec.from_record(raw)

        raw["mode"] = "live_saved"
        raw["start"]["input_payload"] = {"quietly_replace_saved_inputs": True}
        with pytest.raises(ExperimentError, match="cannot be silently overlaid"):
            ExperimentSpec.from_record(raw)
