"""Real approval, Builder, package linker, host ledger and generic Episode loop.

External model replies are supplied. One case uses in-process execution with
fixture attestation; the native case exercises the real systemd worker and
confinement. Neither case is a live-model reasoning benchmark.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agent.duet_contracts import DuetIdentity, DuetPolicy
from agent.duet_service import DuetService
from agent.duet_store import DuetStore
from agent.episode_blueprints import workflow_blueprint_from_spec
from agent.episode_contracts import (
    EpisodeCreationSpec,
    EpisodeDesignSpec,
    EpisodeWorkflowSpec,
    OpaqueId,
    Sha256Digest,
)
from episode_builder._contract_chain import ApprovedBuildRequest
from episode_builder.service import EpisodeBuilder
from episode_builder.store import BuildStore
from episode_library.inquiry import DESIGN, inquiry_contract
from episode_library.models import EpisodeReference
from episode_runtime.contracts import (
    RunEventKind,
    RunEventOrigin,
    RunRegistration,
    RunTerminalStatus,
)
from episode_runtime.learning_broker import LearningBroker
from episode_runtime.identity import materialize_runtime_source_package
from episode_runtime.executor import make_systemd_run_executor_factory
from episode_runtime.broker import ScopedModelBroker
from episode_runtime.store import RunStore
from episode_runtime.linker import current_runtime_episode_id, prepare_source_package
from function_library.epistemic_schemas import model_call_id
from function_library.reasoning import OPEN_SOURCE, BUILD_RESULT, CONTROLLER, SCHEMA
from function_library.reasoning_transport import reasoning_transport_scope
from handoff_library import (
    ADMIT_DUET_LAUNCH_REQUEST,
    DuetLaunchRequest,
    HandoffPayloadContract,
)
from llm_call_library.transport import ModelTransportResponse, model_transport_scope
from llm_call_library import CallOptions
from numeric_control_library import MARGINAL_DOMINATED_HYPERVOLUME

from .conftest import claim_store, numerical_control, oid


def _binding(role, function, arguments=None):
    value = function.bind(role.replace(".", "_"), arguments=arguments or {}).as_record()
    value.pop("name")
    return {
        "role": role,
        "source": "library",
        **value,
        "basis": "approved generic reasoning reference",
    }


def _plan_response(prompt, *, testing=False):
    from function_library.testing import OPEN_SOURCE as TESTING_SOURCE

    payload = HandoffPayloadContract().as_record()
    bindings = [
        _binding(
            "admit_request", ADMIT_DUET_LAUNCH_REQUEST, {"payload_contract": payload}
        ),
        _binding("open_source", TESTING_SOURCE if testing else OPEN_SOURCE, {
            "selection_model_type": "selector", "execution_model_type": "executor",
        }),
        _binding("controller.schema", SCHEMA),
        _binding("controller.composer", CONTROLLER),
        _binding("controller.credit", MARGINAL_DOMINATED_HYPERVOLUME),
        _binding("build_result", BUILD_RESULT, {"payload_contract": payload}),
        *prompt["architecture_owned_numeric_bindings"],
    ]
    return {
        "interface": "test.reasoning",
        "result_channel_names": ["knowledge"],
        "request_payload_contract": payload,
        "result_payload_contract": payload,
        "selected_function_bindings": bindings,
        "generated_component_specs": [],
        "prompt_specs": [],
        "goal_state_spec": {"owner": "host learning ledger"},
        "child_slots": [],
        "derivation_basis": {"goal": "exact approved contract"},
        "unresolved": [],
    }


def _module_response(
    prompt,
    *,
    source_expression=None,
    extra_source="",
    controller_expression="host_controller_factory(goal_view, collaborators)",
    episode_expression=None,
):
    plan, contract = prompt["admitted_node_plan"], prompt["frozen_episode_contract"]
    bindings = {item["role"]: item for item in plan["selected_function_bindings"]}
    source_class = (
        "TestingSource"
        if bindings["open_source"]["library"] == "testing"
        else "ReasoningSource"
    )
    source_expression = source_expression or f'{source_class}(goal_view["goal"], **dict(BINDING.open_source.arguments))'
    episode_expression = (
        episode_expression
        or f"Episode(grain=grain, key=key, request=request, source={source_expression}, build_result=build_reasoning_result)"
    )

    def selected(role):
        value = {
            key: bindings[role][key]
            for key in (
                "library",
                "function_id",
                "interface",
                "definition_id",
                "arguments",
            )
        }
        value["name"] = role.removeprefix("component.").replace(".", "_")
        return f"EpisodeFunctionBinding(**{value!r})"

    components = ",".join(
        selected(role) for role in bindings if role.startswith("component.")
    )
    slots = ",".join(
        f"EpisodeChildSlot(name={edge['slot_name']!r}, accepted_interfaces=({edge['child_interface']!r},), "
        f"build_child={selected('edge.' + edge['slot_name'] + '.build_child')}, "
        f"prepare_request={selected('edge.' + edge['slot_name'] + '.prepare_request')}, "
        f"receive_result={selected('edge.' + edge['slot_name'] + '.receive_result')})"
        for edge in prompt.get("direct_edges", [])
    )
    call_definitions = ", BUILD_REPEATABLE_CHILD" if slots else ""
    root_builders = (
        ""
        if plan["parent_local_id"] is not None
        else """
