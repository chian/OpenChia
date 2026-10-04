"""Machine-readable experiments on exact Target Workflow candidate revisions.

Refinement scope separately selects the refiner workflow and its campaign.
"""

from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints


SCOPES = {
    "component": "One exact registered function used by the admitted candidate.",
    "unit": "One declared unit at an identified Episode invocation boundary.",
    "episode": "One Episode invocation; child execution is explicitly declared.",
    "nested": "An explicitly selected connected group of Episode templates.",
    "workflow": "The complete admitted Target Workflow, including callable children.",
    "refinement": "The complete admitted refinement workflow and its campaign.",
}

MODES = {
    "numerical": {
        "recomputed": ["registered numerical control over saved observations"],
        "reused": ["unit observations", "external responses"],
        "cannot_establish": [
            "candidate behavior under new execution",
            "current external-service behavior",
        ],
        "needs": ["recording_ref"],
    },
    "recorded": {
        "recomputed": ["candidate execution", "measurement", "numerical control"],
        "reused": ["exact matching external responses"],
        "cannot_establish": ["current external-service behavior"],
        "needs": ["recording_ref"],
    },
    "live_saved": {
        "recomputed": ["candidate execution", "external calls", "measurement"],
        "reused": ["exact saved inputs for a new experiment"],
        "cannot_establish": [
            "independence from the selected saved starting state",
            "continuation of interrupted work; use the separate continue operation",
        ],
        "needs": ["start.artifact_ref", "launch_ref"],
    },
    "live_fresh": {
        "recomputed": ["candidate execution", "external calls", "measurement"],
        "reused": ["approved build and explicitly supplied launch inputs"],
        "cannot_establish": ["correctness for inputs or environments not exercised"],
        "needs": ["launch_ref"],
    },
}

# Discoverability and dispatch share this table. Checkpoint restoration and
# numerical replay are distinct routes, not aliases for a fresh Run.
RUN_MODE_STARTS = {
    "live_fresh": ("fresh",),
    "recorded": ("fresh", "saved_inputs"),
    "live_saved": ("saved_inputs",),
}

Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class _ClosedInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class ArtifactReference(_ClosedInput):
    artifact_id: Text
    content_hash: Digest


class InterruptedRunReference(_ClosedInput):
    run_id: Text
    registration_hash: Digest
    terminal_event_id: Text
    terminal_event_hash: Digest


class InvocationPart(_ClosedInput):
    grain: Text
    key: Text


class ScopeInput(_ClosedInput):
    kind: Literal["component", "unit", "episode", "nested", "workflow", "refinement"]
    entry_local_id: Text
    included_local_ids: Annotated[list[Text], Field(min_length=1)]
    component_definition_id: Text | None
    unit_label: Text | None
    invocation_path: list[InvocationPart]


class BoundaryInput(_ClosedInput):
    parent_context_ref: ArtifactReference | None
    children: Literal["execute", "reuse", "none"]


class StartInput(_ClosedInput):
    kind: Literal["fresh", "saved_inputs", "checkpoint"]
    artifact_ref: ArtifactReference | None
    input_payload: dict[str, JsonValue]


class RequirementInput(_ClosedInput):
    requirement_ref: ArtifactReference
    measure_ref: ArtifactReference
    expected: Text
    falsifying: Text


class ExperimentInput(_ClosedInput):
    schema_version: Literal[1]
    question: Text
    rationale: Text
    candidate_ref: ArtifactReference
    build_receipt_ref: ArtifactReference
    environment_ref: ArtifactReference
    scope: ScopeInput
    boundary: BoundaryInput
    start: StartInput
    mode: Literal["numerical", "recorded", "live_saved", "live_fresh"]
    recording_ref: ArtifactReference | None
    launch_ref: ArtifactReference | None = Field(description="Exact Target Workflow launch configuration, or the owning Duet's host-bound model snapshot for refinement-job execution; never interchangeable.")
    campaign_ref: ArtifactReference | None
    requirements: Annotated[list[RequirementInput], Field(min_length=1)]
    unresolved_questions: list[Text]


def experiment_schema():
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "openchia:experiment:1",
        **ExperimentInput.model_json_schema(),
    }


