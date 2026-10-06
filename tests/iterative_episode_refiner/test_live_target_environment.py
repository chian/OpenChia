"""Opt-in real Implementer edits, dependency preparation and independent native Run.

The initial approved scaffold, assignment and exact-answer criterion are fixtures.
The coding response, edits, package resolution and Target Workflow execution are
real. This is an environment integration acceptance, not autonomous Parts/Designer
acceptance. The broken recipe is starting input; only the real coder repairs it.
No supplied MODEL_RESPONDED event or coding-agent verdict is accepted as evidence.
The existing PM fixture stages real uv bytes with supplied disposable tool facts;
this checks resolution and execution, not production installer attestation.
"""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from agent.duet_contracts import content_id
from agent.episode_contracts import EpisodeCreationSpec, EpisodeDesignSpec, EpisodeWorkflowSpec, OpaqueId
from agent.episode_launch import resolve_launch
from episode_builder.service import EpisodeBuilder
from episode_builder.store import BuildStore
from episode_runtime import protocol
from episode_runtime.broker import ScopedModelBroker, model_request_record
from episode_runtime.contracts import RunEventKind, RunEventOrigin, RunTerminalStatus
from episode_runtime.exchanges import broker_model_request
from episode_runtime.executor import make_systemd_run_executor_factory
from episode_runtime.records.experiments import put_data
from episode_runtime.store import RunStore
from episode_runtime.target_environment import ENVIRONMENT_RECIPE_PATH
from episode_runtime.target_environment_preparation import EnvironmentPreparationService
from episode_runtime.testing_harness.contracts import ExperimentSpec
from episode_runtime.testing_harness.service import ExperimentService
from iterative_episode_refiner.candidate_environment import prepare_candidate
from iterative_episode_refiner.candidate_source import admit_candidate, project_candidate_sources
from iterative_episode_refiner.coding import RefinementCodingTransport
from iterative_episode_refiner.runtime import Invocation
from llm_call_library import CallOptions
from llm_call_library.transport import ModelTransportRequest, ModelTransportResponse, model_transport_scope
from numeric_control_library import COMPOSE_INCIDENCE_CONTROLLER
from tests.episode_runtime.conftest import claim_store, numerical_control, oid
from tests.episode_runtime.test_reasoning_workflow import _approved_request, _binding, _module_response, _plan_response
from tests.episode_runtime.testing_harness.launch_fixture import FixtureLaunchHost
from tests.episode_runtime.testing_harness.refinement_fixture import prepared_refiner
from tests.episode_runtime.testing_harness.test_component_execution import assign_measure
from tests.episode_runtime.testing_harness.test_experiment_planning import experiment
from tests.episode_runtime.testing_harness.test_recorded_execution import _Channel
from tests.iterative_episode_refiner.conftest import CampaignFixture
from tests.iterative_episode_refiner.test_live_coding import live_binding
from tests.pm._fixtures import admitted_pm_tools as admitted_pm_tools


NUMBERS = [1234567, -9876543, 0]
EXPECTED = ["1,234,567", "-9,876,543", "0"]
GOAL = (
    "Use humanize.intcomma to format the integers [1234567, -9876543, 0]. "
    "Return a ClosedRecord with formatted (the three comma-separated strings) "
    "and dependency_version (humanize.__version__). Declare bounded public-PyPI "
    "humanize dependencies and the humanize import root in .openchia-environment.json."
)


