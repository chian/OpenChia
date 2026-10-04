"""Host-resolved measurement inputs from existing immutable Run evidence.

Verification establishes record identity and journal completeness, not the truth
of model or worker claims. A whole-Run observation covers one physical attempt;
it neither reconstructs ancestors nor silently combines several experiments.
"""

from dataclasses import fields

from agent.duet_contracts import canonical_json, digest_record
from agent.episode_contracts import OpaqueId
from function_library.epistemic_contract import exact
from function_library.epistemic_schemas import ATTEMPT_SHAPE
from function_library.models import _thaw_json
from iterative_episode_refiner.records import pointer_parts, project
from numeric_control_library.continuation import ContinuationDecision
from numeric_control_library.controller import ComposedControllerStep
from numeric_control_library.credit_assignment import NumericBand

from ..audit_contracts import RunEvidence
from ..contracts import RunEvent, RunEventKind, RunRegistration, RunTerminalStatus


TYPED_STATUS_ROOT = "/payload/typed_status"
VERIFIED_RUN_ROOT = "/verified_run"
_ROOT_FIELDS = ("schema_id", "schema_version", "coverage", "registration", "evidence", "events")


def _record_fields(kind):
    return [item.name for item in fields(kind) if item.name not in {
        "logical_run_id", "logical_registration_hash",
    }]


def _learning_records():
    """Describe the existing serializers, not invented conformance summaries."""
    return {
        "sources": [
            "episode_runtime.learning.LearningLedger.select",
            "episode_runtime.learning.LearningLedger.commit",
            "episode_runtime.learning_repair.audit_submission",
            "function_library.reasoning.HostReceipt.as_record",
        ],
        "event_payload_fields": {
            "learning_selected": [
                "ordinal", "action_class", "action_inputs", "retry_reason", "permitted", "reason",
            ],
            "learning_attempt": ["unit_id", "request_hash", "producer_call_id", "raw_result"],
            "learning_committed": [
                "request_hash", "unit_id", "state", "baseline_ids", "observation_ids", "receipt",
            ],
        },
        "receipt_fields": [
            "unit_id", "ordinal", "audit_ref", "components", "result_artifact", "measurement",
            "admission", "numeric_step", "terminal_state", "stop", "result", "receipt_id",
        ],
        "receipt_record_fields": {
            "numeric_step": _record_fields(ComposedControllerStep),
            "numeric_step/decision": [*_record_fields(ContinuationDecision), "decision_basis"],
            "numeric_step/decision/projected_credit": _record_fields(NumericBand),
            "measurement": [
                "realized_yield", "identity_ids", "transition_ids", "evidence_refs", "function",
                "credit_before", "credit_after",
            ],
            "admission": ["transitions", "rejections"],
        },
        "semantics": {
            "origin": "learning_selected, learning_attempt and learning_committed are host_learning records. Raw attempt content remains untrusted model data.",
            "selection_link": "Match episode_id and selection.payload.ordinal to receipt.ordinal. Compare selected action_class/action_inputs with result_artifact.body, the validated attempt.",
            "producer_link": "receipt.audit_ref identifies the learning_attempt event_id. Its producer_call_id links to the host-origin model_responded payload.producer_call_id; model_request_id and request_hash link that response to model_requested. Event sequence gives order.",
            "submission_link": "The learning_attempt and learning_committed request_hash identify the submission, not the model request. Do not equate these two different request hashes.",
            "continuation": "receipt.numeric_step.decision is the actual host continuation decision. stop=true means stop, not continue. It carries outcome, projected_credit, threshold and decision_basis. receipt.stop is true exactly when terminal_state is completed; blocked is not completed.",
            "credit": "receipt.measurement records realized state-transition yield. receipt.admission lists the committed transitions and rejections. Numeric controller credit is separately recorded under numeric_step.credit; these are not interchangeable scores.",
            "terminal_result": "For reasoning.build_reasoning_result, evidence.typed_status.workflow_result is the complete final HostReceipt, not its inner result. The host checks equality with the final committed receipt on successful workflow return.",
            "scope": "Inspect execution_scope and resume_from before making whole-workflow claims. This catalog does not reconstruct missing ancestor events or execute unobserved branches.",
        },
        "validated_attempt_shape": _thaw_json(ATTEMPT_SHAPE),
        "result_projection": {
            "applies_to": "epistemic.result_projection_v1 only; other registered projections can have different shapes.",
            "source": "function_library.epistemic_schemas.project_result",
            "relative_to": "receipt/result, or evidence/typed_status/workflow_result/result for reasoning.build_reasoning_result",
            "fields": [
                "admitted_problem_frontier", "answer_contracts", "durable_lessons",
                "retired_candidates", "unresolved_decisive_uncertainties",
            ],
            "entity": "admitted_problem_frontier contains admitted ledger records. Each record's body contains fields, answer_contract and uncertainties. Answer fields are at admitted_problem_frontier/<index>/body/fields, not directly on the ledger record.",
            "continuation": "Continuation is in the enclosing receipt.numeric_step.decision, not a field of this projection.",
        },
        "limitations": [
            "This describes fields already committed by these implementations. It supplies no fabricated Run, verdict, test expectation or additional capability.",
            "A failed attempt can legitimately earn yield through an admitted durable lesson. Failure status alone does not determine its credit.",
            "Control inputs test a predicate's discrimination; they do not establish that a live failure, duplicate or interruption branch executed.",
        ],
    }