def build_goal_state(request, collaborators):
    return ReasoningGoalState()
def scope_goal_state(goal_state, goal):
    return MappingProxyType({"goal": goal.objective})
"""
    )
    source = f"""
from types import MappingProxyType
from episode_library.models import EpisodeLibraryDesign
from method_loop import Episode, EpisodeBindingDeclaration, EpisodeChildSlot, EpisodeControllerBinding, EpisodeFunctionBinding, EpisodeTopologyRole
from handoff_library import HandoffPayloadContract, ADMIT_DUET_LAUNCH_REQUEST, ADMIT_PARENT_REQUEST, ADMIT_CHILD_RESULT
from function_library.episode_calls import BUILD_REPEATABLE_CHILD
from function_library.reasoning import OPEN_SOURCE, BUILD_RESULT, CONTROLLER, SCHEMA, ReasoningSource, ReasoningGoalState, build_reasoning_result, build_controller_factory as host_controller_factory
from function_library.epistemic import epistemic_function_library
from function_library.testing import testing_function_library
from function_library.testing_source import TestingSource
from numeric_control_library import COMPOSE_INCIDENCE_CONTROLLER, MARGINAL_DOMINATED_HYPERVOLUME, PAIRED_INCIDENCE, PREDICTED_CREDIT_UPPER_BOUND
REQUEST_PAYLOAD_CONTRACT = HandoffPayloadContract.from_record({plan["request_payload_contract"]!r})
RESULT_PAYLOAD_CONTRACT = HandoffPayloadContract.from_record({plan["result_payload_contract"]!r})
PROMPTS = ()
EXECUTION_CAPABILITY_NAMES = {tuple(contract["execution_capability_names"])!r}
RESULT_CHANNEL_NAMES = {tuple(plan["result_channel_names"])!r}
RESULT_CHANNEL_IDS = {tuple(plan["result_channel_ids"])!r}
BINDING = EpisodeBindingDeclaration(
    grain_name={plan["grain_name"]!r}, interface={plan["interface"]!r}, topology_role=EpisodeTopologyRole.{plan["topology_role"].upper()},
    goal={contract["goal"]!r}, unit={contract["unit"]!r}, result={contract["result"]!r},
    progress={contract["progress"]!r}, stopping={contract["stopping"]!r},
    admit_request={selected("admit_request")}, open_source={selected("open_source")},
    controller=EpisodeControllerBinding(schema={selected("controller.schema")}, composer={selected("controller.composer")},
        credit={selected("controller.credit")}, rarefaction={selected("controller.rarefaction")}, continuation={selected("controller.continuation")}),
    build_result={selected("build_result")}, components=({components}{"," if components else ""}), child_slots=({slots}{"," if slots else ""}))