async def build_scaffold(tmp_path, calls, *, workflow=None):
    """Only the initial incomplete implementation is supplied by the fixture."""
    contract = EpisodeCreationSpec(
        goal=GOAL, progress="Record the actual formatting computation, not a claim of setup success.",
        stopping="Use registered numerical continuation over the finite input observation.",
        numeric_control=numerical_control(0.9),
    )
    workflow = EpisodeWorkflowSpec((EpisodeDesignSpec("inquiry", None, contract),))
    request = _approved_request(tmp_path, workflow=workflow)
    builds = BuildStore(tmp_path)
    source = f'''
from method_loop import Leaf, ClosedRecord
from numeric_control_library.credit_assignment import CreditObservation
from numeric_control_library.controller import compose_controller
from function_library.reasoning import reasoning_credit_schema

def compute_formats(numbers):
    # Implementer must replace this incomplete implementation.
    return {{"formatted": [], "dependency_version": "unimplemented"}}

class FormattingResult(ClosedRecord):
    def __init__(self, result):
        self.result = result
    def as_record(self):
        return self.result

def formatting_controller():
    return compose_controller(
        schema=reasoning_credit_schema(), epoch="format-integers",
        credit_function=MARGINAL_DOMINATED_HYPERVOLUME,
        rarefaction_function=PAIRED_INCIDENCE,
        continuation_function=PREDICTED_CREDIT_UPPER_BOUND,
        credit_parameters=BINDING.controller.credit.arguments,
        rarefaction_parameters=BINDING.controller.rarefaction.arguments,
        continuation_parameters=BINDING.controller.continuation.arguments)

class FormattingSource:
    def __init__(self):
        self.result = None
    def next(self, view):
        if self.result is not None:
            return None
        return Leaf(unit={NUMBERS!r}, extract=compute_formats,
                    result=self.record, label="format-integers")
    def record(self, value, result):
        self.result = result
        return CreditObservation.observed({{reasoning_credit_schema().columns[0]: ({oid("formatting_observation").value!r},)}})
    def build_result(self, record):
        if self.result is None:
            raise ValueError("No formatting computation executed")
        return FormattingResult(self.result)

def build_formatting_episode(grain, key, request):
    source = FormattingSource()
    return Episode(grain=grain, key=key, request=request, source=source, build_result=source.build_result)
'''

    async def model(call):
        prompt = json.loads(call.messages[-1]["content"])
        if "node" in prompt:
            response = _plan_response(prompt)
            response["selected_function_bindings"][3] = _binding("controller.composer", COMPOSE_INCIDENCE_CONTROLLER)
        else:
            response = _module_response(prompt, extra_source=source,
                                        controller_expression="formatting_controller()",
                                        episode_expression="build_formatting_episode(grain, key, request)")
        return ModelTransportResponse(text=json.dumps(response), route={})

    with model_transport_scope(model):
        receipt = await EpisodeBuilder(store=builds, planning_options=CallOptions(model_type="planner"),
                                       emission_options=CallOptions(model_type="writer"),
                                       model_slot_catalog={"selector": {}, "executor": {}}).build(request)
    assert receipt.materialized, [row.as_record() for row in receipt.deficits]
    return request, builds, receipt


def seed_broken_recipe(campaign, python_version):
    recipe = {"schema_version": 1, "python": python_version, "dependencies": ["humanize==0.0.0"],
              "import_roots": ["humanize"], "setup_instructions": "Install the declared public-registry dependency."}
    change = campaign.record("change", {
        "assignment_ref": campaign.implementation.ref.as_record(),
        "design_plan_ref": campaign.plan.ref.as_record(),
        "expected_head_ref": campaign.candidate.ref.as_record(),
        "file_operations": [{"kind": "add", "logical_path": ENVIRONMENT_RECIPE_PATH,
                             "before_hash": None,
                             "after_blob_hash": campaign.builds.put_blob(json.dumps(recipe).encode()).value}],
        "implementation_detail_operations": [], "rationale_claim_refs": [],
    })
    campaign.perform("apply_change", {"change": change.as_record()})


async def coding_exchange(campaign, assignment, selected_binding):
    session = campaign.session
    root = session.calls[session.root_id]
    path = (*root.path, (session.nodes["designer"].grain_name, "design"),
            (session.nodes["implementer"].grain_name, campaign.current_invocation.value))
    wire_path = [{"grain": grain, "key": key} for grain, key in path]
    episode_id = protocol.episode_id_for_path(session.registration.logical_run_id, wire_path)
    call = Invocation(campaign.current_invocation, assignment, path, root.goal,
                      unit_id=campaign.unit, candidate_before=campaign.candidate.ref)
    session.calls[episode_id.value] = call
    record = {**selected_binding.record, "model_types": ["refinement"]}
    binding = SimpleNamespace(record=record, api_key=selected_binding.api_key, owner_duet_id=session.duet_id,
                              reference=put_data(campaign.duets, session.duet_id, "duet_model_binding", record))

    async def unused(_request):
        pytest.fail("Implementer must use its actual coding transport")

    receipts = []
    transport = RefinementCodingTransport(session=session, binding=binding, transport=unused,
                                         record_attempt=receipts.append)
    broker = ScopedModelBroker.from_plan(transport, session.plan)
    request = ModelTransportRequest("episode_structured_json_reasoning", "refinement", (
        {"role": "system", "content": "Implement the scoped assignment; preserve its approved Episode scaffold and host declaration."},
        {"role": "user", "content": json.dumps({"task": "change", "goal": GOAL,
            "instructions": "Implement compute_formats and create or repair the dependency recipe. "
                            "Do not install into OpenChia or personal Python. Preserve all host-owned declarations. "
                            "Read any environment preparation failure in the assignment before repairing."})},
    ), None, None, None, None, None)
    runs = session.store.evidence.runs
    claim_store(runs.root, session.registration, store=runs)  # Inert refiner transport fixture, not Target Workflow execution.
    protocol_binding = protocol.ProtocolBinding.from_registration(session.registration)
    channel = _Channel(protocol_binding)
    encoder = protocol.FrameEncoder(sender=protocol.FrameSender.WORKER, binding=protocol_binding)
    frame = protocol.decode_frame(encoder.encode("model_request", {
        "episode_id": episode_id.value, "episode_path": wire_path,
        "model_request_id": content_id("model_request", {"unit": call.unit_id.value}).value,
        "request": model_request_record(request),
    }), sender=protocol.FrameSender.WORKER, binding=protocol_binding, expected_sequence=0)
    await broker_model_request(run_store=runs, registration=session.registration, channel=channel,
                               frame=frame, model_broker=broker)
    response = [row for row in runs.read_committed_prefix(session.registration.run_id) if row.kind is RunEventKind.MODEL_RESPONDED][-1]
    await session.exchange(episode_id=episode_id, episode_path=wire_path, operation="propose", payload={
        "unit_id": call.unit_id.value, "task": "change", "raw_response": response.payload["response_text"],
        "producer_call_id": response.payload["producer_call_id"],
    })
    assert receipts[-1]["state"] == "succeeded", receipts[-1]
    assert campaign.candidate.ref != call.candidate_before, session.snapshot(call)
    runs.finalize_run(run_id=session.registration.run_id, origin=RunEventOrigin.HOST,
                      sender_sequence=channel.sequence, terminal_status=RunTerminalStatus.CANCELLED,
                      typed_status={"outcome": "cancelled", "reason": "Focused coding-exchange fixture ends; no autonomous refiner Run claimed."})
    return call, receipts[-1]