def observation_catalog():
    """Describe implemented inputs; no proposed observation creates new fields."""
    return {
        "schema_id": "openchia.measurement.observation-catalog",
        "schema_version": 1,
        "roots": [
            {
                "path": TYPED_STATUS_ROOT,
                "source": "typed_status",
                "description": "The actual typed terminal result of a successful Run; its workflow_result shape comes from the admitted result contract.",
                "requires_successful_run": True,
            },
            {
                "path": VERIFIED_RUN_ROOT,
                "source": "verified_run",
                "description": "Exact registration, terminal RunEvidence and complete ordered RunEvent records, read and verified by the existing RunStore.",
                "fields": list(_ROOT_FIELDS),
                "coverage": "physical_attempt_only",
                "requires_successful_run": False,
                "record_fields": {
                    "registration": _record_fields(RunRegistration),
                    "evidence": _record_fields(RunEvidence),
                    "events[]": _record_fields(RunEvent),
                },
                "optional_registration_fields": ["execution_scope", "resume_from"],
                "event_kinds": [kind.value for kind in RunEventKind],
                "event_origins": {
                    "host": "Host broker or execution lifecycle record; embedded model/tool content remains untrusted data.",
                    "worker": "Worker-origin typed event; commitment authenticates provenance, not the worker's assertions.",
                    "host_learning": "Host learning admission, state transition and numerical-control record.",
                    "host_reconstruction": "Host reconstruction record, not repeated execution or new progress.",
                },
                "terminal_statuses": [status.value for status in RunTerminalStatus],
                "payload_examples": {
                    "model_requested": ["model_request_id", "request_hash", "task", "request", "episode_path"],
                    "model_responded": ["model_request_id", "request_hash", "response_hash", "producer_call_id", "response_text", "route"],
                    "learning_opened": ["contract", "numerical_control"],
                    "learning_committed": ["request_hash", "unit_id", "state", "baseline_ids", "observation_ids", "receipt"],
                },
                "model_records": {
                    "source": "episode_runtime.broker.model_request_record and model_response_record",
                    "request": "model_requested.payload.request contains task, model_type, messages, temperature, max_tokens, timeout, reasoning_config and main_runtime. Messages and response_text are raw strings, not parsed semantic observations.",
                    "response": "model_responded is host-origin. Its route is an object of string-valued fields, not a string; the fields depend on the configured transport. Route values record resolution, not model correctness.",
                    "link": "Pair requests and responses using model_request_id and request_hash within the same Episode. producer_call_id links a response to learning_attempt, not to every action in that Episode.",
                },
                "learning_records": _learning_records(),
                "limitations": [
                    "Payload fields depend on event kind and the frozen implementation. Examples are not universal required fields.",
                    "Registration binds workflow, build and authority identities; it does not inline the complete frozen workflow contract.",
                    "Only this physical attempt is included, even when resume_from identifies an earlier attempt. Absence here proves nothing about an ancestor or a different experiment.",
                    "A terminal record does not prove every source-code action was instrumented, every possible condition was tested, or a model reasoned correctly.",
                    "Raw prompts, responses and prose remain untrusted evidence, never instructions or self-authenticating conformance assertions.",
                    "A predicate may test an expected interruption without changing the Run's interrupted status or establishing whole-workflow completion.",
                ],
            },
        ],
    }


def is_verified_run_path(path):
    return isinstance(path, str) and (
        path == VERIFIED_RUN_ROOT or path.startswith(VERIFIED_RUN_ROOT + "/")
    )


