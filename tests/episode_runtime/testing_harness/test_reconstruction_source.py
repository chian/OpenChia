"""Whole-Run admission preserves exact code; later-unit admission stays narrow.

Builds and package preparation are real; materializer responses are supplied.
These tests do not execute Target Workflow code or establish resumed worker behavior.
"""

from contextlib import asynccontextmanager
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

from agent.duet_store import DuetStore
from agent.episode_contracts import EpisodeCreationSpec, Sha256Digest
from episode_builder.service import EpisodeBuilder
from episode_library.testing import DESIGN, testing_learning_contract as learning_contract
from episode_runtime.contracts import RuntimePolicy
from episode_runtime.identity import (
    inspect_runtime_source_manifest,
    runtime_identity_from_manifest,
)
from episode_runtime.linker import prepare_source_package
from episode_runtime.testing_harness.execution import register_build
from episode_runtime.testing_harness.inputs import workflow_template
from episode_runtime.testing_harness.reconstruction_source import (
    _admit_module,
    admit_reconstruction_source,
)
from function_library.reasoning import ReasoningSource
from function_library.testing_contract import TestingContract as Access
from llm_call_library import CallOptions
from llm_call_library.transport import ModelTransportResponse, model_transport_scope
from tests.episode_builder.test_repeatable_call_materialization import build
from tests.episode_runtime.conftest import numerical_control, oid
from tests.episode_runtime.test_reasoning_workflow import (
    _approved_request,
    _module_response,
    _plan_response,
)
from tests.episode_runtime.testing_harness.refinement_fixture import prepared_refiner
from tests.episode_runtime.testing_harness.test_experiment_planning import experiment
from tests.episode_runtime.testing_harness.test_scoped_execution import LinkedExecutor


@asynccontextmanager
async def reference_package(tmp_path, family):
    manifest = inspect_runtime_source_manifest(
        repository_root=Path(__file__).resolve().parents[3]
    )
    identity = runtime_identity_from_manifest(manifest)
    if family == "refinement":
        async with prepared_refiner(tmp_path, identity) as session:
            builds = session.store.evidence.builds
            inputs = builds.inspection_inputs_for_receipt(
                session.registration.build_receipt_id
            )
            package = builds.verify_source_package(inputs.manifest)
            yield (
                prepare_source_package(session.registration, package),
                package,
                manifest,
            )
        return
    request, builds, receipt = await build(tmp_path, ())
    if family == "testing":
        with DuetStore(tmp_path / "duet.db") as artifacts:
            specification = experiment(artifacts, request, receipt)
        target = {
            key: specification[key]
            for key in (
                "candidate_ref",
                "build_receipt_ref",
                "environment_ref",
                "launch_ref",
                "campaign_ref",
            )
        }
        target.update(
            requirements=[
                {key: item[key] for key in ("requirement_ref", "measure_ref")}
                for item in specification["requirements"]
            ],
            recording_refs=[],
            parent_context_refs=[],
        )
        contract = EpisodeCreationSpec(
            goal="Inspect the assigned candidate's evidence.",
            progress="Admitted measured findings.",
            stopping="Registered continuation.",
            numeric_control=numerical_control(),
            execution_capability_names=("episode_testing",),
            testing=Access({"candidate": target}, ("workflow",), ("live_fresh",)),
            epistemic=learning_contract(
                goal_class="testing",
                domain="fixture",
                environment={"fixture": "source_admission"},
            ),
        )
        request = _approved_request(
            tmp_path,
            spec=contract,
            reference=DESIGN,
            allowed_capabilities=("episode_testing",),
            duet_id=oid("testing_duet"),
        )

        async def materializer(call):
            prompt = json.loads(call.messages[-1]["content"])
            response = (
                _plan_response(prompt, testing=True)
                if "node" in prompt
                else _module_response(prompt)
            )
            return ModelTransportResponse(text=json.dumps(response), route={})

        with model_transport_scope(materializer):
            receipt = await EpisodeBuilder(
                store=builds,
                planning_options=CallOptions(model_type="planner"),
                emission_options=CallOptions(model_type="writer"),
                model_slot_catalog={"selector": {}, "executor": {}},
            ).build(request)
    assert receipt.materialized, [item.as_record() for item in receipt.deficits]
    inputs = builds.inspection_inputs_for_receipt(receipt.receipt_id)
    registration, package = register_build(
        LinkedExecutor(tmp_path / "execution", identity),
        builds,
        inputs,
        workflow_template(request.frozen_workflow),
        RuntimePolicy(),
    )
    yield prepare_source_package(registration, package), package, manifest


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ("refinement", "reasoning", "testing"))
async def test_admitted_reference_wrappers_require_the_same_frozen_runtime_without_activation(
    tmp_path, family
):
    async with reference_package(tmp_path, family) as (prepared, package, manifest):
        result = admit_reconstruction_source(
            prepared, source_package_path=package, runtime_manifest=manifest
        )
        assert {item["family"] for item in result["modules"]} == {
            "target" if family == "reasoning" else family
        }
        assert {item["local_id"] for item in result["modules"]} == set(prepared.modules)
        assert all(
            item["source_hash"] == prepared.modules[item["local_id"]].source_hash.value
            for item in result["modules"]
        )
        assert all(
            module.module_name not in sys.modules
            for module in prepared.modules.values()
        )
        assert result["limitations"]
        changed = dict(manifest.local_source_hashes)
        changed["function_library/reasoning.py"] = Sha256Digest.of_bytes(
            b"another reference implementation"
        )
        different = replace(manifest, local_source_hashes=changed)
        forged = replace(
            prepared,
            registration=replace(
                prepared.registration,
                runtime_identity=runtime_identity_from_manifest(different),
            ),
        )
        with pytest.raises(ValueError, match="different reference runtime"):
            admit_reconstruction_source(
                forged, source_package_path=package, runtime_manifest=different
            )