async def independently_run(session, receipt, preparation, tmp_path, factory):
    inputs = session.evaluations.builder.store.inspection_inputs_for_receipt(receipt.receipt_id)
    artifacts, builds = session.store.evidence.duets, session.store.evidence.builds
    executor = factory(RunStore(tmp_path / "independent-runs"))
    service = EnvironmentPreparationService(artifacts=artifacts, builds=builds, runs=executor.run_store, executor=executor)
    fresh = await service.prepare(inputs.manifest.environment_recipe, duet_id=session.duet_id,
                                  resolved_lock=inputs.manifest.environment_lock, fresh=True)
    assert fresh["status"] == "prepared", fresh
    assert not fresh["cache_reused"]
    assert fresh["python_executable"] != preparation["result"]["python_executable"]
    assert fresh["resolved_lock"] == preparation["result"]["resolved_lock"]
    raw = experiment(artifacts, inputs.build_request, receipt)
    raw.update(question="Does the independently prepared Target Workflow compute comma formatting?",
               rationale="Check actual dependency use and exact answers in a fresh native Run.")
    launch = resolve_launch({
        "project": "live-target-environment", "project_root": str(tmp_path), "env_files": [],
        "routes": {"unused": {"provider": "custom", "model": "unused", "base_url": "http://localhost:9999/v1",
                               "api_mode": "chat_completions", "auth": {"kind": "none"}}},
        "model_slots": {"selector": "unused", "executor": "unused"},
        "builder_slots": {"planning": "selector", "emission": "executor"},
    })
    raw["launch_ref"] = put_data(artifacts, session.duet_id, "launch", launch.record)
    FixtureLaunchHost(artifacts, builds, session.duet_id).approve_fixture(launch)
    assign_measure(raw, artifacts, builds, session.duet_id, "/workflow_result/formatted", EXPECTED, [])
    runner = ExperimentService(artifacts=artifacts, builds=builds, runs=executor.run_store, executor=executor)
    result = await runner.run(ExperimentSpec.from_record(raw))
    assert result["execution_status"] == "succeeded", result
    assert result["candidate_verdict"] == "pass", result
    actual = result["typed_status"]["workflow_result"]
    assert actual["formatted"] == EXPECTED
    version = next(row["version"] for row in fresh["prepared"]["distributions"] if row["name"] == "humanize")
    assert actual["dependency_version"] == version
    registration = executor.run_store.read_registration(OpaqueId(result["run_id"]))
    assert registration.target_environment.as_record() == fresh["prepared"]
    assert any(row.kind is RunEventKind.UNIT_COMPLETED for row in executor.run_store.read_committed_prefix(registration.run_id))
    return result, fresh