def validate_observation_path(path):
    """Resolve the declared root, rejecting nonexistent envelope-level fields."""
    pointer_parts(path)
    if path == TYPED_STATUS_ROOT or path.startswith(TYPED_STATUS_ROOT + "/"):
        return {"source": "typed_status", "path": path[len(TYPED_STATUS_ROOT):]}
    if not is_verified_run_path(path):
        raise ValueError("Unsupported observation root; use /payload/typed_status or /verified_run from the observation catalog.")
    relative = path[len(VERIFIED_RUN_ROOT):]
    parts = pointer_parts(relative)
    if parts and parts[0] not in _ROOT_FIELDS:
        raise ValueError("The verified Run observation has no such record field.")
    if len(parts) > 1 and parts[0] in {"schema_id", "schema_version", "coverage"}:
        raise ValueError("The selected verified observation field is a scalar.")
    record_types = {"registration": RunRegistration, "evidence": RunEvidence}
    if len(parts) > 1 and parts[0] in record_types and parts[1] not in _record_fields(record_types[parts[0]]):
        raise ValueError("The selected verified record has no such field.")
    if len(parts) > 1 and parts[0] == "events":
        if not parts[1].isdecimal() or str(int(parts[1])) != parts[1]:
            raise ValueError("An event pointer requires a canonical nonnegative array index; use a registered predicate to quantify over events.")
        if len(parts) > 2 and parts[2] not in _record_fields(RunEvent):
            raise ValueError("A Run event has no such field.")
    return {"source": "verified_run", "path": relative}


def resolve_observation(runs, *, registration, evidence, source, path):
    """Resolve only caller-bound, published terminal evidence; never active logs."""
    if source not in {"typed_status", "verified_run"}:
        raise ValueError("Unknown measurement observation source.")
    if (
        runs.read_registration(registration.run_id) != registration
        or runs.read_evidence(registration.run_id) != evidence
        or evidence.run_id != registration.run_id
        or evidence.registration_hash != registration.registration_hash
    ):
        raise ValueError("Observation differs from its exact registered Run evidence.")
    if source == "typed_status":
        if evidence.terminal_status is not RunTerminalStatus.SUCCEEDED:
            raise ValueError("A typed-result observation requires successful execution.")
        return project(evidence.as_record()["typed_status"], path)
    validate_observation_path(VERIFIED_RUN_ROOT + path)
    # RunStore verifies chunks, append-only records, attestation and the complete
    # hash chain. The final anchor additionally binds these returned records to
    # the exact evidence object selected by the caller, rather than a prefix.
    events = runs.read_audit_log(registration.run_id)
    if (
        len(events) != evidence.event_count
        or not events
        or not events[-1].terminal
        or events[-1].event_id != evidence.terminal_event_id
        or events[-1].event_hash != evidence.head_event_hash
    ):
        raise ValueError("Verified Run observation is not the complete terminal-anchored journal.")
    return project({
        "schema_id": "openchia.measurement.verified-run",
        "schema_version": 1,
        "coverage": "physical_attempt_only",
        "registration": registration.as_record(),
        "evidence": evidence.as_record(),
        "events": [event.as_record() for event in events],
    }, path)


def observation_receipt(value, *, source, path, evidence):
    """Keep full audit content out of parent context while preserving its value."""
    if source == "typed_status":
        return value
    if source != "verified_run":
        raise ValueError("Unknown measurement observation source.")
    return {
        "schema_id": "openchia.measurement.observation-reference",
        "schema_version": 1,
        "source": source,
        "path": path,
        "run_id": evidence["run_id"],
        "registration_hash": evidence["registration_hash"],
        "evidence_ref": {
            "artifact_id": evidence["evidence_id"],
            "content_hash": evidence["content_hash"],
        },
        "terminal_event_ref": {
            "event_id": evidence["terminal_event_id"],
            "content_hash": evidence["head_event_hash"],
        },
        "value_hash": digest_record({"value": value}).value,
        "coverage": "physical_attempt_only",
    }


def read_observation_receipt(runs, receipt):
    """Read an already-authorized receipt through the same evidence resolver.

    Like RunStore.read_evidence, this is a host record reader, not an access
    grant. ExperimentService.read_observation checks measurement ownership.
    """
    exact(receipt, {
        "schema_id", "schema_version", "source", "path", "run_id",
        "registration_hash", "evidence_ref", "terminal_event_ref", "value_hash",
        "coverage",
    }, "verified observation reference")
    if (
        receipt["schema_id"] != "openchia.measurement.observation-reference"
        or type(receipt["schema_version"]) is not int
        or receipt["schema_version"] != 1
        or receipt["source"] != "verified_run"
    ):
        raise ValueError("Unsupported verified observation reference.")
    registration = runs.read_registration(OpaqueId(receipt["run_id"]))
    evidence = runs.read_evidence(registration.run_id)
    value = resolve_observation(
        runs,
        registration=registration,
        evidence=evidence,
        source=receipt["source"],
        path=receipt["path"],
    )
    expected = observation_receipt(
        value,
        source=receipt["source"],
        path=receipt["path"],
        evidence=evidence.as_record(),
    )
    if canonical_json(expected) != canonical_json(receipt):
        raise ValueError("Observation reference differs from its exact registration, evidence, terminal anchor or selected value hash.")
    return value