@pytest.mark.asyncio
async def test_later_unit_source_gate_rejects_generated_dispatch_and_import_effects(
    tmp_path,
):
    async with reference_package(tmp_path, "reasoning") as (
        prepared,
        package,
        manifest,
    ):
        # Generated package bytes are the data under test, not implementation
        # text inspected to infer another function's behavior.
        node = prepared.plan.nodes[0]
        source = (package / prepared.modules[node.local_id].relative_path).read_text(
            encoding="utf-8"
        )
        contract = prepared.build_request.frozen_workflow.workflow.episodes[0].contract
        expected = ReasoningSource.next
        mutations = {
            "module_mutation": source + "\nReasoningSource.next = None\n",
            "subclass": source
            + "\nclass GeneratedSource(ReasoningSource):\n    pass\n",
            "alias": source + "\nReasoningSource = TestingSource\n",
            "default_effect": source.replace(
                "collaborators, child_builders):",
                "collaborators, child_builders=setattr(ReasoningSource, 'next', None)):",
                1,
            ),
            "decorator": source.replace(
                "def build_episode(", "@staticmethod\ndef build_episode(", 1
            ),
            "controller_override": source.replace(
                "return host_controller_factory(goal_view, collaborators)",
                "return ReasoningSource(goal_view['goal'])",
                1,
            ),
            "goal_override": source.replace(
                "return ReasoningGoalState()", "return dict()", 1
            ),
            "helper": source + "\ndef generated_helper():\n    return None\n",
            "cross_module": source + "\nfrom another_generated_module import source\n",
            "top_level_effect": source + "\nsetattr(ReasoningSource, 'next', None)\n",
            "metadata_effect": source.replace(
                "title='Task inquiry'",
                "title=str(setattr(ReasoningSource, 'next', None))",
                1,
            ),
        }
        for name, changed in mutations.items():
            assert changed != source, name
            with pytest.raises(ValueError):
                _admit_module(changed, node=node, contract=contract, edges=())
            assert ReasoningSource.next is expected, name
        # None of the attempted overrides poisoned subsequent source admission.
        assert (
            admit_reconstruction_source(
                prepared, source_package_path=package, runtime_manifest=manifest
            )["modules"][0]["family"]
            == "target"
        )