@pytest.mark.platforms("linux")
@pytest.mark.allow_real_home_io  # Explicit credential reads only; all generated state is disposable.
@pytest.mark.asyncio
@pytest.mark.parametrize("initial_recipe", ["missing", "broken"])
async def test_live_implementer_environment_and_independent_run(tmp_path, request, monkeypatch, initial_recipe):
    selected_binding = live_binding(request)
    if os.environ.get("HERMES_RUN_E2E") != "1":
        pytest.skip("requires HERMES_RUN_E2E=1 for native execution and public dependency installation")
    runtime_dir = Path("/run/user") / str(os.getuid())
    if (runtime_dir / "bus").exists():
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir / 'bus'}")
    status = subprocess.run(["systemctl", "--user", "is-system-running"], capture_output=True, timeout=5)
    assert status.returncode == 0, status.stderr
    tools = request.getfixturevalue("admitted_pm_tools")
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(tools[0]))
    factory = make_systemd_run_executor_factory(repository_root=Path(__file__).resolve().parents[2])

    def executor_type(root, _identity):
        return factory(RunStore(root / "runs"))

    checks = [{"requirement_field": field, "expected": EXPECTED,
               "observation_path": "/payload/typed_status/workflow_result/formatted",
               "grounding": {"numbers": NUMBERS, "expected": EXPECTED}}
              for field in ("goal", "progress")]
    async with prepared_refiner(tmp_path, None, executor_type=executor_type, target_builder=build_scaffold,
                                runtime_checks=checks, allow_source_edits=True) as session:
        await session.evaluations.prepare_context(session)
        python = session.evaluations.executor.python_executable
        absence = subprocess.run([str(python), "-I", "-c",
                                  "import importlib.util;assert importlib.util.find_spec('humanize') is None"],
                                 capture_output=True, timeout=5)
        assert absence.returncode == 0, absence.stderr
        campaign = CampaignFixture(session)
        assignment = campaign.implementer(additional_paths=[ENVIRONMENT_RECIPE_PATH])
        if initial_recipe == "broken":
            seed_broken_recipe(campaign, session.evaluations.environment_context()["runtime"]["python"])
        print(json.dumps({"stage": "live_coding_started", "initial_recipe": initial_recipe, "artifacts": str(tmp_path),
                          "model": selected_binding.record["route"]["model"]}), flush=True)
        call, coding_receipt = await coding_exchange(campaign, assignment, selected_binding)
        candidate = campaign.candidate
        projection = project_candidate_sources(session.store.evidence, session.contract, candidate)
        assert projection.environment_recipe is not None, [row.as_record() for row in projection.deficits]
        preparation = await prepare_candidate(session.evaluations, session, call, candidate, projection)
        assert preparation["result"]["status"] == "prepared", preparation
        if initial_recipe == "broken":
            failures = [row["record"] for row in campaign.duets.artifacts_by_kind(
                duet_id=session.duet_id, kind="refinement.environment_preparation.v1")
                if row["record"]["result"]["status"] == "failed"]
            assert failures and failures[0]["result"]["log_refs"]
            assert any("0.0.0" in campaign.builds.read_blob(log["content_hash"]).decode()
                       for log in failures[0]["result"]["log_refs"])
            context = json.loads((Path(coding_receipt["workspace"]) / ".openchia-assignment.json").read_text(encoding="utf-8"))
            diagnostics = context["host_context"]["inputs"]["target_environment"]["coding_diagnostics"]
            assert any(row["status"] == "failed" and row["diagnostics"] and row["log_refs"] for row in diagnostics)
        receipt = await asyncio.to_thread(admit_candidate, session.store, session.contract, candidate, session.evaluations.builder)
        assert receipt.materialized, [row.as_record() for row in receipt.deficits]
        result, fresh = await independently_run(session, receipt, preparation, tmp_path, factory)
        assert "humanize" not in sys.modules
        accepted = {
            "scope": "Real Implementer/environment/independent Run boundary, not autonomous Parts/Designer acceptance",
            "fixture_inputs": "Approved incomplete scaffold, assignment, exact-answer criterion, disposable PM tool facts",
            "initial_recipe": initial_recipe, "candidate_ref": candidate.ref.as_record(),
            "build_receipt_id": receipt.receipt_id.value, "coding": coding_receipt,
            "preparation_ref": preparation["record_ref"], "fresh_preparation_ref": fresh["preparation_ref"],
            "result": result,
        }
        acceptance_ref = put_data(campaign.duets, session.duet_id, "target_environment_acceptance", accepted)
        print(json.dumps({"stage": "acceptance_completed", "initial_recipe": initial_recipe,
                          "acceptance_ref": acceptance_ref, "run_id": result["run_id"],
                          "workflow_result": result["typed_status"]["workflow_result"]}), flush=True)