def vocabulary():
    from ..records.inventory import InventoryRequest
    from ..records.catalog import HistoryQuery
    from ..records.runs import RunRecord
    from episode_library.testing import DESIGN as testing_design
    from .criteria import criterion_schema
    from .observations import observation_catalog
    from ..records.outcomes import RequirementOutcome
    from function_library.refinement_checks import refinement_check_library
    from function_library.testing_contract import (
        OPERATION_FIELDS,
        testing_contract_schema,
    )

    return {
        "schema": experiment_schema(),
        "testing_episode": {
            "reference_id": testing_design.episode_id,
            "qualified_name": testing_design.qualified_name,
            "unit": testing_design.binding.unit,
            "required_approval": "A frozen testing-access contract and a testing epistemic admission policy; episode_testing must be assignable by the Duet authority.",
            "iteration": "Select experimental operations using prior results and admitted findings; no fixed experiment sequence or harness-owned stop rule.",
            "credit": "Only distinct exact host-measured findings admitted by the frozen policy; repeated passes, predictions and failure alone earn no credit.",
            "verification_limit": "The loop has scripted integration coverage, not yet live model-directed acceptance.",
        },
        "testing_access_schema": testing_contract_schema(),
        "worker_payload_schemas": {
            operation: InventoryRequest.model_json_schema() if operation == "inventory" else {"oneOf": [{
                "type": "object",
                "additionalProperties": False,
                "required": list(fields),
                "properties": {
                    key: {"$ref": "openchia:experiment:1"}
                    if key == "spec"
                    else InterruptedRunReference.model_json_schema() if key == "resume_from"
                    else HistoryQuery.model_json_schema() if key == "query"
                    else {"type": "string", "minLength": 1}
                    for key in fields
                },
            } for fields in choices]}
            for operation, choices in OPERATION_FIELDS.items()
        },
        "criterion_schema": criterion_schema(),
        "continuation_reference_schema": InterruptedRunReference.model_json_schema(),
        "requirement_outcome_schema": RequirementOutcome.model_json_schema(),
        "run_record_schema": RunRecord.record_schema(),
        "history_query_schema": HistoryQuery.model_json_schema(),
        "inventory": {
            "request_schema": InventoryRequest.model_json_schema(),
            "purpose": "Inspect exact invocation paths, UnitRefs, completion facts and context availability from the same maintained Run index, without loading audit bodies.",
            "worker_source": "An owned experiment or an exact assigned/saved recording; direct Run lookup is local-host CLI only.",
            "pagination": "Pass next_query unchanged. It pins the audit prefix, excluding later completions, units and siblings outside a saved selector.",
            "continued_execution": "An experiment with several physical attempts requires query.through_event_ref. An unselected response provides attempts[].inventory_requests for each exact prefix; send the chosen payload unchanged. Coverage is physical_attempt_only, not a reconstructed logical invocation history.",
            "limitations": "Discovery is not acceptance or replay compatibility. Missing entry facts remain missing; recorded observations are not a coherent checkpoint.",
        },
        "history": {
            "operation": {"operation": "history", "payload": {"query": {"limit": 20}}},
            "purpose": "Discover prior experiments, measured outcomes, saved recording references and reuse constraints without scanning audit logs. Local-host kind=executions includes ordinary and refinement Runs, with exact intent provenance.",
            "execution_history": "Local-host queries may select kind=executions, and run_id to page its recordings. Workers inspect execution views inside their owned experiments; this does not expose other Runs in the Duet.",
            "refinement_history": "kind=refinement requires campaign_id and invocation_id; refinement_collection selects observations, controls, reports or conflicts. Local-host CLI and the refiner's existing context request use the same query. Refiner workers may supply test_history_query to context, but cannot replace their host-bound campaign or invocation. Generic testing workers cannot select another refinement assignment.",
            "pagination": "Send next_cursor as query.after. Set query.experiment_id to page an owned experiment's recordings; nested recording lists provide query and next_query. Access is limited to the invoking Episode's experiments and explicitly assigned recordings.",
            "limitations": "Reuse choices require full experiment preview; missing or stale Run indexes are visible, not rebuilt during a query. A continuation reference identifies an interruption; it does not establish source support or authorize execution.",
        },
        "continuation_route": {
            "operation": "continue",
            "payload": {"experiment_id": "the owned experiment", "resume_from": "exact InterruptedRunRef from its interrupted target or declared checker status"},
            "purpose": "Continue the same logical execution through the existing Run executor; this is not a changed experiment or a saved-input restart.",
            "invariants": "Keep the original code, inputs, scope, runtime, authority and expectations. Reconstruct all historical worker frames and host replies without repeating their effects; new work requires the host's current-authority admission.",
            "source_support": "Exact stock ReasoningSource, TestingSource and RefinementSource wrappers with their reference controller/goal behavior; generated overrides and custom execution behavior are rejected by source preflight.",
            "terminal_states": ["interrupted", "cancelled", "resource_limited"],
            "access": "A testing Episode may continue only an experiment owned by its invocation and still permitted by its frozen testing contract. The source Run must be that experiment's target or exact declared checker.",
            "refinement": "Requires the owning Duet-bound service and its shared evaluation service. A plain CLI invocation cannot substitute a Target Workflow launch for the refiner's Duet configuration.",
            "limitations": "An incomplete exchange, changed campaign head, stale authority or unsupported source prevents continuation. Recorded/numerical experiments cannot switch to live execution. This interface does not itself establish native confinement or live reasoning acceptance.",
        },
        "observation_predicates": [
            {
                key: value
                for key, value in function.bind("measurement").as_record().items()
                if key != "name"
            }
            for function in refinement_check_library.functions()
        ],
        "available_observations": observation_catalog(),
        "scopes": deepcopy(SCOPES),
        "modes": deepcopy(MODES),
        "run_routes": {
            "scope_kinds": ["workflow", "episode", "nested", "component", "unit", "refinement"],
            "mode_start_pairs": {
                mode: list(starts) for mode, starts in RUN_MODE_STARTS.items()
            },
            "saved_inputs_source": "start.artifact_ref names a saved recording selector; whole-workflow execution reuses its exact root inputs, while selected execution also requires its verified invocation entry context",
            "checkpoint_restoration": "Starting a new experiment from an arbitrary checkpoint is unsupported. Continue the same interrupted experiment using continuation_route; do not pass a terminal reference as a new start artifact.",
            "selected_invocations": "episode/nested require live_saved or recorded mode, a boundary from the exact source recording, reproducible initial GoalState, and a connected selected group closed over executable children; ancestors do not execute",
            "refinement": {
                "selection": "Exact approved refiner build, all declared roles, and its prepared campaign; candidate_ref names the refiner build, not the target being repaired.",
                "model_binding": "The owning OpenChiaHost.refinement_experiment_service supplies its bound Duet route and shared target evaluations. launch_ref is service.duet_binding.reference, not a Target Workflow launch file. Missing owner binding is an explicit preview gap.",
                "fresh_execution": "live_fresh starts one unused prepared campaign. Its immutable claim prevents another experiment from restarting that same mutable campaign.",
                "numerical": "Saved host continuation decisions can be recalculated without running the refiner or changing the campaign.",
                "limitations": "Saved-input/recorded experiments do not restore an ongoing campaign. Use continue with the exact interrupted owning experiment and its Duet-bound service. This explicit testing path does not activate normal-build refinement.",
            },
            "units": {
                "selection": "Use inventory kind=units, then boundary with the exact unit_id. A label alone is not an identity.",
                "reconstruction_prefix": "Inventory and boundary capture identify the invocation start or preceding unit event, separately from the selected unit's completed observation. Located is not restored: complete history, host state and parent dependencies still require admission; restoration_verified remains false.",
                "starting_state": "Unit zero requires reproducible initial GoalState. A later live_saved unit can restore Episode-local stock reasoning state from the exact original terminal whole Run, with the same build/runtime and a child-free selected entry. Preview validates and exposes learning_baseline; inherited knowledge and credit are reused, not earned again. Custom sources, changed-code transfer and continued/scoped source attempts are unsupported; preceding units are never rerun.",
                "execution": "The ordinary Episode acquires one selected unit, including its declared children, and reports the unchanged controller decision. No containing-Episode result or completion is published.",
                "recording": "The returned recording_ref ends at the selected unit event. Recorded mode must use that exact prefix; request mismatches reject reuse without a live fallback.",
                "limitations": "Unit observation is not containing-Episode completion, parent acceptance, or interruption recovery.",
            },
            "components": {
                "selection": "Select an exact component_definition_id and owning entry_local_id; preview lists matching bindings and call signatures. No Episode or ancestors execute.",
                "boundary": {"parent_context_ref": None, "children": "none"},
                "fresh_input_payload": {
                    "binding_role": "exact role from preview",
                    "adapter": "json_keywords or numeric_band",
                    "inputs": {"keyword": "JSON value"},
                },
                "adapters": {
                    "json_keywords": "Keyword inputs for an unconfigured registered binding. Function-returned JSON or as_record data only; object handles and code are not inputs.",
                    "numeric_band": "For continuation.numeric_credit_band: inputs.projected_credit has value, lower, upper, uncertainty_alpha and status. parameters comes only from the candidate's frozen binding.",
                },
                "saved_inputs": "Use the exact component Run recording in start.artifact_ref; never a workflow's root launch inputs.",
                "observation": "component_result.status is returned or raised, with value or typed error. A successful observation is not Episode completion or candidate acceptance.",
                "limitations": "Other configured or non-JSON interfaces need typed adapters; no arbitrary object construction, host learning mutation or child creation.",
            },
        },
        "numerical_route": {
            "scope_kinds": ["episode", "nested", "workflow", "refinement"],
            "start_kind": "saved_inputs",
            "boundary_children": "reuse",
            "input_source": "start.artifact_ref and recording_ref name the same committed recording; exact build and environment are required",
            "observation_decoders": ["host-admitted epistemic learning observations", "host-committed refinement credit snapshots with exact current and prior opportunity bounds"],
            "saved_learning": "For a later-unit experiment, numerical replay restores its inherited observation history before recomputing new observations. Preview and results expose reused_unit_count and inherited_history_ref; no old credit is awarded again.",
            "limitations": "No acquisition or Run execution; other controller input types, component/unit projections and changed-build counterfactuals are not yet supported.",
        },
        "measurement_route": {
            "configuration": "register-measure freezes a registered predicate, expected value, controls, exact context and implementation identity; use its requirement_ref and measure_ref in subsequent experiments",
            "projection": "Operator criterion observation_path remains relative to terminal Run evidence.typed_status. Campaign checks select an exact root from available_observations: /payload/typed_status or /verified_run. Verified records retain event origins; model/worker prose is data, not a host-certified claim.",
            "eligibility": "exact approved workflow, scope, semantic root inputs and environment; mode must be one of the criterion's accepted_modes",
            "output": "typed per-requirement outcomes; candidate_verdict is separate from parent acceptance and progress",
            "verified_observation_read": {
                "api": "ExperimentService.read_observation(artifacts, runs, duet_id=owner, measurement_ref=report['measurement_ref'], receipt=outcome['observed'])",
                "purpose": "Return the exact selected verified Run value after checking report ownership, observation membership, registration, evidence, terminal anchor and value_hash. No manual audit reconstruction or prose summary is needed.",
                "access": "Host API only, not a new worker operation or CLI command. Describe exposes this same observation catalog to CLI and testing Episodes; existing run-record is the CLI inspection view.",
                "limitations": "Only a receipt retained by that exact measurement report is readable through this method; it does not permit arbitrary paths or browsing another Duet.",
            },
            "limitations": "Operator-supplied controls do not prove their grounding. Campaign checks and grounded checker controls use their original admission contracts; numerical reproduction is not behavioral acceptance.",
        },
        "comparison_route": {
            "inputs": "two experiment IDs in the same Duet, each with committed requirement measurements",
            "output": "per-requirement before/after outcomes, source measurement references, context differences, comparable regressions and resolved failures",
            "limitations": "Different contexts or criteria cannot establish regression or repair. Comparison is read-only, not causal attribution or credit.",
        },
        "judgments": {
            "candidate": "Whether the bound requirement and measure were met.",
            "experiment": "What the executed scope and mode actually established.",
            "progress": "Host-admitted new evidence, not a model score or pass count.",
        },
        "authority": "An experiment is a request, not a grant of Run capabilities.",
        "completion": "Episode continuation remains owned by its numerical controller.",
    }