DESIGN = EpisodeLibraryDesign(qualified_name={plan["interface"]!r}, title='Task inquiry', binding=BINDING,
    function_definitions=tuple(function for function in (ADMIT_DUET_LAUNCH_REQUEST, ADMIT_PARENT_REQUEST, ADMIT_CHILD_RESULT, OPEN_SOURCE, BUILD_RESULT, CONTROLLER, SCHEMA,
        COMPOSE_INCIDENCE_CONTROLLER, MARGINAL_DOMINATED_HYPERVOLUME, PAIRED_INCIDENCE, PREDICTED_CREDIT_UPPER_BOUND{call_definitions}, *epistemic_function_library.functions(), *testing_function_library.functions())
        if function.definition_id in {{selection.definition_id for selection in BINDING.function_bindings()}}), source_symbols=())
def build_controller_factory(goal_view, collaborators):
    return {controller_expression}
{root_builders}
def build_episode(grain, key, request, goal_view, collaborators, child_builders):
    return {episode_expression}
{extra_source}
"""
    return {
        "module_source": source,
        "derivation_notes": {
            "contract": "Exact approved policy and registered host adapters"
        },
    }


def _approved_request(
    tmp_path,
    *,
    spec=None,
    reference=DESIGN,
    repeatable_calls=(),
    allowed_capabilities=(),
    allowed_egress_hosts=(),
    egress_credential_names=(),
    duet_id=None,
    workflow=None,
):
    evidence = (
        {
            "kind": "support",
            "text": "Search X yielded no records under dataset v1.",
            "observation": {
                "action_class": "discover",
                "action_inputs": {},
                "goal_class": "open_problem",
                "environment": {"dataset": "v1"},
                "assumptions": [],
                "expected_observation": "relevant records",
                "observed_outcome": "no records",
                "status": "failed",
            },
        },
        {
            "kind": "counterevidence",
            "text": "A missing record does not establish that no solution exists.",
            "observation": {},
        },
        {
            "kind": "prior_art",
            "text": "Prior formulations did not define a completeness test.",
            "observation": {},
        },
    )
    spec = spec or EpisodeCreationSpec(
        goal="Formulate how to test completeness of this search corpus.",
        progress="Admitted durable knowledge transitions",
        stopping="Registered projected-yield continuation",
        numeric_control=numerical_control(0.1),
        epistemic=inquiry_contract(
            goal_class="open_problem",
            domain="test",
            environment={"dataset": "v1"},
            evidence=evidence,
        ),
    )
    workflow = workflow or EpisodeWorkflowSpec(
        (
            EpisodeDesignSpec(
                "inquiry", None, spec, EpisodeReference(reference.episode_id)
            ),
        ),
        repeatable_calls=repeatable_calls,
    )
    with DuetStore(tmp_path / "duet.db") as store:
        service = DuetService(
            store, allowed_episode_capabilities=allowed_capabilities,
            allowed_egress_hosts=allowed_egress_hosts,
            egress_credential_names=egress_credential_names,
        )
        policy = DuetPolicy(oid("policy"))
        identity = DuetIdentity(
            duet_id or oid("duet"), oid("human"), policy.policy_id, oid("conversation")
        )
        service.open_duet(identity, policy)
        draft = service.record_initial_workflow_draft(
            duet_id=identity.duet_id,
            workflow_blueprint=workflow_blueprint_from_spec(workflow),
            expected_draft_artifact_id=None,
            expected_draft_hash=None,
            expected_draft_revision=None,
            source_stage="human_edit",
        )
        authorization = service.approve_current_workflow(
            identity,
            source_draft_artifact_id=OpaqueId(draft["artifact_id"]),
            source_draft_hash=Sha256Digest(draft["content_hash"]),
        )
    return ApprovedBuildRequest(
        authority_approval=authorization.authority_approval,
        workflow_approval=authorization.workflow_approval,
        frozen_workflow=authorization.frozen_workflow,
        admission_authority=authorization.admission_authority,
        request_nonce="integration",
    )


async def _exercise_workflow(tmp_path, run_store, *, isolated):
    request = _approved_request(tmp_path)
    builder_store = BuildStore(tmp_path)

    async def builder_model(request):
        prompt = json.loads(request.messages[-1]["content"])
        response = (
            _plan_response(prompt) if "node" in prompt else _module_response(prompt)
        )
        return ModelTransportResponse(text=json.dumps(response), route={})

    with model_transport_scope(builder_model):
        receipt = await EpisodeBuilder(store=builder_store,
            planning_options=CallOptions(model_type="planner"),
            emission_options=CallOptions(model_type="writer"),
            model_slot_catalog={"selector": {}, "executor": {}},
        ).build(request)
    assert receipt.status == "materialized", [d.as_record() for d in receipt.deficits]
    manifest = builder_store.read_manifest(receipt.manifest_id)
    runtime_identity = run_store[1].runtime_identity
    if isolated:
        store = RunStore(tmp_path / "execution" / "runs")
        runtime_identity, _ = materialize_runtime_source_package(
            repository_root=Path(__file__).resolve().parents[2],
            destination_root=store.runtime_sources_root,
        )
    registration = RunRegistration.from_admitted_build(
        build_request=request,
        build_attempt=builder_store.read_build_attempt(receipt.build_attempt_id),
        build_receipt=receipt,
        build_manifest=manifest,
        launch_request=DuetLaunchRequest(
            oid("launch").value,
            request.frozen_workflow.artifact_id.value,
            oid("goal").value,
            {},
        ),
        runtime_identity=runtime_identity,
        runtime_policy=run_store[1].runtime_policy,
    )
    if not isolated:
        store, registration, _ = claim_store(tmp_path / "execution", registration)
    package = builder_store.source_package_path(manifest.manifest_id)
    broker = LearningBroker(store, registration, package)
    prepared = prepare_source_package(registration, package)
    activated = None if isolated else prepared.activate()
    calls = []

    async def event_sink(kind, episode_id, payload):
        store.append_event(
            run_id=registration.run_id,
            origin=RunEventOrigin.WORKER,
            sender_sequence=len(calls),
            kind=kind,
            episode_id=episode_id,
            payload=payload,
        )
        calls.append(kind)

    async def learning(operation, payload):
        return await broker(current_runtime_episode_id().value, operation, payload)

    chosen = []
    model_events = []
    rejected_responses = []

    async def inquiry_model(request):
        prompt = json.loads(request.messages[-1]["content"])
        bundle = prompt["typed_unit_input"]
        ordinal = bundle["next_ordinal"]
        action = "discover" if ordinal < 2 else "clarify"
        if "selected_action" not in prompt:
            chosen.append((action, bool(bundle["applicable_lessons"])))
            response = {"action_class": action, "action_inputs": {}, "retry_reason": ""}
        else:
            response = {
                "action_class": action,
                "action_inputs": {},
                "status": "failed" if ordinal < 2 else "succeeded",
                "expected_observation": "relevant records",
                "observed_outcome": "no records",
                "candidate_lessons": [],
                "entities": [],
                "revisions": [],
            }
            sources = bundle["evidence"]
            if ordinal == 1:
                response["candidate_lessons"] = [
                    {
                        "claim": "This route yielded no records",
                        "action_class": action,
                        "scope_tier": "episode",
                        "reopening_conditions": ["dataset changes"],
                        "evidence_refs": [sources[0]["artifact_id"]],
                    }
                ]
            if ordinal >= 2:
                response["entities"] = [
                    {
                        "key": "corpus-completeness",
                        "fields": {
                            field: f"Precisely defined {field} for corpus completeness"
                            for field in bundle["contract"]["required_fields"]
                        },
                        "evidence": [
                            {
                                "kind": s["body"]["kind"],
                                "ref": s["artifact_id"],
                                "quote": s["body"]["text"],
                            }
                            for s in sources
                        ],
                        "answer_contract": {
                            "answer_forms": ["reproducible completeness test"],
                            "acceptance_tests": ["detect held-out missing record"],
                            "falsification_tests": [
                                "a missing held-out record is not detected"
                            ],
                        },
                        "uncertainties": ["reference corpus representativeness"],
                    }
                ]
        if ordinal == 1 and "selected_action" in prompt and not rejected_responses:
            # Scripted wiring regression, not a live reasoning benchmark: make
            # two representations invalid before returning the same valid lesson.
            response["observed_outcome"] = {"result": "no records"}
            rejected_responses.append(response)
        text = json.dumps(response)
        if "repair_request" in prompt and len(rejected_responses) == 1:
            text = "{{{{"  # Exercise invalid JSON provenance through the broker too.
            rejected_responses.append(text)
        if not isolated:
            store.append_event(
                run_id=registration.run_id,
                origin=RunEventOrigin.HOST,
                sender_sequence=len(model_events),
                kind=RunEventKind.MODEL_RESPONDED,
                episode_id=current_runtime_episode_id(),
                payload={
                    "producer_call_id": model_call_id(text, request.task, {}),
                    "response_text": text,
                },
            )
            model_events.append(text)
        return ModelTransportResponse(text=text, route={})

    try:
        if isolated:
            from episode_runtime.http_broker import ScopedHttpBroker

            async def no_http(*args, **kwargs):
                raise AssertionError("This reasoning fixture has no HTTP capability")

            executor = make_systemd_run_executor_factory(
                repository_root=Path(__file__).resolve().parents[2]
            )(store)
            # The canonical runner owns the operational timeout for this test.
            evidence = await executor.execute(
                registration=registration,
                source_package_path=package,
                model_broker=ScopedModelBroker.from_plan(inquiry_model, prepared.plan),
                http_broker=ScopedHttpBroker(
                    policy=registration.egress_policy,
                    credentials={},
                    transport=no_http,
                    max_frame_bytes=registration.runtime_policy.max_frame_bytes,
                ),
            )
            outcome = evidence.typed_status
        else:
            with (
                model_transport_scope(inquiry_model),
                reasoning_transport_scope(learning),
            ):
                outcome = await activated.link(event_sink=event_sink).run()
        broker.validate_completion(outcome)
        result = outcome["workflow_result"]
        assert (
            outcome["outcome"] == "succeeded"
            and result["terminal_state"] == "completed"
        )
        assert (
            result["result"]["admitted_problem_frontier"]
            and result["result"]["durable_lessons"]
        )
        assert all(
            action != "discover"
            for action, lesson_available in chosen
            if lesson_available
        )
        with store._claim_lock(registration.run_id):
            events = store._load_event_chain_locked(
                registration, store.read_claim(registration.run_id)
            )
        units = [
            e.payload["receipt"] for e in events if e.kind.value == "learning_committed"
        ]
        assert units[0]["measurement"]["realized_yield"] == 0
        assert units[1]["measurement"]["realized_yield"] > 0
        repairs = [
            e for e in events if e.kind is RunEventKind.LEARNING_REPAIR_REQUESTED
        ]
        assert len(repairs) == len(rejected_responses) == 2
        assert all(e.payload["ordinal"] == units[1]["ordinal"] for e in repairs)
        assert len(chosen) == len(units)  # Repairs never select another action.
        assert all(u["measurement"]["realized_yield"] == 0 for u in units[3:])
        terminal = (
            evidence
            if isolated
            else store.finalize_run(
                run_id=registration.run_id,
                origin=RunEventOrigin.HOST,
                sender_sequence=len(model_events),
                terminal_status=RunTerminalStatus.SUCCEEDED,
                typed_status=outcome,
            )
        )
        assert terminal.terminal_status is RunTerminalStatus.SUCCEEDED
    finally:
        for module in prepared.modules.values():
            sys.modules.pop(module.module_name, None)


@pytest.mark.platforms("linux")
@pytest.mark.asyncio
async def test_approved_inquiry_build_runs_with_host_learning_and_yield_return(
    tmp_path, run_store
):
    await _exercise_workflow(tmp_path, run_store, isolated=False)


@pytest.mark.platforms("linux")
@pytest.mark.asyncio
async def test_live_confined_reasoning_worker(tmp_path, run_store, monkeypatch):
    runtime_dir = Path("/run/user") / str(os.getuid())
    if (runtime_dir / "bus").exists():
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime_dir))
        monkeypatch.setenv(
            "DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir / 'bus'}"
        )
    status = subprocess.run(
        ["systemctl", "--user", "is-system-running"], capture_output=True, timeout=5
    )
    if status.returncode != 0:
        pytest.skip("live isolated Run requires a running user systemd manager")
    await _exercise_workflow(tmp_path, run_store, isolated=True)
